"""Credential-free compatibility and fail-closed state contracts."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from scripts.release import channel, nightly
from .identity import BuildIdentity, RunProvenance, SourceIdentity, canonical, digest
from .model import (BuildState, PolicyState, Record, ReservationState,
                    advance, bind, dispatch_unknown, reserve)
from .decision import Decision, decide

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)
TOKEN = '11111111-1111-4111-8111-111111111111'
SOURCE = SourceIdentity('a'*40, 'v2', 'b'*64, 'c'*64)


def identity(name='stable', **kwargs):
    return BuildIdentity(name, SOURCE, True, 'd'*64, False, **kwargs)


def discovered():
    return Record('stable', identity().key, SOURCE.upstream_sha, NOW, '{}')


def reserved():
    return reserve(discovered(), TOKEN, NOW, NOW + timedelta(hours=1)).after


def queued():
    return bind(reserved(), TOKEN, 1, '123', NOW).after


class IdentityContract(unittest.TestCase):
    def test_canonical_encoding_and_types(self):
        self.assertEqual(canonical({'z': 1, 'a': ['é', True, None]}),
                         b'{"a":["\\u00e9",true,null],"z":1}')
        self.assertEqual(digest({'a': 1, 'b': 2}), digest({'b': 2, 'a': 1}))
        for value in (float('nan'), 1.0, {1: 'key'}, ('tuple',)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical(value)

    def test_stable_compatibility_all_selections(self):
        for included in (False, True):
            for signing in (False, True):
                policy = 'd'*64 if included else ''
                build = BuildIdentity('stable', SOURCE, included, policy, signing)
                old = channel.build_identity(SOURCE.upstream_sha, SOURCE.patchset,
                    SOURCE.common_patch_hash, SOURCE.sos_patch_hash, 'e'*40,
                    included, policy, signing)
                self.assertEqual(build.historical_digest, old)
                self.assertEqual(build.verify_historical(old), build.key)
                self.assertEqual(build.key, replace(build, release_mode='release').key)

    def test_nightly_compatibility_all_selections(self):
        from dataclasses import asdict
        for mode in ('dry-run', 'draft', 'release'):
            for included in (False, True):
                for signing in (False, True):
                    policy = 'd'*64 if included else ''
                    build = BuildIdentity('nightly', SOURCE, included, policy, signing, mode)
                    data = dict(asdict(SOURCE), wayland_policy_sha256=policy)
                    self.assertEqual(build.historical_digest,
                        nightly.nightly_identity(data, mode, str(included).lower(), str(signing).lower()))

    def test_identity_conflicts_and_provenance(self):
        build = identity()
        for changed in (replace(build, channel='nightly'),
                        replace(build, source=replace(SOURCE, upstream_sha='e'*40)),
                        replace(build, source=replace(SOURCE, common_patch_hash='e'*64)),
                        replace(build, source=replace(SOURCE, sos_patch_hash='e'*64)),
                        replace(build, source=replace(SOURCE, patchset='v1')),
                        replace(build, wayland_policy_sha256='e'*64),
                        replace(build, wayland_included=False, wayland_policy_sha256=''),
                        replace(build, android_signing_enabled=True)):
            self.assertNotEqual(build.key, changed.key)
        self.assertNotEqual(identity('nightly').key,
                            identity('nightly', release_mode='release').key)
        # Changing provenance has no channel identity input.
        a = RunProvenance('e'*40, '123', '456')
        b = RunProvenance('f'*40, '789', '987')
        self.assertNotEqual(a, b)
        self.assertEqual(build.key, identity().key)

    def test_unknown_migration_is_not_a_cache_miss(self):
        for value in ('', 'e'*64, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                identity().verify_historical(value)
        with self.assertRaises(ValueError):
            replace(identity(), policy_version=2)
        with self.assertRaises(ValueError):
            replace(identity(), wayland_included='true')


class StateContract(unittest.TestCase):
    def test_auditable_lifecycle_and_real_attempts(self):
        original = discovered()
        event = reserve(original, TOKEN, NOW, NOW + timedelta(hours=1))
        self.assertEqual(event.before, original)
        self.assertEqual(event.after.attempt, 0)
        run = bind(event.after, TOKEN, 1, '123', NOW).after
        self.assertEqual(run.attempt, 0)
        run = advance(run, TOKEN, 1, BuildState.RUNNING, NOW).after
        self.assertEqual(run.attempt, 1)
        success = advance(run, TOKEN, 1, BuildState.SUCCEEDED, NOW + timedelta(minutes=5)).after
        self.assertEqual(decide(success, NOW, history_verified=True), Decision.SUCCESS)
        with self.assertRaises(ValueError):
            advance(success, TOKEN, 1, BuildState.FAILED, NOW,
                    failure_class='infra', failure_stage='build', failure_reason='late result')

    def test_stale_worker_and_duplicate_reservation(self):
        with self.assertRaises(ValueError):
            reserve(reserved(), TOKEN, NOW, NOW + timedelta(hours=1))
        for token, fence in ((TOKEN, True), (TOKEN, 2), ('22222222-2222-4222-8222-222222222222', 1)):
            with self.subTest(token=token, fence=fence), self.assertRaises(ValueError):
                bind(reserved(), token, fence, '123', NOW)

    def test_timeout_is_not_permission_to_redispatch(self):
        record = dispatch_unknown(reserved(), TOKEN, 1, NOW).after
        self.assertEqual(decide(record, NOW, history_verified=True), Decision.RECONCILE)
        self.assertEqual(record.attempt, 0)
        self.assertEqual(bind(record, TOKEN, 1, '123', NOW).after.state, BuildState.QUEUED)
        self.assertEqual(decide(reserved(), NOW + timedelta(hours=2), history_verified=True),
                         Decision.RECONCILE)
        run = advance(queued(), TOKEN, 1, BuildState.RUNNING, NOW).after
        self.assertEqual(decide(run, NOW + timedelta(hours=2), history_verified=True),
                         Decision.RECONCILE)

    def test_missing_history_and_cooldown_skip_are_conservative(self):
        self.assertEqual(decide(None, NOW), Decision.REVIEW_REQUIRED)
        self.assertEqual(decide(None, NOW, history_verified=True), Decision.RESERVE)
        cooling = replace(discovered(), policy_state=PolicyState.COOLDOWN,
                          next_retry_at=NOW + timedelta(hours=1))
        for _ in range(10):
            self.assertEqual(decide(cooling, NOW, history_verified=True), Decision.COOLDOWN)
        self.assertEqual(cooling.attempt, 0)
        self.assertEqual(decide(cooling, NOW + timedelta(hours=2), history_verified=True),
                         Decision.RECONCILE)

    def test_prebuild_failure_does_not_consume_build_attempt(self):
        record = advance(queued(), TOKEN, 1, BuildState.FAILED, NOW,
                         failure_class='unknown', failure_stage='resolve',
                         failure_reason='runner stopped before build').after
        self.assertEqual(record.attempt, 0)
        self.assertEqual(decide(record, NOW, history_verified=True), Decision.REVIEW_REQUIRED)
        with self.assertRaises(ValueError):
            advance(queued(), TOKEN, 1, BuildState.FAILED, NOW)

    def test_invalid_state_and_time_rejected(self):
        for changes in (dict(schema_version=2), dict(state='RUNNING'),
                        dict(attempt=-1), dict(created_at=None), dict(created_at=NOW.replace(tzinfo=None)),
                        dict(source_provenance='{"z": 1}'),
                        dict(state=BuildState.SUCCEEDED),
                        dict(reservation_id=TOKEN)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(discovered(), **changes)
        with self.assertRaises(ValueError):
            advance(queued(), TOKEN, 1, BuildState.SUCCEEDED, NOW)
        with self.assertRaises(ValueError):
            bind(reserved(), TOKEN, 1, '123', NOW - timedelta(seconds=1))
        with self.assertRaises(ValueError):
            replace(queued(), state=BuildState.FAILED, completed_at=NOW)
        with self.assertRaises(ValueError):
            replace(queued(), completed_at=NOW)


if __name__ == '__main__':
    unittest.main()
