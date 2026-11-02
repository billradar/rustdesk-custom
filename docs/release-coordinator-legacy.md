# Legacy evidence catalog: reviewed migration interface

This change depends on PR #177. It prepares a durable evidence catalog and the
shared read-side admission checks; it does not merge, activate either Router,
write production journals, create workers, dispatch, sign or change Releases.

## Storage and installation choice

The legacy archive is static reviewed evidence, distinct from live reservation
state. It is stored in the protected-main code tree under
`metadata/release/coordinator-legacy/objects/<sha256>.json`. Each object uses the
Coordinator canonical JSON encoding and names its immutable predecessor. A small
canonical `head.json` selects the complete append-only chain. An import is one
reviewed Git commit/PR updating this tree atomically. Git blobs/commits preserve
old bytes; the loader checks content digests, exact source-audit rows, predecessor
links and monotonic record retention. It rejects missing objects, forks, rollback
heads with retained descendants, rewritten records and unknown schemas.

This reuses the existing protected-main PR boundary without adding Contents write
or an online import job. No new mutable state ref, external database or production
credential is needed. Ordinary Coordinator state writers cannot update protected
main directly. Live journal reservations still use the existing atomic Git-ref
implementation; this catalog is neither a reservation lock nor worker state.

The protection has a precise limit: an actor authorized to merge reviewed code
could replace the reader and catalog together. It is not an independent
administrator-proof WORM service. Do not describe filename hashing as a server
rule preventing all privileged edits. The supported import CLI never deletes or
rewrites records; old Git objects and PR history remain the recovery evidence.
A future evidence source or resolution of v1 holds requires a separately reviewed
schema/source-audit migration, not editing the frozen original audit to fill gaps.

## Revalidated evidence and decisions

The source audit is pinned to exact SHA-256
`9cb18b82b52c6f4aa12c80dc6fe9b3053c090099708048787b94c65d59209b65`.
The implementation verifies that every imported row is byte-equivalent JSON data
from that reviewed audit, not merely a caller-supplied row labeled with its hash.
Every original archived JSON document is checked against its recorded raw SHA-256;
original verified ZIP digests are retained as prior audit evidence. This phase did
not download the ZIPs again or revalidate native Release asset digests.

Fresh read-only connector calls rechecked all 25 runs, 34 attempts and 951 job
records in 30-job pages. Capture validates repositories, main, workflow path,
custom SHA, event, latest attempt/status/conclusion/title, complete unique job
inventory and actual compile-step timestamps. Three older scheduled runs are
retained as scheduled review evidence; they are not relabeled workflow_dispatch.
Real compile attempts still total 31, and three no-build runs still count zero.
The same credential-free observation validator processes the captured API data;
no claim is made that a token-bearing CLI capture was executed locally.

| Evidence | Count | Admission effect |
| --- | --- | --- |
| Complete verified producer identity with actual compilation | 7 | SUCCESS_HOLD for the exact Build Identity; never builds again merely because Actions/Artifact history disappears |
| Incomplete identity | 17 | REVIEW_HOLD for the archived source SHA; missing SHA holds the whole channel |
| No-build reuse with incomplete original producer relationship | 1 | REVIEW_HOLD; never invent a successful producer or count a build attempt |

The catalog contains 25 records, with 7 success holds and 18 review holds. Three
of the 18 are no-build records (two are also in the incomplete-identity category).
Stable mode remains outside Build Identity and Nightly mode remains included.
Custom SHA and official run IDs remain provenance. Identity reconstruction uses
archived patch hashes and options, never today's patch files or policy defaults.
The original unavailable official run `41280309181` remains recorded; independently
verified successful official run `41366206478` confirms the same upstream SHA
without rewriting the old ID.

There is a concrete cutover blocker: Nightly records `36872771101`, `37185958897`
and `37279734509` lack an archived source SHA. They conservatively hold all new
Nightly identities until a separately reviewed resolution supplies trustworthy
scope. The seven exact successful identities still deduplicate immediately.
Do not activate this catalog assuming these holds are already resolved.

## Shared runtime behavior

Coordinator.claim reads the catalog before any journal reservation. SUCCESS_HOLD
returns a safe skip; REVIEW_HOLD raises for manual review; NO_OP makes no decision
and still runs all original history, journal, reconciliation and safety gates.
No catalog outcome grants permission to build, retry, sign or publish. A hold
creates no reservation, UUID, fencing token, worker/run index or attempt counter.
Structured logs identify the decision, channel, Build Identity and blocking run
IDs without claiming the existence of a build result record.

Both history adapters can use complete archived success evidence. They compare
live run provenance/attempt against the captured observation before replacing
Artifact lookup; a native rerun, changed source/custom SHA, conclusion, event,
workflow or repository fails closed. Stable checks a verified archived source
SHA before demanding producer success, so an unrelated old review/no-build record
does not block a new source; matching/unscoped evidence still holds. Unknown
records never become successful aliases. Missing future history still uses the original conservative path.
Workers, including sparse-checkout production signing guards, do not load this
catalog and acquire no new permissions or secrets. Stable Lock, source resolvers,
Wayland/matrix, Android Environment/Runner and publication/digest gates are unchanged.

## Offline interface

Run from a reviewed repository checkout, with its declared Python dependencies:

```sh
# Optional fresh read-only capture with an already provisioned read token:
python3 -m scripts.release.coordinator.legacy_import capture --observations /safe/new-observations.json
# Assemble a candidate catalog in a separate workspace and review its Git diff:
python3 -m scripts.release.coordinator.legacy_import prepare --observations /safe/new-observations.json --directory /safe/candidate-catalog
python3 -m scripts.release.coordinator.legacy_import check --directory /safe/candidate-catalog
python3 -m scripts.release.coordinator.legacy_contract
```

Capture accepts only GET under this repository's Actions run endpoints. It never
calls a mutation API. Preparation refuses replacement/deletion of existing rows,
writes a deterministic pending intent before exclusive object creation and is
idempotent for identical input. A restart with exactly the same validated input
can reconstruct an object missing after that intent; different input is rejected.
A crash after complete object creation resumes only after the entire chain is
validated. Standalone resume refuses missing objects; truncated/conflicting
objects remain blocked. This is offline recovery, not a claim of an
online multi-file filesystem transaction. Never commit a partial workspace.

Concurrent PR imports made from the same tip produce distinct child objects;
combining them silently creates a fork that the contract rejects. Regenerate an
append-only union from the current reviewed tip. No force-push, reset, ref deletion
or competing importer is part of this protocol.

## Validation and cutover limits

The new contract executes the real catalog reader/import preparer and shared
Coordinator admission with no credentials. It covers parallel duplicate Routers,
missing/expired Artifacts and original official run IDs, no-build accounting,
native rerun drift, source/JSON tampering, incomplete evidence, identity policy
compatibility, duplicate imports, import forks, interrupted preparation, schema
rejection, 503/incomplete job inventory and worker/signing isolation. Existing
Coordinator and channel/security contracts remain enabled.

Before any actual installation, separately authorize the merge/cutover, stop new
admissions and drain/reconcile old Router and worker runs. Recheck current run
inventory against this snapshot, including native reruns and newly created runs;
regenerate/review evidence if it changed. All running code must use the same
reviewed catalog commit. Online hot import during active admissions is unsupported;
there is no cross-version catalog/journal transaction. This PR alone is not
production migration completion or evidence that a new native package builds.

Rollback: stop admissions, retain this catalog, all immutable evidence objects and
journal/index refs, then reconcile active/unknown work before reverting runtime
integration. Do not remove a success hold or review hold to force a rebuild, and
do not re-enable artifact-only routing while reservations are active. Restoring
an older catalog with removed evidence is an explicit reviewed migration rather
than routine rollback.
