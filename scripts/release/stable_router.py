#!/usr/bin/env python3
"""Route the latest official Stable release to a complete private Draft build."""
import os
import json
from pathlib import Path
import tempfile
import re
import subprocess
import sys

from scripts.release.router_retry_policy import decide
from scripts.release.coordinator_lite import from_hashes as lite_identity
from scripts.release.channel import build_identity, release_preflight, wayland_identity
from scripts.upstream.patchsets import patch_hash, patchset_for_version
from scripts.upstream.resolve import api, choose_stable

REPOSITORY = 'billradar/rustdesk-custom'
WORKFLOW = 'tag.yml'
MAX_ATTEMPTS = 3


def verify_context():
    """Only allow scheduled/manual routing from the trusted main branch."""
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise ValueError('Stable router may only run in the release repository')
    if os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('Stable router may only dispatch from main')
    if os.environ.get('GITHUB_EVENT_NAME') not in ('schedule', 'workflow_dispatch'):
        raise ValueError('Unsupported Stable router trigger')
    if not re.fullmatch(r'[0-9a-f]{40}', os.environ.get('GITHUB_SHA', '')):
        raise ValueError('Stable router requires an exact custom repository SHA')


def discovery():
    release = choose_stable()
    data = {
        'channel': 'stable',
        'upstream_tag': release['upstream_tag'],
        'upstream_ref': release['upstream_tag'],
        'upstream_sha': release['upstream_sha'],
        'version': release['version'],
        'patchset': patchset_for_version(release['version']),
    }
    return data


def version_tuple(value):
    match = re.fullmatch(r'v?([0-9]+)\.([0-9]+)\.([0-9]+)', str(value))
    if not match:
        raise ValueError('Stable router received an invalid numeric version')
    return tuple(int(part) for part in match.groups())


def latest_completed_version():
    """Return the newest Stable version with a completed downstream release record."""
    rows = []
    for page in range(1, 101):
        batch = api(f'repos/{REPOSITORY}/releases?per_page=100&page={page}') or []
        rows.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError('Stable release pagination limit reached; refusing version routing')

    completed = []
    tag_pattern = re.compile(r'^v([0-9]+\.[0-9]+\.[0-9]+)-custom\.v[1-9][0-9]*\.[1-9][0-9]{0,5}$')
    for row in rows:
        if row.get('prerelease'):
            continue
        tag = row.get('tag_name') or row.get('name') or ''
        match = tag_pattern.fullmatch(tag)
        if not match:
            continue
        body = row.get('body') or ''
        if ('Automation-State: complete' not in body
                and 'automation_state=complete' not in body
                and 'automation_state=published' not in body):
            continue
        assets = {item.get('name') for item in row.get('assets', [])
                  if item.get('state') == 'uploaded' and item.get('size', 0) > 0}
        if 'SHA256SUMS' not in assets:
            continue
        completed.append(match.group(1))
    return max(completed, key=version_tuple) if completed else None


def existing_build(data):
    """Use the downstream release gate as the sole authority for reuse."""
    os.environ['INCLUDE_WAYLAND'] = 'true'
    return not release_preflight(data)['build_needed']


def recorded_identity(row):
    """Recover automatically computed identity from the run's latest lock attempt."""
    run_id = str(row.get('id', ''))
    if not re.fullmatch(r'[1-9][0-9]*', run_id):
        raise ValueError('Stable run identity missing; manual review required')
    with tempfile.TemporaryDirectory(prefix='stable-dedup-') as temp:
        result = subprocess.run(['gh', 'run', 'download', run_id, '--repo', REPOSITORY,
                                 '--pattern', f'stable-build-lock-{run_id}-*', '--dir', temp],
                                text=True, capture_output=True)
        candidates = []
        for path in Path(temp).glob('stable-build-lock-*/stable-lock.json'):
            match = re.fullmatch(r'stable-build-lock-' + run_id + r'-([1-9][0-9]*)', path.parent.name)
            if match:
                candidates.append((int(match.group(1)), path))
        if result.returncode != 0 or not candidates:
            raise ValueError('Stable build lock unavailable; manual review required')
        data = json.loads(max(candidates)[1].read_text())
    from scripts.release.stable_lock import SCHEMA
    if (data.get('schema') != SCHEMA or data.get('channel') != 'stable'
            or data.get('workflow_run') != run_id
            or data.get('custom_repository_sha') != row.get('head_sha')
            or type(data.get('wayland_included')) is not bool
            or type(data.get('android_signing_enabled')) is not bool):
        raise ValueError('Invalid historical Stable lock provenance')
    for key, size in (('upstream_sha', 40), ('common_patch_hash', 64), ('sos_patch_hash', 64)):
        if not re.fullmatch('[0-9a-f]{' + str(size) + '}', str(data.get(key, ''))):
            raise ValueError('Invalid historical Stable source identity')
    if data.get('patchset') != patchset_for_version(data.get('version', '')):
        raise ValueError('Invalid historical Stable patchset')
    identity = build_identity(data['upstream_sha'], data['patchset'], data['common_patch_hash'],
                              data['sos_patch_hash'], wayland_included=data['wayland_included'],
                              wayland_policy_sha256=data.get('wayland_policy_sha256', ''),
                              android_signing_enabled=data['android_signing_enabled'])
    if data.get('build_identity') != identity:
        raise ValueError('Invalid historical Stable build identity')
    return lite_identity(data['upstream_sha'], data['common_patch_hash'], data['sos_patch_hash'])


def workflow_runs(tag, identity, signing_enabled=False, prior_run_number=None):
    """Find matching locked batches; unknown active dispatches block duplicate work."""
    runs = []
    for page in range(1, 11):
        batch = api(f'repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs?branch=main&event=workflow_dispatch&per_page=100&page={page}') or {}
        runs.extend(batch.get('workflow_runs', []))
        if len(batch.get('workflow_runs', [])) < 100:
            break
    else:
        raise ValueError('Stable workflow run history exceeds lookup limit; manual review required')
    # Active matches have no completed lock yet. Match by requested source
    # (or conservative 'latest') regardless of mode/Wayland/signing.
    selected = []
    candidates = {tag, tag.lstrip('v'), 'v' + tag.lstrip('v'), 'latest'}
    for row in runs:
        if row.get('head_branch') != 'main' or row.get('event') != 'workflow_dispatch':
            continue
        if prior_run_number is not None:
            try:
                number = int(row['run_number'])
            except (KeyError, ValueError, TypeError) as error:
                raise ValueError('Historical Stable run number unavailable') from error
            if number >= prior_run_number:
                continue
        parts = row.get('display_title', '').split(' / ')
        if (len(parts) < 4 or not parts[0].startswith('Stable ')
                or parts[0][len('Stable '):] not in candidates
                or parts[1] not in ('dry-run', 'draft', 'release')
                or parts[2] not in ('wayland=true', 'wayland=false')
                or parts[3] not in ('android-signing=true', 'android-signing=false')):
            continue
        if row.get('status') != 'completed':
            selected.append(row)
        elif recorded_identity(row) == identity:
            selected.append(row)
    return selected

def run_state(rows):
    if any(row.get('status') != 'completed' for row in rows):
        return 'ACTIVE'
    return 'EXHAUSTED' if len(rows) >= MAX_ATTEMPTS else 'RETRY'


def dispatch(tag):
    subprocess.run([
        'gh', 'workflow', 'run', WORKFLOW,
        '--repo', REPOSITORY,
        '--ref', 'main',
        '-f', f'upstream_ref={tag}',
        '-f', 'release_mode=draft',
        '-f', 'include_wayland=true',
    ], check=True)


def dedup():
    """Admit only the oldest matching Stable workflow dispatch before any build."""
    if (os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_REPOSITORY') != REPOSITORY):
        raise ValueError('Stable Lite admission requires main workflow_dispatch')
    try:
        number = int(os.environ['GITHUB_RUN_NUMBER'])
    except (KeyError, ValueError) as error:
        raise ValueError('Stable run number unavailable') from error
    if number < 1:
        raise ValueError('Invalid Stable run number')
    locked = json.loads(Path('.work/stable-lock.json').read_text())
    if (str(locked.get('workflow_run')) != os.environ.get('GITHUB_RUN_ID')
            or locked.get('custom_repository_sha') != os.environ.get('GITHUB_SHA')
            or locked.get('channel') != 'stable'):
        raise ValueError('Stable Lite lock provenance mismatch')
    identity = lite_identity(locked['upstream_sha'], locked['common_patch_hash'],
                             locked['sos_patch_hash'])
    rows = workflow_runs(locked['upstream_tag'], identity, prior_run_number=number)
    state = decide(rows)
    if state == 'REVIEW':
        raise ValueError('Stable Lite uncertain historical run requires manual review')
    mode = os.environ.get('RELEASE_MODE', 'draft')
    if mode not in ('draft', 'dry-run', 'release'):
        raise ValueError('Invalid Stable release mode')
    # Release can publish a verified prior draft; it must not rebuild an active one.
    skip = state in ('ACTIVE', 'COOLDOWN') or (state == 'SUCCESS' and mode != 'release')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('skip=' + str(skip).lower() + '\n')
    print('Stable Lite admission: ' + state + (' / skip' if skip else ' / continue'))

def route():
    verify_context()
    data = discovery()
    # Rebuild eligibility is determined by upstream+patchset, not release
    # version alone: a changed patchset on the same upstream is a new build.
    identity = lite_identity(data['upstream_sha'],
                             patch_hash('common', data['patchset']),
                             patch_hash('sos', data['patchset']))
    matches = workflow_runs(data['upstream_tag'], identity)
    state = decide(matches)
    if state in ('ACTIVE', 'SUCCESS', 'COOLDOWN'):
        print(f"Stable matching build state={state}; skip.")
        return
    if state == 'REVIEW':
        raise ValueError('Stable retry requires manual review (cancelled, unknown, or exhausted)')
    if existing_build(data):
        print(f"Complete Stable build already exists for {data['upstream_tag']}; skip.")
        return

    dispatch(data['upstream_tag'])
    print(f"Dispatched Stable Draft build for {data['upstream_tag']}.")


if __name__ == '__main__':
    if sys.argv[1:] == ['dedup']:
        dedup()
    elif not sys.argv[1:]:
        route()
    else:
        raise SystemExit('Usage: stable_router.py [dedup]')
