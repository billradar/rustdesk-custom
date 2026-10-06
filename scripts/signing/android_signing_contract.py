#!/usr/bin/env python3
import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class StableAndroidSigningContractTests(unittest.TestCase):
    def setUp(self):
        self.tag = yaml.safe_load((ROOT / ".github/workflows/tag.yml").read_text())
        self.build = yaml.safe_load((ROOT / ".github/workflows/build.yml").read_text())
        self.action = (ROOT / ".github/actions/android-yubikey-sign/action.yml").read_text()
        self.script = (ROOT / "scripts/signing/android_yubikey_sign.py").read_text()

    def test_stable_signing_is_a_direct_environment_bound_job(self):
        signing = self.tag["jobs"]["android-sign"]
        self.assertEqual(signing["runs-on"], ["self-hosted", "linux", "arm64", "rustdesk-signing", "android-signing", "yubikey"])
        self.assertEqual(signing["environment"]["name"], "android-production-signing")
        self.assertEqual(signing["concurrency"]["group"], "rustdesk-android-yubikey-signing")
        self.assertFalse(signing["concurrency"]["cancel-in-progress"])
        self.assertEqual(signing["concurrency"]["queue"], "max")
        for marker in ("github.event_name == 'workflow_dispatch'",
                       "needs.android-build.result == 'success'",
                       "needs.qualification.result == 'success'",
                       "needs.prepare.result == 'success'"):
            self.assertIn(marker, signing["if"])
        self.assertNotIn("production_android_signing", signing["if"])
        self.assertNotIn("release_mode != 'dry-run'", signing["if"])

    def test_secret_is_bound_only_at_direct_job_steps(self):
        signing = self.tag["jobs"]["android-sign"]
        expected = "$" + "{{ secrets.YUBIKEY_PIV_PIN }}"
        preflight = next(s for s in signing["steps"] if s.get("name") == "Environment Secret Binding Preflight")
        self.assertEqual(preflight["env"]["YUBIKEY_PIV_PIN"], expected)
        hardware = next(s for s in signing["steps"] if s.get("name") == "Production Android signing")
        self.assertEqual(hardware["env"]["YUBIKEY_PIV_PIN"], expected)
        self.assertNotIn("YUBIKEY_PIV_PIN", json.dumps(self.action))
        self.assertNotIn("YUBIKEY_PIV_PIN", json.dumps(self.build))
        self.assertNotIn("android-signing-preflight", self.build["jobs"])
        self.assertNotIn("production_android_signing", json.dumps(self.build))
        self.assertNotIn("direct_android_signing", json.dumps(self.build))

    def test_signing_action_and_script_keep_hardware_gates(self):
        self.assertIn("actions/download-artifact@", self.action)
        self.assertIn("actions/upload-artifact@", self.action)
        self.assertIn('"/usr/local/bin/rustdesk-sign"', self.script)
        self.assertIn('"--pin-source", "env"', self.script)
        self.assertIn("559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5", self.script)
        self.assertIn('EXPECTED_PACKAGE = "com.carriez.flutter_hbb"', self.script)
        self.assertIn('if not os.environ.get("YUBIKEY_PIV_PIN")', self.script)
        self.assertIn(r'r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})$"', self.script)
        self.assertNotIn(r'r"^Signer #d+ certificate SHA-256 digest:', self.script)

    def test_build_does_not_own_production_signer(self):
        self.assertNotIn("android-sign:", self.build["jobs"])
        aggregate = self.build["jobs"]["aggregate"]
        self.assertNotIn("android-sign", json.dumps(aggregate.get("needs", {})))
        self.assertNotIn("production_android_signing", aggregate.get("if", ""))
        android = self.build["jobs"]["android-platforms"]
        self.assertEqual(android["needs"], "plan")
        self.assertNotIn("production_android_signing", json.dumps(android))
        self.assertNotIn("direct_android_signing", json.dumps(self.build))

    def test_stable_build_split_and_sign_dependency(self):
        windows = self.tag["jobs"]["windows-build"]
        platforms = self.tag["jobs"]["platforms-build"]
        android = self.tag["jobs"]["android-build"]

        self.assertTrue(windows["with"].get("windows_only", False))
        self.assertNotIn("production_android_signing", json.dumps(windows))
        self.assertTrue(platforms["with"].get("other_platforms_only", False))
        self.assertNotIn("production_android_signing", json.dumps(platforms))
        self.assertTrue(android["with"]["android_only"])
        self.assertNotIn("production_android_signing", json.dumps(android))
        self.assertNotIn("direct_android_signing", json.dumps(self.tag))

        self.assertEqual(self.tag["jobs"]["android-sign"]["needs"][-1], "android-build")

        aggregate = self.tag["jobs"]["aggregate"]
        for name in ("windows-build", "platforms-build", "android-build", "android-sign"):
            self.assertIn(name, json.dumps(aggregate["needs"]))

        draft = self.tag["jobs"]["draft"]
        for name in ("windows-build", "platforms-build", "android-build"):
            self.assertIn(name, json.dumps(draft["needs"]))
        self.assertIn("needs.aggregate.result == 'success'", draft["if"])

    def test_android_artifact_name_contract_matches_build_and_sign_downloads(self):
        build_platform = (ROOT / ".github/workflows/build-platform.yml").read_text()
        self.assertIn("inputs.platform == 'android' && 'android-build-input'", build_platform)
        for arch in ("aarch64", "armv7", "x86_64"):
            expected = (
                "android-build-input-${{ inputs.channel }}-${{ inputs.upstream_version }}"
                "-${{ inputs.upstream_sha }}-standard-android-" + arch
            )
            self.assertIn(expected, self.action)
        self.assertNotIn("pattern: *.apk", self.action)
    def test_signing_identity_resolves_repository_root_for_canonical_metadata(self):
        source = (ROOT / "scripts/signing/android_identity.py").read_text()
        self.assertIn("ROOT = Path(__file__).resolve().parents[2]", source)
        self.assertTrue((ROOT / "metadata/signing/android-standard.json").is_file())

    def test_old_reusable_signer_is_gone(self):
        self.assertFalse((ROOT / ".github/workflows/sign-android.yml").exists())

if __name__ == "__main__": unittest.main()
