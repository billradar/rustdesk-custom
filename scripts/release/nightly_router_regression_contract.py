"""Regression checks for Nightly source pinning and retry safety."""
import os
import unittest
from unittest.mock import patch
from scripts.release import nightly

class NightlyRouterRegression(unittest.TestCase):
    def test_skipped_dispatch_is_not_counted_as_attempt(self):
        row = dict(id=7, display_title='Nightly latest / ' + 'a'*40 +
                   ' / draft / wayland=true / android-signing=false',
                   event='workflow_dispatch', head_branch='main',
                   status='completed', conclusion='success')
        discovery = dict(upstream_sha='b'*40, patchset='v2',
                         common_patch_hash='c'*64, sos_patch_hash='d'*64,
                         dedup_state='COOLDOWN')
        with patch.object(nightly, 'source_sha_from_run', return_value='b'*40), \
             patch.object(nightly, 'discovery_from_run', return_value=discovery):
            nightly.annotate_history([row], 'b'*40)
        self.assertTrue(row['_nightly_identity_skipped'])
        self.assertNotIn('_nightly_identity', row)

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
