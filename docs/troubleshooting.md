# Troubleshooting

[English](troubleshooting.md) · [简体中文](troubleshooting-zh.md)

Start by recording the workflow, job, custom commit SHA, upstream SHA, and first actual error. Do not infer the cause from the last line alone.

## Python cannot import repository modules

**Symptom:** `ModuleNotFoundError: No module named 'scripts'`.

**Check:** Run from the repository root; verify the workflow sets `PYTHONPATH: .` where needed; avoid invoking an importing script by a path that changes its module context.

**Fix:** Correct the working directory or module path and add a check. Do not mistake a missing module path for a missing dependency.

## Upstream SHA or provenance mismatch

**Symptom:** The resolved upstream SHA differs from the expected SHA, or artifact provenance checks fail.

**Check:** Whether the ref moved, a tag was confused with a SHA, prepared source used another SHA, or Standard/SOS came from different source identities.

**Fix:** Resolve and lock the exact SHA, then restart from source preparation. Never edit a manifest to manufacture a match.

## Patch application fails

**Symptom:** A patch cannot be applied, its hash differs, or patchset validation fails.

**Check:** Whether the patch targets this upstream commit, patch order and metadata are correct, or uncommitted edits are present.

**Fix:** Repair the patch in a clean isolated tree and rerun compatibility checks. Do not continue after ignoring the failure.

## A target is missing from the build matrix

**Symptom:** A platform job is absent or target planning rejects it.

**Check:** `enabled`, `support_status`, `required`, and runner in `metadata/platform/matrix.json`; then check for a matching reviewed profile in `metadata/platform/adapter-profiles.json`.

**Fix:** Update the matrix only after platform adaptation, upstream recipe review, and evidence checks. Changing only `enabled: true` is insufficient.

## Build succeeds but qualification fails

**Symptom:** Build jobs pass but aggregation or qualification fails.

**Check:** Required targets, missing artifacts, architecture/checksum/build-info, and whether every artifact shares the same upstream SHA, patchset, and build identity.

**Fix:** Repair the first failing validation and regenerate affected artifacts. Do not fill a batch with artifacts from a different run.

## Stable release is blocked

**Symptom:** Stable preflight or qualification rejects the run.

**Check:** Exact custom commit, upstream version and SHA, existing revision Draft/Release, and duplicate or incomplete identity evidence.

**Fix:** Run qualification for the exact commit/version and follow preflight results. Do not delete an existing Release or arbitrarily increase a revision to bypass a gate.

## Android production signing does not start or fails

**Symptom:** `android-sign` is skipped, the runner is unavailable, PIN preflight fails, or certificate identity mismatches.

**Check:** Repository/branch/event context, preceding build and qualification results, runner labels, Environment, Secret, and hardware identity metadata.

**Fix:** Repair permissions, runner, or identity configuration. Stop if PIN is unavailable or certificate fingerprints differ. Never print the PIN to debug.

## Documentation changes trigger full feature CI

**Symptom:** A documentation-only change runs expensive build jobs.

**Check:** Whether the classifier sees only documentation paths, or whether scripts, workflows, metadata, or dependencies were also changed.

**Fix:** Correct the classification or remove unintended functional changes. Do not weaken required checks, add broad `paths-ignore`, or disable contracts to avoid CI.
