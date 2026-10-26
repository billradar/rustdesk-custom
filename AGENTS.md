# AGENTS.md — RustDesk Custom agent guide

Read this guide before changing code, patches, metadata, workflows, release logic, or documentation. It is a stable orientation and safety contract, not a copy of the implementation. When a detail can change, inspect the live source of truth and update the relevant documentation with the implementation.

## Project identity

RustDesk Custom is a community-maintained RustDesk distribution and maintenance repository. It applies reviewed custom patchsets to official upstream RustDesk source, builds Standard and SOS variants for configured targets, validates packages and provenance, and automates qualification and releases. It is not a full source mirror or an independently maintained replacement for upstream.

The project prioritizes traceable source identity, reviewable customizations, validated packages, and protected signing/release operations. A successful compile alone does not prove a qualified artifact, production signature, published release, runtime behavior, or device upgrade compatibility.

For the user-facing overview, start at [README.md](README.md) or [README-zh.md](README-zh.md). For technical guides, use the matching language index: [English](docs/README.md) or [简体中文](docs/README-zh.md).

## Sources of truth

Before changing a behavior, locate and inspect its implementation and caller. Use these authoritative records:

- Platform targets, required status, and support state: `metadata/platform/matrix.json`.
- Reviewed upstream platform interfaces: `metadata/platform/adapter-profiles.json`.
- Reviewed build adapters and critical input fingerprints: `metadata/build/adapter-profiles.json`.
- Release and patch revision policy: `metadata/release/` and the release scripts that consume it.
- Android signing identity: `metadata/signing/` and the live signing workflow configuration.
- Current triggers, inputs, permissions, conditions, and job dependencies: `.github/workflows/*.yml`.
- Runtime behavior: the actual patch, helper, script, or upstream source path involved.

Do not copy mutable metadata into this file or treat README tables and historical run records as a second source of truth. If this guide conflicts with source, workflow, contract, or canonical metadata, verify the implementation and correct the guide in the same scoped change.

## Repository map

| Area | Responsibility |
| --- | --- |
| `patchsets/` | Reviewed shared and variant-specific customizations |
| `scripts/upstream/` | Upstream resolution, patchset selection, and patch integrity |
| `scripts/source/` | Source retrieval, patch application, and prepared-source checks |
| `scripts/build/` | Build entry points and configuration |
| `scripts/platform/` | Platform adapters, package creation, and artifact validation |
| `scripts/release/` | Channel identity, qualification, aggregation, and release gates |
| `scripts/signing/`, `tools/android-signing-bridge/` | Android signing helpers and hardware bridge |
| `scripts/validation/` | Repository, compatibility, and configuration contracts |
| `metadata/` | Machine-readable support, adapter, release, and signing records |
| `.github/workflows/`, `.github/actions/` | CI/CD orchestration and reusable actions |
| `docs/` | Paired English and Chinese implementation and operations guides |

Check that a referenced path exists on the target branch. Do not restore a removed workflow or file based on an old guide.

## Build and provenance invariants

- Resolve upstream tags/branches to an exact commit SHA; a version or moving ref alone is not source identity.
- Select patchsets using the explicit version policy in `scripts/upstream/patchsets.py`; keep selection separate from patch integrity and applicability checks.
- Prepare Standard and SOS from the same locked upstream identity, using separate source trees.
- Preserve source SHA, patchset and patch hashes, custom commit, variant, target, build run, and artifact provenance through validation and aggregation.
- `scripts/source/prepare.sh` requires an empty destination and must not delete/reset user data to make a build proceed.
- Fail closed on mismatched identity, unreviewed interface, missing/invalid artifact, or failed contract. Never fabricate manifests or reuse artifacts from a different batch.
- Treat `SUPPORTED` as the configured build/validation scope only; do not infer runtime, remote-session, upgrade, or signing validation from build evidence.
- Treat experimental targets and flavors according to the live matrix and their explicit gates. Do not promote them by changing a status field alone.

See the paired [build and validation guides](docs/build-and-validation.md) and [source and patch guides](docs/source-and-patches.md).

## Workflow and release boundaries

Workflow names, inputs, and permissions are live interfaces. Read the workflow and the scripts/actions it invokes before changing or dispatching it.

- CI classification is owned by `ci.yml` and `scripts/validation/change_classification.py`. Documentation-only changes use the configured lightweight path; functional or ambiguous changes must not be hidden by path filters or weakened checks.
- Stable and Nightly have separate resolvers, identities, and release gates. Do not make one channel consume another channel's qualification or artifacts unless the implementation explicitly defines that relationship.
- Stable/Nightly routing may create only the mode authorized by its workflow. Scheduled discovery is not authorization for public publication.
- Deduplication must retain exact identity checks, active-run suppression, bounded retries, and downstream provenance validation.
- Existing releases and completed artifacts are immutable. Do not delete, overwrite, append to, or relabel them to bypass a mismatch.
- Distinguish build, artifact validation, qualification, signing, Draft creation, public release, and runtime/device validation in code, documentation, and status reports.

For detailed current behavior, see [workflows and releases](docs/workflows-and-release.md), [operations](docs/operations.md), and their Chinese counterparts.

## Android production signing — critical boundary

Production Android signing is a separately protected hardware-backed operation. Ordinary CI, compatibility checks, untrusted PRs, and regular build jobs must not receive the signing Environment, PIN, YubiKey/PKCS#11 access, or signing step.

- Keep signing behind the live workflow's explicit repository, branch, event, qualification, runner, Environment, and artifact checks.
- Scope the PIN to the minimum required steps. Never place it in source, command-line arguments, logs, comments, or artifacts; do not add an ordinary-secret fallback.
- Verify package, ABI, source/artifact provenance, certificate identity, and every required APK signature scheme independently.
- Stop on a missing device/key, failed PIN preflight, identity mismatch, invalid APK, or uncertain provenance. Do not weaken checks or substitute an unapproved software key.
- A successful signature does not establish old-certificate continuity, key rotation, store compatibility, or real-device upgrade behavior. Claim those only with matching evidence.

The current identity and operation steps belong in `metadata/signing/`, the signing workflow, and [Android production signing](docs/android-production-signing.md), not as copied fingerprints in this guide.

## Git, PR, and authorization

The normal long-lived branches are `main` (protected integration/release baseline) and `development` (shared development/integration). Follow the user's explicit target branch or existing PR context when present; otherwise prepare normal work on `development` and propose it to `main`.

- Inspect branch heads, merge-base, ahead/behind counts, and relevant commits before branch-sensitive work. Equal file trees do not prove equal history.
- Do not reset, force-push, rebase, delete, or replace shared refs without explicit authorization and exact-SHA checks.
- Do not merge, publish, or perform production signing unless the user explicitly authorized that action and all gates pass.
- A created PR, green check, or successful build does not prove a merge, publication, or runtime behavior. Verify each state separately.
- Use `.github/PULL_REQUEST_TEMPLATE.md`; record actual checks and clearly mark checks not run.

## Documentation rules

- Keep the README focused on project purpose, user-facing capabilities, platform availability, and download/documentation entry points. Put engineering detail in `docs/`.
- Pair every guide as English `name.md` and Chinese `name-zh.md`; keep `docs/README.md` and `docs/README-zh.md` as language-specific indexes.
- Add language switches at the top of paired pages. English pages link to English guides; Chinese pages link to Chinese guides.
- Update both language versions when behavior or instructions change. Keep claims aligned and local links valid.
- Remove stale paths and workflow/input names. Separate implemented, tested, released, and runtime-validated status.
- Documentation-only changes must not alter runtime or workflow behavior.

## Validation and agent procedure

For a functional change, identify the affected workflow → script/action → metadata → contract → documentation chain. Run the repository contract and the relevant domain contracts, inspect exit codes, and verify the exact resulting commit in CI when applicable. For documentation-only changes, check paired files, local links, and `git diff --check`; do not run unrelated builds.

Before finishing:

1. Inspect the working tree and target branch.
2. Make the smallest coherent change and update affected English/Chinese guides.
3. Review the full diff for stale references, unrelated edits, exposed credentials, and weakened gates.
4. Report changed files, commit/PR when applicable, checks actually run, and any material unverified claims.

Never claim a check passed, PR merged, branches synchronized, release published, artifact uploaded, signature succeeded, or runtime behavior validated without current evidence for that exact result.
