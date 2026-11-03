"""Coordinator Lite's sole source+patchset routing identity and active gate."""
import unittest
from pathlib import Path

from scripts.release.coordinator_lite import build_identity, from_hashes, matching_state, patchset_sha256, verify_worker_context


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


    def worker_environment(self, channel):
        workflow, name = {
            'nightly': ('nightly.yml', 'Nightly Build Pipeline'),
            'stable': ('tag.yml', 'Stable Release Pipeline'),
        }[channel]
        repo = 'billradar/rustdesk-custom'
        return {
            'BUILD_CHANNEL': channel,
            'GITHUB_REPOSITORY': repo,
            'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_WORKFLOW': name,
            'GITHUB_WORKFLOW_REF': f'{repo}/.github/workflows/{workflow}@refs/heads/main',
            'GITHUB_SHA': 'a' * 40,
            'UPSTREAM_EXPECTED_SHA': 'b' * 40,
            'PATCHSET': 'v2',
            'GITHUB_RUN_ID': '41667958044',
            'GITHUB_RUN_ATTEMPT': '1',
        }

    def test_reusable_workers_accept_trusted_lite_root_context(self):
        for channel in ('stable', 'nightly'):
            with self.subTest(channel=channel):
                self.assertIsNone(verify_worker_context(self.worker_environment(channel)))

    def test_reusable_workers_reject_mismatched_context(self):
        changes = {
            'BUILD_CHANNEL': 'ci',
            'GITHUB_REPOSITORY': '../other',
            'GITHUB_REF': 'refs/heads/development',
            'GITHUB_EVENT_NAME': 'pull_request',
            'GITHUB_WORKFLOW': 'CI - Patch and Build compatibility',
            'GITHUB_WORKFLOW_REF': 'billradar/rustdesk-custom/.github/workflows/tag.yml@refs/heads/main',
            'GITHUB_SHA': 'wrong',
            'UPSTREAM_EXPECTED_SHA': 'z' * 40,
            'PATCHSET': 'v0',
            'GITHUB_RUN_ID': '0',
            'GITHUB_RUN_ATTEMPT': '0',
        }
        for key, value in changes.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_worker_context(dict(self.worker_environment('nightly'), **{key: value}))

    def test_both_reusable_worker_workflows_use_lite_not_retired_receipt(self):
        root = Path(__file__).resolve().parents[2]
        for path in ('build-platform.yml', 'build-wayland-target.yml'):
            with self.subTest(workflow=path):
                content = (root / '.github/workflows' / path).read_text()
                self.assertIn('python3 -m scripts.release.coordinator_lite worker-guard', content)
                self.assertNotIn('scripts.release.coordinator.runtime guard', content)
                self.assertIn('Verify immutable prepared input before native dependencies', content)


if __name__ == '__main__':
    unittest.main()
