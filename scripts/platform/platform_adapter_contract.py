"""Recipe rendering and execution contracts for reviewed upstream changes."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.platform import platform_adapter as adapter


class RecipeTests(unittest.TestCase):
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
