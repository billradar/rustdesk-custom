"""Fault injection for classified retry, fencing and Actions reconciliation."""
from dataclasses import replace
from datetime import timedelta
import json
import unittest

from .contract import NOW, TOKEN, discovered
from .model import BuildState, PolicyState, ReservationState, dispatch_unknown, reserve
from .reconcile import ActionsEvidence, Reconciler
from .retry import Failure, RetryPolicy
from .store import Conflict
from .store_contract import MemoryAPI, store
from .transitions import (bind_verified, finish, grant_retry, provenance, reserve_retry,
                          retry_schedule)

TOKEN2 = '22222222-2222-4222-8222-222222222222'


def bound():
    api = MemoryAPI()
    journal = store(api)
    snap = journal.append(reserve(discovered(), TOKEN, NOW, NOW + timedelta(hours=1)))
    snap = journal.append(bind_verified(snap.record, TOKEN, 1, '123', 'a'*40, 1, NOW), snap)
    return api, journal, snap


def failed(journal, snap, *, started=True, category=Failure.SHUTDOWN, completed=None):
    return journal.append(finish(snap.record, snap.record.reservation_id, snap.record.fence,
        NOW + timedelta(minutes=1) if started else None, completed or NOW + timedelta(minutes=5),
        False, category.value, 'build', 'verified fixture failure'), snap)


class FakeEvidence:
    def __init__(self, status='completed', conclusion='failure', *, started=True, signing=False):
        self.status, self.conclusion = status, conclusion
        self.started, self.signing = started, signing
        self.calls = 0

    def run(self, record):
        self.calls += 1
        return dict(status=self.status, conclusion=self.conclusion)

    def jobs(self, record):
        rows = [dict(id=1, name='platforms-build / linux-x86_64-standard',
                     status=self.status, conclusion=self.conclusion,
                     completed_at=(NOW + timedelta(minutes=5)).isoformat().replace('+00:00', 'Z'),
                     steps=[dict(name='Official-compatible compile, package and independent gates',
                                 status='completed', started_at=(NOW + timedelta(minutes=1)).isoformat().replace('+00:00', 'Z'))] if self.started else [])]
        if self.conclusion == 'success':
            rows.append(dict(id=2, name='aggregate', status='completed', conclusion='success',
                             completed_at=(NOW + timedelta(minutes=6)).isoformat().replace('+00:00', 'Z')))
        return rows

    def failure(self, run, jobs):
        if self.conclusion == 'cancelled':
            return Failure.CANCELLED, 'workflow', 'cancelled fixture'
        return (Failure.SIGNING if self.signing else Failure.SHUTDOWN), 'build', 'verified fixture'


class RetryReconcileContract(unittest.TestCase):
    def test_failure_classes_are_conservative(self):
        _, journal, snap = bound()
        for category in Failure:
            record = replace(
                snap.record, state=BuildState.FAILED, completed_at=NOW, failure_class=category.value,
                failure_stage='fixture', failure_reason='fixture')
            expected = category in {Failure.NETWORK, Failure.API_5XX, Failure.RUNNER, Failure.SHUTDOWN, Failure.SDK}
            self.assertEqual(RetryPolicy().eligible(record), expected)

    def test_cooldown_uses_actual_completion_and_bounded_jitter(self):
        _, journal, snap = bound()
        complete = NOW + timedelta(hours=20)
        snap = failed(journal, snap, completed=complete)
        policy = RetryPolicy()
        self.assertEqual(policy.next_retry(snap.record, 0), complete + timedelta(hours=6))
        self.assertEqual(policy.next_retry(snap.record, 1), complete + timedelta(hours=7, minutes=30))
        snap = journal.append(retry_schedule(snap.record, complete, policy.next_retry(snap.record, 0)), snap)
        for _ in range(10):
            with self.assertRaises(ValueError):
                reserve_retry(snap.record, TOKEN2, complete, complete + timedelta(hours=6))
        self.assertEqual(snap.record.attempt, 1)
        with self.assertRaises(ValueError):
            retry_schedule(snap.record, complete, complete + timedelta(days=1))

    def test_retry_budget_three_real_attempts_and_monotonic_fences(self):
        _, journal, snap = bound()
        now = NOW
        for attempt in range(1, 4):
            start = now + timedelta(minutes=1)
            end = now + timedelta(minutes=5)
            r = snap.record
            snap = journal.append(finish(r, r.reservation_id, r.fence, start, end, False,
                                         Failure.SHUTDOWN.value, 'build', 'fixture'), snap)
            self.assertEqual(snap.record.attempt, attempt)
            deadline = RetryPolicy().next_retry(snap.record, 0)
            snap = journal.append(retry_schedule(snap.record, end, deadline), snap)
            if attempt == 3:
                self.assertEqual(snap.record.policy_state, PolicyState.REVIEW_REQUIRED)
                self.assertIsNone(deadline)
                break
            now = deadline
            token = f'{attempt+1:08d}-2222-4222-8222-222222222222'
            snap = journal.append(reserve_retry(snap.record, token, now, now+timedelta(hours=6)), snap)
            snap = journal.append(bind_verified(snap.record, token, attempt+1, str(123+attempt),
                                               'a'*40, 1, now), snap)

    def test_prebuild_failures_have_separate_finite_reservation_budget(self):
        record = replace(discovered(), fence=0)
        api = MemoryAPI()
        journal = store(api)
        now = NOW
        snap = journal.append(reserve(record, TOKEN, now, now + timedelta(hours=1)))
        for epoch in range(1, 7):
            r = snap.record
            snap = journal.append(bind_verified(r, r.reservation_id, r.fence, str(epoch), 'a'*40, 1, now), snap)
            r = snap.record
            end = now + timedelta(minutes=1)
            snap = journal.append(finish(r, r.reservation_id, r.fence, None, end, False,
                                         Failure.SDK.value, 'sdk', 'verified SDK installer failure'), snap)
            self.assertEqual(snap.record.attempt, 0)
            deadline = RetryPolicy().next_retry(snap.record, 0)
            snap = journal.append(retry_schedule(snap.record, end, deadline), snap)
            if epoch == 6:
                self.assertEqual(snap.record.policy_state, PolicyState.REVIEW_REQUIRED)
                break
            now = deadline
            token = f'{epoch+1:08d}-2222-4222-8222-222222222222'
            snap = journal.append(reserve_retry(snap.record, token, now, now+timedelta(hours=6)), snap)

    def test_active_actions_run_survives_expired_lease(self):
        _, journal, snap = bound()
        snap = Reconciler(journal, FakeEvidence(status='in_progress')).refresh(snap, NOW+timedelta(hours=2))
        self.assertEqual(snap.record.workflow_run_id, '123')
        self.assertEqual(snap.record.fence, 1)
        self.assertEqual(snap.record.attempt, 1)
        self.assertGreater(snap.record.lease_expires_at, NOW+timedelta(hours=2))

    def test_dispatch_timeout_never_steals_or_consumes_attempt(self):
        api = MemoryAPI()
        journal = store(api)
        snap = journal.append(reserve(discovered(), TOKEN, NOW, NOW+timedelta(hours=1)))
        snap = journal.append(dispatch_unknown(snap.record, TOKEN, 1, NOW), snap)
        evidence = FakeEvidence()
        result = Reconciler(journal, evidence).refresh(snap, NOW+timedelta(days=1))
        self.assertEqual(result, snap)
        self.assertEqual(evidence.calls, 0)
        self.assertEqual(result.record.attempt, 0)
        # A late verified run may recover the same epoch, without a replacement.
        snap = journal.append(bind_verified(snap.record, TOKEN, 1, '123', 'a'*40, 1,
                                           NOW+timedelta(days=1)), snap)
        self.assertEqual(snap.record.fence, 1)

    def test_cancelled_and_signing_failures_require_review(self):
        for evidence in (FakeEvidence(conclusion='cancelled'), FakeEvidence(signing=True)):
            _, journal, snap = bound()
            result = Reconciler(journal, evidence).refresh(snap, NOW+timedelta(hours=1), sample=0)
            self.assertEqual(result.record.policy_state, PolicyState.REVIEW_REQUIRED)
            self.assertIsNone(result.record.next_retry_at)

    def test_success_is_terminal_and_idempotent(self):
        _, journal, snap = bound()
        evidence = FakeEvidence(conclusion='success')
        reconciler = Reconciler(journal, evidence)
        result = reconciler.refresh(snap, NOW+timedelta(hours=1))
        self.assertEqual(result.record.state, BuildState.SUCCEEDED)
        calls = evidence.calls
        self.assertEqual(reconciler.refresh(result, NOW+timedelta(days=1)), result)
        self.assertEqual(evidence.calls, calls)

    def test_manual_grant_is_one_audited_reservation_not_a_gate_bypass(self):
        _, journal, snap = bound()
        snap = failed(journal, snap, category=Failure.COMPILE)
        now = NOW+timedelta(hours=1)
        snap = journal.append(grant_retry(snap.record, 'maintainer', 'Reviewed compiler fix', now), snap)
        self.assertEqual(provenance(snap.record)['manual_grant']['next_fence'], 2)
        snap = journal.append(reserve_retry(snap.record, TOKEN2, now, now+timedelta(hours=6)), snap)
        self.assertNotIn('manual_grant', provenance(snap.record))
        self.assertEqual(snap.record.attempt, 1)
        self.assertEqual(snap.record.fence, 2)

    def test_old_worker_cannot_complete_after_new_reservation(self):
        _, journal, old = bound()
        failed_snap = failed(journal, old)
        now = NOW+timedelta(hours=1)
        granted = journal.append(grant_retry(failed_snap.record, 'maintainer', 'Reviewed retry', now), failed_snap)
        fresh = journal.append(reserve_retry(granted.record, TOKEN2, now, now+timedelta(hours=6)), granted)
        with self.assertRaises(Conflict):
            journal.append(finish(old.record, TOKEN, 1, NOW+timedelta(minutes=1),
                                  NOW+timedelta(minutes=5), True), old)
        self.assertEqual(journal.load(), fresh)

    def test_native_rerun_or_wrong_run_provenance_is_rejected(self):
        _, _, snap = bound()
        worker = provenance(snap.record)['worker']
        good = dict(id=123, repository={'full_name':'example/release-test'},
                    head_repository={'full_name':'example/release-test'}, head_branch='main',
                    event='workflow_dispatch', path='.github/workflows/tag.yml', head_sha='a'*40,
                    run_attempt=1, status='completed')
        class API:
            data = good
            def request(self, *args): return self.data
        api = API()
        evidence = ActionsEvidence(api, 'example/release-test')
        self.assertEqual(evidence.run(snap.record), good)
        for changes in (dict(run_attempt=2), dict(head_sha='b'*40), dict(head_branch='other'),
                        dict(path='.github/workflows/ci.yml')):
            api.data = dict(good, **changes)
            with self.assertRaises(ValueError): evidence.run(snap.record)
        with self.assertRaises(ValueError):
            bind_verified(replace(snap.record, state=BuildState.DISCOVERED,
                reservation_state=ReservationState.RESERVED, workflow_run_id=''), TOKEN, 1, '123', 'a'*40, 2, NOW)

    def test_unknown_logs_never_imply_infrastructure(self):
        evidence = ActionsEvidence(None, 'example/release-test', logs=lambda _: 'error: compiler failed')
        jobs = [dict(id=1, name='platforms-build / linux-x86_64-standard', conclusion='failure', steps=[{}])]
        self.assertEqual(evidence.failure({'conclusion':'failure'}, jobs)[0], Failure.UNKNOWN)
        jobs.append(dict(id=2, name='android-sign', conclusion='failure'))
        # Every failure must be transient; a generic build error alone blocks retry.
        self.assertNotIn(evidence.failure({'conclusion':'failure'}, jobs)[0], (Failure.SDK, Failure.SHUTDOWN))
        with self.assertRaises(ValueError): RetryPolicy(max_attempts=0)


if __name__ == '__main__':
    unittest.main()
