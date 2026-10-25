#!/usr/bin/env python3
"""Follow successful official Nightly runs; never infer source from its moving tag."""
import argparse
import base64
import json
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
    title = f'Nightly {run_id} / {custom_sha}'
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
                        '-f', 'expected_sha=' + data['upstream_sha']], check=True)


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


def aggregate(root, discovery):
    from scripts.release.qualification import aggregate as qualify
    data = json.loads(discovery.read_text())
    required = dict(channel='nightly', upstream_sha=os.environ['UPSTREAM_EXPECTED_SHA'],
                    upstream_version=os.environ['UPSTREAM_VERSION'], patchset=os.environ['PATCHSET'],
                    upstream_repository=OFFICIAL)
    if any(data.get(k) != v for k, v in required.items()):
        raise ValueError('Nightly discovery identity mismatch')
    for p in root.rglob('build-info.json'):
        info = json.loads(p.read_text())
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
    report = qualify(root, 'nightly', False)
    if report['result'] != 'PASS':
        raise ValueError('Complete Nightly matrix required')
    report.update(official_run_id=data['official_run_id'], official_run_url=data['official_run_url'],
                  publication_authorized=False, android_production_signing=False)
    Path('.work/qualification-aggregate/nightly.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['resolve', 'route', 'aggregate'])
    p.add_argument('--official-run-id', default='')
    p.add_argument('--expected-sha', default='')
    p.add_argument('--root', type=Path, default=Path('.work/all-targets'))
    p.add_argument('--discovery', type=Path, default=Path('.work/nightly-discovery.json'))
    a = p.parse_args()
    if a.mode == 'aggregate':
        aggregate(a.root, a.discovery)
    else:
        data = discover(a.official_run_id)
        if a.expected_sha and a.expected_sha != data['upstream_sha']:
            raise ValueError('Official run/source SHA mismatch')
        save(data)
        if a.mode == 'route':
            route(data)
