#!/usr/bin/env python3
"""Explicit Patch Profiles; unknown versions may test latest, never release it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
VERSION = re.compile(r'^(?:v)?([0-9]+)\.([0-9]+)\.([0-9]+)$')
PATCHSET_V1 = 'v1'
PATCHSET_V2 = 'v2'
V2_BOUNDARY = (1, 5, 0)

def version_tuple(value):
    match = VERSION.fullmatch(str(value).strip())
    if not match:
        raise ValueError('Numeric upstream version required: ' + str(value))
    return tuple(int(part) for part in match.groups())

def profile_for_version(version, channel='ci'):
    numeric = version_tuple(version)
    normalized = '.'.join(map(str, numeric))
    if channel not in ('ci', 'nightly', 'stable'):
        raise ValueError('Invalid Patch Profile channel')
    registry = json.loads((ROOT / 'metadata/patch-profiles.json').read_text())
    if registry['schema'] != 'patch-profiles-v1':
        raise ValueError('Unknown Patch Profile schema')
    profile_id = registry['exact_versions'].get(normalized)
    fallback = profile_id is None and numeric >= V2_BOUNDARY
    if profile_id is None:
        profile_id = 'legacy-pre-1.5' if numeric < V2_BOUNDARY else registry['latest_maintained']
    profile = registry['profiles'][profile_id]
    if type(profile['stable_allowed']) is not bool:
        raise ValueError('Invalid Stable Patch Profile policy')
    if channel == 'stable' and (fallback or not profile['stable_allowed']):
        raise ValueError('Stable requires an explicitly maintained Stable Patch Profile; candidate/fallback forbidden')
    selected = profile['patchset']
    if not re.fullmatch(r'v[1-9][0-9]*', selected):
        raise ValueError('Invalid Patch Profile patchset')
    folder = ROOT / 'patchsets' / selected
    if not folder.is_dir():
        raise RuntimeError('Selected patchset directory is missing: ' + str(folder))
    for required in ('common', 'sos'):
        if not (folder / required).is_dir():
            raise RuntimeError('Selected patchset directory is incomplete: ' + str(folder / required))
    return dict(profile=profile_id, selected=selected, fallback=fallback,
                compatibility_test_only=fallback or not profile['stable_allowed'],
                stable_allowed=not fallback and profile['stable_allowed'])


def patchset_for_version(version, channel='ci'):
    return profile_for_version(version, channel)['selected']


def require_selection(version, selected, channel='ci'):
    profile = profile_for_version(version, channel)
    if profile['selected'] != selected:
        raise ValueError('Patchset differs from selected Patch Profile')
    return profile


def mapped(upstream_ref):
    # Legacy callers of mapped() are Stable discovery paths.
    return patchset_for_version(upstream_ref, channel='stable')

def metadata(name):
    if not re.fullmatch(r'v[1-9][0-9]*', name):
        raise ValueError('Invalid patchset ID')
    path = ROOT / 'patchsets' / name / 'patchset.json'
    if not path.is_file():
        raise ValueError('Patchset metadata missing: ' + name)
    return json.loads(path.read_text())

def patch_hash(folder, name=None):
    """Calculate provenance/integrity hash; never used for selection."""
    name = name or os.environ.get('PATCHSET', 'v1')
    metadata(name)
    paths = sorted((ROOT / 'patchsets' / name / folder).glob('*.patch'))
    if not paths:
        raise ValueError('Empty patch generation')
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode() + b'\0' + path.read_bytes().replace(b'\r\n', b'\n'))
    return digest.hexdigest()

def verify(name):
    """Explicit integrity gate; not part of patchset selection."""
    data = metadata(name)
    for folder in ('common', 'sos'):
        if patch_hash(folder, name) != data['hashes'][folder]:
            raise ValueError('Patchset integrity mismatch: ' + name + '/' + folder)
    return data

def select(sha=None, source=None, report=None, upstream_ref=None, version=None, channel=None):
    """Resolve a numeric version Profile; SHA and applicability never select it."""
    selected_version = version or upstream_ref
    if not selected_version and source:
        match = re.search(r'^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"',
                          (Path(source) / 'Cargo.toml').read_text(), re.M)
        selected_version = match.group(1) if match else None
    if not selected_version:
        raise ValueError('Upstream version/ref required for static patchset selection')
    profile = profile_for_version(selected_version, channel or os.environ.get("BUILD_CHANNEL", "ci"))
    selected = profile["selected"]
    data = {'upstream_version': str(selected_version).lstrip('v'),
            'upstream_ref': upstream_ref or str(selected_version),
            'selected': selected,
            'selection_policy': 'patch-profile-v1',
            **profile,
            'overall': 'STATIC_SELECTION_PASS'}
    if report:
        report_path = Path(report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps(data, indent=2))
    return selected

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('sha', nargs='?', help='Retained for compatibility; never used for selection')
    parser.add_argument('--source', type=Path, help='Read numeric Cargo version when --version/--ref is absent')
    parser.add_argument('--report', default='.work/patchset-selection.json')
    parser.add_argument('--ref', default='')
    parser.add_argument('--version', default='')
    parser.add_argument('--channel', choices=('ci', 'nightly', 'stable'), default=None)
    args = parser.parse_args()
    name = select(sha=args.sha, source=args.source, report=args.report, upstream_ref=args.ref, version=args.version, channel=args.channel)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as file:
            file.write('patchset=' + name + '\n')
