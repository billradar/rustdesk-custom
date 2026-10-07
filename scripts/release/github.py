#!/usr/bin/env python3
"""Validate same-run artifacts, then publish test-only prereleases. No PAT required."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import zipfile
from scripts.upstream.resolve import patch_hash, TEST_REPO, VERSION
from scripts.release.naming import windows_installer_name

ROOT = Path(__file__).resolve().parent.parent

def validate(folder):
    info = json.loads((folder / 'build-info.json').read_text())
    from scripts.upstream.patchsets import verify
    verify(info['patchset'])
    if info['patchset'] != os.environ.get('PATCHSET', 'v1'):
        raise ValueError('Artifact selected patchset mismatch')
    if info['variant'] not in ('standard', 'sos') or info['platform'] != 'windows-x86_64':
        raise ValueError('Unexpected variant/platform')
    if info.get('signed') is not False or info.get('configuration') != os.environ.get('BUILD_CONFIGURATION', 'TEST ONLY'):
        raise ValueError('Unexpected signing/configuration policy')
    for field in ('upstream_sha', 'custom_repository_sha'):
        if not re.fullmatch('[0-9a-f]{40}', info[field]):
            raise ValueError('Invalid source SHA')
    for field, env in [('upstream_sha', 'UPSTREAM_EXPECTED_SHA'), ('upstream_tag', 'UPSTREAM_TAG'),
                       ('workflow_run', 'GITHUB_RUN_ID'), ('custom_repository_sha', 'GITHUB_SHA')]:
        if os.environ.get(env) and str(info.get(field)) != os.environ[env]:
            raise ValueError('Artifact/source mismatch: ' + field)
    if info['common_patch_hash'] != patch_hash('common'):
        raise ValueError('Common patch hash mismatch')
    expected_sos = patch_hash('sos') if info['variant'] == 'sos' else None
    if info['sos_patch_hash'] != expected_sos:
        raise ValueError('SOS patch hash mismatch')
    if info['runtime_ui_validation'] != 'SKIPPED BY USER' or info['real_remote_session_validation'] != 'NOT TESTED':
        raise ValueError('Runtime status must not imply validation')
    if os.environ.get('BUILD_CONFIGURATION') == 'PRODUCTION':
        if info.get('custom_repository') != 'billradar/rustdesk-custom' or info.get('architecture') != 'x86_64':
            raise ValueError('Production repository/architecture provenance missing')
        from scripts.signing.production_config import payload
        payload(folder)
    entries = set()
    for line in (folder / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if not re.fullmatch('[0-9a-f]{64}', digest) or name in entries:
            raise ValueError('Invalid/duplicate checksum entry')
        file = folder / name
        if not file.resolve().is_relative_to(folder.resolve()) or not file.is_file():
            raise ValueError('Unsafe/missing checksum path')
        if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError('Checksum mismatch: ' + name)
        entries.add(name)
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p.name != 'SHA256SUMS'}
    if entries != actual:
        raise ValueError('Checksum manifest does not cover exactly all payload files')
    binaries = list((folder / 'rustdesk').glob('*.dll')) + [folder / 'rustdesk/rustdesk.exe']
    for file in binaries:
        data = file.read_bytes()
        if len(data) < 64 or data[:2] != b'MZ':
            raise ValueError('Missing PE header: ' + file.name)
        offset = struct.unpack_from('<I', data, 0x3c)[0]
        if offset + 6 > len(data) or data[offset:offset+4] != b'PE\0\0' or struct.unpack_from('<H', data, offset+4)[0] != 0x8664:
            raise ValueError('Not Windows AMD64: ' + file.name)
    packages = folder / 'packages'
    expected_suffixes = {'.exe', '.msi'}
    if not packages.is_dir():
        raise ValueError('Missing Windows installer package directory')
    package_files = sorted(p for p in packages.iterdir() if p.is_file())
    if {p.suffix.lower() for p in package_files} != expected_suffixes:
        raise ValueError('Windows installers must contain exactly one EXE and one MSI')
    version = info.get('upstream_version') or str(info.get('upstream_tag', '')).lstrip('v')
    expected_names = {
        windows_installer_name(version, info['variant'], 'exe'),
        windows_installer_name(version, info['variant'], 'msi'),
    }
    if {p.name for p in package_files} != expected_names:
        raise ValueError('Windows installer names violate the canonical variant contract')
    for file in package_files:
        data = file.read_bytes()
        if not data:
            raise ValueError('Empty Windows installer: ' + file.name)
        if file.suffix.lower() == '.exe':
            if len(data) < 64 or data[:2] != b'MZ':
                raise ValueError('Installer EXE is not a PE file: ' + file.name)
            offset = struct.unpack_from('<I', data, 0x3c)[0]
            if offset + 6 > len(data) or data[offset:offset+4] != b'PE\0\0' or struct.unpack_from('<H', data, offset+4)[0] != 0x8664:
                raise ValueError('Installer EXE is not Windows AMD64: ' + file.name)
        else:
            if data[:8] != bytes.fromhex('D0CF11E0A1B11AE1'):
                raise ValueError('Installer MSI is not an OLE compound package: ' + file.name)
    print(f'{info["variant"]}: metadata, checksums, Windows AMD64, MSI/EXE installers: PASS')
    return info

def collect(root):
    infos, folders = {}, {}
    for variant in ('standard', 'sos'):
        matches = [p.parent for p in root.rglob('build-info.json') if json.loads(p.read_text()).get('variant') == variant]
        if len(matches) != 1:
            raise ValueError(f'Expected exactly one {variant} same-run artifact')
        folders[variant] = matches[0]
        infos[variant] = validate(matches[0])
    for key in ('patchset', 'upstream_sha', 'upstream_tag', 'custom_repository_sha', 'common_patch_hash', 'workflow_run', 'patch_revision'):
        if infos['standard'][key] != infos['sos'][key]:
            raise ValueError('Standard/SOS provenance mismatch: ' + key)
    if os.environ.get('BUILD_CONFIGURATION') == 'PRODUCTION':
        for key in ('custom_repository', 'server_config_fingerprint'):
            if not infos['standard'].get(key) or infos['standard'][key] != infos['sos'].get(key):
                raise ValueError('Standard/SOS production configuration mismatch: ' + key)
    return infos, folders

def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)

def request(method, path, data):
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as file:
        json.dump(data, file)
        filename = file.name
    try:
        return json.loads(gh('api', '--method', method, path, '--input', filename))
    finally:
        Path(filename).unlink()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['validate', 'collect'])
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    {'validate': validate, 'collect': collect}[args.mode](args.path)
