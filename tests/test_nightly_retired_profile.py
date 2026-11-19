"""Regression: retired historical Nightly profiles must not start new builds."""
import base64
import unittest
from unittest.mock import patch

from scripts.release import nightly


class RetiredNightlyProfileTest(unittest.TestCase):
    def setUp(self):
        self.sha = 'a' * 40
        self.run = {
            'status': 'completed', 'conclusion': 'success',
            'head_branch': 'master', 'event': 'schedule',
            'path': '.github/workflows/flutter-nightly.yml',
            'head_repository': {'full_name': 'rustdesk/rustdesk'},
            'head_sha': self.sha, 'id': 123,
            'html_url': 'https://github.com/rustdesk/rustdesk/actions/runs/123',
        }

    def api(self, path):
        if path == 'repos/rustdesk/rustdesk':
            return {'default_branch': 'master'}
        if 'flutter-nightly.yml/runs?' in path:
            return {'workflow_runs': [self.run]}
        if '/contents/Cargo.toml?' in path:
            cargo = '[package]\nname = "rustdesk"\nversion = "1.5.1"\n'
            return {'content': base64.b64encode(cargo.encode()).decode()}
        raise AssertionError(path)

    @patch.object(nightly, 'api')
    def test_router_skips_retired_profile_with_provenance(self, mock_api):
        mock_api.side_effect = self.api
        data = nightly.discover(allow_retired_skip=True)
        self.assertEqual(data['dedup_state'], 'RETIRED_PROFILE')
        self.assertEqual(data['upstream_sha'], self.sha)
        self.assertEqual(data['upstream_version'], '1.5.1')
        self.assertFalse(data['build_needed'])
        self.assertNotIn('patchset', data)

    @patch.object(nightly, 'api')
    def test_downstream_resolve_still_rejects_retired_profile(self, mock_api):
        mock_api.side_effect = self.api
        with self.assertRaisesRegex(ValueError, 'Retired Patchset v2'):
            nightly.discover()


if __name__ == '__main__':
    unittest.main()
