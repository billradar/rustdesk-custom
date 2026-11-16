"""Abandoned patchsets are immutable evidence and cannot enter any new build."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts.upstream import patchsets, patchset_version

ROOT = Path(__file__).resolve().parents[2]

class RetirementContract(unittest.TestCase):
    def test_archive_bytes_and_complete_inventory_are_frozen(self):
        snapshot = json.loads((ROOT / 'metadata/abandoned-patchsets.json').read_text())
        for name, expected in snapshot['files'].items():
            directory = ROOT / 'archive/abandoned-patchsets' / name
            self.assertFalse((ROOT / 'patchsets' / name).exists())
            actual = {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in directory.rglob('*') if p.is_file()}
            self.assertEqual(actual, expected)
            data = patchsets.metadata(name)
            self.assertEqual(data['hashes'], {scope: patchsets.patch_hash(scope, name) for scope in ('common', 'sos')})
            with self.assertRaisesRegex(ValueError, 'Archived'):
                patchset_version.bump(name)

    def test_all_channels_reject_legacy_versions_without_fallback(self):
        for version in ('1.4.9', '1.5.0', '1.5.1'):
            for channel in ('ci', 'nightly', 'stable'):
                with self.assertRaisesRegex(ValueError, 'Retired'):
                    patchsets.profile_for_version(version, channel)
        for name in ('v1', 'v2'):
            with self.assertRaisesRegex(ValueError, 'Retired'): patchsets.verify(name)
            from scripts.source.prepared_source import verify_tree
            with self.assertRaisesRegex(ValueError, 'Retired'):
                verify_tree(Path('/does-not-exist'), 'standard', 'a'*40, name, 'b'*40, '1')

    def test_raw_patch_application_and_workflow_fail_before_build(self):
        import os
        import yaml
        for name in ('v1', 'v2'):
            with tempfile.TemporaryDirectory() as td:
                result = subprocess.run(['bash', str(ROOT / 'scripts/source/apply_patches.sh'), td, 'standard'],
                                        env=dict(os.environ, PATCHSET=name), capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Retired', result.stderr)
                self.assertEqual(list(Path(td).iterdir()), [])
        workflow = yaml.safe_load((ROOT / '.github/workflows/prepare-source.yml').read_text())
        names = [s.get('name') for s in workflow['jobs']['prepare']['steps']]
        self.assertLess(names.index('Reject abandoned Patchsets before fetching or building'), names.index('Fetch exact official source'))

if __name__ == '__main__': unittest.main()
