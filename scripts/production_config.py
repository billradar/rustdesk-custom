#!/usr/bin/env python3
"""Production input and payload checks; never print configured values."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse

NAMES = ('RUSTDESK_ID_SERVER', 'RUSTDESK_RELAY_SERVER', 'RUSTDESK_API_SERVER',
         'RUSTDESK_KEY', 'RUSTDESK_PASSWORD')
FORBIDDEN = (b'test.invalid', b'11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=',
             b'FICTIONAL-TEST-ONLY-Password-149')
PRIVATE = re.compile(rb'-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----')
TOKEN = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})')

def scan_bytes(data):
    wide = data.decode('utf-16-le', errors='ignore').encode('utf-8')
    if PRIVATE.search(data) or TOKEN.search(data) or PRIVATE.search(wide) or TOKEN.search(wide):
        raise ValueError('Forbidden private key / CI credential detected (value withheld)')

def configured():
    values = {name: os.environ.get(name, '') for name in NAMES}
    for name, value in values.items():
        if not value or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError(name + ': missing or unsupported input (value withheld)')
        scan_bytes(value.encode())
        if any(marker in value.encode() for marker in FORBIDDEN) or '.invalid' in value.lower():
            raise ValueError(name + ': fictional fixture forbidden in production')
    for name in ('RUSTDESK_ID_SERVER', 'RUSTDESK_RELAY_SERVER'):
        if not re.fullmatch(r'[A-Za-z0-9.\-:\[\]]+', values[name]):
            raise ValueError(name + ': invalid hostname/address format')
    url = urlparse(values['RUSTDESK_API_SERVER'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise ValueError('Production API must be HTTPS without credentials in URL')
    try:
        key = base64.b64decode(values['RUSTDESK_KEY'], validate=True)
    except Exception:
        raise ValueError('Public key format invalid (value withheld)') from None
    if len(key) != 32:
        raise ValueError('Public key must encode 32 bytes')
    print('Production configuration: CONFIGURED (values withheld)')
    return values

def server_fingerprint():
    # Only public infrastructure configuration; deliberately excludes the password.
    values = {name: os.environ[name] for name in NAMES if name != 'RUSTDESK_PASSWORD'}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

def payload(folder):
    folder = Path(folder)
    info = json.loads((folder / 'build-info.json').read_text())
    if info.get('configuration') != 'PRODUCTION' or info.get('configuration_validation') != 'PASS':
        raise ValueError('Production configuration verification missing')
    if not (folder / 'rustdesk/librustdesk.dll').is_file():
        raise ValueError('Compiled library missing')
    for file in folder.rglob('*'):
        if not file.is_file():
            continue
        data = file.read_bytes()
        scan_bytes(data)
        if any(marker in data or marker.decode().encode('utf-16-le') in data for marker in FORBIDDEN):
            raise ValueError('Test configuration marker in production payload (value withheld)')
    forbidden = {'password', 'token', 'private_key', 'secrets'}
    if forbidden.intersection(info) or any(name in info for name in NAMES):
        raise ValueError('Sensitive field in build-info')
    print('Production payload: no known test fixture or credential marker')

def compiled(library):
    values = configured()
    data = Path(library).read_bytes()
    scan_bytes(data)
    if any(marker in data for marker in FORBIDDEN):
        raise ValueError('Test fixture remains in compiled library')
    for name, value in values.items():
        if value.encode() not in data:
            raise ValueError(name + ': compiled injection not verified (value withheld)')
    print('Compiled production configuration: PASS (values withheld)')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['inputs', 'compiled', 'payload'])
    parser.add_argument('path', nargs='?')
    args = parser.parse_args()
    if args.mode == 'inputs':
        configured()
    elif not args.path:
        parser.error('path required')
    else:
        {'compiled': compiled, 'payload': payload}[args.mode](args.path)
