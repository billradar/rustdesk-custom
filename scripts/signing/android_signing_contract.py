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
        self.hardware_signer = (ROOT / "tools/android-signing-bridge/src/main/java/com/billradar/rustdesk/signing/bridge/RealYubikeyApksigOneShot.java").read_text()

    def test_stable_signing_is_a_direct_environment_bound_job(self):
        signing = self.tag["jobs"]["android-sign"]
        self.assertEqual(signing["runs-on"], ["self-hosted", "linux", "arm64", "rustdesk-signing", "android-signing", "yubikey"])
        self.assertEqual(signing["environment"]["name"], "android-production-signing")
        self.assertEqual(signing["concurrency"]["group"], "rustdesk-android-yubikey-signing")
        self.assertFalse(signing["concurrency"]["cancel-in-progress"])
        self.assertNotIn("queue", signing["concurrency"])
        for marker in ("github.event_name == 'workflow_dispatch'",
                       "needs.android-build.result == 'success'"):
            self.assertIn(marker, signing["if"])
        self.assertNotIn("production_android_signing", signing["if"])
        self.assertIn("release_mode != 'dry-run'", signing["if"])

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

    def test_production_signer_enables_and_requires_both_v2_v3(self):
        self.assertIn("EXPECTED_HARDWARE_SIGNATURE_COUNT = 3", self.hardware_signer)
        self.assertIn("SIGNING SCHEMES: v1=YES, v2=YES, v3=YES", self.hardware_signer)
        self.assertIn('"setV2SigningEnabled", boolean.class, true', self.hardware_signer)
        self.assertIn('"setV3SigningEnabled", boolean.class, true', self.hardware_signer)
        self.assertNotIn('"setV3SigningEnabled", boolean.class, false', self.hardware_signer)
        self.assertIn("if not {2, 3}.issubset(set(schemes)):", self.script)
        self.assertIn("both v2 and v3 signatures verified", self.script)

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
        windows=self.tag["jobs"]["windows-build"]
        platforms=self.tag["jobs"]["platforms-build"]
        android=self.tag["jobs"]["android-build"]
        self.assertEqual(windows["uses"],"./.github/workflows/build-stable-windows.yml")
        self.assertEqual(platforms["uses"],"./.github/workflows/build-stable-platforms.yml")
        self.assertEqual(android["uses"],"./.github/workflows/build-stable-android.yml")
        for job in (windows,platforms,android):
            self.assertNotIn("windows_only",job.get("with",{}))
            self.assertNotIn("other_platforms_only",job.get("with",{}))
            self.assertNotIn("android_only",job.get("with",{}))
            self.assertNotIn("production_android_signing",json.dumps(job))
            self.assertNotIn("direct_android_signing",json.dumps(job))
        self.assertEqual(self.tag["jobs"]["android-sign"]["needs"],["resolve","android-build"])
        aggregate=self.tag["jobs"]["aggregate"]
        for name in ("windows-build","platforms-build","android-build","android-sign"):
            self.assertIn(name,json.dumps(aggregate["needs"]))
        draft=self.tag["jobs"]["draft"]
        self.assertEqual(draft["needs"],"aggregate")
        self.assertIn("needs.aggregate.result == 'success'",draft["if"])


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

    def test_only_canonical_yubikey_signing_identity_is_recorded(self):
        metadata = json.loads((ROOT / "metadata/signing/android-standard.json").read_text())
        self.assertNotIn("legacy", metadata)
        self.assertNotIn("legacy_android_signing_identity", metadata["production"])
        self.assertEqual(
            metadata["production"]["certificate_sha256"],
            "559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5",
        )
        source = (ROOT / "scripts/signing/android_identity.py").read_text()
        for marker in (
            "ANDROID_SIGNING_KEY",
            "ANDROID_KEY_STORE_PASSWORD",
            "ANDROID_KEY_PASSWORD",
            "ANDROID_ALIAS",
            "legacy-production-apk",
            "legacy_apk",
            "legacy_android_signing_identity",
            "def expected(",
            "def preflight(",
            "def stage(",
            "def finalize(",
        ):
            self.assertNotIn(marker, source)

    def test_old_reusable_signer_is_gone(self):
        self.assertFalse((ROOT / ".github/workflows/sign-android.yml").exists())

if __name__ == "__main__": unittest.main()
