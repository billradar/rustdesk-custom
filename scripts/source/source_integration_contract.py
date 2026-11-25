"""v4 prepared source uses the same frozen policy and source-aware client identity."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

from scripts.source import api_policy, prepared_source, update_identity
from scripts.upstream import patchsets
ROOT=Path(__file__).resolve().parents[2]
SHA='51f94394ce61e1f3d26229565c326b2862cbdd1f'

class SourceIntegrationContract(unittest.TestCase):
    def test_v4_client_identity_uses_real_patchset_and_requires_numeric_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree=Path(tmp)
            for name in ('src/custom_update/build.json',update_identity.ABOUT_PATH):
                p=tree/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
            args=dict(repository='billradar/rustdesk-custom',version='1.5.3',sha=SHA,
                      variant='standard',run='123',channel='ci')
            with patch.dict(os.environ,GITHUB_REPOSITORY_ID='1399548376',GITHUB_REPOSITORY_OWNER_ID='56966687'):
                data=update_identity.write_identity(tree,**args)
                self.assertEqual(data['patchset_version'],'v4.'+str(patchsets.metadata('v4')['revision']))
                update_identity.verify_about_identity(tree)
                with patch.dict(os.environ,GITHUB_REPOSITORY_ID=''):
                    with self.assertRaisesRegex(ValueError,'numeric GitHub'):
                        update_identity.write_identity(tree,**args)
                with self.assertRaisesRegex(ValueError,'Stable requires'):
                    update_identity.write_identity(tree,**dict(args,channel='stable',revision='v4.1'))

    def test_existing_source_workflow_has_shared_policy_and_no_candidate_promotion(self):
        w=yaml.safe_load((ROOT/'.github/workflows/prepare-source.yml').read_text())
        steps=w['jobs']['prepare']['steps']
        for title in ('Freeze public API endpoints from Actions variables','Check frozen API policy matches across variants'):
            step=next(s for s in steps if s.get('name')==title)
            self.assertEqual(step['if'], """contains(fromJSON('["v3","v4"]'), inputs.patchset)""")
        self.assertFalse(patchsets.profile_for_version('1.5.3','ci',source_sha=SHA)['stable_allowed'])

    def test_ci_and_stable_bridge_use_same_generator_but_separate_receipts(self):
        for name,module in (('build-stable-platforms.yml','macos_arm64 bridge-info'),
                            ('staging-v4-desktop-mobile-packages.yml','macos_arm64_ci bridge-info')):
            w=yaml.safe_load((ROOT/'.github/workflows'/name).read_text())
            steps=w['jobs']['macos-arm64-bridge']['steps']
            step=next(s for s in steps if 'generate_flutter344_bridge.sh' in s.get('run',''))
            self.assertIn(module,step['run'])
            self.assertIn('BRIDGE_FLUTTER',step['env'])
        script=(ROOT/'scripts/build/generate_flutter344_bridge.sh').read_text()
        self.assertIn('git rev-parse HEAD',script)
        self.assertIn('apply_flutter_3.44_source_patches.sh',script)
        self.assertIn('--locked',script)

if __name__=='__main__':
    unittest.main()
