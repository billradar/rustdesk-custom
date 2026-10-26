# Operations guide

[English](operations.md) · [简体中文](operations-zh.md)

## Set up

Repository tools require Python 3 and Git. Full builds also need platform-specific RustDesk, Flutter, Rust, native toolchains, and workflow dependencies.

~~~bash
git clone https://github.com/billradar/rustdesk-custom.git
cd rustdesk-custom
git checkout development
python3 -m pip install -r requirements.txt
~~~

## Branches and pull requests

The long-lived branches are `main` (protected integration/release baseline) and `development` (shared development/integration). Normal changes are prepared on `development` and proposed to `main` through a PR. Do not write directly to protected `main`.

Before work, inspect both branch heads, merge-base, ahead/behind counts, and relevant commits. A matching file tree does not prove matching Git history. Do not reset, force-push, rebase, delete, or replace shared branch refs without explicit authorization and SHA verification. A created PR is not a merged PR; verify the merge commit and branch comparison afterward.

Use `.github/PULL_REQUEST_TEMPLATE.md`. Describe the motivation, changes, checks actually run, impact, risks/rollback, and operational notes. Mark unrun checks accurately.

## Understand and validate changes

1. Locate implementation in `scripts/`, `.github/workflows/`, `.github/actions/`, or `metadata/`.
2. Find the caller workflow and contract checks.
3. Confirm authoritative configuration before changing docs or copying settings.
4. Determine whether the change is documentation-only or functional.
5. For release, signing, or provenance changes, identify security boundaries and failure conditions.

Run the repository contract and checks for the changed area:

~~~bash
python3 scripts/validation/repository_contract.py
~~~

Functional changes that build artifacts also require the compatibility, build, artifact, and aggregation checks used by GitHub Actions. Documentation-only changes do not require a RustDesk build; use lightweight documentation checks. Do not relax functional contracts to make documentation checks pass.

## Stable operations

Use **Stable Release Pipeline** (`.github/workflows/tag.yml`) from `main`. `upstream_ref` accepts an official Stable tag; the workflow resolves the exact version and SHA. Empty selects the latest official Stable. `include_wayland` defaults to true and includes both experimental Wayland DEBs.

Start with `dry-run`. After checking source SHA, patchset, revision, required targets, and aggregation qualification, choose `draft` to create a private Draft. Choose `release` only when intentionally publishing. Existing revisions are revalidated; mismatched or incomplete releases are never overwritten.

**Upstream Stable Router** checks hourly and routes the latest official Stable to a signed private Draft on `main`. It reuses release preflight, skips a complete matching build or active run, and never publishes publicly.

## Nightly operations

**Upstream Nightly Router** checks official successful Nightly builds at UTC minutes :07, :22, :37, and :52 (GitHub schedules may be delayed). It pins the exact upstream run and SHA.

For a manual run, use **Nightly Build Pipeline** on `main`. `official_run_id` can be empty to resolve the latest successful official run or set to a successful `flutter-nightly.yml` run ID. `expected_sha` optionally requires an exact 40-character SHA. `release_mode` supports `dry-run`, `draft`, and explicitly requested `release`; `include_wayland` defaults to true. Production modes require platform and Android signing gates. `development` supports dry-run only.

Matching successful or active runs are deduplicated by source identity, custom commit, mode, and Wayland selection. Automatic retries are bounded. Diagnose the first failing step before retrying; do not fabricate identities or combine artifacts from different runs. Public Nightly prereleases require an explicit `release` dispatch and complete matching Draft.

## Wayland variant

`wayland.yml` is a reusable workflow called by Stable/Nightly, not a manual release entry point. The parent `include_wayland` input controls it. Both x86_64 and ARM64 DEBs must pass source, package, and aggregation checks. See [Wayland gates](wayland-unattended.md).

## Results and retries

- Record the workflow URL, branch/commit, upstream version/SHA, patchset, Wayland selection, and final mode. Distinguish job success, qualification, Draft creation, and public release.
- Start diagnosis at the first failed step and verify build identity; see [Troubleshooting](troubleshooting.md).
- For transient runner/network failures, use **Re-run failed jobs**. If code, source SHA, patchset, or build options changed, dispatch a fresh run and validate again.
- A deduplication skip is not a failure. Confirm the successful run or complete Draft matches the same identity.
- Production signing, Draft creation, and public release must use protected GitHub Actions. Never put PINs or key material in ordinary runners or logs.

## Documentation and production safeguards

Pair English and Chinese guides as `name.md` and `name-zh.md`; link to the same language. Keep paths, workflow/input names, and commands current. Separate implemented, tested, and released status. Production signing and releases must use protected workflows; stop when identity, source, runner, or remote asset checks are uncertain.
