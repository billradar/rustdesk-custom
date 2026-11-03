"""Read-only GitHub release asset verification. No publishing or signing capability."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

REPO = "billradar/rustdesk-custom"
RELEASE_IDS = (432254527, 431170313, 430489827)
HEX = re.compile(r"^[0-9a-f]{64}$")
MAX_BYTES = 150 * 1024 * 1024

def request(url, accept="application/vnd.github+json"):
    token = os.environ.get("RELEASE_AUDIT_TOKEN", "")
    if not token:
        raise RuntimeError("RELEASE_AUDIT_TOKEN is required for private draft releases")
    headers = {"Accept": accept, "User-Agent": "rustdesk-release-asset-audit", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        return urlopen(Request(url, headers=headers), timeout=90)
    except HTTPError as error:
        # Never log credentials, request headers, or response bodies.
        accepted = error.headers.get("X-Accepted-GitHub-Permissions", "not supplied")
        request_id = error.headers.get("X-GitHub-Request-Id", "not supplied")
        endpoint = url.split("api.github.com/repos/" + REPO, 1)[-1]
        raise RuntimeError(
            f"GitHub API denied {endpoint}: HTTP {error.code}; "
            f"accepted_permissions={accepted}; request_id={request_id}"
        ) from None

def api(path):
    with request("https://api.github.com/repos/" + REPO + path) as r:
        return json.load(r)

def download(asset, dest):
    if not (0 < asset["size"] <= MAX_BYTES):
        raise ValueError("Asset exceeds size limit: " + asset["name"])
    url = "https://api.github.com/repos/" + REPO + "/releases/assets/" + str(asset["id"])
    digest = hashlib.sha256()
    size = 0
    with request(url, "application/octet-stream") as response, dest.open("wb") as output:
        if "json" in response.headers.get("Content-Type", "").lower():
            raise ValueError("GitHub returned JSON instead of asset bytes: " + asset["name"])
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES or size > asset["size"]:
                raise ValueError("Asset download exceeded declared size")
            digest.update(chunk)
            output.write(chunk)
    actual = "sha256:" + digest.hexdigest()
    if size != asset["size"] or actual != asset.get("digest"):
        raise ValueError("Asset size or digest mismatch: " + asset["name"])
    return digest.hexdigest()

def sums_parse(data):
    result = {}
    for line in data.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64}) ([ *])(.+)", line)
        if not match:
            raise ValueError("Malformed SHA256SUMS entry")
        name = match.group(3)
        if "/" in name or "\\" in name or name in result:
            raise ValueError("Unsafe or duplicate checksum filename")
        result[name] = match.group(1).lower()
    return result

def signer_digests(output):
    digests = re.findall(r"^\s*(?:(?:V[123](?:\.\d+)?\s+)?Signer(?:\s+#\d+)?):?\s+certificate SHA-256 digest: ([0-9a-fA-F]{64})\s*$", output, flags=re.MULTILINE | re.IGNORECASE)
    if not digests:
        raise ValueError("APK signer certificate SHA-256 digest missing")
    return [digest.lower() for digest in digests]

def verify_signer_identity(digests, expected):
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError("Trusted APK signer SHA-256 fingerprint must be 64 hex characters")
    if len(digests) != 1 or digests[0].lower() != expected.lower():
        raise ValueError("APK signing certificate differs from trusted production identity")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-apks", action="store_true")
    parser.add_argument("--verify-all-bytes", action="store_true", help="Download and hash every release asset, not only APKs and SHA256SUMS")
    args = parser.parse_args()
    trusted_signer = os.environ.get("RELEASE_AUDIT_TRUSTED_SIGNER_SHA256", "").strip()
    if args.verify_apks and not trusted_signer:
        raise RuntimeError("RELEASE_AUDIT_TRUSTED_SIGNER_SHA256 must be independently verified and configured")
    result = []
    baseline = api("")
    print("GitHub App repository access: OK (" + baseline["full_name"] + ")", flush=True)
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        for release_id in RELEASE_IDS:
            release = api("/releases/" + str(release_id))
            assets = api("/releases/" + str(release_id) + "/assets?per_page=100")
            names = [a["name"] for a in assets]
            if len(assets) != 32 or len(set(names)) != 32:
                raise ValueError("Release asset inventory changed; manual review required")
            checks = next((a for a in assets if a["name"] == "SHA256SUMS"), None)
            if checks is None:
                raise ValueError("SHA256SUMS missing")
            sums_path = folder / ("SHA256SUMS-" + str(release_id))
            download(checks, sums_path)
            checksums = sums_parse(sums_path.read_text())
            expected = {a["name"] for a in assets if a["name"] != "SHA256SUMS"}
            if set(checksums) != expected:
                raise ValueError("SHA256SUMS missing/extra assets")
            for asset in assets:
                if asset["name"] == "SHA256SUMS":
                    continue
                digest = asset.get("digest", "")
                if not digest.startswith("sha256:") or not HEX.fullmatch(digest[7:]):
                    raise ValueError("Missing GitHub asset digest: " + asset["name"])
                if checksums[asset["name"]] != digest[7:]:
                    raise ValueError("SHA256SUMS and GitHub digest disagree: " + asset["name"])
            apk_names = [a for a in assets if a["name"].endswith("-signed.apk")]
            if len(apk_names) != 3:
                raise ValueError("Expected three Android APKs")
            byte_verified = 1  # SHA256SUMS itself was downloaded and hashed.
            verified = []
            if args.verify_apks:
                for asset in apk_names:
                    path = folder / asset["name"]
                    download(asset, path)
                    command = ["apksigner", "verify", "--verbose", "--print-certs", str(path)]
                    proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
                    if proc.returncode:
                        raise ValueError("APK signature verification failed: " + asset["name"] + "\n" + proc.stderr[-1000:])
                    if "Verified using v2 scheme (APK Signature Scheme v2): true" not in proc.stdout or "Verified using v3 scheme (APK Signature Scheme v3): true" not in proc.stdout:
                        raise ValueError("APK v2/v3 signature missing: " + asset["name"])
                    digests = signer_digests(proc.stdout)
                    verify_signer_identity(digests, trusted_signer)
                    verified.append({"name": asset["name"], "sha256": asset["digest"], "signer_sha256": digests})
                    path.unlink()
                    byte_verified += 1
            if args.verify_all_bytes:
                # A successful result requires a fresh byte-level digest for every
                # asset. Never infer byte verification from GitHub metadata alone.
                already_checked = {a["name"] for a in apk_names} if args.verify_apks else set()
                for asset in assets:
                    if asset["name"] == "SHA256SUMS" or asset["name"] in already_checked:
                        continue
                    path = folder / ("payload-" + str(release_id))
                    actual = download(asset, path)
                    if checksums[asset["name"]] != actual:
                        raise ValueError("Downloaded asset differs from SHA256SUMS: " + asset["name"])
                    path.unlink()
                    byte_verified += 1
                if byte_verified != len(assets):
                    raise ValueError("Incomplete byte-level verification")
            result.append({"release_id": release_id, "release_name": release["name"], "asset_count": len(assets), "sums_verified": True, "byte_verified_count": byte_verified, "full_byte_verification": bool(args.verify_all_bytes), "apk_signatures_verified": verified})
    print(json.dumps({"status": "PASS", "scope": "GitHub metadata and SHA256SUMS; optional full asset byte hashing and APK v2/v3 validation", "releases": result}, indent=2))

if __name__ == "__main__":
    main()
