# AGENTS.md — RustDesk Custom Project Guide and Agent Contract

This file is the first-stop guide for AI agents working in `billradar/rustdesk-custom`. It must explain both **what this repository actually is** and **how an agent is allowed to change it**. Read it before editing code, metadata, patches, workflows, release logic, or documentation.

Treat this as a project map, not a substitute for source inspection. If a detail here disagrees with the live workflow, script, contract, or canonical metadata, verify the implementation and update this guide in the same scoped change.

## 1. Project identity: what this repository is

`billradar/rustdesk-custom` is a **maintenance, patching, build, qualification, signing, and release-automation repository** for customized distributions of the official `rustdesk/rustdesk` project.

It is intentionally **not a full copy of the RustDesk upstream source tree** and should not evolve into an independently maintained source fork. The official upstream source is fetched at a specific revision when a workflow runs. Custom behavior is carried as reviewed patchsets in this repository. Build and release automation then prepares source trees, builds configured targets, validates artifacts and provenance, records qualification evidence, and optionally performs a separately gated Android production-signing operation.

The project optimizes for:
- explicit upstream and custom-repository revision identity;
- small, reviewable, version-bounded customization patches;
- repeatable source preparation and build configuration;
- platform/variant policy defined in machine-readable metadata;
- artifact integrity and provenance validation;
- executable architecture and security contracts;
- a strict separation between ordinary CI and privileged production signing;
- release gates that fail closed instead of silently bypassing missing evidence.

A green compile is only one stage. It does not by itself prove a valid artifact, a qualified release, a production signature, a published release, or working remote sessions on real devices.

## 2. Product and customization model

### Variants

- **Standard** uses the shared/common customization patchset.
- **SOS** uses the same shared/common patchset plus the SOS-specific patchset.
- Standard and SOS must be prepared from the same locked upstream source identity for a comparable build batch, but each variant must use an independent prepared source tree so variant-specific changes cannot leak into the other variant.
- Do not assume SOS exists for every platform. The platform matrix, not the variant name or README table alone, determines enabled/required targets.

Current patchset layout:
- `patchsets/v1/common/`: `0001-hbb-server-defaults.patch`, `0002-client-defaults.patch`, `0003-hide-cm-setting.patch`, `0004-cm-background-window.patch`.
- `patchsets/v1/sos/`: `0001-sos-mode.patch`, `0002-sos-home.patch`, `0003-sos-settings.patch`.
- `patchsets/v2/` contains the corresponding common and SOS customization generation for the newer upstream API boundary.

Common `0004` gives the Flutter CM a hidden native startup, serialized manual-only visibility policy and a local tray “Current connections” command. It keeps the main window on upstream logic. Manual requests are latched in CM Rust state and polled through the existing bridge; no bridge API regeneration is needed. `scripts/validation/cm_window_contract.py` guards prepared-source wiring and executes the pure-Dart policy when Dart is available. Native UI/real remote sessions remain unverified until exact-package testing.

These filenames are useful orientation, not a complete semantic specification. Read the patch before changing or describing its behavior.

### Wayland unattended build flavor

- `.github/workflows/wayland.yml` is a reusable internal build called by Tag/Nightly with `include_wayland` (default true), using the same-run prepared Standard and SOS sources. No separate manual trigger remains. Tag draft/release revalidates and attaches all four DEBs; Nightly aggregates them as Actions artifacts and includes them in its signed prerelease Draft.
- `build-wayland-target.yml` reuses the matching verified Standard/SOS source and records `build_flavor: unattended-wayland` separately from the source variant.
- Canonical x86_64/ARM64 targets remain experimental in `metadata/platform/matrix.json`, excluded from the generic planner (`enabled: false`) and explicitly opted into this workflow (`workflow_enabled: true`). Do not promote without real build evidence.
- `metadata/build/wayland-policy.json` pins the DRM job, packaging interface and libdrmtap dependency. `scripts/platform/wayland.py` and `wayland_contract.py` own recipe, source, package and four-target aggregate gates.
- `include_wayland` selects Standard/SOS × x86_64/ARM64 together. Variant-aware filenames, Actions artifacts and source-peer checks prevent collisions or a Standard binary being labeled SOS. Both variants keep the same Debian package identity and replace one another; never claim parallel installation. The native ABI probe checks the compiled `sos-mode` flag before packaging. Policy schema v2 and its digest require a fresh four-target batch; old two-package releases remain immutable.
- Follow `docs/wayland-unattended.md`; run the new contract and affected release contracts. ARM means ARM64 here; upstream's dedicated DRM job directly defines only x86_64.

Both Common patch generations force `allow-always-software-render=N` via `OVERWRITE_SETTINGS`, overriding saved/custom settings in all variants and platforms. Keep the structural, native-helper and compiled-MIR gates aligned; do not reduce this to a default that persisted `Y` can override.

### Patchset selection is version-bounded

The current selector is `scripts/upstream/patchsets.py`:
- upstream versions below `1.5.0` select `patchsets/v1`;
- upstream versions `1.5.0` and later select `patchsets/v2`.

Selection is based on the explicit numeric upstream version boundary. Patch contents, hashes, source SHA, or whether a patch happens to apply must not silently influence selection. Integrity and applicability are separate validation gates. When a new upstream API migration requires another patch generation, add an explicit reviewed version boundary and the corresponding metadata/contracts; do not add heuristics to the selector.

The patchset manifests currently record:
- `v1`: validated against upstream `1.4.9` / `6c578292e8ebbbec708b76986ba8c4bc7c509747`;
- `v2`: compatibility-validated against upstream `1.5.0` / `fada664df7a294d1d1a9ca3e7cd3637069122f17`.

These are baseline records, not a promise that every current upstream commit or target is fully validated. Always inspect the manifest and fresh CI evidence for the exact revision being changed.

## 3. Repository map: where to look first

| Path | What it owns | Start here when... |
| --- | --- | --- |
| `.github/workflows/` | Workflow triggers, inputs, permissions, job graph, conditions, artifact handoff | CI/CD routing or a skipped/failed job is in question |
| `.github/actions/` | Reusable action implementation | A workflow delegates behavior to a local action |
| `patchsets/vN/common/` | Customizations shared by Standard and SOS | Shared UI/default/server behavior changes |
| `patchsets/vN/sos/` | SOS-only customizations | SOS-specific behavior changes |
| `patchsets/vN/patchset.json` | Patchset baseline, hashes, variant mapping, validation record | Patch selection or patch integrity changes |
| `scripts/upstream/` | Upstream/patchset policy and selection | Version boundary or patchset identity changes |
| `scripts/source/` | Fetch, prepare, patch, and verify clean upstream source | Prepared source, submodules, or patch application fails |
| `scripts/build/` | Platform build entrypoints and build configuration | Toolchain invocation or build flags change |
| `scripts/platform/` | Adapter checks, target execution, packaging and artifact validation | Platform matrix/build adapter/package behavior changes |
| `scripts/release/` | Channel identity, naming, preflight, aggregation, qualification and publication | CI qualification or Stable release behavior changes |
| `scripts/signing/` | Android signing identity/configuration and signing workflow helpers | Android signing policy or certificate validation changes |
| `tools/android-signing-bridge/` | Java bridge for hardware-backed Android signing; includes mock and production interfaces/tests | PKCS#11, PIN handling, ECDSA encoding or signing flow changes |
| `scripts/validation/` | Repository, compatibility, change-classification and native configuration contracts | Architecture policy or change classification changes |
| `metadata/platform/matrix.json` | Canonical enabled/required/support-status target matrix | Whether a target participates in a build |
| `metadata/platform/adapter-profiles.json` | Approved signatures for official upstream platform build definitions | An upstream build interface/profile changes |
| `metadata/build/adapter-profiles.json` | Reviewed build adapter profiles and critical input fingerprints | Toolchain/build configuration drift is detected |
| `metadata/release/identity.json` | Legacy numeric revision consumed by the legacy production adapter; distinct from patch-scoped Stable channel revisions | Legacy adapter identity changes |
| `metadata/release/patch-revision-record.json` | Canonical Stable patch-scoped revision contract (`v{patchset}.{revision}`) and immutable tag format | Patch revision tracking changes |
| `metadata/signing/android-standard.json` | Android Standard package and signing identity evidence | Package/certificate/legacy-identity claims change |
| `metadata/baselines/` | Known build/source/UI baselines used by checks | A regression baseline changes |
| `requirements.txt` | Python tooling dependencies | Python dependency/import failures occur |
| `docs/README.md` | Documentation index | You need the detailed explanation of a subsystem |

The tree may evolve. Check whether a path exists at the target revision before relying on it. Do not resurrect removed files or old workflow names just because an older document mentions them.

## 4. Source-to-artifact data flow

The intended conceptual pipeline is:

```text
Official rustdesk/rustdesk
  │ resolve ref/tag and lock exact 40-character commit SHA
  ▼
Upstream compatibility and reviewed build-interface checks
  │ select patchset by explicit upstream version boundary
  ▼
Clean prepared source + recursive submodules + verified patch hashes
  │ prepare Standard and SOS in separate source trees
  ▼
Platform matrix + reviewed adapter profile
  │ build target-specific artifacts
  ▼
Package / ABI / checksum / build-info / configuration / provenance checks
  ▼
Aggregate required target set + CI qualification record
  │
  ├── optional, separately authorized Android production signing
  ▼
Stable dry-run / draft / explicitly authorized publication
```

Each stage has its own inputs, outputs, and gates. Do not skip stages by hand-editing a manifest or reusing an artifact from a different build batch.

### Source preparation invariants

The core source preparation lives under `scripts/source/`:
1. Fetch the official upstream repository at the requested ref.
2. Resolve the actual commit SHA and compare it to `UPSTREAM_EXPECTED_SHA` when supplied.
3. Check out the exact SHA detached from a moving branch/tag.
4. Initialize recursive submodules and verify their checked-out commits match the parent repository's gitlinks.
5. Require a clean source tree.
6. Select and verify the expected patchset; apply patches to the intended upstream tree.
7. Generate source identity/provenance from actual inputs.

Important: `scripts/source/prepare.sh` requires an **empty destination directory** and deliberately refuses to reset/delete files already there. Never “fix” this safety behavior by adding a destructive clean/reset. Never claim the source SHA from a tag name alone.

### Provenance identity

A build/qualification must preserve the association among:
- custom repository commit SHA;
- official upstream repository, ref/version, and resolved SHA;
- patchset ID and common/SOS patch hashes;
- Standard/SOS variant;
- target platform and architecture;
- reviewed build profile/toolchain inputs;
- build run identity;
- artifact checksums, build-info, and validation reports.

A filename, release label, branch name, or manually edited JSON field is not sufficient evidence of artifact identity.

## 5. Platform support: how to interpret it correctly

`metadata/platform/matrix.json` is the authority for enabled targets, required targets, support status, runner, and experimental eligibility. `metadata/platform/adapter-profiles.json` and `metadata/build/adapter-profiles.json` hold separate reviewed build-interface/profile data; they are not interchangeable with the target matrix.

The README currently summarizes these intended platform/variant families:
- Windows x86_64: Standard and SOS;
- Windows ARM64: Standard and SOS as experimental Tag/Nightly targets; builds and release assets are enabled, runtime qualification is pending;
- Linux x86_64 and ARM64: Standard and SOS;
- macOS x86_64 and ARM64: Standard and SOS;
- Android ARM64, ARMv7, and x86_64: Standard;
- Web is blocked by the reviewed upstream build definition; iOS is not a normal supported release target unless the live matrix says otherwise.

Always confirm these summaries against the current matrix before changing support claims or workflow behavior.

Support status meanings:
- `SUPPORTED`: meets the repository's configured build/validation requirements for that target; does **not** imply runtime UI, real remote-session, upgrade, or production-signing validation.
- `EXPERIMENTAL`: only eligible through the explicit experimental path; never silently promote it to a required Stable target.
- `PLANNED`: not enabled for normal builds.
- `BLOCKED`, `UNSUPPORTED`, or `DISABLED`: do not treat as a normal available target.

Do not set `enabled: true`, `required: true`, or `support_status: SUPPORTED` by itself to make a platform “supported.” The adapter/profile must match the reviewed official upstream build interface, required validation must pass, and the evidence scope must be accurately recorded. Do not copy historical run IDs or PASS labels forward as if they validate a new source SHA.

Keep these evidence levels separate:
1. configured in metadata;
2. selected by the target planner;
3. successfully built in a specific run;
4. artifact validated for package/architecture/checksum/provenance;
5. UI/runtime or real remote-session tested;
6. production-signed with the intended identity;
7. published and, where relevant, installed/upgraded on a real device.

Only state the level that evidence supports. The current patchset records say runtime UI validation was skipped by the user and real remote sessions were not tested; do not turn build evidence into runtime claims.

## 6. Workflow map and channel boundaries

Workflow names and interfaces are live contracts. Read the YAML and the scripts it calls before changing an input, dispatching a workflow, or explaining a failure.

- `.github/workflows/ci.yml`: classifies changes. Documentation-only changes take a lightweight path; functional or ambiguous changes take the full source/compatibility/qualification path. Its current `workflow_dispatch` inputs include `upstream_ref`, `force_rebuild`, and internal `automation_source`.
- `.github/workflows/compat-check.yml`: reusable compatibility/contracts path for explicit upstream identity and channel.
- `.github/workflows/prepare-source.yml`: prepares the locked patched source artifact for downstream builds.
- `.github/workflows/build.yml` and `.github/workflows/build-platform.yml`: build orchestration and target-level platform execution.
- `.github/workflows/build-stable-windows.yml`, `build-stable-platforms.yml`, and `build-stable-android.yml`: Stable target-build entry points.
- `.github/workflows/tag.yml`: Stable resolve/preflight/build/aggregate/qualification and release-mode routing. Current manual release modes are `dry-run`, `draft`, and `release`. Default is `dry-run`.
- Nightly was explicitly restored and then requested to match Tag signing/Draft behavior by the user on 2026-10-25. `nightly.yml` reuses the Tag build cores; protected-main `draft` mode uses the same direct Environment-bound YubiKey signer and creates an immutable prerelease Draft. `dry-run` stays build-only. Public Nightly prerelease mode is an explicit manual choice and may promote only the exact complete matching Draft after revalidating its identity and remote asset digests. `nightly_contract.py` enforces these boundaries.
- `.github/workflows/upstream-stable.yml`: polls official Stable releases and routes the newest eligible tag to a signed private Draft build. It reuses the Stable release preflight for identity and asset verification, skips complete matching builds, deduplicates active runs, and never authorizes public publication.
- The upstream-main monitor also generates unknown-interface review packets in a read-only job and can create report-only draft PRs from protected `main`. It never changes approved profiles or runs unknown upstream build scripts. `scripts/upstream/interface_review.py` and its contract own this boundary.
- Automation exception to the two-branch rule: `automation/upstream-interface-<interface-signature>` branches may contain only a generated JSON report under `docs/upstream-interface-reviews/`, are deduplicated, and are never reset or auto-merged. This isolation is required to propose a report without modifying `main` or shared `development`.
- `upstream-nightly.yml` polls daily at 12:00 UTC, following the latest successful official `flutter-nightly.yml` run on the official default branch. Use its exact head SHA, never the moving `nightly` tag. Deduplicate by upstream SHA, selected patchset and Common/SOS content hashes, release mode, Wayland policy, and signing mode; custom SHA and official run ID are provenance only. Active or successful identical batches are skipped, failures are retried at most three times, and a complete exact Draft may be reused for an explicitly requested promotion only after metadata and remote asset digests match.
- `.github/workflows/upstream-main-compatibility.yml`: periodic compatibility signal for the official upstream default branch; it does not build or publish Nightly artifacts.
- `.github/workflows/android-yubikey-signing-test.yml`: manually and explicitly authorized signing smoke test; it is not a Stable release and must not publish one.
- `.github/actions/android-yubikey-sign/`: local reusable signing action implementation.

Never assume a file exists because an old guide mentions it. Nightly is owned by its explicit workflow and contracts; do not restore legacy release behavior. In particular, `.github/workflows/upstream-event-router.yml` is not a current router.

### Channel rules

- **CI qualification** is tied to the exact custom commit and upstream identity used by the qualification run.
- Stable manual and automatic dispatch compute identity in `scripts/release/stable_lock.py` without an external identity input. The router recovers identities from run lock artifacts for deduplication and retry limits; unknown active batches block duplicates and missing completed locks require manual review. Tag preflight, aggregation and release gates require the same digest-verified lock artifact, run/source identity and frozen signing selection. No force-rebuild/overwrite option is restored.
- Nightly manual and automatic entrypoints both select the latest successful official run at resolve time; no public run-ID/SHA inputs or wait-for-today behavior remain. Downstream builds use that resolved SHA.
- **Stable** resolves an official Stable version/ref and its exact SHA, selects the patchset by version, and deduplicates on upstream SHA, selected patchset and its Common/SOS content hashes, plus Wayland and signing policies. The custom repository SHA remains provenance metadata, not a build identity input. A complete matching revision skips the build; an existing Draft is published only after rechecking identity, completion, exact inventory, uploaded state, sizes, and GitHub SHA-256 digests. Legacy complete releases are reusable only after their recorded v3 identity and current selected patch content are verified.
- Windows ARM64 is opt-in by canonical matrix metadata as an experimental `default_build`: Tag and Nightly run it by default and include successful ARM64 EXE/MSI assets, while CI's normal target plan remains x86_64-only. Do not call it fully supported until exact-run package and runtime evidence justify promotion.
- **Nightly** follows completed official Nightly runs, prepares independent Standard/SOS sources, builds the supported Tag matrix, and aggregates exact-run artifact evidence. It is not Stable qualification. Protected-main draft/release modes require production-signed Android artifacts (both v2 and v3); the write-permission job revalidates the complete package set. Draft mode creates a prerelease Draft. Public prerelease mode is an explicit manual choice and can promote only a complete matching Draft after its remote asset inventory and digests are revalidated. Generic `channel.py resolve` remains CI/Stable-only; use `nightly.py` for verified-run resolution.
- **Upstream default-branch compatibility** is a compatibility signal only. It does not automatically mean Stable publication.
- A router-triggered Nightly batch is not authorization for public publication. Public Nightly release requires an explicit manual `release` mode plus the full signed-artifact and matching-Draft gates. A successful build or qualification by itself is not publication authorization.
- Preserve duplicate suppression and safe retry behavior. Do not weaken freshness checks, SHA revalidation, run matching, or downstream provenance checks just because the upstream router already performed validation.

`force_rebuild` is a current input of `ci.yml`; do not assume it exists in `tag.yml`. `promote_stable` is not a current workflow interface. Never document or add an input based on memory rather than the live YAML.

## 7. CI classification and contracts

`scripts/validation/change_classification.py` classifies a change as:
- `DOCS_ONLY` only when every changed path is recognized as documentation/non-functional;
- `FUNCTIONAL` for functional or ambiguous changes, manual CI dispatch, or a push without a usable previous revision.

The current classifier recognizes Markdown files and the configured documentation/non-functional paths. Changes to scripts, workflows, actions, metadata, patchsets, dependencies, build logic, release logic, or signing logic are functional. A mixed docs + code change is functional. Do not manipulate path names or add broad ignore rules to evade functional CI.

Repository architecture contract:
```bash
python3 scripts/validation/repository_contract.py
```

Relevant domain contracts include (confirm each path exists and inspect its CLI before use):
```text
scripts/release/channel_contract.py
scripts/release/qualification_contract.py
scripts/release/production_contract.py
scripts/build/config_mir_contract.py
scripts/validation/native_config_contract.py
scripts/signing/android_signing_contract.py
```

Run the repository contract and the tests/contracts for every affected domain. Workflow YAML parsing alone does not validate permissions, expression semantics, job dependencies, provenance, release gating, or hardware isolation. A skipped job is not a passed job; determine whether the skip is expected from the workflow conditions.

Use dependencies declared in `requirements.txt`. Do not introduce duplicate dependency files or “fix” missing imports by guessing a package name without checking the declared dependency and module path.

## 8. Android Standard production signing — critical security boundary

Android Standard package identity currently recorded in `metadata/signing/android-standard.json` is `com.carriez.flutter_hbb`. The signing path uses a hardware-backed YubiKey PIV identity and a dedicated bridge. Treat all signing inputs and the identity metadata as security-sensitive.

Current intended configuration, which must be rechecked against live workflow and metadata before any change:
- GitHub Environment: `android-production-signing`;
- Environment Secret: `YUBIKEY_PIV_PIN`;
- dedicated runner labels: `self-hosted`, `linux`, `arm64`, `rustdesk-signing`, `android-signing`, `yubikey`;
- PIV slot: `9C`;
- PKCS#11 object ID: `02`;
- required Android APK signature schemes: v2 **and** v3, each independently verified.

### Non-negotiable isolation

- Ordinary CI, compatibility checks, and ordinary build jobs must not access the production signing Environment, production PIN, YubiKey, PKCS#11 device, or production signing step.
- Production signing must remain behind the intended Tag or protected-main Nightly draft workflow's explicit authorization, branch/event/qualification conditions, dedicated runner and Environment protections.
- The manual signing smoke test is separately gated and must never publish/promote a release.
- Never commit a keystore, private key, PIN, password, token, PKCS#11 credential, or sensitive signing output.
- Never pass the PIN in command-line arguments, echo it, print it in logs, put it in PR comments, or upload it as an artifact. Remove it from the signing script environment before child tools start, pass it to the signer only through standard input, and clear mutable buffers after use. Scope the secret to the minimum step and use the approved Environment secret; do not add a fallback to ordinary repository secrets.
- Do not replace hardware signing with an undisclosed software key or weaken gates to make a run pass.
- A failed PIN preflight, missing device, unavailable key, unexpected certificate, or invalid APK is a stop condition. Do not retry by weakening checks.

### Legacy identity status is not the same as current signing success

The current `metadata/signing/android-standard.json` records:
- legacy APK certificate SHA-256: `a53de75c536ba1431f5e1c0ecaee120a63b5107b563fcdd311efd38297be103c`;
- current production YubiKey certificate SHA-256: `559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5`;
- `legacy_android_signing_identity`: `NOT RECOVERED / NOT VALIDATED`;
- legacy APK runtime upgrade: `NOT TESTED`.

The recorded legacy and current production certificate fingerprints differ. Do **not** claim that the new signing identity preserves the legacy identity or that an in-place upgrade is compatible. A successful hardware-signing operation proves only that the operation succeeded for that input; it does not prove legacy certificate continuity, v3 proof-of-rotation, Play/update compatibility, or successful device upgrade. Those claims require the relevant certificate-chain/signing-lineage and device-level evidence.

For each signed APK, validate package name, certificate fingerprint, version/version code, ABI, hash, signature schemes, and source/artifact provenance. Never weaken the requirement from “v2 and v3” to “either v2 or v3”.

## 9. Release qualification and publication safety

A valid qualification must match the exact:
- custom repository commit;
- upstream version/ref and resolved SHA;
- selected patchset and patch hashes;
- channel and revision;
- required target/variant set;
- build identity and artifact evidence.

Never reuse a qualification record for a different commit, upstream SHA, patchset, revision, target set, or build configuration. Do not manually edit qualification evidence to force a match.

Stable mode semantics:
- `dry-run`: exercise resolution/preflight/build/validation without claiming publication;
- `draft`: create/update only according to the workflow's explicit existing-draft/preflight rules;
- `release`: publication path, requiring the full aggregate gate and explicit user authorization.

Before any release action, inspect the live `tag.yml` inputs, conditions, existing draft/release state, and qualification record. Never silently delete/overwrite an existing release, fabricate a revision, bypass preflight, or infer permission to publish from a scheduled router run.

Report separately whether a source revision was prepared, an artifact built, artifact validation passed, qualification passed, signing passed, a draft exists, a release was published, and runtime/device testing occurred.

## 10. Branch, PR, and history rules

The intended long-lived branches are only:
- `main`: protected stable integration/release baseline;
- `development`: shared development/integration branch.

Normal work is done directly on `development`, validated, and proposed to `main` through a PR. Do not create `feature/*`, `fix/*`, `docs/*`, or other temporary branches unless the user explicitly asks or a platform constraint makes one necessary. Do not commit directly to protected `main`.

Before branch-sensitive operations, inspect both branch heads, merge base, ahead/behind counts, unique commits, and changed files. Tree equality does not prove ancestry. Git history is audit evidence: do not routinely squash/rebase away the shared development history.

Never reset, force-push, rebase, replace a ref, delete a shared branch, or rewrite history without explicit authorization. For any authorized destructive operation, inspect the exact expected target SHA and use an expected-old-SHA guard where available.

Creating a PR does not merge it. A green PR check does not merge it. A merged PR does not prove every desired workflow ran. Verify the actual merge state, resulting commit, CI run, and branch comparison. Do not merge a PR unless the user explicitly authorizes merging.

### Codex review for follow-up PR commits

Codex does not necessarily review each new commit pushed to an already-open PR automatically. After pushing a change to an existing PR, request one Code Review for the new PR head by posting the exact comment `@codex review`.

Before posting, read the PR's current head SHA and the latest Codex review summary:
- If a review is already running for that exact head SHA, wait for it; do not post a duplicate request.
- If a review completed for that exact head SHA, do not repeat it unless the user explicitly requests another review.
- If there is no review for the current head, or the latest review targets an older SHA, post `@codex review` once.
- When several commits are pushed together, review the resulting head once. Do not request reviews for intermediate local commits that were never pushed.

Treat a review as current only when its recorded commit SHA matches the PR head. After addressing findings and pushing a follow-up commit, repeat this check for the new head. Report if Codex review cannot be triggered or remains pending; do not infer that an older review covers new commits. Use `@codex security review` only when a security review is specifically needed.

## 11. Documentation rules and project terminology

- `README.md` and `README.zh-CN.md` are separate English/Chinese landing pages with working language links. Do not merge them into one page or move them into `docs/`.
- `docs/README.md` is the documentation index. Update the relevant guide when implementation behavior changes.
- Documentation-only changes should not alter runtime or workflow behavior.
- Describe current behavior from live source. Remove stale paths, inputs, and assumptions rather than preserving obsolete workflow names.
- Distinguish configured support, CI-tested behavior, a real successful run, validated artifacts, production signing, publication, and device/runtime validation.
- Do not make README tables, old phase summaries, old run IDs, or conversation notes a second source of truth for mutable support/configuration data.

## 12. Debugging workflow failures: minimum evidence to collect

When investigating a failed Actions run:
1. Capture the run URL/ID, workflow name, event, branch, head SHA, and status.
2. Identify the first failing job/step, not just the final summary line.
3. Record the exact custom SHA, upstream SHA/version, patchset, target/variant, and artifact/build identity relevant to the failure.
4. Read the workflow conditions and the called script/action before deciding why a job was skipped or failed.
5. Check whether the failure is an infrastructure/transient error or a reproducible project error; rerun only when appropriate.
6. Fix the underlying contract or implementation. Do not hide failures with `continue-on-error`, broad condition changes, skipped required jobs, relaxed assertions, fake manifests, or stale artifact reuse.
7. Re-run the narrow relevant contract first, then the affected workflow/qualification path.
8. Report evidence and remaining uncertainty. Do not claim a fix until a run on the intended commit verifies it.

Useful first checks:
- Repository structure/policy: `python3 scripts/validation/repository_contract.py`
- Change-classification behavior: `scripts/validation/change_classification.py`
- Patch generation/selection/integrity: `scripts/upstream/patchsets.py`
- Source preparation/submodule/patch application: `scripts/source/`
- Target planning/aggregation: `scripts/release/qualification.py`
- Android identity and signing contract: `scripts/signing/`, `tools/android-signing-bridge/`, `metadata/signing/android-standard.json`

Inspect each script's CLI and required environment before running it. Never invoke a release/publish/signing path casually just because it can be run manually.

## 13. Required agent procedure

Before changing anything:
1. Read this guide and inspect the current repository state and target branch.
2. Trace the requested behavior from workflow → script/action → metadata/contract → documentation as applicable.
3. Confirm the actual implementation and affected interfaces; do not guess from filenames.
4. Classify the change as documentation-only or functional.
5. Identify impact on upstream identity, patchset selection, target matrix, qualification, artifact provenance, signing isolation, and release behavior.
6. Make the smallest coherent change directly on `development` unless explicitly instructed otherwise.
7. Run relevant local contracts/tests and inspect exit codes.
8. Review the full diff for unrelated changes, stale references, leaked secrets, and weakened gates.
9. Open/update a PR to `main` when integration is expected; do not merge without explicit authorization.
10. Verify CI on the exact resulting commit and report the files, commit, PR, checks, and remaining unverified claims.

Prepared-source credential scanning permits only the reviewed public upstream WebSocket TLS test-key path plus exact content hash documented in `docs/build-and-validation.md`. Do not generalize this to a test-directory/PEM exclusion or the production payload/input scanner.

Never claim that CI passed, a PR merged, branches synchronized, a release published, an artifact uploaded, a production signature succeeded, or identity continuity was proven unless current evidence establishes that exact claim. Label historical evidence as historical.

## 14. Core non-negotiable principles

- Inspect the live repository; do not invent files, inputs, target support, or workflow behavior.
- Preserve exact source identity, patch integrity, provenance, qualification, and fail-closed validation.
- Preserve the boundary between ordinary CI and production Android signing.
- Do not turn build evidence into runtime, upgrade, or release evidence.
- Do not perform destructive Git operations or merge/publish/sign without the required explicit authorization.
- Keep changes scoped. Report broader audit findings separately instead of bundling unrelated refactors.
- When documentation and implementation disagree, establish the actual behavior first, fix the scoped issue, and update the documentation so future agents do not repeat the mistake.
