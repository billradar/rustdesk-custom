"""The formal v2 Mac receipt uses the production inventory checks, never release authority."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.build import macos_arm64 as mac, macos_arm64_ci as candidate, recipe_admission, formal_validation as formal
from scripts.source.formal_source_contract import ENV

class FormalMacContract(unittest.TestCase):
    def test_formal_receipt_inventory_and_release_denial(self):
        with patch.dict(os.environ,ENV,clear=True):
            sha=recipe_admission.BASE
            marker=formal.context(sha)
            p=dict(candidate.TOOLS,**candidate.BRIDGE_TOOLS,platform='macos',architecture='aarch64',
                   signature=candidate.PLATFORM_SIGNATURE,bridge_signature=candidate.BRIDGE_SIGNATURE,
                   candidate_source_sha=sha,stable_allowed=False,macos_flutter344=True,
                   patch_sha256='d'*64,source_workflow_sha256='e'*64,
                   reviewed_transform_inputs=list(candidate.TRANSFORMS),
                   reviewed_bridge_inputs=list(candidate.BRIDGE_FILES),production_receipt_qualified=False,
                   **recipe_admission.annotations(sha))
            before={n:'a'*64 for n in candidate.INPUTS}
            after={n:'b'*64 for n in candidate.INPUTS}
            manifest=dict(upstream_sha=sha,patchset='v4',custom_repository=ENV['GITHUB_REPOSITORY'],
                          custom_repository_sha=ENV['GITHUB_SHA'],prepare_workflow_run='123',
                          client_update_identity={'channel':'ci'},formal_validation=marker,variant='standard',
                          build_adapter_signature=candidate.BRIDGE_SIGNATURE,
                          files=dict(before,**{mac.bridge_recipe.PATCH:'d'*64,'.github/workflows/flutter-build.yml':'e'*64}))
            info=dict(upstream_sha=sha,custom_sha=ENV['GITHUB_SHA'],workflow_run='123',
                      flutter=p['bridge_flutter'],patch_sha256=p['patch_sha256'],
                      files={n:after[n] for n in candidate.BRIDGE_FILES})
            r=dict(schema_version=2,formal_validation=marker,release_eligible=False,profile=p,
                   upstream_sha=sha,variant='standard',source_manifest_sha256='f'*64,
                   bridge=info,before=before,after=after)
            self.assertEqual(mac.receipt_checks(r,manifest,'f'*64,formal_validation=True),p)
            with self.assertRaisesRegex(ValueError,'formal validation receipt'):
                mac.receipt_checks(r,manifest,'f'*64)
            for change in ('dialog','approval','variant','bridge'):
                bad=copy.deepcopy(r)
                if change=='dialog':bad['after'].pop(candidate.TRANSFORMS[-1])
                elif change=='approval':bad['release_eligible']=True
                elif change=='variant':bad['variant']='sos'
                else:bad['bridge']['workflow_run']='124'
                with self.subTest(change=change),self.assertRaises(ValueError):
                    mac.receipt_checks(bad,manifest,'f'*64,formal_validation=True)

if __name__=='__main__':
    unittest.main()
