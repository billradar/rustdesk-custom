"""Check vendored LLVM provenance and exercise its Node.js 24 entry point."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / '.github/actions/install-llvm'


class RuntimeContract(unittest.TestCase):
    def test_vendor_integrity_and_runtime_only_change(self):
        record = json.loads((ACTION / 'upstream.json').read_text())
        for name, digest in record['files_sha256'].items():
            data = (ACTION / name).read_bytes()
            if name == 'action.yml':
                self.assertEqual(yaml.safe_load(data)['runs']['using'], 'node24')
                data = data.replace(b'using: "node24"', b'using: "node20"')
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest, name)

    def test_workflows_use_migrated_actions(self):
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            text = path.read_text()
            self.assertNotIn('setup-msbuild@6fb022', text, path)
            self.assertNotIn('flutter-action@2783a3f', text, path)
            self.assertNotIn('KyleMayes/install-llvm-action@', text, path)

    def test_node24_cached_entrypoint_and_required_input(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js not available')
        version = subprocess.check_output([node, '--version'], text=True)
        if int(version.lstrip('v').split('.')[0]) < 24:
            self.skipTest('Node.js 24 or later required')
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            env = {key: os.environ[key] for key in ('PATH', 'SystemRoot', 'TEMP', 'TMP') if key in os.environ}
            for key in ('GITHUB_ENV', 'GITHUB_PATH', 'GITHUB_OUTPUT'):
                path = folder / key
                path.touch()
                env[key] = str(path)
            env.update({'INPUT_VERSION': '15.0.6', 'INPUT_CACHED': 'true', 'INPUT_DIRECTORY': str(folder / 'llvm')})
            result = subprocess.run([node, str(ACTION / 'dist/main.js')], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn('LLVM_PATH', Path(env['GITHUB_ENV']).read_text())
            self.assertIn('bin', Path(env['GITHUB_PATH']).read_text())
            del env['INPUT_VERSION']
            result = subprocess.run([node, str(ACTION / 'dist/main.js')], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('must be provided', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
