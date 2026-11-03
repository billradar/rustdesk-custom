#!/usr/bin/env python3
"""Offline contracts for the scheduled Stable router."""
import os
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.release import stable_router as router


class StableRouterContract(unittest.TestCase):
    def test_trusted_context_is_required(self):
        base = dict(GITHUB_REPOSITORY=router.REPOSITORY, GITHUB_REF='refs/heads/main',
                    GITHUB_EVENT_NAME='schedule', GITHUB_SHA='a' * 40)
        for key, value in [('GITHUB_REPOSITORY', 'attacker/repo'),
                           ('GITHUB_REF', 'refs/heads/development'),
                           ('GITHUB_EVENT_NAME', 'pull_request'),
                           ('GITHUB_SHA', 'invalid')]:
            with self.subTest(key=key), patch.dict(os.environ, {**base, key: value}):
                with self.assertRaises(ValueError):
                    router.verify_context()

    def test_retry_budget_and_active_run(self):
        success = {'status': 'completed'}
        self.assertEqual(router.run_state([]), 'RETRY')
        self.assertEqual(router.run_state([success]), 'RETRY')
        self.assertEqual(router.run_state([success] * 3), 'EXHAUSTED')
        self.assertEqual(router.run_state([{'status': 'queued'}]), 'ACTIVE')

    def test_run_lookup_skips_any_active_same_source_configuration(self):
        identity = 'e' * 64
        rows = [
            {'display_title': 'Stable v1.5.1 / dry-run / wayland=false / android-signing=false',
             'head_branch': 'main', 'event': 'workflow_dispatch', 'status': 'queued'},
            {'display_title': 'Stable latest / release / wayland=true / android-signing=true',
             'head_branch': 'main', 'event': 'workflow_dispatch', 'status': 'in_progress'},
            {'display_title': 'Stable v1.5.0 / draft / wayland=true / android-signing=false',
             'head_branch': 'main', 'event': 'workflow_dispatch', 'status': 'in_progress'},
            {'display_title': 'Stable v1.5.1 / draft / wayland=true / android-signing=false',
             'head_branch': 'feature', 'event': 'workflow_dispatch', 'status': 'queued'},
        ]
        with patch.object(router, 'api', return_value={'workflow_runs': rows}):
            selected = router.workflow_runs('v1.5.1', identity)
        self.assertEqual(selected, rows[:2])

    def test_manual_stable_runs_are_deduplicated_by_actual_lock_when_completed(self):
        active={'display_title':'Stable v1.5.1 / draft / wayland=true / android-signing=false / identity=manual',
                'head_branch':'main','event':'workflow_dispatch','status':'in_progress'}
        completed=dict(active,status='completed',id=123)
        with patch.object(router, 'api', return_value={'workflow_runs':[active,completed]}), \
             patch.object(router, 'recorded_identity', return_value='e'*64):
            selected=router.workflow_runs('v1.5.1','e'*64)
        self.assertEqual(selected,[active,completed])

    def test_automatic_run_dedup_uses_recorded_identity_and_blocks_unknown_active(self):
        base = dict(display_title='Stable latest / draft / wayland=true / android-signing=false',
                    head_branch='main', event='workflow_dispatch', status='completed')
        matching, different, active = [dict(base, id=i) for i in (1, 2, 3)]
        active['status'] = 'queued'
        with patch.object(router, 'api', return_value={'workflow_runs': [matching, different, active]}), patch.object(router, 'recorded_identity', side_effect=['e'*64, 'f'*64]) as read:
            self.assertEqual(router.workflow_runs('v1.5.1', 'e'*64), [matching, active])
            self.assertEqual(read.call_count, 2)
        with patch.object(router, 'api', return_value={'workflow_runs': [matching]}), patch.object(router, 'recorded_identity', side_effect=ValueError('missing lock')):
            with self.assertRaisesRegex(ValueError, 'missing lock'):
                router.workflow_runs('v1.5.1', 'e'*64)

    def test_historical_lock_reads_latest_attempt_and_checks_run_binding(self):
        from scripts.release.stable_lock import SCHEMA
        data = dict(schema=SCHEMA, channel='stable', workflow_run='123',
                    custom_repository_sha='a'*40, upstream_sha='b'*40, version='1.5.1',
                    patchset='v2', common_patch_hash='c'*64, sos_patch_hash='d'*64,
                    wayland_included=True, wayland_policy_sha256='f'*64,
                    android_signing_enabled=False)
        data['build_identity'] = router.build_identity(data['upstream_sha'], 'v2', 'c'*64, 'd'*64,
            wayland_included=True, wayland_policy_sha256='f'*64, android_signing_enabled=False)
        def download(args, **kwargs):
            root = Path(args[args.index('--dir')+1])
            for attempt in (1, 2):
                folder = root / f'stable-build-lock-123-{attempt}'
                folder.mkdir()
                (folder/'stable-lock.json').write_text(json.dumps(data if attempt == 2 else {}))
            return SimpleNamespace(returncode=0)
        row = dict(id=123, head_sha='a'*40)
        with patch.object(router.subprocess, 'run', side_effect=download):
            self.assertEqual(router.recorded_identity(row),
                             router.lite_identity(data['upstream_sha'],
                                                  data['common_patch_hash'], data['sos_patch_hash']))
            with self.assertRaisesRegex(ValueError, 'provenance'):
                router.recorded_identity(dict(row, head_sha='e'*40))
        with patch.object(router.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(ValueError, 'unavailable'): router.recorded_identity(row)

    def test_existing_build_delegates_to_unified_preflight(self):
        data = {'channel': 'stable'}
        with patch.object(router, 'release_preflight', return_value={'build_needed': False}) as gate:
            self.assertTrue(router.existing_build(data))
            gate.assert_called_once_with(data)
        with patch.object(router, 'release_preflight', return_value={'build_needed': True}):
            self.assertFalse(router.existing_build(data))

    def test_same_version_changed_patchset_is_checked(self):
        with patch.object(router, 'verify_context'), \
             patch.object(router, 'discovery', return_value={'version':'1.5.0','upstream_tag':'v1.5.0',
                                                             'upstream_sha':'a'*40, 'patchset':'v2'}), \
             patch.object(router, 'existing_build', return_value=False), \
             patch.object(router, 'patch_hash', side_effect=['b'*64, 'c'*64]), \
             patch.object(router, 'workflow_runs', return_value=[]), \
             patch.object(router, 'dispatch') as dispatch:
            router.route()
        dispatch.assert_called_once_with('v1.5.0')

    def test_dispatch_pins_official_tag_and_private_draft_mode(self):
        with patch.object(router.subprocess, 'run') as run:
            router.dispatch('v1.5.1')
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ['gh', 'workflow', 'run', 'tag.yml'])
        self.assertIn('--ref', args)
        self.assertIn('-f', args)
        self.assertIn('upstream_ref=v1.5.1', args)
        self.assertIn('release_mode=draft', args)
        self.assertIn('include_wayland=true', args)
        self.assertFalse(any(x.startswith('expected_build_identity=') for x in args))
        self.assertTrue(run.call_args.kwargs['check'])

    def test_stable_direct_dispatch_skips_older_active_batch(self):
        lock = dict(channel='stable', workflow_run='20',
                    custom_repository_sha='a'*40, upstream_tag='v1.5.1',
                    upstream_sha='b'*40, common_patch_hash='c'*64, sos_patch_hash='d'*64)
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            old_dir = os.getcwd()
            try:
                os.chdir(td)
                Path('.work').mkdir()
                Path('.work/stable-lock.json').write_text(json.dumps(lock))
                env = dict(GITHUB_REPOSITORY=router.REPOSITORY, GITHUB_REF='refs/heads/main',
                           GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_RUN_NUMBER='20',
                           GITHUB_RUN_ID='20', GITHUB_SHA='a'*40, RELEASE_MODE='draft',
                           GITHUB_OUTPUT=str(Path(td)/'out'))
                with patch.dict(os.environ, env), patch.object(router, 'workflow_runs',
                     return_value=[{'status':'queued', 'conclusion':None}]) as history:
                    router.dedup()
                self.assertIn('skip=true', Path(td, 'out').read_text())
                self.assertEqual(history.call_args.kwargs['prior_run_number'], 20)
            finally:
                os.chdir(old_dir)

    def test_stable_direct_release_can_publish_existing_success(self):
        lock = dict(channel='stable', workflow_run='21',
                    custom_repository_sha='a'*40, upstream_tag='v1.5.1',
                    upstream_sha='b'*40, common_patch_hash='c'*64, sos_patch_hash='d'*64)
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            old_dir = os.getcwd()
            try:
                os.chdir(td)
                Path('.work').mkdir()
                Path('.work/stable-lock.json').write_text(json.dumps(lock))
                env = dict(GITHUB_REPOSITORY=router.REPOSITORY, GITHUB_REF='refs/heads/main',
                           GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_RUN_NUMBER='21',
                           GITHUB_RUN_ID='21', GITHUB_SHA='a'*40, RELEASE_MODE='release',
                           GITHUB_OUTPUT=str(Path(td)/'out'))
                with patch.dict(os.environ, env), patch.object(router, 'workflow_runs',
                     return_value=[{'status':'completed', 'conclusion':'success'}]):
                    router.dedup()
                self.assertIn('skip=false', Path(td, 'out').read_text())
            finally:
                os.chdir(old_dir)


if __name__ == '__main__':
    unittest.main()
