"""Formal recipe admission never grants Stable/Nightly release authorization."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.build import recipe_admission as admission, build_adapter, macos_arm64
from scripts.platform import platform_adapter
from scripts.upstream import patchsets

class RecipeAdmissionContract(unittest.TestCase):
    def test_exact_scope_and_patch_revision(self):
        record=admission.validate(admission.read())
        self.assertEqual(len(record['targets']),13)
        self.assertIs(record['release_eligible'],False)
        for sha in (admission.BASE,admission.SUCCESSOR):
            self.assertIn('build_signature',admission.source(sha))
            with self.assertRaisesRegex(ValueError,'Stable requires'):
                patchsets.profile_for_version('1.5.3','stable',source_sha=sha)
            self.assertTrue(patchsets.profile_for_version('1.5.3','nightly',source_sha=sha)['compatibility_test_only'])
        with self.assertRaisesRegex(ValueError,'unapproved exact source'):
            admission.source('d'*40)
        for change in (dict(release_eligible=True),dict(revision=999),dict(targets={}),
                       dict(production_signing='PASS')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                admission.validate(dict(record,**change))

    def test_reviewed_signature_does_not_change_normal_adapter_gate(self):
        sha=admission.BASE;row=admission.source(sha)
        profile={'upstream_version':'1.5.3','signature':row['build_signature']}
        candidate={'source_sha':sha,'signature':row['build_signature'],'id':'fixture'}
        with patch.object(build_adapter,'inspect',return_value=(dict(profile),{})), \
             patch.object(build_adapter,'_ci_candidate',return_value=candidate):
            reviewed=build_adapter.check(Path('.'),recipe_review=True)
            self.assertTrue(reviewed['production_recipe_approved'])
            self.assertIs(reviewed['release_eligible'],False)
            with self.assertRaisesRegex(ValueError,'unknown critical'):
                build_adapter.check(Path('.'))
        with self.assertRaisesRegex(ValueError,'signature mismatch'):
            admission.check_build(candidate,dict(profile,signature='0'*64))

    def test_platform_review_scope(self):
        row=admission.source(admission.BASE)
        p=dict(signature=row['platforms']['windows']['signature'],runner='windows-2022',
               candidate_source_sha=admission.BASE)
        self.assertTrue(admission.check_platform(p,'windows','x86_64')['production_recipe_approved'])
        for name,arch in (('windows','aarch64'),('ios','aarch64'),('web','web')):
            with self.subTest(name=name,arch=arch),self.assertRaisesRegex(ValueError,'not approved'):
                admission.check_platform(p,name,arch)
        with tempfile.TemporaryDirectory() as td:
            tree=Path(td)
            (tree/'macos-arm64-ci-transform.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'pristine'):
                platform_adapter.check(tree,'macos','aarch64',channel='stable',recipe_review=True)

    def test_mac_review_never_uses_windows_policy_or_accepts_ci_receipt(self):
        from scripts.build import macos_arm64_ci as candidate
        sha=admission.BASE
        p=dict(candidate.TOOLS,signature=candidate.PLATFORM_SIGNATURE,platform='macos',architecture='aarch64',
               candidate_source_sha=sha,ci_candidate_only=True,stable_allowed=False,
               **admission.annotations(sha))
        with patch.object(candidate,'source_sha',return_value=sha), \
             patch.object(candidate,'check_profile',return_value=dict(p,macos_flutter344=True)), \
             patch.object(macos_arm64.bridge_recipe,'check',side_effect=AssertionError('Windows policy is not Mac authority')):
            reviewed=macos_arm64.review_profile(Path('.'),p)
            self.assertIn('flutter/lib/common/widgets/dialog.dart',reviewed['reviewed_transform_inputs'])
            self.assertFalse(reviewed['production_receipt_qualified'])
        with self.assertRaises(ValueError):
            macos_arm64.approved(reviewed)

if __name__=='__main__':
    unittest.main()
