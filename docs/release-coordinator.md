# Unified Release Coordinator: audit and staged implementation

Baseline: main `95abfaf706766f670dddcecea41530320c0ebb66`, inspected 2026-11-02.
This is an implementation audit, not proof that concurrency incidents occurred.
PR 1 supplies dormant identity/state/decision primitives and executable contracts.
Neither production router imports the new core yet. No state backend exists yet.

## Evidence and priority

All line references below refer to the baseline, not this document's branch.

| Priority | Finding | Source evidence | Consequence and disposition |
| --- | --- | --- | --- |
| P1 | Retry classification uses workflow conclusion, not failure stage | `router_retry_policy.py:6-7,23-26` permits generic failure/timed_out/startup_failure | Patch, compile, contract, integrity or signing failures can enter automatic retry eligibility. Replace with explicit evidence classes in PR 3; do not infer infrastructure from conclusion alone. |
| P1 | Discovery/dispatch has no durable reservation | `stable_router.py:route`, `nightly.py:198-235` read history before gh workflow run | The read and dispatch are not atomic. No duplicate production incident is asserted. Manual/downstream entrypoints must participate in the same admission protocol. |
| P1 blocker | Nightly cannot write a Git-ref state ledger with current token permissions | `upstream-nightly.yml:permissions` and route job grant contents read/actions write | Git refs need contents write. Do not silently broaden permissions or expose the existing release App to routers. |
| P2 | Cooldown uses creation time | `router_retry_policy.py:31-40` reads created_at | Long builds may finish after the six-hour window has already elapsed. Use verified completion timestamps, never updated_at as an unexplained substitute. |
| P2 | Retry accounting counts workflow rows | `router_retry_policy.py:23`; no job-stage or run-attempt evidence | Cannot prove that each counted row entered build; leaf reruns use the same run ID. Persist actual build entry and reconcile run attempts with the existing recovery observer. |
| P2 | Added Nightly regression module has invalid Python continuation | `nightly_router_regression_contract.py:17` contains two backslashes before newline | PR 1 fixes the continuation only; no assertions relaxed. |
| P2 | Two retry/regression modules are not executed by the domain-contract list | `compat-check.yml:129-147` | PR 1 adds both modules and the new coordinator contract to the existing fail-fast list. |
| Operational limit | Historical artifact loss stops routing | `stable_router.py:recorded_identity`; `nightly.py:152-195` | Deliberately fail closed. Expired/missing evidence must never mean a free retry. A durable journal will reduce this availability dependency. |
| Operational limit | History lookup is bounded | `stable_router.py:workflow_runs`, `nightly.py:203-210,258-265` | Both fail after ten full pages. Stable release-version scan also has a bounded fail-closed limit. Preserve this safety while avoiding repeated complete history scans. |

Existing safeguards are intentional:
- Stable Lock binds digest, current run, custom commit, exact source, selected patch hashes, Wayland policy and frozen signing choice. Preflight and aggregation revalidate it; artifacts are evidence, never locks.
- Nightly verifies official workflow path, repository, default branch, successful completed status and exact head SHA. Both router and downstream resolve latest successful official run. Do not restore public run-ID/SHA pinning inputs.
- PR #167 is merged at the baseline. Its completed changes preserve latest-successful resolution, mark ACTIVE/SUCCESS/COOLDOWN no-build runs, and exclude those records from identity history. Reimplementing those changes is unnecessary.
- Existing cancellation and unresolved-identity outcomes block automated retries.
- Stable release preflight and publication independently verify exact identity and remote asset digests. Completed Stable revisions remain immutable.
- `qualification.py:366-456` validates aggregate, rejects existing revision/tag, scans successful job logs, uploads a private draft, verifies inventory and creates the immutable ref. The coordinator cannot substitute for any gate.
- `nightly.yml` shares one `nightly-latest` concurrency group for its moving release; this is a publication-order constraint, not a replaceable per-identity lock.
- Stable concurrency uses requested ref/options rather than resolved identity; `latest` and an explicit tag can denote the same source while using different groups.
- Router concurrency groups are separate from build groups. They are not a transaction spanning history, source resolution, dispatch, admission and completion.

## Repository and Actions observations

PR #167's latest head was `27b1c5c970524de74c1106356b3960d34705c86d`; merge is confirmed.
No open PRs were returned at audit start.
Main is protected. Active ruleset `24412604` requires PRs and resolved review threads, rejects deletion/non-fast-forward updates, and has no bypass actors.
The classic branch-protection endpoint returned 403; its additional settings were not verified.
The repository response reports push/admin capability for the connected actor; this does not grant Actions tokens those permissions.
Main/development comparison was diverged (development ahead 36, behind 3), with `compat-check.yml` differing.
Use the explicitly requested independent PR branch from main; do not reset shared development.

Recent main run `41405202330` and PR #167 run `41404677318` were still in progress when inspected.
Historical main CI run `41403341194` succeeded; this is not evidence for new code.
Main action-runtime run `41405202264` was cancelled; no cause is inferred from its conclusion alone.
Historical routers `41398546403` (Stable) and `41292946468` (Nightly) completed successfully; success may mean a safe skip.
The connector rejects workflow-file-name run-list endpoints; repository run history was used instead.
Actual Environment protection rules, runner access configuration and secret policy cannot be read through the available connector. YAML isolation was inspected; live Environment protection remains unverified.
The execution environment failed initialization, so no local Python tests have been executed.

## Identity contract

| Layer | Included | Excluded |
| --- | --- | --- |
| Source v1 | official repository/SHA, selected patchset, common/SOS content digests | official run ID, custom commit, timestamps |
| Build v1 | channel, source, Wayland inclusion/policy digest, signing boolean, explicit policy version; Nightly release mode | custom commit and run IDs; Stable publication mode |
| Run provenance | custom repository SHA, workflow run ID, optional official run ID | never used as the cache/reservation key |

Canonical serialization is sorted compact ASCII-escaped UTF-8 JSON with no float/NaN values; SHA-256 hashes the complete schema envelope.
The v1 policy preserves existing matrix reuse semantics: the current matrix is not silently added to the identity.
A matrix/toolchain/signing-profile identity expansion requires a reviewed policy/schema bump, fixtures, legacy evidence mapping and an explicit migration PR.
The existing signing toggle is preserved; v1 does not claim to encode the entire certificate/profile.
Custom commit remains provenance for both channels. Qualification still matches the exact custom commit independently.

The historical adapter reconstructs Stable v4 and current unversioned Nightly digests exactly.
The old Stable v3 release-verification path remains in channel.py; it is not replaced by this adapter.
New namespace keys must not cause fresh builds merely because the ledger is empty.
Import requires verified lock/discovery/release evidence from existing gates, exact legacy digest comparison, then an audited alias record.
Unknown versions, missing artifacts and conflicting aliases enter REVIEW_REQUIRED.
An identity digest is not evidence of artifact integrity or publication authorization.

## State vocabulary and transitions

Build result, reservation and policy are separate fields.

| Dimension | From | To | Required evidence |
| --- | --- | --- | --- |
| Reservation | NONE | RESERVED | atomic admission; unique UUID; increasing fence; UTC lease |
| Reservation | RESERVED | DISPATCH_UNKNOWN | request outcome cannot be established |
| Reservation | RESERVED / DISPATCH_UNKNOWN | BOUND | verified workflow run and reservation correlation |
| Build | DISCOVERED | QUEUED | bind a verified run |
| Build | QUEUED | RUNNING | observed actual build entry; increments real attempt once |
| Build | QUEUED / RUNNING | FAILED | completion time, failure class, stage, reason |
| Build | RUNNING | SUCCEEDED | verified completion plus existing channel evidence |
| Policy | READY | COOLDOWN / REVIEW_REQUIRED | classified retry decision (PR 3) |
| Recovery | expired reservation | RECONCILE decision | query real Actions state before any replacement |

Success is terminal in PR 1. No normal failure can overwrite it.
PR 1 events retain immutable before/after records and UTC event time; durable append-only storage is PR 2.
Worker writes require reservation UUID and fence. Persistent compare-and-swap must also validate these values in the same atomic write; in-memory checks alone do not fence concurrent writers.
Lease expiry and dispatch ambiguity return RECONCILE, never RESERVE.
PR 1 intentionally has no automatic failed-attempt reset, retry authorization, reservation stealing or publication operations.
Readmission and fencing-token renewal require the transactional backend and PR 3 reconciliation proof.

## Storage options and decision

| Option | Atomicity / durability | Permissions / operation | Assessment |
| --- | --- | --- | --- |
| Per-identity Git ref with single-parent journal commits | atomic ref creation; non-force fast-forward update rejects competing sibling commits; durable audit ancestry | contents write needed; blob/tree/commit/ref calls per transition; ruleset and live API tests needed | preferred no-server candidate only if permission constraint is explicitly resolved |
| PostgreSQL | UNIQUE identity + transaction, row lock/version check; strong concurrency; durable with managed backups | external service and authenticated access required; short-lived credential/OIDC broker preferred | preferred alternative when GITHUB_TOKEN must remain read-only |
| Local SQLite | transaction/unique constraint only inside one database | runner-local disks disappear and are not shared | unsuitable across hosted runners; putting DB in artifacts/caches is not a transaction |
| Hosted SQLite service | depends on server transaction semantics, replication and backups | requires external service/auth just like PostgreSQL | evaluate only with concrete provider guarantees |
| Actions artifacts/cache/concurrency | no atomic durable identity admission | existing permissions | evidence/throughput tools only; rejected as lock backend |

Technical direction: retain backend-neutral pure decisions now.
Git-ref ledger is the lowest-deployment-cost candidate, but is NOT approved for live integration under the current no-permission-expansion requirement.
PostgreSQL satisfies correctness without changing GITHUB_TOKEN only after a real authenticated service exists.
There is no existing authorized durable writer/service verified in this audit. PR 2 live activation is blocked rather than degrading atomicity.

For the Git-ref candidate, each identity owns a journal head.
Every candidate commit has the exact observed head as its only parent and stores the next record plus event.
Two competing siblings cannot both be fast-forwards; never force, merge, reset or delete the ledger head.
Do not mistake REST update-ref for an expected-old-SHA API: the sibling-commit construction is essential.
Read-after-write resolves ambiguous responses; unmatched commits are unreachable evidence, never ownership.
Live tests must use a separate test repository/ref namespace after permissions are established.
No production refs were created for this audit.
GitHub reference API: https://docs.github.com/en/rest/git/refs

## Dispatch, retry and reconciliation plan

The dispatch transaction must persist INTENT before HTTP. A timeout/5xx after sending is ambiguous; never automatically resend.
Bind by unique reservation token in an internal, non-publication-authorizing correlation interface.
No matching run after a timeout is not proof that GitHub rejected dispatch.
Fail closed for indefinite ambiguity; operator resolution must be audited and cannot waive signing/publication gates.
Router-selected Nightly may be superseded before downstream resolution by design. Downstream must resolve latest-successful, then obtain admission for that actual identity before any build. It must not silently build the router's stale selection.
Manual and automatic entrypoints use the same admission path.

PR 3 retry classes: verified transient network/5xx/runner-capacity/build infrastructure only.
Patch/compile/contract/signing/integrity/security rejection, cancellation and unknown failures require review.
Maximum three observed real build entries; prebuild/skip events do not consume attempts.
Backoff uses verified completed_at with bounded exponential delay and injected jitter for deterministic tests.
Observe run_attempt/job history and coordinate with build-reliability.yml; its existing targeted leaf reruns cannot run as an independent competing retry authority.
429 honors Retry-After; reads may retry boundedly; ambiguous writes/dispatches require reconciliation.
Manual retry grants need scope, expiry, reason and explicit attempt-budget policy; repeated manual skips cannot spend budget.

Each router reconciles incomplete reservations, Actions run/attempt/job evidence and identity artifacts before admission.
Expired artifact is unknown evidence, not missing history.
Active or queued run prevents stealing even after lease expiry.
An old worker's lease renewal/final result must atomically match current UUID, fence and journal version.
Success requires the existing aggregate/identity/integrity gates, not Actions conclusion alone.
Audit logs must record decisions and evidence references, never raw logs/credentials.

Source policy remains latest eligible Stable only, preserving same-version explicit opt-in and completed-version guard.
Historical Stable candidates are not silently backfilled.
Nightly follows latest successful official run only; obsolete failed identities may be reconciled but are not automatically rebuilt.
Schedule is a wake-up hint, not a delivery guarantee; keep existing backup cron and idempotent startup reconciliation.

## Staged PRs, validation and rollback

1. Identity/state/pure decisions (this change). Dormant modules, historical parity tests, fail-closed state tests, regression syntax repair and CI wiring.
2. Backend and atomic admission. Blocked on a durable writer compatible with the permission constraint. Add concurrent same/different identity tests and ambiguous persistence faults; prove behavior against isolated live API/service.
3. Classified retry, fenced renewal and reconciliation. Inject 429/5xx/timeouts, worker crash, missing artifacts and stale writers. No production credentials.
4. Nightly integration. Preserve latest-successful resolver and single moving-release writer; downstream admission after resolution; no automatic public release.
5. Stable integration and legacy cleanup. Preserve frozen Stable Lock, exact-digest asset gates and immutable Drafts.

Each later PR is based on the validated preceding branch unless merged main contains it.
Never merge automatically; never proceed to live integration on unverified safety claims.
PR 1 rollback: revert its commit; routers and persistent state are unaffected.
After backend activation, rollback must stop new admission first, retain ledger/history and reconcile active runs; falling back to artifact-only dedup while reservations are live is unsafe.
Schema readers reject unknown versions; migrations are explicit and reversible via retained journal history.
Operational maintenance includes pagination/rate-limit observability, artifact retention alerts and backend backups/ref ancestry checks.

Required commands (results must be recorded separately, not inferred):
```sh
python3 -m scripts.release.coordinator.contract
python3 -m scripts.release.router_retry_policy_contract
python3 -m scripts.release.nightly_router_regression_contract
python3 scripts/validation/repository_contract.py
python3 -m scripts.release.stable_lock_contract
python3 -m scripts.release.stable_router_contract
python3 -m scripts.release.nightly_contract
python3 -m scripts.signing.android_signing_contract
```

Also run the existing full compat-check domain list. PR checks do not authorize production dispatch/signing/publication.
Concurrency, actual storage recovery and live fencing are NOT proven by PR 1's pure-model tests.
