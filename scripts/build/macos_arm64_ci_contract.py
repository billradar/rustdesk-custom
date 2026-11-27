"""Mac ARM v4 CI candidate: fail closed on wrong source, bridge or release channel."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.build import macos_arm64_ci as ci
from scripts.platform import platform_adapter as adapter

class MacArmCiContract(unittest.TestCase):
    def test_receipt_never_enters_release_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/ci.RECEIPT).write_text('{}')
            for channel in ('stable','nightly'):
                with self.subTest(channel=channel):
                    with self.assertRaisesRegex(ValueError,'not release approved'):
                        adapter.check(root,'macos','aarch64',channel=channel)

    def test_exact_sha_and_recipe_only(self):
        p=dict(ci.TOOLS,platform='macos',architecture='aarch64',
               signature=ci.PLATFORM_SIGNATURE,ci_candidate_only=True,
               stable_allowed=False,candidate_source_sha=ci.SOURCE)
        with patch.object(ci,'source_sha',return_value='a'*40):
            with self.assertRaisesRegex(ValueError,'unknown candidate platform identity'):
                ci.check_profile(Path('.'),p)
        with patch.object(ci,'source_sha',return_value=ci.SOURCE),patch.object(ci,'blob',return_value='a'*40):
            with self.assertRaisesRegex(ValueError,'workflow/helper bytes changed'):
                ci.check_profile(Path('.'),p)
        with patch.object(ci,'source_sha',return_value=ci.SOURCE):
            with self.assertRaisesRegex(ValueError,'unknown candidate platform identity'):
                ci.check_profile(Path('.'),dict(p,stable_allowed=True))

    def test_bridge_same_source_run_and_exact_inventory(self):
        p={'bridge_flutter':'3.44.8','patch_sha256':'d'*64}
        info={'upstream_sha':ci.SOURCE,'custom_sha':'b'*40,'workflow_run':'123',
              'flutter':'3.44.8','patch_sha256':'d'*64,
              'files':{n:'e'*64 for n in ci.BRIDGE_FILES}}
        with patch.dict(os.environ,GITHUB_SHA='b'*40,GITHUB_RUN_ID='123'):
            ci.validate_bridge(info,p)
            for change in ({'workflow_run':'124'},{'upstream_sha':'a'*40},
                           {'flutter':'3.22.3'},{'files':{}},{'custom_sha':'c'*40}):
                with self.assertRaisesRegex(ValueError,'bridge identity/inventory mismatch'):
                    ci.validate_bridge(dict(info,**change),p)

    def test_fixture_context_is_not_production(self):
        with patch.dict(os.environ,BUILD_CHANNEL='stable',BUILD_CONFIGURATION='PRODUCTION'):
            with self.assertRaisesRegex(ValueError,'fixture context'):
                ci.context(Path('.'),worker=True)

    def test_new_dialog_transform_is_protected(self):
        self.assertIn('flutter/lib/common/widgets/dialog.dart',ci.TRANSFORMS)
        self.assertNotIn('flutter/lib/common/widgets/dialog.dart',ci.stable.TRANSFORMS)
        self.assertIn('Cargo.toml',ci.PROTECTED)
        self.assertIn(ci.stable.bridge_recipe.PATCH,ci.PROTECTED)

if __name__=='__main__':
    unittest.main()
