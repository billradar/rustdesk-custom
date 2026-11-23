# CI upstream source routing — 2026-11-23

## Purpose

Ordinary push and pull-request CI must validate repository changes against an **immutable, previously passing official RustDesk source**, not against a moving upstream main that can change during an unrelated dependency update. The latter is still tested independently and must remain fail-closed.

## Reviewed normal CI baseline

- Official repository: `rustdesk/rustdesk`
- Source commit: [`54416dcaa127d209f2cfbdc4b08235bae78ccfe6`](https://github.com/rustdesk/rustdesk/commit/54416dcaa127d209f2cfbdc4b08235bae78ccfe6)
- Official source version: `1.5.3`
- Patch Profile: `v3` (Standard and SOS)
- Previous successful PR CI: [Run #44107538838](https://github.com/billradar/rustdesk-custom/actions/runs/44107538838)
- Manifest: `metadata/build/ci-upstream-baseline.json`

`scripts/release/channel.py resolve --channel ci` reads this manifest, requires a full official source SHA, checks its numeric version and the explicitly maintained Patch Profile, verifies patch integrity, resolves the immutable SHA on GitHub, and rejects an identity mismatch. Ordinary PR/main CI retains all existing compatibility and qualification gates; this is not a skipped test or a forced green result.

## Independent upstream main checks

`.github/workflows/upstream-main-compatibility.yml` already checks official current main on the existing 6-hour schedule or manual dispatch. It passes `--ref "$UPSTREAM_SHA"` explicitly, bypassing the normal CI baseline selection and retaining unknown build-adapter and patch-profile failures. Manual CI dispatch can also override `upstream_ref` to test another official upstream commit.

## Boundaries

This does **not approve** the unreviewed `51f94394` build adapter, publish artifacts, promote Stable, merge v4, or change PR #274. A future CI baseline must be an explicitly reviewed manifest update supported by a successful, inspectable compatibility CI run. The upstream main monitor may still fail when official HEAD adds unreviewed build interfaces: such failures remain visible.
