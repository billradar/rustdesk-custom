"""Credential-free legacy import, evidence drift and admission safety contracts."""
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .contract import NOW
from .identity import BuildIdentity, SourceIdentity, canonical
from .legacy import (AUDIT, AUDIT_SHA256, CATALOG, REPOSITORY, Catalog, document,
                     fingerprint, identity, load, source_hint)
from .legacy_import import ReadOnlyAPI, observe, prepare, resume, summary
from .runtime import Coordinator, nightly_history, stable_history
from .runtime_contract import RuntimeAPI
from .store import APIError


def api_run(record):
    value = copy.deepcopy(record['observation']['run'])
    for key in ('repository','head_repository'):
        value[key] = {'full_name':value[key]}
    return value


class LegacyContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load()
        cls.records = list(cls.catalog.records.values())
        cls.success = next(r for r in cls.records if r['audit_row']['run_id'] == 41422335564)
        cls.stable = next(r for r in cls.records if r['audit_row']['run_id'] == 41398573672)

    def test_actual_archived_inventory_and_zero_build_accounting(self):
        result = summary(self.records)
        self.assertEqual((result['records'],result['success_holds'],result['review_holds']), (25,7,18))
        self.assertEqual((result['no_build_rows'],result['actual_compile_attempts'],result['missing_source_holds']), (3,31,3))
        self.assertEqual(sum(len(r['observation']['attempts']) for r in self.records),34)
        self.assertEqual(sum(a['job_count'] for r in self.records for a in r['observation']['attempts']),951)
        self.assertFalse(result['production_state_written']);self.assertFalse(result['automatic_retry_authorized'])
        self.assertEqual(hashlib.sha256(AUDIT.read_bytes()).hexdigest(),AUDIT_SHA256)

    def test_parallel_duplicate_routers_skip_success_without_api_or_artifacts(self):
        for record in (self.success,self.stable):
            api=RuntimeAPI();build=identity(record['audit_row'])
            c=Coordinator(api,REPOSITORY,build,legacy_catalog=self.catalog)
            with ThreadPoolExecutor(max_workers=8) as workers:
                results=list(workers.map(lambda _:c.claim(NOW,'123',lambda:self.fail('Artifact recovery called')),range(16)))
            self.assertEqual(results,[None]*16)
            self.assertEqual(api.refs,{});self.assertEqual(api.objects,{});self.assertEqual(api.dispatches,[])

    def test_unknown_and_missing_source_hold_never_bootstrap_or_count_attempts(self):
        record=next(r for r in self.records if identity(r['audit_row']) is None and not source_hint(r['audit_row']))
        build=replace(identity(self.success['audit_row']),channel=record['audit_row']['channel'])
        catalog=Catalog([record]);api=RuntimeAPI();c=Coordinator(api,REPOSITORY,build,legacy_catalog=catalog)
        for _ in range(4):
            with self.assertRaisesRegex(ValueError,'requires review'):c.claim(NOW,'123',lambda:'EMPTY')
        self.assertEqual(api.refs,{});self.assertEqual(api.objects,{});self.assertEqual(api.dispatches,[])

    def test_no_build_reuse_is_not_a_successful_producer_or_attempt(self):
        record=next(r for r in self.records if r['audit_row']['run_id']==40647868248)
        row=record['audit_row'];options=row['options']
        build=BuildIdentity('stable',SourceIdentity(**row['source_identity']),options['wayland_included'],
                            options['wayland_policy_sha256'],options['android_signing_enabled'],options['release_mode'])
        self.assertIsNone(identity(row));self.assertEqual(row['observed_compile_attempts'],[])
        self.assertEqual(Catalog([record]).decision(build),'REVIEW_HOLD')
        with self.assertRaisesRegex(ValueError,'producer requires review'):
            Catalog([record]).historical_identity(api_run(record),'stable')

    def test_custom_sha_and_official_run_provenance_do_not_change_build_key(self):
        build=identity(self.success['audit_row'])
        self.assertEqual(self.catalog.decision(build),'SUCCESS_HOLD')
        stable=identity(self.stable['audit_row'])
        self.assertEqual(self.catalog.decision(replace(stable,release_mode='release')),'SUCCESS_HOLD')
        self.assertNotEqual(build.key,replace(build,release_mode='release').key)
        self.assertEqual(Catalog([self.success]).decision(replace(build,release_mode='release')),'NO_OP')

    def test_successful_native_attempt_retains_historical_attempts_without_fake_worker(self):
        record=next(r for r in self.records if r['audit_row']['run_id']==41292973439)
        self.assertEqual(record['audit_row']['observed_compile_attempts'],[1,2])
        api=RuntimeAPI();c=Coordinator(api,REPOSITORY,identity(record['audit_row']),legacy_catalog=self.catalog)
        self.assertIsNone(c.claim(NOW,'123',lambda:'EMPTY'));self.assertEqual(api.refs,{})
        self.assertNotIn('reservation_id',record);self.assertNotIn('fence',record)

    def test_nightly_archive_survives_artifact_expiry_and_missing_official_run(self):
        record=next(r for r in self.records if r['audit_row']['run_id']==41292973439)
        before=document(record['audit_row']);run=api_run(record);build=identity(record['audit_row'])
        with patch('scripts.release.coordinator.runtime.history',return_value=[run]), \
             patch('scripts.release.coordinator.legacy.for_repository',return_value=Catalog([record])), \
             patch('scripts.release.nightly.source_sha_from_run',side_effect=AssertionError('Official run unavailable')), \
             patch('scripts.release.nightly.discovery_from_run',side_effect=AssertionError('Artifact expired')):
            self.assertEqual(nightly_history(RuntimeAPI(),REPOSITORY,build),'SUCCESS')
        self.assertEqual(before['official_run_id'],'41280309181')
        self.assertEqual(record['audit_row']['verified_official_source_evidence']['id'],41366206478)
        self.assertEqual(document(record['audit_row']),before)

    def test_stable_archive_does_not_download_expired_lock(self):
        row=api_run(self.stable);build=identity(self.stable['audit_row'])
        with patch('scripts.release.coordinator.runtime.history',return_value=[row]), \
             patch('scripts.release.coordinator.legacy.for_repository',return_value=Catalog([self.stable])), \
             patch('scripts.release.stable_router.recorded_identity',side_effect=AssertionError('Artifact expired')):
            self.assertEqual(stable_history(RuntimeAPI(),REPOSITORY,build),'SUCCESS')

    def test_unrelated_stable_review_evidence_does_not_block_a_new_source(self):
        record=next(r for r in self.records if r['audit_row']['run_id']==40647868248)
        catalog=Catalog([record]);row=api_run(record)
        build=identity(self.stable['audit_row'])
        build=replace(build,source=replace(build.source,common_patch_hash='a'*64))
        self.assertEqual(catalog.decision(build),'NO_OP')
        with patch('scripts.release.coordinator.runtime.history',return_value=[row]), \
             patch('scripts.release.coordinator.legacy.for_repository',return_value=catalog), \
             patch('scripts.release.stable_router.recorded_identity',side_effect=AssertionError('Unrelated archive must not download')):
            self.assertEqual(stable_history(RuntimeAPI(),REPOSITORY,build),'EMPTY')
            c=Coordinator(RuntimeAPI(),REPOSITORY,build,legacy_catalog=catalog)
            snapshot=c.claim(NOW,'123',lambda:stable_history(c.api,REPOSITORY,build))
            self.assertEqual(snapshot.record.attempt,0)
        same=replace(build,source=replace(build.source,upstream_sha=source_hint(record['audit_row'])))
        self.assertEqual(catalog.decision(same),'REVIEW_HOLD')
        with self.assertRaisesRegex(ValueError,'requires review'):
            Coordinator(RuntimeAPI(),REPOSITORY,same,legacy_catalog=catalog).claim(NOW,'123',lambda:'EMPTY')
        row['run_attempt']+=1
        with self.assertRaisesRegex(ValueError,'drift'):catalog.unrelated_source(row,'stable',build.source.upstream_sha)

    def test_run_attempt_repository_source_event_and_path_drift_fail_closed(self):
        for change in (dict(run_attempt=2),dict(head_sha='a'*40),dict(status='in_progress'),
                       dict(conclusion='failure'),dict(event='pull_request'),dict(path='.github/workflows/ci.yml'),
                       dict(repository={'full_name':'foreign/repo'}),dict(display_title='edited')):
            row=api_run(self.success);row.update(change)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'drift'):
                self.catalog.annotate_nightly(row)

    def test_mutable_caller_data_cannot_rewrite_validated_archive(self):
        record=copy.deepcopy(self.success);catalog=Catalog([record])
        build=identity(record['audit_row'])
        record['audit_row']['coordinator_build_identity']='a'*64
        exposed=catalog.records
        exposed[('nightly',41422335564)]['audit_row']['disposition']='REVIEW_REQUIRED'
        self.assertEqual(catalog.decision(build),'SUCCESS_HOLD')
        self.assertEqual(catalog.blockers(build),[41422335564])

    def test_runtime_does_not_depend_on_docs_only_audit_file(self):
        with patch('scripts.release.coordinator.legacy.AUDIT',Path('/missing/offline-audit.json')):
            catalog=load()
            build=identity(self.success['audit_row'])
            self.assertEqual(catalog.decision(build),'SUCCESS_HOLD')
            api=RuntimeAPI()
            self.assertIsNone(Coordinator(api,REPOSITORY,build).claim(NOW,'123',lambda:self.fail('Artifact lookup')))
            self.assertEqual(api.refs,{})

    def test_partial_identity_only_produces_scoped_or_channel_review(self):
        record=next(r for r in self.records if identity(r['audit_row']) is None and source_hint(r['audit_row']))
        build=identity(self.success['audit_row']);build=replace(build,channel=record['audit_row']['channel'],
                source=replace(build.source,upstream_sha=source_hint(record['audit_row'])))
        catalog=Catalog([record]);self.assertEqual(catalog.decision(build),'REVIEW_HOLD')
        self.assertEqual(catalog.decision(replace(build,source=replace(build.source,upstream_sha='a'*40))),'NO_OP')
        self.assertNotEqual(catalog.decision(build),'EMPTY')

    def test_audit_row_and_document_tampering_cannot_be_resealed_as_new_evidence(self):
        for key,value in (('coordinator_build_identity','a'*64),('disposition','REVIEW_REQUIRED'),('latest_attempt',9)):
            record=copy.deepcopy(self.success);record['audit_row'][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'exact reviewed audit row'):Catalog([record])
        row=copy.deepcopy(self.success['audit_row']);row['artifact_evidence'][0]['archived_document_utf8']+=' '
        with self.assertRaisesRegex(ValueError,'JSON digest mismatch'):document(row)

    def test_import_idempotency_append_only_chain_and_rollback_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'catalog';first=prepare([self.success],root)
            self.assertEqual(first,prepare([self.success],root))
            second=prepare([self.success,self.stable],root)
            self.assertNotEqual(first,second);self.assertEqual(len(load(root).records),2)
            with self.assertRaisesRegex(ValueError,'delete or replace'):prepare([self.success],root)
            (root/'head.json').write_bytes(canonical(dict(schema_version=1,catalog_sha256=first)))
            with self.assertRaisesRegex(ValueError,'rolled-back'):load(root)

    def test_two_concurrent_pr_import_forks_are_not_silently_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a';b=Path(tmp)/'b'
            prepare([self.success],a);prepare([self.success],b)
            prepare([self.success,self.stable],a)
            other=next(r for r in self.records if r not in (self.success,self.stable))
            fork=prepare([self.success,other],b)
            (a/'objects'/(fork+'.json')).write_bytes((b/'objects'/(fork+'.json')).read_bytes())
            with self.assertRaisesRegex(ValueError,'fork'):load(a)

    def test_interrupted_preparation_recovers_only_complete_valid_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'catalog';prepare([self.success],root)
            with patch.object(Path,'replace',side_effect=OSError('Injected crash')):
                with self.assertRaises(OSError):prepare([self.success,self.stable],root)
            with self.assertRaisesRegex(ValueError,'fork'):load(root)
            self.assertEqual(len(resume(root).records),2)
            self.assertFalse((root/'head.pending').exists())
            self.assertEqual(prepare([self.success,self.stable],root),json.loads((root/'head.json').read_text())['catalog_sha256'])

    def test_crash_after_intent_before_object_is_reconstructed_from_exact_input(self):
        original=Path.open
        for initial in (True,False):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)/'catalog'
                if not initial:prepare([self.success],root)
                def interrupted(path,*args,**kwargs):
                    if path.parent.name=='objects' and args and args[0]=='xb':
                        raise OSError('Injected crash before object creation')
                    return original(path,*args,**kwargs)
                with patch.object(Path,'open',interrupted):
                    with self.assertRaises(OSError):prepare([self.success,self.stable],root)
                self.assertTrue((root/'head.pending').is_file())
                with self.assertRaises(ValueError):resume(root)
                with self.assertRaisesRegex(ValueError,'differs'):
                    prepare([self.success],root)
                key=prepare([self.success,self.stable],root)
                self.assertEqual(len(load(root).records),2)
                self.assertEqual(key,prepare([self.success,self.stable],root))

    def test_missing_tampered_unknown_schema_or_noncanonical_catalog_fails_closed(self):
        for fault in ('missing','tampered','schema','noncanonical'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)/'catalog';key=prepare([self.success],root);obj=root/'objects'/(key+'.json')
                if fault=='missing':obj.unlink()
                elif fault=='tampered':obj.write_bytes(obj.read_bytes()+b' ')
                else:
                    head=json.loads((root/'head.json').read_text())
                    if fault=='schema':head['schema_version']=True
                    (root/'head.json').write_bytes(json.dumps(head).encode() if fault=='noncanonical' else canonical(head))
                with self.subTest(fault=fault),self.assertRaises(ValueError):load(root)

    def test_read_only_capture_rejects_mutation_and_foreign_resources(self):
        api=RuntimeAPI();reader=ReadOnlyAPI(api)
        for method,path,data in [('POST','repos/'+REPOSITORY+'/actions/runs/1',{}),
            ('GET','repos/foreign/repo/actions/runs/1',None),('GET','repos/'+REPOSITORY+'/git/refs',None),
            ('DELETE','repos/'+REPOSITORY+'/releases/1',None)]:
            with self.subTest(method=method),self.assertRaises(ValueError):reader.request(method,path,data)
        self.assertEqual(api.refs,{});self.assertEqual(api.dispatches,[])

    def test_observer_detects_run_changes_pagination_duplicates_and_api_errors(self):
        record=self.success;row=record['audit_row'];run=api_run(record)
        class API:
            calls=0
            fault=''
            def request(self,method,path,data=None):
                if '/jobs?' in path:
                    if self.fault=='503':raise APIError(503)
                    j=dict(id=1,run_id=row['run_id'],run_attempt=1,status='completed',steps=[])
                    return dict(total_count=2,jobs=[j,j] if self.fault=='duplicates' else [j])
                self.calls+=1
                return dict(run,run_attempt=2) if self.calls>1 else run
        for fault in ('503','duplicates','missing'):
            api=API();api.fault=fault
            with self.subTest(fault=fault),self.assertRaises((ValueError,APIError)):observe(api,row)
        class Drift(API):
            def request(self,method,path,data=None):
                if '/jobs?' in path:return dict(total_count=1,jobs=[dict(id=1,run_id=row['run_id'],run_attempt=1,status='completed',steps=[])])
                return super().request(method,path,data)
        with self.assertRaisesRegex(ValueError,'changed during capture'):observe(Drift(),row)

    def test_sparse_worker_guard_does_not_load_catalog_or_expand_permissions(self):
        from .runtime import guard
        from .runtime_contract import REPO,run
        from .contract import identity as fixture_identity
        import os
        api=RuntimeAPI();c=Coordinator(api,REPO,fixture_identity('nightly'))
        snapshot=c.claim(NOW,'123',lambda:'EMPTY');self.assertTrue(c.admit(snapshot,run(),NOW))
        env=dict(GITHUB_REPOSITORY=REPO,GITHUB_REF='refs/heads/main',GITHUB_EVENT_NAME='workflow_dispatch',
            GITHUB_WORKFLOW_REF=REPO+'/.github/workflows/nightly.yml@refs/heads/main',GITHUB_SHA='a'*40,
            GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='1',UPSTREAM_EXPECTED_SHA='a'*40)
        with patch('scripts.release.coordinator.runtime.GitHubAPI',return_value=api), \
             patch('scripts.release.coordinator.legacy.for_repository',side_effect=AssertionError('Sparse guard must not load archive')), \
             patch.dict(os.environ,env,clear=True):guard()


if __name__ == '__main__':
    unittest.main()
