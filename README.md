# RustDesk Custom — Patch Maintenance

This repository maintains reviewed RustDesk patch generations, prepared-source boundaries, platform builds, validation and release orchestration. It is **not** a full RustDesk source fork.

## Architecture

- `.github/workflows/` — CI/CD orchestration and reusable workflow boundaries.
- `scripts/upstream/` — upstream resolution and frozen patch generations.
- `scripts/source/` — exact-source preparation and provenance boundary.
- `scripts/build/` — build adapters and compiler/configuration validation.
- `scripts/platform/` — platform adapters and package validation.
- `scripts/release/` — channels, qualification, aggregation and publication.
- `scripts/signing/` — production signing implementation.
- `scripts/validation/` — fail-closed validation and repository contracts.
- `metadata/` — machine-readable policy, support and signing identity.
- `docs/` — current operational documentation; `docs/archive/` is historical evidence.

See [current architecture](docs/architecture/current.md) and [dependency map](docs/build/dependency-map.md).

## Build and release model

The pipeline is intentionally staged:

**upstream resolution → compatibility/patch selection → prepared source → parallel platform builds → package/provenance validation → aggregate → optional production Android signing → Draft/Release**

Standard and SOS are generated from the same exact upstream source. Provenance binds upstream SHA, patch generation, repository revision, workflow run and variant-specific source identity. Unexpected source/build interfaces fail closed.

Stable and Nightly release workflows consume the same responsibility-based release implementation. Release publication is never an automatic side effect of compatibility testing.

## Android production signing

Android Standard supports ARM64, ARMv7 and x86_64 builds. Production signing is isolated from the normal build workflow.

The Stable signing job requires:

- exact qualified source and build artifacts;
- the dedicated ARM64 signing runner;
- the `android-production-signing` GitHub Environment;
- `YUBIKEY_PIV_PIN` available only at the signing boundary;
- the pinned production certificate identity;
- successful hardware-backed signing and post-sign verification.

The current production certificate fingerprint is recorded in `metadata/yubikey-android-signing-identity.json`. The signing architecture is documented in [docs/signing](docs/signing/architecture.md).

Desktop code signing remains disabled. Android production signing is a separate hardware-backed trust boundary.

## Repository contracts

The legacy `tests/` tree has been retired. Contract tests are now responsibility-based and executable:

```text
scripts/release/production_contract.py
scripts/release/qualification_contract.py
scripts/release/channel_contract.py
scripts/build/config_mir_contract.py
scripts/validation/native_config_contract.py
scripts/signing/android_signing_contract.py
```

The reusable compatibility workflow runs these contracts once, outside the platform matrix, so the same tests are not repeated for every variant.

## Current support

- Windows x86_64: Standard/SOS
- Linux x86_64/ARM64: Standard/SOS
- macOS x86_64/ARM64: Standard/SOS
- Android ARM64/ARMv7/x86_64: Standard
- Windows ARM64 and iOS: planned
- Web: blocked by the audited disabled upstream job
- Android/iOS/Web SOS: unsupported

Platform support is governed by `metadata/platform-matrix.json`; see [platform support](docs/platform/support.md).

## Historical evidence

Phase-based implementation names are retired. Historical Phase 4/5/5.1/5.2B reports, migration reports and hardware-validation evidence are preserved under [docs/archive](docs/archive/) for auditability, but they are not current architecture entry points.

No current workflow should depend on a historical Phase filename.
