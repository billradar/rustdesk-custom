# Patchset version migration: staged delivery

Baseline main: `2b871ad992a62fcac2d39b83e6ad045f3083b916`. The four review stages form a dependency chain; none is merged, no production state is changed and no release/signing workflow is dispatched.

| Stage | Review artifact | Result |
| --- | --- | --- |
| 1 | [#192](https://github.com/billradar/rustdesk-custom/pull/192) | Historical audit and explicit read-only legacy mapping, unknown spelling rejection, blocked migration diagnostic |
| 2 | [#193](https://github.com/billradar/rustdesk-custom/pull/193) | Base-anchored bump/verify/render, reviewed structured history, generated Changelog and read-only PR gate |
| 3 | [#194](https://github.com/billradar/rustdesk-custom/pull/194) | Manifest readers, shared Coordinator identity policy v2, Stable/Nightly Notes, immutable target collision and blocked production cutover |
| 4 | Current branch `patchset/04-client-regression-20261103` | Explicit client semantics, legacy tag/source/hash mapping, independent Nightly content metadata and regression evidence |

## Actual version lineage

Legacy `v1.5.0-custom.v2.6` was a per-upstream release allocation with Common `c35f6c64...`; legacy `v1.5.1-custom.v2.1` used Common `ba803951...`. Their signed packages, refs, Draft IDs and producer metadata are unchanged. They must not be relabeled as historical content revisions. The full exact mapping and the limited archived v2.5 observation are in the phase-1 audit.

The reviewed metadata migration reserves v1.1 / v2.7 baseline identities at unchanged patch hashes. v2's 7 comes from the maximum observed old allocation 6 plus one, not from guessing the user's example or counting commits. Early missing allocation identities remain unknown; activation must recheck the live inventory.

Phase 4 changes the actual Common update-policy patch in both generations. The dedicated bump script consequently produces **v1.2 / v2.8**, based exactly on phase 3, with reviewed Common-only delta, before/after hashes, reason, compatibility, limitations and references. SOS hashes do not change. Thus a subsequent official 1.5.x upgrade with identical patches retains v2.8. The target would be `v1.5.1-custom.v2.8` for the audited current Stable; this is not an existing/published release claim.

## Compatibility and provenance

Modern release update eligibility requires the explicit `patchset-content-v1` marker and a Patchset Version matching the Tag, complete source metadata and patch/Build Identity hashes. Unmarked legacy compatibility is limited to the two audited tag/source/hash tuples. Unknown same-format tags fail closed. Numeric upstream version comparison remains first, then numeric Generation/Revision for equal upstream versions; older upstream versions cannot win by having a larger revision. Exact Standard/SOS, architecture, package type and Wayland asset matching, API digest/size verification and user-confirmed installer handoff are preserved.

Prepared-source, client and package metadata carry `patchset_version`, `version_semantics`, and `build_policy_sha256`. Stable Lock and Nightly aggregation check these against current manifests and actual source inputs. Native packages now preserve the Stable revision from source identity. CI/Nightly keep their Stable `revision=null`; About shows an explicit `-ci`/`-nightly` suffix with the content version. Native/package/protocol versions and package names remain unchanged.

## Validation evidence

Machine-readable local evidence: [validation.json](audits/patchset-version-20261103/validation.json).

- Repository architecture contract PASS under normal packaging umask 022.
- Complete compat-check domain list plus explicit client/branding checks: 34 modules, 492 Python tests, zero failures and zero skips. Exact official source snapshots were supplied to the two adapter tests that initially skipped. The runner also needs `PYTHONPATH=.` as defined by CI; an initial local invocation omitted it and was corrected.
- New Rust policy compiled/executed with rustc 1.99.1: 9 tests PASS. This is policy verification, not a complete RustDesk native build.
- v1 Standard/SOS patches applied independently to exact official `6c578292...` with its real hbb_common gitlink; v2 Standard/SOS to exact official `23e5bb47...`: all four PASS, using the actual `apply_patches.sh` checks.
- Source update/FFI policy contract and actual About identity injection checked in these patched trees; Stable/Nightly and both variants carry consistent content versions and separate Stable eligibility.
- Client source patch content changed, so the actual `bump` and `verify --base phase3 --check` were exercised and both generations advanced once. No revision is allocated during builds.

At the phase-4 submission snapshot, #192/#193/#194 CI finished successfully and their exact heads had completed Codex reviews with no findings. Phase-4 CI/Review is not awaited, as requested. Passing phase-1/2/3 checks is not evidence for the final phase-4 head. Isolated state-writer workflows skip on PR events as designed; no production canary or signing is invoked.

## Remaining release blockers

This is implemented and locally validated code for review, **not an activated safe migration**. `patchset-cutover.json` and `content.require_cutover()` deliberately prevent new production lock creation, policy-v2 admission and release writers after this staged code is integrated. There is no Boolean/Environment bypass.

Before activation: establish quiescence, reconcile old workers/journals and attempt/fence state, review legacy v1→content identity aliases/holds, re-read current Tag/Draft/Release occupancy, and require the up-to-date Patchset version status check in main protection (or equivalent merge queue). The baseline alias must not authorize rebuilding historical successes or reinterpret incomplete producer evidence. Repository-controlled build policy hashing does not claim full external runner reproducibility; review all effective external inputs, including the existing frozen branding Variable source policy, before approving cutover.

No existing ref/Release/package/signature was moved/deleted/overwritten, no main push or PR merge occurred, and device installation, production signatures, runtime UI and remote sessions remain untested. Do not merge stages piecemeal during live release operations. Revalidate the chain against latest main when retargeting each dependency after integration.
