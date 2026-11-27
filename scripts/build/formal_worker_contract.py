"""Formal package workers use the run-bound source, never release qualification."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
from scripts.build import formal_validation as formal, recipe_admission
from scripts.source.formal_source_contract import ENV
from scripts.upstream.patchsets import patch_hash
from scripts.platform import platform_adapter as adapter

ROOT=Path(__file__).resolve().parents[2]

class FormalWorkerContract(unittest.TestCase):
    def test_worker_identity_rejects_cross_run_variant_and_wrong_context(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,dict(ENV,FORMAL_VALIDATION='true',VARIANT='standard'),clear=True):
            old=Path.cwd()
            try:
                os.chdir(td)
                tree=Path('.work/native/source');tree.mkdir(parents=True)
                sha=recipe_admission.BASE
                marker=formal.context(sha)
                m=dict(formal_validation=marker,upstream_sha=sha,patchset='v4',variant='standard',
                       custom_repository=ENV['GITHUB_REPOSITORY'],custom_repository_sha=ENV['GITHUB_SHA'],
                       prepare_workflow_run='123',client_update_identity={'channel':'ci'},
                       build_adapter_signature=recipe_admission.source(sha)['build_signature'],
                       common_patch_hash=patch_hash('common','v4'),sos_patch_hash=None)
                path=tree/'source-manifest.json';path.write_text(json.dumps(m))
                with patch.object(formal.subprocess,'check_output',return_value=sha+'\n'):
                    evidence=formal.worker_identity(tree)
                    self.assertFalse(evidence['release_eligible'])
                    with self.assertRaisesRegex(ValueError,'variant mismatch'):
                        formal.worker_identity(tree,'sos')
                    for k,v in [('FORMAL_VALIDATION','false'),('GITHUB_RUN_ID','124'),('BUILD_CHANNEL','stable'),('BUILD_CONFIGURATION','PRODUCTION')]:
                        with self.subTest(key=k),patch.dict(os.environ,{k:v}),self.assertRaises(ValueError):
                            formal.worker_identity(tree)
                    with patch.dict(os.environ,BUILD_CONFIGURATION='CI_PACKAGE_TEST',PLATFORM='linux'):
                        self.assertEqual(formal.worker_identity(tree),evidence)
                    with patch.dict(os.environ,BUILD_CONFIGURATION='CI_PACKAGE_TEST',PLATFORM='android'),self.assertRaises(ValueError):
                        formal.worker_identity(tree)
                    (tree/'macos-arm64-ci-transform.json').write_text('{}')
                    with self.assertRaisesRegex(ValueError,'formal worker evidence'):
                        adapter.check(tree,'macos','aarch64',channel='ci')
            finally:
                os.chdir(old)

    def test_all_supported_package_targets_unpack_formal_source(self):
        for filename,job in [('build-validation.yml','package'),('build-validation-linux.yml','native')]:
            w=yaml.safe_load((ROOT/'.github/workflows'/filename).read_text())
            prepare=w['jobs']['formal-prepare']
            self.assertEqual(prepare['uses'],'./.github/workflows/prepare-source.yml')
            self.assertTrue(prepare['with']['formal_validation'])
            worker=w['jobs'][job]
            self.assertIn('formal-prepare',worker['needs'])
            self.assertEqual(worker['env']['FORMAL_VALIDATION'],'true')
            steps=worker['steps']
            runs='\n'.join(s.get('run','') for s in steps)
            self.assertIn('prepared_source.py unpack',runs)
            self.assertIn('--formal-validation',runs)
            self.assertNotIn('scripts/source/apply_patches.sh',runs)
            self.assertNotIn('secrets.',json.dumps(worker))
            if job=='package':
                self.assertIn('macos_arm64 transform .work/native/source',runs)
                self.assertNotIn('macos_arm64_ci transform .work/native/source',runs)

if __name__=='__main__':
    unittest.main()
