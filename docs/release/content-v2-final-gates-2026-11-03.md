# Content Identity v2 — final admission and evidence inventory (2026-11-03)

**Decision: NO-GO / evidence staged. Production metadata stays BLOCKED.** This report is not an activation attestation and must not be referenced as a GO certificate.

## Exact repository baseline

- Repository: `billradar/rustdesk-custom`
- Reviewed main commit: `c47e4e865cf0cdaafa429544f9b6dc164d70a375` (merged PR #228).
- Main compatibility CI: [41631431938](https://github.com/billradar/rustdesk-custom/actions/runs/41631431938) SUCCESS.
- Main content contract: [41631431735](https://github.com/billradar/rustdesk-custom/actions/runs/41631431735) SUCCESS.
- Build reliability: runs 41631503804, 41632574120, 41632728923 SUCCESS.

## GitHub API read-only snapshot

- `actions/runs?status=in_progress`: 0.
- `actions/runs?status=queued`: 0.
- `actions/runs?status=waiting`: 0.
- `git/matching-refs/heads/release-coordinator/v2/`: 0.
- `releases?per_page=20`: three private drafts, IDs `432254527`, `431170313`, `430489827`, 32 assets each. No release mutated.

## Historical production journal heads (immutable)

| Journal identity | Head commit | State | Policy | Reservation | Lease expiry UTC | Run |
| --- | --- | --- | --- | --- | --- | --- |
| `7e235a579e04f8648a37bed55dfb135df458b30248936a4519f2ef1e6c014738` | `1962da0a2e25fa4d48509d10f3ee87cccd9e11dc` | SUCCEEDED | READY | BOUND | 2026-11-03 08:26:19 | 41566163005 |
| `a4bbba02e3e23edc9cd27f97ede5a1239f540c4ca448fa51d2ced98ea0ef7a75` | `e9f1124e3a05d199103b37453fad1ef874ab1bbe` | QUEUED | REVIEW_REQUIRED | BOUND | 2026-11-03 05:57:58 | 41549385808 |

- Four historical run-index refs retained: 41496715461, 41549385808, 41562101960, 41566163005.
- Expired lease does **not** resolve ambiguous dispatch. Never replay run 41549385808, rewrite the historical v1 journals, or create positive v1→v2 aliases.
- No currently unexpired lease was found in the two inspected v1 journal heads. This does not prove absence of another independent writer or storage backend.

## Self-hosted signing host operator snapshot

Operator supplied direct shell output at **2026-11-03 12:09:48 UTC** from Raspberry Pi:
- `rustdesk-actions-runner.service`: active/running.
- `Runner.Listener` PID 23720 present.
- No matching `Runner.Worker`, `apksigner`, `jarsigner`, `gradle`, `flutter`, `cargo` or `android_yubikey_sign` process at that instant.
- This is a point-in-time process check, not a cryptographically bound controller snapshot or proof that all hosts and queues are quiescent.

## Admission implementation findings

- `scripts/release/coordinator/runtime.py` implements v2 admission and invokes `require_cutover()` before new v2 reservation.
- `scripts/release/content.py` currently checks a digest-pinned, repository-local JSON attestation with self-declared GO booleans. That does **not** independently verify worker/controller state, immutable API observations, approval, source SHA, or external writers at runtime.
- `scripts/release/coordinator/store.py` uses Git Ref CAS, with the existing v1 journal namespace. No external PostgreSQL/SQLite is demonstrated by this implementation; independently deployed writers have not been excluded.
- Therefore the current evidence is **not sufficient** to assert production-grade v2-only admission or activate metadata.

## Gates remaining for GO

1. Prove the active production entrypoints and all writers share the same admission/fencing protocol; confirm legacy v1 new admissions are rejected in production-equivalent conditions, with a negative test that cannot dispatch a real build.
2. Independently verify no other production writer or active lease/dispatch exists, and retain the ambiguous historical run in a non-replayable review hold.
3. Bind a fresh controller/runner observation, exact main SHA, journal head SHAs, releases and required version-gate runs into an independently reviewable activation protocol; reject stale or self-asserted-only GO.
4. Repeat the freeze-window queue/ref checks immediately before activation, then separately authorize the production metadata change.

No release, signing key, historical ref, tag, journal or production cutover metadata was changed in preparing this report.
