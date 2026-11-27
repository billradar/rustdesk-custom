"""Configuration validation, frozen-source binding and v3/v4 Actions wiring."""
import json
from pathlib import Path
import tempfile
import unittest
from scripts.source import api_policy as policy

class PolicyContract(unittest.TestCase):
    def tree(self, root):
        for name in (policy.RUST, policy.DART, policy.WSS):
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('// placeholder')

    def test_optional_configuration_and_strict_origin_validation(self):
        self.assertFalse(policy.resolve('', '')['enabled'])
        self.assertEqual(policy.resolve('https://[0:0:0:0:0:0:0:1]/', 'https://backup.test.invalid')['primary'], 'https://[::1]')
        for value in ['http://api.test.invalid', 'https://user:pw@api.test.invalid', 'https://api.test.invalid/api',
                      'https://api.test.invalid?q=x', 'https://api.test.invalid/#x', 'https://api.test.invalid:99999',
                      'https://api.test.invalid\n', 'https://api.test.invalid/$(x)']:
            with self.assertRaises(ValueError):
                policy.resolve('https://primary.test.invalid', value)
        with self.assertRaises(ValueError):
            policy.resolve('https://api.test.invalid', 'https://api.test.invalid:443/')

    def test_frozen_source_and_changed_build_primary_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tree = Path(td); self.tree(tree)
            value = policy.resolve('https://Primary.test.invalid:443/', 'https://backup.test.invalid')
            digest = policy.apply(tree, value)
            self.assertEqual(policy.verify(tree, digest, 'https://primary.test.invalid'), value)
            self.assertIn('const PROFILE_FALLBACK: &str = "https://backup.test.invalid";',
                          (tree / policy.WSS).read_text())
            with self.assertRaises(ValueError):
                policy.verify(tree, digest, 'https://changed.test.invalid')
            for name in (policy.RUST, policy.DART, policy.WSS, policy.SNAPSHOT):
                p = tree / name; old = p.read_bytes(); p.write_bytes(old + b' ')
                with self.assertRaises(ValueError): policy.verify(tree, digest)
                p.write_bytes(old)
            other = policy.apply(tree, policy.resolve('https://primary.test.invalid', 'https://different.test.invalid'))
            self.assertNotEqual(digest, other)

    def test_current_workflow_reads_variables_without_production_literals(self):
        import yaml
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / '.github/workflows/prepare-source.yml').read_text())
        step = next(s for s in workflow['jobs']['prepare']['steps'] if s.get('name') == 'Freeze public API endpoints from Actions variables')
        self.assertEqual(step['if'], """!inputs.formal_validation && contains(fromJSON('["v3","v4"]'), inputs.patchset)""")
        self.assertEqual(step['env']['RUSTDESK_API_SERVER'], '${{ vars.RUSTDESK_API_SERVER }}')
        self.assertEqual(step['env']['RUSTDESK_API_FALLBACK_SERVER'], "${{ vars.RUSTDESK_API_FALLBACK_SERVER || '' }}")
        for generation in ('v3', 'v4'):
            patch = (root / f'patchsets/{generation}/common/0007-api-failover.patch').read_text()
            self.assertNotIn('houxnan.com', patch)

if __name__ == '__main__': unittest.main()
