# Phase 5 acceptance — Cross-platform build support

Phase 5 Build Architecture: **PASS**. Phase 4 Regression: **PASS**. Cross-Platform Promotion: **PASS**.
Accepted on 2026-10-02 after CI [36940045038](https://github.com/billradar/rustdesk-custom/actions/runs/36940045038) completed successfully at maintenance SHA `6b9603b4b575df894a92f54a794dbd7eadf35d8e`.
This acceptance promotes demonstrated build support; it does not claim runtime, remote-session or signing-identity validation. Phase 5.1 has not started.

## Baseline and exact-source identity

Phase 4 frozen code SHA: `31068343275299000954cf7e7d92ebdb186436b4`.
Phase 5 audit SHA: `d7b89b487d218a79423bdac1d52ddca661143131`.
Cross-platform evidence maintenance SHA: `ad65879a7d3588a661910116abd2f6bc57d5f543`.
Promotion is a metadata/documentation change over the accepted CI SHA; the promotion commit is available in this file's Git history. No frozen patch content or build commands changed.

| Source | Version | Exact upstream SHA | Patch set | Evidence scope |
|---|---|---|---|---|
| Stable | 1.4.9 | 6c578292e8ebbbec708b76986ba8c4bc7c509747 | v1 | Phase 5 full 13-target build |
| Development baseline, master | 1.5.0 | fada664df7a294d1d1a9ca3e7cd3637069122f17 | v2 | Phase 4 Windows pair; non-Windows Nightly not tested |

Frozen v1 Common hash: `87b7fb949b3bbc55c6d1e166909e167ebb8e0b6586630c0269f6440ba0542531`.
Frozen v1 SOS hash: `d752022800a8008b10aedd1a79412a00af027464b1754b068c35a0b5b439ea34`.
Resolver remains fail-closed for unknown source/build interfaces. Promotion does not promise every future upstream SHA will compile.

Promotion-local validation: all 74 regression tests passed with Rust 1.75; explicit metadata validation passed; Stable and Nightly each select the expected 13 supported required entries; v1 and v2 frozen patch hashes verified unchanged. Updating support metadata does not itself constitute a new build or a new scheduled-run PASS.

## Actual Actions acceptance

Primary build evidence: [36902005326](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326), overall SUCCESS. All 13 target jobs completed successfully. Each non-Windows job logged `Prepared source checksum/inventory/identity: PASS` and `Package/checksum/architecture/source/configuration/known credential gates: PASS`, then finalized its client artifact. Aggregate job [110537797853](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326/job/110537797853) revalidated downloaded artifacts and reported overall PASS, required_gate PASS, 13 target PASS results and no errors. Aggregate artifact ID: `11186319558`.

| Gate | Result / evidence |
|---|---|
| Patch/API/build compatibility; Resolver | PASS, compatibility jobs in primary run; CI 36940045038 PASS |
| Bridge and Flutter analyze | PASS, primary run |
| Prepared Standard and SOS source | PASS, prepare job 110508724543 and consumer inventory checks |
| Windows x86_64 Standard/SOS regression | PASS, jobs 110508985353 / 110508985449 |
| Explicit matrix, no forbidden mobile SOS | PASS, support metadata and policy checks |
| Parallel DAG, matrix fail-fast=false | PASS, actual overlap and workflow checks |
| Build/package/architecture/checksum/build-info | PASS, all 13 targets |
| Configuration/provenance and Standard/SOS pairing | PASS, per-target gates plus aggregate |
| Known credential pattern scan | PASS within documented pattern/scan coverage |
| Aggregate | PASS, job 110537797853 |
| Stable Draft protection | PASS, Phase 4 Draft run 36865945733; primary experimental run skipped Draft |
| Release deduplication fix | PASS, Actions run 36940172133; all expensive downstream jobs SKIPPED |
| Nightly artifact-only policy | PASS, workflow policy; Windows manual evidence 36872771101 |
| Cross-platform Nightly full build | NOT TESTED; not required for this evidence-backed Stable promotion |

The shared source/hash/provenance gates passed across all selected targets. Stable now selects all 13 SUPPORTED entries as required; a missing or invalid required artifact blocks any new Draft. No historical artifact was reclassified or overwritten. Future supported-set aggregate/Draft runs remain new runs, not retroactive claims about the old five-asset Draft. Dedup preserves that complete historical revision; adding assets requires a new revision, never overwrite.

## Non-Windows promotion evidence

All intervals below are UTC on 2026-10-01. Artifact IDs refer to the original, unchanged primary run.

| Target | Job ID | Start–finish UTC | Artifact ID | Promotion |
|---|---|---|---|---|
| macos-aarch64-standard | [110508986042](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326/job/110508986042) | 18:01:42–18:26:15 | 11184336769 | SUPPORTED — BUILD ONLY |
| linux-x86_64-standard | [110508986096](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326/job/110508986096) | 18:01:37–18:31:57 | 11184422700 | SUPPORTED — BUILD ONLY |
| android-aarch64-standard | [110508986187](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326/job/110508986187) | 18:01:37–19:10:34 | 11186832321 | SUPPORTED — BUILD ONLY |
| macos-x86_64-sos | [110508986238](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326/job/110508986238) | 18:01:39–18:57:35 | 11186785524 | SUPPORTED — BUILD ONLY |
| linux-x86_64-sos | [110508986264](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326/job/110508986264) | 18:01:38–18:32:01 | 11186135657 | SUPPORTED — BUILD ONLY |
| linux-aarch64-standard | [110508986319](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326/job/110508986319) | 18:01:40–18:30:14 | 11185205887 | SUPPORTED — BUILD ONLY |
| macos-x86_64-standard | [110508986330](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326/job/110508986330) | 18:01:39–18:45:23 | 11185723228 | SUPPORTED — BUILD ONLY |
| android-armv7-standard | [110508986336](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326/job/110508986336) | 18:01:37–19:10:29 | 11186747723 | SUPPORTED — BUILD ONLY |
| linux-aarch64-sos | [110508986436](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326/job/110508986436) | 18:01:40–18:29:05 | 11185255736 | SUPPORTED — BUILD ONLY |
| macos-aarch64-sos | [110508986700](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326/job/110508986700) | 18:01:43–18:28:37 | 11185095830 | SUPPORTED — BUILD ONLY |
| android-x86_64-standard | [110508986769](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326/job/110508986769) | 18:01:39–18:28:42 | 11185990466 | SUPPORTED — BUILD ONLY |

Parallelism Evidence: Linux x86_64 Standard job 110508986096 ran 18:01:37–18:31:57 UTC; macOS ARM64 Standard job 110508986042 ran 18:01:42–18:26:15 UTC. Their intervals overlap 18:01:42–18:26:15 UTC. Android ARM64 started at 18:01:37 UTC as well. There is no Windows → Linux → macOS serialization. `fail-fast: false` remains active; prepared inputs are artifacts rather than cache.

## Platform support scope

See [platform-support.md](platform-support.md) and machine-readable `metadata/platform-matrix.json`.

- Windows x86_64: Standard / SOS SUPPORTED; Phase 5 regression PASS.
- Linux x86_64 and ARM64: Standard / SOS SUPPORTED; deb and rpm validated. The Ubuntu 18.04 compiler container is not proof of runtime validation on every Linux distribution.
- macOS Intel and ARM64: Standard / SOS SUPPORTED; unsigned DMG/bundle/native architecture validated. No trusted signing/notarization claim.
- Android ARM64, ARMv7 and x86_64: Standard SUPPORTED for build/package support only. APK output follows the debug/test recipe. Production signing identity, certificate continuity and upgrade signing compatibility are **NOT VALIDATED / DEFERRED TO PHASE 5.1**. No certificate identity Gate PASS is claimed.
- Windows ARM64 Standard/SOS: PLANNED, adapter pending.
- iOS ARM64 Standard: PLANNED, build not attempted; signing/provisioning not enabled.
- Web Standard: BLOCKED, reviewed upstream jobs disabled.
- Android SOS / iOS SOS / Web SOS: NOT IMPLEMENTED / NOT PLANNED.

## Schedule and deduplication history — preserved

Stable scheduled run [36932216497](https://github.com/billradar/rustdesk-custom/actions/runs/36932216497): Trigger Event **schedule**, Overall **FAIL**. Compatibility, Windows pair, validation and aggregate passed; final Draft creation rejected `Existing revision draft`. This historical result is not rewritten as PASS.

Fix commit: `6b9603b4b575df894a92f54a794dbd7eadf35d8e`. Read-only source discovery is followed by a separate Draft release preflight that can view unpublished Drafts. See [draft-preflight-fix.md](draft-preflight-fix.md) for permissions and fail-closed behavior. Manual fix verification [36940172133](https://github.com/billradar/rustdesk-custom/actions/runs/36940172133): PASS; existing complete `v1.4.9-custom.1` detected; build_needed=false, draft_needed=false; compatibility/prepare/build/draft SKIPPED. This was workflow_dispatch, not schedule.

Post-fix Stable schedule: **NOT OBSERVED**.
Nightly schedule: `0 2 * * *`, **CONFIGURED / NOT OBSERVED**.
Phase 3 schedule history is unchanged. Schedule observation is separate from Phase 5 build-support acceptance.

## Policies, limitations and stop point

Stable Release Policy: **DRAFT ONLY**. Automatic Publish: **DISABLED**.
Nightly Release Policy: **ACTIONS ARTIFACTS**.
Runtime/UI: **SKIPPED BY USER**.
Real Remote Session: **NOT TESTED**.
Code Signing: **NOT ENABLED**; Android recipe output is debug/test only, not a validated production signing identity.
Password Security V2: **DEFERRED**.
Embedded client configuration/password can be extracted; GitHub Secrets protect CI input, not client secrecy. Known-pattern scans do not prove absence of every possible encoded credential. Source SBOM is not a complete binary SBOM.
Old `billradar/rustdesk` and `billradar/rustdesk-sos`: **ZERO WRITES by this task**. Historical Releases and existing Draft: **UNCHANGED**. No runtime/remote tests, signing credentials or production password redesign were performed.

Phase 5 completes at evidence-backed metadata promotion and documentation. **STOP: do not begin Phase 5.1 automatically.**
