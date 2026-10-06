# RustDesk Custom — Patch Maintenance

RustDesk Custom is a reviewed maintenance and release system for RustDesk patch generations. It is **not** a full RustDesk source fork.

## Architecture

- `.github/workflows/` — CI/CD lifecycle orchestration and reusable workflow boundaries.
- `.github/actions/` — reusable action implementations.
- `scripts/source/` — exact-source preparation and provenance boundary.
- `scripts/upstream/` — upstream resolution and frozen patchset selection.
- `scripts/build/` — build adapters and compiler/configuration validation.
- `scripts/platform/` — platform adapters and package validation.
- `scripts/release/` — channel discovery, qualification, aggregation and publication.
- `scripts/signing/` — production signing implementation and identity gates.
- `scripts/validation/` — repository-wide and domain-specific fail-closed contracts.
- `metadata/` — canonical machine-readable policy, platform, release and signing data.
- `patchsets/` — reviewed patch generations.
- `docs/` — current engineering and operations documentation.
- `docs/archive/` — historical evidence retained for auditability.

See [current architecture](docs/architecture/current.md) and [build dependency map](docs/build/dependency-map.md).

## Build and release flow

**upstream resolution → compatibility and patch selection → prepared source → platform builds → package/provenance validation → aggregate → optional Android production signing → draft/release**

Build does not own release publication. Release does not own production signing. Production signing consumes already-qualified build artifacts and independently verifies package, ABI, certificate and provenance identity.

## Android production signing

Android Standard supports ARM64, ARMv7 and x86_64 build targets. Production signing is a separate trust boundary.

The signing path requires:

- an explicitly authorized production-signing workflow;
- the dedicated ARM64 YubiKey runner;
- the `android-production-signing` GitHub Environment;
- `YUBIKEY_PIV_PIN` bound only at the signing job boundary;
- the canonical production certificate identity;
- post-signature certificate, package, ABI and provenance verification.

The single canonical Android identity source is `metadata/signing/android-standard.json`. It records both the legacy public signing identity and the current hardware-backed production identity without treating them as the same certificate.

## Repository validation

Run:

`python3 scripts/validation/repository_contract.py`

Domain-specific contracts remain responsible for their own invariants:

```text
scripts/release/production_contract.py
scripts/release/qualification_contract.py
scripts/release/channel_contract.py
scripts/build/config_mir_contract.py
scripts/validation/native_config_contract.py
scripts/signing/android_signing_contract.py
```

## Current support

- Windows x86_64: Standard/SOS
- Linux x86_64/ARM64: Standard/SOS
- macOS x86_64/ARM64: Standard/SOS
- Android ARM64/ARMv7/x86_64: Standard
- Windows ARM64 and iOS: planned
- Web: blocked by the audited upstream definition
- Android/iOS/Web SOS: unsupported

Machine-readable platform authority is `metadata/platform/matrix.json`; reviewed platform adapter profiles live under `metadata/platform/`.

## Development

Install the reviewed Python dependency set from `requirements.txt`. Run repository and domain contracts before expensive builds. Shell scripts use responsibility-based snake_case names.

Historical migration, acceptance and signing evidence is retained under `docs/archive/`. Historical material is evidence only and is not part of the current operational architecture.
