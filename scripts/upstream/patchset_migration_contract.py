"""Offline contracts for the blocked Patchset migration boundary."""
import copy
import json
import subprocess
import sys
import unittest

from scripts.upstream import patchset_migration as migration
from scripts.release.coordinator.identity import BuildIdentity, SourceIdentity


class MigrationContract(unittest.TestCase):
    def setUp(self):
        self.audit = json.loads(migration.AUDIT.read_text())

    def test_audit_valid_but_cutover_blocked(self):
        result = migration.report(self.audit)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertFalse(result['release_cutover_allowed'])
        self.assertTrue(result['candidates_are_not_assigned_versions'])

    def test_legacy_draft_display_names_are_occupied(self):
        for version, revision in [('1.5.0', 6), ('1.5.1', 1)]:
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'immutable'):
                migration.target_available(version, 'v2', revision, self.audit)
        self.assertTrue(any(r['tag_name'].startswith('untagged-') for r in self.audit['releases']))

    def test_archived_allocation_remains_occupied(self):
        with self.assertRaisesRegex(ValueError, 'immutable'):
            migration.target_available('1.5.0', 'v2', 5, self.audit)

    def test_same_spelling_does_not_imply_content_semantics(self):
        self.assertEqual(migration.classify('v1.5.1-custom.v2.1', self.audit), migration.LEGACY)
        self.assertEqual(migration.classify('v1.5.1-custom.v2.7', self.audit), 'UNKNOWN_REQUIRES_EVIDENCE')
        self.assertEqual(migration.classify('v9.0.0-custom.v2.1', self.audit), 'UNKNOWN_REQUIRES_EVIDENCE')

    def test_candidate_floor_spans_upstream_versions(self):
        self.audit['candidate_initial_revisions']['v2'] = 2
        with self.assertRaisesRegex(ValueError, 'exceed'):
            migration.validate(self.audit)

    def test_candidate_not_automatically_allocated(self):
        self.assertEqual(migration.target_available('1.5.1', 'v2', 7, self.audit), 'v1.5.1-custom.v2.7')
        self.assertFalse(migration.report(self.audit)['release_cutover_allowed'])

    def test_audit_cannot_self_activate(self):
        for key, value in [('status', 'ACTIVE'), ('activation_blockers', [])]:
            audit = copy.deepcopy(self.audit)
            audit[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                migration.validate(audit)

    def test_duplicate_releases_and_tags_fail(self):
        for key in ('releases', 'tags'):
            audit = copy.deepcopy(self.audit)
            audit[key].append(copy.deepcopy(audit[key][0]))
            with self.subTest(key=key), self.assertRaises(ValueError):
                migration.validate(audit)

    def test_draft_metadata_must_match_display_name(self):
        self.audit['releases'][0]['metadata']['custom_release_revision'] = 'v2.7'
        with self.assertRaisesRegex(ValueError, 'disagree'):
            migration.validate(self.audit)

    def test_current_coordinator_cannot_distinguish_content_reversion(self):
        # A -> B -> A with N, N+1, N+2. This is evidence of the migration
        # blocker, not the desired future behavior or permission to reuse N.
        sources = [SourceIdentity('a' * 40, 'v2', common * 64, 'c' * 64)
                   for common in ('b', 'd', 'b')]
        self.assertEqual(sources[0].key, sources[2].key)
        self.assertNotEqual(sources[0].key, sources[1].key)
        for channel in ('stable', 'nightly'):
            keys = [BuildIdentity(channel, source, False, '', False).key for source in sources]
            self.assertEqual(keys[0], keys[2])
        self.assertFalse(migration.identity_gaps()['source_binds_revision'])
        self.assertTrue(migration.identity_gaps()['build_binds_policy_digest'])
        self.assertTrue(migration.identity_gaps()['build_binds_revision'])

    def test_cli_is_machine_readable_and_check_fails_closed(self):
        for args, code in [([], 0), (['--check'], 1)]:
            run = subprocess.run([sys.executable, '-m', 'scripts.upstream.patchset_migration', *args],
                                 cwd=migration.ROOT, text=True, capture_output=True)
            self.assertEqual(run.returncode, code, run.stderr)
            self.assertFalse(json.loads(run.stdout)['release_cutover_allowed'])


if __name__ == '__main__':
    unittest.main()
