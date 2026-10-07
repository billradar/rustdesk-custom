#!/usr/bin/env python3
"""Static upstream-version to patchset selection.

Selection is deliberately independent of upstream SHA, patch hashes, patch
contents, and patch applicability. Those checks belong to later gates.

Current policy:
  upstream < 1.5.0  -> patchsets/v1
  upstream >= 1.5.0 -> patchsets/v2

Add future upstream migration boundaries explicitly here; do not reintroduce
content/hash probing into the selector.
"""
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

def patchset_for_version(version):
    selected = PATCHSET_V1 if version_tuple(version) < V2_BOUNDARY else PATCHSET_V2
    folder = ROOT / 'patchsets' / selected
    if not folder.is_dir():
        raise RuntimeError('Selected patchset directory is missing: ' + str(folder))
    for required in ('common', 'sos'):
        if not (folder / required).is_dir():
            raise RuntimeError('Selected patchset directory is incomplete: ' + str(folder / required))
    return selected

def mapped(upstream_ref):
    return patchset_for_version(upstream_ref)

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

def select(sha=None, source=None, report=None, upstream_ref=None, version=None):
    """Select by upstream version only; legacy SHA/source parameters are ignored."""
    selected_version = version or upstream_ref
    if not selected_version:
        raise ValueError('Upstream version/ref required for static patchset selection')
    selected = patchset_for_version(selected_version)
    data = {'upstream_version': str(selected_version).lstrip('v'),
            'upstream_ref': upstream_ref or str(selected_version),
            'selected': selected,
            'selection_policy': 'version-boundary',
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
    parser.add_argument('--source', type=Path, help='Retained for compatibility; never used for selection')
    parser.add_argument('--report', default='.work/patchset-selection.json')
    parser.add_argument('--ref', default='')
    parser.add_argument('--version', default='')
    args = parser.parse_args()
    name = select(sha=args.sha, source=args.source, report=args.report, upstream_ref=args.ref, version=args.version)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as file:
            file.write('patchset=' + name + '\n')
)
PATCHSET_V1 = 'v1'
PATCHSET_V2 = 'v2'
V2_BOUNDARY = (1, 5, 0)

def version_tuple(value):
    match = VERSION.fullmatch(str(value).strip())
    if not match:
        raise ValueError('Numeric upstream version required: ' + str(value))
    return tuple(int(part) for part in match.groups())

def patchset_for_version(version):
    selected = PATCHSET_V1 if version_tuple(version) < V2_BOUNDARY else PATCHSET_V2
    folder = ROOT / 'patchsets' / selected
    if not folder.is_dir():
        raise RuntimeError('Selected patchset directory is missing: ' + str(folder))
    for required in ('common', 'sos'):
        if not (folder / required).is_dir():
            raise RuntimeError('Selected patchset directory is incomplete: ' + str(folder / required))
    return selected

def mapped(upstream_ref):
    return patchset_for_version(upstream_ref)

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
        digest.update(path.name.encode() + b'\\0' + path.read_bytes().replace(b'\\r\\n', b'\\n'))
    return digest.hexdigest()

def verify(name):
    """Explicit integrity gate; not part of patchset selection."""
    data = metadata(name)
    for folder in ('common', 'sos'):
        if patch_hash(folder, name) != data['hashes'][folder]:
            raise ValueError('Patchset integrity mismatch: ' + name + '/' + folder)
    return data

def select(sha=None, source=None, report=None, upstream_ref=None, version=None):
    """Select by upstream version only; legacy SHA/source parameters are ignored."""
    selected_version = version or upstream_ref
    if not selected_version:
        raise ValueError('Upstream version/ref required for static patchset selection')
    selected = patchset_for_version(selected_version)
    data = {'upstream_version': str(selected_version).lstrip('v'),
            'upstream_ref': upstream_ref or str(selected_version),
            'selected': selected,
            'selection_policy': 'version-boundary',
            'overall': 'STATIC_SELECTION_PASS'}
    if report:
        report_path = Path(report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(data, indent=2) + '\\n')
    print(json.dumps(data, indent=2))
    return selected

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('sha', nargs='?', help='Retained for compatibility; never used for selection')
    parser.add_argument('--source', type=Path, help='Retained for compatibility; never used for selection')
    parser.add_argument('--report', default='.work/patchset-selection.json')
    parser.add_argument('--ref', default='')
    parser.add_argument('--version', default='')
    args = parser.parse_args()
    name = select(sha=args.sha, source=args.source, report=args.report, upstream_ref=args.ref, version=args.version)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as file:
            file.write('patchset=' + name + '\\n')
