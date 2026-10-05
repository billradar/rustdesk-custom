import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class StableAndroidSigningContractTests(unittest.TestCase):
    def setUp(self):
        self.tag = yaml.safe_load((ROOT / ".github/workflows/tag.yml").read_text())
        self.build = yaml.safe_load((ROOT / ".github/workflows/build.yml").read_text())
        self.action = (ROOT / ".github/actions/android-yubikey-sign/action.yml").read_text()
        self.script = (ROOT / "scripts/android_yubikey_sign.py").read_text()

    def test_stable_signing_is_a_direct_environment_bound_job(self):
        signing = self.tag["jobs"]["android-sign"]
        self.assertEqual(signing["runs-on"], ["self-hosted", "linux", "arm64", "rustdesk-signing", "android-signing", "yubikey"])
        self.assertEqual(signing["environment"]["name"], "android-production-signing")
        self.assertEqual(signing["concurrency"]["group"], "rustdesk-android-yubikey-signing")
        self.assertFalse(signing["concurrency"]["cancel-in-progress"])
        self.assertEqual(signing["concurrency"]["queue"], "max")
        for marker in ("github.event_name == 'workflow_dispatch'", "inputs.production_android_signing == true", "inputs.dry_run == false", "inputs.include_experimental == false"):
            self.assertIn(marker, signing["if"])

    def test_secret_is_bound_only_at_direct_job_steps(self):
        signing = self.tag["jobs"]["android-sign"]
        expected = "$" + "{{ secrets.YUBIKEY_PIV_PIN }}"
        preflight = next(s for s in signing["steps"] if s.get("name") == "Environment Secret Binding Preflight")
        self.assertEqual(preflight["env"]["YUBIKEY_PIV_PIN"], expected)
        hardware = next(s for s in signing["steps"] if s.get("name") == "Production Android signing")
        self.assertEqual(hardware["env"]["YUBIKEY_PIV_PIN"], expected)
        self.assertNotIn("YUBIKEY_PIV_PIN", json.dumps(self.action))
        self.assertNotIn("YUBIKEY_PIV_PIN", json.dumps(self.build))

    def test_signing_action_and_script_keep_hardware_gates(self):
        self.assertIn("actions/download-artifact@", self.action)
        self.assertIn("actions/upload-artifact@", self.action)
        self.assertIn('"/usr/local/bin/rustdesk-sign"', self.script)
        self.assertIn('"--pin-source", "env"', self.script)
        self.assertIn("559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5", self.script)
        self.assertIn('EXPECTED_PACKAGE = "com.carriez.flutter_hbb"', self.script)
        self.assertIn('if not os.environ.get("YUBIKEY_PIV_PIN")', self.script)

    def test_build_does_not_own_production_signer(self):
        self.assertNotIn("android-sign:", self.build["jobs"])
        aggregate = self.build["jobs"]["aggregate"]
        self.assertNotIn("android-sign", json.dumps(aggregate.get("needs", {})))
        self.assertIn("inputs.production_android_signing != true", aggregate["if"])

    def test_stable_aggregate_waits_for_direct_signer(self):
        aggregate = self.tag["jobs"]["aggregate"]
        self.assertIn("android-sign", json.dumps(aggregate["needs"]))
        draft = self.tag["jobs"]["draft"]
        self.assertIn("needs.aggregate.result == 'success'", draft["if"])
        self.assertIn("inputs.production_android_signing == true", draft["if"])

    def test_old_reusable_signer_is_gone(self):
        self.assertFalse((ROOT / ".github/workflows/sign-android.yml").exists())


if __name__ == "__main__":
    unittest.main()
