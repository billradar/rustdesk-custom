"""Credential-free Mac ARM source/bridge/worker/package receipt fault tests."""
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
import yaml

from scripts.build import macos_arm64 as mac
from scripts.platform import platform_adapter as adapter

ROOT=Path(__file__).resolve().parents[2]


class MacArmContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.tree=self.root/'source';self.bridge=self.root/'bridge'
        self.tree.mkdir();self.bridge.mkdir()
        self.p=dict(json.loads(mac.POLICY.read_text())['profiles'][0],platform='macos',
                    architecture='aarch64',macos_flutter344=True)
        protected=set(adapter.FILES+['.github/workflows/flutter-build.yml',mac.bridge_recipe.PATCH]+mac.INPUTS)
        for name in protected:
            path=self.tree/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('original '+name)
        (self.tree/'build.py').write_text("command = 'MACOSX_DEPLOYMENT_TARGET=10.14 cargo build --locked'\n")
        (self.tree/'Cargo.toml').write_text('[package.metadata.bundle]\nosx_minimum_system_version = "10.14"\n# variant features stay intact\n')
        self.p['patch_sha256']=mac.sha(self.tree/mac.bridge_recipe.PATCH)
        self.p['source_workflow_sha256']=mac.sha(self.tree/'.github/workflows/flutter-build.yml')
        policy=self.root/'policy.json';policy.write_text(json.dumps({'schema_version':1,'profiles':[
            {k:self.p[k] for k in mac.POLICY_KEYS}]}))
        self.policy=patch.object(mac,'POLICY',policy);self.policy.start();self.addCleanup(self.policy.stop)
        self.manifest={'variant':'standard','upstream_sha':'a'*40,'custom_repository_sha':'b'*40,
                       'prepare_workflow_run':'123','files':{n:mac.sha(self.tree/n) for n in protected}}
        (self.tree/'source-manifest.json').write_text(json.dumps(self.manifest))
        for name in mac.BRIDGE_FILES:
            path=self.bridge/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('new '+name)
        self.info={'upstream_sha':'a'*40,'custom_sha':'b'*40,'workflow_run':'123',
                   'flutter':self.p['bridge_flutter'],'patch_sha256':self.p['patch_sha256'],
                   'files':{n:mac.sha(self.bridge/n) for n in mac.BRIDGE_FILES}}
        self.write_info()
        self.env=patch.dict(os.environ,UPSTREAM_EXPECTED_SHA='a'*40,GITHUB_SHA='b'*40,GITHUB_RUN_ID='123',
                            RUNNER_OS='macOS',RUNNER_ARCH='ARM64');self.env.start();self.addCleanup(self.env.stop)

    def write_info(self):
        (self.bridge/mac.BRIDGE_INFO).write_text(json.dumps(self.info))

    def apply(self,tree):
        for name in mac.TRANSFORMS:(tree/name).write_text('transformed '+name)

    def transform(self):
        with patch.object(mac,'profile',return_value=self.p),patch.object(mac,'verify_sdk'), \
             patch.object(mac,'original',return_value=(self.p,{})), \
             patch.object(mac.bridge_recipe,'apply',side_effect=self.apply):
            mac.transform(self.tree,self.bridge)

    def verify(self, **kwargs):
        with patch.object(mac,'verify_sdk'),patch.object(mac,'original',return_value=(self.p,{})):
            return mac.verified(self.tree, **kwargs)

    def deployment_edit(self):
        for name, old, new in (
                ('build.py', b'MACOSX_DEPLOYMENT_TARGET=10.14', b'MACOSX_DEPLOYMENT_TARGET=12.3'),
                ('Cargo.toml', b'osx_minimum_system_version = "10.14"', b'osx_minimum_system_version = "12.3"')):
            path=self.tree/name;path.write_bytes(path.read_bytes().replace(old,new))

    def test_post_build_accepts_only_exact_reviewed_deployment_edits(self):
        original=(self.tree/'source-manifest.json').read_bytes();self.transform()
        self.deployment_edit()
        with self.assertRaisesRegex(ValueError,'protected recipe'):self.verify()
        self.assertEqual(self.verify(post_build=True)[0],self.p)
        self.assertEqual((self.tree/'source-manifest.json').read_bytes(),original)
        path=self.tree/'Cargo.toml';valid=path.read_bytes()
        for invalid in (valid.replace(b'12.3',b'13.0'), valid+b'\n[features]\nsos = []\n'):
            path.write_bytes(invalid)
            with self.assertRaisesRegex(ValueError,'protected recipe'):self.verify(post_build=True)
        path.write_bytes(valid)
        (self.tree/'build.py').write_bytes((self.tree/'build.py').read_bytes()+b'\n# unexpected edit\n')
        with self.assertRaisesRegex(ValueError,'protected recipe'):self.verify(post_build=True)

    def test_post_build_requires_deployment_edit_and_keeps_other_recipe_guards(self):
        self.transform()
        with self.assertRaisesRegex(ValueError,'protected recipe'):self.verify(post_build=True)
        self.deployment_edit();self.verify(post_build=True)
        path=self.tree/'build.rs';path.write_text('unreviewed Rust build script')
        with self.assertRaisesRegex(ValueError,'protected recipe'):self.verify(post_build=True)

    def test_post_build_does_not_ignore_sos_variant_or_bridge_drift(self):
        self.manifest['variant']='sos'
        (self.tree/'source-manifest.json').write_text(json.dumps(self.manifest))
        self.transform();self.deployment_edit();self.verify(post_build=True)
        path=self.tree/mac.BRIDGE_FILES[0];path.write_text('stale bridge')
        with self.assertRaisesRegex(ValueError,'source drift'):self.verify(post_build=True)

    def test_packaging_selects_post_build_verification_before_native_payload_checks(self):
        from scripts.platform import platform_package as package
        profile=self.root/'platform-profile.json';profile.write_text(json.dumps(self.p))
        def local_path(value):
            return profile if str(value)=='.work/platform-profile.json' else Path(value)
        with patch.object(package,'configured',return_value={}),patch.object(package,'Path',side_effect=local_path), \
             patch('scripts.source.update_identity.verify_about_identity'),patch.object(mac,'verified') as verified:
            with self.assertRaisesRegex(ValueError,'native library not found'):
                package.create(self.tree,'macos','aarch64','standard')
            verified.assert_called_once_with(self.tree,post_build=True)

    def test_transform_preserves_manifest_and_detects_transformed_or_recipe_drift(self):
        original=(self.tree/'source-manifest.json').read_bytes();self.transform()
        self.assertEqual((self.tree/'source-manifest.json').read_bytes(),original)
        self.assertEqual(self.verify()[0],self.p)
        (self.tree/'target').mkdir();(self.tree/'target/build-output').write_text('allowed native output')
        self.assertEqual(self.verify()[0],self.p)
        path=self.tree/'flutter/lib/common.dart';valid=path.read_bytes();path.write_text('tampered')
        with self.assertRaisesRegex(ValueError,'source drift'):self.verify()
        path.write_bytes(valid);(self.tree/'Cargo.toml').write_text('tampered recipe')
        with self.assertRaisesRegex(ValueError,'protected recipe'):self.verify()

    def test_stale_bridge_identity_or_inventory_never_executes_source_helper(self):
        for key,value in [('upstream_sha','c'*40),('custom_sha','c'*40),('workflow_run','124'),
                          ('flutter','3.24.5'),('patch_sha256','0'*64),('files',{})]:
            with self.subTest(key=key):
                old=self.info;self.info=dict(old,**{key:value});self.write_info()
                with patch.object(mac,'profile',return_value=self.p),patch.object(mac,'verify_sdk'), \
                     patch.object(mac.bridge_recipe,'apply') as command:
                    with self.assertRaises(ValueError):mac.transform(self.tree,self.bridge)
                    command.assert_not_called()
                self.info=old
        self.write_info();(self.bridge/mac.BRIDGE_FILES[0]).write_text('corrupt')
        with patch.object(mac,'profile',return_value=self.p),patch.object(mac,'verify_sdk'), \
             patch.object(mac.bridge_recipe,'apply') as command:
            with self.assertRaisesRegex(ValueError,'content drift'):mac.transform(self.tree,self.bridge)
            command.assert_not_called()

    def test_worker_epoch_and_original_source_must_match(self):
        self.transform()
        for key,value in [('GITHUB_RUN_ID','124'),('GITHUB_SHA','c'*40),('UPSTREAM_EXPECTED_SHA','c'*40)]:
            with patch.dict(os.environ,{key:value}),self.assertRaisesRegex(ValueError,'worker context'):
                self.verify()
        receipt=self.tree/mac.RECEIPT;value=json.loads(receipt.read_text())
        value['before'][mac.INPUTS[0]]='0'*64;receipt.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'before-state'):self.verify()

    def test_extra_bridge_artifact_is_rejected_before_source_execution(self):
        (self.bridge/'unexpected.rs').write_text('extra artifact')
        with patch.object(mac,'profile',return_value=self.p),patch.object(mac,'verify_sdk'), \
             patch.object(mac.bridge_recipe,'apply') as command:
            with self.assertRaisesRegex(ValueError,'artifact inventory'):mac.transform(self.tree,self.bridge)
            command.assert_not_called()

    def test_second_transformation_and_nonregular_bridge_are_rejected(self):
        self.transform()
        with patch.object(mac,'profile',return_value=self.p),patch.object(mac,'verify_sdk'):
            with self.assertRaisesRegex(ValueError,'already transformed'):mac.transform(self.tree,self.bridge)
        path=self.bridge/mac.BRIDGE_INFO;target=self.root/'info.json';path.rename(target);path.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'receipt'):mac.read(path)

    def test_sdk_and_native_runner_are_verified(self):
        with patch.object(mac.subprocess,'check_output',return_value=json.dumps({'frameworkVersion':self.p['flutter']})):
            mac.verify_sdk(self.p)
            with patch.dict(os.environ,RUNNER_ARCH='X64'),self.assertRaisesRegex(ValueError,'Native Mac ARM'):
                mac.verify_sdk(self.p)
        with patch.object(mac.subprocess,'check_output',return_value=json.dumps({'frameworkVersion':'3.24.5'})):
            with self.assertRaisesRegex(ValueError,'SDK mismatch'):mac.verify_sdk(self.p)

    def test_package_receipt_binds_source_variant_run_and_toolchain(self):
        self.transform()
        info={'platform':'macos','architecture':'aarch64','macos_flutter344':True,'variant':'standard',
              'upstream_sha':'a'*40,'custom_repository_sha':'b'*40,'workflow_run':'123',
              'prepared_source_identity':mac.sha(self.tree/'source-manifest.json'),
              'platform_adapter_signature':self.p['signature'],
              'build_toolchain':{k:self.p[k] for k in ('rust','flutter','vcpkg')}}
        mac.validate_receipt(self.tree,info)
        for key,value in [('variant','sos'),('workflow_run','124'),('custom_repository_sha','c'*40),
                          ('macos_flutter344',False),('platform_adapter_signature','0'*64)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                mac.validate_receipt(self.tree,dict(info,**{key:value}))
        bad=copy.deepcopy(info);bad['build_toolchain']['flutter']='3.24.5'
        with self.assertRaisesRegex(ValueError,'toolchain'):mac.validate_receipt(self.tree,bad)

    def test_receipt_requirement_cannot_be_hidden_with_legacy_sdk_metadata(self):
        downgraded={'macos_flutter344':False,'platform_adapter_signature':'old-signature',
                    'build_toolchain':{'flutter':'3.24.5'}}
        self.assertTrue(mac.requires_receipt(downgraded,self.manifest))
        old=copy.deepcopy(self.manifest);old['files']['.github/workflows/flutter-build.yml']='legacy-recipe'
        self.assertFalse(mac.requires_receipt(downgraded,old))
        self.assertTrue(mac.requires_receipt(dict(downgraded,platform_adapter_signature=self.p['signature']),old))
        self.assertTrue(mac.requires_receipt(dict(downgraded,build_toolchain={'flutter':'3.44.9'}),old))

    def test_unknown_recipe_reports_exact_field_differences_and_remains_blocked(self):
        mac.approved(self.p)
        changed=dict(self.p,flutter='3.45.0',runner='macos-27')
        with patch('sys.stderr', new_callable=__import__('io').StringIO) as diagnostic:
            with self.assertRaisesRegex(ValueError,'field-level differences'):
                mac.approved(changed)
        output=diagnostic.getvalue()
        self.assertIn('Closest approved profile #1',output)
        self.assertIn('flutter:',output)
        self.assertIn('approved: 3.44.9',output)
        self.assertIn('observed: 3.45.0',output)
        self.assertIn('runner:',output)
        self.assertIn('approved: macos-26',output)
        self.assertIn('observed: macos-27',output)

    def test_unknown_recipe_and_schema_remain_blocked(self):
        path=mac.POLICY;v=json.loads(path.read_text());v['schema_version']=2;path.write_text(json.dumps(v))
        with self.assertRaisesRegex(ValueError,'schema'):mac.approved(self.p)

    def test_original_recipe_uses_git_head_not_mutated_worktree(self):
        calls=[]
        def git(args,**kwargs):
            calls.append(args)
            if 'rev-parse' in args:return 'a'*40+'\n'
            return b'official original bytes\n'
        with patch.object(mac.subprocess,'check_output',side_effect=git), \
             patch.object(adapter,'check',return_value=(self.p,{})) as checked:
            p,_=mac.original(self.tree)
            self.assertEqual(p,self.p)
            root=checked.call_args.args[0]
            self.assertNotEqual(root,self.tree)
        self.assertTrue(any('HEAD:flutter/pubspec.yaml' in c for c in calls))
        with patch.object(mac.subprocess,'check_output',return_value='c'*40+'\n'):
            with self.assertRaisesRegex(ValueError,'Git source drift'):mac.original(self.tree)


class MacWorkflowContract(unittest.TestCase):
    def test_new_sdk_is_arch_specific_and_old_sources_stay_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in adapter.FILES:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('recipe input')
            workflow={'env':{'RUST_VERSION':'1.75','MAC_RUST_VERSION':'1.81','FLUTTER_VERSION':'3.24.5',
                             'FLUTTER_MACOS_ARM_VERSION':'3.44.9','VCPKG_COMMIT_ID':'a'*40},
                      'jobs':{'build-for-macOS':{'strategy':{'matrix':{'job':[
                          {'arch':'aarch64','os':'macos-14'},{'arch':'x86_64','os':'macos-15-intel'}]}}}}}
            p=root/'.github/workflows/flutter-build.yml';p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(yaml.safe_dump(workflow))
            self.assertEqual(adapter.inspect(root,'macos','aarch64')[0]['flutter'],'3.44.9')
            self.assertEqual(adapter.inspect(root,'macos','x86_64')[0]['flutter'],'3.24.5')
            del workflow['env']['FLUTTER_MACOS_ARM_VERSION'];p.write_text(yaml.safe_dump(workflow))
            self.assertEqual(adapter.inspect(root,'macos','aarch64')[0]['flutter'],'3.24.5')

    def test_bridge_job_has_no_signing_secrets_and_keeps_guards(self):
        core=yaml.safe_load((ROOT/'.github/workflows/build-stable-platforms.yml').read_text())
        job=core['jobs']['macos-arm64-bridge'];steps=job['steps']
        self.assertEqual(job['permissions'],{'contents':'read'})
        self.assertNotIn('secrets',job);self.assertNotIn('environment',job)
        self.assertNotIn('YUBIKEY',str(job));self.assertNotIn('RUSTDESK_PASSWORD',str(job))
        checkout=next(i for i,s in enumerate(steps) if s.get('uses','').startswith('actions/checkout@'))
        review=next(i for i,s in enumerate(steps) if s.get('id')=='profile')
        dependency=next(i for i,s in enumerate(steps) if s.get('name')=='Install reviewed bridge host dependencies')
        self.assertLess(checkout,review);self.assertLess(review,dependency)
        self.assertFalse(any('coordinator.runtime guard' in s.get('run','') for s in steps))
        for s in steps[dependency:]:self.assertEqual(s['if'],"steps.profile.outputs.required == 'true'")
        self.assertIn('macos-arm64-bridge',core['jobs']['platforms']['needs'])
        build=yaml.safe_load((ROOT/'.github/workflows/build-platform.yml').read_text())
        self.assertEqual(build['permissions'],{'contents':'read'})
        self.assertTrue(any('scripts.release.coordinator_lite verify-worker' in s.get('run','') for s in build['jobs']['platform-build']['steps']))
        step=next(s for s in build['jobs']['platform-build']['steps'] if s.get('name')=='Apply verified Mac ARM source and bridge transformation')
        self.assertIn("inputs.arch == 'aarch64'",step['if'])
        ownership=next(i for i,s in enumerate(build['jobs']['platform-build']['steps']) if s.get('name')=='Verify Mac ARM bridge artifact ownership')
        download=next(i for i,s in enumerate(build['jobs']['platform-build']['steps']) if s.get('with',{}).get('name')=='${{ inputs.macos_bridge_artifact }}')
        self.assertLess(ownership,download)
        self.assertIn('macos-arm64-bridge-$GITHUB_RUN_ID',build['jobs']['platform-build']['steps'][ownership]['run'])
        self.assertIn('macos_arm64 transform',step['run'])

    def test_native_sdk_smoke_has_no_production_authority(self):
        w=yaml.safe_load((ROOT/'.github/workflows/macos-arm64-compatibility.yml').read_text())
        self.assertEqual(w['permissions'],{'contents':'read'})
        self.assertEqual(w['jobs']['source-and-sdk']['runs-on'],'macos-26')
        text=json.dumps(w)
        for forbidden in ('secrets.', 'YUBIKEY', 'android-production-signing', 'RELEASE_APP', 'RUSTDESK_PASSWORD'):
            self.assertNotIn(forbidden,text)
        steps=w['jobs']['source-and-sdk']['steps']
        review=next(i for i,s in enumerate(steps) if s.get('id')=='profile')
        sdk=next(i for i,s in enumerate(steps) if 'flutter-action' in s.get('uses',''))
        self.assertLess(review,sdk)
        self.assertIn('verify_sdk',steps[-1]['run'])
        self.assertIn("original('.work/mac-smoke')",steps[-1]['run'])
        self.assertIn('application compilation/runtime not tested',steps[-1]['run'])

    def test_macos_setup_respects_official_sdk_conditional(self):
        from scripts.platform import platform_adapter
        names=['Install build runtime','Install NASM','Patch flutter','Workaround for flutter issue',
               'Keep CocoaPods for Flutter 3.44 (arm64)']
        job={'steps':[{'name':n,'run':'echo '+n} for n in names]}
        for modern in (False,True):
            p={'macos_flutter344':modern,'official_matrix':{},'tools':{},'rust':'1.81'}
            with patch.object(platform_adapter,'check',return_value=(p,job)), \
                 patch('sys.argv',['platform_commands.py','.','macos','aarch64','setup']), \
                 patch('subprocess.run') as command:
                runpy.run_path(str(ROOT/'scripts/platform/platform_commands.py'),run_name='__main__')
            scripts=[c.args[0][-1] for c in command.call_args_list]
            self.assertEqual(any(s=='echo Patch flutter' for s in scripts),not modern)
            self.assertEqual(any('Keep CocoaPods' in s for s in scripts),modern)
            self.assertTrue(any('Workaround' in s for s in scripts))


if __name__=='__main__':unittest.main()
