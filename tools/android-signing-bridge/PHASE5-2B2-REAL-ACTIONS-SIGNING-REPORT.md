# Phase 5.2B-2 GitHub Actions YubiKey Signing Validation

**Result:** FAIL before PIN acquisition; APK production signing remains **NOT VALIDATED**.

## Run identity

| Item | Result |
|---|---|
| Repository | `billradar/rustdesk-custom` |
| Main commit used by run | `f0093b842a8828ad2c2093c67a368a5eda8ce381` |
| Workflow run | [37121654783](https://github.com/billradar/rustdesk-custom/actions/runs/37121654783) |
| Event / ref | `workflow_dispatch` / `main` |
| Dispatch count | 1 |
| Official input release | RustDesk `1.4.9` (informational only) |
| Runner | `raspberrypi-rustdesk-signing`, `github-runner`, Linux ARM64 |
| Environment | `android-production-signing`; `YUBIKEY_PIV_PIN` existence confirmed from metadata only; value was never queried by the agent |
| Signing workflow result | Failed in the one authorized signing-step invocation |

The source resolver, compatibility checks, bridge build, Flutter analysis, Android ARM64 Standard build, and same-run artifact provenance/package/ABI checks passed. The unsigned artifact was `android-build-input-signing-validation-1.4.9-6c578292e8ebbbec708b76986ba8c4bc7c509747-standard-android-aarch64`.

## Signing-step evidence

The runner log reported `APKSIG SIGNING: FAIL (IllegalStateException)`. It included the expected hardware signature count of 2, but no actual signature count, `PIN SOURCE`, PIN zeroization, PKCS#11 error code, or successful signed-artifact verification. Session/module cleanup reported PASS. The signed-artifact verification and upload steps were skipped.

The input passed the signing bridge's package and ABI policy checks: `com.carriez.flutter_hbb`, `arm64-v8a`. Input APK SHA-256: `84BDA289EFF1D73F930F9B5A249C1A8945386DB121FDDEA3058C53FB81E4057B`. The selected signature schemes were v1 and v2; v3 and later schemes were disabled. The configured expected hardware signature count was 2; actual count was not reached.

The bridge source calls `EnvironmentPinSource.readPin()` before constructing the JCA provider or invoking apksig. That source throws `IllegalStateException` when the `YUBIKEY_PIV_PIN` process environment lookup returns null or empty. The missing `PIN SOURCE` marker and the failure class are consistent with that pre-signing failure path. The safe error handler intentionally emits only the exception class, so the exact branch message is not present in the runner log. The available evidence does not identify why the process environment lookup was empty or unavailable.

**Therefore:** the workflow's hardware-signing step was invoked once, but there is no evidence that Java accepted a PIN, called `C_Login`, `C_SignInit`, or `C_Sign`, or ran apksig's signer. No PIN value was printed or queried by the agent. No private-key operation or YubiKey modification occurred. The run produced no signed APK artifact and did not create a tag, release, or store publication.

## Runtime and gate state

- Installed bridge: `0.1.0-SNAPSHOT`, interface revision `phase5.2b-1.1`, built from baseline `6eb2513262d89c377c9ad6d48d41da92a6cd5644`; installed bytecode and read-only integrity checks passed before dispatch.
- OpenJDK: `21.0.12.1+1-1~deb13u1`; XiPKI PKCS#11 wrapper: `1.0.9`; apksig: `0.9` (informational only).
- Bridge's read-only token/certificate identity check passed. Fingerprint and release version are recorded policy metadata only; this run did not establish signing success or a production-signed APK identity.
- The one-shot workflow input was closed after the run. PR #3 merged at `35ea34469b8b7707098fe0a1384f74870bac4d88`; main now sets `validation_enable_signing: false`.
- No retry, workflow rerun, APK signing continuation, tag, or release was performed.

## Final status

```text
PRE-SIGN BUILD AND ARTIFACT GATES: PASS
YUBIKEY SIGNING STEP INVOCATIONS: 1
ENVIRONMENT PIN SOURCE: UNAVAILABLE OR EMPTY TO THE JAVA PROCESS
PIN ACCEPTED BY BRIDGE: NO EVIDENCE
PKCS#11 LOGIN: NOT REACHED
PRIVATE-KEY SIGNATURE OPERATIONS: 0 EVIDENCED
APKSIG SIGNER INVOCATION: NOT REACHED
SIGNED APK / APK VERIFY: NOT RUN
SIGNED APK ARTIFACT UPLOAD: SKIPPED
ONE-SHOT VALIDATION GATE: CLOSED
APK PRODUCTION SIGNING: NOT VALIDATED
LEGACY ANDROID SIGNING IDENTITY: NOT RECOVERED / NOT VALIDATED
WORKFLOW MODIFIED: YES, TEMPORARY GATE ENABLED AND THEN CLOSED
YUBIKEY MODIFIED: NO
```

## Phase 5.2B-2.5: GitHub Environment Secret Visibility Matrix

**PHASE:** 5.2B-2.5

**RESULT:** FAIL (the matrix completed and isolated the failing boundary)

**PROBE SECRET:** `SECRET_CONTEXT_PROBE` (dummy Environment Secret)

**SECOND PROBE:** `SECRET_CONTEXT_PROBE_2` (dummy repository Secret, used only for explicit `workflow_call` passing)

**SECRET VALUE OBSERVED:** NO

### Documented behavior

GitHub documents that Environment secrets cannot be passed by the caller through `workflow_call`. When the called workflow binds an Environment to its job, that job's Environment secret is used; an identically named secret passed by the caller does not replace it. The probe therefore tested the Environment-bound called job and, separately, an explicitly passed dummy caller secret. [GitHub documentation: reusing workflows and using inputs and secrets](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows#using-inputs-and-secrets-in-a-reusable-workflow)

### Observed behavior

| Path / layer | Result | Evidence |
|---|---|---|
| Direct workflow → Environment `secrets` context | PASS | Direct run emitted context PASS. |
| Direct workflow → step environment mapping | PASS | Direct run emitted mapping PASS. |
| Direct workflow → child process environment | PASS | Direct run emitted process PASS. |
| Reusable job Environment → `secrets` context | FAIL | Reusable run emitted Environment context FAIL. |
| Reusable job Environment → step mapping | FAIL | Reusable run emitted mapping FAIL. |
| Reusable job Environment → child process | FAIL | Reusable run emitted process FAIL. |
| Caller dummy secret → declared `workflow_call` secret → `secrets` context | PASS | Reusable run emitted context PASS. |
| Explicit `workflow_call` secret → step mapping | PASS | Reusable run emitted mapping PASS. |
| Explicit `workflow_call` secret → child process | PASS | Reusable run emitted process PASS. |

The Environment `android-production-signing` exists, has a custom deployment branch policy permitting `main`, and has no required reviewers. Both runs recorded an Environment deployment for `main` at commit `7ae5e80da617754f16357c7391c2a86049bc5bae`. The `SECRET_CONTEXT_PROBE` Environment Secret and `SECRET_CONTEXT_PROBE_2` repository Secret were confirmed present by name metadata only. `YUBIKEY_PIV_PIN` was confirmed present by metadata only; its value and all derived information were not read. Its reported `updated_at` remained `2026-10-03T15:12:02Z`.

Both jobs ran on `raspberrypi-rustdesk-signing`, Linux, runner version `2.337.0`; the runner API architecture field was null, and its labels include `ARM64`. Direct run `37137026747` succeeded. Reusable run `37137083721` failed closed because the Environment-secret path was empty, while the separately passed dummy `workflow_call` path passed.

### Root cause boundary and production impact

**ROOT CAUSE BOUNDARY:** The dummy Environment Secret is available to a direct Environment-bound job, but is not available in the `secrets` context of this Environment-bound reusable-workflow job. The general reusable-workflow `workflow_call` secret route works. This isolates the failure to the Environment Secret × reusable-job path, before step mapping. The underlying reason for the mismatch with the documented behavior is **NOT DETERMINED** by these safe observations.

**FIX:** NONE. No production workflow was changed. The dummy `workflow_call` result does not prove that an Environment Secret can be read by the caller and forwarded: GitHub documents that Environment secrets are not passable from a reusable-workflow caller, and the caller job that invokes a reusable workflow cannot itself bind the job Environment. A production change to restructure the signing workflow or use a different documented Environment-secret path is therefore required before another production-secret attempt. Do not move `YUBIKEY_PIV_PIN` to repository scope. **PRODUCTION WORKFLOW CHANGE REQUIRED: YES; not implemented in this phase.**

`validation_enable_signing` remains `false`. The direct and reusable probes are dispatch-only, restricted to the exact repository/ref/workflow, use the dedicated runner and Environment, and inspect only non-empty booleans for the two dummy probe secrets. No probe printed or compared a Secret value.

### Final status

```text
PHASE: 5.2B-2.5
PROBE SECRET: SECRET_CONTEXT_PROBE
SECRET VALUE OBSERVED: NO
DIRECT WORKFLOW: PASS (run 37137026747)
DIRECT ENV SECRET CONTEXT / STEP MAPPING / PROCESS: PASS / PASS / PASS
REUSABLE WORKFLOW: FAIL (run 37137083721)
REUSABLE ENV SECRET CONTEXT / STEP MAPPING / PROCESS: FAIL / FAIL / FAIL
WORKFLOW_CALL SECRET PATH: PASS
WORKFLOW_CALL SECRET CONTEXT / STEP MAPPING / PROCESS: PASS / PASS / PASS
ENVIRONMENT SECRET PATH: FAIL in reusable job; PASS in direct job
ROOT CAUSE: Environment Secret × reusable-job visibility boundary; underlying reason NOT DETERMINED
FIX: NONE
PRODUCTION WORKFLOW CHANGE REQUIRED: YES (not implemented)
BRIDGE: NOT STARTED (YubiKey signing bridge)
PKCS11: NOT INITIALIZED
PRIVATE KEY: NOT USED
APK SIGNING: NOT RUN
YUBIKEY: NOT MODIFIED
YUBIKEY_PIV_PIN: PRESENT (metadata only; value not read or modified)
SIGNING GATE: CLOSED (`validation_enable_signing: false`)
READY FOR HARDWARE ATTEMPT #2: NO
APK PRODUCTION SIGNING: NOT VALIDATED
LEGACY ANDROID SIGNING IDENTITY: NOT RECOVERED / NOT VALIDATED
```

The PR CI also ran the repository's ordinary RustDesk Flutter/FFI bridge compatibility build; it did not start the YubiKey signing bridge or initialize PKCS#11.

The next investigation should determine, without exposing its value, why the environment-level secret was not visible as a nonempty process environment variable in the called workflow's signing process. Do not repeat this signing workflow until that wiring is understood and separately authorized.

## Evidence links

- [Successful pre-sign CI checks for the one-shot enable PR](https://github.com/billradar/rustdesk-custom/pull/2)
- [Single workflow dispatch and failed signing job](https://github.com/billradar/rustdesk-custom/actions/runs/37121654783)
- [One-shot gate closure PR](https://github.com/billradar/rustdesk-custom/pull/3)
- [GitHub documentation: reusable workflows and environment secrets](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)

## Phase 5.2B-2.1: Environment PIN delivery preflight

**Implementation status:** fail-closed preflight and safe diagnostics implemented; no hardware validation was performed.

### Audit of the failed run

The actual run commit (`f0093b842a8828ad2c2093c67a368a5eda8ce381`) was audited, not inferred from the current checkout:

- Caller `android-sign` invokes `.github/workflows/sign-android.yml` and does not pass a PIN through `workflow_call`.
- The called workflow's actual `sign` job binds `environment.name: android-production-signing`.
- Only the `Production YubiKey signing` step maps `YUBIKEY_PIV_PIN: ${{ secrets.YUBIKEY_PIV_PIN }}`. The job and workflow have no PIN environment mapping.
- GitHub deployment metadata records an `android-production-signing` deployment for the failed run commit. Environment secret metadata listed the exact name `YUBIKEY_PIV_PIN`; the secret value was not queried. Repository-level secret names did not include this PIN secret.
- The existing bridge resolves the environment source before JCA provider creation and before the apksig invocation. Its source rejects a null or empty environment lookup. The run's safe error class and missing `PIN SOURCE` marker are consistent with that early failure; there is no evidence of login or a private-key operation.

**Root cause established to the available evidence boundary:** Java's `YUBIKEY_PIV_PIN` environment lookup resolved as missing or empty during that run, so the bridge stopped at PIN-source acquisition. The caller/reusable-workflow wiring, signing-job Environment binding, and step-level secret expression were correctly placed. Metadata proves the named Environment secret existed, but does not prove its stored value was nonempty or what GitHub injected into that process. Its value and runtime content were intentionally not inspected, so the underlying reason that resolution was empty cannot be distinguished further from this run alone.

### Fix and dummy-only regression

The signing step now checks `${YUBIKEY_PIV_PIN:-}` before creating the signing output directory or invoking `/usr/local/bin/rustdesk-sign`. It emits only `ENVIRONMENT PIN AVAILABLE: PASS` or `ENVIRONMENT PIN AVAILABLE: FAIL`, failing closed on the latter. Secret injection remains scoped to this single signing step. The validation workflow's `validation_enable_signing` input remains `false`.

The bridge now reports absent/empty environment input with only:

```text
PIN SOURCE: ENVIRONMENT
ENVIRONMENT PIN AVAILABLE: FAIL
FAILURE STAGE: PIN SOURCE
```

Local dummy tests cover nonempty source resolution, null/empty fail-closed behavior, safe diagnostic output, and mutable-buffer zeroization. No real `YUBIKEY_PIV_PIN` was used. This implementation cannot establish live GitHub runtime delivery without a future separately authorized hardware workflow invocation; the new preflight will report only a boolean before starting the bridge.

### Phase status

```text
FAILED RUN: 37121654783
FAILURE STAGE: PIN SOURCE (consistent with bridge source and observed safe error; underlying empty cause not independently observable)
ROOT CAUSE: process environment lookup was null/empty; workflow wiring is correctly scoped; reason for the empty runtime value remains unproven
ENVIRONMENT: android-production-signing
ENVIRONMENT SECRET METADATA: YUBIKEY_PIV_PIN PRESENT
SECRET VALUE ACCESSED BY INVESTIGATION: NO
SIGNING JOB ENVIRONMENT BINDING: PASS
SIGNING STEP SECRET MAPPING: PASS
EMPTY-SECRET PREFLIGHT: IMPLEMENTED
BRIDGE SAFE PIN-SOURCE DIAGNOSTIC: PASS (dummy tests)
REAL PIN USED: NO
PRIVATE KEY OPERATION: NO
YUBIKEY MODIFIED: NO
APK SIGNED: NO
ONE-SHOT GATE: CLOSED
APK PRODUCTION SIGNING: NOT VALIDATED
LEGACY ANDROID SIGNING IDENTITY: NOT RECOVERED / NOT VALIDATED
```

The implementation adds earlier, value-free detection but does not claim that it resolves the unknown cause of GitHub's empty runtime value. No real signing run was triggered.

## Phase 5.2B-2.2: Environment Secret Delivery Runtime Probe

**Result: FAIL.** This was a secret-availability probe only, not a hardware signing attempt.

| Item | Result |
|---|---|
| Probe workflow | `Android Environment Secret Delivery Probe` |
| Probe run | [37130243147](https://github.com/billradar/rustdesk-custom/actions/runs/37130243147) |
| Probe commit | `4f5c0195b5952ae8db804a46503bff16852ecdca` |
| Event / ref | `workflow_dispatch` / `main` |
| Runner | `raspberrypi-rustdesk-signing`; labels matched the dedicated self-hosted signing runner |
| Environment | `android-production-signing` |
| Secret metadata | `YUBIKEY_PIV_PIN` present; value was not read |
| Signing job Environment binding | PASS |
| Step-scoped Secret mapping | PASS |
| Environment PIN availability | **FAIL** |

The target job ran on the dedicated runner with the expected labels and Environment. Its only step emitted `ENVIRONMENT PIN AVAILABLE: FAIL` and failed closed. The job definition has no steps before or after the probe, and its only Secret mapping is on that step. The one-shot production signing gate remained `false`.

The probe log contained no invocation of `/usr/local/bin/rustdesk-sign`, no Bridge or PKCS#11 initialization markers, no `C_Login`, `C_SignInit`, `C_Sign`, `apksigner sign`, or private-key operation. The Secret value and all derived data were neither observed by a human nor logged. No APK was signed and the YubiKey was not modified.

The result means GitHub did not provide a nonempty value to this probe step. Metadata confirms the secret name exists, but cannot distinguish an empty/unusable configured value from another GitHub Environment/runtime delivery issue. **`YUBIKEY_PIV_PIN MAY REQUIRE USER RECONFIGURATION`** in the GitHub Environment UI. No secret was changed, overwritten, or deleted by this investigation.

```text
PHASE 5.2B-2.2: FAIL
GITHUB ENVIRONMENT SECRET DELIVERY: NOT VALIDATED
ENVIRONMENT PIN AVAILABLE: FAIL
SECRET VALUE OBSERVED BY HUMAN: NO
SECRET VALUE LOGGED: NO
SECRET LENGTH / HASH / DERIVED DATA LOGGED: NO
BRIDGE STARTED: NO
PKCS11 INITIALIZED: NO
C_LOGIN: NO
C_SIGNINIT: NO
C_SIGN: NO
PRIVATE KEY OPERATION: NO
APK SIGNED: NO
YUBIKEY MODIFIED: NO
HARDWARE SIGNING ATTEMPTS THIS PHASE: 0
VALIDATION SIGNING GATE: CLOSED
READY FOR SECOND AUTHORIZED PHASE 5.2B-2 HARDWARE ATTEMPT: NO
APK PRODUCTION SIGNING: NOT VALIDATED
LEGACY ANDROID SIGNING IDENTITY: NOT RECOVERED / NOT VALIDATED
```

Per the probe stop condition, no redispatch or hardware signing was attempted. After the Environment Secret owner has reviewed/reconfigured the existing secret if needed, a new probe requires a separate explicit authorization; hardware signing remains a separate authorization.

## Phase 5.2B-2.3: Environment Secret Reconfiguration Verification

**Result: FAIL.** The user re-saved the existing Environment Secret before this probe. The Secret value was not observed or accessed by the agent.

| Item | Result |
|---|---|
| Previous probe | [37130243147](https://github.com/billradar/rustdesk-custom/actions/runs/37130243147), `ENVIRONMENT PIN AVAILABLE: FAIL` |
| User reconfigured Secret | YES, as reported by the user; agent did not modify it |
| Secret metadata | `YUBIKEY_PIV_PIN` present; `updated_at: 2026-10-03T15:12:02Z` |
| New probe workflow | `Android Environment Secret Delivery Probe` |
| New probe run | [37132595356](https://github.com/billradar/rustdesk-custom/actions/runs/37132595356) |
| Probe commit | `3867fbf882da766b1fa428adcc469a2cf6eb866a` |
| Event / ref / attempt | `workflow_dispatch` / `main` / 1 |
| Runner | `raspberrypi-rustdesk-signing`, expected dedicated runner labels |
| Environment deployment | PASS; deployment `6829329951`, `android-production-signing`, ref `main`, matching probe commit |
| Job Environment binding | PASS |
| Step-scoped Secret mapping | PASS |
| Environment PIN availability | **FAIL** |

The target probe step emitted `ENVIRONMENT PIN AVAILABLE: FAIL` and the job failed closed. Read-only run metadata confirms the repository, workflow path, ref, event, attempt, runner labels, and matching Environment deployment. The reusable job binds the Environment and maps the Secret only into its single probe step, as designed. The `validation_enable_signing` gate remains `false`.

The job log contained no signer invocation, Bridge startup, PKCS#11 initialization, `C_Login`, `C_SignInit`, `C_Sign`, `apksigner sign`, or private-key operation. No APK was signed; the YubiKey was not modified. No value, length, hash, or other Secret-derived data was inspected or logged.

```text
PREVIOUS PROBE RUN: 37130243147
PREVIOUS RESULT: ENVIRONMENT PIN AVAILABLE: FAIL
SECRET RECONFIGURED BY USER: YES
SECRET VALUE OBSERVED BY AGENT: NO
SECRET METADATA: PRESENT
SECRET UPDATED METADATA: 2026-10-03T15:12:02Z
NEW PROBE RUN: 37132595356
NEW PROBE COMMIT: 3867fbf882da766b1fa428adcc469a2cf6eb866a
RUNNER: raspberrypi-rustdesk-signing
ENVIRONMENT: android-production-signing
ENVIRONMENT PIN AVAILABLE: FAIL
BRIDGE STARTED: NO
PKCS11 INITIALIZED: NO
C_LOGIN: NO
C_SIGNINIT: NO
C_SIGN: NO
PRIVATE KEY OPERATION: NO
APK SIGNED: NO
YUBIKEY MODIFIED: NO
HARDWARE SIGNING ATTEMPTS THIS PHASE: 0
VALIDATION SIGNING GATE: CLOSED
PHASE 5.2B-2.3: FAIL
GITHUB ENVIRONMENT SECRET DELIVERY: NOT VALIDATED
SECRET RECONFIGURATION: DID NOT RESOLVE RUNTIME DELIVERY
READY FOR PHASE 5.2B-2 HARDWARE ATTEMPT #2: NO
APK PRODUCTION SIGNING: NOT VALIDATED
LEGACY ANDROID SIGNING IDENTITY: NOT RECOVERED / NOT VALIDATED
```

Per the FAIL stop condition, there was no second probe and no signing attempt. Environment/workflow metadata and the reusable-workflow boundary were checked read-only; these all match the intended path. The runtime still resolves the step value as unset or empty. No further Secret edits or runs were made.

## Phase 5.2B-2.4: GitHub reusable-workflow Secret Context Diagnosis

**Result: FAIL.** One diagnostic probe ran after PR #9 merged. No further probe, signing, or Secret modification was performed.

### Current workflow chain audit

```text
android-signing-validation.yml (workflow_dispatch on main)
  └─ job android-sign
       uses: ./.github/workflows/sign-android.yml
       caller `secrets:` mapping: ABSENT
       └─ reusable workflow `on.workflow_call`
            `secrets:` contract: ABSENT
            └─ job sign
                 environment.name: android-production-signing
                 └─ step hardware-sign
                      env.YUBIKEY_PIV_PIN: ${{ secrets.YUBIKEY_PIV_PIN }}
```

The diagnostic probe follows the same reusable-workflow shape:

```text
android-signing-secret-probe.yml (workflow_dispatch on main)
  └─ job probe
       uses: ./.github/workflows/android-signing-secret-probe-job.yml
       caller `secrets:` mapping: ABSENT
       └─ reusable workflow `on.workflow_call`
            `secrets:` contract: ABSENT
            └─ job environment-pin-probe
                 environment.name: android-production-signing
                 └─ sole step
                      env.YUBIKEY_PIV_PIN: ${{ secrets.YUBIKEY_PIV_PIN }}
                      env.PIN_SECRET_CONTEXT_AVAILABLE: ${{ secrets.YUBIKEY_PIV_PIN != '' }}
```

The Environment is bound to the job inside the reusable workflow, not the caller or step. This is the intended place for an Environment secret in a reusable workflow: GitHub documents that Environment secrets cannot be passed by the caller through `workflow_call`, and that an Environment attached to a called-workflow job supplies its Environment secret there. Therefore the missing `workflow_call.secrets` declaration and absent caller `secrets:` mapping are confirmed facts, but are **not by themselves evidence of a defect** for this Environment-scoped secret. [GitHub reusable workflows documentation](https://docs.github.com/en/actions/sharing-automations/reusing-workflows#using-inputs-and-secrets-in-a-reusable-workflow)

The repository-level secret metadata list remains `RUSTDESK_KEY` and `RUSTDESK_PASSWORD`; it does not contain `YUBIKEY_PIV_PIN`. Environment metadata lists `YUBIKEY_PIV_PIN` as present (`updated_at: 2026-10-03T15:12:02Z`). No Secret value was queried.

### Diagnostic probe evidence

| Item | Result |
|---|---|
| Workflow | `Android Environment Secret Delivery Probe` |
| Run | [37134585246](https://github.com/billradar/rustdesk-custom/actions/runs/37134585246) |
| Commit | `e67cc9fda87b2bf574947b1225bbf20c248fef4b` |
| Event / ref | `workflow_dispatch` / `main` |
| Runner | `raspberrypi-rustdesk-signing`; dedicated labels matched |
| Environment deployment | PASS; deployment `6829691189`, matching commit and `main` |
| Job Environment binding | PASS |
| `secrets` context non-empty test | **FAIL** |
| Step environment mapping | **FAIL** |
| Child process environment | **FAIL** |
| `ENVIRONMENT PIN AVAILABLE` | **FAIL** |

The first failed layer observable in this matrix is the `secrets` context expression in the Environment-bound reusable job. The step mapping and child process then also received an unset/empty value. This identifies the loss point as **Environment secret → `secrets` context inside the reusable job**, before step environment mapping. It rules out the `bash` child process as the point where a nonempty mapped value was lost.

**ROOT CAUSE:** `NOT DETERMINED WITH AVAILABLE NON-SECRET OBSERVABILITY` beyond the identified loss point. The metadata API confirms secret-name existence and update time only; it cannot establish whether the stored value is nonempty or why the GitHub `secrets` context evaluated false. No conclusion is drawn about the Secret value. The production signing path was not run.

### Final status

```text
PREVIOUS PROBE: 37132595356
PREVIOUS RESULT: ENVIRONMENT PIN AVAILABLE: FAIL
WORKFLOW_CALL SECRET CONTRACT: ABSENT (probe and production signing reusable workflows)
CALLER SECRET PASSING: ABSENT (probe and production android-sign reusable job)
JOB ENVIRONMENT: PASS (reusable job)
STEP SECRET MAPPING: YAML PASS; runtime value empty
SECRETS CONTEXT: FAIL
PROCESS ENVIRONMENT: FAIL
NEW PROBE: 37134585246
ENVIRONMENT PIN AVAILABLE: FAIL
SECRET VALUE OBSERVED: NO
SECRET DERIVED DATA: NO
BRIDGE STARTED: NO
PKCS11: NO
C_LOGIN: NO
C_SIGNINIT: NO
C_SIGN: NO
APK SIGNED: NO
YUBIKEY MODIFIED: NO
VALIDATION SIGNING GATE: CLOSED
PHASE 5.2B-2.4: FAIL
GITHUB REUSABLE-WORKFLOW SECRET CONTEXT: NOT VALIDATED
ENVIRONMENT SECRET DELIVERY: NOT VALIDATED
READY FOR HARDWARE ATTEMPT #2: NO
APK PRODUCTION SIGNING: NOT VALIDATED
LEGACY ANDROID SIGNING IDENTITY: NOT RECOVERED / NOT VALIDATED
```

The context diagnostic was added through PR #9 and merged at `e67cc9fda87b2bf574947b1225bbf20c248fef4b`. Local actionlint v1.7.12, the Android workflow tests (11), and `git diff --check` passed before merge. The production signing gate remains `false`. Per the failure stop condition, no additional probe or signing action was taken.

## Phase 5.2B-2.6: Production Workflow Secret Context Structural Fix

**Result: PASS for the direct Android signing-validation workflow's non-sensitive Environment Secret path. Production signing remains NOT VALIDATED.** This phase used only `SECRET_CONTEXT_PROBE`; the real PIN Secret value and all derived data were not observed.

### Evidence adopted from Phase 5.2B-2.5

The direct Environment-bound job had passed the non-sensitive Environment Secret probe, while an Environment Secret in the reusable-workflow job had failed. In the same reusable-workflow experiment, explicitly passed `workflow_call` dummy secret succeeded. GitHub's documented behavior and the observed matrix localized the visibility boundary to the Environment secret inside that reusable job. This phase does not repeat or reinterpret that matrix.

### Current workflow and structural fix

The manual `android-signing-validation.yml` dispatch on `main` now has a normal `android-sign` job rather than `uses: ./.github/workflows/sign-android.yml`. That job directly binds `environment.name: android-production-signing` and runs on the dedicated self-hosted ARM64 signing runner. It downloads and verifies the same-run Android build artifact, then runs the non-sensitive probe. The production PIN remains referenced only by the explicit, separately gated hardware-sign step; the workflow input `validation_enable_signing` defaults to `false`.

The minimal fix removes the reusable-workflow boundary from this validation path so the job that owns the Environment also evaluates `secrets.SECRET_CONTEXT_PROBE`. The Environment secret's scope was not changed. This structural change does not claim that any separate stable/tag workflow which still calls the reusable signing workflow has been validated or repaired.

### Merge and runtime verification

| Item | Result |
|---|---|
| PR | [#13](https://github.com/billradar/rustdesk-custom/pull/13) |
| Merge commit | `f1dd3bda06216a8de904e4f395f6e73c47da1226` |
| CI | PASS; run [37138777409](https://github.com/billradar/rustdesk-custom/actions/runs/37138777409) |
| Probe run | [37139262585](https://github.com/billradar/rustdesk-custom/actions/runs/37139262585), `workflow_dispatch` on `main` at merge commit |
| Environment deployment | PASS; deployment `6830821952`, Environment `android-production-signing`, ref `main`, matching merge commit |
| Runner metadata | `raspberrypi-rustdesk-signing`; Linux; ARM64 label; runner version `2.337.0`; online and busy during the job |
| Same-run artifact provenance/checksum/package/ABI validation | PASS |
| `SECRET_CONTEXT_PROBE` context | PASS |
| Step mapping | PASS |
| Process environment | PASS |
| Production workflow structure | PASS |
| Android signing-validation run | SUCCESS |
| Hardware signing step | SKIPPED (`validation_enable_signing` default false) |
| Production verify/upload steps | SKIPPED |
| Workspace cleanup | PASS |
| `YUBIKEY_PIV_PIN` value or derived data observed | NO |

The build job produced the workflow's test-signed validation input artifact; no production signature operation ran and no production-signed APK was created. The real Environment Secret was neither queried nor modified. The Bridge was not started; PKCS#11 was not initialized; `C_Login`, `C_SignInit`, and `C_Sign` were not called; YubiKey was not accessed or modified.

```text
PHASE: 5.2B-2.6
PREVIOUS ROOT CAUSE BOUNDARY: Environment Secret × reusable-job visibility
CURRENT WORKFLOW: android-signing-validation.yml → direct Environment-bound android-sign job → step-scoped dummy probe; gated hardware step
STRUCTURAL FIX: make android-sign a direct job so its own job-level Environment supplies the secret context
PR: #13
MERGE COMMIT: f1dd3bda06216a8de904e4f395f6e73c47da1226
PROBE: 37139262585
ENVIRONMENT: PASS
SECRET_CONTEXT_PROBE: PASS
SECRET CONTEXT: PASS
STEP_MAPPING: PASS
PROCESS_ENVIRONMENT: PASS
REAL PIN OBSERVED: NO
YUBIKEY: NOT MODIFIED
BRIDGE: NOT STARTED
PKCS11: NOT INITIALIZED
C_LOGIN: NOT CALLED
C_SIGNINIT: NOT CALLED
C_SIGN: NOT CALLED
APK: NO PRODUCTION-SIGNED APK CREATED
SIGNING GATE: CLOSED
APK PRODUCTION SIGNING: NOT VALIDATED
LEGACY ANDROID SIGNING IDENTITY: NOT RECOVERED / NOT VALIDATED
READY FOR HARDWARE ATTEMPT #2: YES (direct validation path only; hardware attempt not performed)
```

## Phase 5.2B-2.7: Closeout and Evidence Archival

**Result: PASS.** This was a read-only closeout plus this report update. No new workflow run was dispatched and no hardware attempt was made.

### Final state checks

| Check | Observed result |
|---|---|
| PR #13 workflow structural fix | MERGED at `f1dd3bda06216a8de904e4f395f6e73c47da1226` |
| PR #14 Phase 5.2B-2.6 report | MERGED at `780dd715600a8b392b48b9d70bc5ff38633d09bd` |
| `android-production-signing` Environment | PRESENT; metadata endpoint returned this Environment and branch protection metadata |
| Environment `YUBIKEY_PIV_PIN` Secret | PRESENT by name in Environment Secret metadata; value NOT READ |
| Repository-scoped `YUBIKEY_PIV_PIN` | ABSENT by name in repository Secret metadata |
| `validation_enable_signing` | Defaults to `false`; the Phase 5.2B-2.6 dispatch omitted the input and the hardware-sign step was observed SKIPPED |
| Ordinary CI hardware signing | NOT TRIGGERED; compatibility CI runs had no signing job, and the hardware step requires the explicit validation input and exact manual validation workflow ref |
| PIN disclosure | NONE OBSERVED; no PIN value was queried, emitted, or placed in this report. The validation run emitted only fixed PASS/FAIL markers for the dummy probe |
| YubiKey / PKCS#11 operation | NONE; the hardware-sign step was skipped in run `37139262585`; no PKCS#11 initialization or signing call was made in this phase |
| Phase 5.2B-2.6 probe | PASS in run `37139262585`; Environment, Secret Context, step mapping, and process environment all PASS |
| APK production signing | NOT VALIDATED; no production signing step executed |

### Workflow trigger boundary

The compatibility CI workflows do not invoke the Android signer. The nightly reusable build caller leaves `production_android_signing` at its default `false`. The dedicated validation workflow defaults `validation_enable_signing` to `false` and requires an explicit `workflow_dispatch` with that input set to `true` before its hardware-sign step can run. The separate tag workflow is a manual release path, not ordinary CI; its reusable signing job and inner hardware-step conditions differ, so this closeout does not claim that the tag signing path is validated.

The Environment Secret metadata confirms scope and presence only; it does not reveal or verify the value. Repository Secret metadata does not list `YUBIKEY_PIV_PIN`. The dedicated dummy Secret remains separate from the production PIN. No Secret was changed.

```text
PHASE: 5.2B-2.7
RESULT: PASS
PR #13: MERGED (f1dd3bda06216a8de904e4f395f6e73c47da1226)
PR #14: MERGED (780dd715600a8b392b48b9d70bc5ff38633d09bd)
ENVIRONMENT android-production-signing: PRESENT
YUBIKEY_PIV_PIN ENVIRONMENT SECRET: PRESENT BY METADATA; VALUE NOT READ
YUBIKEY_PIV_PIN REPOSITORY SECRET: ABSENT BY METADATA
validation_enable_signing: DEFAULT FALSE; HARDWARE STEP SKIPPED IN RUN 37139262585
ORDINARY CI HARDWARE SIGNING: NOT TRIGGERED
REAL PIN LEAK: NONE OBSERVED; VALUE NEVER READ
YUBIKEY / PKCS11 OPERATIONS: NONE
APK PRODUCTION SIGNING: NOT VALIDATED
READY FOR HARDWARE ATTEMPT #2: YES
HARDWARE ATTEMPT #2: NOT EXECUTED
```

**Phase 5.2B closeout:** 2.5 Secret Context Investigation PASS; 2.6 Workflow Structural Fix PASS; 2.7 Closeout / Archival PASS. **Stop here.** Hardware Attempt #2 was not executed.
