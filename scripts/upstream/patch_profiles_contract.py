"""Profile routing, isolation, fail-stop patching and Stable admission regressions."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.upstream import patchsets
from scripts.release import channel, stable_lock

ROOT = Path(__file__).resolve().parents[2]


class ProfileContract(unittest.TestCase):
    def test_exact_baseline_and_candidate_profiles(self):
        for version in ('1.5.0', '1.5.1'):
            self.assertEqual(patchsets.patchset_for_version(version, 'stable'), 'v2')
        self.assertEqual(patchsets.patchset_for_version('1.4.9', 'stable'), 'v1')
        candidate = patchsets.profile_for_version('v1.5.3')
        self.assertEqual(candidate['selected'], 'v3')
        self.assertFalse(candidate['fallback'])
        self.assertTrue(candidate['compatibility_test_only'])
        self.assertFalse(candidate['stable_allowed'])

    def test_exact_profile_precedes_legacy_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'metadata').mkdir()
            registry = json.loads((ROOT / 'metadata/patch-profiles.json').read_text())
            registry['exact_versions']['1.4.9'] = 'rd-1.5.1'
            (root / 'metadata/patch-profiles.json').write_text(json.dumps(registry))
            for scope in ('common', 'sos'):
                (root / 'patchsets/v2' / scope).mkdir(parents=True)
            with patch.object(patchsets, 'ROOT', root):
                result = patchsets.profile_for_version('1.4.9')
            self.assertEqual(result['profile'], 'rd-1.5.1')
            self.assertEqual(result['selected'], 'v2')
            self.assertFalse(result['fallback'])

    def test_unknown_versions_test_latest_but_never_gain_stable(self):
        for version in ('1.5.2', '1.5.4', '2.0.0'):
            for lane in ('ci', 'nightly'):
                result = patchsets.profile_for_version(version, lane)
                self.assertEqual(result['selected'], 'v3')
                self.assertTrue(result['fallback'])
                self.assertTrue(result['compatibility_test_only'])
                self.assertFalse(result['stable_allowed'])
        for version in ('1.5.2', '1.5.3', '2.0.0'):
            with self.assertRaisesRegex(ValueError, 'Stable'):
                patchsets.patchset_for_version(version, 'stable')
            with self.assertRaisesRegex(ValueError, 'Stable'):
                patchsets.mapped(version)

    def test_profile_isolation_rejects_manually_supplied_generation(self):
        for version, selected in (('1.5.1', 'v3'), ('1.5.3', 'v2')):
            with self.assertRaisesRegex(ValueError, 'differs'):
                patchsets.require_selection(version, selected)
        for name in ('v1', 'v2', 'v3'):
            patchsets.verify(name)
        self.assertEqual(patchsets.metadata('v2')['revision'], 8)
        self.assertEqual(patchsets.patch_hash('common', 'v2'),
                         'a9a8ef83aa02890f09beb19e0b4818b268d4d873362f9ccf7ee9b09d3415e5b0')
        self.assertEqual(patchsets.patch_hash('sos', 'v2'), patchsets.patch_hash('sos', 'v3'))
        old = ROOT / 'patchsets/v2'
        new = ROOT / 'patchsets/v3'
        for scope in ('common', 'sos'):
            for source in (old / scope).glob('*.patch'):
                if source.name != '0004-cm-background-window.patch':
                    self.assertEqual(source.read_bytes(), (new / scope / source.name).read_bytes())

    def test_stable_lock_and_preflight_reject_before_external_effects(self):
        for version in ('1.5.2', '1.5.3', '2.0.0'):
            data = dict(channel='stable', version=version, upstream_ref=version,
                        upstream_tag=version, upstream_sha='a'*40, patchset='v3')
            with patch.object(channel, 'release_rows', side_effect=AssertionError('no network')):
                with self.assertRaisesRegex(ValueError, 'Stable'):
                    channel.release_preflight(copy.deepcopy(data))
            with self.assertRaisesRegex(ValueError, 'Stable'):
                stable_lock.plan(data, 'v3')

    def test_missing_latest_does_not_silently_use_older_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'metadata').mkdir()
            shutil.copy(ROOT / 'metadata/patch-profiles.json', root / 'metadata/patch-profiles.json')
            shutil.copytree(ROOT / 'patchsets/v2', root / 'patchsets/v2')
            with patch.object(patchsets, 'ROOT', root):
                with self.assertRaisesRegex(RuntimeError, 'missing'):
                    patchsets.profile_for_version('2.0.0')

    def test_failed_patch_stops_before_next_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(ROOT / 'scripts', root / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT / 'metadata', root / 'metadata')
            folder = root / 'patchsets/v3'
            (folder / 'common').mkdir(parents=True)
            (folder / 'sos').mkdir()
            add = lambda name: f'diff --git a/{name} b/{name}\nnew file mode 100644\n--- /dev/null\n+++ b/{name}\n@@ -0,0 +1 @@\n+applied\n'
            (folder / 'common/0001-first.patch').write_text(add('first'))
            (folder / 'common/0002-broken.patch').write_text('invalid patch\n')
            (folder / 'common/0003-never.patch').write_text(add('never'))
            (folder / 'sos/0001-never-sos.patch').write_text(add('never-sos'))
            (folder / 'patchset.json').write_text('{}')
            with patch.object(patchsets, 'ROOT', root):
                hashes = {key: patchsets.patch_hash(key, 'v3') for key in ('common', 'sos')}
            (folder / 'patchset.json').write_text(json.dumps({'hashes': hashes}))
            source = root / 'source'
            source.mkdir()
            (source / 'Cargo.toml').write_text('version = "1.5.3"\n')
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            result = subprocess.run(['bash', str(root / 'scripts/source/apply_patches.sh'), str(source), 'sos'],
                                    env=dict(os.environ, PATCHSET='v3', BUILD_CHANNEL='ci', PYTHONPATH=str(root)),
                                    capture_output=True, text=True, cwd=root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('STOP: failed patch 0002-broken.patch', result.stderr)
            self.assertTrue((source / 'first').exists())
            self.assertFalse((source / 'never').exists())
            self.assertFalse((source / 'never-sos').exists())


if __name__ == '__main__':
    unittest.main()
