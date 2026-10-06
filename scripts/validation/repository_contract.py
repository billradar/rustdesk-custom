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

ALLOWED_ROOT_FILES = {".gitignore", "README.md", "requirements.txt"}
CURRENT_DOC_DIRS = {
    "architecture", "build", "platform", "release", "signing", "upstream", "archive"
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
}
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


def check_root_and_directories(files: list[Path], errors: list[str]) -> None:
    for entry in ROOT.iterdir():
        if entry.is_file() and entry.name not in ALLOWED_ROOT_FILES:
            fail(errors, entry, "unexpected root-level file")
    docs = ROOT / "docs"
    if not docs.is_dir():
        fail(errors, docs, "docs directory is missing")
        return
    for entry in docs.iterdir():
        if entry.is_file():
            fail(errors, entry, "current docs must be inside a responsibility directory")
        elif entry.name not in CURRENT_DOC_DIRS:
            fail(errors, entry, "unexpected current docs directory")


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
        if r.startswith("docs/archive/"):
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
        for marker in SIGNING_MARKERS:
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
        ("root structure", lambda: check_root_and_directories(files, errors)),
        ("naming convention", lambda: check_naming(files, errors)),
        ("forbidden files", lambda: check_forbidden_paths(files, errors)),
        ("legacy references", lambda: check_current_legacy_references(files, errors)),
        ("documentation layout", lambda: check_root_and_directories(files, errors)),
        ("metadata uniqueness", lambda: check_metadata(files, errors)),
        ("signing boundary", lambda: check_signing_boundary(files, errors)),
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
