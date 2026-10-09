# RustDesk Custom

English · [中文](README.zh-CN.md)

[![Stable Release Pipeline](https://github.com/billradar/rustdesk-custom/actions/workflows/tag.yml/badge.svg)](https://github.com/billradar/rustdesk-custom/actions/workflows/tag.yml)
[![Nightly - Development artifacts](https://github.com/billradar/rustdesk-custom/actions/workflows/nightly.yml/badge.svg)](https://github.com/billradar/rustdesk-custom/actions/workflows/nightly.yml)
[![CI - Patch and Build compatibility](https://github.com/billradar/rustdesk-custom/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/billradar/rustdesk-custom/actions/workflows/ci.yml)

RustDesk Custom is a maintained RustDesk distribution built from upstream RustDesk with a reviewed set of custom patches.

The repository provides the build, validation, packaging, signing, and release automation needed to maintain those changes without keeping a separate full copy of the upstream source tree.

## What this project does

- Maintains reviewed RustDesk patchsets.
- Resolves and records the exact upstream revision used for a build.
- Builds Standard and SOS variants for supported platforms.
- Validates packages, architectures, checksums, configuration, and provenance.
- Produces machine-readable build and release metadata.
- Keeps production Android signing separate from normal CI.
- Automates qualification and Stable release workflows.

The repository is a **maintenance and release repository**, not a full RustDesk source fork.

## Supported platforms

| Platform | Architecture | Standard | SOS |
| --- | --- | :---: | :---: |
| Windows | x86_64 | ✓ | ✓ |
| Linux | x86_64 | ✓ | ✓ |
| Linux | ARM64 | ✓ | ✓ |
| macOS | x86_64 | ✓ | ✓ |
| macOS | ARM64 | ✓ | ✓ |
| Android | ARM64 | ✓ | — |
| Android | ARMv7 | ✓ | — |
| Android | x86_64 | ✓ | — |

Windows ARM64 and iOS are planned. Web is currently blocked by the reviewed upstream build definition.

The authoritative platform matrix is [metadata/platform/matrix.json](metadata/platform/matrix.json).

## How it works

The normal build and release flow is:

~~~text
Upstream
   ↓
Patch selection
   ↓
Prepared source
   ↓
Platform builds
   ↓
Package & provenance validation
   ↓
Artifact aggregation
   ↓
Optional Android production signing
   ↓
Qualification
   ↓
Stable release
~~~

Each stage has a separate responsibility. Building an artifact does not automatically publish a release, and production Android signing is not part of ordinary CI.

## Repository structure

~~~text
.github/
├── actions/              Reusable GitHub Actions
└── workflows/            CI/CD workflows

metadata/
├── baselines/            Known upstream/build baselines
├── build/                Build adapter metadata
├── platform/             Platform support matrix and profiles
├── release/              Release identity and metadata
├── signing/              Signing identity metadata
└── upstream/             Upstream metadata

patchsets/                Reviewed custom patch generations

scripts/
├── build/                Build and compiler/configuration logic
├── platform/             Platform-specific build/package logic
├── release/              Release, channel, and qualification logic
├── signing/              Production signing logic
├── source/               Prepared-source handling
├── upstream/             Upstream resolution and patch selection
└── validation/           Repository and domain validation

docs/                    Implementation principles and operating procedures

tools/                    Development and maintenance utilities
requirements.txt          Python dependencies
README.md                 Project overview
~~~

For detailed architecture information, see [docs/README.md](docs/README.md).

## Requirements

Repository-level tooling currently requires:

- Python 3
- Git
- GitHub Actions for hosted CI workflows
- Platform-specific RustDesk, Flutter, and native build dependencies for local builds

Install the repository Python dependencies with:

~~~bash
python3 -m pip install -r requirements.txt
~~~

## Development

Clone the repository and work from the development branch:

~~~bash
git clone https://github.com/billradar/rustdesk-custom.git
cd rustdesk-custom
git checkout test/development
~~~

Before making a larger change, run the repository contract:

~~~bash
python3 scripts/validation/repository_contract.py
~~~

The validation scripts are designed to fail closed when repository structure, release metadata, platform definitions, or signing boundaries do not satisfy their contracts.

## CI

The main CI workflow validates a specific custom revision against an upstream RustDesk revision.

For a Stable build, the CI qualification must be generated for:

- the exact custom commit that will be released;
- the exact Stable upstream version;
- the corresponding upstream commit;
- the current reviewed patchset.

This qualification is later consumed by the Stable Release Pipeline.

### Manual Stable qualification

When dispatching the CI workflow manually:

1. Set **Stable upstream version** to the desired upstream version, for example 1.5.0.
2. Leave **Force rebuild** disabled unless a rebuild is specifically required.
3. Leave **Run Stable CD dry-run after qualification** disabled unless the release pipeline itself is being tested.
4. Wait for CI qualification to complete successfully.
5. Run the Stable Release Pipeline for the same custom revision.

A successful build alone is not a Stable qualification. The custom commit and upstream revision must match exactly.

## Release

The Stable release workflow is intentionally gated.

A Stable release proceeds only after the exact custom revision has a successful CI qualification for the requested upstream Stable version.

The release flow is roughly:

~~~text
Qualified CI result
       ↓
Stable preflight
       ↓
Platform artifact builds
       ↓
Artifact validation
       ↓
Android production signing (when authorized)
       ↓
Release aggregation
       ↓
Draft / publish
~~~

Release automation does not silently replace or overwrite an existing revision's artifacts.

## Android production signing

Android Standard production signing is isolated from ordinary CI.

Production signing requires:

- explicit authorization;
- the dedicated signing runner;
- the android-production-signing GitHub Environment;
- the protected YUBIKEY_PIV_PIN secret;
- the configured hardware-backed signing identity;
- post-signing certificate, package, ABI, and provenance verification.

Normal CI does **not** need access to the production signing environment, YubiKey, PKCS#11 credentials, or production PIN.

The canonical Android signing metadata is [metadata/signing/android-standard.json](metadata/signing/android-standard.json).

For implementation details and operational steps, see [the documentation index](docs/README.md), especially [Android production signing](docs/android-production-signing.md).

## Validation and contracts

The repository uses executable contracts to keep important boundaries explicit.

The repository-wide contract is:

~~~bash
python3 scripts/validation/repository_contract.py
~~~

Other contracts cover areas such as:

~~~text
scripts/release/production_contract.py
scripts/release/qualification_contract.py
scripts/release/channel_contract.py
scripts/build/config_mir_contract.py
scripts/validation/native_config_contract.py
scripts/signing/android_signing_contract.py
~~~

Run the contracts relevant to an area when changing that area.

## Documentation

Start at [docs/README.md](docs/README.md). The documentation is organized around implementation principles, source and patch handling, build validation, workflow/release operations, Android production signing, and troubleshooting.

## Upstream

This project is based on the upstream RustDesk project:

- Upstream repository: https://github.com/rustdesk/rustdesk
- Upstream project website: https://rustdesk.com/

Custom changes are maintained as reviewed patchsets rather than by continuously copying the complete upstream repository into this repository.

## Security

Security-sensitive operations are deliberately separated from normal development and CI.

In particular:

- Production signing credentials are not stored in the repository.
- Production signing is not performed by ordinary build jobs.
- Signing requires explicit workflow authorization.
- Release artifacts are validated before publication.
- Repository and signing contracts are checked automatically.

If you find a security issue, avoid publishing credentials, signing material, or other sensitive information in a public issue. Use the project's private security reporting process where available.

## License

RustDesk Custom contains maintenance and automation code for RustDesk. RustDesk itself is licensed under its upstream project's license.

Please refer to the upstream RustDesk repository and the applicable files in this repository for the exact licensing terms of each component.
