#!/usr/bin/env python3
"""Check configuration wiring, exact legacy Flutter UI, and compile the injected helper.

The isolated Rust check covers the actual patched helper with in-memory config maps.
It does not replace the full Rust/Flutter build or a remote assistance session.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('workspace', nargs='?')
parser.add_argument('variant', nargs='?', choices=['standard', 'sos'])
parser.add_argument('--config-only', action='store_true')
parser.add_argument('--static-only', action='store_true')
parser.add_argument('--automation', action='store_true', help='Use API/structural checks instead of historical whole-file hashes')
args = parser.parse_args()
for name in ['RUSTDESK_ID_SERVER', 'RUSTDESK_API_SERVER', 'RUSTDESK_KEY', 'RUSTDESK_PASSWORD']:
    if not os.environ.get(name):
        raise SystemExit(f'{name} is not configured')
key = base64.b64decode(os.environ['RUSTDESK_KEY'], validate=True)
if len(key) != 32:
    raise SystemExit('RUSTDESK_KEY must be a base64 32-byte public key')
url = urlparse(os.environ['RUSTDESK_API_SERVER'])
if url.scheme not in ('http', 'https') or not url.hostname:
    raise SystemExit('Invalid API server URL')
print('Build configuration: configured (values withheld)')
if args.config_only:
    raise SystemExit(0)
if not args.workspace or not args.variant:
    parser.error('workspace and variant are required')
workspace = Path(args.workspace)
expected = json.loads((ROOT / 'metadata/legacy-ui-baseline.json').read_text())[args.variant]
for name, digest in ([] if args.automation else expected.items()):
    # Git for Windows may check out text as CRLF. Compare canonical LF bytes;
    # preserve every other byte, including whitespace, so content changes still fail.
    canonical = (workspace / name).read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(canonical).hexdigest() != digest:
        raise SystemExit(f'Legacy UI mismatch: {name}')
if not args.automation:
    print('Legacy Flutter UI comparison (canonical LF bytes): PASS')
common = (workspace / 'src/common.rs').read_text()
helper = common[common.index('fn apply_custom_build_defaults()'):common.index('\npub fn load_custom_client()')]
if common.count('        apply_custom_build_defaults();') != 1 or common.count('    apply_custom_build_defaults();') != 2:
    raise SystemExit('Expected custom defaults in both legacy initialization paths')
if 'env!("RUSTDESK_API_SERVER").to_owned()' not in common:
    raise SystemExit('Missing API fallback injection')
hbb = (workspace / 'libs/hbb_common/src/config.rs').read_text()
constants = '\n'.join(line for line in hbb.splitlines() if line.startswith(('pub const RENDEZVOUS_SERVERS:', 'pub const RS_PUB_KEY:')))
if 'env!("RUSTDESK_ID_SERVER")' not in constants or 'env!("RUSTDESK_KEY")' not in constants:
    raise SystemExit('Missing official submodule configuration injection')
if ('"sos-mode"' in helper) != (args.variant == 'sos'):
    raise SystemExit('Wrong variant initialization')
if any(s in helper for s in ['conn-type', 'disable-settings', 'compute_permanent_password_h1']):
    raise SystemExit('Unexpected policy/password redesign in reproduction patch')
print('Native configuration wiring: PASS')
if args.static_only:
    print('Native helper compilation: NOT_RUN (--static-only)')
    raise SystemExit(0)
if not shutil.which('rustc'):
    raise SystemExit('rustc required for native helper verification')
mock = '''
mod config {
    use std::collections::HashMap;
    use std::sync::{OnceLock, RwLock, RwLockWriteGuard, LockResult};
    pub struct Settings(OnceLock<RwLock<HashMap<String, String>>>);
    impl Settings {
        pub fn write(&self) -> LockResult<RwLockWriteGuard<'_, HashMap<String, String>>> {
            self.0.get_or_init(|| RwLock::new(HashMap::new())).write()
        }
    }
    pub static HARD_SETTINGS: Settings = Settings(OnceLock::new());
    pub static DEFAULT_SETTINGS: Settings = Settings(OnceLock::new());
    pub static BUILTIN_SETTINGS: Settings = Settings(OnceLock::new());
    pub mod keys { pub const OPTION_ALLOW_REMOTE_CONFIG_MODIFICATION: &str = "allow-remote-config-modification"; }
}
'''
if os.environ.get('PATCHSET', 'v1') == 'v2':
    mock += '\nmod base { pub mod config { pub use crate::config::keys; } }\n'
test = '''
fn main() {
    apply_custom_build_defaults();
    assert_eq!(RENDEZVOUS_SERVERS, &[std::env::var("RUSTDESK_ID_SERVER").unwrap()]);
    assert_eq!(RS_PUB_KEY, std::env::var("RUSTDESK_KEY").unwrap());
    let hard = config::HARD_SETTINGS.write().unwrap();
    assert!(hard.get("password").map(String::as_str) == Some(env!("RUSTDESK_PASSWORD")), "Permanent password initialization mismatch (value withheld)");
    assert_eq!(hard["verification-method"], "use-permanent-password");
    drop(hard);
    let mut defaults = config::DEFAULT_SETTINGS.write().unwrap();
    assert_eq!(defaults["allow-remote-config-modification"], "Y");
    assert_eq!(defaults["allow-hide-cm"], "Y");
    if let Ok(relay) = std::env::var("RUSTDESK_RELAY_SERVER") {
        if !relay.is_empty() { assert_eq!(defaults["relay-server"], relay); }
    }
    defaults.insert("allow-hide-cm".to_owned(), "N".to_owned());
    drop(defaults);
    apply_custom_build_defaults();
    assert_eq!(config::DEFAULT_SETTINGS.write().unwrap()["allow-hide-cm"], "N");
    assert_eq!(config::BUILTIN_SETTINGS.write().unwrap().get("sos-mode").map(String::as_str), SOS_EXPECTED);
    println!("Native injected defaults: PASS (values withheld)");
}
'''
test = test.replace('SOS_EXPECTED', 'Some("Y")' if args.variant == 'sos' else 'None')
with tempfile.TemporaryDirectory(dir=workspace) as temp:
    rs = Path(temp) / 'verify_config.rs'
    exe = Path(temp) / ('verify_config.exe' if os.name == 'nt' else 'verify_config')
    rs.write_text(mock + constants + '\n' + helper + test)
    subprocess.run(['rustc', '--edition=2021', str(rs), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
