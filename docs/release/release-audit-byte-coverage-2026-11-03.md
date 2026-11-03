# Release audit byte-coverage clarification — 2026-11-03

This note corrects a potentially misleading interpretation of [release audit #41611975833](https://github.com/billradar/rustdesk-custom/actions/runs/41611975833) and is **not** a production cutover approval.

## Verified by inspecting the implementation on main

The implementation [`scripts/release/audit_release_assets.py`](../../scripts/release/audit_release_assets.py) checks each of the three draft releases for 32 unique assets and downloads each release's `SHA256SUMS` file, hashing those bytes and matching the API asset digest. It compares the 31 listed asset checksums **to GitHub API digest metadata**, but does **not download the other 28 non-APK, non-SHA256SUMS assets per release**. With `--verify-apks`, it downloads and hashes the three signed APKs per release, runs `apksigner verify --verbose --print-certs`, explicitly requires APK v2 and v3 scheme success, and checks the signer certificate SHA-256 against the configured trusted fingerprint.

The protected-main audit log recorded `PASS`, `sums_verified=true` for 3 × 32 assets, and nine APK signature successes. The nine logged APK digests were compared with the current GitHub API metadata and all nine match. This is valid evidence of:
- Three downloaded and hashed `SHA256SUMS` manifests;
- Nine downloaded, hashed, independently verified APKs with v2/v3 signatures and trusted certificate fingerprint;
- Metadata-to-manifest consistency for 93 payload entries.

It is **not** evidence of a full independent byte-level SHA-256 download of all 96 release assets. The 84 non-APK payload files have not been independently re-downloaded and hashed by this audit. Counts: 3 manifests + 9 APKs = **12 independently downloaded/hash-checked assets**; 84 other release assets were metadata-checked against manifests only.

## Remaining NO-GO evidence

1. Obtain and preserve an independent 84-file byte-level audit, or formally approve a narrower asset assurance policy in a separate review.
2. Authenticate self-hosted runner status and external queue/lease quiescence; the available GitHub connector could not read runner inventory.
3. Reconcile live coordinator reservations and explicitly verify v2-only production admission under isolated least-privilege credentials.
4. Repeat live GitHub queue/ref/tag/release checks immediately before a separate reviewed production activation.

Do not change `metadata/release/patchset-cutover.json` from `BLOCKED`, replay historical Identity v1 records, recover owner-deleted runs, or alter signatures/releases/tags.
