"""Summary presentation, real evidence and simulation isolation contracts."""
from contextlib import redirect_stderr, redirect_stdout
from html.parser import HTMLParser
import io
import json
import os
import re
import shlex
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml
from scripts.validation import summary as ui
from scripts.validation import summary_dashboard as collector

ROOT=Path(__file__).resolve().parents[2]


class SummaryContract(unittest.TestCase):
    def setUp(self):
        isolation=ui.isolated_summary()
        isolation.__enter__()
        self.addCleanup(isolation.__exit__,None,None,None)
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'summary.md'

    def test_all_statuses_are_distinct_and_unknown_is_not_pass(self):
        for state in ('PASS','FAIL','WARNING','NOT RUN','SKIPPED','RUNNING'):
            self.assertIn(state,ui.badge(state))
        for state in (None,'N/A','NOT PASSED','FAIL (SIMULATED)',True):
            self.assertEqual(ui.state(state),'NOT RUN')
        self.assertEqual(ui.state('success'),'PASS')
        self.assertEqual(ui.state('failure'),'FAIL')
        self.assertEqual(ui.state('skipped'),'SKIPPED')
        self.assertEqual(ui.overall(['PASS','NOT RUN']),'NOT RUN')
        self.assertEqual(ui.overall(['PASS','WARNING']),'WARNING')
        self.assertEqual(ui.overall(['PASS','FAIL']),'FAIL')

    def test_markdown_and_html_injection_are_escaped_in_cells(self):
        payload='a|b\n# heading [link](javascript:alert(1)) `x` *bold* <script>x</script> & \\ '
        rendered=ui.table(('Field','Value'),[('name',payload)])
        self.assertNotIn('<script>',rendered)
        self.assertNotIn('[link]',rendered)
        self.assertNotIn('`x`',rendered)
        self.assertNotIn('*bold*',rendered)
        self.assertIn('&#124;',rendered)
        self.assertIn('<br>',rendered)
        for line in rendered.splitlines():
            if line.startswith('|'):self.assertEqual(line.count('|'),3)

    def test_quotes_and_existing_entities_do_not_double_escape(self):
        self.assertEqual(ui.text('O\'Reilly "quoted" & <>'), 'O\'Reilly "quoted" &amp; &lt;&gt;')
        self.assertEqual(ui.text('&lt;script&gt;'), '&amp;lt;script&amp;gt;')

    def test_folded_json_cannot_escape_html(self):
        output=ui.details('diagnostic <bad>',{'value':'</pre></details><script>alert(1)</script>```'})
        self.assertNotIn('<script>',output)
        self.assertEqual(output.count('<details>'),1)
        self.assertEqual(output.count('</details>'),1)
        class Balanced(HTMLParser):
            def __init__(self):super().__init__();self.stack=[]
            def handle_starttag(self,tag,attrs):self.stack.append(tag)
            def handle_endtag(self,tag):
                if not self.stack or self.stack.pop()!=tag:raise AssertionError(tag)
        parser=Balanced();parser.feed(output)
        self.assertEqual(parser.stack,[])

    def test_missing_data_displays_unknown_counts_and_not_run(self):
        output=ui.dashboard({})
        self.assertNotIn('✅ PASS',output)
        self.assertIn('| Succeeded | — |',output)
        self.assertIn('| Failed | — |',output)
        self.assertIn('NOT RUN',output)
        self.assertNotIn('Automatic recovery',output)

    def test_actual_overview_counts_time_and_identity(self):
        run=dict(name='Actual workflow',id=123,run_attempt=2,head_sha='a'*40,status='completed',conclusion='failure',created_at='2026-10-30T10:00:00Z')
        jobs=[dict(name='build / android-x86_64-standard',conclusion='success',completed_at='2026-10-30T10:02:05Z'),dict(name='failed',conclusion='failure'),dict(name='skipped',conclusion='skipped')]
        output=ui.overview_card(run,jobs,dict(upstream_version='1.5.1',upstream_sha='b'*40))
        for expected in ('Actual workflow','123 / 2','a'*40,'2m 5s','| Succeeded | 1 |','| Failed | 1 |','| Skipped | 1 |','1&#46;5&#46;1'):
            self.assertIn(expected,output)

    def test_separate_real_reports_merge_without_promoting_unexecuted_sdk(self):
        reports=[dict(upstream_sha='a'*40,patchset='v2',variants={'standard':{'Patch Apply':'PASS','Rust real-config compile':'PASS','Build System':'WARNING'}}),
                 dict(upstream_sha='a'*40,patchset='v2',variants={'standard':{'Rust real-config compile':'NOT RUN','Flutter Analyze':'PASS'}}),
                 dict(upstream_sha='other',patchset='v2',variants={'sos':{'Patch Apply':'PASS'}})]
        values=ui.merge_compatibility(reports,'a'*40,'v2')
        self.assertEqual(values['standard']['Rust Compile'],'PASS')
        self.assertEqual(values['standard']['SDK Preflight'],'NOT RUN')
        self.assertEqual(values['sos']['Patch Apply'],'NOT RUN')
        output=ui.compatibility_cards(values)
        self.assertIn('| SDK Preflight | ⬜ NOT RUN | ⬜ NOT RUN |',output)
        self.assertIn('| Overall Compatibility | ⬜ NOT RUN | ⬜ NOT RUN |',output)

    def test_simulated_and_malformed_reports_are_never_production_passes(self):
        values=ui.merge_compatibility([None,{'variants':None},dict(simulated=True,variants={'standard':{'Patch Apply':'PASS'}}),dict(variants={'standard':{'Patch Apply':'FAIL (SIMULATED)'}})])
        self.assertTrue(all(x=='NOT RUN' for v in values.values() for x in v.values()))
        self.assertEqual(ui.recovery_card({'simulated':True,'recovery':'REQUESTED'},3),'')

    def test_failed_variant_remains_failed_even_if_stage_data_is_missing(self):
        values=ui.merge_compatibility([{'Overall':'FAIL','Failed variant':'sos','variants':{'sos':{}}}])
        self.assertIn('| Overall Compatibility | ⬜ NOT RUN | ❌ FAIL |',ui.compatibility_cards(values))

    def test_flutter_warning_is_not_a_green_pass_and_does_not_change_exit_gate(self):
        self.assertEqual(ui.analysis_status('warning • Unused import • x.dart:3:1',0),'WARNING')
        self.assertEqual(ui.analysis_status('info • lint hint',0),'PASS')
        self.assertEqual(ui.analysis_status('error • undefined name',1),'FAIL')

    def test_recovery_card_uses_real_decision_and_remaining_faults(self):
        report=dict(attempt=2,recovery='REQUESTED',retry_job_id=7,jobs=[dict(id=7,name='bad|job',reason='RUNNER_SHUTDOWN',retry_eligible=True),dict(id=8,name='compile',reason='BUILD_OR_UNKNOWN',retry_eligible=False)])
        output=ui.recovery_card(report,3)
        for expected in ('REQUESTED','RUNNER&#95;SHUTDOWN','bad&#124;job','| Current attempt | 2 |','| Maximum run attempts | 3 |','| Human intervention | YES |'):
            self.assertIn(expected,output)
        self.assertIn('MANUAL REVIEW',output)

    def test_missing_recovery_limit_is_not_invented(self):
        output=ui.dashboard({'id':123},recovery={'recovery':'NOT_NEEDED'})
        self.assertIn('| Maximum run attempts | — |',output)
        self.assertIn('| Maximum additional retries | — |',output)

    def test_detailed_files_and_json_only_appear_inside_fold(self):
        report={'variants':{'standard':{'Build System':'WARNING','Changed build files':['build.py','Cargo.toml']}}}
        output=ui.compatibility_report_card(report)
        before,fold=output.split('<details>',1)
        self.assertNotIn('Cargo.toml',before)
        self.assertIn('Cargo.toml',fold)
        self.assertEqual(output.count('Changed build files'),1)
        self.assertEqual(output.count('<pre>'),1)

    def test_compatibility_build_failure_survives_renderer_error(self):
        from scripts.validation import compatibility
        with patch.object(compatibility,'ROOT',Path(self.temp.name)),patch.object(sys,'argv',['compatibility.py','rust','--variant','standard']),patch.object(compatibility,'run',side_effect=RuntimeError('compiler failed')),patch.object(ui,'compatibility_report_card',side_effect=RuntimeError('renderer failed')),patch.dict(os.environ,GITHUB_STEP_SUMMARY=str(self.path)),redirect_stderr(io.StringIO()):
            code=compatibility.main()
        self.assertEqual(code,1)
        saved=json.loads((Path(self.temp.name)/'.work/validation/report.json').read_text())
        self.assertEqual(saved['Overall'],'FAIL')
        self.assertEqual(saved['variants']['standard']['Rust real-config compile'],'FAIL')

    def test_generation_report_preserves_gate_and_merges_variant_evidence(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/compat-check.yml').read_text())
        run=next(s['run'] for s in workflow['jobs']['validation-report']['steps'] if s.get('name')=='Report generation and actual compile coverage')
        script='\n'.join(run.splitlines()[1:-1])
        folder=Path(self.temp.name)
        for name,values in [('preflight',{'Patch Apply':'PASS','Rust real-config compile':'PASS','Build System':'WARNING'}),('flutter',{'Patch Apply':'PASS','Flutter Analyze':'PASS'})]:
            path=folder/'diagnostics'/name/'report.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps(dict(upstream_sha='a'*40,patchset='v2',variants={'standard':values,'sos':values})))
        env=dict(os.environ,GITHUB_STEP_SUMMARY=str(self.path),PYTHONPATH=str(ROOT),SELECTED='v2',UPSTREAM_EXPECTED_SHA='a'*40,UPSTREAM_VERSION='1.5.1',CONTRACT_RESULT='success',PREFLIGHT_RESULT='success',BRIDGE_RESULT='success',FLUTTER_RESULT='success',HELPER_RESULT='skipped',CHANNEL='ci',ANDROID_SIGNING_SMOKE='false')
        result=subprocess.run([sys.executable,'-c',script],cwd=folder,env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads((folder/'compatibility-report.json').read_text())
        self.assertEqual(report['overall'],'PASS')
        self.assertEqual(report['full_compatibility'],'COMPATIBLE')
        self.assertEqual(report['variants']['standard']['Rust Compile'],'PASS')
        self.assertEqual(report['variants']['sos']['Flutter Analyze'],'PASS')
        self.assertEqual(report['variants']['sos']['SDK Preflight'],'NOT RUN')
        self.assertEqual(self.path.read_text().count('<pre>'),1)
        env['FLUTTER_RESULT']='failure'
        result=subprocess.run([sys.executable,'-c',script],cwd=folder,env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads((folder/'compatibility-report.json').read_text())['overall'],'FAIL')
        self.assertEqual(self.path.read_text().count('<pre>'),1)

    def test_repeated_section_is_replaced_and_other_sections_preserved(self):
        with patch.dict(os.environ,GITHUB_STEP_SUMMARY=str(self.path)):
            ui.publish('tests',ui.card,'Tests',[('Passed',20)])
            ui.publish('dashboard',ui.details,'Old evidence',{'old':'payload'})
            ui.publish('dashboard',ui.details,'New evidence',{'new':'payload'})
        output=self.path.read_text()
        self.assertEqual(output.count('rustdesk-summary:dashboard:begin'),1)
        self.assertEqual(output.count('rustdesk-summary:tests:begin'),1)
        self.assertNotIn('Old evidence',output)
        self.assertEqual(output.count('New evidence'),1)

    def test_renderer_and_filesystem_failures_do_not_raise_or_change_build_result(self):
        with patch.dict(os.environ,GITHUB_STEP_SUMMARY=str(self.path)),redirect_stderr(io.StringIO()):
            self.assertFalse(ui.publish('bad',lambda:1/0))
            with patch.object(Path,'write_text',side_effect=OSError('read-only')):
                self.assertFalse(ui.publish('bad',lambda:'text'))
        with patch.dict(os.environ,{},clear=True):
            self.assertFalse(ui.publish('missing',lambda:1/0))

    def test_utf8_and_github_path_with_spaces(self):
        target=Path(self.temp.name)/'GitHub Summary 文件.md'
        with patch.dict(os.environ,GITHUB_STEP_SUMMARY=str(target)):
            self.assertTrue(ui.publish('utf8',ui.card,'✅ 中文',[('状态','PASS')]))
            self.assertTrue(ui.publish('utf8',ui.card,'✅ 中文',[('状态','FAIL')]))
        self.assertIn('FAIL',target.read_text(encoding='utf-8'))
        self.assertEqual(target.read_text(encoding='utf-8').count('✅ 中文'),1)

    def test_large_details_keep_full_artifact_as_authority(self):
        rendered=ui.details('large',{'log':'x'*20000})
        self.assertIn('complete evidence remains in Artifacts',rendered)
        self.assertLess(len(rendered),17000)

    def test_simulated_suite_writes_only_one_count_card_and_keeps_console_logs(self):
        env=dict(os.environ,GITHUB_STEP_SUMMARY=str(self.path),PYTHONPATH='.')
        result=subprocess.run([sys.executable,'-m','scripts.validation.build_reliability_contract'],cwd=ROOT,env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Android SDK preflight attempt',result.stdout)
        output=self.path.read_text()
        count=int(re.search(r'Ran ([0-9]+) tests',result.stderr).group(1))
        self.assertGreater(count,0)
        self.assertIn(f'| Passed | {count} |',output)
        self.assertIn('| Failed | 0 |',output)
        self.assertNotIn('Automatic recovery',output)
        self.assertNotIn('REQUESTED',output)
        self.assertNotIn('example/repo',output)
        self.assertEqual(output.count('rustdesk-summary:'),2)

    def test_test_result_failure_counts_and_reasons(self):
        class Case(unittest.TestCase):
            def runTest(self):self.fail('necessary | reason')
        result=unittest.TestResult();Case().run(result)
        output=ui.test_card(result,'Self-test')
        self.assertIn('| Failed | 1 |',output)
        self.assertIn('| Passed | 0 |',output)
        self.assertIn('necessary | reason',output)
        self.assertIn('<details>',output)

    def test_read_only_observer_has_no_recovery_or_signing_privileges(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/build-reliability.yml').read_text())
        self.assertEqual(workflow['jobs']['ci-dashboard']['permissions'],{'contents':'read','actions':'read'})
        self.assertEqual(workflow['jobs']['ci-dashboard']['steps'][0]['with']['ref'],'main')
        self.assertEqual(workflow['jobs']['observe']['permissions'],{'contents':'read','actions':'write','checks':'read'})
        self.assertIn("workflow_run.name != 'CI - Patch and Build compatibility'",workflow['jobs']['observe']['if'])

    def test_observer_entrypoint_imports_summaries_without_pythonpath(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/build-reliability.yml').read_text())
        command=shlex.split(next(s['run'] for s in workflow['jobs']['observe']['steps'] if s.get('name')=='Record scheduling and recover one infrastructure target'))
        self.assertEqual(command,['python3','-m','scripts.validation.build_reliability'])
        workspace=Path(self.temp.name)/'workspace with spaces'
        scripts=workspace/'scripts/validation'
        scripts.mkdir(parents=True)
        for name in ('build_reliability.py','summary.py','summary_dashboard.py'):
            shutil.copy2(ROOT/'scripts/validation'/name,scripts/name)
        event=workspace/'event.json'
        run=dict(id=42,repository={'full_name':'example/repo'},head_repository={'full_name':'example/repo'},
                 event='workflow_dispatch',head_branch='main',path='.github/workflows/nightly.yml',
                 status='completed',conclusion='success',head_sha='a'*40,run_attempt=1,
                 created_at='2026-10-30T10:00:00Z',display_title='Nightly latest / '+'a'*40+' / draft / wayland=true / android-signing=true')
        event.write_text(json.dumps({'workflow_run':run}))
        bootstrap="""
import json,os,runpy,sys
from types import SimpleNamespace
from unittest.mock import patch
run=json.load(open(os.environ['GITHUB_EVENT_PATH']))['workflow_run']
def fake_gh(command,**kwargs):
    assert command[:2]==['gh','api'],command
    assert '--method' not in command, 'entrypoint must not mutate this successful fixture'
    endpoint=command[2].split('?')[0]
    if endpoint.endswith('/jobs'): data={'jobs':[]}
    elif endpoint.endswith('/artifacts'): data={'artifacts':[]}
    elif endpoint.endswith('/runs/42'): data=run
    else: raise AssertionError(endpoint)
    return SimpleNamespace(stdout=json.dumps(data),returncode=0)
with patch('subprocess.run',side_effect=fake_gh):
    runpy.run_module(sys.argv[1],run_name='__main__')
"""
        env=dict(os.environ,GITHUB_EVENT_PATH=str(event),GITHUB_REPOSITORY='example/repo',GITHUB_STEP_SUMMARY=str(self.path))
        env.pop('PYTHONPATH',None)
        result=subprocess.run([sys.executable,'-c',bootstrap,command[2]],cwd=workspace,env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads((workspace/'.work/build-reliability/report.json').read_text())['recovery'],'NOT_NEEDED')
        self.assertTrue((workspace/'.work/build-reliability/dashboard-evidence.json').is_file())
        output=self.path.read_text()
        self.assertIn('Run overview',output)
        self.assertIn('Automatic recovery',output)
        self.assertEqual(output.count('rustdesk-summary:dashboard:begin'),1)

    def test_only_new_presentation_job_is_advisory(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/ci.yml').read_text())
        self.assertTrue(workflow['jobs']['dashboard']['continue-on-error'])
        for name in ('classify','resolve','compatibility','qualification'):
            self.assertFalse(workflow['jobs'][name].get('continue-on-error',False))
        compatibility=yaml.safe_load((ROOT/'.github/workflows/compat-check.yml').read_text())
        for name in ('contracts','preflight','bridge','flutter-analyze','windows-helper'):
            self.assertFalse(compatibility['jobs'][name].get('continue-on-error',False))

    def test_snapshot_does_not_turn_api_failure_into_zero_counts_or_pass(self):
        with patch.dict(os.environ,GITHUB_STEP_SUMMARY=str(self.path)),patch.object(collector,'collect',side_effect=RuntimeError),redirect_stdout(io.StringIO()):
            self.assertFalse(collector.publish_run('example/repo',123))
        output=self.path.read_text()
        self.assertIn('unavailable',output)
        self.assertNotIn('✅ PASS',output)
        self.assertNotIn('| Succeeded | 0 |',output)

    def test_legacy_variant_artifacts_are_recovered_only_for_the_same_source(self):
        run={'id':123,'head_sha':'c'*40}
        names=['channel-discovery-123','generation-compatibility-123','preflight-standard-report-123','flutter-standard-report-123','preflight-sos-report-123']
        data={names[0]:{'upstream_sha':'a'*40},names[1]:{'upstream_version':'1.5.1','selected':'v2'},
              names[2]:{'upstream_sha':'a'*40,'patchset':'v2','variants':{'standard':{'Patch Apply':'PASS','Rust real-config compile':'PASS'}}},
              names[3]:{'upstream_sha':'a'*40,'patchset':'v2','variants':{'standard':{'Flutter Analyze':'PASS'}}},
              names[4]:{'upstream_sha':'b'*40,'patchset':'v2','variants':{'sos':{'Patch Apply':'PASS'}}}}
        with patch.object(collector,'snapshot',return_value=(run,[])),patch.object(collector,'pages',return_value=[{'name':name} for name in names]),patch.object(collector,'read_artifact',side_effect=lambda repo,run_id,name,filename:data[name]):
            _,_,upstream,values=collector.collect('example/repo',123)
        self.assertEqual(upstream['upstream_version'],'1.5.1')
        self.assertEqual(values['standard']['Rust Compile'],'PASS')
        self.assertEqual(values['standard']['Flutter Analyze'],'PASS')
        self.assertEqual(values['sos']['Patch Apply'],'NOT RUN')

    def test_foreign_source_generation_metadata_is_not_used(self):
        data={'channel-discovery-123':{'upstream_sha':'a'*40},'generation-compatibility-123':{'upstream_sha':'b'*40,'upstream_version':'9.0.0','patchset':'v2','variants':{'standard':{'Patch Apply':'PASS'}}}}
        with patch.object(collector,'snapshot',return_value=({'id':123},[])),patch.object(collector,'pages',return_value=[{'name':name} for name in data]),patch.object(collector,'read_artifact',side_effect=lambda repo,run_id,name,filename:data[name]):
            _,_,upstream,values=collector.collect('example/repo',123)
        self.assertNotIn('upstream_version',upstream)
        self.assertEqual(values['standard']['Patch Apply'],'NOT RUN')

    def test_sdk_summary_requires_all_android_architectures_evidence(self):
        run={'id':123,'repository':{'full_name':'example/repo'}}
        jobs=[dict(name='build / android-aarch64-standard',steps=[{'name':'Prepare and verify Android SDK before native compilation','conclusion':'success'}]),dict(name='build / android-x86_64-standard',steps=[])]
        with patch.object(collector,'snapshot',return_value=(run,jobs)),patch.object(collector,'pages',return_value=[]):
            _,_,_,values=collector.collect('example/repo',123)
        self.assertEqual(values['standard']['SDK Preflight'],'NOT RUN')
        self.assertEqual(values['sos']['SDK Preflight'],'NOT RUN')


if __name__=='__main__':ui.run_contract_tests('Summary contracts')
