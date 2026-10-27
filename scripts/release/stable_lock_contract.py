"""Stable automatic identity and mandatory downstream lock regressions."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
from scripts.release import stable_lock as lock

ROOT = Path(__file__).resolve().parents[2]


class LockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'lock.json'
        self.env = patch.dict(os.environ, dict(GITHUB_SHA='a'*40, GITHUB_RUN_ID='123',
            GITHUB_RUN_ATTEMPT='1', INCLUDE_WAYLAND='true',
            ANDROID_PRODUCTION_SIGNING_ENABLED='false', STABLE_LOCK_REQUIRED='true'), clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.data = dict(channel='stable', version='1.5.0', upstream_sha='b'*40,
                         upstream_tag='1.5.0', upstream_ref='1.5.0')

    def create(self):
        result = lock.create(self.data, 'v2', self.path)
        os.environ.update(STABLE_LOCK_PATH=str(self.path), STABLE_LOCK_SHA256=result['lock_sha256'],
                          EXPECTED_BUILD_IDENTITY=result['build_identity'])
        return result

    def test_manual_computes_and_router_checks_same_identity(self):
        result = self.create()
        self.assertEqual(lock.current()['build_identity'], result['build_identity'])
        lock.create(self.data, 'v2', self.path, result['build_identity'])
        with self.assertRaisesRegex(ValueError, 'Router build identity'):
            lock.create(self.data, 'v2', self.path, 'f'*64)

    def test_missing_or_tampered_lock_fails(self):
        with self.assertRaises(ValueError): lock.current()
        self.create()
        self.path.write_text(self.path.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'): lock.current()

    def test_run_commit_and_policy_cannot_drift(self):
        self.create()
        for key, value in dict(GITHUB_SHA='c'*40, GITHUB_RUN_ID='124', INCLUDE_WAYLAND='false',
                               ANDROID_PRODUCTION_SIGNING_ENABLED='true').items():
            with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                with self.assertRaises(ValueError): lock.current()

    def test_version_controls_patchset(self):
        with self.assertRaisesRegex(ValueError, 'version selection'):
            lock.create(self.data, 'v1', self.path)

    def test_preflight_must_match_lock(self):
        result = self.create()
        with patch.object(lock.channel, 'release_preflight', return_value={'build_identity': 'f'*64}):
            with self.assertRaises(ValueError): lock.preflight()
        with patch.object(lock.channel, 'release_preflight', return_value=result):
            self.assertEqual(lock.preflight(), result)

    def test_artifact_source_and_both_variants_required(self):
        result = self.create()
        infos = [dict(variant=v, upstream_sha=result['upstream_sha'], upstream_version=result['version'],
                      patchset='v2', common_patch_hash=result['common_patch_hash'],
                      sos_patch_hash=result['sos_patch_hash'] if v == 'sos' else None,
                      custom_repository_sha='a'*40, build_run='123') for v in ('standard', 'sos')]
        lock.require(infos)
        with self.assertRaises(ValueError): lock.require(infos[:1])
        for key in ('upstream_sha', 'upstream_version', 'patchset', 'common_patch_hash',
                    'sos_patch_hash', 'custom_repository_sha', 'build_run'):
            changed = [dict(i) for i in infos]
            changed[1][key] = 'wrong'
            with self.subTest(key=key), self.assertRaises(ValueError): lock.require(changed)

    def test_attempt_specific_artifact_can_be_reused_by_failed_job_retry(self):
        first = self.create()
        with patch.dict(os.environ, GITHUB_RUN_ATTEMPT='2'):
            lock.current()
            second = lock.create(self.data, 'v2', self.path)
        self.assertNotEqual(first['lock_artifact'], second['lock_artifact'])
        self.assertEqual(first['lock_sha256'], second['lock_sha256'])

    def test_workflow_makes_lock_mandatory_and_freezes_signing(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/tag.yml').read_text())
        jobs = workflow['jobs']
        self.assertIn('auto', workflow['run-name'])
        for name in ('aggregate', 'publish-existing', 'release', 'draft'):
            with self.subTest(job=name):
                job = jobs[name]
                self.assertEqual(job['env']['STABLE_LOCK_REQUIRED'], 'true')
                for field in ('STABLE_LOCK_SHA256', 'EXPECTED_BUILD_IDENTITY'):
                    self.assertIn('needs.', job['env'][field])
                self.assertTrue(any('lock_artifact' in s.get('with', {}).get('name', '') for s in job['steps']))
                self.assertIn('outputs.signing_enabled', job['env']['ANDROID_PRODUCTION_SIGNING_ENABLED'])
        signer = jobs['android-production-sign'] if 'android-production-sign' in jobs else next(j for j in jobs.values() if 'vars.ANDROID_PRODUCTION_SIGNING_ENABLED' in j.get('if', '') and 'signing_enabled' in j.get('if', ''))
        self.assertIn("needs.resolve.outputs.signing_enabled == 'true'", signer['if'])
        self.assertIn('vars.ANDROID_PRODUCTION_SIGNING_ENABLED', signer['if'])


if __name__ == '__main__':
    unittest.main()
