#!/usr/bin/env python3
"""Create and validate a non-APK fixture for Phase 5.2A workflow dry runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path


EXPECTED_PACKAGE = "com.carriez.flutter_hbb"
EXPECTED_ARCH = "aarch64"
FIXTURE_NAME = "input.apk.fixture"
FIXTURE_BYTES = b"MOCK ONLY: this is not an Android APK and cannot be installed.\n"
EXPECTED_MOCK_OPERATIONS = 2


class GateError(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_fixture(root: Path, repository: str, ref: str, commit: str, run_id: str) -> None:
    if root.exists():
        raise GateError("output already exists")
    if not repository or not ref or not commit or not run_id:
        raise GateError("incomplete build provenance")
    root.mkdir(parents=True)
    payload = root / FIXTURE_NAME
    payload.write_bytes(FIXTURE_BYTES)
    info = {
        "artifact_class": "MOCK_FIXTURE_NOT_APK",
        "repository": repository,
        "ref": ref,
        "commit": commit,
        "run_id": str(run_id),
        "platform": "android",
        "variant": "standard",
        "architecture": EXPECTED_ARCH,
        "package_name": EXPECTED_PACKAGE,
        "input_name": FIXTURE_NAME,
        "input_sha256": sha256(FIXTURE_BYTES),
    }
    (root / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")


def validate_fixture(root: Path, repository: str, ref: str, commit: str, run_id: str) -> dict:
    try:
        info = json.loads((root / "build-info.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError("missing or invalid fixture manifest") from exc
    expected = {
        "artifact_class": "MOCK_FIXTURE_NOT_APK",
        "repository": repository,
        "ref": ref,
        "commit": commit,
        "run_id": str(run_id),
        "platform": "android",
        "variant": "standard",
        "architecture": EXPECTED_ARCH,
        "package_name": EXPECTED_PACKAGE,
        "input_name": FIXTURE_NAME,
    }
    for key, value in expected.items():
        if info.get(key) != value:
            raise GateError(f"artifact provenance/metadata mismatch: {key}")
    payload = root / FIXTURE_NAME
    if not payload.is_file() or payload.is_symlink():
        raise GateError("expected one regular mock fixture")
    if sha256(payload.read_bytes()) != info.get("input_sha256"):
        raise GateError("fixture checksum mismatch")
    files = {p.name for p in root.iterdir()}
    if files != {"build-info.json", FIXTURE_NAME}:
        raise GateError("unexpected artifact contents")
    return info


def simulate(root: Path, output: Path, repository: str, ref: str, commit: str, run_id: str) -> None:
    info = validate_fixture(root, repository, ref, commit, run_id)
    if output.exists():
        raise GateError("refusing to overwrite simulation output")
    output.mkdir(parents=True)
    original = (root / FIXTURE_NAME).read_bytes()
    simulated = output / "output.apk.fixture"
    shutil.copyfile(root / FIXTURE_NAME, simulated)
    receipt = {
        "mode": "MOCK_ONLY",
        "real_pkcs11_module_loaded": False,
        "pin_used": False,
        "private_key_operation": False,
        "release_created": False,
        "input_sha256": info["input_sha256"],
        "input_unchanged": sha256((root / FIXTURE_NAME).read_bytes()) == info["input_sha256"],
        "expected_mock_signature_operations": EXPECTED_MOCK_OPERATIONS,
        "actual_mock_signature_operations": EXPECTED_MOCK_OPERATIONS,
        "output_verification_simulation": "PASS",
        "output_sha256": sha256(simulated.read_bytes()),
    }
    (output / "dry-run-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    validate_receipt(output)
    if (root / FIXTURE_NAME).read_bytes() != original:
        raise GateError("input fixture changed")


def validate_receipt(output: Path) -> dict:
    try:
        receipt = json.loads((output / "dry-run-receipt.json").read_text())
        payload = (output / "output.apk.fixture").read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError("missing or invalid mock receipt/output") from exc
    required = {
        "mode": "MOCK_ONLY",
        "real_pkcs11_module_loaded": False,
        "pin_used": False,
        "private_key_operation": False,
        "release_created": False,
        "input_unchanged": True,
        "expected_mock_signature_operations": EXPECTED_MOCK_OPERATIONS,
        "actual_mock_signature_operations": EXPECTED_MOCK_OPERATIONS,
        "output_verification_simulation": "PASS",
    }
    for key, value in required.items():
        if receipt.get(key) != value:
            raise GateError(f"mock result gate failed: {key}")
    if receipt.get("output_sha256") != sha256(payload):
        raise GateError("mock output checksum mismatch")
    if receipt.get("output_sha256") != receipt.get("input_sha256"):
        raise GateError("mock output verification simulation failed")
    if {p.name for p in output.iterdir()} != {"dry-run-receipt.json", "output.apk.fixture"}:
        raise GateError("unexpected simulation output contents")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--root", type=Path, required=True)
    simulate_cmd = sub.add_parser("simulate")
    simulate_cmd.add_argument("--root", type=Path, required=True)
    simulate_cmd.add_argument("--output", type=Path, required=True)
    validate_input = sub.add_parser("validate-input")
    validate_input.add_argument("--root", type=Path, required=True)
    validate_cmd = sub.add_parser("validate-output")
    validate_cmd.add_argument("--output", type=Path, required=True)
    for command in (build, simulate_cmd, validate_input):
        command.add_argument("--repository", required=True)
        command.add_argument("--ref", required=True)
        command.add_argument("--commit", required=True)
        command.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build_fixture(args.root, args.repository, args.ref, args.commit, args.run_id)
            print("MOCK ARTIFACT BUILD: PASS (fixture is not an APK)")
        elif args.command == "validate-input":
            validate_fixture(args.root, args.repository, args.ref, args.commit, args.run_id)
            print("PROVENANCE / PACKAGE / ARCHITECTURE / CHECKSUM GATES: PASS")
        elif args.command == "simulate":
            simulate(args.root, args.output, args.repository, args.ref, args.commit, args.run_id)
            print("MOCK SIGNING / OPERATION COUNT / OUTPUT VERIFICATION SIMULATION: PASS")
        else:
            receipt = validate_receipt(args.output)
            print("MOCK RECEIPT: PASS")
            print(f"MOCK SIGNATURE OPERATIONS: {receipt['actual_mock_signature_operations']}")
            print("REAL YUBIKEY OPERATION: NO")
        return 0
    except GateError as exc:
        print(f"DRY-RUN GATE: FAIL ({exc})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
