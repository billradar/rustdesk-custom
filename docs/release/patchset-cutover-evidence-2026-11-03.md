# Patchset Cutover — historical evidence checkpoint (2026-11-03)

This is an **audit-only** snapshot. It does not authorize cutover, modify historical refs, or infer success from missing Actions evidence.

## Coordinator journals

| Build identity | Journal | Policy | Worker | Assessment |
| --- | --- | --- | --- | --- |
| `7e235a579e04f8648a37bed55dfb135df458b30248936a4519f2ef1e6c014738` | SUCCEEDED | READY | 41566163005 | Authenticated manual reconciliation run 41595382946 succeeded; journal head `1962da0a2e25fa4d48509d10f3ee87cccd9e11dc` |
| `a4bbba02e3e23edc9cd27f97ede5a1239f540c4ca448fa51d2ced98ea0ef7a75` | QUEUED | REVIEW_REQUIRED | 41549385808 | Actions run intentionally deleted according to repository owner (operator statement, not independently verifiable from GitHub API); 404 corroborates unavailability, not historical outcome. Owner-confirmed manual deletion; skip further deletion-actor/reason verification. Historical outcome remains unknown; **do not** infer failure/success or rewrite journal |

The repository owner reports intentionally deleting Actions runs 41496715461, 41549385808, and 41562101960. All three currently return Actions 404; GitHub API alone cannot verify the deletion actor, reason, or prior conclusion. This is operator testimony about provenance, **not** authenticated evidence of historical completion or release side effects. The fourth, 41566163005, has confirmed successful Actions evidence. Run-index records are historical admission evidence and need not mirror current journal state.

## Historical run deletion disposition

- **Owner-confirmed manual operation (2026-11-03; accepted as authoritative for who deleted these runs):** repository owner states that runs `41496715461`, `41549385808`, and `41562101960` were deliberately deleted.
- **Independently observed:** Actions API currently returns HTTP 404 for these three run IDs. The historical Run Index refs remain intact.
- **Not established:** original run conclusions, whether any release/signing side effects occurred, and whether all corresponding external artifacts are accounted for.
- **Disposition of deletion provenance:** `OWNER_MANUAL_DELETION_CONFIRMED`; skip all further requests for deletion-actor or deletion-reason evidence for these three IDs. This disposition is not a worker completion, a retry approval, a signing approval, or a cutover authorization.
- **Safety decision:** retain the `a4bb...` journal at `QUEUED / REVIEW_REQUIRED` and preserve `BLOCKED` cutover. Do not synthesize success, failure, cancellation, or missing-run recovery solely from owner testimony.
- **Closure requirements:** deletion provenance is closed by owner confirmation and must not be raised again. Resolve only the distinct historical side-effect/terminal-state question through authenticated journal/release evidence or an explicit unknown-outcome disposition supported by the Coordinator state machine; do not mutate immutable refs. Do not mutate immutable historical refs to make evidence appear complete.

## Tag / draft release inventory

| Git tag | Tag target SHA | Draft release | Release target SHA | Assets |
| --- | --- | --- | --- | --- |
| nightly | `8d6f0b96aba2d20255381585f2bd3ecb82aa356a` | 432254527 (nightly, prerelease) | same | 32 |
| v1.5.1-custom.v2.1 | `82859cd32d4608e6507314de1cdd5cf9ebb2860c` | 431170313 (untagged-ae5bef8b7a54e85070ed) | same | 32 |
| v1.5.0-custom.v2.6 | `bed8113783f8e9da9ae0ae9a4b300f68bc445ddd` | 430489827 (untagged-1adf51dab8dd95750d11) | same | 32 |

The stable draft API tag names differ from the corresponding existing Git tag names (GitHub uses `untagged-*` for draft releases). **Do not** treat this as a verified duplicate or as proof of a safe identity alias. Asset counts and target SHA matches are inventory evidence only; asset provenance, signatures and checksums are not yet validated.

## Required gates before activation

- Resolve or formally disposition the REVIEW_REQUIRED historical journal using independently authenticated evidence; do not manufacture missing Actions records.
- Establish a reviewed Legacy v1 → Content Identity alias table and verify collision/deduplication behavior.
- Verify asset provenance, release/tag mapping, signing records and no duplicate publishing.
- Run the required up-to-date Patchset Version gate on current main and preserve its logs.
- Re-evaluate the `metadata/release/patchset-cutover.json` blockers in a **separate reviewed migration**; keep `BLOCKED` until all prerequisites are satisfied.

## Read-only evidence sources

- GitHub Actions run 41595382946 (manual reconciliation)
- GitHub Actions run 41566163005 (successful Worker)
- `refs/heads/release-coordinator/v1/nightly/<identity>` journals and `refs/heads/release-coordinator-runs/v1/<run-id>` indexes
- GitHub Releases REST inventory and `refs/tags/*`
- `metadata/release/patchset-cutover.json`

No production mutation was performed as part of this audit.

## Follow-up verification (2026-11-03; post PR #215 and #216)

- PR #215 merged as `ac6156126816d6b485ab8ed30566fe5217e64753`: the three owner-deleted run IDs are excluded from automatic and explicit missing-run recovery; original journal remains unchanged.
- PR #216 merged as `d7490b62cf6793ae90c6a161c55518d1cfc9174b`: content-v2 versus legacy-success deduplication regression test added. Its final head `253c070ea1406e6ad60a59382e756eb5459445b7` passed Coordinator cutover offline contracts (Actions 41614183552) and Patchset content version contract (Actions 41614183550). Isolated API/ref checks were skipped by workflow conditions; not a positive production proof.
- The full CI - Patch and Build compatibility workflow (Actions 41614183600) was still running when checked. Its eventual outcome must be inspected before migration approval.
- The prior release-asset audit (Actions 41611975833, job 125836714215) passed 96 assets across three draft releases and nine Android APK signatures against trusted signer SHA-256 `559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5`. This closes the historical asset/signer gate for that snapshot, not an inventory freshness gate for future cutover.
- Owner deletion provenance is closed. Unknown historical worker outcome is explicitly retained as a safety hold; no retry, journal mutation or invented terminal event is authorized.
- **Current decision: BLOCKED.** A fresh quiescent production-worker/journal check, fresh tag/draft inventory, production alias collision review, and an independent reviewed migration remain required. This document is not an activation switch.
