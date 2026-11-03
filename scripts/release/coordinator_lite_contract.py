"""Coordinator Lite's sole source+patchset routing identity and active gate."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml

from scripts.release.coordinator_lite import (build_identity, from_hashes, matching_state,
                                              patchset_sha256, verify_worker_context)


class CoordinatorLiteContract(unittest.TestCase):
    def test_only_upstream_and_combined_patchset_sha_define_identity(self):
        p = patchset_sha256('b'*64, 'c'*64)
        self.assertEqual(len(p), 64)
        self.assertEqual(from_hashes('a'*40, 'b'*64, 'c'*64),
                         build_identity('a'*40, p))
        self.assertNotEqual(from_hashes('a'*40, 'b'*64, 'c'*64),
                            from_hashes('d'*40, 'b'*64, 'c'*64))
        self.assertNotEqual(from_hashes('a'*40, 'b'*64, 'c'*64),
                            from_hashes('a'*40, 'b'*64, 'd'*64))

    def test_in_progress_queued_waiting_unknown_are_skipped(self):
        for status in ('queued', 'pending', 'waiting', 'in_progress', None):
            with self.subTest(status=status):
                self.assertEqual(matching_state([{'status':status}]), 'ACTIVE')
        self.assertEqual(matching_state([{'status':'completed', 'conclusion':'success'}]), 'SUCCESS')
        self.assertEqual(matching_state([{'status':'completed', 'conclusion':'failure'}]), 'RETRY')


    def test_stateless_worker_trusts_only_current_main_channel(self):
        repo = 'example/repo'
        base = dict(GITHUB_REPOSITORY=repo, GITHUB_REF='refs/heads/main',
                    GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_SHA='a'*40,
                    GITHUB_RUN_ATTEMPT='2')
        for channel, filename in (('nightly', 'nightly.yml'), ('stable', 'tag.yml')):
            env = dict(base, BUILD_CHANNEL=channel,
                       GITHUB_WORKFLOW_REF=f'{repo}/.github/workflows/{filename}@refs/heads/main')
            with self.subTest(channel=channel), patch.dict(os.environ, env, clear=True):
                verify_worker_context()  # A legitimate leaf-job rerun is allowed.
                for key, invalid in (('GITHUB_REPOSITORY', 'attacker/repo'),
                                     ('GITHUB_REF', 'refs/heads/development'),
                                     ('GITHUB_EVENT_NAME', 'pull_request'),
                                     ('GITHUB_SHA', 'bad'),
                                     ('BUILD_CHANNEL', 'ci'),
                                     ('GITHUB_WORKFLOW_REF', repo+'/.github/workflows/ci.yml@refs/heads/main')):
                    with self.subTest(key=key), patch.dict(os.environ, {key: invalid}):
                        with self.assertRaises(ValueError):
                            verify_worker_context()
                with patch.dict(os.environ, {'GITHUB_WORKFLOW_REF': ''}):
                    with self.assertRaises(ValueError):
                        verify_worker_context()

    def test_live_workers_use_lite_before_source_not_retired_admission(self):
        root = Path(__file__).resolve().parents[2]
        for file in (root/'.github/workflows').glob('*.yml'):
            self.assertNotIn('scripts.release.coordinator.runtime', file.read_text(), file.name)
        for name in ('build-platform.yml', 'build-wayland-target.yml'):
            with self.subTest(workflow=name):
                workflow = yaml.safe_load((root/'.github/workflows'/name).read_text())
                self.assertEqual(workflow['permissions'], {'contents': 'read'})
                steps = workflow['jobs']['platform-build']['steps']
                gate = next(i for i, s in enumerate(steps)
                            if 'coordinator_lite verify-worker' in s.get('run', ''))
                source = next(i for i, s in enumerate(steps)
                              if s.get('id') == 'source')
                self.assertLess(gate, source)
                self.assertIn("github.ref == 'refs/heads/main'", steps[gate]['if'])
                self.assertIn("github.event_name == 'workflow_dispatch'", steps[gate]['if'])
                self.assertNotIn('GH_TOKEN', steps[gate].get('env', {}))
                self.assertEqual(steps[gate]['run'],
                                 'python3 -m scripts.release.coordinator_lite verify-worker')



if __name__ == '__main__':
    unittest.main()
