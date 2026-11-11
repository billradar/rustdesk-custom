#!/usr/bin/env python3
"""Report-only automation must never approve an interface or mutate protected code."""
import copy
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
from scripts.upstream import interface_review as review


class ReviewContract(unittest.TestCase):
    def setUp(self):
        self.env={'GITHUB_REPOSITORY':review.REPOSITORY,'GITHUB_REF':'refs/heads/main',
            'GITHUB_EVENT_NAME':'schedule','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'17'}
        self.packet={'schema':review.SCHEMA,'approval':'REQUIRED / NOT APPROVED',
            'upstream_repository':'rustdesk/rustdesk','upstream_sha':'b'*40,'custom_repository_sha':'a'*40,
            'workflow_run':'17','observed_profile':None,'critical':None,
            'checks':{'interface':'UNKNOWN / BLOCKED','rust_compile':'NOT RUN','bridge':'NOT RUN','flutter_analyze':'NOT RUN','runtime':'NOT TESTED'}}

    def test_rejects_foreign_context_stale_packets_and_fabricated_validation(self):
        with patch.dict(os.environ,self.env):
            review.validate_packet(self.packet)
            for key,value in [('approval','APPROVED'),('custom_repository_sha','c'*40),('workflow_run','18'),('upstream_sha','bad')]:
                p=dict(self.packet,**{key:value})
                with self.assertRaises(ValueError):review.validate_packet(p)
            p=copy.deepcopy(self.packet);p['checks']['rust_compile']='PASS'
            with self.assertRaises(ValueError):review.validate_packet(p)
            for key,value in [('GITHUB_REF','refs/heads/development'),('GITHUB_EVENT_NAME','pull_request'),('GITHUB_REPOSITORY','other/repo')]:
                with patch.dict(os.environ,{key:value}),patch.object(review,'request') as api:
                    with self.assertRaises(ValueError):review.publish(self.packet)
                    api.assert_not_called()

    def test_proposal_changes_only_one_document_and_is_draft(self):
        calls=[]
        created=False
        def api(path,method='GET',data=None,missing=False):
            nonlocal created
            calls.append((path,method,data))
            if path.startswith('pulls?'):return []
            if path=='git/ref/heads/main':return {'object':{'sha':'a'*40}}
            if path.startswith('git/ref/heads/'):return {'object':{'sha':'e'*40}} if created else None
            if path.startswith('git/commits/') and method=='GET':return {'tree':{'sha':'d'*40}}
            if path in ['git/trees','git/commits']:return {'sha':'e'*40}
            if path=='git/refs':created=True;return {}
            if path=='pulls':return {'html_url':'https://github.com/billradar/rustdesk-custom/pull/1'}
            raise AssertionError(path)
        with patch.dict(os.environ,self.env),patch.object(review,'request',side_effect=api):
            review.publish(self.packet)
        tree=next(data for path,method,data in calls if path=='git/trees')
        self.assertEqual(len(tree['tree']),1)
        self.assertEqual(tree['tree'][0]['path'],'docs/upstream-interface-reviews/'+'b'*40+'.json')
        pr=next(data for path,method,data in calls if path=='pulls')
        self.assertTrue(pr['draft']);self.assertEqual(pr['base'],'main')
        self.assertFalse(any(method in ['PATCH','PUT','DELETE'] for _,method,_ in calls))

    def test_existing_review_deduplicates_without_writes(self):
        with patch.dict(os.environ,self.env),patch.object(review,'request',return_value=[{'html_url':'existing'}]) as api:
            self.assertEqual(review.publish(self.packet),'existing')
            self.assertEqual(api.call_count,1)

    def test_partial_retry_rejects_branch_with_code_changes(self):
        def api(path,*args,**kw):
            if path.startswith('pulls?'):return []
            if path=='git/ref/heads/main':return {'object':{'sha':'a'*40}}
            if path.startswith('git/ref/heads/'):return {'object':{'sha':'f'*40}}
            if path.startswith('compare/'):return {'files':[{'filename':'metadata/build/adapter-profiles.json','status':'modified'}]}
            raise AssertionError(path)
        with patch.dict(os.environ,self.env),patch.object(review,'request',side_effect=api),self.assertRaisesRegex(ValueError,'unexpected changes'):
            review.publish(self.packet)

    def recovery(self, change=None):
        """An old source report and a new discovery with the same interface."""
        current=copy.deepcopy(self.packet)
        current['critical']={'files':{},'tools':{}}
        current['observed_profile']={'signature':review.build_adapter.digest(current['critical'])}
        stored=copy.deepcopy(current)
        stored.update(upstream_sha='c'*40,custom_repository_sha='d'*40,workflow_run='11')
        path='docs/upstream-interface-reviews/'+'c'*40+'.json'
        state={'files':[{'filename':path,'status':'added','sha':'e'*40}],
            'mode':'100644','truncated':False,'stored':stored,
            'run':{'head_sha':'d'*40,'head_branch':'main','event':'schedule',
                'path':'.github/workflows/upstream-main-compatibility.yml',
                'repository':{'full_name':review.REPOSITORY}}}
        if change:change(state)
        calls=[];refs={'main':0,'branch':0}
        def api(endpoint,method='GET',data=None,missing=False):
            calls.append((endpoint,method,data))
            if endpoint.startswith('pulls?'):return []
            if endpoint=='git/ref/heads/main':
                refs['main']+=1
                sha='0'*40 if state.get('main_changed') and refs['main']>1 else 'a'*40
                return {'object':{'sha':sha}}
            if endpoint.startswith('git/ref/heads/'):
                refs['branch']+=1
                sha='0'*40 if state.get('branch_changed') and refs['branch']>1 else 'f'*40
                return {'object':{'sha':sha}}
            if endpoint=='compare/'+'a'*40+'...'+'f'*40:return {'files':state['files']}
            if endpoint=='git/commits/'+'f'*40:return {'tree':{'sha':'d'*40}}
            if endpoint=='git/trees/'+'d'*40+'?recursive=1':
                return {'truncated':state['truncated'],'tree':[
                    {'path':path,'mode':state['mode'],'type':'blob','sha':'e'*40}]}
            if endpoint=='git/blobs/'+'e'*40:
                raw=state.get('raw',json.dumps(state['stored']).encode())
                return {'encoding':'base64','size':state.get('size',len(raw)),
                        'content':base64.b64encode(raw).decode()}
            if endpoint=='actions/runs/11':return state['run']
            if endpoint=='pulls' and method=='POST':return {'html_url':'recovered-draft'}
            raise AssertionError(endpoint)
        return current,calls,api

    def test_same_interface_different_source_recovers_only_the_missing_pr(self):
        current,calls,api=self.recovery()
        with patch.dict(os.environ,self.env),patch.object(review,'request',side_effect=api):
            self.assertEqual(review.publish(current),'recovered-draft')
        writes=[(path,method) for path,method,_ in calls if method!='GET']
        self.assertEqual(writes,[('pulls','POST')])
        pr=next(data for path,_,data in calls if path=='pulls')
        self.assertTrue(pr['draft'])
        self.assertEqual(pr['head'],'automation/upstream-interface-'+current['observed_profile']['signature'])
        self.assertIn('`'+'c'*40+'`',pr['body'])
        self.assertIn('`'+'b'*40+'`',pr['body'])
        self.assertIn('/actions/runs/11',pr['body'])
        self.assertIn('/actions/runs/17',pr['body'])
        self.assertIn('historical report source',pr['body'])

    def test_recovery_rejects_untrusted_reports_and_changed_refs_without_writes(self):
        changes={
            'extra code':lambda s:s['files'].append({'filename':'src/main.rs','status':'modified'}),
            'symlink':lambda s:s.update(mode='120000'),
            'executable':lambda s:s.update(mode='100755'),
            'truncated tree':lambda s:s.update(truncated=True),
            'oversized':lambda s:s.update(size=2*1024*1024),
            'invalid JSON':lambda s:s.update(raw=b'not JSON'),
            'wrong filename identity':lambda s:s['stored'].update(upstream_sha='0'*40),
            'fabricated build':lambda s:s['stored']['checks'].update(rust_compile='PASS'),
            'approved report':lambda s:s['stored'].update(approval='APPROVED'),
            'digest mismatch':lambda s:s['stored']['critical'].update(unexpected=True),
            'untrusted workflow':lambda s:s['run'].update(path='.github/workflows/other.yml'),
            'foreign run':lambda s:s['run'].update(repository={'full_name':'other/repo'}),
            'wrong historical commit':lambda s:s['run'].update(head_sha='0'*40),
            'main advanced':lambda s:s.update(main_changed=True),
            'branch changed':lambda s:s.update(branch_changed=True),
        }
        for name,change in changes.items():
            with self.subTest(name=name):
                current,calls,api=self.recovery(change)
                with patch.dict(os.environ,self.env),patch.object(review,'request',side_effect=api):
                    with self.assertRaises(ValueError):review.publish(current)
                self.assertFalse(any(method!='GET' for _,method,_ in calls))

    def test_different_valid_interface_cannot_reuse_the_branch(self):
        def change(state):
            state['stored']['critical']={'files':{'different':'input'}}
            state['stored']['observed_profile']['signature']=review.build_adapter.digest(state['stored']['critical'])
        current,calls,api=self.recovery(change)
        with patch.dict(os.environ,self.env),patch.object(review,'request',side_effect=api):
            with self.assertRaisesRegex(ValueError,'different source or interface'):review.publish(current)
        self.assertFalse(any(method!='GET' for _,method,_ in calls))

    def test_known_interface_creates_no_report(self):
        profile={'signature':'known'}
        approved={'approved':{'linux':['approved'],'macos':['approved'],'android':['approved']}}
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,self.env),patch.object(review.subprocess,'check_output',side_effect=['b'*40+'\n','']),patch.object(review.build_adapter,'inspect',return_value=(profile,{})),patch.object(review.platform_adapter,'inspect',return_value=({'signature':'approved'},{})),patch.object(review.json,'loads',side_effect=[{'profiles':[profile]},approved]):
            out=Path(td)/'out'
            self.assertIsNone(review.collect(Path(td),'b'*40,out));self.assertFalse(out.exists())

    def test_unknown_platform_interface_is_not_hidden_by_known_bridge_profile(self):
        profile={'signature':'known','id':'test-base','reviewed_upstream_sha':'c'*40}
        approved={'approved':{'linux':['approved'],'macos':['approved'],'android':['approved']}}
        observations=[({'signature':'unknown'}, {})]+[({'signature':'approved'}, {}) for _ in range(6)]
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,self.env),patch.object(review.subprocess,'check_output',side_effect=['b'*40+'\n','']),patch.object(review.build_adapter,'inspect',return_value=(profile,{})),patch.object(review.platform_adapter,'inspect',side_effect=observations),patch.object(review.json,'loads',side_effect=[{'profiles':[profile]},approved]):
            out=Path(td)/'out'
            packet=review.collect(Path(td),'b'*40,out)
            self.assertTrue(out.exists())
            self.assertEqual(packet['platform_unknown'],['linux/x86_64: unknown'])
            self.assertEqual(packet['approval'],'REQUIRED / NOT APPROVED')

    def test_collected_native_review_survives_json_artifact_round_trip(self):
        critical={'files':{},'tools':{}}
        profile={'signature':review.build_adapter.digest(critical),
                 'id':'test-base','reviewed_upstream_sha':'c'*40}
        # YAML 1.1 turns the actual Linux matrix's `on` key into True.
        observed={'signature':'d'*64,
                  'official_matrix':yaml.safe_load('on: ubuntu-22.04\narch: x86_64\n')}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);meta=root/'metadata';(meta/'build').mkdir(parents=True)
            (meta/'platform').mkdir()
            (meta/'build/adapter-profiles.json').write_text(json.dumps({'profiles':[profile]}))
            (meta/'platform/adapter-profiles.json').write_text(json.dumps(
                {'approved':{'linux':[],'macos':[],'android':[]}}))
            with patch.dict(os.environ,self.env),patch.object(review,'ROOT',root),patch.object(
                    review.subprocess,'check_output',side_effect=['b'*40+'\n','']),patch.object(
                    review.build_adapter,'inspect',return_value=(profile,critical)),patch.object(
                    review.platform_adapter,'inspect',return_value=(observed,{})):
                packet=review.collect(root,'b'*40,root/'out')
                loaded=json.loads((root/'out/proposal.json').read_text())
                review.validate_packet(loaded)
                self.assertEqual(loaded,packet)
                self.assertEqual(review.report_identity(loaded),review.report_identity(packet))
                changed=copy.deepcopy(loaded)
                changed['platform_interfaces']['linux/x86_64']['official_matrix']['arch']='aarch64'
                with self.assertRaisesRegex(ValueError,'Native platform review identity mismatch'):
                    review.validate_packet(changed)

    def test_unknown_interface_records_patch_failure_without_approving(self):
        critical={'files':{},'tools':{}};profile={'signature':review.build_adapter.digest(critical),'upstream_version':'1.5.1'}
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,self.env),patch.object(review.subprocess,'check_output',side_effect=['b'*40+'\n','']),patch.object(review.build_adapter,'inspect',return_value=(profile,critical)),patch.object(review.shutil,'copytree'),patch.object(review.subprocess,'run') as run:
            run.return_value.returncode=1;run.return_value.stdout='patch conflict';run.return_value.stderr=''
            p=review.collect(Path(td),'b'*40,Path(td)/'out')
            self.assertEqual(p['approval'],'REQUIRED / NOT APPROVED')
            self.assertEqual(p['checks']['patches']['sos']['patch_apply'],'FAIL')
            self.assertEqual(p['checks']['rust_compile'],'NOT RUN')

    def test_unknown_version_still_records_review(self):
        profile={'signature':'unknown','upstream_version':'1.5.2-dev'}
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,self.env),patch.object(review.subprocess,'check_output',side_effect=['b'*40+'\n','']),patch.object(review.build_adapter,'inspect',return_value=(profile,{})):
            p=review.collect(Path(td),'b'*40,Path(td)/'out')
            self.assertIn('patchset_error',p)
            self.assertEqual(p['checks']['patches'],{})
            self.assertEqual(p['approval'],'REQUIRED / NOT APPROVED')

    def test_upstream_resolution_api_steps_receive_scoped_read_only_token(self):
        w=yaml.safe_load((review.ROOT/'.github/workflows/upstream-main-compatibility.yml').read_text())
        job=w['jobs']['resolve']
        for name in ('Resolve default branch and exact HEAD', 'Validate CI channel identity'):
            with self.subTest(step=name):
                step=next(s for s in job['steps'] if s.get('name')==name)
                self.assertEqual(step.get('env',{}).get('GH_TOKEN'),'${{ github.token }}')
        self.assertEqual(job.get('permissions',w['permissions']),{'contents':'read','actions':'read'})
        self.assertNotIn('environment',job)

    def test_workflow_separates_read_only_inspection_and_writer(self):
        w=yaml.safe_load((review.ROOT/'.github/workflows/upstream-main-compatibility.yml').read_text())
        self.assertEqual(w['permissions'],{'contents':'read','actions':'read'})
        read=w['jobs']['interface-review'];writer=w['jobs']['propose-interface-review']
        self.assertNotIn('permissions',read)
        self.assertEqual(writer['permissions'],{'contents':'write','pull-requests':'write','actions':'read'})
        self.assertIn("github.ref == 'refs/heads/main'",writer['if'])
        self.assertIn("needs.interface-review.result == 'success'",writer['if'])
        self.assertEqual(writer['needs'],'interface-review')
        self.assertNotIn('continue-on-error',json.dumps(w))
        self.assertNotIn('secrets.',json.dumps(read))
        self.assertNotIn('environment',writer)
        self.assertFalse(any('collect' in x.get('run','') or 'prepare.sh' in x.get('run','') for x in writer['steps']))


if __name__=='__main__':unittest.main()
