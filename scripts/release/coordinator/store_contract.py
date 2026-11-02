"""Concurrent and fault-injected Git REST transport contracts; no credentials."""
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from threading import Barrier, Lock
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from .contract import NOW, TOKEN, discovered
from .identity import canonical
from .model import advance, bind, BuildState, reserve
from .store import (APIError, AmbiguousWrite, Conflict, GitHubAPI, GitRefStore,
                    decode_record, encode_record)


class MemoryAPI:
    """GitHub-shaped object database with atomic FF-only ref updates."""
    def __init__(self):
        self.objects, self.refs = {}, {}
        self.lock = Lock()
        self.fault = ''
        self.read_error = 0
        self.barrier = None

    def _object(self, kind, data):
        sha = hashlib.sha1(kind.encode() + b'\0' + canonical(data)).hexdigest()
        self.objects[sha] = (kind, data)
        return {'sha': sha}

    def request(self, method, path, data=None):
        endpoint = path.split('/git/', 1)[1]
        if method == 'GET' and self.read_error:
            raise APIError(self.read_error)
        if self.barrier and (endpoint == 'refs' or endpoint.startswith('refs/')):
            self.barrier.wait(timeout=10)
        with self.lock:
            if method == 'POST' and endpoint == 'blobs':
                return self._object('blob', data)
            if method == 'POST' and endpoint == 'trees':
                return self._object('tree', data)
            if method == 'POST' and endpoint == 'commits':
                return self._object('commit', data)
            if method == 'GET' and endpoint.startswith('ref/'):
                ref = 'refs/' + endpoint[4:]
                if ref not in self.refs:
                    raise APIError(404)
                return {'ref': ref, 'object': {'type': 'commit', 'sha': self.refs[ref]}}
            if method == 'GET':
                kind, sha = endpoint.split('/', 1)
                stored, value = self.objects[sha]
                if kind == 'blobs':
                    return dict(encoding='base64', content=b64encode(value['content'].encode()).decode())
                if kind == 'trees':
                    return dict(tree=value['tree'], truncated=False)
                if kind == 'commits':
                    return dict(parents=[{'sha': p} for p in value['parents']], tree={'sha': value['tree']})
                raise AssertionError(endpoint)
            if self.fault == 'before':
                self.fault = ''
                raise AmbiguousWrite('request interrupted before ref mutation')
            if method == 'POST' and endpoint == 'refs':
                ref = data['ref']
                if ref in self.refs:
                    raise APIError(422)
            elif method == 'PATCH' and endpoint.startswith('refs/'):
                ref = 'refs/' + endpoint[5:]
                if data['force'] is not False:
                    raise AssertionError('Forced journal mutation')
                cursor = data['sha']
                while cursor != self.refs[ref]:
                    parents = self.objects[cursor][1]['parents']
                    if not parents:
                        raise APIError(422)
                    cursor = parents[0]
            else:
                raise AssertionError((method, endpoint))
            self.refs[ref] = data['sha']
            if self.fault == 'after':
                self.fault = ''
                raise AmbiguousWrite('response lost after server accepted ref')
            return {'ref': ref, 'object': {'sha': data['sha']}}


def store(api, record=None, channel=None):
    record = record or discovered()
    return GitRefStore(api, 'example/release-test', channel or record.channel, record.build_identity)


def reservation(record=None, token=TOKEN):
    return reserve(record or discovered(), token, NOW, NOW + timedelta(hours=1))


class PersistenceContract(unittest.TestCase):
    def test_record_round_trip_rejects_unknown_schema(self):
        self.assertEqual(decode_record(encode_record(reservation().after)), reservation().after)
        data = encode_record(discovered())
        data['extra'] = 'unknown'
        with self.assertRaises(ValueError):
            decode_record(data)

    def test_same_identity_concurrent_admission_has_one_winner(self):
        api = MemoryAPI()
        api.barrier = Barrier(2)
        tokens = [TOKEN, '22222222-2222-4222-8222-222222222222']
        def claim(token):
            try:
                return store(api).append(reservation(token=token))
            except Conflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as workers:
            rows = list(workers.map(claim, tokens))
        self.assertEqual(sum(row is not None for row in rows), 1)
        self.assertEqual(len(api.refs), 1)
        self.assertIn(store(api).load().record.reservation_id, tokens)

    def test_different_identities_are_independent(self):
        api = MemoryAPI()
        api.barrier = Barrier(2)
        records = [discovered(), replace(discovered(), build_identity='f'*64)]
        with ThreadPoolExecutor(max_workers=2) as workers:
            rows = list(workers.map(lambda r: store(api, r).append(reservation(r)), records))
        self.assertEqual(len(api.refs), 2)
        self.assertEqual({row.record.build_identity for row in rows}, {r.build_identity for r in records})

    def test_competing_child_commits_and_stale_writer(self):
        api = MemoryAPI()
        journal = store(api)
        first = journal.append(reservation())
        one = bind(first.record, TOKEN, 1, '123', NOW)
        two = bind(first.record, TOKEN, 1, '456', NOW)
        winner = journal.append(one, first)
        with self.assertRaises(Conflict):
            journal.append(two, first)
        self.assertEqual(journal.load(), winner)
        running = journal.append(advance(winner.record, TOKEN, 1, BuildState.RUNNING, NOW), winner)
        self.assertEqual(running.record.attempt, 1)
        with self.assertRaises(Conflict):
            journal.append(two, first)

    def test_network_loss_before_or_after_ref_write(self):
        for position in ('before', 'after'):
            with self.subTest(position=position):
                api = MemoryAPI()
                api.fault = position
                journal = store(api)
                if position == 'before':
                    with self.assertRaises(AmbiguousWrite):
                        journal.append(reservation())
                    self.assertIsNone(journal.load())
                else:
                    result = journal.append(reservation())
                    self.assertEqual(journal.load(), result)
                # A rerun uses a fresh read/decision; it does not duplicate root.
                api.fault = ''
                if journal.load():
                    with self.assertRaises(Conflict):
                        journal.append(reservation(token='22222222-2222-4222-8222-222222222222'))

    def test_api_errors_are_never_a_missing_identity(self):
        for status in (403, 429, 500, 503):
            api = MemoryAPI()
            api.read_error = status
            with self.subTest(status=status), self.assertRaises(APIError):
                store(api).load()

    def test_wrong_namespace_or_identity_rejected(self):
        api = MemoryAPI()
        with self.assertRaises(ValueError):
            GitRefStore(api, 'example/release-test', 'stable', 'f'*64, namespace='main')
        with self.assertRaises(ValueError):
            store(api, channel='nightly').append(reservation())

    def test_forged_success_overwrite_and_attempt_increment_rejected(self):
        from .model import Event
        api = MemoryAPI()
        journal = store(api)
        event = reservation()
        with self.assertRaises(ValueError):
            journal.append(Event(NOW, 'reserve', event.before, replace(event.after, attempt=2)))
        first = journal.append(event)
        bound = journal.append(bind(first.record, TOKEN, 1, '123', NOW), first)
        running = journal.append(advance(bound.record, TOKEN, 1, BuildState.RUNNING, NOW), bound)
        success = journal.append(advance(running.record, TOKEN, 1, BuildState.SUCCEEDED, NOW), running)
        self.assertEqual(journal.load(), success)
        with self.assertRaises(ValueError):
            journal.append(Event(NOW, 'advance', success.record, running.record), success)

    def test_real_git_server_rejects_competing_siblings(self):
        import os
        from pathlib import Path
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory(prefix='coordinator-git-') as temp:
            root = Path(temp)
            def git(*args, input=None):
                return subprocess.run(['git', *args], input=input, text=True, capture_output=True,
                                      env=dict(os.environ, GIT_AUTHOR_NAME='Coordinator Fixture',
                                               GIT_AUTHOR_EMAIL='fixture@example.invalid',
                                               GIT_COMMITTER_NAME='Coordinator Fixture',
                                               GIT_COMMITTER_EMAIL='fixture@example.invalid'))
            self.assertEqual(git('init', '--bare', str(root/'server')).returncode, 0)
            self.assertEqual(git('init', '--bare', str(root/'objects')).returncode, 0)
            prefix = ('--git-dir=' + str(root/'objects'),)
            tree = git(*prefix, 'mktree', input='').stdout.strip()
            base = git(*prefix, 'commit-tree', tree, input='initial journal').stdout.strip()
            left = git(*prefix, 'commit-tree', tree, '-p', base, input='token one').stdout.strip()
            right = git(*prefix, 'commit-tree', tree, '-p', base, input='token two').stdout.strip()
            ref = 'refs/heads/coordinator-integration/v1/identity'
            def push(sha):
                return git(*prefix, 'push', str(root/'server'), sha + ':' + ref).returncode
            self.assertEqual(push(base), 0)
            barrier = Barrier(2)
            def compete(sha):
                barrier.wait(timeout=10)
                return push(sha)
            with ThreadPoolExecutor(max_workers=2) as workers:
                results = list(workers.map(compete, [left, right]))
            self.assertEqual(results.count(0), 1)
            self.assertEqual(len([r for r in results if r != 0]), 1)
            # No force/merge/reset is used; the losing sibling remains rejected.
            loser = right if results[0] == 0 else left
            self.assertNotEqual(push(loser), 0)

    def test_read_retry_bounded_and_write_never_replayed(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        for status in (429, 500, 503):
            error = urllib.error.HTTPError('https://api.github.com', status, 'temporary', {'Retry-After': '2'}, None)
            sleeps = []
            api = GitHubAPI('fictional-test-token', sleep=sleeps.append)
            with patch('urllib.request.urlopen', side_effect=[error, response]) as call:
                self.assertEqual(api.request('GET', 'repos/example/test/git/ref/heads/main'), {})
                self.assertEqual(call.call_count, 2)
            self.assertEqual(sleeps, [2])
            with patch('urllib.request.urlopen', side_effect=error) as call:
                with self.assertRaises(APIError):
                    api.request('PATCH', 'repos/example/test/git/refs/heads/state', {'force': False})
                self.assertEqual(call.call_count, 1)
            with patch('urllib.request.urlopen', side_effect=error) as call:
                with self.assertRaises(APIError):
                    api.request('GET', 'repos/example/test/git/ref/heads/main')
                self.assertEqual(call.call_count, 3)


if __name__ == '__main__':
    unittest.main()
