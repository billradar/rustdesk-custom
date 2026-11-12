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
    def test_exact_baseline_and_formal_release_profiles(self):
        for version in ('1.5.0', '1.5.1'):
            self.assertEqual(patchsets.patchset_for_version(version, 'stable'), 'v2')
        self.assertEqual(patchsets.patchset_for_version('1.4.9', 'stable'), 'v1')
        official = patchsets.profile_for_version('v1.5.3', 'stable')
        self.assertEqual(official['profile'], 'rd-1.5.3')
        self.assertEqual(official['selected'], 'v3')
        self.assertFalse(official['fallback'])
        self.assertFalse(official['compatibility_test_only'])
        self.assertTrue(official['stable_allowed'])
        self.assertEqual(patchsets.mapped('1.5.3'), 'v3')

    def test_historical_candidate_profile_remains_forbidden(self):
        registry = json.loads((ROOT / 'metadata/patch-profiles.json').read_text())
        self.assertFalse(registry['profiles']['rd-1.5.3-candidate']['stable_allowed'])
        registry['exact_versions']['1.5.3'] = 'rd-1.5.3-candidate'
        original = json.loads
        with patch.object(patchsets.json, 'loads', side_effect=lambda raw: copy.deepcopy(registry) if 'exact_versions' in raw else original(raw)):
            candidate = patchsets.profile_for_version('1.5.3', 'nightly')
            self.assertFalse(candidate['stable_allowed'])
            self.assertTrue(candidate['compatibility_test_only'])
            with self.assertRaisesRegex(ValueError, 'Stable'):
                patchsets.patchset_for_version('1.5.3', 'stable')

    def test_formal_153_lock_preflight_and_client_identity_use_current_revision(self):
        from scripts.source.update_identity import write_identity, ABOUT_PATH
        data = dict(channel='stable',version='1.5.3',upstream_tag='1.5.3',upstream_ref='1.5.3',
                    upstream_sha='95cca3f661f635b3cc85c04935fe8d96d8f432ef')
        with patch.dict(os.environ,GITHUB_SHA='b'*40,GITHUB_RUN_ID='42',GITHUB_REPOSITORY_ID='1399548376',GITHUB_REPOSITORY_OWNER_ID='56966687',INCLUDE_WAYLAND='false',ANDROID_PRODUCTION_SIGNING_ENABLED='false'):
            lock = stable_lock.plan(data,'v3')
            with patch.object(channel,'api',side_effect=AssertionError('dry-run must not inspect or write Releases')):
                result = channel.release_preflight(dict(lock),dry_run=True)
            self.assertEqual(result['patch_revision'],'v3.3')
            self.assertTrue(result['build_needed']);self.assertFalse(result['draft_needed'])
            self.assertFalse(result['publish_existing'])
            with tempfile.TemporaryDirectory() as td:
                tree=Path(td);(tree/'src/custom_update').mkdir(parents=True)
                (tree/'src/custom_update/build.json').write_text('{}')
                (tree/ABOUT_PATH).parent.mkdir(parents=True);(tree/ABOUT_PATH).write_text('')
                identity=write_identity(tree,repository='billradar/rustdesk-custom',version='1.5.3',
                                        sha=data['upstream_sha'],variant='standard',run='42',channel='stable',revision='v3.3')
                self.assertEqual(identity['repository_id'],'1399548376')
                self.assertEqual(identity['repository_owner_id'],'56966687')
                with patch.dict(os.environ,GITHUB_REPOSITORY_ID=''):
                    with self.assertRaisesRegex(ValueError,'numeric GitHub'):
                        write_identity(tree,repository='billradar/rustdesk-custom',version='1.5.3',sha=data['upstream_sha'],variant='standard',run='42',channel='stable',revision='v3.3')
                self.assertEqual(identity['revision'],'v3.3')
                self.assertEqual(identity['patchset_version'],'v3.3')
                with self.assertRaises(ValueError):
                    write_identity(tree,repository='billradar/rustdesk-custom',version='1.5.3',
                                   sha=data['upstream_sha'],variant='standard',run='42',channel='stable',revision='v2.8')

    def test_formal_admission_evidence_is_exact_and_does_not_claim_full_builds(self):
        audit=json.loads((ROOT/'docs/audits/stable-1.5.3-admission/review.json').read_text())
        self.assertEqual(audit['official_tag']['ref'],'refs/tags/1.5.3')
        self.assertEqual(audit['official_tag']['object'],{'type':'commit','sha':'95cca3f661f635b3cc85c04935fe8d96d8f432ef'})
        self.assertFalse(audit['official_release']['draft']);self.assertFalse(audit['official_release']['prerelease'])
        self.assertEqual(audit['source_checks']['upstream_sha'],audit['official_tag']['object']['sha'])
        self.assertEqual(audit['source_checks']['profile'],'rd-1.5.3')
        self.assertFalse(audit['patch_content_changed']);self.assertEqual(audit['v2_revision'],8)
        self.assertEqual(len(audit['interfaces']['native']),7)
        for variant in ('standard','sos'):
            checks=audit['source_checks']['variants'][variant]
            self.assertEqual(checks['git_apply_check'],'PASS')
            self.assertEqual(checks['native_helper_compile'],'PASS')
            self.assertEqual(checks['upstream_dpi_preservation'],'PASS')
        self.assertTrue(audit['limitations'])

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
        for version in ('1.5.2', '1.5.4', '2.0.0'):
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
                if source.name not in ('0004-cm-background-window.patch','0005-custom-release-updates.patch'):
                    self.assertEqual(source.read_bytes(), (new / scope / source.name).read_bytes())

    def test_stable_lock_and_preflight_reject_before_external_effects(self):
        for version in ('1.5.2', '1.5.4', '2.0.0'):
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
