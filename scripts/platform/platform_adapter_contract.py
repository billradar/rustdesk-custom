"""Recipe rendering and execution contracts for reviewed upstream changes."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.platform import platform_adapter as adapter


class RecipeTests(unittest.TestCase):
    def test_exact_linux_ci_candidate_and_release_denials(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'metadata/platform').mkdir(parents=True)
            (root/'Cargo.toml').write_text('[package]\nversion = "1.5.3"\n')
            (root/'metadata/platform/adapter-profiles.json').write_text(
                json.dumps({'approved':{'linux':[]}}))
            row={'id':'test-linux','source_sha':'a'*40,'upstream_version':'1.5.3',
                 'platform':'linux','signature':'b'*64,'ci_only':True,
                 'stable_allowed':False,'architectures':['x86_64','aarch64'],
                 'runners':{'x86_64':'ubuntu-22.04','aarch64':'ubuntu-22.04-arm'}}
            registry=root/'metadata/platform/ci-candidates.json'
            registry.write_text(json.dumps({'schema':'platform-ci-candidates-v1',
                                            'candidates':[row]}))
            profile={'signature':'b'*64,'platform':'linux','runner':'ubuntu-22.04',
                     'official_disabled':False,'tools':{}}
            with patch.object(adapter,'ROOT',root),patch.object(
                    adapter,'inspect',return_value=(profile,{})):
                with patch.object(adapter.subprocess,'check_output',return_value='a'*40):
                    result,_=adapter.check(root,'linux','x86_64',channel='ci')
                    self.assertTrue(result['ci_candidate_only'])
                    self.assertFalse(result['stable_allowed'])
                    self.assertEqual(result['candidate_source_sha'],'a'*40)
                    for channel in ('stable','nightly'):
                        with self.subTest(channel=channel),self.assertRaisesRegex(ValueError,'unreviewed official'):
                            adapter.check(root,'linux','x86_64',channel=channel)
                    with patch.dict('os.environ',{'BUILD_FLAVOR':'unattended-wayland'}):
                        with self.assertRaisesRegex(ValueError,'unattended Wayland'):
                            adapter.check(root,'linux','x86_64',channel='ci')
                    with self.assertRaisesRegex(ValueError,'unsupported CI platform or architecture'):
                        adapter.check(root,'android','x86_64',channel='ci')
                    for change in ({'signature':'c'*64},{'upstream_version':'1.5.2'},
                                   {'ci_only':False},{'stable_allowed':True},
                                   {'runners':{'x86_64':'ubuntu-latest','aarch64':'ubuntu-22.04-arm'}}):
                        registry.write_text(json.dumps({'schema':'platform-ci-candidates-v1',
                                                        'candidates':[dict(row,**change)]}))
                        with self.assertRaisesRegex(ValueError,'candidate drift'):
                            adapter.check(root,'linux','x86_64',channel='ci')
                    registry.write_text(json.dumps({'schema':'platform-ci-candidates-v1',
                                                    'candidates':[row]}))
                with patch.object(adapter.subprocess,'check_output',return_value='d'*40):
                    with self.assertRaisesRegex(ValueError,'unreviewed exact'):
                        adapter.check(root,'linux','x86_64',channel='ci')

    def test_real_ci_candidates_not_formally_approved(self):
        import json
        registry=json.loads((adapter.ROOT/'metadata/platform/ci-candidates.json').read_text())
        approved=json.loads((adapter.ROOT/'metadata/platform/adapter-profiles.json').read_text())
        self.assertEqual(registry['schema'],'platform-ci-candidates-v1')
        self.assertEqual({r['source_sha'] for r in registry['candidates']},
                         {'9724512429b053be04cdb843345e99ddcccdb80e',
                          '51f94394ce61e1f3d26229565c326b2862cbdd1f',
                          'a0c0963c483fc8f1aeed4547787d1673adcb583c',
                          '45e34a69239c2c2467fd02af8ee97263ff26ef23'})
        self.assertEqual(len(registry['candidates']), 16)
        self.assertEqual({(r['source_sha'],r['platform']) for r in registry['candidates']},
                         {(sha,platform) for sha in {r['source_sha'] for r in registry['candidates']}
                          for platform in adapter.CI_PLATFORM_RUNNERS})
        for row in registry['candidates']:
            self.assertEqual(row['runners'],adapter.CI_PLATFORM_RUNNERS[row['platform']])
            self.assertEqual(row['architectures'],list(row['runners']))
            self.assertTrue(row['ci_only'])
            self.assertFalse(row['stable_allowed'])
            self.assertRegex(row['signature'],r'^[a-f0-9]{64}$')
            self.assertNotIn(row['signature'],approved['approved'][row['platform']])

    def test_desktop_mobile_ci_scope(self):
        import json
        from os import environ
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'metadata/platform').mkdir(parents=True)
            (root/'Cargo.toml').write_text('[package]\nversion = "1.5.3"\n')
            registry=root/'metadata/platform/ci-candidates.json'
            registry.write_text(json.dumps({'schema':'platform-ci-candidates-v1','candidates':[
                {'id':platform+'-test','source_sha':'a'*40,'upstream_version':'1.5.3',
                 'platform':platform,'signature':'b'*64,'ci_only':True,'stable_allowed':False,
                 'architectures':list(runners),'runners':runners}
                for platform,runners in adapter.CI_PLATFORM_RUNNERS.items()]}))
            (root/'metadata/platform/adapter-profiles.json').write_text(json.dumps(
                {'approved':{p:[] for p in adapter.CI_PLATFORM_RUNNERS}}))
            with patch.object(adapter,'ROOT',root),patch.object(adapter.subprocess,'check_output',return_value='a'*40):
                for platform,runners in adapter.CI_PLATFORM_RUNNERS.items():
                    for arch,runner in runners.items():
                        profile={'signature':'b'*64,'platform':platform,'runner':runner,
                                 'official_disabled':False,'tools':{}}
                        with self.subTest(platform=platform,arch=arch),patch.object(adapter,'inspect',return_value=(profile,{})),patch.dict(environ,{'VARIANT':'standard','BUILD_FLAVOR':''}):
                            admitted,_=adapter.check(root,platform,arch,channel='ci')
                            self.assertTrue(admitted['ci_candidate_only'])
                            self.assertFalse(admitted['stable_allowed'])
                            for channel in ('stable','nightly'):
                                with self.assertRaisesRegex(ValueError,'unreviewed official'):
                                    adapter.check(root,platform,arch,channel=channel)
                            if platform=='android':
                                with patch.dict(environ,{'VARIANT':'sos'}),self.assertRaisesRegex(ValueError,'Android SOS forbidden'):
                                    adapter.check(root,platform,arch,channel='ci')
                            with patch.dict(environ,{'BUILD_FLAVOR':'unattended-wayland'}),self.assertRaisesRegex(ValueError,'unattended Wayland'):
                                adapter.check(root,platform,arch,channel='ci')

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
            self.assertIn('python3 ./build.py --flutter --skip-cargo --hwcodec --unix-file-copy-paste --no-drm', adapted)
            self.assertIn('STOCK_FEATURES=$(python3 ./build.py --flutter --hwcodec --unix-file-copy-paste --no-drm --print-features)', adapted)
            self.assertIn("if [[ \"$STOCK_FEATURES\" != 'hwcodec,flutter,unix-file-copy-paste' ]]", adapted)
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

    def test_stock_linux_deb_rpm_payload_must_not_contain_drm(self):
        from scripts.platform.platform_package import validate_stock_linux_payload
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lib = root / 'usr/share/rustdesk/lib/librustdesk.so'
            lib.parent.mkdir(parents=True)
            lib.write_bytes(b'non-DRM test native library')
            validate_stock_linux_payload(root)
            for value in (b'/usr/lib/rustdesk/libdrmtap.so.0',
                          b'enable-drm-display-wake'):
                with self.subTest(value=value):
                    lib.write_bytes(b'header' + value + b'trailer')
                    with self.assertRaisesRegex(ValueError, 'enables DRM capture'):
                        validate_stock_linux_payload(root)
            lib.write_bytes(b'non-DRM test native library')
            capture = root / 'usr/lib/rustdesk/libdrmtap.so.0.5.12'
            capture.parent.mkdir(parents=True)
            capture.write_bytes(b'prebuilt capture library')
            with self.assertRaisesRegex(ValueError, 'bundles libdrmtap'):
                validate_stock_linux_payload(root)
            capture.unlink()
            symlink = capture.parent/'libdrmtap.so.0'
            symlink.symlink_to('libdrmtap.so.0.5.12')
            with self.assertRaisesRegex(ValueError, 'bundles libdrmtap'):
                validate_stock_linux_payload(root)

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
