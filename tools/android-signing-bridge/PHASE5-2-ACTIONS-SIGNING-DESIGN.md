# Phase 5.2A — GitHub Actions Signing Integration (Mock Dry Run)

**Purpose:** validate workflow boundaries and artifact gates without touching the YubiKey.
**Phase 5.1 baseline:** PASS / FROZEN.
**Phase 5.2A:** implementation ready for a mock-only dispatch; not yet run on GitHub.
**Real YubiKey operation / PIN / production signing / release:** NO / NO / NOT RUN / NOT RUN.

## Audit findings

- Repository is `billradar/rustdesk-custom`, branch `main`. A read-only GitHub Actions runner query found `raspberrypi-rustdesk-signing` online and idle with labels `self-hosted`, `Linux`, `ARM64`, `rustdesk-signing`, `android-signing`, and `yubikey`.
- `rustdesk-actions-runner.service` is active under `github-runner:github-runner`, with supplementary group `rustdesk-yubikey`; its unit sets `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`, and `ProtectHome`. `pcscd.socket` is listening. OpenSC package is `0.26.1-2`; `/etc/opensc/opensc.conf` contains only the default app block with debug examples commented out, and no PIN-caching override. `/usr/lib/aarch64-linux-gnu/opensc-pkcs11.so` is root-owned and world-readable. The vendor socket was `root:root` mode `0666`; a persistent systemd drop-in now makes it `root:rustdesk-yubikey` mode `0660`. The service account is the only group member. An authorized-runner OpenSC query passed and an unauthorized `nobody` socket connection was denied. No runner credential files or token values were inspected.
- `sign-android.yml` selects the dedicated self-hosted labels, serializes signing with concurrency, and binds `android-production-signing`. Its stock `apksigner sign` / `SunPKCS11` step has been removed. The current production CLI accepts generic package/ABI-matching APKs and explicit `--pin-source console|env`. The installed signer step is disabled by default: the validation caller passes `validation_enable_signing: false`, and execution also requires the exact validation workflow ref, `workflow_dispatch`, and `signing-validation` channel. Its Environment Secret reference is scoped to that step only. No signing workflow was dispatched and no secret value was read.
- `build.yml` and `android-signing-validation.yml` directly call the reusable signing workflow; `tag.yml` calls the stable build workflow, which can in turn request production signing. The reusable signing job checks the repository, main ref, caller workflow ref, event, and channel before reaching the dedicated runner. PR workflows do not call it. Manual dispatch of the stable/tag flow can lead to draft-release work when configured without dry-run; the dedicated dry-run workflow has no release job and is not connected to those callers.
- GitHub Environment `android-production-signing` is limited to branch `main` and disables administrator bypass. Its required-reviewer rule was removed by the owner under the accepted single-maintainer model. Metadata confirmed the `YUBIKEY_PIV_PIN` secret name exists; its value was not read. The production step has a scoped secret mapping and is disabled by default through the validation caller flag and exact workflow/event/channel conditions. No workflow run injected the secret. No Environment variables are configured.

## Dry-run workflow and architecture

For Phase 5.2A, `.github/workflows/android-signing-dry-run.yml` was the only workflow added. During the later Phase 5.2B-1 work, `.github/workflows/sign-android.yml` was also changed to replace the stock signer with the installed Bridge entrypoint. The dry-run workflow has a single `workflow_dispatch` trigger and two jobs:

1. `build-mock-artifact` runs on `ubuntu-24.04`, tests the fixture gates and frozen Bridge software-only tests, creates a small synthetic fixture (explicitly **not an installable APK**), and uploads it for one day.
2. `mock-signing-runner` requires the exact dedicated self-hosted runner labels and does not check out repository code. It downloads only the artifact named for this run, gates repository/ref/workflow/commit/run provenance plus Android Standard package and aarch64 metadata and checksum, invokes `/usr/local/bin/rustdesk-sign --dry-run` to verify the root-owned installation and perform no-PIN read-only certificate discovery, then emits and validates a mock-only receipt with exactly two simulated signing operations and output hash verification.

Both jobs require `billradar/rustdesk-custom`, `refs/heads/main`, the exact workflow path on `main`, and `workflow_dispatch`. There is no PR, fork, schedule, arbitrary input, workflow-call, release, production Environment, secret, or signing command. Workflow token permissions are read-only. Checkout and artifact actions are pinned to immutable commit SHAs. Inputs and outputs are isolated under `.work`; the simulation refuses to overwrite its output and checks that the fixture input remains unchanged.

The dedicated runner is used to validate placement and runner selection. Its step commands come from the checked-in workflow text and installed launcher; the job does not checkout or execute repo helper code. The dry run grants no PIN and its installed Bridge self-test reads only the public certificate. Its artifact is a fixture rather than a real APK. The operation count and output verification receipt are simulation assertions, not hardware-signing evidence. Bridge cryptographic behavior remains covered by software-key mock tests run on GitHub-hosted infrastructure or locally.

## Trust boundaries and gates

| Boundary | Gate | Failure behavior |
|---|---|---|
| Event/repository/ref | Both jobs require trusted repository, exact `main` ref, exact workflow ref and manual dispatch | Job skipped; no self-hosted execution |
| Build to signer | Artifact name includes current run ID; manifest binds repository, ref, commit and run ID | Reject mismatch |
| Artifact contents | Exact file allowlist, fixture checksum and manifest format | Reject altered, missing or extra files |
| Android identity model | Require Android / Standard / aarch64 / expected package metadata | Reject any mismatch; fixture is not treated as an actual APK |
| Input integrity | Hash before/after simulation; output must not overwrite input | Fail on mutation or output collision |
| Mock Bridge | `mvn clean verify` on software-only tests | Fail on any test failure |
| Operation count / output | Receipt must say `MOCK_ONLY`, two expected/two simulated operations, no PIN/backend/private-key operation, and matching output hash | Fail closed |
| Release boundary | No release action, contents-write permission, tag, or release upload | No release possible from this workflow |

The helper and tests live in `tools/android-signing-bridge/phase52_dry_run.py` and `test_phase52_dry_run.py`; they create no private key, PIN, APK signature, or PKCS#11 session. The workflow's `mvn clean verify` runs only on `ubuntu-24.04`, executes software-key mocks, and does not start the `RealYubikey*OneShot` entrypoints.

## PIN delivery options

### Fully unattended GitHub Environment Secret

The `EnvironmentPinSource` implementation reads `YUBIKEY_PIV_PIN` only when the caller explicitly selects `--pin-source env`. The mock CI path exercised it only with a dummy value. The real production workflow step is disabled by default, so the GitHub Environment secret has not been injected or read. The owner explicitly accepted that production signing will use the single-maintainer model without independent reviewer approval. The process must never pass the secret in argv, a file, output, log, or artifact and must clear mutable Bridge buffers. This remains unattended PIN use: the secret exists in GitHub and is available to the trusted runner process. A compromised runner, malicious workflow, or same-user process can threaten it. Environment restrictions authorize a job but do not prove physical user presence at the token.

### Locally approved hardware signing

GitHub Actions can build and publish a short-lived, provenance-bound unsigned artifact and stop before private-key access. An operator then reviews the run, downloads that exact artifact, and starts a separate local one-shot signing process from a real terminal on the dedicated host. The process verifies repository/run/commit/package/hash/certificate policy before prompting on `/dev/tty`, passes a mutable PIN buffer directly to the Bridge, and clears it. This provides explicit local approval and avoids storing the PIN in GitHub, but it is a human-operated signing stage rather than fully unattended Actions. A future design must define how the verified signed result and audit receipt return to the run without making the unsigned artifact or PIN an arbitrary input.

These models have different trust assumptions. No real PIN was deployed or used. Both PIN source interfaces exist; the environment path was exercised with a dummy value in a no-hardware mock. The production Actions signing step remains disabled by default. The owner has accepted the single-maintainer authorization model; production access therefore relies on the active `main` ruleset, Environment `main` restriction, workflow and artifact gates, dedicated self-hosted runner, installed Bridge, PC/SC policy, hardware key, and post-sign verification.

## Existing workflow integration and release boundary

The reusable production workflow contains the intended `/usr/local/bin/rustdesk-sign --input ... --output ... --pin-source env` invocation and step-scoped secret mapping. The validation caller remains manual-only and one-architecture for a one-shot hardware validation. Its signing flag is false by default; the signer step also requires the exact validation caller workflow ref, `workflow_dispatch`, and `signing-validation` channel. When invoked, the installed generic CLI checks the APK package and exactly one supported RustDesk ABI, calculates an input SHA-256, rechecks the input after signing, stages output privately, and refuses symlink paths or overwrite. The parent workflow separately validates same-run provenance and the Standard variant; the APK alone does not prove its artifact provenance. The installed launcher is root-owned and integrity-checked. The accepted authorization model is single-maintainer, and the `main` ruleset is active. No production workflow was dispatched.

Phase 5.2A creates only a mock artifact and receipt. It cannot publish APKs, tags, or Releases. A future rollback is to disable/remove `android-signing-dry-run.yml` and the two fixture helper files; no runner service, OpenSC configuration, YubiKey state, or production workflow needs rollback.

## Validation record

```text
PHASE 5.1 BASELINE: PASS / FROZEN
PHASE 5.2A DRY RUN: PASS (local mock artifact/gate pipeline including installed `--dry-run`; GitHub workflow not dispatched)
PHASE 5.2B-1.1 GENERIC INSTALLED CLI: PASS (two real Standard APK inputs; mock only, no hardware)
LOCAL FIXTURE TESTS: PASS (8 tests)
BRIDGE MOCK TESTS: PASS (30 tests; Maven clean verify)
WORKFLOW SYNTAX: PASS (actionlint v1.7.7 over all .github/workflows/*.yml)
WORKFLOW POLICY / STATIC SECURITY REVIEW: PASS
GIT DIFF --CHECK: PASS
REAL YUBIKEY OPERATION: NO
PIN USED: NO
PRODUCTION SIGNING: NOT RUN
RELEASE: NOT RUN
WORKFLOW MODIFIED: YES (mock-only workflow; production invocation is hard-disabled; no workflow dispatched)
ENVIRONMENT STRING ZEROIZATION: NOT GUARANTEED (documented Java getenv limitation)
REAL PIN / PRIVATE KEY OPERATION / APK SIGNING: NO / NO / NO
NEXT STEP: One-shot real Actions signing validation after the audited baseline is merged
```

The local fixture pipeline exercised build → artifact metadata → provenance/package/checksum gates → installed Bridge `--dry-run` → mock operation-count receipt → output verification simulation. The full GitHub Actions workflow itself has not been dispatched. The local checks do not count as real APK signing or hardware evidence.
