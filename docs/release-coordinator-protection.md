# Coordinator ref protection validation

This follow-up depends on PR #174, which depends on the five implementation PRs and isolated storage PR #173. None is merged. The user authorized isolated protection verification followed by production journal/index protection, not activation, merging, signing or publication.

## Reviewed rules

| Namespace | Rules | Mirror ruleset |
| --- | --- | --- |
| `refs/heads/coordinator-integration/v1/stable/*`, `.../nightly/*` | deletion + non_fast_forward | 26375171 |
| `refs/heads/coordinator-integration-index/v1/*` | deletion + non_fast_forward + update | 26375414 |

Both mirror rulesets are active with empty bypass lists. Their exact API scope and enforcement are checked before state creation. The administrator-side API audit confirms the empty bypass lists. GitHub omits bypass actors for tokens without administration access; the live harness reports this visibility limitation explicitly, rejects any visible nonempty bypass list, and proves its own token is subject to enforcement through actual rejected writes. It does not claim to have audited actors hidden from that token. Index updates have no fetch/merge exception. Production equivalents are the reviewed JSON proposals under `docs/audits/coordinator-preactivation-20261102/`; production application remains pending live test evidence.

## Validation and risk

The credential-free eight-test protection contract exercises the actual harness with a protected atomic in-memory transport. It verifies rule drift stops before writes, unauthorized/429/5xx failures do not count as rejection proof, successful forbidden writes fail, existing test refs are never adopted, non-owned refs cannot be deleted, exact trusted workflow context, and isolated permissions. The existing five-test integration contract remains unchanged apart from internal explicit context parameters.

The live workflow has Contents read globally and Contents write only on one isolated hosted job. No Environment, signing secrets, publication App, Actions write, fork write event or production workflow dispatch is used. Each successful run retains five synthetic state refs: two canaries and three storage-race refs. The only deletion requests concern the newly created disposable canaries and are expected to be rejected. Unexpected acceptance fails the workflow. Test commits contain state/event JSON only and are never executed. 503 and lost acknowledgements are fault injections, not claims of a real GitHub outage.

The probe compares exact state heads before and after every rejection. Journal positive controls use the unmodified GitRefStore. Index positive creation and rejected fast-forward use the same root/child state commits, proving the update test is a real fast-forward. Offline tests alone do not establish server enforcement; live run and exact-head CI must be recorded separately.

## Rollback and maintenance

This PR adds validation only. Reverting it removes canary execution without changing Router behavior. Retain all state refs and protections as audit evidence. Do not remove protections or force/reset a journal to recover a worker. Production protection rollback requires disabling admissions, reconciling active/unknown dispatches and separate review; simply removing protections is unsafe. A future ruleset ID or namespace change must update both the verifier and its reviewed contract. Existing unmerged activation and legacy-migration risks in PR #174 remain open.
