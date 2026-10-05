#!/usr/bin/env python3
"""Single production release adapter over the validated artifact gates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.parse
import zipfile
from scripts.upstream.resolve import api, choose_stable, VERSION
from scripts.upstream.patchsets import patch_hash
from scripts.upstream.patchsets import mapped, select
from scripts.release.github import collect, gh, request
from scripts.signing.production_config import payload, scan_bytes

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'billradar/rustdesk-custom'

def guard():
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise ValueError('Production writes/build discovery limited to named production repository')

def discover(ref, force=False, dry_run=True):
    guard()
    data = choose_stable(ref)
    revision = (ROOT / 'patch-revision.txt').read_text().strip()
    if not re.fullmatch(r'[1-9][0-9]{0,5}', revision):
        raise ValueError('Invalid revision')
    name = mapped(data['upstream_sha']) or select(data['upstream_sha'])
    os.environ['PATCHSET'] = name
    data.update(patchset=name, revision=revision, common_patch_hash=patch_hash('common'),
                sos_patch_hash=patch_hash('sos'))
    tag = f'v{data["version"]}-custom.{revision}'
    data['release_tag'] = tag
    existing = api(f'repos/{REPOSITORY}/releases/tags/{urllib.parse.quote(tag, safe="")}', missing=True)
    if existing:
        body = existing.get('body') or ''
        expected = [f'Upstream SHA: {data["upstream_sha"]}', f'Patch Set: {name}',
                    f'Common Patch Hash: {data["common_patch_hash"]}',
                    f'SOS Patch Hash: {data["sos_patch_hash"]}', 'Automation-State: complete']
        asset_names = {a['name'] for a in existing['assets'] if a['state'] == 'uploaded'}
        required = {'SHA256SUMS', 'build-info-standard.json', 'build-info-sos.json',
                    f'rustdesk-{data["version"]}-standard-windows-x86_64.zip',
                    f'rustdesk-{data["version"]}-sos-windows-x86_64.zip'}
        if existing['prerelease'] or not all(x in body for x in expected) or asset_names != required:
            raise ValueError('Existing release incomplete or different; never overwrite, review revision')
    else:
        # An existing tag without a matching complete release is also a hard stop.
        ref_exists = api(f'repos/{REPOSITORY}/git/ref/tags/{urllib.parse.quote(tag, safe="")}', missing=True)
        if ref_exists:
            raise ValueError('Tag exists without a complete release; never overwrite')
    data['already_processed'] = bool(existing)
    data['build_needed'] = not existing or force
    data['publish_needed'] = not existing and not dry_run
    data['dry_run'] = dry_run
    Path('.work').mkdir(exist_ok=True)
    Path('.work/discovery.json').write_text(json.dumps(data, indent=2) + '\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as file:
            for key, value in data.items():
                text = str(value).lower() if isinstance(value, bool) else str(value)
                if '\n' in text or '\r' in text:
                    raise ValueError('Unsafe discovery output')
                file.write(f'{key}={text}\n')
    print(json.dumps(data, indent=2))
    return data

def scan_job_log(job_id):
    # gh rejects ANSI controls by default; permit them only into captured memory.
    # Never render or print downloaded logs. Scan raw and de-coloured text so
    # terminal formatting cannot hide a known credential pattern.
    text = gh('api', '--allow-escape-sequences',
              f'repos/{REPOSITORY}/actions/jobs/{job_id}/logs')
    scan_bytes(text.encode())
    normalized = re.sub(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))', '', text)
    scan_bytes(normalized.encode())

def assets(root):
    guard()
    # Check completed source/build jobs before either dry-run approval or publishing.
    # GitHub redacts known Secrets; this gate checks visible credential patterns only.
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    if not re.fullmatch(r'[1-9][0-9]*', run_id):
        raise ValueError('Actual production workflow run ID required')
    page = 1
    while True:
        jobs = api(f'repos/{REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100&page={page}')['jobs']
        for job in jobs:
            if job['status'] == 'completed' and job['conclusion'] == 'success':
                scan_job_log(job["id"])
        if len(jobs) < 100:
            break
        page += 1
    infos, folders = collect(Path(root))
    for variant in ('standard', 'sos'):
        payload(folders[variant])
    info = infos['standard']
    tag = info['upstream_tag']
    if not VERSION.fullmatch(tag):
        raise ValueError('Official stable tag required')
    version = tag.lstrip('v')
    stable = choose_stable(tag)
    if stable['upstream_sha'] != info['upstream_sha']:
        raise ValueError('Official tag SHA changed or is not stable')
    revision = (ROOT / 'patch-revision.txt').read_text().strip()
    if info['patch_revision'] != revision:
        raise ValueError('Revision mismatch')
    directory = ROOT / '.work/production-release-assets'
    directory.mkdir(parents=True, exist_ok=False)
    for variant, folder in folders.items():
        archive = directory / f'rustdesk-{version}-{variant}-windows-x86_64.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
            for file in sorted(folder.rglob('*')):
                if file.is_file():
                    output.write(file, file.relative_to(folder).as_posix())
        (directory / f'build-info-{variant}.json').write_bytes((folder / 'build-info.json').read_bytes())
    sums = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                   for p in sorted(directory.iterdir()))
    (directory / 'SHA256SUMS').write_text(sums)
    result = {'result': 'PASS', 'upstream_sha': info['upstream_sha'], 'patchset': info['patchset'],
              'common_patch_hash': info['common_patch_hash'], 'sos_patch_hash': infos['sos']['sos_patch_hash'],
              'custom_repository_sha': info['custom_repository_sha'], 'workflow_run': info['workflow_run'],
              'configuration': 'PRODUCTION', 'runtime_ui': 'SKIPPED BY USER',
              'completed_job_log_scan': 'PASS / VISIBLE KNOWN PATTERNS ONLY',
              'server_config_fingerprint': info['server_config_fingerprint'],
              'real_remote_session': 'NOT TESTED', 'credential_scan': 'KNOWN PATTERNS ONLY'}
    (ROOT / '.work/production-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    return infos, directory

def publish(root, dry_run_id):
    guard()
    previous = None
    if dry_run_id:
        if not re.fullmatch(r'[1-9][0-9]*', dry_run_id):
            raise ValueError('Validated production dry-run ID required')
        run = api(f'repos/{REPOSITORY}/actions/runs/{dry_run_id}')
        if (run['conclusion'] != 'success' or run['event'] != 'workflow_dispatch' or
                run['head_sha'] != os.environ['GITHUB_SHA'] or run['path'] != '.github/workflows/release-check.yml'):
            raise ValueError('Dry-run must be successful at current production commit/workflow')
        listed = api(f'repos/{REPOSITORY}/actions/runs/{dry_run_id}/artifacts?per_page=100')['artifacts']
        if not any(a['name'] == 'production-dry-run-validated' and not a['expired'] for a in listed):
            raise ValueError('Production dry-run validation artifact missing or expired')
        # The workflow downloads and verifies this report before invoking publish.
        previous = json.loads((ROOT / '.work/dry-run-evidence/production-validation.json').read_text())
    else:
        # First publication requires the explicit dry run. Subsequent stable versions
        # retain all same-run build/validation gates and may publish automatically.
        prior = api(f'repos/{REPOSITORY}/releases?per_page=100')
        if not any(not r['draft'] and not r['prerelease'] and
                   re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+-custom\.[1-9][0-9]*', r['tag_name']) and
                   'Automation-State: complete' in (r.get('body') or '') for r in prior):
            raise ValueError('First production release requires a validated dry-run run ID')
    infos, directory = assets(root)
    info, sos = infos['standard'], infos['sos']
    if previous is not None:
        for key in ('upstream_sha', 'patchset', 'common_patch_hash', 'custom_repository_sha', 'server_config_fingerprint'):
            if previous.get(key) != info[key]:
                raise ValueError('Dry-run/current production provenance mismatch: ' + key)
        if previous.get('result') != 'PASS' or previous.get('sos_patch_hash') != sos['sos_patch_hash'] or str(previous.get('workflow_run')) != dry_run_id:
            raise ValueError('Dry-run evidence not validated for this pair')
    tag = f'v{info["upstream_tag"].lstrip("v")}-custom.{info["patch_revision"]}'
    if api(f'repos/{REPOSITORY}/releases/tags/{tag}', missing=True) or api(f'repos/{REPOSITORY}/git/ref/tags/{tag}', missing=True):
        raise ValueError('Release/tag already exists; no overwrite')
    dry_run_note = (f'https://github.com/{REPOSITORY}/actions/runs/{dry_run_id}' if dry_run_id else 'Not required after initial validated release')
    notes = f'''RustDesk Standard and SOS — unsigned Windows x86_64 clients.

Upstream: rustdesk/rustdesk
Upstream Tag: {info['upstream_tag']}
Upstream SHA: {info['upstream_sha']}
Patch Set: {info['patchset']}
Custom Repository SHA: {info['custom_repository_sha']}
Common Patch Hash: {info['common_patch_hash']}
SOS Patch Hash: {sos['sos_patch_hash']}
Variants: Standard / SOS
Platform: Windows x86_64
Workflow: https://github.com/{REPOSITORY}/actions/runs/{info['workflow_run']}
Production Dry Run: {dry_run_note}

Build Validation: PASS
Checksum Validation: PASS
Architecture Validation: PASS
Provenance Validation: PASS
Runtime/UI Validation: SKIPPED BY USER
Real Remote Session Validation: NOT TESTED
Code Signing: NOT ENABLED
Configuration: PRODUCTION
Password Security V2: DEFERRED

Embedded client password/configuration can be extracted by a client owner.
SOS retains historical UI restrictions; native controller capability is not disabled.
Source: exact upstream SHA + this maintenance commit and patches included in both ZIPs.
'''
    draft = request('POST', f'repos/{REPOSITORY}/releases', {
        'tag_name': tag, 'target_commitish': info['custom_repository_sha'],
        'name': tag, 'body': notes, 'draft': True, 'prerelease': False})
    gh('release', 'upload', tag, *map(str, sorted(directory.iterdir())), '--repo', REPOSITORY)
    uploaded = api(f'repos/{REPOSITORY}/releases/{draft["id"]}/assets')
    expected = {p.name: p.stat().st_size for p in directory.iterdir()}
    if {a['name']: a['size'] for a in uploaded if a['state'] == 'uploaded'} != expected:
        raise ValueError('Incomplete draft upload; release remains unpublished')
    result = request('PATCH', f'repos/{REPOSITORY}/releases/{draft["id"]}', {
        'draft': True, 'prerelease': False, 'body': notes + '\nAutomation-State: complete\n'})
    print(result['html_url'])

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['discover', 'validate', 'publish'])
    p.add_argument('--ref', default='')
    p.add_argument('--force', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--path', type=Path, default=Path('.work/collected'))
    p.add_argument('--dry-run-id', default='')
    args = p.parse_args()
    if args.mode == 'discover':
        discover(args.ref, args.force, args.dry_run)
    elif args.mode == 'validate':
        assets(args.path)
    else:
        publish(args.path, args.dry_run_id)
