# Phase 5.2B-1.1 — Generic Production Signing Interface

**Result: PASS.** The generic CLI, explicit PIN sources, non-TTY dummy-secret mock path, and root-owned installation passed validation. The real workflow signing step remains hard-disabled. No real PIN, YubiKey private-key operation, APK signing, Release, Tag, commit, or push occurred.

## Outcome

| Requirement | Result | Evidence |
|---|---|---|
| Generic APK input | PASS | Installed dry-run accepted two different Standard RustDesk APKs, 1.4.9 and 1.5.0, both package `com.carriez.flutter_hbb`, aarch64 / `arm64-v8a` |
| Phase 5.1 fixed SHA removed from production path | PASS | No fixed digest in `src/main`; historical digest remains test-only and in prior evidence |
| APK input/output path guards | PASS | Unit tests cover missing input, malformed ZIP, wrong package, input=output, existing output, and symlink input |
| Input SHA identity | PASS | CLI hashes input before package/ABI policy and verifies the same hash after mock/signing operation |
| Package / ABI policy | PASS | `aapt dump badging` plus ZIP native-library check; exactly one supported RustDesk ABI required |
| Standard build variant | PASS at workflow boundary | Existing trusted workflow provenance gate requires `variant=standard`; APK-only CLI makes no provenance claim |
| Interactive PIN source | PASS (code/unit scope) | Explicit `console` source calls `Console.readPassword`; default is console; no environment fallback; no real prompt invoked this round |
| Environment PIN source | PASS WITH DUMMY | Installed non-TTY mock used a dummy `YUBIKEY_PIV_PIN`; missing/empty, explicit selection, and no implicit fallback unit cases passed |
| Non-TTY mock signing | PASS | Installed mock dry-run on both APKs copied a mock output, verified input unchanged, and reported no PKCS#11/YubiKey operation |
| PIN in signer argv / on disk / logs | NO / NO / NO (real PIN) | CLI takes only paths and source selector; dummy was supplied as an environment value; captured test output contained no dummy PIN |
| Bridge mutable PIN buffers | PASS | Success and exception path tests confirmed source and per-operation mutable buffers are zeroized |
| Environment String zeroization | NOT GUARANTEED | `System.getenv` materializes an immutable Java `String`; documented in source, README, and this report |
| Phase 5.1 regression | PASS | Existing mock signing core tests pass; historical APK accepted by installed generic mock CLI and its historical digest is test-only |
| Installation / permissions / integrity | PASS | Root-owned install, manifest verification, `--verify-install`, runner write denial |
| Workflow validation | PASS | Actionlint over all workflow YAML; production hardware step guarded by `if: false` |

## Generic CLI and safeguards

Production invocation:

```text
/usr/local/bin/rustdesk-sign \
  --input <input.apk> \
  --output <output.apk> \
  --pin-source env
```

`--pin-source` defaults to `console`. `env` mode must be requested explicitly and reads only `YUBIKEY_PIV_PIN`. The CLI rejects symlink components, missing or non-regular input, missing output directory, existing output, input/output equality, malformed APK archives, non-RustDesk package names, unsupported architectures, and anything other than exactly one supported `librustdesk.so` ABI. It hashes input before APK policy validation, stages apksig output in a mode-0600 temporary file next to the requested output, hashes input again after signing, and publishes without replacing an existing output.

Supported native ABIs match current Standard Android signing workflow policy: `arm64-v8a`, `armeabi-v7a`, or `x86_64`. The enclosing workflow must provide the trusted same-run provenance, Standard variant, source identity, and validation-library checksum gates. CLI package/ABI acceptance alone is not a provenance guarantee.

The signing core remains frozen at baseline commit `6eb2513262d89c377c9ad6d48d41da92a6cd5644`. Changes are in outer CLI, input policy, PIN-source adapter, mock flow, packaging launcher, and tests. No PKCS#11, adaptive key selection, context-specific authentication, JCA SPI, ECDSA conversion, or apksig algorithm implementation was changed.

## PIN lifecycle and threat boundary

The interactive source reads only through Java Console. The environment source does not run unless `--pin-source env` is explicit. It converts the returned Java environment String promptly to a mutable array; the String itself cannot be deterministically cleared. The Bridge clears its mutable owner and per-operation copies in `finally` paths. No exception message containing arbitrary detail or PIN text is printed; signing failures report a PKCS#11 error code or exception class.

The self-hosted `github-runner` account remains in the signing trusted computing base because it has PC/SC access. Root-owned Bridge files prevent modification of the installed copy; they cannot stop a compromised workflow or runner account from directly using OpenSC/PKCS#11. Environment review protects the repository/workflow authorization boundary, not a fully compromised runner.

## Deployment evidence

```text
INSTALL PATH: /opt/rustdesk-signing-bridge
STABLE CLI: /usr/local/bin/rustdesk-sign
BRIDGE VERSION: 0.1.0-SNAPSHOT / phase5.2b-1.1
SOURCE BASELINE: 6eb2513262d89c377c9ad6d48d41da92a6cd5644 (uncommitted worktree build)
BRIDGE JAR SHA256: 6d8c42b0700544ad082257de0044698ec3d097519acdf029adddd2452f6a2710
LAUNCHER SHA256: 93c5f849328b9ac4029951906529b881d77e37ae42e2ee591cff0115c027b221
MANIFEST SHA256: 0dfa1793c62d8141ab797c902d8e0ad541293717b3e292334d1d4665ba2620c2
OWNER: root:root
RUNNER MODIFY: NO
INSTALL HASH CHECK: PASS
VERIFY INSTALL: PASS
NO-PIN SELF-TEST: PASS
```

Environment: Debian 13 aarch64, OpenJDK `21.0.12.1+1-1~deb13u1`, Maven `3.9.9`, OpenSC `0.26.1-2`, pcsc-lite `2.3.3-1`, XiPKI wrapper `1.0.9`, apksig `0.9`.

## Test record

```text
mvn --batch-mode --file tools/android-signing-bridge/pom.xml clean test: 34 PASS
mvn --batch-mode --file tools/android-signing-bridge/pom.xml clean package: 34 PASS
Phase 5.2A gate tests: 8 PASS
Deployment tests: 5 PASS
Installed no-PIN self-test: PASS
Installed generic mock CLI, Phase 5.1 APK: PASS
Installed generic mock CLI, separate 1.5.0 Standard APK: PASS
Actionlint, all .github/workflows/*.yml: PASS
git diff --check: PASS
Temporary APK test copies/output cleanup: PASS
```

The 1.4.9 test input SHA-256 was `596591B25C4910D7E17FBD2EC499DC2592B06256965F6C50A885B538F6E81325`; it is accepted because of package/ABI policy, not because production code pins that value. The separate 1.5.0 input SHA-256 was `3DF1E82B2A83C877996885616080DA79FFA5962F9FD59D22C4A00F87CFF6FEA9`. Both dry-runs used only a dummy environment value, generated a byte-for-byte mock copy, confirmed source immutability, and did not load PKCS#11.

## Remote authorization and workflow state

`android-production-signing` previously had `main` deployment policy, reviewer `billradar`, and prevent-self-review enabled. `billradar` is the only collaborator, so Environment approval is blocked by single-collaborator self-review. The secret name was previously confirmed by metadata; its value was not read in this phase. `main` branch protection remains unconfigured. No GitHub repository security setting was weakened or changed.

`.github/workflows/sign-android.yml` now contains the future installed CLI syntax and scopes `YUBIKEY_PIV_PIN` to that signing step. The step is explicitly and unconditionally disabled with `if: false`, so this change cannot trigger hardware signing. The mock workflow remains secret-free and was not dispatched.

```text
PHASE 5.1: PASS / FROZEN
PHASE 5.2A: PASS (LOCAL MOCK + STATIC)
PHASE 5.2B-1: FAIL-CLOSED / HARDENING COMPLETED
PHASE 5.2B-1.1: PASS
ENVIRONMENT AUTHORIZATION: BLOCKED BY SINGLE-COLLABORATOR SELF-REVIEW
MAIN BRANCH PROTECTION: NOT CONFIGURED
REAL PIN USED: NO
PRIVATE KEY OPERATION: NO
PRODUCTION APK SIGNED: NO
YUBIKEY MODIFIED: NO
RELEASE / TAG: NO / NO
COMMIT / PUSH: NO / NO
```

Stop here. A future authorized phase must resolve remote approval policy before enabling the real workflow step or attempting one real hardware signing operation.
