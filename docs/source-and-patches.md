# Upstream source and patchsets

[English](source-and-patches.md) · [简体中文](source-and-patches-zh.md)

## Why use patchsets?

Custom changes live in `patchsets/`, while upstream RustDesk remains a separately fetched source. This identifies the upstream commit, patch generation, and whether the patch contents match the qualification record.

## Source preparation

The implementation lives under `scripts/source/`:

1. Resolve the requested upstream tag or branch to an exact commit SHA.
2. Fetch the ref from official `rustdesk/rustdesk` and verify its resolved SHA against the expected SHA, when supplied.
3. Initialize recursive submodules and compare their commits with the upstream gitlinks.
4. Select a patchset through `scripts/upstream/patchsets.py` and validate its metadata and content hashes.
5. Apply patches to a clean upstream tree and generate a source manifest.
6. Prepare Standard and SOS in separate source trees.
7. Upload prepared source through `prepare-source.yml` for downstream builds.

## Invariants

- The prepared-source destination must be empty; scripts must not silently reset user data.
- The resolved upstream SHA must equal the SHA locked by the caller.
- Submodules must match upstream gitlinks and the source tree must be clean.
- Patchset structure and content must validate. Do not change a patch during a build while retaining its old identity.
- Standard and SOS share the common source identity; variant-specific patches are tracked separately.
- Manifests and artifact identities are generated from actual inputs, never fabricated by hand.

## Changing a patch

1. Identify the target upstream commit and current patchset.
2. Make patch or metadata changes in an isolated working state.
3. Run patchset checks and `python3 scripts/validation/repository_contract.py`.
4. Run compatibility/build CI for the intended upstream commit.
5. Verify source manifests, patch hashes, and artifact identities agree.
6. Merge after PR review; do not rewrite shared branch history.

Revalidate when the upstream SHA, patch content, patchset selection, build adapter, target matrix, or source manifest format changes. Documentation-only edits do not require a full build.

## 1.5.1 source compatibility evidence

The 1.5.1 development snapshot `1297da6d186e58d9096be24072ae3998cdbbf8fe` passed Standard/SOS Rust configuration API compilation, bridge generation, both Flutter analyses, and CI Qualification in [run 40175351746](https://github.com/billradar/rustdesk-custom/actions/runs/40175351746). This does not establish compatibility with a future 1.5.1 tag, native packages, or real remote-session behavior. Patchset v3 is reserved for an actual incompatible upstream API boundary, not a version number alone.

## Rendering policy

Common helpers in v1 and v2 force `allow-always-software-render=N` through `config::OVERWRITE_SETTINGS` after loading client settings. Standard, SOS, and unattended Wayland builds inherit this on all platforms. On Linux, the normal upstream startup path consequently removes `LIBGL_ALWAYS_SOFTWARE`. This policy cannot be re-enabled in these custom builds; other rendering and codec choices retain their existing behavior.

On the tested AX211/Intel+NVIDIA laptop, forced software rendering crashed Mesa when libdrmtap selected the Intel EGL device. Removing the setting allowed EGL 1.5 initialization and a user-confirmed locked-screen session. This is evidence about the previous package only, not new builds. New Common hashes require fresh build and qualification evidence; older results remain historical.
