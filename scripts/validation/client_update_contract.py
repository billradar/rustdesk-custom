"""Latest-only client update, identity and executable version-policy regressions."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml
from scripts.source.update_identity import write_identity
from scripts.release.qualification import build_release_body
from scripts.validation.cm_window_contract import new_file

ROOT = Path(__file__).resolve().parents[2]
PATCH = "common/0005-custom-release-updates.patch"


def patch_file(generation, name):
    return new_file((ROOT / "patchsets" / generation / PATCH).read_text(), name)


def source_contract(tree):
    module = (tree / "src/custom_update/mod.rs").read_text()
    expected = patch_file("v2", "src/custom_update/mod.rs")
    if module != expected:
        raise ValueError("Client update implementation differs from reviewed patch")
    ffi = (tree / "src/flutter_ffi.rs").read_text()
    home = (tree / "flutter/lib/desktop/pages/desktop_home_page.dart").read_text()
    if "custom_update::response(&key)" not in ffi or "showCustomUpdateDialog();" not in home:
        raise ValueError("Client update UI/FFI route missing")


class ClientUpdateTests(unittest.TestCase):
    def test_both_patch_generations_share_the_same_update_policy(self):
        for name in ("src/custom_update/mod.rs", "src/custom_update/policy.rs",
                     "src/custom_update/stable_release_fixture.txt",
                     "flutter/lib/common/widgets/custom_update.dart"):
            self.assertEqual(patch_file("v1", name), patch_file("v2", name))

    def test_parser_fixture_is_generated_by_the_real_stable_publisher(self):
        actual = build_release_body(
            "Official release notes used by the producer/consumer regression.", [
                "upstream_repository=rustdesk/rustdesk", "upstream_tag=1.5.1",
                "upstream_sha=" + "a" * 40, "patchset=v2",
                "custom_release_revision=v2.6", "automation_state=complete"])
        self.assertEqual(actual, patch_file("v2", "src/custom_update/stable_release_fixture.txt"))

    def test_latest_only_and_no_beta_ui(self):
        module = patch_file("v2", "src/custom_update/mod.rs")
        widget = patch_file("v2", "flutter/lib/common/widgets/custom_update.dart")
        self.assertIn("/billradar/rustdesk-custom/releases/latest", module)
        self.assertNotIn("releases/tags/nightly", module)
        self.assertNotIn("参加内测", widget)
        self.assertNotIn("nightly", widget.lower())
        self.assertIn(".https_only(true)", module)
        self.assertIn("verify_file(&d.path", module)

    def test_stable_revision_is_passed_from_preflight_to_prepared_source(self):
        tag = yaml.safe_load((ROOT / ".github/workflows/tag.yml").read_text())
        self.assertEqual(tag["jobs"]["prepare"]["with"]["patch_revision"],
                         "${{ needs.draft-preflight.outputs.patch_revision }}")
        self.assertIs(tag["jobs"]["prepare"]["with"]["client_release_identity"], True)
        prepare = yaml.safe_load((ROOT / ".github/workflows/prepare-source.yml").read_text())
        self.assertEqual(prepare["jobs"]["prepare"]["env"]["CLIENT_PATCH_REVISION"],
                         "${{ inputs.patch_revision }}")

    def test_identity_requires_qualified_stable_revision_and_separates_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            destination = tree / "src/custom_update/build.json"
            destination.parent.mkdir(parents=True)
            destination.write_text("{}")
            args = dict(version="1.5.1", sha="a" * 40, variant="standard", run="123",
                        channel="stable", revision="v2.6")
            self.assertEqual(write_identity(tree, **args)["revision"], "v2.6")
            self.assertEqual(json.loads(destination.read_text())["variant"], "standard")
            args.update(variant="sos")
            self.assertEqual(write_identity(tree, **args)["variant"], "sos")
            for invalid in ("", "v2.0", "v2.6/evil"):
                with self.subTest(revision=invalid), self.assertRaises(ValueError):
                    write_identity(tree, **(args | {"revision": invalid}))
            args.update(channel="nightly", revision="")
            self.assertIsNone(write_identity(tree, **args)["revision"])
            with self.assertRaises(ValueError):
                write_identity(tree, **(args | {"revision": "v2.6"}))

    def test_policy_with_real_rust_compiler(self):
        compiler = RUSTC or shutil.which("rustc")
        if not compiler:
            self.skipTest("rustc unavailable; CI preflight executes this policy")
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            policy = tree / "policy.rs"
            policy.write_text(patch_file("v2", "src/custom_update/policy.rs"))
            (tree / "stable_release_fixture.txt").write_text(
                patch_file("v2", "src/custom_update/stable_release_fixture.txt"))
            executable = tree / "policy-tests"
            subprocess.run([compiler, "--edition=2021", "--test", str(policy),
                            "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)


RUSTC = None
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--rustc")
    args = parser.parse_args()
    RUSTC = args.rustc
    if args.source:
        source_contract(args.source)
    unittest.main(argv=[__file__])
