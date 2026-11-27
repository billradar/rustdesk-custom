# CI upstream source routing — reviewed exact source

Ordinary push/PR CI checks an immutable reviewed source; explicit upstream refs and the separate six-hour upstream-main monitor retain the existing fail-closed compatibility checks.

- Official RustDesk 1.5.3 tag: `95cca3f661f635b3cc85c04935fe8d96d8f432ef`.
- Source identity audit: `docs/audits/stable-1.5.3-admission/review.json` (historical source review, not proof of current patch build).
- Patch Profile v3 revision 9; Common SHA256 `96c198122eb8053deac05c7d22a08af8503701b2fb63aa2f94564bc8296dd3d2`, SOS SHA256 `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`.
- Manifest `metadata/build/ci-upstream-baseline.json` binds exact source, numeric version, Profile, revision and patch hashes. Full CI is required; no prior complete CI success is claimed for this new baseline until the new run finishes.

The older [run 44107538838](https://github.com/billradar/rustdesk-custom/actions/runs/44107538838) tested `54416dcaa127d209f2cfbdc4b08235bae78ccfe6` with v3.7. It is historical evidence only, not current baseline qualification.

The integrated #274 branch requires exact SHA-first selection unconditionally and rejects unknown fallback and candidate profiles. The pre-integration #275 branch alone used the legacy selector after verifying the source admission audit. No new Stable/Nightly admission or release authority is granted. Any baseline or patch revision/hash change must be reviewed and validated by full CI. Explicit upstream-main checks remain separate and are not suppressed.
