import ast
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
    def test_yubikey_secret_and_hardware_signing_are_scoped(self):
        def load(name):return yaml.safe_load((ROOT/'.github/workflows'/name).read_text())
        for name in ['prepare-source.yml','compat-check.yml','build-platform.yml','ci.yml','nightly.yml']:
            self.assertFalse(any(n in (ROOT/'.github/workflows'/name).read_text() for n in signing.NAMES),name)
        w=load('android-signing-validation.yml')
        self.assertEqual(w['permissions']['contents'],'read')
        self.assertNotIn('draft',w['jobs'])
        self.assertEqual(w['jobs']['android-build']['needs'],['resolve','compatibility','prepare'])
        self.assertFalse(w['jobs']['android-build']['strategy']['fail-fast'])
        self.assertEqual(w['jobs']['android-build']['strategy']['matrix']['arch'],['aarch64','armv7','x86_64'])
        sign=load('sign-android.yml')
        steps=sign['jobs']['sign']['steps']
        job=sign['jobs']['sign']
        self.assertEqual(job['runs-on'],['self-hosted','linux','arm64','rustdesk-signing','android-signing','yubikey'])
        self.assertEqual(job['environment']['name'],'android-production-signing')
        self.assertEqual(job['concurrency'],{'group':'rustdesk-android-yubikey-signing','cancel-in-progress':False})
        self.assertIn("github.repository == 'billradar/rustdesk-custom'",job['if'])
        self.assertIn("github.ref == 'refs/heads/main'",job['if'])
        self.assertIn(".github/workflows/tag.yml@refs/heads/main",job['if'])
        self.assertIn(".github/workflows/android-signing-validation.yml@refs/heads/main",job['if'])
        self.assertNotIn("github.event_name == 'pull_request'",job['if'])
        self.assertNotIn('YUBIKEY_PIV_PIN',json.dumps(job.get('env',{})))
        self.assertNotIn('YUBIKEY_PIV_PIN',json.dumps(sign.get('env',{})))
        self.assertFalse(any(s.get('uses','').startswith('actions/checkout@') for s in steps))
        action=next(s for s in steps if s.get('id')=='hardware-sign')
        self.assertIn('YUBIKEY_PIV_PIN',action['env'])
        self.assertIn('--ks-type PKCS11',action['run'])
        self.assertIn('--ks-pass env:YUBIKEY_PIV_PIN',action['run'])
        self.assertIn('set +x',action['run'])
        for step in steps:
            if step is not action:
                self.assertNotIn('YUBIKEY_PIV_PIN',json.dumps(step))
        cleanup=next(s for s in steps if s.get('if')=='always()')
        self.assertIn('rustdesk-yubikey-signing',cleanup['run'])
        upload=next(s for s in steps if s.get('uses','').startswith('actions/upload-artifact@'))
        self.assertEqual(upload['with']['path'],'.work/verified-signed/')
        self.assertEqual(sign['permissions'],{'contents':'read','actions':'read'})
        build=load('build.yml')
        for name in ['build','plan','validate','aggregate','platforms']:
            self.assertFalse(any(n in json.dumps(build['jobs'][name]) for n in signing.NAMES),name)
    def test_stable_draft_requires_signing_while_dry_run_can_test(self):
        w=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())
        expr=w['jobs']['build']['with']['production_android_signing']
        self.assertIn('inputs.dry_run != true',expr)
        self.assertIn('inputs.include_experimental != true',expr)
        self.assertIn('inputs.dry_run != true',w['jobs']['draft']['if'])
        self.assertIn("os.environ['REQUIRE_ANDROID_PRODUCTION_SIGNING']='true'",(ROOT/'scripts/phase5.py').read_text())


class ArtifactContractTests(unittest.TestCase):
    def build_bundle(self, root, arch):
        tree=root/'source'
        target={'aarch64':'aarch64-linux-android','armv7':'armv7-linux-androideabi','x86_64':'x86_64-linux-android'}[arch]
        native=tree/'target'/target/'release'/'liblibrustdesk.so'
        native.parent.mkdir(parents=True)
        data=bytearray(64);data[:4]=b'\x7fELF';data[4]=1 if arch=='armv7' else 2;data[5]=1
        struct.pack_into('<H',data,18,{'aarch64':183,'armv7':40,'x86_64':62}[arch])
        native.write_bytes(data)
        manifest={'variant':'standard','upstream_repository':'rustdesk/rustdesk','upstream_ref':'1.5.0','upstream_version':'1.5.0','upstream_sha':'a'*40,'patchset':'v1','common_patch_hash':patch_hash('common','v1'),'sos_patch_hash':None,'custom_repository':'billradar/rustdesk-custom','custom_repository_sha':'b'*40,'prepare_workflow_run':'99'}
        (tree/'source-manifest.json').write_text(json.dumps(manifest))
        (tree/'LICENCE').write_text('Public test licence fixture')
        packages=tree/'signed-apk';packages.mkdir()
        with zipfile.ZipFile(packages/'fixture.apk','w') as apk:
            apk.writestr('lib/'+signing.ABIS[arch]+'/librustdesk.so',data)
        (root/'README.md').write_text('Public test source fixture')
        shutil.copytree(ROOT/'patchsets/v1/common',root/'patchsets/v1/common')
        work=root/'.work';work.mkdir()
        profile=dict(target=target,signature='c'*64,rust='1.75',flutter='3.24.5',vcpkg='fixture',ndk='fixture',cargo_ndk='3.1.2')
        (work/'platform-profile.json').write_text(json.dumps(profile))
        mir=work/'mir';mir.mkdir()
        (mir/'validated.json').write_text(json.dumps({'result':'PASS','target':arch,'method':'compiler-mir'}))
        (mir/'client.mir').write_text('Synthetic compiler fixture; compilation is outside this contract test')
        env={'CONFIG_MIR_DIR':str(mir),'UPSTREAM_VERSION':'1.5.0','BUILD_CHANNEL':'stable','GITHUB_RUN_ID':'99','GITHUB_SHA':'b'*40,'UPSTREAM_EXPECTED_SHA':'a'*40,'PATCHSET':'v1'}
        # Only external compilation/config injection is stubbed. Package creation,
        # architecture, native bytes, checksum and source provenance gates run for real.
        previous=Path.cwd()
        try:
            os.chdir(root)
            with patch.object(platform_package,'ROOT',root),patch.object(platform_package,'configured',return_value={}),patch('config_mir.verify'),patch.dict(os.environ,env,clear=True):
                platform_package.create(tree,'android',arch,'standard')
        finally:
            os.chdir(previous)
        return next((root/'artifacts').iterdir())

    def validate_bundle(self, bundle):
        # CI supplies real source/run identities; this synthetic bundle must
        # exercise the same gates against its own explicit fixture identities.
        env={'UPSTREAM_EXPECTED_SHA':'a'*40,'GITHUB_SHA':'b'*40,'GITHUB_RUN_ID':'99','PATCHSET':'v1'}
        with patch.dict(os.environ,env):
            platform_package.validate(bundle)

    def test_signing_workflow_requires_same_canonical_native_file(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/sign-android.yml').read_text())
        step=next(s for s in workflow['jobs']['sign']['steps'] if s.get('id')=='input')
        script=step['run'].split("python3 - <<'PY'\n",1)[1].rsplit("\nPY",1)[0]
        parsed=ast.parse(script)
        required=next(ast.literal_eval(n.value) for n in ast.walk(parsed) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='required' for t in n.targets))
        self.assertIn('validation/librustdesk.so',required)
        self.assertNotIn('validation/liblibrustdesk.so',required)
        self.assertIn("bundle / 'validation/librustdesk.so'",script)

    def test_build_to_signing_contract_all_three_abis(self):
        for arch in signing.ABIS:
            with self.subTest(arch=arch),tempfile.TemporaryDirectory() as tmp:
                bundle=self.build_bundle(Path(tmp),arch)
                native=bundle/'validation/librustdesk.so'
                self.assertTrue(native.is_file())
                self.assertFalse((bundle/'validation/liblibrustdesk.so').exists())
                self.assertEqual(list((bundle/'validation').iterdir()),[native])
                platform_package.verify_checksums(bundle)
                self.assertIn(platform_package.sha(native)+'  validation/librustdesk.so',(bundle/'SHA256SUMS').read_text())
                with zipfile.ZipFile(next((bundle/'packages').glob('*.apk'))) as apk:
                    self.assertEqual(apk.read('lib/'+signing.ABIS[arch]+'/librustdesk.so'),native.read_bytes())
                self.validate_bundle(bundle)

    def test_noncanonical_extra_symlink_and_mismatched_native_fail_closed(self):
        for mode in ('old-name','extra-file','symlink','symlink-directory','different-bytes','checksum-coverage'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                bundle=self.build_bundle(Path(tmp),'aarch64')
                native=bundle/'validation/librustdesk.so'
                if mode=='old-name':native.rename(native.with_name('liblibrustdesk.so'))
                elif mode=='extra-file':native.with_name('liblibrustdesk.so').write_bytes(native.read_bytes())
                elif mode=='symlink':
                    other=bundle/'other.so';native.rename(other);native.symlink_to(other)
                elif mode=='symlink-directory':
                    directory=bundle/'validation';other=bundle/'other-validation';directory.rename(other);directory.symlink_to(other,target_is_directory=True)
                elif mode=='different-bytes':native.write_bytes(native.read_bytes()+b'changed')
                platform_package.checksums(bundle)
                if mode=='checksum-coverage':
                    sums=bundle/'SHA256SUMS';sums.write_text('\n'.join(line for line in sums.read_text().splitlines() if not line.endswith('  validation/librustdesk.so'))+'\n')
                with self.assertRaises(ValueError):self.validate_bundle(bundle)
