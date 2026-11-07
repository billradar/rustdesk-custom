"""Contract tests for explicit, fail-closed upstream runner migrations."""
import unittest

from scripts.platform.runner_migrations import effective_runner, migrations, validates_matrix_runner


class RunnerMigrationTests(unittest.TestCase):
    def test_policy_is_schema_v2_and_unique(self):
        rows=migrations()
        keys=[(row['platform'],row['architecture']) for row in rows]
        self.assertEqual(len(keys),len(set(keys)))
        self.assertEqual(set(keys),{('macos','x86_64'),('macos','aarch64')})

    def test_current_and_reviewed_legacy_labels_map_to_effective_images(self):
        self.assertEqual(effective_runner('macos','x86_64','macos-15-intel'),'macos-26-intel')
        self.assertEqual(effective_runner('macos','aarch64','macos-14'),'macos-26')
        self.assertEqual(effective_runner('macos','aarch64','macos-15'),'macos-26')

    def test_unknown_upstream_label_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'unreviewed official runner migration source'):
            effective_runner('macos','aarch64','macos-27')
        with self.assertRaisesRegex(ValueError,'unreviewed official runner migration source'):
            effective_runner('macos','x86_64','macos-26-intel-preview')

    def test_unmigrated_platform_preserves_its_official_runner(self):
        self.assertEqual(effective_runner('linux','x86_64','ubuntu-24.04'),'ubuntu-24.04')

    def test_matrix_validation_uses_reviewed_baseline_not_current_upstream_label(self):
        reviewed=[{'platform':'macos','architecture':'aarch64','runner':'macos-14'}]
        self.assertTrue(validates_matrix_runner('macos','aarch64','macos-26',reviewed))
        self.assertFalse(validates_matrix_runner('macos','aarch64','macos-26-intel',reviewed))
        self.assertFalse(validates_matrix_runner('macos','aarch64','macos-26',[]))


if __name__=='__main__':
    unittest.main()
