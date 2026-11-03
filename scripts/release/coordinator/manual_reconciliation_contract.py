"""Additional fail-closed contracts for manual historical-worker reconciliation.

Run with: python3 -m unittest scripts.release.coordinator.manual_reconciliation_contract
"""
from datetime import timedelta
import unittest

from .contract import NOW
from .model import BuildState, PolicyState
from .reconcile import Reconciler, MISSING_REASON
from .reconcile_contract import FakeEvidence, bound
from .store import APIError


class MissingRunEvidence:
    def run(self, record):
        raise APIError(404)


class MissingJobsEvidence(FakeEvidence):
    def jobs(self, record):
        raise APIError(404)


class IncompleteSuccessEvidence(FakeEvidence):
    def jobs(self, record):
        jobs = super().jobs(record)
        return [j for j in jobs if j.get('name') != 'aggregate']


class HistoricalWorkerReconciliationContract(unittest.TestCase):
    def test_missing_run_fails_closed_and_is_idempotent(self):
        _, journal, snap = bound()
        reconciler = Reconciler(journal, MissingRunEvidence())
        first = reconciler.refresh(snap, NOW + timedelta(hours=2))
        self.assertEqual(first.record.policy_state, PolicyState.REVIEW_REQUIRED)
        self.assertEqual(first.record.state, BuildState.QUEUED)
        self.assertEqual(first.record.failure_reason, MISSING_REASON)
        second = reconciler.refresh(first, NOW + timedelta(hours=3))
        self.assertEqual(second.sha, first.sha)

    def test_missing_jobs_does_not_guess_terminal_outcome(self):
        _, journal, snap = bound()
        result = Reconciler(journal, MissingJobsEvidence(conclusion='success')).refresh(
            snap, NOW + timedelta(hours=2))
        self.assertEqual(result.record.policy_state, PolicyState.REVIEW_REQUIRED)
        self.assertEqual(result.record.state, BuildState.QUEUED)
        self.assertIsNone(result.record.completed_at)

    def test_success_requires_aggregate_evidence(self):
        _, journal, snap = bound()
        result = Reconciler(journal, IncompleteSuccessEvidence(conclusion='success')).refresh(
            snap, NOW + timedelta(hours=2))
        self.assertEqual(result.record.policy_state, PolicyState.REVIEW_REQUIRED)
        self.assertNotEqual(result.record.state, BuildState.SUCCEEDED)

    def test_verified_success_is_terminal_and_repeat_safe(self):
        _, journal, snap = bound()
        reconciler = Reconciler(journal, FakeEvidence(conclusion='success'))
        done = reconciler.refresh(snap, NOW + timedelta(hours=2))
        self.assertEqual(done.record.state, BuildState.SUCCEEDED)
        self.assertEqual(done.record.attempt, 1)
        self.assertEqual(reconciler.refresh(done, NOW + timedelta(hours=3)).sha, done.sha)


if __name__ == '__main__':
    unittest.main()
