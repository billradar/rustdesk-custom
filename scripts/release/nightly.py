#!/usr/bin/env python3
"""Follow successful official Nightly runs; never infer source from its moving tag."""
import argparse
import base64
import json
import hashlib
import time
import os
from pathlib import Path
import re
import subprocess
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


def route_state(rows, run_id, custom_sha):
    title = f'Nightly {run_id} / {custom_sha} / draft / wayland=true'
    matched = [r for r in rows if r['display_title'] == title and r['head_sha'] == custom_sha
               and r['event'] == 'workflow_dispatch' and r['head_branch'] == 'main']
    if any(r['status'] != 'completed' for r in matched):
        return 'ACTIVE'
    if any(r['conclusion'] == 'success' for r in matched):
        return 'SUCCESS'
    return 'EXHAUSTED' if len(matched) >= 3 else 'RETRY'


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
    state = route_state(rows, data['official_run_id'], os.environ['GITHUB_SHA'])
    print('Nightly route: ' + state)
    if state == 'EXHAUSTED':
        raise ValueError('Three attempts failed; inspect logs or dispatch manually')
    if state == 'RETRY':
        subprocess.run(['gh', 'workflow', 'run', 'nightly.yml', '--repo', REPO, '--ref', 'main',
                        '-f', 'official_run_id=' + data['official_run_id'],
                        '-f', 'expected_sha=' + data['upstream_sha'], '-f', 'release_mode=draft'], check=True)


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
    if mode not in ('dry-run', 'draft'):
        raise ValueError('Unsupported Nightly release mode')
    os.environ['REQUIRE_ANDROID_PRODUCTION_SIGNING'] = 'true' if mode == 'draft' else 'false'
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
    if mode == 'draft' and not signed:
        raise ValueError('Nightly draft requires all three production-signed Android targets with v2 and v3')
    report = qualify(root, 'nightly', False)
    if report['result'] != 'PASS':
        raise ValueError('Complete Nightly matrix required')
    report.update(official_run_id=data['official_run_id'], official_run_url=data['official_run_url'],
                  publication_authorized=False, draft_authorized=mode == 'draft', android_production_signing=signed)
    Path('.work/qualification-aggregate/nightly.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def require_draft_context():
    expected = {'GITHUB_REPOSITORY': REPO, 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'workflow_dispatch', 'RELEASE_MODE': 'draft',
                'GITHUB_WORKFLOW_REF': REPO + '/.github/workflows/nightly.yml@refs/heads/main'}
    if any(os.environ.get(k) != v for k, v in expected.items()):
        raise ValueError('Nightly draft writes require the protected main draft workflow')


def draft(root, discovery):
    from scripts.release.github import request, gh
    from scripts.release.production import scan_job_log
    require_draft_context()
    report = aggregate(root, discovery)  # Revalidate downloaded binaries and signatures in write job.
    if report['result'] != 'PASS' or not report['android_production_signing']:
        raise ValueError('Incomplete signed Nightly aggregate')
    data = json.loads(discovery.read_text())
    run_id = str(data['official_run_id'])
    if not re.fullmatch(r'[1-9][0-9]*', run_id):
        raise ValueError('Invalid official run identity')
    identity_data = dict(upstream_sha=data['upstream_sha'], official_run_id=run_id,
                         custom_sha=os.environ['GITHUB_SHA'], patchset=data['patchset'],
                         common_patch_hash=patch_hash('common', data['patchset']),
                         sos_patch_hash=patch_hash('sos', data['patchset']),
                         wayland_policy=report.get('wayland', {}).get('policy_sha256'))
    identity = hashlib.sha256(json.dumps(identity_data, sort_keys=True).encode()).hexdigest()
    tag = 'nightly-v' + data['upstream_version'] + '-custom.' + data['patchset'] + '-' + identity[:12]
    if api(f'repos/{REPO}/releases/tags/{tag}', missing=True) or api(f'repos/{REPO}/git/ref/tags/{tag}', missing=True):
        raise ValueError('Immutable Nightly tag/release already exists; never overwrite')
    for page in range(1, 11):
        rows = api(f'repos/{REPO}/releases?per_page=100&page={page}') or []
        if any(r.get('name') == tag or r.get('tag_name') == tag for r in rows):
            raise ValueError('Immutable Nightly draft already exists; never overwrite')
        if len(rows) < 100:
            break
    else:
        raise ValueError('Release history exhausted; refusing duplicate draft')
    for job in api(f'repos/{REPO}/actions/runs/{os.environ["GITHUB_RUN_ID"]}/jobs?per_page=100')['jobs']:
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
                'asset_inventory=' + json.dumps(sorted(expected)),
                'android_signing=PRODUCTION SIGNED / IDENTITY VERIFIED; APK v2 AND v3',
                'desktop_code_signing=NOT ENABLED', 'runtime_ui_validation=NOT TESTED',
                'real_remote_session=NOT TESTED', 'release_policy=DRAFT ONLY; NOT PUBLIC',
                'automation_state=uploading']
    if identity_data['wayland_policy']:
        metadata.append('wayland_policy_sha256=' + identity_data['wayland_policy'])
    notes = ('## RustDesk Custom Nightly ' + data['upstream_version'] + '\n\n'
             'Based on the [verified upstream Nightly build](' + data['official_run_url'] + ').\n\n'
             '### Downloads\n\nUse the attached packages and `SHA256SUMS` to verify integrity.\n\n'
             '### Verification\n\nAndroid APK v2/v3 signatures verified; desktop code signing not enabled. '
             'Runtime UI and remote sessions have not been tested.\n\n'
             '<!-- rustdesk-custom-release-metadata\n' + '\n'.join(metadata) + '\n-->\n')
    created = request('POST', f'repos/{REPO}/releases', dict(tag_name=tag, name='RustDesk ' + data['upstream_version'] + ' Custom Nightly (' + data['patchset'] + ', ' + identity[:12] + ')',
                      target_commitish=os.environ['GITHUB_SHA'], body=notes, draft=True, prerelease=True))
    if created.get('draft') is not True:
        raise ValueError('Nightly must remain a draft')
    gh('release', 'upload', tag, *map(str, files), '--repo', REPO)
    for attempt in range(12):
        uploaded = {a['name']: {'size': a['size'], 'digest': a.get('digest')} for a in
                    (api(f'repos/{REPO}/releases/{created["id"]}/assets?per_page=100') or []) if a.get('state') == 'uploaded'}
        if uploaded == expected:
            break
        if attempt < 11:
            time.sleep(5)
    if uploaded != expected:
        raise ValueError('Incomplete Nightly upload/checksum verification; draft remains incomplete')
    final = request('PATCH', f'repos/{REPO}/releases/{created["id"]}',
                    dict(draft=True, prerelease=True, body=notes.replace('automation_state=uploading', 'automation_state=complete')))
    if final.get('draft') is not True or final.get('prerelease') is not True:
        raise ValueError('Nightly draft state mismatch')
    result = dict(tag=tag, release_id=created['id'], draft=True, prerelease=True,
                  workflow_run=os.environ['GITHUB_RUN_ID'], assets=expected)
    (ROOT / '.work/nightly-draft.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Verified Nightly draft created: ' + tag)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['resolve', 'route', 'aggregate', 'preflight', 'draft'])
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
    elif a.mode == 'aggregate':
        aggregate(a.root, a.discovery)
    else:
        data = discover(a.official_run_id)
        if a.expected_sha and a.expected_sha != data['upstream_sha']:
            raise ValueError('Official run/source SHA mismatch')
        save(data)
        if a.mode == 'route':
            route(data)
