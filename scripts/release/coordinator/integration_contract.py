"""No credentials: safety allowlist and the exact live test harness itself."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

from .integration import BRANCH, WORKFLOW, REPOSITORY, IsolatedAPI, exercise, trusted_context
from .store import APIError
from .store_contract import MemoryAPI

ROOT=Path(__file__).resolve().parents[3]


class IntegrationContract(unittest.TestCase):
    def test_complete_harness_uses_unmodified_store_and_atomic_transport(self):
        api=IsolatedAPI(MemoryAPI(),'example/test')
        result=exercise(api,'example/test','offline')
        self.assertEqual(result['result'],'PASS')
        self.assertEqual(len(result['checks']),7)
        self.assertEqual(len(result['refs']),3)
        self.assertTrue(all('/coordinator-integration/v1/' in r for r in result['refs']))
        self.assertGreater(result['api_calls'],100)

    def test_transport_rejects_production_tag_release_dispatch_delete_and_force(self):
        raw=MemoryAPI();api=IsolatedAPI(raw,'example/test')
        key='heads/coordinator-integration/v1/stable/'+'a'*64
        api.register(key);api.commits.add('b'*40)
        base='repos/example/test/'
        cases=[('POST',base+'actions/workflows/nightly.yml/dispatches',{'ref':'main'}),
               ('POST',base+'releases',{}),
               ('POST',base+'git/refs',{'ref':'refs/heads/main','sha':'b'*40}),
               ('POST',base+'git/refs',{'ref':'refs/tags/fixture','sha':'b'*40}),
               ('POST',base+'git/refs',{'ref':'refs/heads/release-coordinator/v1/stable/'+'a'*64,'sha':'b'*40}),
               ('PATCH',base+'git/refs/'+key,{'sha':'b'*40,'force':True}),
               ('DELETE',base+'git/refs/'+key,None),
               ('POST','repos/other/repo/git/refs',{'ref':'refs/'+key,'sha':'b'*40}),
               ('POST',base+'git/trees',{'tree':[{'path':'.github/workflows/evil.yml','content':'bad'}]}),
               ('POST',base+'git/commits',{'message':'bad','tree':'a'*40,'parents':['b'*40]}),
               ('POST',base+'git/commits',{'message':'coordinator: reserve','tree':'a'*40,'parents':[], 'author':{},'committer':{}}),
               ('POST',base+'git/trees',{'tree':[{'path':p,'mode':'100644','type':'blob','sha':'b'*40} for p in ('state.json','event.json')]})]
        for method,path,data in cases:
            with self.subTest(path=path),self.assertRaises(ValueError):api.request(method,path,data)
        self.assertEqual(raw.objects,{})
        self.assertEqual(raw.refs,{})
        self.assertEqual(api.calls,1) # Only the absent-ref preflight reached transport.

    def test_existing_test_ref_is_never_adopted(self):
        raw=MemoryAPI();ref='heads/coordinator-integration/v1/stable/'+'a'*64
        raw.refs['refs/'+ref]='b'*40
        with self.assertRaises(ValueError):IsolatedAPI(raw,'example/test').register(ref)
        self.assertEqual(raw.refs,{'refs/'+ref:'b'*40})
        self.assertEqual(raw.objects,{})

    def test_manual_and_pull_request_trust_boundaries(self):
        base=dict(GITHUB_REPOSITORY=REPOSITORY,COORDINATOR_INTEGRATION_ALLOW_WRITE='true',GITHUB_RUN_ID='123',
                  GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_REF='refs/heads/main',
                  GITHUB_WORKFLOW_REF=REPOSITORY+'/'+WORKFLOW+'@refs/heads/main')
        with patch.dict(os.environ,base,clear=True):
            self.assertEqual(trusted_context(),REPOSITORY)
            for changes in ({'GITHUB_REF':'refs/heads/development'},{'GITHUB_EVENT_NAME':'pull_request_target'},
                            {'COORDINATOR_INTEGRATION_ALLOW_WRITE':'false'},{'GITHUB_REPOSITORY':'fork/repo'}):
                with patch.dict(os.environ,changes),self.assertRaises(ValueError):trusted_context()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'event.json'
            event=dict(number=173,pull_request=dict(head=dict(ref=BRANCH,repo={'full_name':REPOSITORY}),
                                                   base=dict(repo={'full_name':REPOSITORY})))
            path.write_text(json.dumps(event))
            e=dict(base,GITHUB_EVENT_NAME='pull_request',GITHUB_REF='refs/pull/173/merge',GITHUB_HEAD_REF=BRANCH,
                   GITHUB_WORKFLOW_REF=REPOSITORY+'/'+WORKFLOW+'@refs/pull/173/merge',GITHUB_EVENT_PATH=str(path))
            with patch.dict(os.environ,e,clear=True):
                self.assertEqual(trusted_context(),REPOSITORY)
                event['pull_request']['head']['repo']['full_name']='fork/repo';path.write_text(json.dumps(event))
                with self.assertRaises(ValueError):trusted_context()

    def test_workflow_writer_has_no_signing_environment_or_dispatch_permission(self):
        w=yaml.safe_load((ROOT/WORKFLOW).read_text())
        self.assertEqual(set(w['on']),{'pull_request','workflow_dispatch'})
        self.assertEqual(w['permissions'],{'contents':'read'})
        self.assertEqual(set(w['jobs']),{'isolated-state-writer'})
        job=w['jobs']['isolated-state-writer']
        self.assertEqual(job['permissions'],{'contents':'write'})
        self.assertEqual(job['runs-on'],'ubuntu-22.04')
        self.assertIn(BRANCH,job['if']);self.assertIn('head.repo.full_name == github.repository',job['if'])
        for text in ('secrets.','environment:','actions: write','pull_request_target','release-coordinator/v1/'):
            self.assertNotIn(text,(ROOT/WORKFLOW).read_text())
        checkout=job['steps'][0]
        self.assertIs(checkout['with']['persist-credentials'],False)
        self.assertNotIn('env',job)
        writer=next(s for s in job['steps'] if s.get('run'))
        self.assertEqual(writer['run'],'python3 -m scripts.release.coordinator.integration')
        self.assertEqual(set(writer['env']),{'GH_TOKEN','COORDINATOR_INTEGRATION_ALLOW_WRITE'})


if __name__=='__main__':unittest.main()
