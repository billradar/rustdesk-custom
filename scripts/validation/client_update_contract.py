"""Latest-only client update, identity and executable version-policy regressions."""
import argparse
import json
import os
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
    return new_file((ROOT / "patchsets" / generation / PATCH).read_text(encoding='utf-8'), name)


def source_contract(tree, generation="v2"):
    module = (tree / "src/custom_update/mod.rs").read_text(encoding='utf-8')
    expected = patch_file(generation, "src/custom_update/mod.rs")
    if module != expected:
        raise ValueError("Client update implementation differs from reviewed patch")
    policy = (tree / "src/custom_update/policy.rs").read_text(encoding='utf-8')
    if policy != patch_file(generation, "src/custom_update/policy.rs"):
        raise ValueError("Client update package policy differs from selected patchset")
    ffi = (tree / "src/flutter_ffi.rs").read_text(encoding='utf-8')
    home = (tree / "flutter/lib/desktop/pages/desktop_home_page.dart").read_text(encoding='utf-8')
    if "custom_update::response(&key)" not in ffi or "showCustomUpdateDialog();" not in home:
        raise ValueError("Client update UI/FFI route missing")


class ClientUpdateTests(unittest.TestCase):
    def test_both_patch_generations_share_the_same_update_policy(self):
        for name in ("src/custom_update/mod.rs", "src/custom_update/policy.rs",
                     "src/custom_update/stable_release_fixture.txt",
                     "flutter/lib/common/widgets/custom_update.dart"):
            self.assertEqual(patch_file("v1", name), patch_file("v2", name))

    def test_v3_changes_only_the_rpm_package_selector_in_update_policy(self):
        old=patch_file('v2','src/custom_update/policy.rs')
        start=old.index('            let rpm_arch =')
        end=old.index('            let tail =',start)
        expected=(old[:start]+old[end:]).replace('-linux-{arch}-0.{rpm_arch}{tail}', '-linux-{arch}{tail}')
        self.assertEqual(patch_file('v3','src/custom_update/policy.rs'),expected)
        for name in ('src/custom_update/mod.rs','src/custom_update/stable_release_fixture.txt','flutter/lib/common/widgets/custom_update.dart'):
            self.assertEqual(patch_file('v3',name),patch_file('v2',name))

    def test_publisher_names_match_executed_client_selectors_for_all_packages(self):
        compiler=RUSTC or shutil.which('rustc')
        if not compiler:self.skipTest('rustc unavailable; CI runs the package policy')
        from scripts.release.qualification import plan
        from scripts.release.naming import native_package_name,windows_installer_name
        from scripts.platform.wayland import package_name
        for generation in ('v2','v3'):
            cases=[]
            for target in plan('stable')['selected']:
                os_name=target['platform'];arch=target['arch'];variant=target['variant']
                formats={'windows':['exe','msi'],'linux':['deb','rpm','suse.rpm'],'macos':['dmg'],'android':['apk']}[os_name]
                for fmt in formats:
                    if os_name=='windows':name=windows_installer_name('1.5.3',variant,fmt,arch)
                    else:
                        tails={'deb':'.deb','rpm':f'-0.{arch}.rpm','suse.rpm':f'-0.{arch}-suse.rpm','dmg':'-unsigned.dmg','apk':'-signed.apk'}
                        raw=f'{variant}-rustdesk-1.5.3-{arch}'+tails[fmt]
                        name=native_package_name('1.5.3',variant,os_name,arch,raw,legacy_rpm=generation=='v2')
                    cases.append((variant,os_name,arch,False,fmt,name))
            for variant in ('standard','sos'):
                for arch in ('x86_64','aarch64'):cases.append((variant,'linux',arch,True,'deb',package_name('1.5.3',variant,arch)))
            self.assertEqual(len(cases),31)
            with tempfile.TemporaryDirectory() as td:
                tree=Path(td);(tree/'policy.rs').write_text(patch_file(generation,'src/custom_update/policy.rs'))
                assertions=[]
                for variant,platform,arch,wayland,fmt,name in cases:
                    args=', '.join(json.dumps(v) for v in ('1.5.3',variant,platform,arch))+', '+str(wayland).lower()+', '+json.dumps(fmt)
                    assertions.append('assert_eq!(policy::package_name('+args+'), Some('+json.dumps(name)+'.to_string()));')
                (tree/'driver.rs').write_text('mod policy; fn main() {\n'+'\n'.join(assertions)+'\n}')
                build=subprocess.run([compiler,'--edition=2021',str(tree/'driver.rs'),'-o',str(tree/'driver')],capture_output=True,text=True)
                self.assertEqual(build.returncode,0,build.stderr)
                subprocess.run([str(tree/'driver')],check=True,capture_output=True)

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
        self.assertIn("https://api.github.com/repos/{}/releases/latest", module)
        self.assertNotIn("billradar/rustdesk-custom", module)
        self.assertIn("b.repository", module)
        self.assertNotIn("releases/tags/nightly", module)
        self.assertNotIn("参加内测", widget)
        self.assertNotIn("nightly", widget.lower())
        self.assertIn(".https_only(true)", module)
        self.assertIn("verify_file(&d.path", module)

    def test_stable_revision_is_passed_from_preflight_to_prepared_source(self):
        tag = yaml.safe_load((ROOT / ".github/workflows/tag.yml").read_text(encoding='utf-8'))
        self.assertEqual(tag["jobs"]["prepare"]["with"]["patch_revision"],
                         "${{ needs.draft-preflight.outputs.patch_revision }}")
        self.assertIs(tag["jobs"]["prepare"]["with"]["client_release_identity"], True)
        prepare = yaml.safe_load((ROOT / ".github/workflows/prepare-source.yml").read_text(encoding='utf-8'))
        self.assertEqual(prepare["jobs"]["prepare"]["env"]["CLIENT_PATCH_REVISION"],
                         "${{ inputs.patch_revision }}")

    def test_identity_requires_qualified_stable_revision_and_separates_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            destination = tree / "src/custom_update/build.json"
            destination.parent.mkdir(parents=True)
            destination.write_text("{}", encoding='utf-8')
            about = tree / 'flutter/lib/common/custom_about_identity.dart'
            about.parent.mkdir(parents=True)
            about.write_text("", encoding='utf-8')
            args = dict(repository="fork-owner/custom-client", version="1.5.1", sha="a" * 40, variant="standard", run="123",
                        channel="stable", revision="v2.8")
            self.assertEqual(write_identity(tree, **args)["revision"], "v2.8")
            self.assertEqual(json.loads(destination.read_text(encoding='utf-8'))["variant"], "standard")
            self.assertEqual(json.loads(destination.read_text(encoding='utf-8'))["repository"], "fork-owner/custom-client")
            for invalid in ("", "https://github.com/owner/repo", "owner/repo/extra", "owner/repo?x", "owner/.."):
                with self.subTest(repository=invalid), self.assertRaises(ValueError):
                    write_identity(tree, **(args | {"repository": invalid}))
            args.update(variant="sos")
            self.assertEqual(write_identity(tree, **args)["variant"], "sos")
            for invalid in ("", "v2.0", "v2.6/evil", "v2.7", "v1.2"):
                with self.subTest(revision=invalid), self.assertRaises(ValueError):
                    write_identity(tree, **(args | {"revision": invalid}))
            args.update(channel="nightly", revision="")
            self.assertIsNone(write_identity(tree, **args)["revision"])
            with self.assertRaises(ValueError):
                write_identity(tree, **(args | {"revision": "v2.6"}))

    def test_about_identity_versions_variants_and_wayland_isolation(self):
        from scripts.source.update_identity import ABOUT_PATH, about_source, enable_wayland_about, verify_about_identity
        with tempfile.TemporaryDirectory() as directory:
            tree=Path(directory)
            native=tree/'src/custom_update/build.json';native.parent.mkdir(parents=True)
            about=tree/ABOUT_PATH;about.parent.mkdir(parents=True)
            native.write_text('{}');about.write_text('')
            for variant,label in [('standard','Standard'),('sos','SOS')]:
                for channel,revision,version in [('stable','v2.8','1.5.0-custom.v2.8'),
                                                  ('nightly','','1.5.0-custom.v2.8-nightly'),('ci','','1.5.0-custom.v2.8-ci')]:
                    with self.subTest(variant=variant,channel=channel):
                        data=write_identity(tree,repository='owner/repo',version='1.5.0',sha='a'*40,
                                            variant=variant,run='123',channel=channel,revision=revision)
                        before=native.read_bytes()
                        self.assertIn('"'+version+'"',about.read_text())
                        self.assertIn('"'+label+'"',about.read_text())
                        self.assertIn('customAboutWayland = false',about.read_text())
                        verify_about_identity(tree)
                        with self.assertRaises(ValueError):enable_wayland_about(tree,'sos' if variant=='standard' else 'standard')
                        enable_wayland_about(tree,variant)
                        verify_about_identity(tree,unattended=True)
                        self.assertIn('customAboutWayland = true',about.read_text())
                        self.assertEqual(native.read_bytes(),before)
                        self.assertEqual(data['version'],'1.5.0')
                        with self.assertRaises(ValueError):verify_about_identity(tree)
                        about.write_text(about_source(data).replace(version,'9.9.9-custom'))
                        with self.assertRaises(ValueError):verify_about_identity(tree)

    def test_policy_with_real_rust_compiler(self):
        compiler = RUSTC or shutil.which("rustc")
        if not compiler:
            self.skipTest("rustc unavailable; CI preflight executes this policy")
        for generation in ('v2','v3'):
            with tempfile.TemporaryDirectory() as directory:
                tree = Path(directory)
                policy = tree / "policy.rs"
                policy.write_text(patch_file(generation, "src/custom_update/policy.rs"), encoding='utf-8')
                (tree / "stable_release_fixture.txt").write_text(
                    patch_file(generation, "src/custom_update/stable_release_fixture.txt"), encoding='utf-8')
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
        source_contract(args.source, os.environ.get("PATCHSET", "v2"))
    unittest.main(argv=[__file__])
