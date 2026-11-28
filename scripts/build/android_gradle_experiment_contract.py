"""Offline checks for the Gradle dependency seed boundary."""

from pathlib import Path
import tempfile
import unittest

from scripts.build.android_gradle_experiment import seed_dependencies


class SeedContract(unittest.TestCase):
    def test_copy_only_dependencies_without_locks_or_task_output(self):
        with tempfile.TemporaryDirectory() as directory:
            cold = Path(directory) / 'cold'
            warm = Path(directory) / 'warm'
            for name in ('caches/modules-2/files-2.1/example.jar',
                         'caches/modules-2/modules-2.lock', 'caches/modules-2/gc.properties',
                         'caches/build-cache-1/task', 'gradle.properties'):
                path = cold / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            seed_dependencies(cold, warm)
            files = {path.relative_to(warm).as_posix() for path in warm.rglob('*') if path.is_file()}
            self.assertEqual(files, {'caches/modules-2/files-2.1/example.jar'})

    def test_reject_empty_home_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            cold = Path(directory) / 'cold'
            warm = Path(directory) / 'warm'
            with self.assertRaises(ValueError):
                seed_dependencies(cold, warm)
            modules = cold / 'caches/modules-2'
            modules.mkdir(parents=True)
            (modules / 'unsafe').symlink_to(warm)
            with self.assertRaises(ValueError):
                seed_dependencies(cold, warm)
            self.assertFalse(warm.exists())


if __name__ == '__main__':
    unittest.main()
