#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import phase52_dry_run as dry_run


class DryRunGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.artifact = self.base / "artifact"
        self.output = self.base / "output"
        dry_run.build_fixture(self.artifact, "billradar/rustdesk-custom", "refs/heads/main", "a" * 40, "123")

    def tearDown(self):
        self.temp.cleanup()

    def test_provenance_and_metadata_pass(self):
        info = dry_run.validate_fixture(self.artifact, "billradar/rustdesk-custom", "refs/heads/main", "a" * 40, "123")
        self.assertEqual(info["variant"], "standard")
        self.assertEqual(info["architecture"], "aarch64")

    def test_rejects_untrusted_repository(self):
        with self.assertRaisesRegex(dry_run.GateError, "repository"):
            dry_run.validate_fixture(self.artifact, "attacker/fork", "refs/heads/main", "a" * 40, "123")

    def test_rejects_untrusted_ref(self):
        with self.assertRaisesRegex(dry_run.GateError, "ref"):
            dry_run.validate_fixture(self.artifact, "billradar/rustdesk-custom", "refs/heads/topic", "a" * 40, "123")

    def test_rejects_wrong_run_or_commit(self):
        with self.assertRaisesRegex(dry_run.GateError, "commit"):
            dry_run.validate_fixture(self.artifact, "billradar/rustdesk-custom", "refs/heads/main", "b" * 40, "123")
        with self.assertRaisesRegex(dry_run.GateError, "run_id"):
            dry_run.validate_fixture(self.artifact, "billradar/rustdesk-custom", "refs/heads/main", "a" * 40, "456")

    def test_rejects_package_arch_and_variant_mismatch(self):
        path = self.artifact / "build-info.json"
        original = json.loads(path.read_text())
        for key, value in (("package_name", "evil.package"), ("architecture", "x86_64"), ("variant", "sos")):
            modified = dict(original, **{key: value})
            path.write_text(json.dumps(modified))
            with self.subTest(key=key), self.assertRaises(dry_run.GateError):
                dry_run.validate_fixture(self.artifact, "billradar/rustdesk-custom", "refs/heads/main", "a" * 40, "123")
        path.write_text(json.dumps(original))

    def test_rejects_checksum_tamper_and_extra_file(self):
        payload = self.artifact / dry_run.FIXTURE_NAME
        payload.write_bytes(b"tampered")
        with self.assertRaisesRegex(dry_run.GateError, "checksum"):
            dry_run.validate_fixture(self.artifact, "billradar/rustdesk-custom", "refs/heads/main", "a" * 40, "123")
        payload.write_bytes(dry_run.FIXTURE_BYTES)
        (self.artifact / "unexpected").write_text("extra")
        with self.assertRaisesRegex(dry_run.GateError, "unexpected"):
            dry_run.validate_fixture(self.artifact, "billradar/rustdesk-custom", "refs/heads/main", "a" * 40, "123")

    def test_simulation_preserves_input_and_validates_exact_count(self):
        before = (self.artifact / dry_run.FIXTURE_NAME).read_bytes()
        dry_run.simulate(self.artifact, self.output, "billradar/rustdesk-custom", "refs/heads/main", "a" * 40, "123")
        self.assertEqual(before, (self.artifact / dry_run.FIXTURE_NAME).read_bytes())
        receipt = dry_run.validate_receipt(self.output)
        self.assertEqual(receipt["actual_mock_signature_operations"], 2)
        receipt["actual_mock_signature_operations"] = 1
        (self.output / "dry-run-receipt.json").write_text(json.dumps(receipt))
        with self.assertRaisesRegex(dry_run.GateError, "actual_mock_signature_operations"):
            dry_run.validate_receipt(self.output)

    def test_refuses_to_overwrite_output(self):
        self.output.mkdir()
        with self.assertRaisesRegex(dry_run.GateError, "overwrite"):
            dry_run.simulate(self.artifact, self.output, "billradar/rustdesk-custom", "refs/heads/main", "a" * 40, "123")


if __name__ == "__main__":
    unittest.main(verbosity=2)
