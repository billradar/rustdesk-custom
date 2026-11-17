"""Freeze Actions API endpoints into v3 prepared source, covered by its inventory."""
import argparse
import hashlib
import json
import os
import re
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = 'api-failover-policy-v1'
RUST = 'src/hbbs_http/api_failover_policy.rs'
DART = 'flutter/lib/utils/api_failover_policy.dart'
WSS = 'libs/hbb_common/src/radar_wss_generated.rs'
SNAPSHOT = 'api-failover.json'


def origin(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError('API endpoint must be an ASCII HTTPS origin (value withheld)')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or any(c in value for c in ('\\', '"', '$', '`'))):
        raise ValueError('API endpoint must be HTTPS without credentials/path/query (value withheld)')
    port = parsed.port
    host = parsed.hostname.lower()
    if ':' in host:
        if '%' in host:
            raise ValueError('Scoped IPv6 addresses are not public API origins')
        host = ipaddress.IPv6Address(host).compressed
    elif len(host) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
        raise ValueError('API endpoint has an invalid DNS hostname (value withheld)')
    if ':' in host:
        host = '[' + host + ']'
    return 'https://' + host + (':' + str(port) if port and port != 443 else '')


def resolve(primary, fallback):
    if not fallback:
        return dict(schema=SCHEMA, primary='', fallback='', enabled=False)
    primary, fallback = origin(primary), origin(fallback)
    if primary == fallback:
        raise ValueError('Primary and fallback must be different HTTPS origins')
    return dict(schema=SCHEMA, primary=primary, fallback=fallback, enabled=True)


def load(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if value != resolve(value.get('primary'), value.get('fallback')):
        raise ValueError('Invalid frozen API policy')
    return value


def sources(value):
    rust = ('// Generated from frozen public Actions variables.\n'
            'const PROFILE_PRIMARY: &str = ' + json.dumps(value['primary']) + ';\n'
            'const PROFILE_FALLBACK: &str = ' + json.dumps(value['fallback']) + ';\n')
    dart = ('// Generated from frozen public Actions variables.\n'
            'const customApiPrimaryOrigin = ' + json.dumps(value['primary']) + ';\n'
            'const customApiFallbackOrigin = ' + json.dumps(value['fallback']) + ';\n')
    wss = ('// Generated from frozen public Actions API origins for own WSS.\n'
           'const PROFILE_PRIMARY: &str = ' + json.dumps(value['primary']) + ';\n'
           'const PROFILE_FALLBACK: &str = ' + json.dumps(value['fallback']) + ';\n')
    return {RUST: rust, DART: dart, WSS: wss}


def apply(tree, value):
    tree = Path(tree)
    for name, text in sources(value).items():
        path = tree / name
        if not path.is_file() or path.is_symlink():
            raise ValueError('v3 API policy patch must exist before configuration')
        path.write_text(text, encoding='utf-8', newline='\n')
    snapshot = tree / SNAPSHOT
    if snapshot.is_symlink():
        raise ValueError('API policy snapshot must be a regular file')
    snapshot.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8', newline='\n')
    return hashlib.sha256(snapshot.read_bytes()).hexdigest()


def verify(tree, digest, expected_primary=None):
    tree = Path(tree)
    path = tree / SNAPSHOT
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('Frozen API policy differs from prepared source identity')
    value = load(path)
    for name, expected in sources(value).items():
        source = tree / name
        if source.is_symlink() or source.read_text(encoding='utf-8') != expected:
            raise ValueError('Compiled API policy differs from its frozen snapshot')
    if value['enabled'] and expected_primary is not None and origin(expected_primary) != value['primary']:
        raise ValueError('Build API primary differs from frozen source policy; prepare a fresh batch')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    snapshot = resolve(os.environ.get('RUSTDESK_API_SERVER', ''), os.environ.get('RUSTDESK_API_FALLBACK_SERVER', ''))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print('v3 API policy frozen: ' + ('enabled' if snapshot['enabled'] else 'disabled (fallback variable empty)'))
