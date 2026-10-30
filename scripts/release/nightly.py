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


def repository():
    """Use the repository that owns this workflow, including user clones."""
    repo = os.environ.get('GITHUB_REPOSITORY', REPO)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Invalid custom repository identity')
    return repo


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


def nightly_identity(data, release_mode=None, wayland='true', signing='false'):
    identity = dict(upstream_sha=data['upstream_sha'], patchset=data['patchset'],
                    common_patch_hash=data['common_patch_hash'], sos_patch_hash=data['sos_patch_hash'],
                    wayland=wayland, signing=signing,
                    wayland_policy_sha256=data.get('wayland_policy_sha256', '') if wayland == 'true' else '')
    if release_mode is not None:
        identity['release_mode'] = release_mode
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def route_state(rows, identity, release_mode='draft', wayland='true', current_run_id='', signing='false', upstream_sha=''):
    title_suffix = f' / {release_mode} / wayland={wayland} / android-signing={signing}'
    unresolved = [r for r in rows if r.get('_nightly_identity_unresolved')
                  and (r.get('_upstream_sha') == upstream_sha
                       or (not r.get('_upstream_sha') and r.get('display_title', '').startswith('Nightly latest /')))
                  and r.get('display_title', '').endswith(title_suffix)
                  and r['event'] == 'workflow_dispatch' and r['head_branch'] == 'main'
                  and str(r['id']) != str(current_run_id)]
    if any(r.get('status') != 'completed' for r in unresolved):
        return 'ACTIVE'
    if unresolved:
        return 'UNKNOWN'
    matched = [r for r in rows if r.get('_nightly_identity') == identity
               and r['display_title'].endswith(title_suffix)
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
    match = re.fullmatch(r'Nightly ([0-9a-f]{40}) / [0-9a-f]{40} / (?:dry-run|draft|release) / wayland=(?:true|false)(?: / android-signing=(?:true|false))?', title)
    if match:
        return match.group(1)
    match = re.fullmatch(r'Nightly ([1-9][0-9]*) / [0-9a-f]{40} / (?:dry-run|draft|release) / wayland=(?:true|false)(?: / android-signing=(?:true|false))?', title)
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
            result = subprocess.run(['gh', 'run', 'download', str(row['id']), '--repo', repository(),
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


def discovery_from_run(row):
    """Read the run's immutable discovery artifact, which records selected patch hashes."""
    if not row.get('id'):
        return None
    with tempfile.TemporaryDirectory(prefix='nightly-dedup-') as temp:
        artifact = f'nightly-discovery-{row["id"]}'
        result = subprocess.run(['gh', 'run', 'download', str(row['id']), '--repo', repository(),
                                 '--name', artifact, '--dir', temp], text=True, capture_output=True)
        if result.returncode != 0:
            return None
        candidates = list(Path(temp).rglob('nightly-discovery.json'))
        if len(candidates) != 1:
            return None
        try:
            data = json.loads(candidates[0].read_text())
        except (OSError, json.JSONDecodeError):
            return None
        required = ('upstream_sha', 'patchset', 'common_patch_hash', 'sos_patch_hash')
        if (not re.fullmatch(r'[0-9a-f]{40}', str(data.get('upstream_sha', '')))
                or not re.fullmatch(r'v[1-9][0-9]*', str(data.get('patchset', '')))
                or any(not re.fullmatch(r'[0-9a-f]{64}', str(data.get(key, ''))) for key in required[2:])):
            return None
        return data


def annotate_history(rows, upstream_sha=None):
    for row in rows:
        row['_upstream_sha'] = source_sha_from_run(row)
        title = row.get('display_title', '')
        if upstream_sha and row['_upstream_sha'] != upstream_sha and not title.startswith('Nightly latest /'):
            continue
        match = re.fullmatch(r'Nightly (?:[0-9a-f]{40}|[1-9][0-9]*|latest) / [0-9a-f]{40} / (dry-run|draft|release) / wayland=(true|false)(?: / android-signing=(true|false))?', title)
        if not match:
            continue
        data = discovery_from_run(row)
        if (not data or (row['_upstream_sha'] and data['upstream_sha'] != row['_upstream_sha'])
                or (upstream_sha and data and data['upstream_sha'] != upstream_sha)):
            row['_nightly_identity_unresolved'] = True
            continue
        row['_nightly_identity'] = nightly_identity(data, match.group(1), match.group(2), match.group(3) or 'false')
    return rows


def route(data):
    repo = repository()
    if (os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') not in ('schedule', 'workflow_dispatch')):
        raise ValueError('Nightly router requires trusted main context')
    rows = []
    for page in range(1, 11):
        batch = api(f'repos/{repo}/actions/workflows/nightly.yml/runs?event=workflow_dispatch&branch=main&per_page=100&page={page}')['workflow_runs']
        rows += batch
        if len(batch) < 100:
            break
    else:
        raise ValueError('Route history exhausted; refusing unsafe deduplication')
    signing = os.environ.get('ANDROID_PRODUCTION_SIGNING_ENABLED', 'false').lower()
    if signing not in ('true', 'false'):
        raise ValueError('Invalid Android signing toggle')
    identity_data = dict(data, wayland_policy_sha256=wayland_policy_hash(True))
    identity = nightly_identity(identity_data, 'draft', 'true', signing)
    annotate_history(rows, data['upstream_sha'])
    state = route_state(rows, identity, signing=signing, upstream_sha=data['upstream_sha'])
    print('Nightly route: ' + state)
    if state == 'EXHAUSTED':
        raise ValueError('Three attempts failed; inspect logs or dispatch manually')
    if state == 'UNKNOWN':
        raise ValueError('A matching Nightly run has no discovery artifact; inspect it before dispatching again')
    if state == 'RETRY':
        subprocess.run(['gh', 'workflow', 'run', 'nightly.yml', '--repo', repo, '--ref', 'main',
                        '-f', 'release_mode=draft',
                        '-f', 'include_wayland=true'], check=True)


def dedup():
    """Skip duplicate manual dispatches before preparation/build/signing begins."""
    repository()
    if (os.environ.get('GITHUB_REF') not in ('refs/heads/main', 'refs/heads/development')
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'):
        raise ValueError('Nightly dedup requires a trusted branch workflow_dispatch context')
    current = os.environ.get('GITHUB_RUN_ID', '')
    mode = os.environ.get('RELEASE_MODE', 'draft')
    wayland = os.environ.get('INCLUDE_WAYLAND', 'true').lower()
    signing = os.environ.get('ANDROID_PRODUCTION_SIGNING_ENABLED', 'false').lower()
    if mode not in ('dry-run', 'draft', 'release') or wayland not in ('true', 'false') or signing not in ('true', 'false'):
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
        batch = api(f'repos/{repository()}/actions/workflows/nightly.yml/runs?event=workflow_dispatch&branch=main&per_page=100&page={page}')['workflow_runs']
        rows += batch
        if len(batch) < 100:
            break
    else:
        raise ValueError('Nightly history exhausted; refusing unsafe deduplication')
    rows = prior_history(rows, current)
    identity_data = dict(upstream_sha=os.environ['UPSTREAM_EXPECTED_SHA'],
                         patchset=os.environ['PATCHSET'],
                         common_patch_hash=patch_hash('common', os.environ['PATCHSET']),
                         sos_patch_hash=patch_hash('sos', os.environ['PATCHSET']),
                         wayland_policy_sha256=wayland_policy_hash(wayland == 'true'))
    identity = nightly_identity(identity_data, mode, wayland, signing)
    annotate_history(rows, identity_data['upstream_sha'])
    state = route_state(rows, identity, mode, wayland, current, signing, identity_data['upstream_sha'])
    print('Nightly dedup: ' + state)
    if state == 'EXHAUSTED':
        raise ValueError('Three attempts failed for this exact source/build identity; inspect logs before retrying')
    if state == 'UNKNOWN':
        raise ValueError('A matching Nightly run has no discovery artifact; inspect it before retrying')
    skip = state in ('ACTIVE', 'SUCCESS')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('skip=' + str(skip).lower() + '\n')
            output.write('state=' + state + '\n')


def save(data):
    Path('.work').mkdir(exist_ok=True)
    data['wayland_policy_sha256'] = wayland_policy_hash(
        os.environ.get('INCLUDE_WAYLAND', 'true').lower() == 'true')
    Path('.work/nightly-discovery.json').write_text(json.dumps(data, indent=2) + '\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            for k, v in data.items():
                if '\n' in v or '\r' in v:
                    raise ValueError('Unsafe Nightly output')
                f.write(k + '=' + v + '\n')
    print(json.dumps(data, indent=2))


def wayland_policy_hash(enabled):
    if not enabled:
        return ''
    from scripts.platform.wayland import POLICY
    return hashlib.sha256(POLICY.read_bytes()).hexdigest()


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
    signing_required = os.environ.get('ANDROID_PRODUCTION_SIGNING_ENABLED', 'false').lower() == 'true'
    os.environ['REQUIRE_ANDROID_PRODUCTION_SIGNING'] = 'true' if signing_required and mode in ('draft', 'release') else 'false'
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
    if mode in ('draft', 'release') and signing_required and not signed:
        raise ValueError('Nightly draft/release requires all three production-signed Android targets with v2 and v3')
    report = qualify(root, 'nightly', False)
    if report['result'] != 'PASS':
        raise ValueError('Complete Nightly matrix required')
    report.update(official_run_id=data['official_run_id'], official_run_url=data['official_run_url'],
                  publication_authorized=mode == 'release', draft_authorized=mode in ('draft', 'release'), android_production_signing=signed)
    (ROOT / '.work/qualification-aggregate/nightly.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def require_draft_context():
    repo = repository()
    expected = {'GITHUB_REPOSITORY': repo, 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_WORKFLOW_REF': repo + '/.github/workflows/nightly.yml@refs/heads/main'}
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


def cleanup_superseded_nightly_releases(current_release_id, release_name):
    """Keep only the completed, canonical Nightly release for this channel."""
    from scripts.release.github import gh
    repo = repository()
    stale = []
    for page in range(1, 11):
        rows = api(f'repos/{repo}/releases?per_page=100&page={page}') or []
        stale.extend(r for r in rows
                     if str(r.get('id')) != str(current_release_id)
                     and r.get('prerelease') is True
                     and 'channel=nightly' in (r.get('body') or '').splitlines())
        if len(rows) < 100:
            break
    else:
        raise ValueError('Too many release pages to safely clean superseded Nightly releases')
    for release in stale:
        if release.get('immutable') is True:
            raise ValueError('A superseded Nightly release is immutable and cannot be removed')
        gh('api', '--method', 'DELETE', f'repos/{repo}/releases/{release["id"]}')
        if api(f'repos/{repo}/releases/{release["id"]}', missing=True) is not None:
            raise ValueError('Could not remove superseded Nightly release: ' + str(release.get('tag_name')))
        print('Removed superseded Nightly release: ' + str(release.get('tag_name')))


def delete_refresh_draft(existing):
    """Delete only the unchanged workflow-owned private Draft selected for refresh."""
    from scripts.release.github import gh
    require_draft_context()
    if (existing.get('draft') is not True or existing.get('prerelease') is not True
            or existing.get('immutable') is True
            or 'channel=nightly' not in (existing.get('body') or '').splitlines()
            or not re.fullmatch(r'[1-9][0-9]*',str(existing.get('id','')))):
        raise ValueError('Refusing to delete a non-owned, published or immutable Nightly release')
    path=f'repos/{repository()}/releases/{existing["id"]}'
    fresh=api(path,missing=True)
    fields=('id','draft','prerelease','immutable','tag_name','target_commitish','body','updated_at')
    if not fresh or any(fresh.get(key)!=existing.get(key) for key in fields):
        raise ValueError('Nightly Draft changed before deletion; refusing to delete')
    gh('api','--method','DELETE',path)
    if api(path,missing=True) is not None:
        raise ValueError('Old Nightly Draft still exists; refusing duplicate creation')
    print('Deleted prior private Nightly Draft: '+str(existing['id']))


def draft(root, discovery):
    from scripts.release.github import request, gh
    from scripts.release.production import scan_job_log
    require_draft_context()
    release_mode = os.environ['RELEASE_MODE']
    signing_required = os.environ.get('REQUIRE_ANDROID_PRODUCTION_SIGNING', 'false').lower() == 'true'
    report = aggregate(root, discovery)  # Revalidate downloaded binaries and signatures in write job.
    if report['result'] != 'PASS' or (signing_required and not report['android_production_signing']):
        raise ValueError('Incomplete signed Nightly aggregate')
    data = json.loads(discovery.read_text())
    repo = repository()
    release_name, upstream_notes = upstream_nightly_release()
    run_id = str(data['official_run_id'])
    if not re.fullmatch(r'[1-9][0-9]*', run_id):
        raise ValueError('Invalid official run identity')
    identity_data = dict(upstream_repository=OFFICIAL, upstream_sha=data['upstream_sha'],
                         patchset=data['patchset'],
                         common_patch_hash=patch_hash('common', data['patchset']),
                         sos_patch_hash=patch_hash('sos', data['patchset']),
                         wayland_included=os.environ.get('INCLUDE_WAYLAND', 'true').lower() == 'true',
                         wayland_policy_sha256=report.get('wayland', {}).get('policy_sha256', ''),
                         release_mode=release_mode,
                         signing='true' if signing_required else 'false')
    identity_source = dict(upstream_sha=identity_data['upstream_sha'],
                           patchset=identity_data['patchset'],
                           common_patch_hash=identity_data['common_patch_hash'],
                           sos_patch_hash=identity_data['sos_patch_hash'],
                           wayland_policy_sha256=identity_data['wayland_policy_sha256'])
    identity = nightly_identity(identity_source,
                                wayland=str(identity_data['wayland_included']).lower(),
                                signing=identity_data['signing'])
    tag = 'nightly'
    jobs_path = f'repos/{repo}/actions/runs/{os.environ["GITHUB_RUN_ID"]}/jobs?per_page=100'
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
            scan_job_log(job['id'], repo)
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
                'android_signing=' + ('PRODUCTION SIGNED / IDENTITY VERIFIED; APK v2 AND v3'
                                      if report['android_production_signing'] else 'NOT ENABLED'),
                'desktop_code_signing=NOT ENABLED', 'runtime_ui_validation=NOT TESTED',
                'real_remote_session=NOT TESTED', 'release_policy=' + ('PUBLIC NIGHTLY PRERELEASE; NOT STABLE' if release_mode == 'release' else 'DRAFT ONLY; NOT PUBLIC'),
                'automation_state=uploading']
    if identity_data['wayland_policy_sha256']:
        metadata.append('wayland_policy_sha256=' + identity_data['wayland_policy_sha256'])
    notes = (upstream_notes + '\n\n'
             '<!-- rustdesk-custom-release-metadata\n' + '\n'.join(metadata) + '\n-->\n')

    # The tag remains moving. Refresh private Drafts with a new Release identity;
    # published prereleases retain the explicitly authorized release-mode path.
    existing = api(f'repos/{repository()}/releases/tags/{tag}', missing=True)
    # Tag lookup may miss Draft/legacy records. Locate the workflow-owned
    # Nightly record by metadata before a guarded refresh.
    if not existing:
        matches = []
        for page in range(1, 11):
            rows = api(f'repos/{repository()}/releases?per_page=100&page={page}') or []
            matches.extend(r for r in rows
                           if r.get('prerelease') is True
                           and 'channel=nightly' in (r.get('body') or '').splitlines())
            if len(rows) < 100:
                break
        else:
            raise ValueError('Too many release pages to safely locate an existing Nightly release')
        if len(matches) > 1:
            raise ValueError('Multiple workflow-owned Nightly releases exist; refusing ambiguous replacement')
        existing = matches[0] if matches else None
    if existing and existing.get('immutable') is True:
        raise ValueError('The nightly release is immutable and cannot be refreshed')
    if existing and 'channel=nightly' not in (existing.get('body') or '').splitlines():
        raise ValueError('Refusing to replace a nightly-tag release not owned by this workflow')
    if existing:
        body = existing.get('body') or ''
        existing_ref = api(f'repos/{repository()}/git/ref/tags/{tag}', missing=True)
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
        remote_rows = api(f'repos/{repository()}/releases/{existing["id"]}/assets?per_page=100') or []
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
        if complete_match and existing.get('tag_name') == tag and release_mode == 'release':
            if existing.get('draft') is True:
                promoted_body = body.replace('release_policy=DRAFT ONLY; NOT PUBLIC',
                                             'release_policy=PUBLIC NIGHTLY PRERELEASE; NOT STABLE')
                promoted = request('PATCH', f'repos/{repository()}/releases/{existing["id"]}',
                                   dict(draft=False, prerelease=True, body=promoted_body))
                if promoted.get('draft') is not False or promoted.get('prerelease') is not True:
                    raise ValueError('Reused Nightly Draft promotion state mismatch')
            cleanup_superseded_nightly_releases(existing['id'], release_name)
            result = dict(tag=tag, release_id=existing['id'], draft=False, prerelease=True,
                          reused=True, workflow_run=os.environ['GITHUB_RUN_ID'], assets=expected)
            (ROOT / '.work/nightly-draft.json').write_text(json.dumps(result, indent=2) + '\n')
            print('Verified complete Nightly release: ' + tag)
            return result
    if existing and existing.get('draft') is True:
        # Restore a missing canonical ref before discarding the old Release identity.
        # Creating its replacement as a private Draft does not create a Git tag.
        if not api(f'repos/{repository()}/git/ref/tags/{tag}', missing=True):
            restored_ref = request('POST', f'repos/{repository()}/git/refs',
                                   dict(ref='refs/tags/' + tag, sha=os.environ['GITHUB_SHA']))
            if restored_ref.get('object', {}).get('sha') != os.environ['GITHUB_SHA']:
                raise ValueError('Nightly tag could not be recreated at the validated custom source commit')
        # All local package/signature/checksum/log gates above have passed.
        # Keep the Git ref; deleting the Release removes its old attachments.
        delete_refresh_draft(existing)
        existing = None
    elif existing and release_mode == 'draft':
        raise ValueError('Nightly is publicly released; Draft refresh must not hide or delete it')
    if existing:
        release_id = existing['id']
        if existing.get('tag_name') != tag:
            # Restore the canonical moving tag before reattaching the existing
            # release, so a missing ref cannot cause GitHub to mint another
            # untagged release during replacement.
            current_ref = api(f'repos/{repository()}/git/ref/tags/{tag}', missing=True)
            if current_ref:
                updated_ref = request('PATCH', f'repos/{repository()}/git/refs/tags/{tag}',
                                      dict(sha=os.environ['GITHUB_SHA'], force=True))
                if updated_ref.get('object', {}).get('sha') != os.environ['GITHUB_SHA']:
                    raise ValueError('Nightly tag did not move to the validated custom source commit')
            else:
                created_ref = request('POST', f'repos/{repository()}/git/refs',
                                      dict(ref='refs/tags/' + tag, sha=os.environ['GITHUB_SHA']))
                if created_ref.get('object', {}).get('sha') != os.environ['GITHUB_SHA']:
                    raise ValueError('Nightly tag could not be restored at the validated custom source commit')
        staged = request('PATCH', f'repos/{repository()}/releases/{release_id}',
                         dict(tag_name=tag, target_commitish=os.environ['GITHUB_SHA'],
                              name=release_name, body=notes, draft=True, prerelease=True))
        if staged.get('draft') is not True or staged.get('prerelease') is not True:
            raise ValueError('Could not hide existing Nightly release before replacing assets')
        old_assets = []
        for page in range(1, 11):
            page_assets = api(f'repos/{repository()}/releases/{release_id}/assets?per_page=100&page={page}') or []
            old_assets.extend(page_assets)
            if len(page_assets) < 100:
                break
        else:
            raise ValueError('Nightly release has too many asset pages; refusing incomplete replacement')
        for asset in old_assets:
            gh('api', '--method', 'DELETE', f'repos/{repository()}/releases/assets/{asset["id"]}')
        if api(f'repos/{repository()}/releases/{release_id}/assets?per_page=100'):
            raise ValueError('Could not clear prior Nightly assets before replacement')
    ref_path = f'repos/{repository()}/git/ref/tags/{tag}'
    ref_update_path = f'repos/{repository()}/git/refs/tags/{tag}'
    current_ref = api(ref_path, missing=True)
    if current_ref:
        if current_ref.get('object', {}).get('sha') != os.environ['GITHUB_SHA']:
            updated_ref = request('PATCH', ref_update_path, dict(sha=os.environ['GITHUB_SHA'], force=True))
            if updated_ref.get('object', {}).get('sha') != os.environ['GITHUB_SHA']:
                raise ValueError('Nightly tag did not move to the validated custom source commit')
    elif existing:
        created_ref = request('POST', f'repos/{repository()}/git/refs',
                              dict(ref='refs/tags/' + tag, sha=os.environ['GITHUB_SHA']))
        if created_ref.get('object', {}).get('sha') != os.environ['GITHUB_SHA']:
            raise ValueError('Nightly tag could not be recreated at the validated custom source commit')
    if not existing:
        created = request('POST', f'repos/{repository()}/releases',
                          dict(tag_name=tag, name=release_name,
                               target_commitish=os.environ['GITHUB_SHA'], body=notes,
                               draft=True, prerelease=True))
        if created.get('tag_name') != tag or created.get('target_commitish') != os.environ['GITHUB_SHA']:
            raise ValueError('Nightly release tag was not created at the validated custom source commit')
        release_id = created['id']
    else:
        release_id = existing['id']
    current_release = api(f'repos/{repository()}/releases/{release_id}')
    if current_release.get('tag_name') != tag or current_release.get('draft') is not True:
        raise ValueError('Nightly replacement release is not safely staged as a draft')
    gh('release', 'upload', tag, *map(str, files), '--repo', repository())
    for attempt in range(12):
        uploaded = {a['name']: {'size': a['size'], 'digest': a.get('digest')} for a in
                    (api(f'repos/{repository()}/releases/{release_id}/assets?per_page=100') or []) if a.get('state') == 'uploaded'}
        if uploaded == expected:
            break
        if attempt < 11:
            time.sleep(5)
    if uploaded != expected:
        raise ValueError('Incomplete Nightly upload/checksum verification; draft remains incomplete')
    # GitHub's Release date can follow the tag commit date even for a fresh object.
    # Record actual package verification time separately, without changing source identity.
    verified_at = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    completed_notes = (notes.replace('automation_state=uploading', 'automation_state=complete')
                       + f'\nLatest packages verified (UTC): `{verified_at}` · '
                       + f'[Actions run {os.environ["GITHUB_RUN_ID"]}]'
                       + f'(https://github.com/{repo}/actions/runs/{os.environ["GITHUB_RUN_ID"]})\n')
    # Publication is the final irreversible step, only after every signed asset digest matches.
    final = request('PATCH', f'repos/{repository()}/releases/{release_id}',
                    dict(tag_name=tag, target_commitish=os.environ['GITHUB_SHA'],
                         name=release_name, draft=release_mode != 'release', prerelease=True,
                         body=completed_notes))
    if final.get('draft') is not (release_mode != 'release') or final.get('prerelease') is not True:
        raise ValueError('Nightly release state mismatch')
    if final.get('tag_name') != tag:
        raise ValueError('Completed Nightly release does not use the canonical tag')
    cleanup_superseded_nightly_releases(release_id, release_name)
    result = dict(tag=tag, release_id=release_id, draft=release_mode != 'release', prerelease=True,
                  workflow_run=os.environ['GITHUB_RUN_ID'], assets=expected)
    (ROOT / '.work/nightly-draft.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Verified Nightly ' + release_mode + ' created: ' + tag)
    return result


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['resolve', 'route', 'dedup', 'aggregate', 'preflight', 'draft'])
    p.add_argument('--root', type=Path, default=Path('.work/all-targets'))
    p.add_argument('--tree', type=Path)
    p.add_argument('--discovery', type=Path, default=Path('.work/nightly-discovery.json'))
    a = p.parse_args(argv)
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
        data = discover()
        save(data)
        if a.mode == 'route':
            route(data)


if __name__ == '__main__':
    main()
