# AGENTS.md

# RustDesk Custom — AI Agent Operating Contract

This file is the repository-wide operating contract for AI coding agents working in `billradar/rustdesk-custom`. Read it before making changes. Treat current source code, workflow definitions, machine-readable metadata, and executable contracts as authoritative; prose documentation and conversation history are not substitutes for inspecting the current repository.

## 1. Project purpose and non-goals

`billradar/rustdesk-custom` maintains an auditable customization, compatibility, build, qualification, and release system for the official `rustdesk/rustdesk` upstream. Customizations are maintained as controlled patchsets rather than by silently replacing upstream source.

The repository produces Standard and SOS variants, prepares source trees, validates compatibility, builds configured targets, verifies artifact provenance, records qualification, and supports a separately protected Android production-signing path.

This is not a disposable source fork. Preserve reproducibility, traceability, fail-closed validation, release safety, and the separation between ordinary CI and privileged production operations.

## 2. Authority and sources of truth

When information disagrees, use this order and investigate the mismatch instead of guessing:

1. Current workflow definitions and reusable workflow/action implementations for triggers, inputs, permissions, job conditions, dependencies, and artifact flow.
2. Executable contracts and scripts for validation and release/signing behavior.
3. Canonical machine-readable metadata for platform policy, build profiles, release identity, and signing identity.
4. Documentation for explanation and navigation only.
5. Historical CI runs, PR descriptions, old commits, and conversation history as historical evidence only—not proof of current behavior.

Important canonical locations include:

- `.github/workflows/` and `.github/actions/`: orchestration, permissions, gates, and reusable execution.
- `scripts/upstream/`, `scripts/source/`, `scripts/build/`, and `scripts/platform/`: upstream resolution, source preparation, build adapters, platform execution, packaging, and artifact validation.
- `scripts/release/`: channel identity, preflight, qualification, aggregation, naming, and publication gates.
- `scripts/validation/`: repository contracts, change classification, compatibility validation, configuration checks, and repository scanning.
- `scripts/signing/` and `tools/android-signing-bridge/`: Android signing policy and hardware-signing bridge.
- `metadata/platform/matrix.json`: configured platform/target policy.
- `metadata/platform/adapter-profiles.json` and `metadata/build/adapter-profiles.json`: reviewed build/adapter profiles.
- `metadata/release/identity.json` and related release metadata: canonical release identity and revision data.
- `metadata/signing/android-standard.json` plus the identity metadata actually consumed by the signing workflow: Android signing identity.
- `patchsets/`: reviewed customization inputs.
- `requirements.txt`: Python dependencies for repository tooling.

Do not create a second configuration source by copying mutable metadata into scripts or documentation. Verify exact paths in the current tree before referring to them; legacy names may have been removed.

## 3. Current workflow responsibilities

This is a responsibility map, not a replacement for reading each workflow. Inputs and implementation may change; inspect the current file before invoking or modifying it.

- `.github/workflows/ci.yml`: classifies changes. Documentation-only changes take a lightweight path; functional or ambiguous changes go through source resolution, compatibility checks, and qualification.
- `.github/workflows/compat-check.yml`: reusable compatibility/contracts pipeline for an explicitly supplied upstream repository/ref/SHA and channel.
- `.github/workflows/prepare-source.yml`, `build.yml`, and `build-platform.yml`: prepare source, plan/build configured targets, and pass artifact identity between stages.
- `.github/workflows/build-stable-windows.yml`, `build-stable-platforms.yml`, and `build-stable-android.yml`: Stable target build entry points used by the release pipeline.
- `.github/workflows/tag.yml`: Stable pipeline, including upstream resolution, release/revision preflight, build, artifact aggregation, gated Android signing, and Dry-run/Draft/Release decisions.
- `.github/workflows/nightly.yml`: dispatch-driven Nightly build/artifact pipeline. It is not itself the upstream polling router and must not publish a Stable release or perform Android production signing.
- `.github/workflows/upstream-stable.yml`: periodically detects the official upstream Stable release and routes a deduplicated Stable dry-run; the router is not authorization to publish a release.
- `.github/workflows/upstream-nightly.yml`: periodically discovers and validates an official scheduled upstream Flutter Nightly run and its published Nightly assets, then routes the locked SHA to the downstream Nightly build workflow.
- `.github/workflows/upstream-main-compatibility.yml`: periodically checks compatibility against the official upstream default branch. This signal is separate from Stable release and Nightly artifact routing.
- `.github/workflows/android-yubikey-signing-test.yml`: manually invoked, explicitly authorized signing smoke test. It is not a Stable release and must not publish one.

Do not assume a workflow exists based on an old document or a familiar name. For example, do not refer to an `upstream-event-router.yml` unless it exists in the current tree.

## 4. Upstream identity, routing, and reproducibility

The only supported upstream identity for normal project flows is the official `rustdesk/rustdesk` repository unless a reviewed workflow explicitly says otherwise.

- Resolve an upstream tag/ref/branch to one exact commit SHA before building. Propagate that SHA through preparation, compatibility checks, build jobs, artifact manifests, qualification, and release metadata.
- A branch name or moving tag is not a durable source identity. Never infer the built commit from a display name or filename.
- Stable, Nightly, and upstream-default-branch compatibility are separate channels with separate intent. Do not let a change to upstream `main` implicitly trigger a Nightly release, and do not treat Nightly artifacts as Stable.
- The Nightly router must fail closed unless it can validate the official scheduled Flutter Nightly workflow run, its successful completed status, the matching 40-character upstream `head_sha`, and the official published Nightly prerelease/assets required by the router. It also checks that release assets are fresh relative to the run and guards against the release changing during routing.
- The downstream Nightly workflow must validate routed provenance again. Do not weaken or remove this second validation merely because the router already checked it.
- The Stable router's automatic route is a dry-run. Router success is not publication authorization.
- Preserve duplicate suppression and safe retry behavior. A matching active run must not be duplicated; a prior failed or absent run may be retried according to the workflow's current logic.
- Do not hard-code a moving upstream revision to make CI green. Test fixtures must never be accepted as production source or payload.
- When modifying patchsets, identify the affected upstream version boundary, verify the intended patchset is selected, apply the patches to the exact source, inspect the resulting diff, and run the relevant compatibility checks.

## 5. Change classification and CI

Change classification is fail-closed:

- If every changed file is confidently documentation-only, classify as `DOCS_ONLY`.
- If any changed file is functional or ambiguous, classify as `FUNCTIONAL`.

Functional changes include, at minimum, workflows/actions, scripts, metadata, patchsets, build/platform configuration, dependency declarations, packaging inputs, and signing/qualification code. A mixed documentation/functional change is functional.

Documentation-only work should receive appropriate lightweight validation. Do not run expensive builds, production signing, or release jobs unnecessarily for prose-only changes. Conversely, do not classify functional changes as documentation-only to save CI time. Avoid path filters that leave required checks permanently pending.

`force_rebuild` is a current input of `.github/workflows/ci.yml` and explicitly requests the functional/full CI path. Input names and semantics are workflow-specific; do not assume this input exists on other workflows. `promote_stable` is not a current interface contract: do not reintroduce it or document it as an active input without an explicit design change.

Treat CI as an executable policy boundary, not a status badge. Do not bypass a failing architecture, source-identity, patch, compatibility, artifact, qualification, provenance, or signing gate to obtain a green run.

## 6. Branch and pull-request model

The only intended long-lived branches are:

- `main`: protected stable integration and release baseline.
- `test/development`: shared development and integration branch.

The normal workflow is to make scoped changes on `test/development`, validate them, then open a pull request from `test/development` to `main`. Do not create `feature/*`, `fix/*`, or other temporary branches unless the user explicitly requests them or a platform constraint makes one necessary. Do not commit directly to protected `main`.

At the start of a cycle, inspect both branch heads and their ancestry. Prefer synchronized branch tips before starting new work, but never assume that matching trees prove matching history. Check the merge base, ahead/behind counts, unique commits, and changed files.

Git history is audit data. For the long-lived development-to-main integration, prefer a normal merge commit; do not routinely squash or rebase away the development history. Do not rewrite a shared branch merely to make its graph look cleaner.

Never reset, force-push, rebase, replace a branch ref, delete a shared branch, or rewrite history on `main` or `test/development` without explicit user authorization. Before any authorized destructive branch operation, inspect both heads, ancestry, unique commits, tree equality, shared-branch impact, and the exact expected target SHA. Use an expected-old-SHA guard when the available API supports it.

A created PR is not a merged PR. A matching file tree is not proof that commits were merged. Verify the resulting commit, merge state, and branch comparison after integration.

## 7. Stable release and qualification boundaries

Stable release flow must preserve the association among:

- custom repository commit SHA;
- official upstream ref and resolved SHA;
- selected patchset and its content identity;
- patch revision/release identity;
- target/variant and build configuration;
- artifact hashes, verification reports, and qualification evidence.

Do not reuse a qualification record across a different custom commit, upstream SHA, patchset, revision, target, or build configuration. Preflight and duplicate-release protections are mandatory, not optional cleanup.

The Stable pipeline currently distinguishes Dry-run, Draft, and Release modes. Read the actual `tag.yml` input choices and job conditions before dispatching. Dry-run is not a published release; Draft is not a published release; Release publication must pass the full aggregate gate and be explicitly requested by the user. Do not infer authorization from a scheduled router run, a green build, or the existence of an older draft.

Never silently delete, overwrite, or bypass an existing release/revision to get past preflight. If release identity or prior artifacts conflict, stop and investigate.

Configured target support is determined by canonical platform metadata and the current workflow matrix. Do not make blanket claims that every historical target is currently supported, required, built, or release-qualified. Build support, artifact validation, production signing, and real-device/runtime validation are different states.

## 8. Android production signing and secret handling

Android production signing is a privileged operation, isolated from ordinary CI and Nightly builds.

- Production signing must occur only through the intended Stable workflow, on the required dedicated self-hosted runner, on `main`, with the expected GitHub Environment and explicit workflow conditions satisfied.
- Current signing boundary: GitHub Environment `android-production-signing`; Environment Secret `YUBIKEY_PIV_PIN`; dedicated runner labels `self-hosted`, `linux`, `arm64`, `rustdesk-signing`, `android-signing`, `yubikey`; YubiKey PIV slot `9C`; PKCS#11 object ID `02`. Verify these against the live workflow and identity metadata before changing them.
- Normal CI, Nightly, compatibility checks, and ordinary build jobs must not access the production signing Environment, PIN, YubiKey, PKCS#11 device, or production signing action.
- The smoke-test workflow is separately gated by a manual, explicit authorization input and must not publish or promote artifacts.
- Never commit keystores, private keys, PINs, passwords, tokens, PKCS#11 credentials, or sensitive signing output. Never put a PIN in command-line arguments, logs, PRs, issue comments, artifacts, or documentation. Bind secrets only to the narrow steps that need them.
- Do not replace hardware signing with an undisclosed software key, add a repository-secret fallback for the production PIN, weaken preflight, or bypass the dedicated runner/Environment gates.
- The production path requires APK Signature Scheme v2 and v3 to both be enabled and independently verified for every required signed APK. Do not weaken this to “v2 or v3”.
- Validate package identity, certificate fingerprint, version, ABI, APK hash, signature schemes, and provenance using the current metadata and verification reports.
- A successful Android build does not prove a production signature. A successful signature operation does not prove legacy signing-identity continuity, device installation, upgrade compatibility, or key rotation. Never claim legacy identity migration or v3 proof-of-rotation unless the relevant certificate and device-level evidence actually establishes it.

## 9. Repository contracts, tests, and dependencies

For repository structure/policy changes, inspect and run the repository architecture contract:

```bash
python3 scripts/validation/repository_contract.py
```

Then run the relevant domain contracts and tests identified by the changed workflow, including release qualification, signing, source preparation, patch selection, or platform configuration contracts as applicable. Install only declared dependencies using `requirements.txt`; do not create temporary or duplicate dependency manifests.

Workflow YAML changes must be validated with the repository's configured workflow parser/linter and relevant CI contract tests. A YAML parse alone does not prove correct job dependencies, permissions, expressions, provenance, or release behavior.

For changes affecting source, patchsets, builds, artifact identity, or release behavior, use the actual compatibility/build/qualification path and inspect its reports. A unit test or simulated fixture is not a substitute for the production path where the production path is the behavior being claimed.

For documentation-only changes, check links, paths, headings, and language-switch navigation as relevant. Do not modify functional contracts merely to accommodate documentation.

## 10. Documentation and naming

`README.md` and `README.zh-CN.md` are separate English and Chinese landing pages and should provide a working language switch to each other. They are valid root documentation and must not be moved into `docs/` to satisfy an artificial architecture rule.

Documentation should explain the implementation rather than invent a second implementation. Workflow tables are navigational aids only. When a workflow changes, update relevant documentation in the same scoped change if it has become inaccurate. Remove stale workflow names, input names, paths, and claims rather than preserving them for historical continuity.

Distinguish clearly among:
- implemented/configured;
- CI-tested;
- successfully executed in a real run;
- artifact produced and verified;
- production-signed;
- published;
- installed or tested on a real device.

Do not use historical phase labels or temporary fix names as permanent architecture when a clear functional name is available. Prefer existing canonical names and avoid gratuitous renames.

## 11. Required agent procedure

Before making a change:

1. Inspect current `main` and `test/development` heads, status, and ancestry when branch state matters.
2. Read this file and the relevant workflow, implementation, metadata, documentation, and contract tests.
3. Confirm the requested scope and classify it as documentation-only or functional.
4. Identify security, source identity, release, signing, and CI interfaces that could be affected.
5. Make the smallest coherent change on `test/development` unless the user explicitly specifies another target.
6. Run the appropriate local checks and inspect their exit codes.
7. Review the full diff for accidental changes, stale names, secret leakage, and weakened gates.
8. Open a PR from `test/development` to `main` when integration is requested or expected; do not merge it unless authorized.
9. After merge or branch synchronization, verify the actual commit and compare the branch tips.
10. Report the exact files/commits/PRs, checks performed, check results, and remaining unverified claims.

Never claim CI passed, a PR merged, branches synchronized, a release published, an artifact uploaded, or a signature/identity validated unless the current repository or run evidence proves it. Report historical evidence as historical. If a run is queued or in progress, say so.

## 12. Scope control and core principles

When asked to fix one issue or improve one document, do not automatically refactor unrelated workflows, change release semantics, rename unrelated files, change upstream resolution, alter signing behavior, or remove functionality. Broad audit findings should be reported separately and converted into scoped follow-up work rather than silently bundled.

Preserve behavior unless a change is explicitly intended. Preserve auditability, exact source identity, security boundaries, and fail-closed behavior. Prefer explicit evidence over assumptions. Ask before destructive operations. Never invent repository state.

This file is an operating contract, not a suggestion.
