import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class AndroidSigningWorkflowTests(unittest.TestCase):
    def test_production_signing_chain_is_explicit_and_fail_closed(self):
        tag = yaml.safe_load((ROOT / ".github/workflows/tag.yml").read_text())
        build = yaml.safe_load((ROOT / ".github/workflows/build.yml").read_text())
        sign = yaml.safe_load((ROOT / ".github/workflows/sign-android.yml").read_text())

        expr = tag["jobs"]["build"]["with"]["production_android_signing"]
        for marker in (
            "github.event_name == 'workflow_dispatch'",
            "inputs.production_android_signing == true",
            "inputs.dry_run == false",
            "inputs.include_experimental == false",
        ):
            self.assertIn(marker, expr)

        signing = build["jobs"]["android-sign"]
        self.assertNotIn("strategy", signing)
        self.assertEqual(signing["uses"], "./.github/workflows/sign-android.yml")
        self.assertEqual(signing["with"]["arches"], "aarch64,armv7,x86_64")
        self.assertIn("production_android_signing", json.dumps(signing.get("if", "")))

        job = sign["jobs"]["sign"]
        checkout = next(
            step for step in job["steps"]
            if "Checkout signing identity metadata from current commit" in step.get("name", "")
        )
        self.assertEqual(
            checkout["uses"],
            "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
        )
        self.assertEqual(checkout["with"]["ref"], "${{ github.sha }}")
        self.assertEqual(
            checkout["with"]["sparse-checkout"],
            "metadata/yubikey-android-signing-identity.json",
        )
        self.assertEqual(checkout["with"]["fetch-depth"], 1)

        identity = next(
            step for step in job["steps"]
            if "Validate public YubiKey identity metadata" in step.get("name", "")
        )
        self.assertIn(
            "559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5",
            identity["run"],
        )
        self.assertNotIn("legacy_android_signing_identity", identity["run"])

        hardware = next(
            step for step in job["steps"]
            if "Production YubiKey signing of all Android architectures" in step.get("name", "")
        )
        self.assertEqual(
            hardware["env"]["YUBIKEY_PIV_PIN"],
            "${{ secrets.YUBIKEY_PIV_PIN }}",
        )
        self.assertIn("/usr/local/bin/rustdesk-sign", hardware["run"])
        self.assertIn('"--pin-source", "env"', hardware["run"])

        aggregate = build["jobs"]["aggregate"]
        self.assertIn("needs.android-sign.result == 'success'", json.dumps(aggregate.get("if", "")))
        self.assertIn("android-sign", json.dumps(aggregate.get("needs", {})))

        draft = tag["jobs"]["draft"]
        self.assertIn("needs.aggregate.result == 'success'", draft["if"])
        self.assertIn("inputs.production_android_signing == true", draft["if"])


if __name__ == "__main__":
    unittest.main()
