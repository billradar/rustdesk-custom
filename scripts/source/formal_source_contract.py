"""Formal prepared sources may only be unpacked by explicit test-only consumers."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

from scripts.build import formal_validation as formal, recipe_admission
from scripts.source import prepared_source

ROOT=Path(__file__).resolve().parents[2]
SHA=recipe_admission.BASE
ENV=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='billradar/rustdesk-custom',
         GITHUB_EVENT_NAME='pull_request',BUILD_CHANNEL='ci',BUILD_CONFIGURATION='TEST ONLY',
         PATCHSET='v4',UPSTREAM_EXPECTED_SHA=SHA,CLIENT_RELEASE_IDENTITY='false',
         CLIENT_PATCH_REVISION='',BUILD_FLAVOR='',GITHUB_SHA='b'*40,GITHUB_RUN_ID='123')

class FormalSourceContract(unittest.TestCase):
    def test_marker_binds_source_and_epoch(self):
        with patch.dict(os.environ,ENV,clear=True):
            marker=formal.context(SHA)
            manifest={'formal_validation':marker,'upstream_sha':SHA,'patchset':'v4',
                      'custom_repository':ENV['GITHUB_REPOSITORY'],'custom_repository_sha':ENV['GITHUB_SHA'],
                      'prepare_workflow_run':'123','client_update_identity':{'channel':'ci'},
                      'build_adapter_signature':recipe_admission.source(SHA)['build_signature']}
            self.assertEqual(formal.verify_manifest(manifest),marker)
            for key,value in (('BUILD_CHANNEL','stable'),('BUILD_CONFIGURATION','PRODUCTION'),
                              ('CLIENT_RELEASE_IDENTITY','true'),('GITHUB_EVENT_NAME','push'),
                              ('BUILD_FLAVOR','unattended-wayland'),('GITHUB_RUN_ID','124')):
                with self.subTest(key=key),patch.dict(os.environ,{key:value}),self.assertRaises(ValueError):
                    formal.verify_manifest(manifest)
            with self.assertRaises(ValueError):
                formal.verify_manifest(dict(manifest,build_adapter_signature='0'*64))
            with tempfile.TemporaryDirectory() as td:
                tree=Path(td)
                (tree/'source-manifest.json').write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError,'cannot enter a release worker'):
                    prepared_source.verify_tree(tree,'standard',SHA,'v4','b'*40,'123')

    def test_existing_reusable_workflow_is_isolated(self):
        w=yaml.safe_load((ROOT/'.github/workflows/prepare-source.yml').read_text())
        self.assertFalse(w['on']['workflow_call']['inputs']['formal_validation']['default']
                         if 'on' in w else w[True]['workflow_call']['inputs']['formal_validation']['default'])
        self.assertEqual(w['permissions'],{'contents':'read'})
        steps=w['jobs']['prepare']['steps']
        self.assertEqual(next(s for s in steps if s.get('name')=='Freeze public branding variables with defaults')['if'],
                         '!inputs.formal_validation')
        self.assertIn('--formal-validation',next(s for s in steps if s.get('name')=='Prepare Common once and fork independent variant sources')['run'])

if __name__=='__main__':
    unittest.main()
