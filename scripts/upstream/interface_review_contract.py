#!/usr/bin/env python3
"""Report-only automation must never approve an interface or mutate protected code."""
import copy
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
        def api(path,method='GET',data=None,missing=False):
            calls.append((path,method,data))
            if path.startswith('pulls?'):return []
            if path=='git/ref/heads/main':return {'object':{'sha':'a'*40}}
            if path.startswith('git/ref/heads/'):return None
            if path.startswith('git/commits/') and method=='GET':return {'tree':{'sha':'d'*40}}
            if path in ['git/trees','git/commits']:return {'sha':'e'*40}
            if path=='git/refs':return {}
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

    def test_known_interface_creates_no_report(self):
        profile={'signature':'known'}
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,self.env),patch.object(review.subprocess,'check_output',side_effect=['b'*40+'\n','']),patch.object(review.build_adapter,'inspect',return_value=(profile,{})),patch.object(review.json,'loads',return_value={'profiles':[profile]}):
            out=Path(td)/'out'
            self.assertIsNone(review.collect(Path(td),'b'*40,out));self.assertFalse(out.exists())

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
