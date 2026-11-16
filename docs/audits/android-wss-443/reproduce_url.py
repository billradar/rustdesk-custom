"""Audit only: compile exact upstream URL functions with a Config facade.
Not an Android, socket, TLS, proxy, or production configuration integration test.
Usage: python3 reproduce_url.py /clean/locked/upstream --output results.json
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

UPSTREAM = '95cca3f661f635b3cc85c04935fe8d96d8f432ef'
HBB = 'fae47e024dd83cef6aaecde0aa7d11731df11649'

def function(path, name):
    text = path.read_text()
    start = text.index('fn ' + name + '(') if name != 'split_host_port' else text.index('fn split_host_port<')
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

def run(source):
    hbb = source / 'libs/hbb_common'
    for tree, expected in ((source, UPSTREAM), (hbb, HBB)):
        assert subprocess.check_output(['git', '-C', str(tree), 'rev-parse', 'HEAD'], text=True).strip() == expected
        assert not subprocess.check_output(['git', '-C', str(tree), 'status', '--porcelain'])
    extracted = '\n'.join(function(hbb / 'src' / path, name) for path, name in (
        ('lib.rs', 'is_ipv4_str'), ('lib.rs', 'is_ipv6_str'), ('lib.rs', 'is_ip_str'),
        ('socket_client.rs', 'split_host_port'), ('websocket.rs', 'is_ws_endpoint'),
        ('websocket.rs', 'check_ws'), ('websocket.rs', 'websocket_port')))
    facade = r'''
use std::{cell::RefCell, collections::HashMap, sync::RwLock, time::Duration};
#[macro_export] macro_rules! throttled_log { ($($tokens:tt)*) => {{ let _ = Duration::from_secs(60); }}; }
const RENDEZVOUS_PORT: i32 = 21116;
const RELAY_PORT: i32 = 21117;
const OPTION_RELAY_SERVER: &str = "relay-server";
const OPTION_WEBSOCKET_PORT: &str = "websocket-port";
static EXE_RENDEZVOUS_SERVER: RwLock<String> = RwLock::new(String::new());
static PROD_RENDEZVOUS_SERVER: RwLock<String> = RwLock::new(String::new());
thread_local! { static OPTIONS: RefCell<HashMap<String,String>> = RefCell::new(HashMap::new()); }
struct Config;
impl Config {
    fn get_option(key: &str) -> String { OPTIONS.with(|m| m.borrow().get(key).cloned().unwrap_or_default()) }
    fn get_rendezvous_server() -> String {
        let s = Self::get_option("custom-rendezvous-server");
        if s.is_empty() { "example.test:21116".into() } else if split_host_port(&s).is_some() { s } else { format!("{s}:21116") }
    }
}
fn set(key: &str, value: &str) { OPTIONS.with(|m| { m.borrow_mut().insert(key.into(),value.into()); }); }
fn use_ws() -> bool { Config::get_option("allow-websocket") == "Y" }
fn case(name: &str, input: &str, expected: &str) {
    let actual = check_ws(input);
    assert_eq!(actual, expected, "{name}");
    println!("{name}\t{actual}");
}
fn main() {
    case("disabled-tcp-address", "example.test:21116", "example.test:21116");
    set("allow-websocket", "Y");
    set("custom-rendezvous-server", "example.test");
    case("empty-api-id", "example.test:21116", "ws://example.test/ws/id");
    case("empty-api-relay", "example.test:21117", "ws://example.test/ws/relay");
    set("api-server", "https://example.test");
    case("https-api-id", "example.test:21116", "wss://example.test/ws/id");
    case("https-api-online", "example.test:21115", "wss://example.test/ws/id");
    case("https-api-relay", "example.test:21117", "wss://example.test/ws/relay");
    case("native-ipv4-id", "127.0.0.1:21116", "ws://127.0.0.1:21118");
    case("native-ipv4-relay", "127.0.0.1:21117", "ws://127.0.0.1:21119");
    case("native-ipv6-id", "[0:0:0:0:0:0:0:1]:21116", "ws://[0:0:0:0:0:0:0:1]:21118");
    case("native-ipv6-relay", "[0:0:0:0:0:0:0:1]:21117", "ws://[0:0:0:0:0:0:0:1]:21119");
    case("explicit-wss", "wss://example.test:9443/ws/id", "wss://example.test:9443/ws/id");
    case("explicit-ws", "ws://example.test:21118", "ws://example.test:21118");
    set("websocket-port", "8443");
    case("own-wss-port", "example.test:21116", "wss://example.test:8443/ws/id");
    case("peer-default-port", "peer.test:21117", "wss://peer.test/ws/relay");
    set("websocket-port", "");
    set("custom-rendezvous-server", "example.test:23456");
    case("custom-id-port", "example.test:23456", "wss://example.test/ws/id");
    case("custom-relay-port", "example.test:23457", "wss://example.test/ws/relay");
    set("api-server", "http://example.test");
    case("intentional-plain-ws", "example.test:23456", "ws://example.test/ws/id");
    set("allow-websocket", "");
    case("disabled-ipv6-tcp", "[0:0:0:0:0:0:0:1]:21116", "[0:0:0:0:0:0:0:1]:21116");
}
'''
    with tempfile.TemporaryDirectory(prefix='wss-url-audit-') as td:
        root = Path(td)
        (root / 'src').mkdir()
        (root / 'Cargo.toml').write_text('[package]\nname="wss-url-audit"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nregex="=1.11.1"\n')
        (root / 'src/main.rs').write_text(facade + extracted)
        output = subprocess.check_output(['cargo', 'run', '--quiet', '--manifest-path', str(root / 'Cargo.toml')], text=True)
    return dict(scope='actual extracted URL functions; Config facade only; NO network/TLS/Android validation',
                upstream_sha=UPSTREAM, hbb_sha=HBB,
                runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                extracted_sha256=hashlib.sha256(extracted.encode()).hexdigest(),
                compiler=subprocess.check_output(['rustc', '--version'], text=True).strip(),
                cases=dict(row.split('\t', 1) for row in output.splitlines()))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = run(args.source)
    content = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(content)
    print(content)
