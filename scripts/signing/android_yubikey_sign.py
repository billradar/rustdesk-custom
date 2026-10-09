#!/usr/bin/env python3
import hashlib, json, os, re, shutil, subprocess, zipfile
from pathlib import Path

EXPECTED_FINGERPRINT = "559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5"
EXPECTED_PACKAGE = "com.carriez.flutter_hbb"
ABI_BY_ARCH = {"aarch64": "arm64-v8a", "armv7": "armeabi-v7a", "x86_64": "x86_64"}

def fail(message):
    raise SystemExit(message)

arches = [x.strip() for x in os.environ["ARCHES"].split(",") if x.strip()]
if set(arches) != set(ABI_BY_ARCH):
    fail("SIGNING: expected exactly aarch64, armv7 and x86_64")
if not os.environ.get("YUBIKEY_PIV_PIN"):
    print("ENVIRONMENT PIN AVAILABLE: FAIL")
    raise SystemExit(1)
print("ENVIRONMENT PIN AVAILABLE: PASS")

root = Path(".work/android-input").resolve()
signed_root = Path(".work/signed").resolve()
signed_root.mkdir(parents=True, exist_ok=True)

for arch in arches:
    input_root = (root / arch).resolve()
    manifests = list(input_root.rglob("build-info.json"))
    if len(manifests) != 1:
        fail(f"SIGNING[{arch}]: expected exactly one build manifest")
    bundle = manifests[0].parent.resolve()
    if not bundle.is_relative_to(input_root):
        fail(f"SIGNING[{arch}]: artifact path escaped its root")
    for path in bundle.rglob("*"):
        if path.is_symlink():
            fail(f"SIGNING[{arch}]: symlink in downloaded artifact")

    required = ["SHA256SUMS", "source-manifest.json", "validation/librustdesk.so"]
    if any(not (bundle / name).is_file() for name in required):
        fail(f"SIGNING[{arch}]: incomplete Android build artifact")
    subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=bundle, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    info = json.loads((bundle / "build-info.json").read_text())
    source = json.loads((bundle / "source-manifest.json").read_text())
    expected = {
        "platform": "android", "variant": "standard", "architecture": arch,
        "package_type": "debug-signed-apk",
        "signed_status": "TEST SIGNED / NOT PRODUCTION SIGNED",
        "custom_repository": os.environ["GITHUB_REPOSITORY"],
        "custom_repository_sha": os.environ["GITHUB_SHA"],
        "upstream_sha": os.environ["UPSTREAM_EXPECTED_SHA"],
        "upstream_version": os.environ["UPSTREAM_VERSION"],
        "patchset": os.environ["PATCHSET"],
        "build_run": os.environ["GITHUB_RUN_ID"],
        "workflow_run": os.environ["GITHUB_RUN_ID"],
    }
    for key, value in expected.items():
        if str(info.get(key)) != str(value):
            fail(f"SIGNING[{arch}]: build artifact provenance mismatch: {key}")
    for key in ("upstream_sha", "upstream_version", "patchset", "custom_repository_sha", "variant"):
        if source.get(key) != info.get(key):
            fail(f"SIGNING[{arch}]: prepared source provenance mismatch: {key}")
    if hashlib.sha256((bundle / "source-manifest.json").read_bytes()).hexdigest() != info.get("prepared_source_identity"):
        fail(f"SIGNING[{arch}]: prepared source identity checksum mismatch")
    if str(source.get("prepare_workflow_run")) != str(info.get("prepare_run")):
        fail(f"SIGNING[{arch}]: prepare/source-build run mismatch")
    if str(info.get("prepare_run")) != str(info.get("build_run")):
        fail(f"SIGNING[{arch}]: prepare/build run mismatch")
    if str(info.get("build_run")) != os.environ["GITHUB_RUN_ID"]:
        fail(f"SIGNING[{arch}]: build/current workflow run mismatch")

    packages = list((bundle / "packages").glob("*.apk"))
    if len(packages) != 1:
        fail(f"SIGNING[{arch}]: expected exactly one input APK")
    apk = packages[0].resolve()
    if not apk.is_relative_to(bundle):
        fail(f"SIGNING[{arch}]: APK path escaped artifact bundle")
    if subprocess.run(["apksigner", "verify", "--verbose", str(apk)],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        fail(f"SIGNING[{arch}]: input APK signature verification failed")
    badging = subprocess.run(["aapt", "dump", "badging", str(apk)],
                             check=True, capture_output=True, text=True).stdout
    match = re.search(r"^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']*)'", badging, re.M)
    if not match or match.group(1) != EXPECTED_PACKAGE:
        fail(f"SIGNING[{arch}]: unexpected Android package identity")
    abi = ABI_BY_ARCH[arch]
    with zipfile.ZipFile(apk) as archive:
        native = "lib/" + abi + "/librustdesk.so"
        if native not in archive.namelist() or archive.read(native) != (bundle / "validation/librustdesk.so").read_bytes():
            fail(f"SIGNING[{arch}]: APK ABI does not match validated build output")
    print(f"{arch}: artifact, source, package, ABI and checksum gates: PASS")

    out_dir = Path(os.environ["RUNNER_TEMP"]) / f"rustdesk-yubikey-signing-{arch}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(mode=0o700, parents=True)
    out_apk = out_dir / "signed.apk"
    print(f"Signing {arch} with YubiKey PIV 9C...")
    subprocess.run([
        "/usr/local/bin/rustdesk-sign", "--input", str(apk),
        "--output", str(out_apk), "--pin-source", "env"
    ], check=True, env=os.environ.copy())
    out_apk.chmod(0o600)

    destination = signed_root / arch
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(bundle, destination, symlinks=False)
    packages = destination / "packages"
    for item in packages.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    signed = packages / f"standard-android-{arch}-signed.apk"
    shutil.copy2(out_apk, signed)

    result = subprocess.run(
        ["apksigner", "verify", "--verbose", "--print-certs", str(signed)],
        check=True, capture_output=True, text=True,
    )
    certs = re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})$", result.stdout, re.M)
    if len(certs) != 1 or certs[0].lower() != EXPECTED_FINGERPRINT:
        fail(f"SIGNING[{arch}]: signer certificate fingerprint mismatch")
    schemes = [int(value) for value in re.findall(
        r"^Verified using v([123]) scheme.*: true$", result.stdout, re.M)]
    if not {2, 3}.issubset(set(schemes)):
        fail(f"SIGNING[{arch}]: APK must have both v2 and v3 signatures verified")
    badging = subprocess.run(["aapt", "dump", "badging", str(signed)],
                             check=True, capture_output=True, text=True).stdout
    match = re.search(r"^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']*)'", badging, re.M)
    if not match or match.group(1) != EXPECTED_PACKAGE:
        fail(f"SIGNING[{arch}]: signed APK package identity mismatch")
    with zipfile.ZipFile(signed) as archive:
        native = "lib/" + abi + "/librustdesk.so"
        if native not in archive.namelist() or archive.read(native) != (destination / "validation/librustdesk.so").read_bytes():
            fail(f"SIGNING[{arch}]: signed APK ABI differs from validated build output")

    info = json.loads((destination / "build-info.json").read_text())
    info.update(
        signed=True, signing_identity_verified=True, certificate_sha256=certs[0].lower(),
        package_name=match.group(1), version_code=int(match.group(2)), version_name=match.group(3),
        signing_schemes=schemes, signed_status="PRODUCTION SIGNED / IDENTITY VERIFIED",
        package_type="production-signed-apk", signing_method="yubikey-piv-9c-pkcs11",
        signing_run=os.environ["GITHUB_RUN_ID"],
    )
    (destination / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")
    receipt = {
        "certificate_sha256": certs[0].lower(), "expected_certificate_sha256": EXPECTED_FINGERPRINT,
        "certificate_match": "PASS", "package_name": match.group(1),
        "version_code": int(match.group(2)), "version_name": match.group(3), "abis": [abi],
        "apk_sha256": hashlib.sha256(signed.read_bytes()).hexdigest(),
        "signature_verification": "PASS", "signing_schemes": schemes,
        "signing_method": "yubikey-piv-9c-pkcs11", "piv_slot": "9C", "pkcs11_id": "02",
        "key_algorithm": "EC", "curve": "secp384r1", "workflow_run": os.environ["GITHUB_RUN_ID"],
        "custom_repository_sha": os.environ["GITHUB_SHA"],
    }
    (destination / "android-signing-verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
    rows = []
    for path in sorted(destination.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            rows.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.relative_to(destination).as_posix())
    (destination / "SHA256SUMS").write_text("\n".join(rows) + "\n")
    print(f"{arch}: APK signature, fingerprint, package, ABI and provenance gates: PASS")
