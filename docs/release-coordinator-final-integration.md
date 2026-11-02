# Final integration and controlled cutover

This integration collects the independently reviewed implementation PRs #168–#179 and the final source-scope fix into one main-targeted review. The original staged commits and PRs remain audit evidence. PR #167 is already merged into the unchanged integration base `95abfaf706766f670dddcecea41530320c0ebb66`.

## Final correction

The three old Nightly runs retain their original catalog records. A pinned, versioned functional metadata overlay binds the recovered source evidence to each exact record. It narrows review holds to the two verified upstream SHAs, without inventing release mode, official-run identity, Wayland policy, signing success or modern build success. Matching sources still require review. Other sources proceed through existing history, atomic reservation and downstream gates. The history adapter explicitly honors catalog review decisions even for old titles without modern option suffixes.

## Validation

Local execution on the final correction passed all 27 commands from the repository contract and the compatibility workflow's release/domain contract step, including all coordinator contracts, router regressions, Stable Lock, Wayland and Android signing contracts. The legacy contract contains 26 tests, including four new source-resolution fault/regression tests. GitHub CI and exact-head Codex review must also complete before this change is considered merge-ready; their actual results belong in the PR.

Earlier isolated GitHub API storage/protection checks are documented in the staged reports. They are historical evidence for those commits, not a claim that real production build/sign/publication ran on this integration. This change has not dispatched a production workflow, imported worker state, signed an artifact, published/deleted a Release or merged a PR.

## Merge and cutover conditions

The integrated workflows enable coordinator routing. **Merging changes the production admission path.** Do not merge merely because code checks are green or assume scheduled routers stay idle.

1. Obtain explicit merge/cutover authorization for the final reviewed head. Pause Stable and Nightly router workflow entrances in GitHub and prevent concurrent manual Tag/Nightly admissions during the maintenance window. Do not cancel or delete running production jobs merely to shorten the window.
2. Inventory and drain/reconcile every queued/running Tag/Nightly job and reservation. Refresh upstream/run/artifact inventory since the frozen preactivation audit. New unknown history remains fail-closed; update reviewed evidence through a PR if needed. Recheck active journal/run-index protection rules and exact main/PR heads.
3. Merge the final integration through the protected PR path. Do not merge the old dependency PRs separately afterward; close them as superseded only after verifying the actual integration merge commit and tree.
4. Resume Nightly first under explicit authorization, verify journal/index ownership, exact-source admission and duplicate suppression. Verify the downstream signing/Draft gates through their separately authorized normal operation. Resume Stable only after Nightly evidence is satisfactory. Public publication remains separately authorized.
5. Record actual workflow IDs and outcomes. A skipped build, missing artifact or pending check cannot be reported as a completed production validation.

## Rollback and maintenance

Pause admissions again and reconcile live jobs before rollback. Revert the integration through a new protected-main PR; preserve the Git journal, immutable run indexes, original legacy catalog and all audit evidence. Never force-update/delete state refs, silently re-enable old deduplication over live managed work, or treat an empty ledger as proof that no build happened. Roll forward a narrow compatibility fix when a running managed build still needs its guards.

For later source-scope changes, preserve the original records and existing resolutions, add reviewed evidence, update the pinned metadata digest, and rerun the catalog, runtime and channel contracts. The catalog is protected Git history, not an administrator-proof WORM store. Source-only recovery cannot authorize retries or certify modern build/signing/publication results.
