"""Missing-run fault injection without GitHub credentials or production writes."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
import unittest

from .contract import NOW
from .model import BuildState, PolicyState, ReservationState
from .reconcile import Reconciler, WORKFLOWS
from .reconcile_contract import bound
from .recovery import recover
from .store import APIError, Conflict
from .transitions import finish, provenance

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
            return {'workflow_runs':self.rows}
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
