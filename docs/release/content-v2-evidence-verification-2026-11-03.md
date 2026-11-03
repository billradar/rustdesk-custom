# Content Identity v2 — refreshed evidence and operator disposition (2026-11-03)

**Decision: NO-GO for production activation.** This is a read-only evidence update, not a GO attestation. The production cutover metadata remains BLOCKED.

## Exact repository baseline

- Repository: `billradar/rustdesk-custom`.
- Verified main SHA: `3b116171ac7e6a68c01cf59dbf1aaa738f57d4d0` (merged PR #229).
- GitHub Actions API reports `completed/success` for the following runs **at that exact main SHA**:
  - Patchset content version contract: [41639117979](https://github.com/billradar/rustdesk-custom/actions/runs/41639117979)
  - CI - Patch and Build compatibility: [41639117965](https://github.com/billradar/rustdesk-custom/actions/runs/41639117965)
  - Coordinator cutover offline contracts: [41639117724](https://github.com/billradar/rustdesk-custom/actions/runs/41639117724)
  - Build reliability and targeted recovery: [41640602408](https://github.com/billradar/rustdesk-custom/actions/runs/41640602408)

## Operator confirmation: independent production writers

The operator explicitly confirmed that independent production writers can be excluded. **Disposition: OPERATOR-CONFIRMED / PASS for the stated scope**, not an independently observed machine-state proof. Do not conflate this confirmation with a cryptographically verifiable host inventory.

GitHub Actions API read-only snapshot: `in_progress=0`, `queued=0`, `waiting=0`. A previously supplied Raspberry Pi process snapshot found no Runner.Worker or signing/build subprocess at the observation time. These observations are point-in-time.

## Historical journal review hold — PASS for preservation and non-replay policy, not historical completion

- Journal `7e235a579e04f8648a37bed55dfb135df458b30248936a4519f2ef1e6c014738`: head `1962da0a2e25fa4d48509d10f3ee87cccd9e11dc`; historical SUCCEEDED.
- Journal `a4bbba02e3e23edc9cd27f97ede5a1239f540c4ca448fa51d2ced98ea0ef7a75`: head `e9f1124e3a05d199103b37453fad1ef874ab1bbe`; historical QUEUED / REVIEW_REQUIRED; run `41549385808` has an uncertain historical outcome.
- Both heads match the earlier snapshot; four run-index refs remain present.
- **PASS: historical preservation/non-replay disposition** — retain the ambiguous journal in REVIEW_REQUIRED; never mark it SUCCEEDED, replay it, or mutate it to manufacture reconciliation. The offline coordinator contract at run 41639117724 passed.
- **NOT independently proven**: production-equivalent end-to-end non-replay behavior across every independently deployed entrypoint. This limitation is not overridden by a PASS label.

## Real GitHub API evidence — VERIFIED

- All four main-branch run IDs above were fetched individually and confirmed completed/success with matching `head_sha`.
- Releases individually fetched:
  - `432254527` — draft, tag `nightly`, 32 assets
  - `431170313` — draft, placeholder `untagged-ae5bef8b7a54e85070ed`, 32 assets
  - `430489827` — draft, placeholder `untagged-1adf51dab8dd95750d11`, 32 assets
- Three actual tag refs: `nightly`, `v1.5.0-custom.v2.6`, `v1.5.1-custom.v2.1`. The `untagged-*` draft placeholders are not actual tag refs.
- Production v1 journal refs: 2; v2 journal refs: 0. The store namespace version is not necessarily the build identity version.

## Gate assessment

| Gate | Disposition | Basis |
| --- | --- | --- |
| Independent writers excluded | OPERATOR-CONFIRMED PASS | Explicit operator confirmation, not independent API proof |
| Historical ambiguous journal non-replay/preservation | PASS for preservation policy | Existing REVIEW_REQUIRED record, unchanged heads, successful offline contracts |
| Release/tag inventory | VERIFIED | GitHub API release and tag reads |
| Up-to-date patchset/version/coordinator contracts | VERIFIED | Four successful main-SHA runs |
| Real activation certificate validation | **OPEN** | Current runtime checks reference formats and repository-local digest, not remote GitHub API truth/freshness |
| Production cutover activation | **BLOCKED** | `metadata/release/patchset-cutover.json` still BLOCKED |

**No production activation, signing, release, journal mutation, or historical tag rewrite is authorized by this report.** Before GO, implement and review independent verification of the referenced API observations and activation freshness; then perform a freeze-window recheck and explicit activation authorization.
