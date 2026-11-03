# v2 production cutover evidence bundle — 2026-11-03

**Disposition: BLOCKED / evidence staging only.** This is a repository-hosted, reviewable index of independently observed facts and explicit outstanding evidence. It does not authorize or implement production activation.

## Scope and provenance

Repository: `billradar/rustdesk-custom`. Evidence was retrieved read-only from GitHub REST API and workflow job summaries. Prior snapshot: [PR #222](https://github.com/billradar/rustdesk-custom/pull/222). Current reviewed main merge: `8c2a6bb4659ece539968d2434dbc254ea0a9b233`. No historical ref, tag, draft release, signature, or owner-deleted run was mutated.

| Evidence ID | Result | Source / reproducible inspection | Limit |
| --- | --- | --- | --- |
| MAIN-CI-01 | PASS | [Patchset content version #41620937683](https://github.com/billradar/rustdesk-custom/actions/runs/41620937683) — success, main SHA `8c2a6bb` | Version contract only |
| MAIN-CI-02 | PASS | [Patch and Build compatibility #41620937743](https://github.com/billradar/rustdesk-custom/actions/runs/41620937743) — success, same SHA | Compatibility CI, not production admission |
| MAIN-CI-03 | PASS | [Build reliability and targeted recovery #41620990615](https://github.com/billradar/rustdesk-custom/actions/runs/41620990615) — success, same SHA | Successful run is not proof of no external worker |
| GH-QUEUE-01 | PASS AT OBSERVATION | GitHub `GET /repos/billradar/rustdesk-custom/actions/runs?status=in_progress&per_page=100` and `?status=queued&per_page=100`: each `total_count=0` | Point-in-time; recheck immediately before activation |
| RELEASE-01 | PASS METADATA | `GET /repos/billradar/rustdesk-custom/releases?per_page=30`: 3 drafts × 32 assets = 96; every asset has a GitHub API `sha256:` digest field | Digest **presence**, not independent byte recomputation |
| RELEASE-02 | PASS METADATA | `GET /repos/billradar/rustdesk-custom/git/matching-refs/tags/`: exactly `nightly`, `v1.5.1-custom.v2.1`, `v1.5.0-custom.v2.6`; targets match corresponding draft release targets | Draft `untagged-*` placeholders are not additional tag refs |
| NIGHTLY-01 | PASS HISTORICAL RUN | [Nightly #41566163005](https://github.com/billradar/rustdesk-custom/actions/runs/41566163005): overall success, including `Sign Nightly Android production artifacts (YubiKey PIV 9C)`, Windows provenance and Wayland aggregate jobs | Proves the historical workflow job conclusions, not independent signer verification of every currently stored APK |
| JOURNAL-01 | PASS READ-ONLY INVENTORY | `refs/heads/release-coordinator/v1/nightly/7e235a579e04f8648a37bed55dfb135df458b30248936a4519f2ef1e6c014738`: historical `state.json` = `SUCCEEDED`, run `41566163005` | Immutable historical v1 record |
| JOURNAL-02 | HISTORICAL REVIEW HOLD | `refs/heads/release-coordinator/v1/nightly/a4bbba02e3e23edc9cd27f97ede5a1239f540c4ca448fa51d2ced98ea0ef7a75`: historical `QUEUED`/`REVIEW_REQUIRED`, run `41549385808` | Owner-deleted run: **no retry, no replay, no positive v1→v2 alias** |
| JOURNAL-03 | PASS READ-ONLY INVENTORY | Four `refs/heads/release-coordinator-runs/v1/*` entries observed; three owner-deleted IDs `41496715461`, `41549385808`, `41562101960` are retained as immutable provenance | Do not infer worker activity from historical branch presence |

## Additional verification of private release audit output

- Read the complete successful job log for [Verify private draft assets #125836714215](https://github.com/billradar/rustdesk-custom/actions/runs/41611975833/job/125836714215). The audit's structured JSON returned `status=PASS`, all three exact release IDs `432254527`, `431170313`, `430489827`, each with `asset_count=32` and `sums_verified=true`, plus 3 APK signer records per release.
- Compared the nine recorded signed-APK SHA-256 digests with the current GitHub release API asset metadata: **9/9 match**, zero mismatches; the three release IDs and 32-asset counts also match. This independently validates the consistency of the historic audit output with today's API inventory, **not** a new download or cryptographic re-verification of all 96 files.
- GitHub Actions API checks for `in_progress`, `queued`, and `waiting` each returned `total_count=0`. `release-coordinator/v2/*` matching refs returned no entries. Access to the repository self-hosted runners inventory through the available read-only GitHub fetch action was denied by endpoint allowlisting; therefore no runner-busy/lease conclusion is claimed.

## Evidence that must still be independently produced

| Gate | Required evidence | Status |
| --- | --- | --- |
| WORKER-QUIESCENCE | Authenticated snapshot from self-hosted runner/worker controller and any external queues, with observation timestamp, active jobs/processes, leases, and pending dispatches; compare with GitHub queue | **NOT VERIFIED** |
| JOURNAL-RECONCILIATION | Operator-reviewed snapshot of current v2 reservations/leases and explicit disposition for uncertain historical outcomes without rewriting v1 history; validate no active v1 admission | **NOT VERIFIED** |
| ASSET-BYTES | Protected-main [Release Audit #41611975833](https://github.com/billradar/rustdesk-custom/actions/runs/41611975833) returned `PASS` and `sums_verified=true` for all 3 releases / 96 assets. Full current 96-asset byte-for-byte re-download was not independently repeated after the audit. | **HISTORICAL PASS; CURRENT RE-RUN NOT VERIFIED** |
| APK-SIGNATURES | The same protected-main audit verified 9 APK signatures (3 per draft) against trusted public certificate SHA-256 `559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5`. All nine APK digests in its JSON output were independently cross-checked against the current GitHub release asset `digest` metadata: **9/9 identical**. A new on-demand private-asset verifier run is still advisable immediately before activation. | **HISTORICAL PASS + CURRENT DIGEST MATCH; FRESH BYTE AUDIT NOT RUN** |
| PRODUCTION-ADMISSION | Verify v2-only identity admission and rejection of v1/missing digests under production-equivalent isolated API/ref permissions, without dispatching production builds | **NOT VERIFIED** |
| FINAL-FREEZE | Immediately before any activation, repeat live queue/ref/tag/release inventory and pin exact `main` SHA; obtain separate reviewed approval | **NOT VERIFIED** |

## Safety / execution rules

- `metadata/release/patchset-cutover.json` remains `BLOCKED`. `scripts/release/content.py::require_cutover()` must continue to fail closed until a separately reviewed activation migration has sufficient evidence.
- No boolean or environment-variable override, PR-triggered production activation, implicit worker clearance, or speculative historical journal completion.
- Legacy **Coordinator Identity v1** is retired for future admission. Do not create positive v1-to-v2 alias migrations. `patchsets/v1` source patches are a distinct compatibility concept.
- Do not touch owner-deleted Actions runs or historical refs. No automatic release publishing, signing, duplicate dispatch, or tag rewrite.
- Store new independent evidence as separate, timestamped, immutable review artifacts with source URLs, exact SHA, command/tool versions, signer certificate fingerprints (public), and explicit PASS/FAIL/UNVERIFIED status. Never publish signing secrets.

**Cutover decision: NO-GO pending all NOT VERIFIED gates.** A docs-only merge must not change this decision.
