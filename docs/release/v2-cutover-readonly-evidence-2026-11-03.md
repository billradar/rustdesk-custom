# Content Identity v2 cutover — final read-only GitHub evidence refresh (2026-11-03)

This is a **read-only evidence snapshot**, not an activation approval. All observations are from GitHub repository API responses on 2026-11-03. The production cutover remains **BLOCKED**. Do not alter historical journals, releases, tags, signatures, or owner-deleted Actions runs.

## Current main and CI

- Current `main`: `bd9553788df5bca3b5b04a35c1f20baa9b0097e2` (PR #218 squash merge).
- Push workflow [Patchset content version contract #41618988392](https://github.com/billradar/rustdesk-custom/actions/runs/41618988392): completed **success** on this exact SHA.
- Push workflow [CI - Patch and Build compatibility #41618988454](https://github.com/billradar/rustdesk-custom/actions/runs/41618988454): completed **success** on this exact SHA.
- The earlier PR #218 run #41618966454 failed because it compared the already advanced `main` to an older PR test merge commit; this does not supersede the two successful push checks above.
- PR #221's final-head offline Coordinator, Patchset content version, and full compatibility PR checks also completed successfully; isolated API/ref checks were skipped by workflow conditions.

## Fresh Git tag and draft release inventory

Read GitHub `/git/matching-refs/tags/` and `/releases?per_page=30`:

| Git tag | Git tag target SHA | Draft release ID | Release API tag | Release target SHA | Assets |
| --- | --- | ---: | --- | --- | ---: |
| `nightly` | `8d6f0b96aba2d20255381585f2bd3ecb82aa356a` | 432254527 | `nightly` | same | 32 |
| `v1.5.1-custom.v2.1` | `82859cd32d4608e6507314de1cdd5cf9ebb2860c` | 431170313 | `untagged-ae5bef8b7a54e85070ed` | same | 32 |
| `v1.5.0-custom.v2.6` | `bed8113783f8e9da9ae0ae9a4b300f68bc445ddd` | 430489827 | `untagged-1adf51dab8dd95750d11` | same | 32 |

Three Git tag refs and three draft releases were returned, totalling **96 assets**. The draft-release `untagged-*` names are GitHub draft placeholders, **not** additional Git tag refs or proof of duplication. Targets match for all three. This is a current metadata inventory, not a fresh per-asset provenance/signature/checksum verification. Historical [release audit run #41611975833](https://github.com/billradar/rustdesk-custom/actions/runs/41611975833) passed 96 assets and nine Android APK signer checks for its earlier snapshot; do not mislabel that as a current full re-audit.

## GitHub Actions and immutable legacy journal observations

- `/actions/runs?status=in_progress&per_page=50` returned **zero** in-progress GitHub Actions runs at the time of inspection. This does not independently prove absence of an external/self-hosted worker process or queued work outside GitHub Actions.
- The two `refs/heads/release-coordinator/v1/nightly/*` refs remain in place. Read-only `state.json` observations:
  - `7e235a579e04f8648a37bed55dfb135df458b30248936a4519f2ef1e6c014738`: `SUCCEEDED`, `completed_at=2026-11-03T03:44:51Z`, workflow run `41566163005`.
  - `a4bbba02e3e23edc9cd27f97ede5a1239f540c4ca448fa51d2ced98ea0ef7a75`: `QUEUED`, `REVIEW_REQUIRED`, historical workflow run `41549385808`, whose owner-confirmed deletion is closed as provenance. This is a historical hold, **not** an instruction to recover or replay the run.
- Four `release-coordinator-runs/v1/*` run-index refs remain, including the three owner-deleted run IDs `41496715461`, `41549385808`, `41562101960`. Preserve them without re-investigating the owner's deletion action.
- Legacy Coordinator Identity v1 is retired for future build admission; do not require positive v1-to-v2 aliases or replay old journals. This does **not** retire `patchsets/v1` source patches.

## Remaining activation gates and evidence boundary

1. Capture independently authenticated production worker quiescence and queue/journal reconciliation evidence, or an explicitly reviewed safe disposition of historical uncertain outcomes. A zero-running-Actions API result alone is insufficient.
2. Validate current release-asset provenance/signatures/checksums and deduplication behavior as appropriate for production activation; the current metadata inventory alone is insufficient.
3. Verify any remaining production-specific API/ref permission, admission, and signing isolation contracts not covered by conditionally skipped CI.
4. Submit a **separate reviewed main-branch migration** that explicitly changes `require_cutover()` only after all gates pass. No environment-variable bypass, PR-workflow activation, history rewrite, duplicate release, or speculative worker completion is permitted.

**Decision: BLOCKED.** This document makes no runtime, build, signing, journal, tag, or release changes.
