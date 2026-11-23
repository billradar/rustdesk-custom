"""Fail-closed Linux CI entrypoint and shared Stable build-core contracts."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/build/linux.sh'


class LinuxCoreContracts(unittest.TestCase):
    def invoke(self, **changes):
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env.update({
                'PLATFORM_ARCH': 'x86_64',
                'VARIANT': 'standard',
                'PREPARED_SOURCE_DIR': str(Path(td) / 'source'),
                'BUILD_CONFIGURATION': 'CI_TEST',
                'BUILD_CHANNEL': 'ci',
                'PATCHSET': 'v4',
                'UPSTREAM_EXPECTED_SHA': '51f94394ce61e1f3d26229565c326b2862cbdd1f',
                'GITHUB_ACTIONS': 'true',
                'GITHUB_EVENT_NAME': 'pull_request',
                'GITHUB_RUN_ID': '123',
            })
            env.update(changes)
            return subprocess.run(['bash', str(SCRIPT)], cwd=ROOT, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True)

    def test_shell_syntax(self):
        subprocess.run(['bash', '-n', str(SCRIPT)], check=True)

    def test_ci_requires_candidate_event_channel_variant_and_no_wayland(self):
        invalid = (
            {'BUILD_CHANNEL': 'nightly'}, {'BUILD_CHANNEL': 'stable'},
            {'PATCHSET': 'v3'}, {'GITHUB_ACTIONS': 'false'},
            {'GITHUB_EVENT_NAME': 'push'},
            {'BUILD_FLAVOR': 'unattended-wayland'},
            {'VARIANT': 'unexpected'},
        )
        for values in invalid:
            with self.subTest(values=values):
                result = self.invoke(**values)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('CI Linux probe context forbidden', result.stdout)

    def test_unsupported_mode_rejected(self):
        result = self.invoke(BUILD_CONFIGURATION='UNREVIEWED')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid Linux build configuration', result.stdout)

    def test_staging_source_must_be_local_isolated_tree(self):
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CI source must be the isolated staging tree', result.stdout)

    def test_production_denies_ci_channel(self):
        result = self.invoke(BUILD_CONFIGURATION='PRODUCTION', BUILD_CHANNEL='ci')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CI-only source cannot enter production Linux build', result.stdout)

    def test_single_shared_profile_vcpkg_and_production_package_path(self):
        code = SCRIPT.read_text()
        self.assertEqual(code.count('scripts/platform/platform_adapter.py "$source"'), 1)
        self.assertEqual(code.count('"$VCPKG_ROOT/vcpkg" install'), 1)
        self.assertIn('python3 scripts/signing/production_config.py inputs', code)
        self.assertIn('python3 scripts/platform/platform_package.py create', code)
        self.assertIn('cargo check --locked --lib --features hwcodec,flutter,unix-file-copy-paste', code)
        self.assertIn('test -s "$source/src/bridge_generated.rs"', code)
        self.assertIn('test -f "$VCPKG_ROOT/installed/$triplet/lib/libavcodec.a"', code)


if __name__ == '__main__':
    unittest.main()
