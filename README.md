# RustDesk Custom — Patch Maintenance

This repository maintains reviewed RustDesk patch generations and build orchestration, not a full RustDesk source fork.

Standard = official exact SHA + Common. SOS = same exact SHA + Common + SOS.
SOS retains the historical simplified desktop UI and settings restrictions; it does not disable native controller functionality.

## Channels and shared core

- `ci.yml`: PR, main push, manual. Resolve official ref once; reusable patch/API and build compatibility checks. No production secrets or release writes.
- `tag.yml`: official stable Release discovery (05:41/17:41 UTC), manual. Exact SHA -> compatibility -> prepared sources -> shared build -> paired validation -> **Draft only**. Publication is a manual user decision.
- `nightly.yml`: official default development branch, daily **02:00 UTC**, manual. Same core; version read from that exact source's Cargo.toml. Only Actions artifacts, named with version/SHA/variant/platform.
- `compat-check.yml`, `prepare-source.yml`, `build.yml`: reusable cores. Windows consumers do not resolve upstream or apply patches again.

Legacy `release-check.yml` is artifact-only and manual; original `test-build.yml` remains a Phase 3 regression reference. Neither retains automatic published-release behavior.

## Patch generations and build interface

v1 preserves validated 1.4.9 SHA `6c578292e8ebbbec708b76986ba8c4bc7c509747`. v2 targets the newer configuration API. Their patch bytes remain frozen. Known exact mappings take priority; other SHAs require successful clean candidate probes. No compatible generation means STOP.

`build_adapter.py` reads critical official Windows/Bridge/helper/toolchain definitions from the target source. Only reviewed signatures in `metadata/build-adapter-profiles.json` are accepted. Unknown critical changes fail before native dependency builds. Noncritical changes remain warnings. This is intentionally conservative: a changed critical official profile must be reviewed in staging before promotion.

Prepared Standard/SOS source artifacts include recursive official submodules, generated Bridge and file inventories. They contain no production configuration. Hash-verified archives and source-manifest bind upstream version/SHA, patchset/hashes, repository commit and prepare run. Platform jobs verify before consuming; caches are optional acceleration, never source provenance.

## Configuration

Settings -> Secrets and variables -> Actions:

| Kind | Name |
|---|---|
| Variable | RUSTDESK_ID_SERVER |
| Optional Variable | RUSTDESK_RELAY_SERVER |
| Variable | RUSTDESK_API_SERVER |
| Secret | RUSTDESK_KEY |
| Secret | RUSTDESK_PASSWORD |

These preserve the validated Phase 3 interface. Empty Relay preserves upstream discovery. API must be HTTPS without credentials; server key is a base64 32-byte public key, not a private key. Missing required production inputs fails. Fictional fixture inputs are used only for compatibility tests, never production artifacts. The old PRODUCTION_RELEASE_ENABLED variable is not used by the new draft-only entry.

Secrets protect CI input, not embedded client configuration. A client owner may extract the fixed password. Never supply PAT, GitHub App private key, SSH/signing/server private key or cloud credentials as client configuration. Password Security V2 remains deferred. No values/password hashes enter manifests/logs.

## Manual verification

1. Actions -> **CI - Patch and Build compatibility**: empty ref tests official default branch; `1.4.9` tests historical stable.
2. Actions -> **Stable - Draft only**: upstream_ref `1.4.9`; `dry_run=true` creates artifacts only. After reviewing regression evidence, `dry_run=false` creates a complete unpublished Draft. It never publishes it.
3. Actions -> **Nightly - Development artifacts**: tests latest default-branch exact SHA with source-derived version.

Draft and published versions both deduplicate by upstream/revision and recorded source/patch identities. Force rebuild on an existing completed revision only produces artifacts; never overwrites release/tag/assets. Increase `patch-revision.txt` for a new custom revision.

## Artifacts and gates

Unsigned unpacked Windows Flutter bundles, not signed installers. Paired checks require exact same upstream SHA, patchset, Common hash, repository SHA, run and server configuration fingerprint. Each bundle includes build-info, source-manifest, patches, AGPL licence and per-file checksums. Stable Draft includes both ZIPs, both build-info files and global checksums. Native built-DLL configuration probing, AMD64 headers, compiled test-marker exclusion and visible known credential pattern scans remain mandatory. Pattern scans do not prove absence of every encoded/unknown credential.

Development upstream requests source SBOM: generate per patched prepared variant with pinned Syft; label it source SBOM, not complete compiled binary inventory.

## Support and validation

Build-supported targets: Windows x86_64 Standard/SOS; Linux x86_64/ARM64 and macOS x86_64/ARM64 Standard/SOS; Android ARM64/ARMv7/x86_64 Standard. Phase 5 full build/package/architecture/checksum/provenance evidence is run 36902005326, with CI gate 36940045038. Windows ARM64 and iOS remain PLANNED; Web is BLOCKED by the audited official disabled job. Android/iOS/Web SOS are forbidden. See [platform support](docs/platform-support.md).
Android is SUPPORTED for BUILD ONLY. Production signing identity is NOT VALIDATED and deferred to Phase 5.1, which has not started. Runtime/UI remains SKIPPED BY USER; real remote sessions NOT TESTED.

Phase 5 extends the same prepared-source build core with an explicit parallel matrix and `fail-fast: false`. Stable defaults to all 13 supported required targets. Manual Stable `include_experimental=true` always disables Draft creation; use artifacts-only plus force rebuild to regress an existing revision. Nightly includes experimental targets by default, with a manual opt-out. A full matrix starts 13 target builds and may consume substantial runner time. Non-Windows full Nightly builds remain NOT TESTED; Stable promotion does not replace that evidence.

Each new platform adapter verifies the exact source's reviewed official build interface before toolchain preparation. Unknown changes fail closed. Platform jobs independently package/validate; aggregate verifies required artifacts and shared source identities, preserving experimental diagnostics. Only actual Actions evidence can promote a target in `metadata/platform-matrix.json`. Android packages use the debug/test recipe, without production signing identity validation. [Phase 5 acceptance](docs/phase5-acceptance.md) records the evidence and remaining limitations, including the historical scheduled failure and post-fix schedule NOT OBSERVED.

Runtime/UI: **SKIPPED BY USER**. Real remote session: **NOT TESTED**. Code signing: **NOT ENABLED**. Nightly schedule is configured; only an observed schedule event can prove execution.

Floating official engine downloads, hosted runners and system packages prevent a bitwise reproducibility promise. Their identities/hashes are recorded where available; source/patch/provenance consistency remains enforced.

Staging `billradar/rustdesk-custom-test` retains experiments and future patch generation development. Production compatibility only reports failures; it never auto-generates patches. Old `billradar/rustdesk`, `billradar/rustdesk-sos` and historical releases remain untouched.

Audit: [current architecture](docs/phase4-current-architecture.md), [official build](docs/upstream-build-architecture.md), [dependency map](docs/build-dependency-map.md). Frozen Phase 3 baseline: `metadata/PHASE3_BASELINE.json`.
