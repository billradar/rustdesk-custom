# Android production signing

[English](android-production-signing.md) · [简体中文](android-production-signing-zh.md)

## Purpose and boundary

Android Standard production signing uses a dedicated hardware-backed path, separate from ordinary CI builds. Normal CI must not access the production GitHub Environment, YubiKey, PKCS#11 device, or PIN.

Signing must be explicitly authorized by the protected Stable workflow and satisfy repository, branch, event, build, and qualification conditions. A successful build alone cannot trigger production signing.

## Recorded identity

The machine-readable record is `metadata/signing/android-standard.json`. It identifies package `com.carriez.flutter_hbb`, YubiKey PIV slot `9C`, PKCS#11 object ID `02`, and production certificate SHA-256 `559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5`.

The repository maintains this production identity and no longer retains the old certificate fingerprint, old APK checksums, or keystore configuration. App-update compatibility is a separate test: matching package names or the presence of v3 signing does not prove that an APK can update an installation signed with another certificate.

## Execution path

1. A regular Android build job creates test-signed artifacts.
2. The isolated `android-sign` job runs only in the workflow's restricted context.
3. It uses the dedicated self-hosted ARM64 runner labels: `self-hosted`, `linux`, `arm64`, `rustdesk-signing`, `android-signing`, and `yubikey`.
4. The job enters the `android-production-signing` GitHub Environment.
5. `YUBIKEY_PIV_PIN` is exposed only to required preflight/signing steps and must never be printed or passed to ordinary build jobs.
6. Helpers verify source, package, ABI, signing identity, and result; any mismatch fails closed.
7. Signed results undergo final aggregation checks.

Verify actual runner, Environment, and Secret configuration in GitHub settings; documentation cannot confirm live configuration.

## Before signing

- [ ] Confirm this is the protected Stable Release Pipeline, not ordinary CI or an unapproved Nightly path.
- [ ] Verify the target custom commit and upstream SHA have matching qualification.
- [ ] Confirm the workflow explicitly authorizes production signing.
- [ ] Confirm the dedicated runner is online and trusted.
- [ ] Verify Environment approvals and Secret configuration.
- [ ] Compare public identity metadata with the physical signing hardware.
- [ ] Ensure artifact source, ABI, package name, and checksums are traceable.

## Operation

Run Stable Release Pipeline from GitHub Actions. Check branch, commit, upstream version, and mode. A dry-run can validate non-destructive release gates but cannot validate actual hardware signing. When every authorization, runner, and identity condition is satisfied, run the authorized production path. Inspect signing, certificate verification, upload, and aggregation results. Save the run URL and non-sensitive verification summary; never save PINs or replayable signing material.

## Cryptographic overview

APK signing protects APK content and identifies the signer. The configured path uses a YubiKey hardware key in PIV slot `9C`, EC curve `secp384r1`, and the runner-installed `/usr/local/bin/rustdesk-sign` interface. The private key should remain on the hardware token. The PIN authorizes token access; it is not the private signing key.

The signing tool signs APK data, writes signature metadata and certificate into the APK, and then `apksigner verify` checks the result. The certificate SHA-256 must exactly match the expected fingerprint; package, ABI, and provenance are checked again before release.

| Scheme | Role | Repository gate |
| --- | --- | --- |
| v1 (JAR) | Legacy entry-level signing | Cannot satisfy production gate alone |
| v2 | Protects APK contents using the APK Signing Block | Must verify successfully |
| v3 | Adds SDK-range metadata and rotation-proof structure | Must verify successfully alongside v2 |

Passing v2/v3 checks does not prove installation, upgrade, or key rotation behavior on every Android version. See the Android Open Source Project documentation for [APK signing](https://source.android.google.cn/docs/security/features/apksigning?hl=en), [v2](https://source.android.google.cn/docs/security/features/apksigning/v2?hl=en), and [v3](https://source.android.google.cn/docs/security/features/apksigning/v3?hl=en).

## Artifact checks

Before signing, `scripts/signing/android_yubikey_sign.py` verifies the unique build-info file, absence of symlinks, required manifests/native library, SHA256SUMS, platform/variant/ABI/repository/commit/run identity, source manifest hash, exactly one APK per ABI, original APK signature, package name, and equality of the APK native library to the validated build output. Any failed check stops signing.

After signing, it verifies APK signature and certificate fingerprint, requires both v2 and v3, rechecks package and ABI, updates build metadata, writes `android-signing-verification.json`, regenerates `SHA256SUMS`, uploads signed artifacts, and cleans temporary data. The receipt supports audit but does not replace signature verification.

## Update compatibility

An identical Android package name does not make differently signed APKs upgrade-compatible. v3 proof-of-rotation can support a key transition only when a valid rotation chain has been created and verified. Current signing checks prove the new identity's signature; they do not prove compatibility with older APKs signed by another certificate. Seamless upgrades require a verifiable previous identity/rotation chain and real-device upgrade tests.

## Prohibited practices

- Never put `YUBIKEY_PIV_PIN` in repository files, command-line arguments, logs, PR comments, or documentation.
- Never expose production secrets to ordinary builds, untrusted PRs, or unprotected jobs.
- Never replace hardware signing with a software key to bypass a failed gate.
- Stop when source, identity, or runner trust is uncertain.
- Do not equate tool availability or a successful signing job with verified upgrade compatibility.
