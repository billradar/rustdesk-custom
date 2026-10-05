import base64
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import shutil
import struct
import zipfile
import unittest
from unittest.mock import patch
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import android_signing as signing
import platform_package
from patchsets import patch_hash

class IdentityTests(unittest.TestCase):
    def test_yubikey_artifact_root_must_contain_exactly_one_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'download';bundle=root/'rustdesk-stable-artifact'
            bundle.mkdir(parents=True);(bundle/'build-info.json').write_text('{}')
            self.assertEqual(signing.locate_yubikey_bundle(root),bundle.resolve())
            (root/'second').mkdir();(root/'second/build-info.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'exactly one build manifest'):
                signing.locate_yubikey_bundle(root)

    def test_certificate_package_and_abi_fail_closed(self):
        expected={'certificate_sha256':'a'*64,'package_name':'com.example.app'}
        actual=dict(expected,abis=['arm64-v8a'])
        signing.identity_gate(actual,expected,'aarch64')
        for field,value in [('certificate_sha256','b'*64),('package_name','com.example.other'),('abis',['x86_64'])]:
            with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(ValueError):
                signing.identity_gate(dict(actual,**{field:value}),expected,'aarch64')
    def test_preflight_never_discloses_values(self):
        values={n:'private-fixture-'+n for n in signing.NAMES}
        for missing in [None,*signing.NAMES]:
            env=dict(values)
            if missing:env[missing]=''
            out=io.StringIO()
            with patch.dict(os.environ,env,clear=True),contextlib.redirect_stdout(out):
                if missing:
                    with self.assertRaisesRegex(ValueError,'LEGACY SIGNING SECRETS NOT AVAILABLE'):signing.preflight()
                else:signing.preflight()
            for value in values.values():self.assertNotIn(value,out.getvalue())
    def test_keystore_and_actual_secret_leaks_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);p=folder/'public.json'
            env={n:'fixture-value-'+n for n in signing.NAMES}
            env['ANDROID_SIGNING_KEY']=base64.b64encode(b'fake-existing-material').decode()
            with patch.dict(os.environ,env,clear=True),contextlib.redirect_stdout(io.StringIO()):
                for payload in [b'fake-existing-material',env['ANDROID_KEY_PASSWORD'].encode(),env['ANDROID_SIGNING_KEY'].encode(),b'\xfe\xed\xfe\xedxxxx']:
                    p.write_bytes(payload)
                    with self.assertRaises(ValueError):signing.leakage_scan(folder,True)
                p.write_text('{}')
                signing.leakage_scan(folder,True)
                (folder/'accidental.jks').write_bytes(b'no-key')
                with self.assertRaises(ValueError):signing.leakage_scan(folder)
    def test_reject_multiple_signers_and_invalid_signature(self):
        result=type('Result',(),{'returncode':0,'stdout':'Signer #1 certificate SHA-256 digest: '+'a'*64+'\nSigner #2 certificate SHA-256 digest: '+'b'*64+'\n'})()
        with patch.object(signing.subprocess,'run',return_value=result),self.assertRaisesRegex(ValueError,'exactly one'):signing.public_identity(Path('fake.apk'))
        result.returncode=1
        with patch.object(signing.subprocess,'run',return_value=result),self.assertRaisesRegex(ValueError,'verification failed'):signing.public_identity(Path('fake.apk'))
    def test_private_stage_restricts_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'bundle';(folder/'packages').mkdir(parents=True)
            (folder/'packages/test.apk').write_bytes(b'existing-build')
            with patch.object(signing,'validate',return_value={'platform':'android','variant':'standard'}):signing.stage(folder,root/'private')
            self.assertEqual((root/'private').stat().st_mode&0o777,0o700)
            self.assertEqual((root/'private/signingKey.jks').stat().st_mode&0o777,0o600)

class WorkflowTests(unittest.TestCase):

    def test_stable_production_signing_gate(self):
        tag=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())
        build=yaml.safe_load((ROOT/'.github/workflows/build.yml').read_text())
        sign=yaml.safe_load((ROOT/'.github/workflows/sign-android.yml').read_text())

        expr=tag['jobs']['build']['with']['production_android_signing']
        for marker in (
            "github.event_name == 'workflow_dispatch'",
            'inputs.production_android_signing == true',
            'inputs.dry_run == false',
            'inputs.include_experimental == false',
        ):
            self.assertIn(marker,expr)

        gate=tag['on']['workflow_dispatch']['inputs']['production_android_signing']
        self.assertFalse(gate['default'])
        self.assertIn('direct_android_signing',tag['jobs']['build']['with'])

        signing=build['jobs']['android-sign']
        self.assertNotIn('strategy',signing)
        self.assertEqual(signing['uses'],'./.github/workflows/sign-android.yml')
        self.assertEqual(signing['with']['arches'],'aarch64,armv7,x86_64')
        self.assertIn('production_android_signing',json.dumps(signing.get('if','')))

        job=sign['jobs']['sign']
        self.assertEqual(job['runs-on'],['self-hosted','linux','arm64','rustdesk-signing','android-signing','yubikey'])
        self.assertEqual(job['concurrency']['group'],'rustdesk-android-yubikey-signing')
        self.assertFalse(job['concurrency']['cancel-in-progress'])
        self.assertEqual(job['concurrency']['queue'],'max')
        identity_preflight=next(step for step in job['steps'] if 'Validate public YubiKey identity metadata' in step.get('name',''))
        self.assertIn('559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5',identity_preflight['run'])
        self.assertNotIn('legacy_android_signing_identity',identity_preflight['run'])
        self.assertIn("github.workflow_ref == 'billradar/rustdesk-custom/.github/workflows/tag.yml@refs/heads/main'",job['if'])
        self.assertIn("inputs.channel == 'stable'",job['if'])

        hardware=next(step for step in job['steps'] if 'Production YubiKey signing of all Android architectures' in step.get('name',''))
        self.assertEqual(hardware['env']['YUBIKEY_PIV_PIN'],'${{ secrets.YUBIKEY_PIV_PIN }}')
        self.assertIn('/usr/local/bin/rustdesk-sign',hardware['run'])
        self.assertIn('"--pin-source", "env"',hardware['run'])

        verify=next(step for step in job['steps'] if 'Verify all production signatures' in step.get('name',''))
        self.assertIn('559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5',verify['run'])

        aggregate=build['jobs']['aggregate']
        self.assertIn("needs.android-sign.result == 'success'",json.dumps(aggregate.get('if','')))
        self.assertIn('android-sign',json.dumps(aggregate.get('needs',{})))

        draft=tag['jobs']['draft']
        self.assertIn("needs.aggregate.result == 'success'",draft['if'])
        self.assertIn("github.event_name == 'workflow_dispatch'",draft['if'])
        self.assertIn('inputs.production_android_signing == true',draft['if'])
        self.assertIn('inputs.dry_run == false',draft['if'])
        self.assertIn('inputs.include_experimental == false',draft['if'])

class ArtifactContractTests(unittest.TestCase):
    def build_bundle(self, root, arch):
        tree=root/'source'
        target={'aarch64':'aarch64-linux-android','armv7':'armv7-linux-androideabi','x86_64':'x86_64-linux-android'}[arch]
        native=tree/'target'/target/'release'/'liblibrustdesk.so'
        native.parent.mkdir(parents=True)
        data=bytearray(64);data[:4]=b'\x7fELF';data[4]=1 if arch=='armv7' else 2;data[5]=1
        struct.pack_into('<H',data,18,{'aarch64':183,'armv7':40,'x86_64':62}[arch])
        manifest={'variant':'standard','upstream_repository':'rustdesk/rustdesk','upstream_ref':'1.5.0','upstream_version':'1.5.0','upstream_sha':'a'*40,'patchset':'v1','common_patch_hash':patch_hash('common','v1'),'sos_patch_hash':None,'custom_repository':'billradar/rustdesk-custom','custom_repository_sha':'b'*40,'prepare_workflow_run':'99'}
        (tree/'source-manifest.json').write_text(json.dumps(manifest));(tree/'LICENCE').write_text('Public test licence fixture')
        packages=tree/'signed-apk';packages.mkdir()
        with zipfile.ZipFile(packages/'fixture.apk','w') as apk: apk.writestr('lib/'+signing.ABIS[arch]+'/librustdesk.so',data)
        native.write_bytes(data)
        (root/'README.md').write_text('Public test source fixture')
        shutil.copytree(ROOT/'patchsets/v1/common',root/'patchsets/v1/common')
        work=root/'.work';work.mkdir()
        (work/'platform-profile.json').write_text(json.dumps(dict(target=target,signature='c'*64,rust='1.75',flutter='3.24.5',vcpkg='fixture',ndk='fixture',cargo_ndk='3.1.2')))
        mir=work/'mir';mir.mkdir();(mir/'validated.json').write_text(json.dumps({'result':'PASS','target':arch,'method':'compiler-mir'}));(mir/'client.mir').write_text('Synthetic compiler fixture; compilation is outside this contract test')
        env={'CONFIG_MIR_DIR':str(mir),'UPSTREAM_VERSION':'1.5.0','BUILD_CHANNEL':'stable','GITHUB_RUN_ID':'99','GITHUB_SHA':'b'*40,'UPSTREAM_EXPECTED_SHA':'a'*40,'PATCHSET':'v1'}
        previous=Path.cwd()
        try:
            os.chdir(root)
            with patch.object(platform_package,'ROOT',root),patch.object(platform_package,'configured',return_value={}),patch('config_mir.verify'),patch.dict(os.environ,env,clear=True): platform_package.create(tree,'android',arch,'standard')
        finally: os.chdir(previous)
        return next((root/'artifacts').iterdir())
    def validate_bundle(self, bundle):
        env={'UPSTREAM_EXPECTED_SHA':'a'*40,'GITHUB_SHA':'b'*40,'GITHUB_RUN_ID':'99','PATCHSET':'v1'}
        with patch.dict(os.environ,env): platform_package.validate(bundle)

    def test_build_to_signing_contract_all_three_abis(self):
        for arch in signing.ABIS:
            with self.subTest(arch=arch),tempfile.TemporaryDirectory() as tmp:
                bundle=self.build_bundle(Path(tmp),arch);native=bundle/'validation/librustdesk.so'
                self.assertTrue(native.is_file());self.assertFalse((bundle/'validation/liblibrustdesk.so').exists());self.assertEqual(list((bundle/'validation').iterdir()),[native])
                platform_package.verify_checksums(bundle);self.assertIn(platform_package.sha(native)+'  validation/librustdesk.so',(bundle/'SHA256SUMS').read_text())
                with zipfile.ZipFile(next((bundle/'packages').glob('*.apk'))) as apk:self.assertEqual(apk.read('lib/'+signing.ABIS[arch]+'/librustdesk.so'),native.read_bytes())
                self.validate_bundle(bundle)
    def test_noncanonical_extra_symlink_and_mismatched_native_fail_closed(self):
        for mode in ('old-name','extra-file','symlink','symlink-directory','different-bytes','checksum-coverage'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                bundle=self.build_bundle(Path(tmp),'aarch64');native=bundle/'validation/librustdesk.so'
                if mode=='old-name':native.rename(native.with_name('liblibrustdesk.so'))
                elif mode=='extra-file':native.with_name('liblibrustdesk.so').write_bytes(native.read_bytes())
                elif mode=='symlink':other=bundle/'other.so';native.rename(other);native.symlink_to(other)
                elif mode=='symlink-directory':directory=bundle/'validation';other=bundle/'other-validation';directory.rename(other);directory.symlink_to(other,target_is_directory=True)
                elif mode=='different-bytes':native.write_bytes(native.read_bytes()+b'changed')
                platform_package.checksums(bundle)
                if mode=='checksum-coverage':
                    sums=bundle/'SHA256SUMS';sums.write_text('\n'.join(line for line in sums.read_text().splitlines() if not line.endswith('  validation/librustdesk.so'))+'\n')
                with self.assertRaises(ValueError):self.validate_bundle(bundle)
