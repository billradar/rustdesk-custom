"""Offline retry-state contracts for Stable and Nightly routers."""
import unittest
from datetime import datetime, timezone, timedelta
from scripts.release.router_retry_policy import decide

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)

def row(conclusion='failure', hours=1, status='completed'):
    return {'status': status, 'conclusion': conclusion,
            'created_at': (NOW - timedelta(hours=hours)).isoformat()}

class RouterRetryPolicyContract(unittest.TestCase):
    def test_first_attempt(self):
        self.assertEqual(decide([], NOW), 'RETRY')

    def test_active_blocks(self):
        self.assertEqual(decide([row(status='queued')], NOW), 'ACTIVE')
        self.assertEqual(decide([row(status='in_progress')], NOW), 'ACTIVE')

    def test_success_is_terminal(self):
        self.assertEqual(decide([row('success', 20)], NOW), 'SUCCESS')

    def test_cooldown(self):
        self.assertEqual(decide([row(hours=1)], NOW), 'COOLDOWN')
        self.assertEqual(decide([row(hours=6)], NOW), 'RETRY')

    def test_exhaustion(self):
        self.assertEqual(decide([row(hours=20)] * 3, NOW), 'REVIEW')

    def test_cancelled_and_unknown_are_not_retried(self):
        for outcome in ('cancelled', 'skipped', 'action_required', None):
            with self.subTest(outcome=outcome):
                self.assertEqual(decide([row(outcome, 20)], NOW), 'REVIEW')

    def test_missing_timestamp_fails_closed(self):
        with self.assertRaises(ValueError):
            decide([{'status': 'completed', 'conclusion': 'failure'}], NOW)

if __name__ == '__main__':
    unittest.main()
