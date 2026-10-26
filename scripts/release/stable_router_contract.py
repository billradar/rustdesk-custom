#!/usr/bin/env python3
"""Offline contracts for the scheduled Stable router."""
import os
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

    def test_run_lookup_matches_only_target_stable_variant(self):
        rows = [
            {'display_title': 'Stable v1.5.1 / draft / wayland=true', 'head_branch': 'main', 'event': 'workflow_dispatch', 'head_sha': 'a' * 40},
            {'display_title': 'Stable v1.5.1 / release / wayland=true', 'head_branch': 'main', 'event': 'workflow_dispatch'},
            {'display_title': 'Stable v1.5.1 / draft / wayland=false', 'head_branch': 'main', 'event': 'workflow_dispatch'},
            {'display_title': 'Stable v1.5.1 / draft', 'head_branch': 'main', 'event': 'workflow_dispatch', 'head_sha': 'c' * 40},
            {'display_title': 'Stable v1.5.1 / draft / wayland=true', 'head_branch': 'feature', 'event': 'workflow_dispatch', 'head_sha': 'a' * 40},
        ]
        rows.append({'display_title': 'Stable v1.5.1 / draft / wayland=true', 'head_branch': 'main',
                     'event': 'workflow_dispatch', 'head_sha': 'b' * 40})
        with patch.object(router, 'api', return_value={'workflow_runs': rows}):
            selected = router.workflow_runs('v1.5.1', 'a' * 40)
        self.assertEqual(len(selected), 1)

    def test_existing_build_delegates_to_unified_preflight(self):
        data = {'channel': 'stable'}
        with patch.object(router, 'release_preflight', return_value={'build_needed': False}) as gate:
            self.assertTrue(router.existing_build(data))
            gate.assert_called_once_with(data)
        with patch.object(router, 'release_preflight', return_value={'build_needed': True}):
            self.assertFalse(router.existing_build(data))

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
        self.assertTrue(run.call_args.kwargs['check'])


if __name__ == '__main__':
    unittest.main()
