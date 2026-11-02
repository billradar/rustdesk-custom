# Unified Release Coordinator: audit and staged implementation

Baseline: main `95abfaf706766f670dddcecea41530320c0ebb66`, inspected 2026-11-02.
This is an implementation audit, not proof that concurrency incidents occurred.
This document records the audit baseline and staged implementation. The current
branch includes the persistent journal, recovery core and both Nightly and Stable integrations. No production activation has been performed.

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
The initial execution environment failed initialization. Subsequent stages restored execution; local contracts and each PR CI are recorded in the PRs. This initial limitation is historical.

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
Legacy checks require verified lock/discovery/release evidence from existing gates and exact legacy digest comparison. Known active/successful history blocks a fresh reservation; unknown or failed history does not bootstrap a journal. An operator-assisted legacy import protocol remains separate work.
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
Git-ref journal was selected after explicit user authorization on 2026-11-02 for Contents write only on coordinator state-writing jobs. Ordinary workers keep Contents read. PostgreSQL remains an alternative if these narrowly scoped permissions are unavailable. No server, credentials or Actions artifact lock is introduced. Production activation still requires review/merge and isolated live API/ruleset validation.

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
Bind a verified trusted-main run with the resolved identity, epoch creation time and atomic fence. No new public dispatch input is added; a late/duplicate run can bind at most one current epoch and all workers require their immutable admission index.
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

## Persistent journal implementation (PR 2)

`coordinator/store.py` now implements the GitHub Git Database transport and journal.
The user authorized only coordinator state-writing jobs to use Contents write on
2026-11-02. Ordinary build/CI/signing/publication permissions remain unchanged;
this PR does not yet add any production job or activate the backend.

Each ref is `heads/release-coordinator/v1/{channel}/{build-key}`. Trees contain
only canonical `state.json` and `event.json`; they are orphan journal histories,
never source checkouts. Every update has one observed parent and force=false.
The backend revalidates the event against model transitions, verifies identity,
compares the previous snapshot, and rejects sibling updates. It never merges,
resets or deletes refs. Loaded events must agree with the current and parent
state and ancestry. Missing ref (404) is distinguished from permissions,
rate-limit or infrastructure errors. Historical channel evidence is still
mandatory at the caller; absent ledger does not authorize a rebuild.

Final-ref response loss is resolved only by reading the journal back. Exact
candidate-head equality proves success. Conflicts require a fresh decision;
all other uncertain results remain ambiguous and are not replayed. Blob/tree/
commit writes that fail leave no valid reservation and never dispatch work.
Reads retry at most three times for 429/5xx/transport errors; writes never replay.
Unknown response/schema, merged history and extra state files fail closed.

Local contracts use an in-memory GitHub-shaped API for deterministic races and
fault injection, plus two actual concurrent non-force pushes to a temporary
bare Git server. This proves the single-parent fast-forward primitive; it is
not a claim that live GitHub permission/ruleset integration has been exercised.
No production refs, releases, tags, signing credentials or external services
are used by these contracts. Run `python3 -m
scripts.release.coordinator.store_contract` and the existing domain list.

PR 2 rollback: revert the storage module and its contract wiring. No active
coordinator state exists from this PR. After activation, retain journals and
stop admission before reverting any runtime integration.

## Classified retry and reconciliation implementation (PR 3)

`retry.py`, `transitions.py` and `reconcile.py` implement dormant recovery core.
Defaults are three actual compile-stage entries, with a separate maximum of six
reservation epochs to bound repeated prebuild infrastructure failures. Skips
change neither counter. Backoff starts at six hours from actual job completion,
doubles to a 24-hour base ceiling and adds bounded 0–25% jitter. Limits are
frozen in provenance when configured; invalid or excessive limits fail closed.

Generic failure, compilation, Patch, contract, signature, integrity, unknown
identity, cancellation and safety rejection never qualify automatically. Live
log classification currently recognizes only the existing explicit SDK download
and runner shutdown evidence on leaf build jobs. Other typed transient classes
are available to verified evidence producers; absence of such evidence remains
manual review. Logs are inspected in memory and not printed or journaled.

The reconciler verifies exact repository, workflow path, main branch, custom
commit, run ID and run attempt. Native GitHub reruns require a fresh explicit
coordinator authorization and cannot silently reuse an old reservation. Actual
compile step timestamps determine build entry; the latest observed job completion
determines completion time. An active bound run is never stolen after expiry;
its same fenced lease can be extended. Unknown dispatch is never resent on expiry.
Success requires actual build and aggregate evidence and remains terminal.

An explicit manual grant records actor, reason, timestamp and the next fence. It
permits one new reservation and is consumed there; it cannot change source,
signing or publication gates. The runtime workflow/UI for such grants will be
introduced with channel integration. Retries must recheck the old Actions run is
terminal immediately before the atomic replacement; stale snapshots fail CAS.

`reconcile_contract` covers bounded build and reservation budgets, completion-time
cooldown/jitter, cancellation/signing rejection, active-run lease recovery,
ambiguous dispatch, stale worker results, exact-run provenance and native-rerun
rejection. All fixtures run without production credentials. This stage still
has no production workflow dispatch or backend activation. Rollback: revert
this PR while dormant; after activation retain journal history and stop admission
before reverting recovery logic.

## Nightly integration (PR 4)

Nightly's fixed workflow environment enables the shared route path; the resolver
still selects latest successful official source with no public run/SHA input.
The normal contract process does not inherit the runtime routing flag. Manual
main runs and automatic dispatch use the same digest-verified discovery handoff
and a dedicated admission job. Development dry-run remains isolated and does not
write production state. Stable routing was unchanged in PR 4; PR 5 adds the corresponding Stable integration.

The router persists a unique dispatch-request UUID before HTTP. The UUID is
necessary even with one reservation UUID: two simultaneous writers could otherwise
produce byte-identical commits and both regard the same idempotent ref update as
permission to dispatch. Different request UUIDs produce sibling commits, so only
one wins. Response loss never authorizes a resend. An unstarted RESERVED intent
can resume safely; DISPATCH_UNKNOWN requires a verified arriving run or review.
A changed latest Nightly source is admitted under its actual resolved identity;
obsolete reservations are reconciled without dispatching obsolete source.

An immutable per-run ref under `heads/release-coordinator-runs/v1/` points to the
admission snapshot. It is evidence lookup, not a lock. Before source preparation,
compilation, signing, aggregation and release writing, a read-only guard checks
this index against the current identity journal, UUID/fence, run ID/attempt,
custom commit and available source SHA. Denied runs may point at another worker's
snapshot, which cannot pass their guard. Ordinary guards need only Contents read;
only state writers query Actions and write journals. Signing's sparse checkout
adds only the reviewed guard modules and their standard-library dependencies;
PIN handling, dedicated runner, Environment and v2/v3 gates are unchanged.

`release-coordinator.yml` observes completion from trusted main and can record an
explicit actor/reason grant for one new reservation of an existing identity. It
cannot build, sign, publish or select a different source. Old completion events
cannot modify a newer reservation. The existing reliability observer reports
coordinator-managed batches without independently rerunning a leaf job; legacy
runs retain their existing targeted-recovery behavior.

Public Nightly release still requires explicit manual release mode and all
existing signed-package/Draft/digest checks. The router can dispatch only Draft
with its frozen configuration; direct publication mode is rejected by the shared
dispatch interface. No coordinator code calls a release or signing API.

Historical runs without a durable index still require valid legacy discovery.
An unknown/expired historical identity or unclassified legacy failure requires
manual review, never a free build. The first migration can therefore require
operator reconciliation; this conservative availability limitation is deliberate.
Journal inventory currently fails closed above 1000 identities per channel;
large long-lived repositories need a separately reviewed archive/index strategy.
No live GitHub state-ref writes, signing, public release or release deletion were
used in verification; transport contracts and a real local Git server cover the
atomic primitive, while live deployment/ruleset validation remains separate.

Rollback: stop Nightly routing and new admissions first, retain all journals and
run indexes, reconcile active workers and ambiguous dispatches, then revert the
integration. Do not simply enable artifact-only legacy dispatch while fenced
reservations are still live. Existing completed releases and tags are unchanged.

## Stable integration (PR 5)

Stable's fixed routing step enables the shared core; its separate resolver still
selects the latest official Stable release. Reconciliation runs before the original
completed-version and exact-release preflight checks. Automatic scheduling does
not backfill historical Stable versions. An explicit manual upstream tag remains
available through Tag; same-version router checks retain the existing explicit
`allow_same_version` opt-in. Nightly still follows only latest successful official
source; recovery never dispatches superseded historical identities.

Tag downloads and revalidates its original same-run Stable Lock (digest, source,
custom commit, current run, patch hashes, signing and Wayland options) before
reservation binding. Source preparation requires admission on main. Development
dry-run remains isolated; development draft/release fails explicitly. Existing
publish-existing goes through its original complete-Draft/remote-digest gates and
does not create a new build reservation. New aggregation, Draft and release
writing have an additional read-only worker guard before the release App step.

Stable's existing identity deliberately excludes publication mode. A successful
dry-run cannot satisfy a production Draft: `reserve_upgrade` creates a new fenced
epoch for draft/release, records the previous successful run and preserves the
cumulative attempt budget. The prior success stays in immutable journal ancestry.
This is the sole explicit successful-purpose transition, never an ordinary
success-to-failure overwrite. Production success remains deduplicated. A failed
dry-run may advance to production, and failed draft/release may switch between
production modes, only when the retry is independently authorized by normal
classification/cooldown or an explicit actor/reason grant. Production cannot
be downgraded to dry-run to bypass its gates. Default budgets
are three actual compile attempts and six reservation epochs; an explicit grant
authorizes only one next epoch and never changes signing/publication gates.

| Event | From | To | Constraint |
| --- | --- | --- | --- |
| reserve_upgrade | Stable dry-run SUCCEEDED | DISCOVERED / RESERVED | old exact run terminal, new UUID/fence, budget or one explicit grant |
| grant_upgrade | Stable dry-run SUCCEEDED | same result with authorization | reviewed actor/reason, only next fence |
| reserve_retry purpose change | FAILED dry-run | reserved draft/release | all normal retry gates, cumulative attempts preserved |

`stable_runtime_contract` exercises actual Stable Lock creation/reading with and
without Wayland, positive admission/guards, digest tampering, foreign runs,
manual retry/purpose upgrades, budget/grant consumption, latest-version behavior,
unknown legacy evidence and signing/publication workflow isolation. Existing
channel/security/qualification contracts remain enabled. Legacy helpers remain
for historical evidence and regression compatibility; fixed production router
paths share Coordinator instead of the old artifact-only dispatch decision.

Operational limits: native GitHub reruns (attempt > 1) are rejected; use an explicit
reviewed coordinator grant followed by a fresh workflow_dispatch for known terminal
failures. A pre-existing native rerun, missing initial legacy identity, or ambiguous
dispatch with no arriving verified worker may require operator reconciliation.
No timeout clears an uncertain reservation. No live signing/build/publication or
GitHub state-ref fault injection was performed; the bare local Git race test is
not a claim of deployed GitHub integration validation.

Rollback and maintenance: disable both routers and new admissions, preserve both
journal/index namespaces, reconcile active runs and unknown dispatches, then revert
PR 5/PR 4 integration in reverse order. Keep the shared core/observer until active
workers terminate. Never delete journal heads to force a build, never force-update
or merge their histories, and never re-enable legacy dispatch while reservations
are live. Monitor structured REVIEW/UNKNOWN logs and Git API rate limits; inventory
above 1000 identities requires a reviewed archive plan. Revalidate tests after any
matrix, signing-profile or source-policy change and review an explicit identity
policy migration before expanding identity fields.

## Isolated live Git API verification supplement

The supplemental validation PR adds `integration.py`, which uses the unmodified
GitRefStore and real GitHub Git API under `heads/coordinator-integration/v1/`.
The dedicated integration workflow is read-only globally; only its isolated
state-writing job receives Contents write. It has no Actions dispatch permission,
Environment, signing/publication credentials, or production build calls. Automatic
PR execution is confined to the named same-repository validation branch, with
matching checks in Python. Forks and pull_request_target are rejected. Future
manual execution requires the reviewed exact main workflow; there are no inputs.

Each execution generates an unpredictable run-specific session and exactly three
synthetic test refs. Existing refs are never adopted. The transport rejects
production journals, normal branches, tags, Releases, Actions dispatches, force
updates, deletion, foreign repositories, and trees containing executable files.
It retains test refs as audit evidence; the namespace is not queried by production
routers. Nothing checks out or executes these orphan state commits. No cleanup
uses an unsafe read-then-delete operation. Future retention maintenance must be
separately reviewed and limited to this test namespace.

Seven checks cover same-identity atomic creation, independent identities/channels,
competing single-parent updates, fresh-worker recovery, an accepted real write
with injected lost acknowledgement, a 503 injected before a ref request with no
replay, and rejection of an old synthetic worker after a replacement epoch. The
503/timeouts are transport fault injections around real storage operations;
no outage of GitHub infrastructure or actual Runner termination is claimed.
Synthetic run numbers are state fixtures, not Actions completion evidence. This
supplement validates the storage primitive rather than dispatch, production
signing or publication. Both failures and successes produce sanitized summaries
with the attempted test refs, session and API count; authentication is never
printed or stored. Offline integration_contract checks the allowlist, context,
workflow isolation and complete harness against the atomic in-memory transport.

Live result: [run 41456872443](https://github.com/billradar/rustdesk-custom/actions/runs/41456872443) succeeded on commit `9d43579c3cb88ef077dd4bc8134a7bc444592a37`, with all seven checks PASS and three isolated refs recorded in its uploaded summary. This is actual GitHub Git API storage verification, with synthetic run evidence and injected transport faults. A follow-up tightens object ownership as well: state trees can reference only blobs created by this test transport, and commits can reference only its state-only trees. The preceding five stage PRs remain unmerged; their prior green CI is unchanged. Live Environment protection and deployed production behavior remain independently unverified.
