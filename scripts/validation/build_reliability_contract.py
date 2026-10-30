"""Offline SDK preflight and bounded single-target recovery regressions."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib
from scripts.validation.summary import isolated_summary, run_contract_tests
import yaml
from scripts.platform import android_sdk as sdk
from scripts.validation import build_reliability as recovery

ROOT = Path(__file__).resolve().parents[2]


class SdkTests(unittest.TestCase):
    def setUp(self):
        isolation=isolated_summary()
        isolation.__enter__()
        self.addCleanup(isolation.__exit__,None,None,None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tree, self.flutter, self.sdk = [self.root / x for x in ('tree', 'flutter', 'sdk')]
        self.app = self.tree/'flutter/android/app/build.gradle'
        self.app.parent.mkdir(parents=True)
        self.app.write_text('compileSdkVersion 36')
        manager = self.sdk/'cmdline-tools/latest/bin/sdkmanager'
        manager.parent.mkdir(parents=True)
        manager.touch()
        self.output = self.root/'report.json'

    def install(self, package, root=None):
        folder = (root or self.sdk).joinpath(*package.split(';'))
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'source.properties').write_text('AndroidVersion.ApiLevel=' + package.split('android-')[-1])
        with zipfile.ZipFile(folder/'android.jar', 'w') as archive:
            archive.writestr('android/app/Activity.class', 'fixture')

    def corrupt_compressed_jar(self, root, package):
        jar=root.joinpath(*package.split(';'))/'android.jar'
        with zipfile.ZipFile(jar,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('android/app/Activity.class',b'fixture'*100)
        with zipfile.ZipFile(jar) as archive:
            info=archive.infolist()[0]
            header_offset=info.header_offset
        raw=bytearray(jar.read_bytes())
        name_length=int.from_bytes(raw[header_offset+26:header_offset+28],'little')
        extra_length=int.from_bytes(raw[header_offset+28:header_offset+30],'little')
        compressed_start=header_offset+30+name_length+extra_length
        # Reserved DEFLATE block type: directory remains valid but decompression fails.
        raw[compressed_start] |= 0b110
        jar.write_bytes(raw)
        with zipfile.ZipFile(jar) as archive:
            self.assertEqual(archive.namelist(),['android/app/Activity.class'])
            with self.assertRaises(zlib.error):archive.testzip()

    def test_corrupt_compressed_cached_and_staged_jar_can_be_repaired(self):
        self.install('platforms;android-33')
        self.corrupt_compressed_jar(self.sdk,'platforms;android-33')
        self.assertFalse(sdk.valid(self.sdk,'platforms;android-33'))
        attempts=[]
        def install(args,**kwargs):
            staging=Path(next(x.split('=',1)[1] for x in args if x.startswith('--sdk_root=')))
            selected=[x for x in args if x.startswith('platforms;')]
            attempts.append(selected)
            for package in selected:self.install(package,staging)
            if len(attempts)==1:self.corrupt_compressed_jar(staging,'platforms;android-33')
            return SimpleNamespace(returncode=0)
        with patch.object(sdk.subprocess,'run',side_effect=install),patch.object(sdk.time,'sleep') as sleep:
            report=sdk.prepare(self.tree,self.flutter,self.sdk,self.output)
        self.assertEqual(report['result'],'PASS')
        self.assertEqual(attempts,[['platforms;android-33','platforms;android-36'],['platforms;android-33']])
        self.assertEqual(report['attempts'][0]['invalid'],['platforms;android-33'])
        sleep.assert_called_once_with(10)

    def test_repeated_compressed_jar_corruption_keeps_exhaustion_marker(self):
        self.install('platforms;android-36')
        def install(args,**kwargs):
            staging=Path(next(x.split('=',1)[1] for x in args if x.startswith('--sdk_root=')))
            self.install('platforms;android-33',staging)
            self.corrupt_compressed_jar(staging,'platforms;android-33')
            return SimpleNamespace(returncode=0)
        with patch.object(sdk.subprocess,'run',side_effect=install) as run,patch.object(sdk.time,'sleep'):
            with self.assertRaisesRegex(ValueError,'INFRASTRUCTURE: SDK_INSTALL_RETRY_EXHAUSTED'):
                sdk.prepare(self.tree,self.flutter,self.sdk,self.output)
        self.assertEqual(run.call_count,3)
        self.assertEqual(json.loads(self.output.read_text())['result'],'FAIL')

    def test_exact_application_and_plugin_platforms(self):
        self.assertEqual(sdk.packages(self.tree, self.flutter), ['platforms;android-33','platforms;android-36'])
        self.app.write_text('compileSdkVersion flutter.compileSdkVersion')
        extension = self.flutter/'packages/flutter_tools/gradle/src/main/groovy/flutter.groovy'
        extension.parent.mkdir(parents=True)
        extension.write_text('public final int compileSdkVersion = 34')
        self.assertEqual(sdk.packages(self.tree, self.flutter), ['platforms;android-33','platforms;android-34'])

    def test_unknown_sdk_expression_fails_before_install(self):
        self.app.write_text('compileSdkVersion customUnreviewedValue')
        with patch.object(sdk.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'BUILD_COMPAT'): sdk.prepare(self.tree,self.flutter,self.sdk,self.output)
            run.assert_not_called()

    def test_zip_and_platform_metadata_are_checked(self):
        self.install('platforms;android-33')
        self.assertTrue(sdk.valid(self.sdk,'platforms;android-33'))
        (self.sdk/'platforms/android-33/android.jar').write_text('not a zip')
        self.assertFalse(sdk.valid(self.sdk,'platforms;android-33'))

    def test_retry_is_bounded_and_backed_off(self):
        with patch.object(sdk.subprocess,'run',return_value=SimpleNamespace(returncode=1)) as run, patch.object(sdk.time,'sleep') as sleep:
            with self.assertRaisesRegex(ValueError,'SDK_INSTALL_RETRY_EXHAUSTED'):
                sdk.prepare(self.tree,self.flutter,self.sdk,self.output)
            self.assertEqual(run.call_count,3)
            roots=[next(x for x in c.args[0] if x.startswith('--sdk_root=')) for c in run.call_args_list]
            self.assertEqual(len(set(roots)),3)
            self.assertEqual([c.args[0] for c in sleep.call_args_list],[10,20])
            self.assertEqual(json.loads(self.output.read_text())['result'],'FAIL')

    def test_successful_retry_and_valid_component_is_preserved(self):
        self.install('platforms;android-33')
        marker=self.sdk/'platforms/android-33/keep'
        marker.touch()
        def install(*args,**kwargs):
            staging=Path(next(x.split('=',1)[1] for x in args[0] if x.startswith('--sdk_root=')))
            self.install('platforms;android-36',staging)
            return SimpleNamespace(returncode=0)
        with patch.object(sdk.subprocess,'run',side_effect=install) as run:
            report=sdk.prepare(self.tree,self.flutter,self.sdk,self.output)
        self.assertEqual(report['result'],'PASS')
        self.assertTrue(marker.exists())
        self.assertNotIn('platforms;android-33',run.call_args.args[0])

    def test_installer_timeout_exhausts_budget_without_accepting_bad_zip(self):
        from subprocess import TimeoutExpired
        with patch.object(sdk.subprocess,'run',side_effect=TimeoutExpired('sdkmanager',300)), patch.object(sdk.time,'sleep'):
            with self.assertRaisesRegex(ValueError,'SDK_INSTALL_RETRY_EXHAUSTED'):
                sdk.prepare(self.tree,self.flutter,self.sdk,self.output)
        report=json.loads(self.output.read_text())
        self.assertEqual([a['exit_code'] for a in report['attempts']],['timeout']*3)



class RecoveryTests(unittest.TestCase):
    def setUp(self):
        isolation=isolated_summary()
        isolation.__enter__()
        self.addCleanup(isolation.__exit__,None,None,None)
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)/'report.json'
        self.run=dict(id=123,repository={'full_name':'example/repo'},head_repository={'full_name':'example/repo'},
                      event='workflow_dispatch',head_branch='main',path='.github/workflows/nightly.yml',
                      status='completed',conclusion='failure',head_sha='a'*40,run_attempt=1,
                      created_at='2026-10-29T17:47:00Z',
                      display_title='Nightly latest / '+'a'*40+' / draft / wayland=true / android-signing=true')
        self.job=dict(id=456,check_run_url='https://api.github.com/repos/example/repo/check-runs/789',name='android-build / Build Android targets / android-x86_64-standard',
                      conclusion='failure',steps=[{'name':'Download source','conclusion':'cancelled'}],
                      created_at='2026-10-29T17:53:43Z',started_at='2026-10-29T17:53:45Z',
                      completed_at='2026-10-29T17:53:54Z')

    def invoke(self, log='The runner has received a shutdown signal.', annotations=None):
        def api(path):
            if '/compare/' in path:return {'status':'ahead'}
            return self.run
        def pages(path,key=None):
            return [self.job] if '/jobs?' in path else annotations or []
        def gh(*args):
            return '' if '--method' in args else log
        with patch.object(recovery,'api',side_effect=api),patch.object(recovery,'pages',side_effect=pages),patch.object(recovery,'gh',side_effect=gh) as calls:
            report=recovery.process({'workflow_run':copy.deepcopy(self.run)},'example/repo',self.output)
            return report,calls

    def test_partial_retry_keeps_prior_success_and_other_failed_targets(self):
        previous=dict(self.job,run_attempt=1)
        retry=dict(self.job,id=999,run_attempt=2,conclusion='success')
        other=dict(self.job,id=457,name='other / macos-aarch64-standard',run_attempt=1)
        success=dict(self.job,id=458,name='other / linux-aarch64-standard',run_attempt=1,conclusion='success')
        selected=recovery.latest_jobs([previous,other,success,retry])
        self.assertEqual(selected,[retry,other,success])

    def test_both_windows_callers_have_recoverable_leaf_jobs(self):
        stable=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())
        nightly=yaml.safe_load((ROOT/'.github/workflows/nightly.yml').read_text())
        for workflow, caller in ((stable,stable['jobs']['windows-build']['name']),
                                 (nightly,nightly['jobs']['windows-build'].get('name','windows-build'))):
            self.run['path']='.github/workflows/tag.yml' if workflow is stable else '.github/workflows/nightly.yml'
            self.run['display_title']='Stable 1.5.1 / draft / wayland=true / android-signing=true' if workflow is stable else 'Nightly latest / '+'a'*40+' / draft / wayland=true / android-signing=true'
            for variant in ('standard','sos','aarch64-standard','aarch64-sos'):
                with self.subTest(caller=caller,variant=variant):
                    self.job['name']=caller+' / build/windows-'+variant
                    report,calls=self.invoke()
                    self.assertEqual(report['recovery'],'REQUESTED')
                    self.assertIn(('api','repos/example/repo/actions/jobs/456/logs'),[c.args for c in calls.call_args_list])
                    self.job.update(steps=[],conclusion='cancelled')
                    report,_=self.invoke(annotations=[{'message':'Due to capacity constraints'}])
                    self.assertTrue(report['jobs'][0]['retry_eligible'])
                    self.job.update(steps=[{'name':'Download source','conclusion':'cancelled'}],conclusion='failure')
            for suffix in ('Build shared Windows helper','Validate Windows build provenance',
                           'Validate native Windows ARM64 provenance','arm64-bridge','build/windows-web'):
                with self.subTest(caller=caller,suffix=suffix):
                    self.assertFalse(recovery.target_job({'name':caller+' / '+suffix}))
        self.assertFalse(recovery.target_job({'name':'unrelated / build/windows-standard'}))

    def test_only_failed_leaf_and_dependents_are_retried(self):
        report,calls=self.invoke()
        self.assertEqual(report['recovery'],'REQUESTED')
        posts=[c.args for c in calls.call_args_list if '--method' in c.args]
        self.assertEqual(posts,[('api','--method','POST','repos/example/repo/actions/jobs/456/rerun')])
        self.assertEqual(report['jobs'][0]['queue_seconds'],2)
        self.assertEqual(report['custom_sha'],'a'*40)

    def test_compile_failure_is_not_retried(self):
        report,calls=self.invoke('error[E0425]: cannot find value')
        self.assertEqual(report['jobs'][0]['reason'],'BUILD_OR_UNKNOWN')
        self.assertFalse(any('--method' in c.args for c in calls.call_args_list))

    def test_sdk_zip_error_requires_specific_installer_evidence(self):
        self.assertEqual(recovery.classify(self.job,[],'Archive is not a ZIP archive'),'BUILD_OR_UNKNOWN')
        report,_=self.invoke('Archive is not a ZIP archive; Install Android SDK Platform 33; Failed to install the following SDK components')
        self.assertEqual(report['jobs'][0]['reason'],'SDK_DOWNLOAD')

    def test_capacity_without_steps_has_no_fake_zero_queue(self):
        self.job.update(steps=[],conclusion='cancelled')
        report,_=self.invoke(annotations=[{'message':'The job was not acquired by Runner of type hosted'}])
        job=report['jobs'][0]
        self.assertEqual(job['reason'],'RUNNER_CAPACITY')
        self.assertIsNone(job['queue_seconds'])
        self.assertEqual(job['unassigned_seconds'],11)

    def test_signing_publication_source_and_successful_upload_are_excluded(self):
        for name in ('Sign Nightly Android production artifacts','prepare / prepare','aggregate', 'Create qualified Nightly draft'):
            self.job['name']=name
            report,calls=self.invoke()
            self.assertFalse(report['jobs'][0]['retry_eligible'])
            self.assertFalse(any('--method' in c.args for c in calls.call_args_list))
        self.job['name']='android-build / Build Android targets / android-x86_64-standard'
        self.job['steps']=[dict(name='Upload validated target only',conclusion='success')]
        report,_=self.invoke()
        self.assertFalse(report['jobs'][0]['retry_eligible'])

    def test_retry_budget_public_release_and_disabled_switch(self):
        self.run['run_attempt']=3
        report,_=self.invoke()
        self.assertEqual(report['recovery'],'MANUAL_REVIEW')
        self.run['run_attempt']=1
        self.run['display_title']=self.run['display_title'].replace('/ draft /','/ release /')
        report,_=self.invoke()
        self.assertEqual(report['recovery'],'MANUAL_REVIEW')
        self.run['display_title']=self.run['display_title'].replace('/ release /','/ draft /')
        with patch.dict(os.environ,BUILD_INFRA_AUTO_RETRY_ENABLED='false'):
            report,_=self.invoke()
            self.assertEqual(report['recovery'],'MANUAL_REVIEW')

    def test_foreign_main_history_cannot_be_retried(self):
        def api(path):
            return {'status':'diverged'} if '/compare/' in path else self.run
        with patch.object(recovery,'api',side_effect=api), patch.object(recovery,'pages',side_effect=lambda path,key=None:[self.job] if '/jobs?' in path else []), patch.object(recovery,'gh',return_value='The runner has received a shutdown signal.') as gh:
            with self.assertRaisesRegex(ValueError,'not in main history'):
                recovery.process({'workflow_run':self.run},'example/repo',self.output)
        self.assertFalse(any('--method' in c.args for c in gh.call_args_list))
        self.assertEqual(json.loads(self.output.read_text())['recovery'],'MANUAL_REVIEW')

    def test_stale_event_does_not_duplicate_a_manual_retry(self):
        incoming=copy.deepcopy(self.run)
        self.run.update(status='in_progress',run_attempt=2)
        with patch.object(recovery,'api',return_value=self.run),patch.object(recovery,'gh') as gh:
            report=recovery.process({'workflow_run':incoming},'example/repo',self.output)
        self.assertEqual(report['recovery'],'SKIPPED_STALE_EVENT')
        gh.assert_not_called()

    def test_untrusted_context_cannot_regain_privileges(self):
        for changes in ({'head_branch':'development'},{'event':'pull_request'},
                        {'head_repository':{'full_name':'attacker/repo'}},
                        {'path':'.github/workflows/ci.yml'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                recovery.verify_run(dict(self.run,**changes),'example/repo')

    def test_workflow_has_fixed_trusted_checkout_and_no_credentials(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/build-reliability.yml').read_text())
        self.assertEqual(workflow['on']['workflow_run']['types'],['completed'])
        job=workflow['jobs']['observe']
        self.assertEqual(job['steps'][0]['with'],{'ref':'main','persist-credentials':False})
        self.assertEqual(job['permissions'],{'contents':'read','actions':'write','checks':'read'})
        build=yaml.safe_load((ROOT/'.github/workflows/build-platform.yml').read_text())['jobs']['platform-build']['steps']
        ids=[s.get('id') for s in build]
        self.assertLess(ids.index('source'),ids.index('android-sdk'))
        self.assertLess(ids.index('profile'),ids.index('android-sdk'))
        self.assertLess(ids.index('android-sdk'),ids.index('vcpkg'))
        self.assertLess(ids.index('android-sdk'),ids.index('build'))


if __name__=='__main__':run_contract_tests('Build reliability contracts')
