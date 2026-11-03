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

    def test_manual_release_not_blocked_by_successful_draft(self):
        # The Lite identity is source+patch only. A release is an explicit
        # publication action and must pass all downstream signed-asset gates.
        self.assertEqual(nightly.nightly_identity(dict(upstream_sha='a'*40,
                         common_patch_hash='b'*64,sos_patch_hash='c'*64), 'draft'),
                         nightly.nightly_identity(dict(upstream_sha='a'*40,
                         common_patch_hash='b'*64,sos_patch_hash='c'*64), 'release'))
        self.assertTrue(nightly.skip_duplicate_dispatch('SUCCESS', 'draft'))
        self.assertFalse(nightly.skip_duplicate_dispatch('SUCCESS', 'dry-run'))
        self.assertFalse(nightly.skip_duplicate_dispatch('ACTIVE', 'dry-run'))
        self.assertFalse(nightly.skip_duplicate_dispatch('COOLDOWN', 'dry-run'))
        self.assertFalse(nightly.skip_duplicate_dispatch('SUCCESS', 'release'))
        self.assertTrue(nightly.skip_duplicate_dispatch('ACTIVE', 'release'))
        self.assertTrue(nightly.skip_duplicate_dispatch('COOLDOWN', 'release'))
        self.assertFalse(nightly.skip_duplicate_dispatch('RETRY', 'release'))
        with self.assertRaises(ValueError):
            nightly.skip_duplicate_dispatch('UNKNOWN', 'release')

    def test_main_dry_run_never_queries_lite_history(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'result'
            env=dict(GITHUB_REPOSITORY='example/repo',GITHUB_REF='refs/heads/main',
                     GITHUB_EVENT_NAME='workflow_dispatch',RELEASE_MODE='dry-run',
                     INCLUDE_WAYLAND='true',ANDROID_PRODUCTION_SIGNING_ENABLED='false',
                     GITHUB_OUTPUT=str(output))
            with patch.dict(os.environ,env), \
                 patch.object(nightly,'api',side_effect=AssertionError('Dry-run history queried')) as history:
                nightly.dedup()
            history.assert_not_called()
            self.assertIn('skip=false',output.read_text())

    def test_release_dedup_invokes_existing_validation_path(self):
        import tempfile
        import json
        from pathlib import Path
        fixture={'upstream_sha':'a'*40,'common_patch_hash':'b'*64,
                 'sos_patch_hash':'c'*64,'patchset':'v2'}
        prior=dict(id=20, run_number=20, event='workflow_dispatch',
                   head_branch='main', display_title='Nightly latest / '+'d'*40+
                   ' / draft / wayland=true / android-signing=false',
                   status='completed', conclusion='success')
        current=dict(id=21,run_number=21)
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'out'
            env={'GITHUB_REPOSITORY':'example/repo','GITHUB_REF':'refs/heads/main',
                 'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ID':'21',
                 'RELEASE_MODE':'release','INCLUDE_WAYLAND':'true',
                 'ANDROID_PRODUCTION_SIGNING_ENABLED':'false',
                 'UPSTREAM_EXPECTED_SHA':'a'*40,'PATCHSET':'v2','GITHUB_OUTPUT':str(output)}
            with patch.dict(os.environ, env), \
                 patch.object(nightly, 'repository', return_value='example/repo'), \
                 patch.object(nightly, 'api', return_value={'workflow_runs':[current,prior]}), \
                 patch.object(nightly, 'patch_hash', side_effect=['b'*64,'c'*64]), \
                 patch.object(nightly, 'source_sha_from_run', return_value='a'*40), \
                 patch.object(nightly, 'discovery_from_run', return_value=fixture):
                nightly.dedup()
            self.assertIn('skip=false',output.read_text())

    def test_retry_policy_does_not_count_cancelled_as_retryable(self):
        from scripts.release.router_retry_policy import decide
        self.assertEqual(decide([dict(status='completed', conclusion='cancelled',
                                      created_at='2026-11-01T00:00:00Z')]), 'REVIEW')

if __name__ == '__main__':
    unittest.main()
