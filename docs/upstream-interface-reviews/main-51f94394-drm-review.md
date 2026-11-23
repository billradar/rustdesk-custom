# Upstream main `51f94394`: build adapter and DRM policy review

**Status: HOLD — staging evidence only. Do not approve the new build-adapter signature, merge Stable, or publish.**

## Source identities

- Prior reviewed adapter source: [`6aec3069`](https://github.com/rustdesk/rustdesk/commit/6aec3069aec486ad7df07429a0a1ee411fc8d73a) (1.5.1).
- v4 source with validated Standard/SOS patch application and `hbb_common` Cargo check: [`97245124`](https://github.com/rustdesk/rustdesk/commit/9724512429b053be04cdb843345e99ddcccdb80e) (1.5.3).
- Main compatibility workflow's later source: [`51f94394`](https://github.com/rustdesk/rustdesk/commit/51f94394ce61e1f3d26229565c326b2862cbdd1f) (1.5.3).

Direct GitHub blob comparisons show all of the following identical between `97245124` and `51f94394`: `build.py`, `build.rs`, `.github/workflows/flutter-build.yml`, `.github/workflows/bridge.yml`, `.github/workflows/third-party-RustDeskTempTopMostWindow.yml`, `.github/patches/flutter_3.24.4_dropdown_menu_enableFilter.diff` and `Cargo.toml`. The reviewed adapter's critical signature is therefore the same for both sources; it remains *unapproved*. The source commits are **not** equivalent for other files, so this does not establish patch applicability on the later source.

## Material drift from the reviewed 1.5.1 adapter

Only `build.py` changed among the *adapter's* critical files; the Windows x64 job, declared tools, and other critical files are unchanged. However, its Linux build/packaging semantics changed materially:

1. `--drm` opt-in was replaced with `--no-drm` opt-out. Flutter Linux DEB/pacman targets enable the `drm` and `drm-wake` features by default.
2. Linux's official `Build rustdesk` recipe now explicitly runs `cargo build --features hwcodec,flutter,unix-file-copy-paste,drm,drm-wake` and packages with `python3 ./build.py --flutter --skip-cargo` without `--no-drm`. Appending `--no-drm` to packaging alone would **not** remove DRM features already compiled into the native library.
3. DRM packaging moves from a separately named `rustdesk-unattended-wayland` artifact to ordinary `rustdesk` packaging, with additional recommends/conflicts/replaces metadata. The former package rename and measured glibc floor logic were removed. The Arch Flutter recipe also packages the DRM library.

Our project intentionally distinguishes the ordinary Linux Standard/SOS distribution from its explicitly requested **unattended-wayland** flavor. The latter has its own `scripts/build/linux_wayland.sh`, pinned DRM policy, provenance, package-identity checks, native tests and output naming; it must not be silently collapsed into ordinary packages.

## Fail-closed remediation

- `scripts/platform/platform_adapter.py` now rejects ordinary Linux recipes containing explicit `cargo --features ...drm[,drm-wake]`, an explicit `build.py --drm`, or a `build.py --flutter` call missing `--no-drm` when using the new default-on interface.
- Its regression contract checks the old opt-in default remains usable, the new opt-out default is rejected without explicit disablement, the explicitly disabled stock combination is acceptable when native features are also clean, and explicit DRM compilation is rejected.
- `scripts/build/upstream_51f94394_review.py` and `.github/workflows/staging-upstream-51f94394-build-audit.yml` compare exact upstream snapshots, reproduce adapter identity, verify DRM policy drift, and assert the signature remains outside `metadata/build/adapter-profiles.json`.
- The main CI's build-adapter rejection remains deliberate and unchanged; no signature has been allowlisted and no Stable policy or release path has been changed.

## Missing admission evidence

A separate, explicit, reviewed adaptation of the source-specific Linux build recipe is required, with both native build features and the packaging flag aligned. Ordinary DEB/RPM/Arch packaging, the unattended-wayland build, generated bridge/API/Flutter compatibility, and cross-platform tests must be independently validated on the later upstream SHA before any release approval. The staging workflow is **diagnostic only**: passing it does not grant general build or Stable eligibility.

## Latest-source candidate Patch Profile routing

The dedicated [CI-only source probe](https://github.com/billradar/rustdesk-custom/actions/runs/45180782944) passed all v4 Standard/SOS patches and the isolated native helper/configuration validation against `51f94394`. This is sufficient to register an explicit **candidate-only** v4 Patch Profile for that exact SHA. It does **not** approve the default-on DRM build adapter, release qualification, runtime compatibility, or Stable. The production patch application gate now independently verifies the exact source SHA and v4 hashes for both `97245124` and `51f94394`.
