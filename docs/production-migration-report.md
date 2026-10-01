# Production migration report — 2026-10-01

Status: MIGRATED / PRODUCTION CONFIGURATION AND ACTIONS VALIDATION PENDING.
Source/Code Migration: COMPLETE. Production Repository Migration acceptance: NOT COMPLETE. Production Build/Release: NOT RUN.

## Baseline

Source: billradar/rustdesk-custom-test, main,
`d40235baa3e414dac3f52c1866c4c563e62b4390`.
Target: https://github.com/billradar/rustdesk-custom . User created an empty public non-fork repository.
Initial production README SHA: `3336a8ddbbd6fecac30a4c81220222acb7751397`.
Frozen patch/core migration SHA: `952c8100a100a1b82fad4b28c218b097d8eae214`.
Production adapter SHA: refer to the immutable commit containing this report.
All copied input files were checked against exact GitHub blob SHA, not local HEAD.
Source metadata: [migration-baseline](../metadata/migration-baseline.json).
Adaptations / unchanged files: [migration-diff](../metadata/migration-diff.json).

## Frozen source / minimal adaptations

v1/v2 patch files, metadata, index and fail-closed Resolver remain byte-identical.
prepare/apply/build-standard/build-sos/build-windows and native toolchain recipe remain unchanged.
Release/package adapters add PRODUCTION provenance, compiled configuration and forbidden-fixture checks.
A verification-helper password assertion now suppresses values on failure; no RustDesk password algorithm or Patch was changed.
New production.py replaces paired test publication with one production Release and first-Dry-Run evidence requirement.
Stable Release checks continue to use official draft/prerelease metadata and exact tag SHA.
Compatibility follows official default branch and has no release/write path; original low-frequency cron retained.

## Configuration

RUSTDESK_ID_SERVER (Variable): NOT VERIFIED (repository configuration read not available).
RUSTDESK_RELAY_SERVER (Variable): NOT VERIFIED (repository configuration read not available).
RUSTDESK_API_SERVER (Variable): NOT VERIFIED (repository configuration read not available).
RUSTDESK_KEY (Variable, public key): NOT VERIFIED (repository configuration read not available).
RUSTDESK_PASSWORD (Secret): NOT VERIFIED (repository configuration read not available).
PRODUCTION_RELEASE_ENABLED (Variable): NOT VERIFIED; keep disabled until Dry Run passes.
No production value or secret was requested from, read from or modified in the old repositories.

## Local verification

22 local unit/regression tests PASS: stable discovery metadata, dedup, force/no-overwrite,
unknown generation fail-closed, immutable v1 hashes/mapping, both variants required,
checksum/PE architecture/runtime-status rejection, production pair/server consistency,
fixture/private-key/token input and payload rejection, ASCII/UTF16 patterns,
no input values printed, wrong repository and missing first Dry Run prevent writes.

Python AST, shell and embedded Bash syntax, YAML parse and full Action SHA pin checks PASS.
This is not an Actions execution or full Windows compilation result.
Production Dry Run Standard: NOT RUN.
Production Dry Run SOS: NOT RUN.
Production Release: NOT CREATED.
Production checksum/architecture/provenance: NOT VALIDATED ON REAL BUILD.
Production Secret Leakage Gate: IMPLEMENTED / NOT VALIDATED ON REAL RUN.

## Provenance and publication gates

Production Gate requires official stable SHA, selected patch generation, successful independent
Standard/SOS builds, Bridge, metadata, full file checksums, AMD64 PE checks and matching source/run/Common/config fingerprints.
Configured server/public-key fingerprint excludes password; fixed password is validated privately at compile time.
First publication requires real successful production Dry Run on same maintenance SHA and upstream/Patch/config fingerprint.
Subsequent stable releases retain same-run gates; scheduler stays disabled until explicit release-enabled Variable.
No complete existing release is overwritten; tag-only/incomplete release also blocks.
Each Release has both ZIPs and per-variant build-info plus archive/metadata SHA256SUMS.

## Security and limitations

Contents write limited to release job; actions read limited to completed-log review and cross-run artifact verification.
No PAT, signing credential or production private key input.
Client preset password remains extractable; Password Security V2 DEFERRED.
Known credential/fixture scanning is heuristic; GitHub already masks known Secrets in downloaded logs.
Masked logs cannot prove that an input was never exposed before redaction; no claim of exhaustive leak absence.
First real run still requires review of visible logs, repository and delivered artifacts.

Runtime/UI: SKIPPED BY USER.
Real remote session: NOT TESTED.
Code signing: NOT ENABLED.
Windows x86_64 only; v2 development full Windows build NOT RUN.
Engine main download / runner / apt dependencies remain floating.

## Phase 3 and safety

Phase 3: FUNCTIONALLY COMPLETE / SCHEDULE OBSERVATION PENDING.
Scheduled execution: CONFIGURED / NOT OBSERVED. Temporary high-frequency cron removed, original retained.
No new schedule PASS was observed during preparation. Production schedules also remain CONFIGURED / NOT OBSERVED.
Old billradar/rustdesk: ZERO WRITES.
Old billradar/rustdesk-sos: ZERO WRITES.
Old/test Releases: UNCHANGED.
Test repository: RETAINED, no Phase 4 writes in this preparation step.
No runtime test, signing, platform addition, archive/deletion or retirement was performed.

## Next execution boundary

The available GitHub connector can read/write repository files and commits but exposes no repository creation,
Actions Variable/Secret configuration or workflow-dispatch operation. No browser fallback was used without approval.
The repository is now initialized and code migration has been performed. Configure the five production inputs
on GitHub, or approve a browser fallback for unsupported connector operations.
Never send the fixed password in chat or put it in Git. Once the initialized repository exists,
file/tree/commit migration can continue via the existing connector, preserving a clean forward history.

## Remote migration verification

Production adapter commit: `0abb885e73be892d390a7f247535732b95909ec3`.
Remote main contains 45 maintenance files; frozen patch/core Git blobs exactly match source baseline.
GitHub registered all three workflows as active:
- release-check.yml: 371959432
- test-build.yml: 371959434
- upstream-compatibility.yml: 371959438

At this verification, production workflow_runs total_count=0 and test schedule total_count=0.
Workflow registration is not compile or Release validation. Production acceptance remains pending.
The next run is release-check with upstream_ref=1.4.9, dry_run=true, force_rebuild=false.
Do not enable production publishing or supply a dry_run_id until that first real run is successful.
