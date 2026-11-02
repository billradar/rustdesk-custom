"""Regression checks for Nightly source pinning and retry safety."""
import os
import unittest
from unittest.mock import patch
from scripts.release import nightly

class NightlyRouterRegression(unittest.TestCase):
    def test_discover_rejects_invalid_pinned_run(self):
        with patch.dict(os.environ, {'OFFICIAL_RUN_ID': 'not-a-run'}), \
             patch.object(nightly, 'api', return_value={'default_branch': 'master'}):
            with self.assertRaisesRegex(ValueError, 'Invalid official run ID'):
                nightly.discover()

    def test_active_unresolved_identity_blocks_duplicate(self):
        row = dict(id=1, event='workflow_dispatch', head_branch='main',
                   status='queued', display_title='Nightly latest / ' + 'a'*40 +
                   ' / draft / wayland=true / android-signing=false',
                   _nightly_identity_unresolved=True, _upstream_sha='')
        self.assertEqual(nightly.route_state([row], 'b'*64, upstream_sha='c'*40), 'ACTIVE')

    def test_retry_policy_does_not_count_cancelled_as_retryable(self):
        from scripts.release.router_retry_policy import decide
        self.assertEqual(decide([dict(status='completed', conclusion='cancelled',
                                      created_at='2026-11-01T00:00:00Z')]), 'REVIEW')

if __name__ == '__main__':
    unittest.main()
