#!/usr/bin/env python3
"""Repository-wide architecture contract.

This contract checks repository structure and cross-domain invariants only.
Domain-specific build/release/signing contracts remain authoritative for their
own behavior.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

NON_FUNCTIONAL_ROOT_NAMES = {
    ".gitignore",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
}
FORBIDDEN_FILENAMES = {
    "patch-revision.txt",
    "requirements-build.txt",
}
LEGACY_TEXT_MARKERS = (
    "patch-revision.txt",
    "requirements-build.txt",
    "tests/",
)
SIGNING_WORKFLOWS = {
    ".github/workflows/tag.yml",
    ".github/workflows/android-yubikey-signing-test.yml",
    ".github/workflows/nightly.yml",
}
# This manual, read-only preflight is allowed to target the dedicated signing
# runner, but must never bind a PIN or invoke a production signing operation.
READ_ONLY_SIGNING_PREFLIGHT = ".github/workflows/test-android-v3-signing.yml"
SIGNING_MARKERS = (
    "YUBIKEY_PIV_PIN",
    "android-production-signing",
    "PKCS#11",
    "pkcs11",
    "YubiKey",
    "yubikey",
    "rustdesk-signing",
    "android-signing",
)


def tracked_files() -> list[Path]:
    return [
        p for p in ROOT.rglob("*")
        if p.is_file() and ".git" not in p.parts
    ]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def fail(errors: list[str], path: Path, reason: str, expected: str = "", actual: str = "") -> None:
    detail = f"{rel(path)}: {reason}"
    if expected:
        detail += f"; expected={expected}"
    if actual:
        detail += f"; actual={actual}"
    errors.append(detail)


def is_non_functional_document(path: Path) -> bool:
    r = rel(path)
    if r == "docs" or r.startswith("docs/"):
        return True
    if r.startswith(".github/ISSUE_TEMPLATE/") or r.startswith(".github/PULL_REQUEST_TEMPLATE/"):
        return True
    if r in {".github/PULL_REQUEST_TEMPLATE.md", ".github/CODEOWNERS", ".github/SECURITY.md"}:
        return True
    if path.suffix.lower() == ".md":
        return True
    if path.name in NON_FUNCTIONAL_ROOT_NAMES:
        return True
    if path.name.startswith("LICENSE."):
        return True
    if path.name.startswith("CHANGELOG."):
        return True
    return False


def check_functional_root_structure(files: list[Path], errors: list[str]) -> None:
    canonical_functional_root = {"requirements.txt"}
    for entry in ROOT.iterdir():
        if not entry.is_file() or is_non_functional_document(entry):
            continue
        if entry.name not in canonical_functional_root:
            fail(errors, entry, "unexpected functional root-level file")


def check_naming(files: list[Path], errors: list[str]) -> None:
    snake = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)*$")
    for path in files:
        r = rel(path)
        if not (r.startswith("scripts/") or r.startswith("tools/")):
            continue
        if path.suffix not in {".py", ".sh"}:
            continue
        if path.parts[:1] == ("tools",):
            # Java/tooling naming conventions are outside this contract.
            if path.suffix == ".py" and not snake.match(path.name):
                fail(errors, path, "Python filename is not snake_case")
            continue
        if not snake.match(path.name):
            fail(errors, path, "script filename is not snake_case")


def check_forbidden_paths(files: list[Path], errors: list[str]) -> None:
    for path in files:
        if is_non_functional_document(path):
            continue
        r = rel(path)
        parts = path.parts
        if "tests" in parts:
            fail(errors, path, "legacy tests directory is forbidden")
        if any(name in FORBIDDEN_FILENAMES for name in parts):
            fail(errors, path, "obsolete repository artifact is forbidden")
        if path.suffix in {".py", ".sh", ".json", ".yaml", ".yml"} and re.match(
            r"phase[0-9]", path.name, re.IGNORECASE
        ) and not r.startswith("docs/archive/"):
            fail(errors, path, "Phase implementation/configuration file is forbidden")


def check_current_legacy_references(files: list[Path], errors: list[str]) -> None:
    for path in files:
        r = rel(path)
        if is_non_functional_document(path) or r == "scripts/validation/repository_contract.py":
            continue
        if path.suffix.lower() not in {".md", ".py", ".sh", ".json", ".yaml", ".yml", ".txt"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in LEGACY_TEXT_MARKERS:
            if marker in text:
                fail(errors, path, "legacy reference is not allowed outside docs/archive", "absent", marker)
        if re.search(r"\bphase(?:4|5)(?:\.1|\.2b?1?)?\b", text, re.IGNORECASE):
            fail(errors, path, "historical Phase reference is not allowed in current artifacts")


def check_metadata(files: list[Path], errors: list[str]) -> None:
    required = {
        "metadata/release/identity.json",
        "metadata/build/adapter-profiles.json",
        "metadata/platform/adapter-profiles.json",
        "metadata/platform/matrix.json",
        "metadata/signing/android-standard.json",
        "metadata/baselines/build.json",
        "metadata/baselines/legacy-ui.json",
        "metadata/baselines/source-regression.json",
    }
    paths = {rel(p) for p in files}
    for required_path in sorted(required):
        if required_path not in paths:
            fail(errors, ROOT / required_path, "canonical metadata source is missing")
    for obsolete in (
        "metadata/release-identity.json",
        "metadata/build-adapter-profiles.json",
        "metadata/platform-adapter-profiles.json",
        "metadata/platform-matrix.json",
        "metadata/android-signing-identity.json",
        "metadata/yubikey-android-signing-identity.json",
        "metadata/legacy-ui-baseline.json",
        "metadata/source-regression-baseline.json",
    ):
        if obsolete in paths:
            fail(errors, ROOT / obsolete, "duplicate/legacy metadata source remains")


def check_signing_boundary(files: list[Path], errors: list[str]) -> None:
    paths = {rel(p): p for p in files}
    for path, file in paths.items():
        if not path.startswith(".github/workflows/"):
            continue
        if path in SIGNING_WORKFLOWS:
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        markers = SIGNING_MARKERS
        if path == READ_ONLY_SIGNING_PREFLIGHT:
            # Runner labels are required to select the hardware host. Keep the
            # exception narrow: credentials and production signing interfaces
            # remain forbidden in this read-only workflow.
            markers = (
                "YUBIKEY_PIV_PIN",
                "android-production-signing",
                "PKCS#11",
                "pkcs11",
                "YubiKey",
            )
        for marker in markers:
            if marker in text:
                fail(errors, file, "production signing marker leaked into normal workflow", "absent", marker)

    action = paths.get(".github/actions/android-yubikey-sign/action.yml")
    if action:
        text = action.read_text(encoding="utf-8")
        if "YUBIKEY_PIV_PIN" in text:
            fail(errors, action, "production PIN must be bound by workflow, not reusable action")
    else:
        fail(errors, ROOT / ".github/actions/android-yubikey-sign/action.yml", "YubiKey signing action is missing")

    signing_meta = paths.get("metadata/signing/android-standard.json")
    if signing_meta:
        import json
        data = json.loads(signing_meta.read_text(encoding="utf-8"))
        production = data.get("production", {})
        if production.get("certificate_sha256") != "559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5":
            fail(errors, signing_meta, "canonical production certificate fingerprint mismatch")
        if production.get("piv_slot") != "9C" or production.get("pkcs11_id") != "02":
            fail(errors, signing_meta, "canonical production key identity mismatch")


def check_stable_runtime_contract(files: list[Path], errors: list[str]) -> None:
    paths = {rel(p): p for p in files}

    wrapper = paths.get("scripts/build/config_mir.py")
    if wrapper is None:
        fail(errors, ROOT / "scripts/build/config_mir.py", "Stable Android compiler wrapper is missing")
    elif not (wrapper.stat().st_mode & 0o111):
        fail(errors, wrapper, "Stable Android compiler wrapper must be executable", "mode with execute bit", oct(wrapper.stat().st_mode & 0o777))

    windows = paths.get(".github/workflows/build-stable-windows.yml")
    if windows:
        text = windows.read_text(encoding="utf-8")
        if "bytes((0x50,0x45,0,0))" not in text:
            fail(errors, windows, "Stable Windows PE signature check must use explicit NUL bytes")
        if "int.from_bytes(b[off+4:off+6],'little')!=0x8664" not in text:
            fail(errors, windows, "Stable Windows PE machine check must validate AMD64 explicitly")

def check_workflow_syntax(files: list[Path], errors: list[str]) -> None:
    for path in files:
        r = rel(path)
        if not (r.startswith(".github/workflows/") or r.startswith(".github/actions/")):
            continue
        if path.suffix not in {".yml", ".yaml"}:
            continue
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            fail(errors, path, f"YAML parse failed: {exc}")


def main() -> int:
    files = tracked_files()
    errors: list[str] = []

    checks = [
        ("functional root structure", lambda: check_functional_root_structure(files, errors)),
        ("naming convention", lambda: check_naming(files, errors)),
        ("forbidden files", lambda: check_forbidden_paths(files, errors)),
        ("legacy references", lambda: check_current_legacy_references(files, errors)),
        ("metadata uniqueness", lambda: check_metadata(files, errors)),
        ("signing boundary", lambda: check_signing_boundary(files, errors)),
        ("Stable runtime contract", lambda: check_stable_runtime_contract(files, errors)),
        ("workflow YAML", lambda: check_workflow_syntax(files, errors)),
    ]

    print("Repository architecture contract")
    for name, check in checks:
        before = len(errors)
        try:
            check()
        except Exception as exc:
            errors.append(f"{name}: contract execution error: {exc}")
        print(f"[{'FAIL' if len(errors) > before else 'PASS'}] {name}")

    if errors:
        print()
        for item in errors:
            print(f"FAIL: {item}")
        print("RESULT: FAIL")
        return 1

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
