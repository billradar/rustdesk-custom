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
    def test_phase_5_2b_2_5_secret_visibility_probes_are_dummy_only_and_step_scoped(self):
        root=ROOT/'.github/workflows'
        direct=yaml.safe_load((root/'secret-context-direct-probe.yml').read_text())
        self.assertEqual(set(direct['on']),{'workflow_dispatch'})
        direct_job=direct['jobs']['direct-probe']
        self.assertEqual(direct_job['environment']['name'],'android-production-signing')
        self.assertEqual(direct_job['runs-on'],['self-hosted','linux','arm64','rustdesk-signing','android-signing','yubikey'])
        self.assertIn("github.repository == 'billradar/rustdesk-custom'",direct_job['if'])
        self.assertIn("github.ref == 'refs/heads/main'",direct_job['if'])
        self.assertIn("github.event_name == 'workflow_dispatch'",direct_job['if'])
        self.assertIn('secret-context-direct-probe.yml@refs/heads/main',direct_job['if'])
        self.assertNotIn('env',direct_job)
        self.assertEqual(len(direct_job['steps']),1)
        direct_step=direct_job['steps'][0]
        self.assertEqual(set(direct_step['env']),{'PROBE_CONTEXT_AVAILABLE','SECRET_CONTEXT_PROBE'})
        self.assertIn("secrets.SECRET_CONTEXT_PROBE != ''",direct_step['env']['PROBE_CONTEXT_AVAILABLE'])
        self.assertEqual(direct_step['env']['SECRET_CONTEXT_PROBE'],'${{ secrets.SECRET_CONTEXT_PROBE }}')

        caller=yaml.safe_load((root/'secret-context-reusable-probe.yml').read_text())
        self.assertEqual(set(caller['on']),{'workflow_dispatch'})
        caller_job=caller['jobs']['reusable-probe']
        self.assertEqual(caller_job['uses'],'./.github/workflows/secret-context-reusable-probe-job.yml')
        self.assertEqual(caller_job['secrets'],{'SECRET_CONTEXT_PROBE_2':'${{ secrets.SECRET_CONTEXT_PROBE_2 }}'})
        self.assertNotIn('YUBIKEY_PIV_PIN',json.dumps(caller))

        reusable=yaml.safe_load((root/'secret-context-reusable-probe-job.yml').read_text())
        self.assertEqual(set(reusable['on']),{'workflow_call'})
        self.assertEqual(reusable['on']['workflow_call']['secrets'],{
            'SECRET_CONTEXT_PROBE':{'required':False},'SECRET_CONTEXT_PROBE_2':{'required':True}})
        job=reusable['jobs']['reusable-probe']
        self.assertEqual(job['environment']['name'],'android-production-signing')
        self.assertEqual(job['runs-on'],direct_job['runs-on'])
        self.assertIn('secret-context-reusable-probe.yml@refs/heads/main',job['if'])
        self.assertNotIn('env',job)
        self.assertEqual(len(job['steps']),1)
        probe=job['steps'][0]
        self.assertEqual(set(probe['env']),{
            'ENVIRONMENT_PROBE_CONTEXT_AVAILABLE','SECRET_CONTEXT_PROBE',
            'CALLER_PROBE_CONTEXT_AVAILABLE','SECRET_CONTEXT_PROBE_2'})
        self.assertIn("secrets.SECRET_CONTEXT_PROBE != ''",probe['env']['ENVIRONMENT_PROBE_CONTEXT_AVAILABLE'])
        self.assertEqual(probe['env']['SECRET_CONTEXT_PROBE'],'${{ secrets.SECRET_CONTEXT_PROBE }}')
        self.assertIn("secrets.SECRET_CONTEXT_PROBE_2 != ''",probe['env']['CALLER_PROBE_CONTEXT_AVAILABLE'])
        self.assertEqual(probe['env']['SECRET_CONTEXT_PROBE_2'],'${{ secrets.SECRET_CONTEXT_PROBE_2 }}')
        for workflow in (direct,caller,reusable):
            serialized=json.dumps(workflow)
            self.assertNotIn('YUBIKEY_PIV_PIN',serialized)
            self.assertNotIn('/usr/local/bin/rustdesk-sign',serialized)
            for forbidden in ('C_Initialize','C_Login','C_SignInit','C_Sign','apksigner','printenv','set -x'):
                self.assertNotIn(forbidden,serialized)
        for marker in ('DIRECT SECRET CONTEXT: PASS','DIRECT SECRET CONTEXT: FAIL',
                       'DIRECT STEP MAPPING: PASS','DIRECT PROCESS ENVIRONMENT: PASS',
                       'DIRECT WORKFLOW: PASS','DIRECT WORKFLOW: FAIL'):
            self.assertIn(marker,direct_step['run'])
        for marker in ('REUSABLE ENV SECRET CONTEXT: PASS','REUSABLE ENV SECRET CONTEXT: FAIL',
                       'REUSABLE ENV STEP MAPPING: PASS','REUSABLE ENV PROCESS ENVIRONMENT: PASS',
                       'WORKFLOW_CALL SECRET CONTEXT: PASS','WORKFLOW_CALL STEP MAPPING: PASS',
                       'WORKFLOW_CALL PROCESS ENVIRONMENT: PASS','REUSABLE ENVIRONMENT SECRET PATH: PASS',
                       'WORKFLOW_CALL SECRET PATH: PASS','REUSABLE WORKFLOW: PASS','REUSABLE WORKFLOW: FAIL'):
            self.assertIn(marker,probe['run'])

    def test_environment_pin_probe_is_dispatch_only_and_never_starts_signer(self):
        root=ROOT/'.github/workflows'
        caller=yaml.safe_load((root/'android-signing-secret-probe.yml').read_text())
        self.assertEqual(set(caller['on']),{'workflow_dispatch'})
        self.assertEqual(caller['permissions'],{'contents':'read'})
        self.assertEqual(caller['jobs']['probe']['uses'],'./.github/workflows/android-signing-secret-probe-job.yml')

        reusable=yaml.safe_load((root/'android-signing-secret-probe-job.yml').read_text())
        self.assertEqual(set(reusable['on']),{'workflow_call'})
        self.assertIsNone(reusable['on']['workflow_call'])
        job=reusable['jobs']['environment-pin-probe']
        self.assertEqual(job['environment']['name'],'android-production-signing')
        self.assertEqual(job['runs-on'],['self-hosted','linux','arm64','rustdesk-signing','android-signing','yubikey'])
        for gate in ["github.repository == 'billradar/rustdesk-custom'",
                     "github.ref == 'refs/heads/main'",
                     "github.event_name == 'workflow_dispatch'",
                     "android-signing-secret-probe.yml@refs/heads/main"]:
            self.assertIn(gate,job['if'])
        self.assertNotIn('YUBIKEY_PIV_PIN',json.dumps(job.get('env',{})))
        self.assertEqual(len(job['steps']),1)
        probe=job['steps'][0]
        self.assertEqual(set(probe['env']),{'PIN_SECRET_CONTEXT_AVAILABLE','YUBIKEY_PIV_PIN'})
        self.assertIn('secrets.YUBIKEY_PIV_PIN',probe['env']['YUBIKEY_PIV_PIN'])
        self.assertIn("secrets.YUBIKEY_PIV_PIN != ''",probe['env']['PIN_SECRET_CONTEXT_AVAILABLE'])
        for result in ('SECRETS CONTEXT: PASS','SECRETS CONTEXT: FAIL',
                       'STEP ENV MAPPING: PASS','STEP ENV MAPPING: FAIL',
                       'PROCESS ENVIRONMENT: PASS','PROCESS ENVIRONMENT: FAIL'):
            self.assertIn(result,probe['run'])
        self.assertIn('ENVIRONMENT PIN AVAILABLE: PASS',probe['run'])
        self.assertIn('ENVIRONMENT PIN AVAILABLE: FAIL',probe['run'])
        caller=yaml.safe_load((root/'android-signing-secret-probe.yml').read_text())
        self.assertNotIn('secrets',caller['jobs']['probe'])
        for forbidden in ('rustdesk-sign','C_Login','C_SignInit','C_Sign','apksigner','opensc-pkcs11.so','printenv','set -x'):
            self.assertNotIn(forbidden,probe['run'])

        production_caller=yaml.safe_load((root/'android-signing-validation.yml').read_text())
        production_reusable=yaml.safe_load((root/'sign-android.yml').read_text())
        self.assertNotIn('uses',production_caller['jobs']['android-sign'])
        self.assertEqual(production_caller['jobs']['android-sign']['environment']['name'],'android-production-signing')
        self.assertEqual(production_caller['jobs']['android-sign']['runs-on'],['self-hosted','linux','arm64','rustdesk-signing','android-signing','yubikey'])
        self.assertEqual(production_caller['on']['workflow_dispatch']['inputs']['validation_enable_signing']['default'],False)
        self.assertNotIn('secrets',production_reusable['on']['workflow_call'])
        self.assertEqual(production_reusable['jobs']['sign']['environment']['name'],'android-production-signing')
        signing=next(step for step in production_caller['jobs']['android-sign']['steps'] if step.get('id')=='hardware-sign')
        self.assertEqual(signing['env']['YUBIKEY_PIV_PIN'],'${{ secrets.YUBIKEY_PIV_PIN }}')

    def test_yubikey_secret_and_hardware_signing_are_scoped(self):
        def load(name):return yaml.safe_load((ROOT/'.github/workflows'/name).read_text())
        for name in ['prepare-source.yml','compat-check.yml','build-platform.yml','ci.yml','nightly.yml']:
            self.assertFalse(any(n in (ROOT/'.github/workflows'/name).read_text() for n in signing.NAMES),name)
        w=load('android-signing-validation.yml')
        self.assertEqual(w['permissions']['contents'],'read')
        self.assertNotIn('draft',w['jobs'])
        self.assertEqual(set(w['on']),{'workflow_dispatch'})
        self.assertEqual(w['jobs']['android-build']['needs'],['resolve','compatibility','prepare'])
        self.assertFalse(w['jobs']['android-build']['strategy']['fail-fast'])
        self.assertEqual(w['jobs']['android-build']['strategy']['matrix']['arch'],['aarch64'])
        self.assertEqual(w['jobs']['android-sign']['strategy']['matrix']['arch'],['aarch64'])
        sign=load('android-signing-validation.yml')
        steps=sign['jobs']['android-sign']['steps']
        job=sign['jobs']['android-sign']
        self.assertEqual(job['runs-on'],['self-hosted','linux','arm64','rustdesk-signing','android-signing','yubikey'])
        self.assertEqual(job['environment']['name'],'android-production-signing')
        self.assertEqual(job['concurrency'],{'group':'rustdesk-android-yubikey-signing','cancel-in-progress':False,'queue':'max'})
        self.assertIn("github.repository == 'billradar/rustdesk-custom'",job['if'])
        self.assertIn("github.ref == 'refs/heads/main'",job['if'])
        self.assertIn(".github/workflows/android-signing-validation.yml@refs/heads/main",job['if'])
        self.assertNotIn("github.event_name == 'pull_request'",job['if'])
        self.assertNotIn('YUBIKEY_PIV_PIN',json.dumps(job.get('env',{})))
        self.assertNotIn('YUBIKEY_PIV_PIN',json.dumps(sign.get('env',{})))
        self.assertEqual(sign['on']['workflow_dispatch']['inputs']['validation_enable_signing']['default'],False)
        probe=next(step for step in steps if step.get('name')=='Non-sensitive production workflow secret-context preflight')
        self.assertEqual(set(probe['env']),{'SECRET_CONTEXT_PROBE_AVAILABLE','SECRET_CONTEXT_PROBE'})
        self.assertIn("secrets.SECRET_CONTEXT_PROBE != ''",probe['env']['SECRET_CONTEXT_PROBE_AVAILABLE'])
        self.assertEqual(probe['env']['SECRET_CONTEXT_PROBE'],'${{ secrets.SECRET_CONTEXT_PROBE }}')
        for marker in ('ENVIRONMENT: PASS','SECRET CONTEXT: PASS','STEP MAPPING: PASS',
                       'PROCESS ENVIRONMENT: PASS','PRODUCTION WORKFLOW STRUCTURE: PASS'):
            self.assertIn(marker,probe['run'])
        action=next(s for s in steps if s.get('id')=='hardware-sign')
        self.assertIn('YUBIKEY_PIV_PIN',action['env'])
        self.assertIn('inputs.validation_enable_signing == true',action['if'])
        self.assertIn("github.event_name == 'workflow_dispatch'",action['if'])
        self.assertIn('/usr/local/bin/rustdesk-sign',action['run'])
        self.assertIn('--pin-source env',action['run'])
        self.assertLess(action['run'].index('ENVIRONMENT PIN AVAILABLE: FAIL'),
                        action['run'].index('/usr/local/bin/rustdesk-sign'))
        self.assertIn('[[ -z "${YUBIKEY_PIV_PIN:-}" ]]',action['run'])
        self.assertIn("ENVIRONMENT PIN AVAILABLE: PASS",action['run'])
        self.assertNotIn('apksigner sign',action['run'])
        self.assertNotIn('SunPKCS11',action['run'])
        self.assertFalse(w['on']['workflow_dispatch']['inputs']['validation_enable_signing']['default'])
        self.assertEqual(w['jobs']['verify-all']['if'],'inputs.validation_enable_signing == true')
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
        tag=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())
        build=yaml.safe_load((ROOT/'.github/workflows/build.yml').read_text())
        sign=yaml.safe_load((ROOT/'.github/workflows/sign-android.yml').read_text())

        expr=tag['jobs']['build']['with']['production_android_signing']
        self.assertIn("github.event_name == 'workflow_dispatch'",expr)
        self.assertIn('inputs.production_android_signing == true',expr)
        self.assertIn('inputs.dry_run == false',expr)
        self.assertIn('inputs.include_experimental == false',expr)

        gate=tag['on']['workflow_dispatch']['inputs']['production_android_signing']
        self.assertFalse(gate['default'])
        self.assertIn('direct_android_signing',tag['jobs']['build']['with'])
        self.assertNotIn('android-sign',tag['jobs'])

        signing=build['jobs']['android-sign']
        self.assertNotIn('strategy',signing)
        self.assertEqual(signing['uses'],'./.github/workflows/sign-android.yml')
        self.assertEqual(signing['with']['arches'],'aarch64,armv7,x86_64')
        self.assertIn('production_android_signing',json.dumps(signing.get('if','')))

        job=sign['jobs']['sign']
        self.assertEqual(job['runs-on'],['self-hosted','linux','arm64','rustdesk-signing','android-signing','yubikey'])
        self.assertNotIn('matrix',json.dumps(job))
        step_names=[step.get('name','') for step in job['steps']]
        self.assertTrue(any('aarch64 build artifact' in name for name in step_names))
        self.assertTrue(any('armv7 build artifact' in name for name in step_names))
        self.assertTrue(any('x86_64 build artifact' in name for name in step_names))
        hardware=next(step for step in job['steps'] if 'Production YubiKey signing of all Android architectures' in step.get('name',''))
        self.assertEqual(hardware['env']['YUBIKEY_PIV_PIN'],'${{ secrets.YUBIKEY_PIV_PIN }}')
        self.assertIn('/usr/local/bin/rustdesk-sign',hardware['run'])
        self.assertIn('set -euo pipefail',hardware['run'])
        self.assertNotIn('YUBIKEY_PIV_PIN',json.dumps(job.get('env',{})))
        verify=next(step for step in job['steps'] if 'Verify all production signatures' in step.get('name',''))
        self.assertIn('expected_fingerprint',verify['run'])
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
    def test_signing_workflow_requires_same_canonical_native_file(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/android-signing-validation.yml').read_text())
        step=next(s for s in workflow['jobs']['android-sign']['steps'] if s.get('id')=='input')
        script=step['run'].split("python3 - <<'PY'\n",1)[1].rsplit("\nPY",1)[0]
        parsed=ast.parse(script)
        required=next(ast.literal_eval(n.value) for n in ast.walk(parsed) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='required' for t in n.targets))
        self.assertIn('validation/librustdesk.so',required);self.assertNotIn('validation/liblibrustdesk.so',required);self.assertIn("bundle / 'validation/librustdesk.so'",script)
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
