"""Manual publication boundaries, exact Draft binding and native-proof failure handling."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import yaml
from scripts.release import publish_stable as p

ROOT=Path(__file__).resolve().parents[2]
TAG='v1.5.3-custom.v3.3'
ENV=dict(GITHUB_REPOSITORY=p.REPOSITORY,GITHUB_REF='refs/heads/main',GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_ACTOR='billradar',GITHUB_ACTOR_ID=p.attestation.OWNER_ID,
         GITHUB_WORKFLOW_REF=p.REPOSITORY+'/.github/workflows/publish-stable.yml@refs/heads/main')


def fixture():
    assets=[dict(id=i,name=name,size=10,digest='sha256:'+'f'*64,state='uploaded') for i,name in enumerate(('update-manifest.json','release-attestation.json','client.deb'),1)]
    release=dict(id=7,name=TAG,tag_name=TAG,draft=True,prerelease=False,immutable=False,
                 target_commitish='a'*40,updated_at='unchanged',assets=assets)
    value=dict(upstream_version='1.5.3',patchset='v3',patch_revision='v3.3',
               common_patch_hash='c'*64,sos_patch_hash='d'*64,custom_repository_sha='a'*40,build_run='42',android_signing_enabled=False,android_production_signed=False)
    statement=dict(_type='https://in-toto.io/Statement/v1',predicateType='https://in-toto.io/attestation/release/v0.2',
        predicate=dict(databaseId='7',ownerId=p.attestation.OWNER_ID,repositoryId=p.attestation.REPOSITORY_ID,
                       packageId=p.attestation.REPOSITORY_ID,repository=p.REPOSITORY,tag=TAG,purl=f'pkg:github/{p.REPOSITORY}@{TAG}'),
        subject=[dict(uri=f'pkg:github/{p.REPOSITORY}@{TAG}',digest=dict(sha1='a'*40))]+[
            dict(name=a['name'],digest=dict(sha256=a['digest'][7:])) for a in assets])
    verified=dict(verificationResult=dict(signature=dict(certificate=dict(subjectAlternativeName='https://dotcom.releases.github.com')),statement=statement))
    return release,value,verified


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.release,self.value,self.verified=fixture();self.published=False
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)/'receipt.json'
        self.context=patch.dict(os.environ,ENV,clear=True);self.context.start();self.addCleanup(self.context.stop)
        for patcher in (patch.object(p.attestation,'read_release',side_effect=lambda *args,**kwargs:copy.deepcopy(self.value)),
                        patch('scripts.upstream.patchsets.require_selection'),
                        patch('scripts.upstream.patchset_version.current',return_value={'versioning':{'history':[dict(revision=3,after={'common':'c'*64,'sos':'d'*64})]}}),
                        patch('scripts.release.stable_tag.commit_of',return_value='a'*40),
                        patch.object(p.time,'sleep')):
            patcher.start();self.addCleanup(patcher.stop)

    def api(self,path,missing=False):
        if path.endswith('/immutable-releases'):return dict(enabled=True)
        if '/git/ref/' in path:return dict(object=dict(type='commit',sha='a'*40))
        if '/actions/runs/' in path:return dict(status='completed',conclusion='success',head_branch='main',event='workflow_dispatch',path='.github/workflows/tag.yml',head_sha='a'*40)
        if path.endswith('/releases/7'):
            return copy.deepcopy(dict(self.release,**({'draft':False,'immutable':True} if self.published else {})))
        self.fail(path)

    def write(self,method,path,payload):
        self.assertEqual((method,path),('PATCH','repos/'+p.REPOSITORY+'/releases/7'))
        self.assertEqual(payload,dict(tag_name=TAG,target_commitish='a'*40,draft=False,prerelease=False))
        self.published=True
        return self.api(path)

    def run_publish(self,**kwargs):
        command=kwargs.pop('command',lambda *a,**k:SimpleNamespace(stdout=json.dumps(self.verified)))
        with patch.object(p,'api',side_effect=kwargs.pop('api',self.api)),patch.object(p,'request',side_effect=kwargs.pop('write',self.write)) as write,patch.object(p.subprocess,'run',side_effect=command) as run:
            result=p.publish('7',TAG,'f'*64,self.output)
        return result,write,run

    def test_only_manual_main_context_and_exact_inputs(self):
        for key,value in [('GITHUB_REF','refs/heads/development'),('GITHUB_EVENT_NAME','push'),('GITHUB_WORKFLOW_REF','other/workflow'),('GITHUB_ACTOR','github-actions[bot]'),('GITHUB_ACTOR_ID','1'),('GITHUB_TRIGGERING_ACTOR','other-maintainer')]:
            with patch.dict(os.environ,{key:value}),patch.object(p,'api') as read:
                with self.assertRaises(ValueError):p.publish('7',TAG,'f'*64,self.output)
                read.assert_not_called()
        for rid,tag,digest in [('0',TAG,'f'*64),('7','nightly','f'*64),('7',TAG,'bad'),('7','v1.5.1-custom.v2.8','f'*64)]:
            with self.assertRaises(ValueError):p.identity_inputs(rid,tag,digest)

    def test_publish_once_after_proof_then_verify_native_statement(self):
        result,write,run=self.run_publish()
        self.assertEqual(result['publication'],'PUBLISHED');self.assertEqual(result['native_attestation'],'VERIFIED')
        write.assert_called_once()
        self.assertEqual(run.call_args.args[0],['gh','release','verify',TAG,'--repo',p.REPOSITORY,'--format','json'])
        self.assertEqual(json.loads(self.output.read_text())['publication'],'PUBLISHED')

    def test_rerun_only_verifies_the_same_already_immutable_release(self):
        self.published=True
        result,write,_=self.run_publish()
        self.assertEqual(result['native_attestation'],'VERIFIED');write.assert_not_called()
        self.assertIn('READ-ONLY',result['publication'])

    def test_missing_immutability_permission_or_disabled_policy_never_publishes(self):
        for error in (dict(enabled=False),PermissionError('administration read unavailable')):
            def api(path,missing=False):
                if isinstance(error,Exception):raise error
                return error
            with patch.object(p,'api',side_effect=api),patch.object(p,'request') as write:
                with self.assertRaises((ValueError,PermissionError)):p.publish('7',TAG,'f'*64,self.output)
                write.assert_not_called()

    def test_changed_or_wrong_draft_fails_before_publication(self):
        for edit in (dict(id=8),dict(prerelease=True),dict(name='foreign',tag_name='foreign'),dict(assets=[]),dict(draft=False,immutable=False)):
            self.release.update(edit)
            with patch.object(p,'api',side_effect=self.api),patch.object(p,'request') as write,patch.object(p.subprocess,'run'):
                with self.assertRaises(ValueError):p.publish('7',TAG,'f'*64,self.output)
                write.assert_not_called()
            self.release,self.value,self.verified=fixture()
        original=p.check_draft
        calls=0
        def changed(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:self.release['updated_at']='changed'
            return original(*args,**kwargs)
        with patch.object(p,'check_draft',side_effect=changed),patch.object(p,'api',side_effect=self.api),patch.object(p,'request') as write,patch.object(p.subprocess,'run'):
            with self.assertRaisesRegex(ValueError,'changed'):p.publish('7',TAG,'f'*64,self.output)
            write.assert_not_called()

    def test_invalid_proof_source_history_and_build_run_block_writes(self):
        failures=[patch.object(p.attestation,'read_release',side_effect=ValueError('bad proof')),
                  patch('scripts.upstream.patchsets.require_selection',side_effect=ValueError('candidate')),
                  patch('scripts.release.stable_tag.commit_of',return_value='b'*40),
                  patch('scripts.upstream.patchset_version.current',return_value={'versioning':{'history':[]}})]
        for failure in failures:
            with failure,patch.object(p,'api',side_effect=self.api),patch.object(p,'request') as write:
                with self.assertRaises(ValueError):p.check_draft('7',TAG,'f'*64)
                write.assert_not_called()
        api=self.api
        for key,wrong in [('conclusion','failure'),('head_branch','development'),('event','pull_request'),('path','.github/workflows/nightly.yml'),('head_sha','b'*40)]:
            def changed(path,missing=False):
                row=api(path,missing)
                if '/actions/runs/' in path:row[key]=wrong
                return row
            with patch.object(p,'api',side_effect=changed),self.assertRaises(ValueError):p.check_draft('7',TAG,'f'*64)

    def test_current_signing_policy_cannot_publish_an_old_unsigned_draft(self):
        with patch.dict(os.environ,REQUIRE_ANDROID_PRODUCTION_SIGNING='true'),patch.object(p,'api',side_effect=self.api),patch.object(p,'request') as write:
            with self.assertRaisesRegex(ValueError,'production-signed'):p.check_draft('7',TAG,'f'*64)
            write.assert_not_called()

    def test_publication_transport_error_is_unknown_and_never_retried(self):
        with patch.object(p,'api',side_effect=self.api),patch.object(p.subprocess,'run'),patch.object(p,'request',side_effect=TimeoutError('ambiguous write')) as write:
            with self.assertRaises(TimeoutError):p.publish('7',TAG,'f'*64,self.output)
            write.assert_called_once()
        self.assertTrue(json.loads(self.output.read_text())['publication'].startswith('UNKNOWN'))

    def test_native_unavailability_retries_reads_but_never_publication(self):
        def command(args,**kwargs):
            if '--help' in args:return SimpleNamespace(stdout='')
            raise subprocess.CalledProcessError(1,args)
        with patch.object(p,'api',side_effect=self.api),patch.object(p,'request',side_effect=self.write) as write,patch.object(p.subprocess,'run',side_effect=command):
            with self.assertRaisesRegex(ValueError,'already published'):p.publish('7',TAG,'f'*64,self.output)
            write.assert_called_once()
        receipt=json.loads(self.output.read_text());self.assertEqual(receipt['publication'],'PUBLISHED');self.assertEqual(receipt['native_attestation'],'FAILED AFTER PUBLICATION')

    def test_invalid_native_binding_records_the_already_published_outcome(self):
        self.verified['verificationResult']['statement']['predicate']['ownerId']='foreign'
        with patch.object(p,'api',side_effect=self.api),patch.object(p,'request',side_effect=self.write) as write,patch.object(p.subprocess,'run',return_value=SimpleNamespace(stdout=json.dumps(self.verified))):
            with self.assertRaises(ValueError):p.publish('7',TAG,'f'*64,self.output)
            write.assert_called_once()
        receipt=json.loads(self.output.read_text())
        self.assertEqual(receipt['publication'],'PUBLISHED')
        self.assertEqual(receipt['native_attestation'],'INVALID AFTER PUBLICATION')

    def test_native_binding_rejects_foreign_duplicate_missing_or_wrong_subjects(self):
        for key in self.verified['verificationResult']['statement']['predicate']:
            changed=copy.deepcopy(self.verified);changed['verificationResult']['statement']['predicate'][key]='foreign'
            with patch.object(p,'api',side_effect=self.api),self.subTest(key=key),self.assertRaises(ValueError):p.native_statement(changed,self.release,self.value,TAG)
        for transform in (lambda s:s.pop(),lambda s:s.append(copy.deepcopy(s[-1])),lambda s:s[0]['digest'].update(sha1='b'*40),lambda s:s[-1]['digest'].update(sha256='0'*64)):
            changed=copy.deepcopy(self.verified);transform(changed['verificationResult']['statement']['subject'])
            with patch.object(p,'api',side_effect=self.api),self.assertRaises(ValueError):p.native_statement(changed,self.release,self.value,TAG)

    def test_workflow_is_manual_main_only_and_build_pipelines_have_no_release_mode(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/publish-stable.yml').read_text())
        self.assertEqual(set(workflow['on']),{'workflow_dispatch'})
        job=workflow['jobs']['publish'];self.assertIn("github.ref == 'refs/heads/main'",job['if'])
        self.assertIn('github.actor == github.repository_owner',job['if'])
        verify=next(x for x in job['steps'] if 'publish_stable' in x.get('run',''))
        self.assertIn('ANDROID_PRODUCTION_SIGNING_ENABLED',verify['env']['REQUIRE_ANDROID_PRODUCTION_SIGNING'])
        self.assertFalse(any('attest-build-provenance' in x.get('uses','') for x in job['steps']))
        for file in ('tag.yml','nightly.yml'):
            w=yaml.safe_load((ROOT/'.github/workflows'/file).read_text())
            self.assertEqual(w['on']['workflow_dispatch']['inputs']['release_mode']['options'],['dry-run','draft'])
        setup=(ROOT/'.github/actions/setup-publisher-gh/action.yml').read_text()
        self.assertIn('sha256sum --check --status',setup)
        self.assertIn('4c806978ffce1cec70853302a56d70ac6da4f19bae7adca4e1a8ab00633dd91d',setup)

if __name__=='__main__':unittest.main()
