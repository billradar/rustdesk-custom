# Phase 5 — implementation checkpoint

Status: **IN PROGRESS / ACTIONS VALIDATION PENDING**. This is not final acceptance.

## Baseline and source identities

Frozen Phase 4 code: `31068343275299000954cf7e7d92ebdb186436b4`; audit commit: `d7b89b487d218a79423bdac1d52ddca661143131`.
Stable evidence: run [36865945733](https://github.com/billradar/rustdesk-custom/actions/runs/36865945733).
Nightly evidence: run [36872771101](https://github.com/billradar/rustdesk-custom/actions/runs/36872771101).
CI evidence: run [36865665982](https://github.com/billradar/rustdesk-custom/actions/runs/36865665982).
These are Phase 4 evidence, not Phase 5 regression results.

| Source | Version | Exact SHA | Patch set |
|---|---|---|---|
| Stable | 1.4.9 | 6c578292e8ebbbec708b76986ba8c4bc7c509747 | v1 |
| Development baseline, master | 1.5.0 | fada664df7a294d1d1a9ca3e7cd3637069122f17 | v2 |

No frozen patch content changed. New runs resolve current upstream once; development may move beyond this audited snapshot and must pass the reviewed build-interface guard.

## Implemented, not yet Actions-proven

- Explicit support metadata and matrix include; `fail-fast: false`.
- One prepared Standard/SOS input, checked before platform toolchains; no per-platform resolver.
- Existing Windows build path retained; independent Linux, macOS and Android jobs added.
- Reviewed exact-source official platform recipes, runners and toolchain signatures; unknown interfaces fail closed.
- Independent package, architecture, checksum, configuration, credential and provenance gates.
- Aggregate checks required targets, duplicates, source identities and per-variant pairing. Experimental failures remain visible in diagnostics; they do not become Stable required targets.
- Stable Draft only; experimental Stable runs are artifacts-only. Nightly has no Release job.

Initial local test checkpoint: 57 tests PASS. First Actions run and repair status: [first-run analysis](phase5-first-run-fixes.md). This does not prove repaired compilation or packaging on GitHub runners.

## Remaining acceptance

| Requirement | Status |
|---|---|
| Windows x86_64 Standard/SOS Phase 5 regression | PASS, run 36889364030 |
| New platform compile/package/architecture/config gates | Android ARM64 PASS; other attempted targets FAIL; repair retest pending |
| Cross-platform actual time-overlap evidence | PASS, run 36889364030 |
| Aggregate on actual cross-platform artifacts | PARTIAL; required Windows gate PASS |
| Non-Windows platform promotion | NOT ACHIEVED |
| Phase 5 Build Architecture acceptance | PENDING |
| Cross-Platform Promotion | PENDING |

No experimental target has been promoted. See [platform support](platform-support.md) and [dependency map](build-dependency-map.md).

## Manual Actions verification

1. Stable workflow, branch `main`, upstream `1.4.9`: enable existing-revision artifact rebuild, artifacts-only/dry-run, and experimental targets. This tests both frozen v1 variants without modifying the existing Draft.
2. Nightly workflow, branch `main`: include experimental targets. It locks the official default-branch SHA, resolves its patch generation, and produces artifacts only.
3. Inspect each target diagnostic and the aggregate artifact. Record run/job IDs and overlapping start/finish times. Only after every promotion gate passes may the corresponding metadata entry become SUPPORTED.

Stable's default required matrix remains Windows x86_64 Standard/SOS until evidence-backed promotion. Windows ARM64 needs its dedicated official ARM Bridge adapter; iOS has not been attempted; Web is disabled in both audited official workflows. Do not call those builds PASS or invent a signing result.

## Unchanged limitations and safety

Runtime/UI: **SKIPPED BY USER**. Real remote session: **NOT TESTED**.
Code signing: **NOT ENABLED**; Android uses the reviewed official debug/test-signing recipe, never a production signing identity.
Password Security V2: **DEFERRED**. Client-embedded configuration remains extractable; CI Secrets do not change that fact.
Nightly schedule: `0 2 * * *`, **CONFIGURED / NOT OBSERVED**; Phase 3 history is unchanged.
Credential scans detect known patterns, not every possible encoded credential. Source SBOM is not a complete binary SBOM.
Old repositories and old Releases: **ZERO WRITES by this task / UNCHANGED**.
