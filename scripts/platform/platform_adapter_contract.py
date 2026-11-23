"""Recipe rendering and execution contracts for reviewed upstream changes."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.platform import platform_adapter as adapter


class RecipeTests(unittest.TestCase):
    def test_stock_linux_recipe_never_inherits_implicit_drm(self):
        """Ordinary Standard/SOS artifacts must not silently include the DRM backend."""
        with tempfile.TemporaryDirectory() as temp:
            tree = Path(temp)
            build = tree / 'build.py'
            compile_stock = 'cargo build --locked --lib --features hwcodec,flutter --release'
            package_stock = 'python3 ./build.py --flutter --skip-cargo'
            build.write_text("parser.add_argument('--drm')\n")
            self.assertTrue(adapter.guard_stock_linux_drm_recipe(
                tree, compile_stock + '\n' + package_stock))
            with self.assertRaisesRegex(ValueError, 'explicitly requests DRM'):
                adapter.guard_stock_linux_drm_recipe(
                    tree, compile_stock + '\n' + package_stock + ' --drm')
            build.write_text("parser.add_argument('--no-drm')\n")
            with self.assertRaisesRegex(ValueError, 'requires explicit --no-drm'):
                adapter.guard_stock_linux_drm_recipe(
                    tree, compile_stock + '\n' + package_stock)
            self.assertTrue(adapter.guard_stock_linux_drm_recipe(
                tree, compile_stock + '\n' + package_stock + ' --no-drm'))
            for feature in ('drm', 'drm-wake', 'hwcodec,flutter,drm,drm-wake'):
                with self.subTest(feature=feature), self.assertRaisesRegex(
                        ValueError, 'stock Linux recipe enables DRM'):
                    adapter.guard_stock_linux_drm_recipe(
                        tree, 'cargo build --locked --lib --features ' + feature +
                        '\n' + package_stock + ' --no-drm')

    def test_exact_source_linux_opt_out_recipe_transformation(self):
        original = """
cargo build --locked --lib $JOBS --features hwcodec,flutter,unix-file-copy-paste,drm,drm-wake --release
check_rpm_drm() {
  if [[ "$1" == *something* ]]; then
    echo 'upstream DRM assert'
  fi
}
python3 ./build.py --flutter --skip-cargo
check_rpm_drm "$name"
check_rpm_drm "$name"
"""
        known = '51f94394ce61e1f3d26229565c326b2862cbdd1f'
        with tempfile.TemporaryDirectory() as temp:
            tree = Path(temp)
            (tree/'build.py').write_text("parser.add_argument('--no-drm')\n")
            with patch('subprocess.check_output', return_value=known):
                adapted = adapter.adapt_stock_linux_recipe(tree, original)
            self.assertIn('--features hwcodec,flutter,unix-file-copy-paste --release', adapted)
            self.assertNotIn('--features hwcodec,flutter,unix-file-copy-paste,drm', adapted)
            self.assertIn('python3 ./build.py --flutter --skip-cargo --no-drm', adapted)
            self.assertNotIn('check_rpm_drm()', adapted)
            self.assertNotIn('check_rpm_drm "$name"', adapted)
            self.assertEqual(adapted.count('stock RPM validated after extraction'), 2)
            self.assertIn('stock Linux source contains prebuilt libdrmtap', adapted)
            self.assertTrue(adapter.guard_stock_linux_drm_recipe(tree, adapted))
            with patch('subprocess.check_output', return_value='a'*40):
                with self.assertRaisesRegex(ValueError, 'unreviewed source'):
                    adapter.adapt_stock_linux_recipe(tree, original)
            for drift in (original.replace('drm,drm-wake', 'drm'),
                          original.replace('check_rpm_drm "$name"', ':', 1),
                          original.replace('python3 ./build.py --flutter --skip-cargo',
                                           'python3 ./build.py --flutter --skip-cargo --no-drm')):
                with patch('subprocess.check_output', return_value=known):
                    with self.assertRaisesRegex(ValueError, 'no longer matches'):
                        adapter.adapt_stock_linux_recipe(tree, drift)
            # The reviewed legacy default-off source retains its original recipe.
            (tree/'build.py').write_text("parser.add_argument('--drm')\n")
            legacy = 'cargo build --features hwcodec,flutter\npython3 ./build.py --flutter --skip-cargo'
            with patch('subprocess.check_output', side_effect=AssertionError('legacy must not need SHA lookup')):
                self.assertEqual(adapter.adapt_stock_linux_recipe(tree, legacy), legacy)

    def test_linux_ci_tests_render_and_execute_only_on_x64(self):
        source = '''if [[ "${{ matrix.job.arch }}" == "x86_64" && "${{ inputs.upload-artifact }}" == "false" ]]; then
echo RUN_FLUTTER_TESTS
fi
'''
        for arch in ('x86_64', 'aarch64'):
            profile = dict(platform='linux', rust='1.75', tools={}, official_matrix={'arch': arch})
            script = adapter.render(source, profile)
            self.assertNotIn('${{', script)
            result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script],
                                    check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout, 'RUN_FLUTTER_TESTS\n' if arch == 'x86_64' else '')

    def test_unknown_inputs_and_other_platforms_remain_rejected(self):
        for platform, expression in [('linux', 'inputs.publish-update-metadata'),
                                     ('android', 'inputs.upload-artifact')]:
            profile = dict(platform=platform, rust='1.75', tools={}, official_matrix={})
            with self.assertRaisesRegex(ValueError, 'unhandled official expression'):
                adapter.render('${{ '+expression+' }}', profile)

    def test_android_jni_check_runs_before_dependencies_and_stops_on_failure(self):
        profile = dict(platform='android', rust='1.75', tools={}, official_matrix={})
        for check_script in ('echo JNI_OK', 'exit 1', None):
            with self.subTest(check_script=check_script), tempfile.TemporaryDirectory() as tmp:
                tree = Path(tmp)
                steps = [{'name': 'Install vcpkg dependencies', 'run': 'touch deps-started'}]
                if check_script is not None:
                    steps.insert(0, {'name': 'Check JNI natives are in ffi.FFI', 'run': check_script})
                with patch.object(adapter, 'check', return_value=(profile, {'steps': steps})), \
                     patch('sys.argv', ['platform_commands.py', str(tree), 'android', 'aarch64', 'deps']):
                    if check_script == 'exit 1':
                        with self.assertRaises(subprocess.CalledProcessError):
                            runpy.run_module('scripts.platform.platform_commands', run_name='__main__')
                        self.assertFalse((tree/'deps-started').exists())
                    else:
                        runpy.run_module('scripts.platform.platform_commands', run_name='__main__')
                        self.assertTrue((tree/'deps-started').exists())


if __name__ == '__main__':
    unittest.main()
