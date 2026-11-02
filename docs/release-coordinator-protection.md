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

## Executed result and deployment hold

On commit `9039409dc7902537c9dd859fb37562b9142bf33d`, [live run 41467995091](https://github.com/billradar/rustdesk-custom/actions/runs/41467995091) passed: three positive controls, five actual HTTP 422 rejections with unchanged heads, and all seven protected storage race/fault checks. The [sanitized summary](audits/coordinator-preactivation-20261102/ref-protection-live-summary.json) records all five retained test refs. The low-permission token did not expose bypass actors, as explicitly reported. Administrator-side reads independently confirmed both empty bypass lists. Codex Code Review for this exact commit completed without findings.

[CI run 41467994953](https://github.com/billradar/rustdesk-custom/actions/runs/41467994953) passed repository architecture and all release/domain contracts but failed `compatibility / Resolve official source and patchset` at `Fail-closed official build adapter`. The resolved official SHA was `6aec3069aec486ad7df07429a0a1ee411fc8d73a`, observed build interface signature `f13aa9d4edd1afa76be5803dd3c28cf01785c359bd393e3d2b090312797308a6`. The closest approved profile is `reviewed-151-1297da`, baseline SHA `1297da6d186e58d9096be24072ae3998cdbbf8fe`. Among critical file hashes, `.github/workflows/bridge.yml` changed from `b519191d9d9bd7f4350cc978c8fd6db366cf3152206835620a73f09a165b4d05` to `bc3714806b91f7a99748e68540c136103c7a7f7333703047e75a6f21bae61ae7`. This is evidence of an unapproved interface, not proof that the new interface is unsafe or safe. No unknown upstream code was executed in the local diagnostic.

The same failure was reproduced locally using the exact upstream static files. `scripts/build/build_adapter.py` and `metadata/build/adapter-profiles.json` are byte-identical to protected main, with SHA-256 `41f9154ac078ca06cad876586aebae381dcf488a6e01b36b29c215b5a215adae` and `c105073cb743596166ccaa2d0fe411cd7424bf161f3e85d5e5fb4eb1d3af7629` respectively. The Coordinator PR did not change either. Do not retry an unknown interface as an infrastructure fault, approve its hash without staging review, pin the automatic source to hide the failure, or call the full CI green.

Production journal/index protection remains **not applied** because the required phase CI is not fully passing. Only the two isolated mirror rulesets were created. No PR was merged, Router activated, production state imported, signature requested or Release changed. The existing main ruleset is unchanged. Unblock by separately reviewing the upstream bridge interface in staging, validating compatibility, then rerunning applicable CI before production protection application. Later documentation-only checks do not replace this failed functional CI.
