# Current repository architecture

This repository is a maintenance and release system for RustDesk patch generations. It is not a full RustDesk source fork.

## Repository boundaries

```
.github/workflows/       CI/CD orchestration
.github/actions/         reusable action implementations
scripts/build/           build and compiler/config logic
scripts/platform/        platform adapters and packaging
scripts/release/         release, channel and qualification logic
scripts/signing/         production signing logic
scripts/source/          prepared-source boundary
scripts/upstream/        upstream resolution and frozen patchsets
scripts/validation/      fail-closed validation and contracts
metadata/                machine-readable policy and identity
patchsets/               reviewed patch generations
docs/                    current architecture and operations
docs/archive/            historical evidence
```

## Naming policy

Production implementation files use responsibility-based names. Phase numbers are historical metadata, not implementation names.

Contract files end in `_contract.py` and are executable repository invariants. They validate architecture, workflow security, release policy and build/signing boundaries.

The old `tests/` tree has been retired. Contract tests live beside the responsibility they protect and are executed by the reusable compatibility workflow.

## Release flow

Upstream resolution -> compatibility/patch selection -> prepared source -> platform builds -> package/provenance validation -> aggregate -> optional Android production signing -> Draft/Release.

Stable Android production signing is isolated to the dedicated YubiKey runner and GitHub Environment. The normal build workflow never owns the production signer.

## Source of truth

- Platform support: `metadata/platform-matrix.json`
- Reviewed build interfaces: `metadata/build-adapter-profiles.json`
- Android signing identity: `metadata/yubikey-android-signing-identity.json`
- Release qualification implementation: `scripts/release/qualification.py`
- Current signing architecture: `docs/signing/`

Historical Phase reports and migration evidence live under `docs/archive/` and are not part of the current operational contract.
