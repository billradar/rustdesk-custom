# Manual Patchset Cutover reconciliation — 2026-11-03

Status: **REVIEW REQUIRED — NOT APPROVED FOR ACTIVATION**

Scope: read-only GitHub API inventory of `billradar/rustdesk-custom` at main `ab99cce82c38a868f462301b9edb5e419897fd88`. This report is evidence for review, not a migration certificate. No historical refs, releases, tags, signatures, or journal records are changed.

## Inventory

- Release coordinator identity refs: `nightly/7e235a579e04f8648a37bed55dfb135df458b30248936a4519f2ef1e6c014738`, `nightly/a4bbba02e3e23edc9cd27f97ede5a1239f540c4ca448fa51d2ced98ea0ef7a75`.
- Run-index refs: `41496715461`, `41549385808`, `41562101960`, `41566163005`.
- Tags: `nightly` -> `8d6f0b96aba2d20255381585f2bd3ecb82aa356a`; `v1.5.0-custom.v2.6` -> `bed8113783f8e9da9ae0ae9a4b300f68bc445ddd`; `v1.5.1-custom.v2.1` -> `82859cd32d4608e6507314de1cdd5cf9ebb2860c`.
- Draft releases: `432254527` (`nightly`, 32 assets, prerelease); `430489827` (`v1.5.0-custom.v2.6`, 32 assets); `431170313` (`v1.5.1-custom.v2.1`, 32 assets). Stable drafts use `untagged-*` API tag names even though their `target_commitish` matches the corresponding version-tag SHA; this is not proof of tag association.
- Latest queried 100 Actions runs had no active runs at query time; this is **not** exhaustive historical worker quiescence evidence.

## Journal / worker comparison

| Identity prefix | Run index | Fence | Run index state | Current identity ref state | Actions evidence |
|---|---:|---:|---|---|---|
| a4bbba02 | 41496715461 | 1 | QUEUED / READY | superseded by fence 2 | Run and jobs API 404 |
| a4bbba02 | 41549385808 | 2 | QUEUED / READY | QUEUED / REVIEW_REQUIRED | Run and jobs API 404 |
| 7e235a57 | 41562101960 | 1 | QUEUED / READY | superseded by fence 2 | Run and jobs API 404 |
| 7e235a57 | 41566163005 | 2 | QUEUED / READY | RUNNING / READY, completed_at null | Actions completed/success, attempt 1, head SHA 8d6f0b96aba2d20255381585f2bd3ecb82aa356a |

All four run-index records were read from Git refs -> commit -> tree -> `state.json` blobs. The two identity refs were read by the same route. Both identity records are policy_version=1 and channel=nightly. Missing Actions runs are **unknown**, not failed, canceled, or successful.

## Remaining mandatory checks before cutover

1. Verify the full append-only journal event chains, record ancestry, fence/reservation ownership, and run-index binding; reconcile terminal evidence without rewriting immutable history.
2. For `41566163005`, verify exact worker provenance, release/draft identity and successful terminal evidence before appending a terminal transition through the coordinator's existing CAS/append interface.
3. For the three 404 runs, inspect historical journal events, run deletion/audit evidence and release artifacts; retain REVIEW_REQUIRED wherever outcome is ambiguous.
4. Inventory historical Stable and Nightly producers beyond the recent 100-run window and prove no active writer or outstanding lease can race migration.
5. Compute both legacy v1 and new content Build Identity from frozen, verified inputs; record a collision-free, channel/mode-aware mapping with deterministic evidence. Do not alias based solely on upstream SHA or patchset name.
6. Verify current patchset revision, common/SOS hashes, build-policy digest, version history, and the required up-to-date version gate.
7. Add regression tests for missing evidence, conflicting identity, stale fence, concurrent reservation, repeated migration, release uniqueness and successful reconciliation.
8. Only after all gates pass, implement a separately reviewed activation change; do not remove or bypass `require_cutover()` in this evidence PR.

## Source links

- https://github.com/billradar/rustdesk-custom/actions/runs/41566163005
- https://github.com/billradar/rustdesk-custom/actions/runs/41576263348
- https://github.com/billradar/rustdesk-custom/releases
- https://github.com/billradar/rustdesk-custom/blob/ab99cce82c38a868f462301b9edb5e419897fd88/metadata/release/patchset-cutover.json

This audit intentionally makes **no** claim that cutover is approved.
