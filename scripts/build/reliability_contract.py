"""Offline fault injection for the Phase 1 operation boundaries."""

from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts.build import reliability as brf
from scripts.platform.platform_commands import android_package

RATE_LIMIT = """Execution failed for task ':gradle:compileGroovy'.
> Could not resolve all files for configuration ':gradle:compileClasspath'.
   > Could not GET 'https://repo.maven.apache.org/maven2/org/ow2/asm/asm/9.1/asm-9.1.pom'. Received status code 429 from server: Too Many Requests
"""
GIT_ERROR = "fatal: unable to access 'https://github.com/rustdesk/rustdesk.git/': "
SCITER_ERROR = "failed to fetch https://github.com/rustdesk-org/rust-sciter\n" + GIT_ERROR


class ReliabilityContract(unittest.TestCase):
    def test_classification_requires_operation_context_and_failure(self):
        self.assertEqual(brf.classify(brf.MAVEN, 1, RATE_LIMIT), 'NET_RATE_LIMIT')
        for log in (
            '429 timeout',
            RATE_LIMIT.replace('repo.maven.apache.org', 'example.org'),
            RATE_LIMIT.replace('429', '404'),
            RATE_LIMIT + 'checksum mismatch',
            RATE_LIMIT + "Execution failed for task ':app:compileReleaseJavaWithJavac'",
            'BlobNotFound',
        ):
            self.assertEqual(brf.classify(brf.MAVEN, 1, log), 'UNKNOWN', log)
        self.assertEqual(brf.classify(brf.MAVEN, 0, RATE_LIMIT), 'UNKNOWN')
        self.assertEqual(brf.classify(brf.MAVEN, -15, RATE_LIMIT), 'CANCELLED')

    def test_git_and_cargo_classification(self):
        for message, category in (
            ("Failed to connect to github.com port 443 after 100 ms: Couldn't connect to server", 'NET_CONNECT_FAILED'),
            ('Failed to connect to github.com port 443 after 100 ms: Timeout was reached', 'NET_CONNECT_TIMEOUT'),
            ('Operation timed out after 500 milliseconds with 0 bytes received', 'NET_READ_TIMEOUT'),
            ('Recv failure: Connection reset by peer', 'NET_CONNECTION_RESET'),
            ('Temporary failure in name resolution', 'NET_DNS_TEMPORARY'),
            ('The requested URL returned error: 503', 'NET_SERVER_ERROR'),
            ('The requested URL returned error: 404', 'UNKNOWN'),
            ('The requested URL returned error: 403', 'UNKNOWN'),
            ('The requested URL returned error: 401', 'UNKNOWN'),
            ('SSL certificate problem: unable to get local issuer certificate', 'UNKNOWN'),
        ):
            self.assertEqual(brf.classify(brf.GIT, 128, GIT_ERROR + message), category)
            self.assertEqual(brf.classify(brf.CARGO, 101, SCITER_ERROR + message), category)
            self.assertEqual(brf.classify(brf.GIT, 128, message), 'UNKNOWN')
        self.assertEqual(brf.classify(brf.CARGO, 101, GIT_ERROR + 'Connection reset by peer'), 'UNKNOWN')

    def test_policy_schema_and_bounds(self):
        document = json.loads(brf.POLICY.read_text())
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / 'policy.json'
            for value in (True, -1, 7201, '300'):
                document['operations'][brf.GIT]['budget_seconds'] = value
                policy.write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    brf.load_policy(policy)
            policy.write_text('{"schema":1,"schema":2}')
            with self.assertRaises(ValueError):
                brf.load_policy(policy)

    def test_retry_after_and_jitter(self):
        now = datetime(2026, 11, 28, tzinfo=timezone.utc)
        self.assertEqual(brf.retry_after('120', now), 120)
        self.assertEqual(brf.retry_after('Sat, 28 Nov 2026 00:02:00 GMT', now), 120)
        self.assertEqual(brf.retry_after('Fri, 27 Nov 2026 23:58:00 GMT', now), 0)
        for header in (None, 'bogus', '-3'):
            self.assertEqual(brf.retry_after(header, now), 0)
        with patch.object(brf.random, 'uniform', side_effect=[1, 1.2, 1, 1]):
            self.assertEqual(brf.retry_delay(60, 200), 60)
            self.assertEqual(brf.retry_delay(60, 200), 72)
            self.assertEqual(brf.retry_delay(60, 200, '120'), 120)
            self.assertIsNone(brf.retry_delay(60, 100, '120'))

    def test_replay_success_and_stops(self):
        failed = (19, RATE_LIMIT, False)
        cases = (
            ('canary', [failed, (0, '', False)], True, 0, 2, 'RECOVERED'),
            ('canary', [failed, failed], True, 19, 2, 'EXHAUSTED'),
            ('canary', [failed], False, 19, 1, 'FAILED'),
            ('canary', [(19, RATE_LIMIT, True)], True, 19, 1, 'FAILED'),
            ('observe', [failed], True, 19, 1, 'OBSERVED'),
            ('canary', [(-15, RATE_LIMIT, False)], True, -15, 1, 'CANCELLED'),
        )
        for mode, responses, safe, code, count, result in cases:
            with self.subTest(result=result), patch.object(brf, 'mode', return_value=mode), \
                    patch.object(brf, 'execute', side_effect=responses) as execute, \
                    patch.object(brf, 'event') as event, patch.object(brf.time, 'sleep'):
                self.assertEqual(brf.run(brf.MAVEN, ['flutter'], '.', replay_safe=lambda: safe), code)
                self.assertEqual(execute.call_count, count)
                self.assertEqual(event.call_args.args[3], result)

    def test_multiple_git_failures_recover(self):
        failed = (128, GIT_ERROR + 'Connection reset by peer', False)
        with patch.object(brf, 'mode', return_value='canary'), \
                patch.object(brf, 'execute', side_effect=[failed, failed, (0, '', False)]) as execute, \
                patch.object(brf.time, 'sleep') as sleep, patch.object(brf, 'event') as event:
            self.assertEqual(brf.run(brf.GIT, ['git'], '.'), 0)
            self.assertEqual(execute.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(event.call_args.args[3], 'RECOVERED')

    def test_budget_and_cancelled_wait(self):
        failed = (19, RATE_LIMIT, False)
        with patch.object(brf, 'mode', return_value='canary'), \
                patch.object(brf, 'execute', return_value=failed) as execute, \
                patch.object(brf, 'event') as event, patch.object(brf.time, 'sleep') as sleep:
            with patch.object(brf.time, 'monotonic', side_effect=[0, 7199, 7200]):
                self.assertEqual(brf.run(brf.MAVEN, ['flutter'], '.'), 19)
                sleep.assert_not_called()
                self.assertEqual(event.call_args.args[3], 'EXHAUSTED')
            sleep.side_effect = brf.Interrupted(signal.SIGTERM)
            self.assertEqual(brf.run(brf.MAVEN, ['flutter'], '.'), -signal.SIGTERM)
            self.assertEqual(execute.call_count, 2)
            self.assertEqual(event.call_args.args[3], 'CANCELLED')

    @unittest.skipUnless(os.name == 'posix', 'POSIX execution only')
    def test_deadline_kills_child_group_with_open_pipe(self):
        start = time.monotonic()
        command = [sys.executable, '-c',
                   "import subprocess,sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])"]
        with self.assertRaises(subprocess.TimeoutExpired):
            brf.execute(command, '.', None, start + 0.5)
        self.assertLess(time.monotonic() - start, brf.CLEANUP_SECONDS + 1)

    def test_canary_context_and_operation_allowlist(self):
        with patch.dict(os.environ, {'BRF_MODE': 'canary', 'BUILD_CHANNEL': 'stable'}):
            with self.assertRaises(ValueError):
                brf.mode()
        with patch.object(brf, 'mode', return_value='off'):
            with self.assertRaises(ValueError):
                brf.run('sign', ['never-run'], '.')

    def test_evidence_excludes_raw_text(self):
        out = io.StringIO()
        with patch.object(sys, 'stdout', out):
            brf.event(brf.CARGO, 1, 'NET_CONNECT_FAILED', 'OBSERVED', time.monotonic(), None, 101)
        record = json.loads(out.getvalue().removeprefix('BRF '))
        self.assertEqual(record['exit_code'], 101)
        self.assertNotIn('log', record)

    @unittest.skipUnless(os.name == 'posix', 'POSIX recipe only')
    def test_wrapped_recipe_runs_flutter_and_preserves_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flutter = root / 'flutter'
            flutter.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit "${FIXTURE_EXIT:-0}"\n')
            flutter.chmod(0o755)
            script = android_package(
                'flutter build apk "--release" --target-platform android-x64 --split-per-abi\n'
                'printf "post-build\\n"'
            )
            env = {**os.environ, 'PATH': f'{directory}:' + os.environ['PATH'], 'BRF_MODE': 'observe'}
            for code in (0, 19):
                result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=root,
                                        env={**env, 'FIXTURE_EXIT': str(code)}, capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertTrue(result.stdout.startswith('build\napk\n--release\n--target-platform\nandroid-x64\n--split-per-abi\n'))
                self.assertEqual('post-build' in result.stdout, code == 0)

    def test_split_preserves_non_replayed_steps(self):
        commands = ('  flutter build apk "--release" --target-platform android-x64 --split-per-abi\n'
                    '  mv build/app/outputs/flutter-apk/app.apk ../app.apk\n')
        wrapped = android_package(commands)
        self.assertIn('flutter_apk.py', wrapped)
        self.assertNotIn(' build apk', wrapped)
        self.assertIn(' "--release" --target-platform android-x64 --split-per-abi\n', wrapped)
        self.assertEqual(wrapped.splitlines()[-1], commands.splitlines()[-1])
        self.assertEqual(android_package('flutter build apk --target other'), 'flutter build apk --target other')


if __name__ == '__main__':
    unittest.main()
