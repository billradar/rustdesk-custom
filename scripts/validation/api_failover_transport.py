"""Compile the actual patched Rust selector and exercise local TLS fault scenarios.
No production endpoints are contacted. Requires a prepared v3 tree, cargo, OpenSSL,
IPv6 loopback and the repository Python environment. Keys exist only in a temp dir.
"""
import argparse
import hashlib
import http.server
import json
import os
import select
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

FIXTURE = Path(__file__).parent / 'fixtures/api-failover'

class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    address_family = socket.AF_INET6

class ConnectHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_CONNECT(self):
        target = urlsplit('//' + self.path)
        # Test-only proxy accepts loopback targets exclusively.
        if target.hostname not in ('localhost', '::1', '127.0.0.1'):
            self.send_error(403)
            return
        with socket.create_connection((target.hostname, target.port), timeout=3) as upstream:
            self.send_response(200)
            self.end_headers()
            peers = (self.connection, upstream)
            while True:
                ready, _, _ = select.select(peers, [], [], 5)
                if not ready:
                    return
                for peer in ready:
                    data = peer.recv(65536)
                    if not data:
                        return
                    (upstream if peer is self.connection else self.connection).sendall(data)

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def handle_request(self):
        if self.path == '/stats':
            result = json.dumps(self.server.stats).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(result)))
            self.end_headers()
            self.wfile.write(result)
            return
        body = self.rfile.read(int(self.headers.get('Content-Length', '0'))).decode()
        if self.command == 'HEAD':
            self.server.stats['probe_auth'] = self.headers.get('Authorization', '')
            self.server.stats['probe_method'] = self.command
            count = self.server.stats.get('probe_count', 0)
            status = (401, 404, 405)[count % 3]
            self.server.stats['probe_count'] = count + 1
            self.server.stats['probe_status'] = status
            self.send_response(status)
            self.end_headers()
            return
        self.server.stats['requests'] += 1
        if self.path == '/api/drop':
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if self.path in ('/api/body-drop', '/api/body-stall'):
            self.send_response(200)
            self.send_header('Content-Length', '100')
            self.end_headers()
            self.wfile.write(b'partial')
            self.wfile.flush()
            if self.path == '/api/body-stall':
                time.sleep(14)
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if self.path == '/api/slow':
            time.sleep(14)
            return
        status = int(self.path.rsplit('/', 1)[-1]) if '/status/' in self.path else (200 if self.path == '/api/record' else 302)
        result = json.dumps(dict(authorization=self.headers.get('Authorization'),
                                 host=self.headers.get('Host'), path=self.path, body=body)).encode()
        self.send_response(status)
        self.send_header('Content-Length', str(len(result)))
        if status == 302:
            self.send_header('Location', 'http://127.0.0.1:1/forbidden')
        self.end_headers()
        self.wfile.write(result)

    do_GET = do_POST = do_HEAD = handle_request


def run(source, output):
    with tempfile.TemporaryDirectory(prefix='api-failover-') as directory:
        root = Path(directory)
        for name in ('Cargo.toml', 'Cargo.lock'):
            shutil.copyfile(FIXTURE / name, root / name)
        shutil.copytree(FIXTURE / 'facade', root / 'facade')
        shutil.copytree(source / 'libs/radar_diagnostics', root / 'diagnostics')
        (root / 'src').mkdir()
        shutil.copyfile(FIXTURE / 'lib.rs', root / 'src/lib.rs')
        code = (source / 'src/hbbs_http/api_failover.rs').read_text()
        from scripts.source.api_policy import resolve, sources, RUST
        policy = resolve('https://api.test.invalid', 'https://backup.test.invalid')
        (root / 'src/api_failover_policy.rs').write_text(sources(policy)[RUST], encoding='utf-8')
        (root / 'src/api_failover.rs').write_text(code + '\n' + (FIXTURE / 'scenarios.rs').read_text())
        def openssl(*args):
            subprocess.run(['openssl', *args], cwd=root, check=True, capture_output=True)
        (root / 'ca.cnf').write_text('[req]\ndistinguished_name=dn\nx509_extensions=v3_ca\n[dn]\n[v3_ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n')
        openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'ca.key',
                '-out', 'ca.pem', '-subj', '/CN=API Local Test CA', '-days', '1', '-config', 'ca.cnf')
        openssl('req', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'server.key',
                '-out', 'server.csr', '-subj', '/CN=localhost')
        (root / 'ext').write_text('subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1\nextendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n')
        openssl('x509', '-req', '-in', 'server.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key',
                '-CAcreateserial', '-out', 'server.pem', '-days', '1', '-extfile', 'ext')
        openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'bad.key',
                '-out', 'bad.pem', '-subj', '/CN=untrusted.invalid', '-days', '1')
        servers = []
        def serve(v6=True, bad=False):
            cls = Server if v6 else http.server.ThreadingHTTPServer
            s = cls(('::1' if v6 else '127.0.0.1', 0), Handler)
            s.stats = dict(requests=0, probe_auth='', probe_method='')
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(root / ('bad.pem' if bad else 'server.pem'), root / ('bad.key' if bad else 'server.key'))
            s.socket = context.wrap_socket(s.socket, server_side=True)
            threading.Thread(target=s.serve_forever, daemon=True).start()
            servers.append(s)
            return f'https://{"localhost" if v6 else "127.0.0.1"}:{s.server_port}'
        primary, fallback, bad = serve(), serve(False), serve(bad=True)
        def serve_proxy(v6):
            cls = Server if v6 else http.server.ThreadingHTTPServer
            server = cls(('::1' if v6 else '127.0.0.1', 0), ConnectHandler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
            return f'http://{"[::1]" if v6 else "127.0.0.1"}:{server.server_port}'
        proxy4, proxy6 = serve_proxy(False), serve_proxy(True)
        closed = socket.socket(socket.AF_INET6)
        closed.bind(('::1', 0))
        closed_url = f'https://localhost:{closed.getsockname()[1]}'
        # Bound but not listening: deterministic refused connection, no port reuse.
        blackhole = socket.socket(socket.AF_INET6)
        blackhole.bind(('::1', 0))
        blackhole.listen()
        def accept_blackhole():
            while True:
                try:
                    conn, _ = blackhole.accept()
                except OSError:
                    return
                threading.Thread(target=lambda c: (time.sleep(7), c.close()), args=(conn,), daemon=True).start()
        threading.Thread(target=accept_blackhole, daemon=True).start()
        env = dict(os.environ, SSL_CERT_FILE=str(root / 'ca.pem'), RUSTDESK_API_SERVER='https://api.test.invalid',
                   API_TEST_PRIMARY=primary, API_TEST_FALLBACK=fallback, API_TEST_BAD_TLS=bad,
                   API_TEST_PROXY4=proxy4, API_TEST_PROXY6=proxy6,
                   API_TEST_CLOSED=closed_url, API_TEST_BLACKHOLE=f'https://localhost:{blackhole.getsockname()[1]}')
        try:
            for args in (['test', '--locked', '--', '--nocapture'], ['clippy', '--locked', '--all-targets', '--', '-D', 'warnings']):
                subprocess.run(['cargo', args[0], '--manifest-path', str(root / 'Cargo.toml'), *args[1:]],
                               env=env, check=True)
            result = dict(scope='isolated actual selector; not full RustDesk client', rust='PASS', clippy='PASS',
                          runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          compiler=subprocess.check_output(['rustc', '--version'], env=env, text=True).strip(),
                          selector_sha256=hashlib.sha256(code.encode()).hexdigest(),
                          diagnostic_core_sha256=hashlib.sha256((source / 'libs/radar_diagnostics/src/lib.rs').read_bytes()).hexdigest(),
                          fixture_sha256=hashlib.sha256(b''.join((FIXTURE / name).read_bytes() for name in ('Cargo.toml', 'Cargo.lock', 'lib.rs', 'scenarios.rs', 'facade/Cargo.toml', 'facade/src/lib.rs'))).hexdigest(),
                          production_network='NOT_TESTED', native_failover='NOT_IMPLEMENTED')
            if output:
                output.write_text(json.dumps(result, indent=2) + '\n')
        finally:
            closed.close()
            blackhole.close()
            for server in servers:
                server.shutdown()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
