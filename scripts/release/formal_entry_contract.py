"""Fault tests for the explicit non-main dry-run entry and shared package evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
from scripts.build import formal_validation as formal, recipe_admission
from scripts.release import formal_entry as entry
from scripts.source.formal_source_contract import ENV

ROOT=Path(__file__).resolve().parents[2]

class EntryContract(unittest.TestCase):
    def test_gate_only_accepts_manual_non_release_exact_source(self):
        for channel,file in entry.FILES.items():
            ref='refs/heads/feature/source-aware-patch-profiles-v4'
            env=dict(ENV,FORMAL_ENTRY_CHANNEL=channel,FORMAL_SOURCE_SHA=recipe_admission.BASE,
                     GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_REF=ref,
                     GITHUB_WORKFLOW_REF=ENV['GITHUB_REPOSITORY']+'/.github/workflows/'+file+'@'+ref,
                     RELEASE_MODE='dry-run',INCLUDE_WAYLAND='false',FORCE_RETRY='false')
            self.assertEqual(entry.gate(env),recipe_admission.BASE)
            for key,value in [('RELEASE_MODE','draft'),('INCLUDE_WAYLAND','true'),('FORCE_RETRY','true'),
                              ('GITHUB_REF','refs/heads/main'),('GITHUB_EVENT_NAME','schedule'),
                              ('FORMAL_SOURCE_SHA',recipe_admission.SUCCESSOR),('FORMAL_SOURCE_SHA',''),
                              ('REQUESTED_REF','1.5.3'),('OFFICIAL_RUN_ID','123'),('ROUTER_EXPECTED_SHA','a'*40),
                              ('GITHUB_WORKFLOW_REF','other')]:
                with self.subTest(channel=channel,key=key),self.assertRaises(ValueError):
                    entry.gate(dict(env,**{key:value}))

    def test_entry_has_no_release_authority_and_reuses_single_source_pair(self):
        for file in entry.FILES.values():
            w=yaml.safe_load((ROOT/'.github/workflows'/file).read_text())
            self.assertEqual(w['on']['workflow_dispatch']['inputs']['formal_source_sha']['default'],'')
            jobs=w['jobs']
            self.assertIn("inputs.formal_source_sha == ''",jobs['resolve']['if'])
            gate=jobs['formal-gate'];call=jobs['formal-dry-run']
            self.assertEqual(gate['permissions'],{'contents':'read'})
            self.assertEqual(call['needs'],'formal-gate')
            self.assertEqual(call['uses'],'./.github/workflows/staging-v4-desktop-mobile-packages.yml')
            self.assertTrue(call['with']['include_linux'])
            self.assertNotIn('secrets',call)
            for key in ('android-sign','aggregate','draft'):
                self.assertIn("inputs.formal_source_sha == ''",jobs[key]['if'])
        desktop=yaml.safe_load((ROOT/'.github/workflows/staging-v4-desktop-mobile-packages.yml').read_text())
        linux=yaml.safe_load((ROOT/'.github/workflows/staging-v4-linux-packages.yml').read_text())
        self.assertEqual(desktop['jobs']['linux']['with']['reuse_prepared'],True)
        self.assertIn('formal-prepare.outputs.standard_artifact',desktop['jobs']['linux']['with']['prepared_standard'])
        self.assertIn('formal-prepare.outputs.sos_artifact',desktop['jobs']['linux']['with']['prepared_sos'])
        for key in ('compatibility','formal-prepare'):
            self.assertEqual(linux['jobs'][key]['if'],'!inputs.reuse_prepared')
        self.assertNotIn('secrets',desktop['jobs']['linux'])
        self.assertIn('linux',desktop['jobs']['formal-summary']['needs'])

    def test_aggregate_rejects_missing_and_cross_variant_reports(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,ENV,clear=True):
            root=Path(td)/'reports';root.mkdir()
            receipts=Path(td)/'receipts';receipts.mkdir()
            marker=formal.context(recipe_admission.BASE)
            expected=recipe_admission.validate(recipe_admission.read())['targets']
            with self.assertRaisesRegex(ValueError,'target report directory'):
                entry.aggregate(root,receipts)
            for target,t in expected.items():
                platform,arch,variant=target.split('-')
                folder=root/t['report_artifact_name'];folder.mkdir()
                ext={'android':['apk'],'windows':['exe','msi'],'macos':['dmg'],'linux':['deb','rpm','rpm']}[platform]
                info=dict(kind='CI_FIXTURE_PACKAGE_SMOKE',schema='linux-v4-ci-package-smoke-v1',result='PASS',
                          release_eligible=False,platform=platform,arch=arch,architecture=arch,variant=variant,
                          upstream_sha=recipe_admission.BASE,package_count=len(ext),native_architecture='PASS',
                          fixture_configuration_markers='PASS',
                          packages=[dict(name=str(i)+'.'+e,sha256='a'*64,size=123) for i,e in enumerate(ext)],
                          formal_source_evidence=dict(formal_validation=marker,variant=variant,release_eligible=False,
                                                      source_manifest_sha256=('b' if variant=='standard' else 'c')*64))
                if platform=='macos' and arch=='aarch64':
                    d=receipts/('v4-formal-mac-arm64-'+variant+'-receipt');d.mkdir()
                    (d/'source-manifest.json').write_text(json.dumps({'fixture':variant}))
                    (d/'macos-arm64-transform.json').write_text('{}')
                    info['formal_source_evidence']['macos_arm64_receipt_sha256']=entry.digest(d/'macos-arm64-transform.json')
                (folder/'package-report.json').write_text(json.dumps(info))
            # Cross-source evidence must fail even before Mac receipt validation.
            path=root/expected['android-x86_64-standard']['report_artifact_name']/'package-report.json'
            info=json.loads(path.read_text())
            bad=copy.deepcopy(info);bad['formal_source_evidence']['source_manifest_sha256']='d'*64
            path.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError,'different prepared sources'):
                entry.aggregate(root,receipts)
            path.write_text(json.dumps(info))
            with self.assertRaisesRegex(ValueError,'Mac receipt/source digest mismatch'):
                entry.aggregate(root,receipts)

if __name__=='__main__':
    unittest.main()
