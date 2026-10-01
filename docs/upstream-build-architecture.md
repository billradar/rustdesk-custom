# Official RustDesk build architecture audit

Read snapshots: stable 1.4.9 `6c578292e8ebbbec708b76986ba8c4bc7c509747`; default master `fada664df7a294d1d1a9ca3e7cd3637069122f17` (2026-10-01).
Source links: https://github.com/rustdesk/rustdesk/tree/fada664df7a294d1d1a9ca3e7cd3637069122f17/.github/workflows

`flutter-ci.yml`: PR, master push and manual; path exclusions; calls flutter-build without release upload.
`flutter-tag.yml`: version tag push and manual; calls flutter-build with upload/tag.
`flutter-nightly.yml`: midnight UTC and manual; calls flutter-build targeting nightly release. Our Nightly deliberately differs: 02:00 UTC, artifacts only.
`flutter-build.yml`: workflow_call; bridge/helper jobs, explicit platform matrices, package/upload/signing logic. GitHub requires reusable workflow references known in workflow YAML: a workflow checked out dynamically at an upstream SHA cannot be executed as a local reusable workflow. Calling official workflow directly would also checkout unpatched official source and inherit official release assumptions. Therefore use a reviewed build adapter, reading definitions from the exact source and rejecting unknown critical profiles.

## Toolchains and migration

| Setting | 1.4.9 | audited development |
|---|---|---|
| Rust desktop / macOS | 1.75 / 1.81 | same |
| Flutter desktop / Android | 3.24.5 | same |
| Flutter Windows ARM | 3.44.0 | 3.44.9 |
| LLVM | 15.0.6 | same |
| vcpkg | 120deac3062162151622ca4860575a33844ba10b | 9e593bb18ea69cc5095e012465dcd675a822ed0d |
| vcpkg CMake | prior recipe | 4.3.0 |
| NDK / cargo-ndk | r28c / 3.1.2 | same |
| source version | 1.4.9 | 1.5.0 |

Bridge uses Rust 1.75, cargo-expand 1.0.95, FRB 1.80.1. The default bridge generation profile uses Flutter 3.22.3 and extended_text resolution adjustment; newer ARM bridge profile uses separate newer Flutter. Only the audited x64 default profile is enabled in our build adapter.

## Official matrices (not custom validation)

Windows Flutter: x86_64/windows-2022 and aarch64/windows-11-arm; Sciter also i686.
macOS Flutter: Intel macos-15-intel, Apple Silicon macos-14.
Linux Flutter: x86_64 Ubuntu 22.04 and aarch64 Ubuntu 22.04 ARM, older distribution packaging; AppImage/Flatpak and Sciter jobs also exist. Development adds Linux DRM.
Android: aarch64, armv7, x86_64 on Ubuntu 24.04, plus universal package.
iOS: aarch64-apple-ios on macos-latest. Web: Ubuntu 22.04.
These are upstream-supported targets; custom builds remain unvalidated outside Windows x64.

## Dependencies and packaging

WindowInjection helper is pinned to ecd8d6a139eee76845ea66423fb739af450fda90 and architecture-specific. Windows engine downloads use floating rustdesk/engine main release; record hash, do not claim bitwise reproducibility. Official SDK dropdown patch comes from exact source. Native dependencies use exact source vcpkg manifest and overlay scripts. Official packaging includes portable wrappers/installers/signing paths beyond our unsigned ZIP scope.

Development adds generate-sbom using Syft against source. An official unpatched source SBOM is not a custom artifact SBOM. Custom SBOM must describe prepared patched source or actual packaged output; do not label unimplemented custom SBOM as PASS.

Critical adapter profiles must cover official Windows job, bridge/helper workflow, build.py/build.rs, SDK patch and relevant global toolchain values. Changed unsupported critical profile fails before costly build. Other platform changes are monitored but do not imply custom support.
