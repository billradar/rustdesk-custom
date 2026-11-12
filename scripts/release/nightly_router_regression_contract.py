"""Regression checks for Nightly source pinning and retry safety."""
import os
from pathlib import Path
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

    def test_publication_cannot_bypass_draft_deduplication(self):
        self.assertTrue(nightly.skip_duplicate_dispatch('SUCCESS','draft'))
        self.assertFalse(nightly.skip_duplicate_dispatch('SUCCESS','dry-run'))
        for state in ('ACTIVE','SUCCESS','COOLDOWN','RETRY'):
            with self.assertRaises(ValueError):nightly.skip_duplicate_dispatch(state,'release')

    def test_nightly_router_checkbox_and_build_gate(self):
        import yaml
        root = Path(__file__).resolve().parents[2]
        for path in ('upstream-nightly.yml', 'nightly.yml'):
            w = yaml.safe_load((root/'.github/workflows'/path).read_text())
            option = w['on']['workflow_dispatch']['inputs']['force_retry']
            self.assertEqual(option['type'], 'boolean')
            self.assertIs(option['default'], False)
        router = yaml.safe_load((root/'.github/workflows/upstream-nightly.yml').read_text())
        build = yaml.safe_load((root/'.github/workflows/nightly.yml').read_text())
        route_step = next(s for s in router['jobs']['route']['steps'] if 'route' in s.get('run',''))
        dedup_step = next(s for s in build['jobs']['resolve']['steps'] if s.get('id') == 'dedup')
        self.assertIn('inputs.force_retry', route_step['env']['FORCE_RETRY'])
        self.assertIn('inputs.force_retry', dedup_step['env']['FORCE_RETRY'])

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

    def test_release_dispatch_is_rejected_before_history_lookup(self):
        with patch.dict(os.environ,GITHUB_REPOSITORY=nightly.REPO,GITHUB_REF='refs/heads/main',GITHUB_EVENT_NAME='workflow_dispatch',RELEASE_MODE='release'),patch.object(nightly,'api') as read:
            with self.assertRaises(ValueError):nightly.dedup()
            read.assert_not_called()

    def test_nightly_force_router_propagates_to_build(self):
        env = dict(GITHUB_REPOSITORY='example/repo', GITHUB_REF='refs/heads/main',
                   GITHUB_EVENT_NAME='workflow_dispatch', FORCE_RETRY='true',
                   ANDROID_PRODUCTION_SIGNING_ENABLED='false')
        data = dict(upstream_sha='a'*40, official_run_id='123', upstream_version='1.5.1', patchset='v2',
                    common_patch_hash='b'*64, sos_patch_hash='c'*64)
        with patch.dict(os.environ, env), \
             patch.object(nightly,'api',return_value={'workflow_runs':[]}), \
             patch.object(nightly,'decide',return_value='RETRY') as decision, \
             patch.object(nightly.subprocess,'run') as dispatch:
            nightly.route(data)
        self.assertTrue(decision.call_args.kwargs['force_retry'])
        self.assertIn('force_retry=true', dispatch.call_args.args[0])
        self.assertIn('display_label=' + nightly.display_label(data),
                      dispatch.call_args.args[0])

    def test_retry_policy_does_not_count_cancelled_as_retryable(self):
        from scripts.release.router_retry_policy import decide
        self.assertEqual(decide([dict(status='completed', conclusion='cancelled',
                                      created_at='2026-11-01T00:00:00Z')]), 'REVIEW')

if __name__ == '__main__':
    unittest.main()
