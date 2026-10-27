#!/usr/bin/env python3
"""Follow successful official Nightly runs; never infer source from its moving tag."""
import argparse
import base64
from datetime import datetime, timezone
import json
import hashlib
import time
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
try:
    import tomllib
except ImportError:
    import tomli as tomllib
from scripts.upstream.resolve import api
from scripts.upstream.patchsets import patchset_for_version, patch_hash

REPO = 'billradar/rustdesk-custom'
OFFICIAL = 'rustdesk/rustdesk'
ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / '.work/qualification-aggregate/assets'


def discover(run_id=''):
    branch = api(f'repos/{OFFICIAL}')['default_branch']
    if run_id:
        if not re.fullmatch(r'[1-9][0-9]*', str(run_id)):
            raise ValueError('Invalid official run ID')
        run = api(f'repos/{OFFICIAL}/actions/runs/{run_id}')
    else:
        rows = api(f'repos/{OFFICIAL}/actions/workflows/flutter-nightly.yml/runs?status=success&per_page=30')['workflow_runs']
        run = next((r for r in rows if r['head_branch'] == branch and r['event'] in ('schedule', 'workflow_dispatch')), None)
        if run is None:
            raise ValueError('No successful official Nightly run')
    if (run['status'] != 'completed' or run['conclusion'] != 'success'
            or run['head_branch'] != branch or run['event'] not in ('schedule', 'workflow_dispatch')
            or run['path'] != '.github/workflows/flutter-nightly.yml'
            or run['head_repository']['full_name'] != OFFICIAL):
        raise ValueError('Untrusted or incomplete official Nightly run')
    sha = run['head_sha']
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Invalid official source SHA')
    cargo = api(f'repos/{OFFICIAL}/contents/Cargo.toml?ref={sha}')
    version = tomllib.loads(base64.b64decode(cargo['content']).decode())['package']['version']
    patchset = patchset_for_version(version)
    return dict(channel='nightly', upstream_repository=OFFICIAL, upstream_sha=sha,
                upstream_ref=sha, upstream_tag='', upstream_version=version, patchset=patchset,
                official_run_id=str(run['id']), official_run_url=run['html_url'],
                common_patch_hash=patch_hash('common', patchset), sos_patch_hash=patch_hash('sos', patchset))


def discover_scheduled():
    """Wait for today's upstream scheduled Nightly, then bind to its completed SHA."""
    branch = api(f'repos/{OFFICIAL}')['default_branch']
    utc_day = datetime.now(timezone.utc).date().isoformat()
    deadline = time.monotonic() + 150 * 60
    while True:
        rows = api(f'repos/{OFFICIAL}/actions/workflows/flutter-nightly.yml/runs?per_page=100')['workflow_runs']
        run = next((r for r in rows if r.get('created_at', '').startswith(utc_day)
                    and r.get('head_branch') == branch and r.get('event') in ('schedule', 'workflow_dispatch')
                    and r.get('path') == '.github/workflows/flutter-nightly.yml'
                    and (r.get('head_repository') or {}).get('full_name') == OFFICIAL), None)
        if run:
            current = api(f'repos/{OFFICIAL}/actions/runs/{run["id"]}')
            if current.get('status') == 'completed':
                if current.get('conclusion') != 'success':
                    raise ValueError('Today\'s official Nightly run completed without success')
                return discover(str(run['id']))
            print(f'Waiting for today\'s official Nightly run {run["id"]} to complete')
        else:
            print('Waiting for today\'s official Nightly run to start')
        if time.monotonic() >= deadline:
            raise TimeoutError('Today\'s official Nightly did not complete within the routing window')
        time.sleep(60)


def route_state(rows, upstream_sha, custom_sha, release_mode='draft', wayland='true', current_run_id=''):
    matched = [r for r in rows if r.get('_upstream_sha') == upstream_sha and r['head_sha'] == custom_sha
               and r['display_title'].endswith(f' / {release_mode} / wayland={wayland}')
               and r['event'] == 'workflow_dispatch' and r['head_branch'] == 'main'
               and str(r['id']) != str(current_run_id)]
    if any(r['status'] != 'completed' for r in matched):
        return 'ACTIVE'
    if any(r['conclusion'] == 'success' for r in matched):
        return 'SUCCESS'
    return 'EXHAUSTED' if len(matched) >= 3 else 'RETRY'


def prior_history(rows, current_run_id=''):
    """Return only runs older than this run, excluding later queued dispatches."""
    if not current_run_id:
        return rows
    current = next((r for r in rows if str(r.get('id')) == str(current_run_id)), None)
    if current is None:
        raise ValueError('Current Nightly run is missing from workflow history; refusing unsafe deduplication')
    try:
        current_number = int(current['run_number'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('Current Nightly run has no valid run number; refusing unsafe deduplication')
    prior = []
    for row in rows:
        if str(row.get('id')) == str(current_run_id):
            continue
        try:
            if int(row['run_number']) < current_number:
                prior.append(row)
        except (KeyError, TypeError, ValueError):
            continue
    return prior


def source_sha_from_run(row):
    """Recover source identity for historical titles while migrating to SHA-based names."""
    title = row.get('display_title', '')
    match = re.fullmatch(r'Nightly ([0-9a-f]{40}) / [0-9a-f]{40} / (?:dry-run|draft|release) / wayland=(?:true|false)', title)
    if match:
        return match.group(1)
    match = re.fullmatch(r'Nightly ([1-9][0-9]*) / [0-9a-f]{40} / (?:dry-run|draft|release) / wayland=(?:true|false)', title)
    if match:
        try:
            return discover(match.group(1))['upstream_sha']
        except (ValueError, KeyError, urllib.error.HTTPError) as error:
            print(f"Nightly dedup: cannot recover historical official run {match.group(1)}: {error}")
            return ''
    # Older runs named "latest" retain a same-run discovery artifact. Read it
    # when available so migration does not rebuild a completed identical batch.
    if title.startswith('Nightly latest / ') and row.get('id'):
        with tempfile.TemporaryDirectory(prefix='nightly-dedup-') as temp:
            artifact = f'nightly-discovery-{row["id"]}'
            result = subprocess.run(['gh', 'run', 'download', str(row['id']), '--repo', REPO,
                                     '--name', artifact, '--dir', temp],
                                    text=True, capture_output=True)
            if result.returncode == 0:
                candidates = list(Path(temp).rglob('nightly-discovery.json'))
                if len(candidates) == 1:
                    data = json.loads(candidates[0].read_text())
                    sha = data.get('upstream_sha', '')
                    if re.fullmatch(r'[0-9a-f]{40}', sha):
                        return sha
    return ''


def annotate_history(rows):
    for row in rows:
        row['_upstream_sha'] = source_sha_from_run(row)
    return rows


def route(data):
    if (os.environ.get('GITHUB_REPOSITORY') != REPO or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') not in ('schedule', 'workflow_dispatch')):
        raise ValueError('Nightly router requires trusted main context')
    rows = []
    for page in range(1, 11):
        batch = api(f'repos/{REPO}/actions/workflows/nightly.yml/runs?event=workflow_dispatch&branch=main&per_page=100&page={page}')['workflow_runs']
        rows += batch
        if len(batch) < 100:
            break
    else:
        raise ValueError('Route history exhausted; refusing unsafe deduplication')
    annotate_history(rows)
    state = route_state(rows, data['upstream_sha'], os.environ['GITHUB_SHA'])
    print('Nightly route: ' + state)
    if state == 'EXHAUSTED':
        raise ValueError('Three attempts failed; inspect logs or dispatch manually')
    if state == 'RETRY':
        subprocess.run(['gh', 'workflow', 'run', 'nightly.yml', '--repo', REPO, '--ref', 'main',
                        '-f', 'official_run_id=' + data['official_run_id'],
                        '-f', 'expected_sha=' + data['upstream_sha'], '-f', 'release_mode=draft'], check=True)


def dedup():
    """Skip duplicate manual dispatches before preparation/build/signing begins."""
    if (os.environ.get('GITHUB_REPOSITORY') != REPO
            or os.environ.get('GITHUB_REF') not in ('refs/heads/main', 'refs/heads/development')
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'):
        raise ValueError('Nightly dedup requires a trusted branch workflow_dispatch context')
    current = os.environ.get('GITHUB_RUN_ID', '')
    mode = os.environ.get('RELEASE_MODE', 'draft')
    wayland = os.environ.get('INCLUDE_WAYLAND', 'true').lower()
    if mode not in ('dry-run', 'draft', 'release') or wayland not in ('true', 'false'):
        raise ValueError('Invalid Nightly dedup configuration')
    if os.environ['GITHUB_REF'] == 'refs/heads/development':
        if mode != 'dry-run':
            raise ValueError('Development Nightly runs are dry-run only')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                output.write('skip=false\nstate=RETRY\n')
        print('Nightly dedup: development dry-run is isolated from production history')
        return
    rows = []
    for page in range(1, 11):
        batch = api(f'repos/{REPO}/actions/workflows/nightly.yml/runs?event=workflow_dispatch&branch=main&per_page=100&page={page}')['workflow_runs']
        rows += batch
        if len(batch) < 100:
            break
    else:
        raise ValueError('Nightly history exhausted; refusing unsafe deduplication')
    rows = prior_history(rows, current)
    annotate_history(rows)
    state = route_state(rows, os.environ['UPSTREAM_EXPECTED_SHA'], os.environ['GITHUB_SHA'],
                        mode, wayland, current)
    print('Nightly dedup: ' + state)
    if state == 'EXHAUSTED':
        raise ValueError('Three attempts failed for this exact source/build identity; inspect logs before retrying')
    skip = state in ('ACTIVE', 'SUCCESS')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('skip=' + str(skip).lower() + '\n')
            output.write('state=' + state + '\n')


def save(data):
    Path('.work').mkdir(exist_ok=True)
    Path('.work/nightly-discovery.json').write_text(json.dumps(data, indent=2) + '\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            for k, v in data.items():
                if '\n' in v or '\r' in v:
                    raise ValueError('Unsafe Nightly output')
                f.write(k + '=' + v + '\n')
    print(json.dumps(data, indent=2))


def preflight(tree):
    from scripts.platform.platform_adapter import check
    from scripts.release.qualification import plan
    actual = subprocess.check_output(['git', '-C', str(tree), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != os.environ['UPSTREAM_EXPECTED_SHA']:
        raise ValueError('Nightly platform preflight source SHA mismatch')
    checked = set()
    errors = []
    for target in plan('nightly')['selected']:
        pair = (target['platform'], target['arch'])
        if pair[0] == 'windows' or pair in checked:
            continue  # Windows uses the separate build_adapter gate directly before this step.
        checked.add(pair)
        try:
            profile, _ = check(tree, *pair)
            if profile['runner'] != target['runner']:
                raise ValueError('Canonical native runner mismatch')
            print('Nightly platform preflight: ' + '/'.join(pair) + ' PASS')
        except ValueError as error:
            errors.append('/'.join(pair) + ': ' + str(error))
    if errors:
        raise ValueError('Nightly platform review required before native dependencies: ' + '; '.join(errors))


def aggregate(root, discovery):
    from scripts.release.qualification import aggregate as qualify
    data = json.loads(discovery.read_text())
    required = dict(channel='nightly', upstream_sha=os.environ['UPSTREAM_EXPECTED_SHA'],
                    upstream_version=os.environ['UPSTREAM_VERSION'], patchset=os.environ['PATCHSET'],
                    upstream_repository=OFFICIAL)
    if any(data.get(k) != v for k, v in required.items()):
        raise ValueError('Nightly discovery identity mismatch')
    mode = os.environ.get('RELEASE_MODE', 'dry-run')
    if mode not in ('dry-run', 'draft', 'release'):
        raise ValueError('Unsupported Nightly release mode')
    os.environ['REQUIRE_ANDROID_PRODUCTION_SIGNING'] = 'true' if mode in ('draft', 'release') else 'false'
    infos = []
    for p in root.rglob('build-info.json'):
        info = json.loads(p.read_text())
        infos.append(info)
        expected = dict(required, custom_repository_sha=os.environ['GITHUB_SHA'],
                        common_patch_hash=patch_hash('common', data['patchset']))
        expected.pop('upstream_repository')
        for k, v in expected.items():
            if info.get(k) != v:
                raise ValueError('Nightly artifact identity mismatch: ' + k)
        if str(info['build_run']) != os.environ['GITHUB_RUN_ID']:
            raise ValueError('Nightly artifacts must be from this exact run')
        if info.get('upstream_tag'):
            raise ValueError('Nightly must not claim a Stable tag')
    android = [i for i in infos if i.get('platform') == 'android']
    signed = len(android) == 3 and all(i.get('signed_status') == 'PRODUCTION SIGNED / IDENTITY VERIFIED' and i.get('signing_identity_verified') is True and {2, 3}.issubset(set(i.get('signing_schemes', []))) for i in android)
    if mode in ('draft', 'release') and not signed:
        raise ValueError('Nightly draft/release requires all three production-signed Android targets with v2 and v3')
    report = qualify(root, 'nightly', False)
    if report['result'] != 'PASS':
        raise ValueError('Complete Nightly matrix required')
    report.update(official_run_id=data['official_run_id'], official_run_url=data['official_run_url'],
                  publication_authorized=mode == 'release', draft_authorized=mode in ('draft', 'release'), android_production_signing=signed)
    (ROOT / '.work/qualification-aggregate/nightly.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def require_draft_context():
    expected = {'GITHUB_REPOSITORY': REPO, 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_WORKFLOW_REF': REPO + '/.github/workflows/nightly.yml@refs/heads/main'}
    if any(os.environ.get(k) != v for k, v in expected.items()) or os.environ.get('RELEASE_MODE') not in ('draft', 'release'):
        raise ValueError('Nightly release writes require the protected main workflow and qualified mode')


def upstream_nightly_release():
    """Return the official Nightly title and visible release notes verbatim."""
    release = api(f'repos/{OFFICIAL}/releases/tags/nightly')
    name = release.get('name') or 'nightly'
    body = release.get('body') or ''
    if not body.strip():
        raise ValueError('Official upstream Nightly release description is unavailable')
    return name, body.rstrip()


def draft(root, discovery):
    from scripts.release.github import request, gh
    from scripts.release.production import scan_job_log
    require_draft_context()
    release_mode = os.environ['RELEASE_MODE']
    report = aggregate(root, discovery)  # Revalidate downloaded binaries and signatures in write job.
    if report['result'] != 'PASS' or not report['android_production_signing']:
        raise ValueError('Incomplete signed Nightly aggregate')
    data = json.loads(discovery.read_text())
    release_name, upstream_notes = upstream_nightly_release()
    run_id = str(data['official_run_id'])
    if not re.fullmatch(r'[1-9][0-9]*', run_id):
        raise ValueError('Invalid official run identity')
    identity_data = dict(upstream_repository=OFFICIAL, upstream_sha=data['upstream_sha'],
                         custom_sha=os.environ['GITHUB_SHA'], patchset=data['patchset'],
                         common_patch_hash=patch_hash('common', data['patchset']),
                         sos_patch_hash=patch_hash('sos', data['patchset']),
                         wayland_included=os.environ.get('INCLUDE_WAYLAND', 'true').lower() == 'true',
                         build_profile='production-signed',
                         wayland_policy=report.get('wayland', {}).get('policy_sha256'))
    identity = hashlib.sha256(json.dumps(identity_data, sort_keys=True).encode()).hexdigest()
    tag = 'nightly'
    jobs_path = f'repos/{REPO}/actions/runs/{os.environ["GITHUB_RUN_ID"]}/jobs?per_page=100'
    for attempt in range(5):
        try:
            jobs = api(jobs_path)['jobs']
            break
        except urllib.error.HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504) or attempt == 4:
                raise
            delay = min(2 ** attempt, 16)
            print(f'GitHub Actions jobs API returned HTTP {error.code}; retrying in {delay}s')
            time.sleep(delay)
    for job in jobs:
        if job['status'] == 'completed' and job['conclusion'] == 'success':
            scan_job_log(job['id'])
    files = sorted(p for p in ASSETS.iterdir() if p.is_file())
    if any(p.suffix.lower() == '.json' or p.name.startswith(('source-', 'build-info-')) for p in files):
        raise ValueError('Non-public metadata in Nightly release assets')
    if len({p.name for p in files}) != len(files):
        raise ValueError('Duplicate Nightly asset names')
    if not files or not (ASSETS / 'SHA256SUMS').is_file():
        raise ValueError('Nightly public package inventory missing')
    expected = {p.name: {'size': p.stat().st_size, 'digest': 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest()} for p in files}
    checksum_lines = (ASSETS / 'SHA256SUMS').read_text().splitlines()
    checksum_expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.name != 'SHA256SUMS'}
    checksum_actual = {}
    for line in checksum_lines:
        match = re.fullmatch(r'([0-9a-f]{64})  ([^/\\\\]+)', line)
        if not match or match.group(2) in checksum_actual:
            raise ValueError('Malformed or duplicate Nightly checksum entry')
        checksum_actual[match.group(2)] = match.group(1)
    if checksum_actual != checksum_expected:
        raise ValueError('Nightly SHA256SUMS does not match public assets')
    metadata = [f'channel=nightly', 'nightly_identity=' + identity,
                'upstream_repository=' + OFFICIAL, 'upstream_sha=' + data['upstream_sha'],
                'official_run_id=' + run_id, 'official_run_url=' + data['official_run_url'],
                'custom_repository_sha=' + os.environ['GITHUB_SHA'], 'build_run=' + os.environ['GITHUB_RUN_ID'],
                'patchset=' + data['patchset'], 'common_patch_hash=' + identity_data['common_patch_hash'],
                'sos_patch_hash=' + identity_data['sos_patch_hash'],
                'wayland_included=' + str(identity_data['wayland_included']).lower(),
                'asset_inventory=' + json.dumps(sorted(expected)),
                'android_signing=PRODUCTION SIGNED / IDENTITY VERIFIED; APK v2 AND v3',
                'desktop_code_signing=NOT ENABLED', 'runtime_ui_validation=NOT TESTED',
                'real_remote_session=NOT TESTED', 'release_policy=' + ('PUBLIC NIGHTLY PRERELEASE; NOT STABLE' if release_mode == 'release' else 'DRAFT ONLY; NOT PUBLIC'),
                'automation_state=uploading']
    if identity_data['wayland_policy']:
        metadata.append('wayland_policy_sha256=' + identity_data['wayland_policy'])
    notes = (upstream_notes + '\n\n'
             '<!-- rustdesk-custom-release-metadata\n' + '\n'.join(metadata) + '\n-->\n')

    # A single moving release is intentional. Hide an existing published
    # prerelease during replacement so consumers never see a mixed asset set.
    existing = api(f'repos/{REPO}/releases/tags/{tag}', missing=True)
    if existing and existing.get('immutable') is True:
        raise ValueError('The nightly release is immutable and cannot be refreshed')
    if existing and 'channel=nightly' not in (existing.get('body') or '').splitlines():
        raise ValueError('Refusing to replace a nightly-tag release not owned by this workflow')
    if existing:
        body = existing.get('body') or ''
        existing_ref = api(f'repos/{REPO}/git/ref/tags/{tag}', missing=True)
        tag_matches_source = (existing_ref or {}).get('object', {}).get('sha') == os.environ['GITHUB_SHA']
        expected_metadata = [
            'nightly_identity=' + identity,
            'upstream_repository=' + OFFICIAL,
            'upstream_sha=' + data['upstream_sha'],
            'custom_repository_sha=' + os.environ['GITHUB_SHA'],
            'patchset=' + data['patchset'],
            'common_patch_hash=' + identity_data['common_patch_hash'],
            'sos_patch_hash=' + identity_data['sos_patch_hash'],
            'wayland_included=' + str(identity_data['wayland_included']).lower(),
            'automation_state=complete',
        ]
        remote_rows = api(f'repos/{REPO}/releases/{existing["id"]}/assets?per_page=100') or []
        remote = {a['name']: {'size': a['size'], 'digest': a.get('digest')}
                  for a in remote_rows if a.get('state') == 'uploaded'}
        inventory_line = next((line for line in body.splitlines() if line.startswith('asset_inventory=')), '')
        try:
            prior_inventory = json.loads(inventory_line.split('=', 1)[1])
        except (IndexError, json.JSONDecodeError):
            prior_inventory = None
        complete_match = (
            existing.get('prerelease') is True
            and existing.get('name') == release_name
            and body.startswith(upstream_notes + '\n\n<!-- rustdesk-custom-release-metadata')
            and tag_matches_source
            and all(value in set(body.splitlines()) for value in expected_metadata)
            and len(remote) == len(remote_rows)
            and prior_inventory == sorted(expected)
            and remote == expected
        )
        if complete_match and release_mode == 'draft' and existing.get('draft') is True:
            result = dict(tag=tag, release_id=existing['id'], draft=True, prerelease=True,
                          reused=True, workflow_run=os.environ['GITHUB_RUN_ID'], assets=expected)
            (ROOT / '.work/nightly-draft.json').write_text(json.dumps(result, indent=2) + '\n')
            print('Exact complete Nightly Draft already exists: ' + tag)
            return result
        if complete_match and release_mode == 'release':
            if existing.get('draft') is True:
                promoted_body = body.replace('release_policy=DRAFT ONLY; NOT PUBLIC',
                                             'release_policy=PUBLIC NIGHTLY PRERELEASE; NOT STABLE')
                promoted = request('PATCH', f'repos/{REPO}/releases/{existing["id"]}',
                                   dict(draft=False, prerelease=True, body=promoted_body))
                if promoted.get('draft') is not False or promoted.get('prerelease') is not True:
                    raise ValueError('Reused Nightly Draft promotion state mismatch')
            result = dict(tag=tag, release_id=existing['id'], draft=False, prerelease=True,
                          reused=True, workflow_run=os.environ['GITHUB_RUN_ID'], assets=expected)
            (ROOT / '.work/nightly-draft.json').write_text(json.dumps(result, indent=2) + '\n')
            print('Verified complete Nightly release: ' + tag)
            return result
    if existing:
        release_id = existing['id']
        staged = request('PATCH', f'repos/{REPO}/releases/{release_id}',
                         dict(tag_name=tag, target_commitish=os.environ['GITHUB_SHA'],
                              name=release_name, body=notes, draft=True, prerelease=True))
        if staged.get('draft') is not True or staged.get('prerelease') is not True:
            raise ValueError('Could not hide existing Nightly release before replacing assets')
        old_assets = []
        for page in range(1, 11):
            page_assets = api(f'repos/{REPO}/releases/{release_id}/assets?per_page=100&page={page}') or []
            old_assets.extend(page_assets)
            if len(page_assets) < 100:
                break
        else:
            raise ValueError('Nightly release has too many asset pages; refusing incomplete replacement')
        for asset in old_assets:
            gh('api', '--method', 'DELETE', f'repos/{REPO}/releases/assets/{asset["id"]}')
        if api(f'repos/{REPO}/releases/{release_id}/assets?per_page=100'):
            raise ValueError('Could not clear prior Nightly assets before replacement')
    ref_path = f'repos/{REPO}/git/ref/tags/{tag}'
    ref_update_path = f'repos/{REPO}/git/refs/tags/{tag}'
    current_ref = api(ref_path, missing=True)
    if current_ref:
        if current_ref.get('object', {}).get('sha') != os.environ['GITHUB_SHA']:
            updated_ref = request('PATCH', ref_update_path, dict(sha=os.environ['GITHUB_SHA'], force=True))
            if updated_ref.get('object', {}).get('sha') != os.environ['GITHUB_SHA']:
                raise ValueError('Nightly tag did not move to the validated custom source commit')
    elif existing:
        created_ref = request('POST', f'repos/{REPO}/git/refs',
                              dict(ref='refs/tags/' + tag, sha=os.environ['GITHUB_SHA']))
        if created_ref.get('object', {}).get('sha') != os.environ['GITHUB_SHA']:
            raise ValueError('Nightly tag could not be recreated at the validated custom source commit')
    if not existing:
        created = request('POST', f'repos/{REPO}/releases',
                          dict(tag_name=tag, name=release_name,
                               target_commitish=os.environ['GITHUB_SHA'], body=notes,
                               draft=True, prerelease=True))
        if created.get('tag_name') != tag or created.get('target_commitish') != os.environ['GITHUB_SHA']:
            raise ValueError('Nightly release tag was not created at the validated custom source commit')
        release_id = created['id']
    else:
        release_id = existing['id']
    current_release = api(f'repos/{REPO}/releases/{release_id}')
    if current_release.get('tag_name') != tag or current_release.get('draft') is not True:
        raise ValueError('Nightly replacement release is not safely staged as a draft')
    gh('release', 'upload', tag, *map(str, files), '--repo', REPO)
    for attempt in range(12):
        uploaded = {a['name']: {'size': a['size'], 'digest': a.get('digest')} for a in
                    (api(f'repos/{REPO}/releases/{release_id}/assets?per_page=100') or []) if a.get('state') == 'uploaded'}
        if uploaded == expected:
            break
        if attempt < 11:
            time.sleep(5)
    if uploaded != expected:
        raise ValueError('Incomplete Nightly upload/checksum verification; draft remains incomplete')
    # Publication is the final irreversible step, only after every signed asset digest matches.
    final = request('PATCH', f'repos/{REPO}/releases/{release_id}',
                    dict(tag_name=tag, target_commitish=os.environ['GITHUB_SHA'],
                         name=release_name, draft=release_mode != 'release', prerelease=True,
                         body=notes.replace('automation_state=uploading', 'automation_state=complete')))
    if final.get('draft') is not (release_mode != 'release') or final.get('prerelease') is not True:
        raise ValueError('Nightly release state mismatch')
    result = dict(tag=tag, release_id=release_id, draft=release_mode != 'release', prerelease=True,
                  workflow_run=os.environ['GITHUB_RUN_ID'], assets=expected)
    (ROOT / '.work/nightly-draft.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Verified Nightly ' + release_mode + ' created: ' + tag)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['resolve', 'route', 'dedup', 'aggregate', 'preflight', 'draft'])
    p.add_argument('--official-run-id', default='')
    p.add_argument('--expected-sha', default='')
    p.add_argument('--root', type=Path, default=Path('.work/all-targets'))
    p.add_argument('--tree', type=Path)
    p.add_argument('--discovery', type=Path, default=Path('.work/nightly-discovery.json'))
    a = p.parse_args()
    if a.mode == 'preflight':
        if a.tree is None:
            p.error('preflight requires --tree')
        preflight(a.tree)
    elif a.mode == 'draft':
        draft(a.root, a.discovery)
    elif a.mode == 'dedup':
        dedup()
    elif a.mode == 'aggregate':
        aggregate(a.root, a.discovery)
    else:
        if a.mode == 'route' and os.environ.get('GITHUB_EVENT_NAME') == 'schedule':
            data = discover_scheduled()
        else:
            data = discover(a.official_run_id)
        if a.expected_sha and a.expected_sha != data['upstream_sha']:
            raise ValueError('Official run/source SHA mismatch')
        save(data)
        if a.mode == 'route':
            route(data)
