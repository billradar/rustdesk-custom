#!/usr/bin/env python3
"""Route the latest official Stable release to a complete private Draft build."""
import os
import re
import subprocess

from scripts.release.channel import release_preflight
from scripts.upstream.patchsets import patchset_for_version
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


def workflow_runs(tag, signing_enabled=False):
    """Find prior tag.yml dispatches for the release version and signing mode."""
    runs = []
    for page in range(1, 11):
        batch = api(f'repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs?branch=main&event=workflow_dispatch&per_page=100&page={page}') or {}
        runs.extend(batch.get('workflow_runs', []))
        if len(batch.get('workflow_runs', [])) < 100:
            current_title = f'Stable {tag} / draft / wayland=true / android-signing={str(signing_enabled).lower()}'
            legacy_signed_titles = (
                {f'Stable {tag} / draft / wayland=true', f'Stable {tag} / draft'}
                if signing_enabled else set())
            return [row for row in runs if row.get('head_branch') == 'main'
                    and row.get('event') == 'workflow_dispatch'
                    and row.get('display_title') in ({current_title} | legacy_signed_titles)]
    raise ValueError('Stable workflow run history exceeds lookup limit; manual review required')


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


def route():
    verify_context()
    data = discovery()
    completed_version = latest_completed_version()
    allow_same_version = (os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
                          and os.environ.get('ALLOW_SAME_VERSION', 'false').lower() == 'true')
    if (completed_version and version_tuple(data['version']) <= version_tuple(completed_version)
            and not allow_same_version):
        print(f"Official Stable version {data['version']} has not advanced beyond completed version {completed_version}; skip.")
        return
    if existing_build(data):
        print(f"Complete Stable build already exists for {data['upstream_tag']}; skip.")
        return

    signing_enabled = os.environ.get('ANDROID_PRODUCTION_SIGNING_ENABLED', 'false').lower() == 'true'
    state = run_state(workflow_runs(data['upstream_tag'], signing_enabled))
    if state == 'ACTIVE':
        print(f"A Stable Draft build is already active for {data['upstream_tag']}; skip.")
        return
    if state == 'EXHAUSTED':
        raise ValueError('Stable Draft retry budget exhausted; manual review required')

    dispatch(data['upstream_tag'])
    print(f"Dispatched Stable Draft build for {data['upstream_tag']}.")


if __name__ == '__main__':
    route()
