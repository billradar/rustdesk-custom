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
