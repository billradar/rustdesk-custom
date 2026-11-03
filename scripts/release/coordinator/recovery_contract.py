"""Missing-run fault injection without GitHub credentials or production writes."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
import unittest

from .contract import NOW
from .model import BuildState, PolicyState, ReservationState
from .reconcile import Reconciler, WORKFLOWS
from .reconcile_contract import bound
from .recovery import automatic, recover
from .store import APIError, Conflict
from .transitions import finish, provenance, updated, bind_verified, auto_recover_missing

REPO='example/release-test'


class MissingEvidence:
    def run(self, record):raise APIError(404)


class RecoveryAPI:
    def __init__(self):self.status=404;self.rows=[];self.calls=[];self.failure=None
    def request(self, method, path):
        self.calls.append(path)
        if path==f'repos/{REPO}':return {'full_name':REPO}
        if '/actions/runs?' in path:
            if self.failure:raise self.failure
            return {'total_count':len(self.rows),'workflow_runs':self.rows}
        if self.status:raise APIError(self.status)
        return {'status':'completed'}


class RecoveryContract(unittest.TestCase):
    def setUp(self):
        _,self.journal,self.old=bound();self.now=NOW+timedelta(hours=2)
        self.snap=Reconciler(self.journal,MissingEvidence()).refresh(self.old,self.now)
        self.api=RecoveryAPI()

    def recover(self, **kw):
        args=dict(expected_sha=self.snap.sha,run_id='123',confirmation='STOPPED_AND_BUILD_STARTED',
                  actor='maintainer',reason='Reviewed stopped worker and build-entry evidence',
                  creator='456',now=self.now)
        args.update(kw)
        return recover(self.api,REPO,self.journal,**args)

    def auto(self):
        return automatic(self.api,REPO,self.journal,self.snap,'456',self.now)

    def test_automatic_missing_run_preserves_actual_count_and_records_unknown_budget(self):
        fresh=self.auto();r=fresh.record
        self.assertEqual((r.attempt,r.fence),(0,2))
        self.assertIsNone(r.started_at);self.assertIsNone(r.completed_at)
        self.assertEqual(provenance(r)['missing_run_uncertain_attempts'],1)
        history=provenance(r)['automatic_missing_run_recoveries']
        self.assertEqual((history[0]['run_id'],history[0]['compilation']),('123','UNKNOWN'))
        self.assertEqual(sum('/actions/runs/123' in p for p in self.api.calls),2)

    def test_automatic_recovery_is_limited_to_one_per_identity(self):
        fresh=self.auto();r=fresh.record
        self.snap=self.journal.append(bind_verified(r,r.reservation_id,r.fence,'124','a'*40,1,self.now),fresh)
        self.snap=Reconciler(self.journal,MissingEvidence()).refresh(self.snap,self.now)
        self.assertIsNone(self.auto())
        self.assertEqual(self.journal.load(),self.snap)

    def test_automatic_recovery_requires_repository_and_actions_access(self):
        for status in (403,429,500):
            self.api.status=status
            with self.subTest(status=status),self.assertRaises(APIError):self.auto()
        self.api.status=404;self.api.failure=APIError(403)
        with self.assertRaises(APIError):self.auto()
        self.assertEqual(self.journal.load(),self.snap)

    def test_automatic_existing_run_or_list_disagreement_is_not_recovered(self):
        self.api.status=0;self.assertIsNone(self.auto())
        self.api.status=404;self.api.rows=[{'id':123,'status':'completed'}]
        self.assertIsNone(self.auto())
        self.assertEqual(self.journal.load(),self.snap)

    def test_automatic_blocks_active_matching_or_unindexed_runs(self):
        self.api.rows=[{'id':555,'path':WORKFLOWS[self.snap.record.channel],'status':'in_progress'}]
        for indexed in (None,self.snap.record):
            with patch('scripts.release.coordinator.runtime.index_record',return_value=indexed):
                self.assertIsNone(self.auto())
        self.assertEqual(self.journal.load(),self.snap)
        other=replace(self.snap.record,build_identity='f'*64)
        with patch('scripts.release.coordinator.runtime.index_record',return_value=other):
            self.assertIsNotNone(self.auto())

    def test_automatic_recovery_checks_pages_beyond_first(self):
        original=self.api.request
        def pages(method,path):
            if '/actions/runs?' in path:
                if path.endswith('page=1'):return {'total_count':101,'workflow_runs':[{'id':i,'path':'.github/workflows/ci.yml','status':'completed'} for i in range(100)]}
                return {'total_count':101,'workflow_runs':[{'id':555,'path':WORKFLOWS[self.snap.record.channel],'status':'queued'}]}
            return original(method,path)
        with patch.object(self.api,'request',side_effect=pages),patch('scripts.release.coordinator.runtime.index_record',return_value=None):
            self.assertIsNone(self.auto())
        self.assertEqual(self.journal.load(),self.snap)

    def test_filtered_inventory_cap_or_unknown_count_cannot_authorize_recovery(self):
        original=self.api.request
        for count in (None,True,-1,1000,1001):
            def capped(method,path):
                if '/actions/runs?' in path:return {'total_count':count,'workflow_runs':[]}
                return original(method,path)
            with self.subTest(count=count),patch.object(self.api,'request',side_effect=capped):
                with self.assertRaisesRegex(ValueError,'incomplete'):self.auto()
        self.assertEqual(self.journal.load(),self.snap)

    def test_missing_run_uncertainty_counts_against_later_automatic_retry_budget(self):
        from .retry import RetryPolicy, Failure
        record=replace(self.snap.record,source_provenance=updated(self.snap.record,missing_run_uncertain_attempts=2))
        from .reconcile_contract import TOKEN2
        with self.assertRaisesRegex(ValueError,'budget'):
            auto_recover_missing(record,TOKEN2,'456',self.now,self.now+timedelta(hours=6))
        failed=replace(record,state=BuildState.FAILED,attempt=1,started_at=self.now,
            completed_at=self.now,failure_class=Failure.NETWORK.value)
        self.assertFalse(RetryPolicy().eligible(failed))

    def test_known_terminal_failure_is_never_a_404_auto_retry(self):
        from .retry import Failure
        from .reconcile_contract import TOKEN2
        for failure in (Failure.SIGNING,Failure.COMPILE,Failure.CANCELLED,Failure.SECURITY,Failure.UNKNOWN):
            r=replace(self.snap.record,state=BuildState.FAILED,completed_at=self.now,failure_class=failure.value)
            with self.subTest(failure=failure),self.assertRaises(ValueError):
                auto_recover_missing(r,TOKEN2,'456',self.now,self.now+timedelta(hours=6))

    def test_two_automatic_recoveries_only_one_epoch_wins(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier=Barrier(2);append=self.journal.append
        def contested(event,snapshot):
            barrier.wait(timeout=10)
            return append(event,snapshot)
        def attempt():
            try:return self.auto()
            except Conflict:return None
        with patch.object(self.journal,'append',side_effect=contested),ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:attempt(),range(2)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.journal.load().record.fence,2)

    def test_404_holds_without_inventing_result_or_count_and_is_idempotent(self):
        self.assertEqual(self.snap.record.state,BuildState.QUEUED)
        self.assertEqual(self.snap.record.policy_state,PolicyState.REVIEW_REQUIRED)
        self.assertEqual(self.snap.record.attempt,0)
        self.assertIsNone(self.snap.record.completed_at)
        self.assertEqual(Reconciler(self.journal,MissingEvidence()).refresh(self.snap,self.now),self.snap)

    def test_explicit_recovery_accounts_build_and_fences_old_worker(self):
        fresh=self.recover();r=fresh.record
        self.assertEqual((r.fence,r.attempt),(2,1))
        self.assertEqual(r.reservation_state,ReservationState.RESERVED)
        self.assertNotEqual(r.reservation_id,self.old.record.reservation_id)
        self.assertEqual(r.workflow_run_id,'');self.assertIsNone(r.completed_at)
        self.assertEqual(provenance(r)['missing_run_recoveries'][-1]['run_id'],'123')
        with self.assertRaises(Conflict):
            self.journal.append(finish(self.old.record,self.old.record.reservation_id,1,
                NOW+timedelta(minutes=1),self.now,True),self.old)
        with self.assertRaises(ValueError):self.recover()

    def test_stale_snapshot_run_and_missing_confirmation_never_write(self):
        for kw in ({'expected_sha':'f'*40},{'run_id':'999'},{'confirmation':''}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):self.recover(**kw)
        self.assertEqual(self.journal.load(),self.snap)

    def test_existing_run_api_denial_and_active_run_block(self):
        for status in (0,403,429,500):
            self.api.status=status
            with self.subTest(status=status),self.assertRaises((ValueError,APIError)):self.recover()
        self.api.status=404
        for status in ('queued','in_progress','waiting','pending',None):
            self.api.rows=[{'path':WORKFLOWS[self.snap.record.channel],'status':status}]
            with self.subTest(status=status),self.assertRaises(ValueError):self.recover()
        self.assertEqual(self.journal.load(),self.snap)

    def test_api_failure_and_incomplete_pagination_do_not_release(self):
        self.api.failure=APIError(503)
        with self.assertRaises(APIError):self.recover()
        self.api.failure=None
        self.api.rows=[{'path':'.github/workflows/ci.yml','status':'completed'}]*100
        with self.assertRaisesRegex(ValueError,'pagination'):self.recover()
        self.assertEqual(self.journal.load(),self.snap)

    def test_race_after_checks_is_rejected_by_cas(self):
        with patch.object(self.journal,'append',side_effect=Conflict('concurrent writer')):
            with self.assertRaises(Conflict):self.recover()
        self.assertEqual(self.journal.load(),self.snap)

    def test_attempt_budget_and_success_cannot_be_reset(self):
        from .transitions import recover_missing
        from .reconcile_contract import TOKEN2
        success=finish(self.old.record,self.old.record.reservation_id,1,
                       NOW+timedelta(minutes=1),self.now,True).after
        for r in (replace(self.snap.record,attempt=3),replace(self.snap.record,policy_state=PolicyState.READY),success):
            with self.assertRaises(ValueError):
                recover_missing(r,'maintainer','review','123',TOKEN2,'456',self.now,self.now+timedelta(hours=6))

    def test_two_recovery_operators_only_one_reservation_wins(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier=Barrier(2);append=self.journal.append
        def contested(event,snapshot):
            barrier.wait(timeout=10)
            return append(event,snapshot)
        def attempt():
            try:return self.recover()
            except Conflict:return None
        with patch.object(self.journal,'append',side_effect=contested),ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:attempt(),range(2)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.journal.load().record.fence,2)

    def test_run_disappearing_during_final_read_holds_without_completion(self):
        from .reconcile_contract import FakeEvidence
        for disappear in (2,3):
            _,journal,snapshot=bound();evidence=FakeEvidence()
            original=evidence.run;calls=[]
            def read(record):
                calls.append(record)
                if len(calls)==disappear:raise APIError(404)
                return original(record)
            evidence.run=read
            result=Reconciler(journal,evidence).refresh(snapshot,self.now)
            self.assertEqual(result.record.policy_state,PolicyState.REVIEW_REQUIRED)
            self.assertIsNone(result.record.completed_at)

    def test_transient_api_error_is_not_missing_evidence(self):
        for status in (403,429,503):
            evidence=MissingEvidence()
            evidence.run=lambda r,s=status:(_ for _ in ()).throw(APIError(s))
            with self.assertRaises(APIError):Reconciler(self.journal,evidence).refresh(self.snap,self.now)
        self.assertEqual(self.journal.load(),self.snap)


if __name__=='__main__':unittest.main()
