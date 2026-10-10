#!/usr/bin/env python3
"""Local deployment checks. These tests never authenticate or sign with PKCS#11."""

import hashlib
import subprocess
import unittest
from pathlib import Path
import grp


INSTALL = Path('/opt/rustdesk-signing-bridge')
STABLE = Path('/usr/local/bin/rustdesk-sign')
SOCKET = Path('/run/pcscd/pcscd.comm')
REPO = Path(__file__).resolve().parents[2]


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)


class InstalledBridgeDeploymentTest(unittest.TestCase):
    def test_launcher_integrity_and_read_only_self_test(self):
        integrity = run([str(STABLE), '--verify-install'])
        self.assertIn('INSTALLED BRIDGE INTEGRITY: PASS', integrity.stdout)
        output = run(['/usr/bin/sudo', '-n', '-u', 'github-runner', str(STABLE), '--self-test']).stdout
        self.assertIn('CERTIFICATE IDENTITY MATCH: PASS', output)
        self.assertIn('PIN REQUESTED: NO', output)
        self.assertIn('PRIVATE KEY OPERATION: NO', output)

    def test_installed_runtime_advertises_v2_v3_without_pin_or_private_key_operation(self):
        output = run(['/usr/bin/sudo', '-n', '-u', 'github-runner', str(STABLE), '--capabilities']).stdout
        self.assertIn('APK SIGNING SCHEMES: v1=YES, v2=YES, v3=YES, v3.1=NO, v4=NO', output)
        self.assertIn('PIN REQUESTED: NO', output)
        self.assertIn('PRIVATE KEY OPERATION: NO', output)

    def test_root_ownership_and_runner_read_execute_only(self):
        self.assertEqual(STABLE.resolve(), INSTALL / 'bin/rustdesk-sign')
        for path in (Path('/usr/local/bin'), STABLE, INSTALL, INSTALL / 'bin', INSTALL / 'lib',
                     INSTALL / 'VERSION', INSTALL / 'MANIFEST.sha256',
                     INSTALL / 'bin/rustdesk-sign', INSTALL / 'lib/rustdesk-android-signing-bridge.jar',
                     INSTALL / 'lib/ipkcs11wrapper-1.0.9.jar', INSTALL / 'lib/apksig-0.9.jar'):
            self.assertEqual(path.stat().st_uid, 0, str(path))
            writable = subprocess.run(['/usr/bin/sudo', '-n', '-u', 'github-runner', 'test', '-w', str(path)])
            self.assertNotEqual(writable.returncode, 0, str(path))
        self.assertEqual(STABLE.lstat().st_uid, 0)

    def test_installed_manifest_matches_runtime_components(self):
        lines = (INSTALL / 'MANIFEST.sha256').read_text().splitlines()
        names = {line.split(None, 1)[1].lstrip('* ') for line in lines}
        expected = {
            'bin/rustdesk-sign', 'lib/rustdesk-android-signing-bridge.jar',
            'lib/ipkcs11wrapper-1.0.9.jar', 'lib/apksig-0.9.jar', 'VERSION',
        }
        self.assertEqual(names, expected)
        for line in lines:
            expected_hash, relative = line.split(None, 1)
            relative = relative.lstrip('* ')
            actual = hashlib.sha256((INSTALL / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected_hash, relative)

    def test_pcsc_access_is_limited_to_runner_group(self):
        self.assertEqual(SOCKET.stat().st_uid, 0)
        self.assertEqual(SOCKET.stat().st_gid, grp.getgrnam('rustdesk-yubikey').gr_gid)
        self.assertEqual(SOCKET.stat().st_mode & 0o777, 0o660)
        authorized = run(['/usr/bin/sudo', '-n', '-u', 'github-runner', '/usr/bin/opensc-tool', '-l'])
        self.assertIn('Yubico YubiKey', authorized.stdout)
        denied_script = '''import socket, sys
s = socket.socket(socket.AF_UNIX)
try:
    s.connect("/run/pcscd/pcscd.comm")
except PermissionError:
    print("DENIED")
    sys.exit(0)
else:
    print("UNEXPECTED ACCESS")
    sys.exit(1)
'''
        denied = run(['/usr/bin/sudo', '-n', '-u', 'nobody', '/usr/bin/python3', '-c', denied_script])
        self.assertIn('DENIED', denied.stdout)

    def test_future_workflows_use_only_installed_signer_path(self):
        production = (REPO / '.github/workflows/sign-android.yml').read_text()
        self.assertIn('/usr/local/bin/rustdesk-sign \\\n            --input', production)
        self.assertIn("inputs.validation_enable_signing == true", production)
        self.assertIn("github.event_name == 'workflow_dispatch'", production)
        self.assertIn("inputs.channel == 'signing-validation'", production)
        self.assertIn('YUBIKEY_PIV_PIN: ${{ secrets.YUBIKEY_PIV_PIN }}', production)
        self.assertIn('[[ -z "${YUBIKEY_PIV_PIN:-}" ]]', production)
        self.assertLess(production.index('ENVIRONMENT PIN AVAILABLE: FAIL'),
                        production.index('/usr/local/bin/rustdesk-sign'))
        validation = (REPO / '.github/workflows/android-signing-validation.yml').read_text()
        self.assertTrue(any(line.strip() in ('validation_enable_signing: true', 'validation_enable_signing: false')
                            for line in validation.splitlines()))
        for forbidden in ('apksigner sign', 'SunPKCS11'):
            self.assertNotIn(forbidden, production)
        dry_run = (REPO / '.github/workflows/android-signing-dry-run.yml').read_text()
        self.assertIn('/usr/local/bin/rustdesk-sign --dry-run', dry_run)
        self.assertNotIn('pull_request', dry_run)
        self.assertNotIn('YUBIKEY_PIV_PIN', dry_run)


if __name__ == '__main__':
    unittest.main(verbosity=2)
