#!/usr/bin/env python3
"""Read-only upstream discovery. No untrusted ref is interpolated into a shell."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = 'rustdesk/rustdesk'
TEST_REPO = 'billradar/rustdesk-custom-test'
VERSION = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$')

def api(path, missing=False):
    req = urllib.request.Request('https://api.github.com/' + path, headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'rustdesk-custom-test',
        **({'Authorization': 'Bearer ' + os.environ['GH_TOKEN']} if os.environ.get('GH_TOKEN') else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if missing and error.code == 404:
            return None
        raise

from scripts.upstream.patchsets import patch_hash, mapped, select

def resolve_ref(ref):
    value = api(f'repos/{OFFICIAL}/commits/{urllib.parse.quote(ref, safe="")}')['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('Invalid upstream SHA')
    return value

def stable_releases():
    result = []
    for page in range(1, 11):
        rows = api(f'repos/{OFFICIAL}/releases?per_page=100&page={page}')
        result += [r for r in rows if not r['draft'] and not r['prerelease'] and VERSION.fullmatch(r['tag_name'])]
        if len(rows) < 100:
            break
    return sorted(result, key=lambda r: tuple(map(int, VERSION.fullmatch(r['tag_name']).groups())), reverse=True)

def choose_stable(ref=''):
    rows = stable_releases()
    if not rows:
        raise ValueError('No official stable release')
    if ref:
        rows = [r for r in rows if r['tag_name'] == ref]
        if not rows:
            raise ValueError('Requested ref is not an official non-draft, non-prerelease numeric release')
    selected = rows[0]
    return {'upstream_tag': selected['tag_name'], 'version': selected['tag_name'].lstrip('v'),
            'upstream_sha': resolve_ref(selected['tag_name']), 'official_release_id': selected['id']}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['default', 'stable'])
    parser.add_argument('--ref', default='')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--simulate-failure', action='store_true')
    args = parser.parse_args()
    if args.mode == 'default':
        branch = api(f'repos/{OFFICIAL}')['default_branch']
        ref = args.ref or branch
        data = {'upstream_branch': ref, 'upstream_ref': ref, 'upstream_sha': resolve_ref(ref)}
    else:
        data = choose_stable(args.ref)
        revision = json.loads(RELEASE_IDENTITY.read_text())['revision']
        if not re.fullmatch(r'[1-9][0-9]{0,5}', revision):
            raise ValueError('Invalid patch revision')
        name=mapped(data['upstream_sha']) or select(data['upstream_sha'])
        os.environ['PATCHSET']=name
        data['patchset']=name
        data.update(revision=revision, common_patch_hash=patch_hash('common'), sos_patch_hash=patch_hash('sos'))
        completed = []
        for variant, suffix in [('standard', 'custom'), ('sos', 'sos')]:
            tag = f'v{data["version"]}-{suffix}-test.{revision}'
            release = api(f'repos/{TEST_REPO}/releases/tags/{tag}', missing=True)
            data[variant + '_tag'] = tag
            if release:
                body = release.get('body') or ''
                expected = [f'Upstream SHA: {data["upstream_sha"]}', f'Common Patch Hash: {data["common_patch_hash"]}',
                            'Automation-State: complete']
                if variant == 'sos':
                    expected.append(f'SOS Patch Hash: {data["sos_patch_hash"]}')
                legacy = data['upstream_sha']=='6c578292e8ebbbec708b76986ba8c4bc7c509747' and name=='v1'
                if not legacy: expected.append('Patch Set: '+name)
                assets = {a['name'] for a in release['assets']}
                if not release['prerelease'] or release['draft'] or not all(s in body for s in expected) or not {'build-info.json', 'SHA256SUMS'} <= assets or not any(s.endswith('.zip') for s in assets):
                    raise ValueError(f'Existing tag {tag} is incomplete or differs; do not overwrite. Review and increase revision.')
                completed.append(variant)
        if len(completed) == 1 and not args.simulate_failure:
            raise ValueError('Only one variant was published; manual recovery required, no automatic overwrite')
        data['already_processed'] = len(completed) == 2
        data['build_needed'] = not data['already_processed'] or args.force or args.simulate_failure
        # Force only produces diagnostic artifacts if this revision is already published.
        data['publish_needed'] = not data['already_processed'] and not args.simulate_failure
    Path('.work').mkdir(exist_ok=True)
    Path('.work/discovery.json').write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps(data, indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as file:
            for key, value in data.items():
                value = str(value).lower() if isinstance(value, bool) else str(value)
                if '\n' in value or '\r' in value:
                    raise ValueError('Invalid output')
                file.write(f'{key}={value}\n')

if __name__ == '__main__':
    main()
