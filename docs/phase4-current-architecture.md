# Phase 4 current architecture audit

Audit date: 2026-10-01. Read-only baseline: billradar/rustdesk-custom main
`219b688f8dfeb48015b0b3ac254cce62be6d04c7`.
Validated production dry run: https://github.com/billradar/rustdesk-custom/actions/runs/36854953000
Upstream 1.4.9: `6c578292e8ebbbec708b76986ba8c4bc7c509747`.

## Existing flow and evidence

`release-check.yml` -> `production.py discover` uses official Releases API, excludes drafts/prereleases, resolves tag to exact commit. Numeric official release tags are required. Deduplication checks revision, provenance and uploaded assets; incomplete existing versions fail closed.

`test-build.yml` independently resolves supplied SHA, runs `patchsets.py select`, preflight, bridge, Windows variant matrix, and compatibility aggregation. Known exact SHA mapping is authoritative; other SHAs try candidates in independent clean clones and fail if none satisfy both variant contracts. v1/v2 patches and metadata are hash verified.

`prepare.sh` fetches exact source and recursive official submodules. `apply-patches.sh` checks each patch before applying, including the small hbb_common submodule patch. No vendoring. Common applies to both variants; SOS only to SOS.

Production inputs: repository variables ID/Relay/API; repository secrets KEY/PASSWORD. Compiler environment injects configuration through frozen patches. `verify-source.py` checks contracts using fictional preflight configuration; `production_config.py` checks real inputs without printing them. `native_config_probe.py` queries the built DLL configuration via existing bridge, isolated from normal application startup. This is configuration validation, not UI/remote-session validation.

Windows uses build.py `--portable --flutter --skip-portable-pack --hwcodec --vram`; historical workflow pins Rust 1.75.0, Flutter 3.24.5, LLVM 15.0.6, vcpkg 120deac3062162151622ca4860575a33844ba10b. Bridge uses official Rust 1.75 / Flutter 3.22.3 / cargo-expand 1.0.95 / FRB 1.80.1 recipe. WindowInjection is separately built at ecd8d6a139eee76845ea66423fb739af450fda90. Packaging is an unsigned unpacked Flutter ZIP, not official installer/signing flow.

`package.py` verifies actual compiled configuration, DLL identity and AMD64 PE headers, emits build-info and per-file SHA256SUMS. `release.py collect` validates exactly one artifact per variant and shared source/patch/config/run identities. `production.py assets` scans captured completed job logs for known credential patterns and creates paired ZIPs/global checksums. Pattern scans are not a guarantee against all possible secrets.

## Preserve / refactor

Preserve unchanged v1/v2 patch bytes, resolver semantics, config interface, native configuration probe, actual build.py flags, checksum/architecture/provenance gates. Preserve old build entry as regression reference, not an automatic publication path.

Refactor duplicated upstream clones/patching per platform into prepared source. Split orchestration from shared build. Read reviewed official toolchain profiles at exact source rather than fixed historical dependency pins. Replace warning-only build-file monitoring with fail-closed adapter compatibility for critical definitions. Keep noncritical upstream changes as warnings.

Existing `production.py publish` creates a draft but then patches draft=false: this must be removed. Existing scheduled release-check must not retain an automatic published-release path. Stable becomes draft-only; Nightly artifacts-only. No runtime status upgrades.
