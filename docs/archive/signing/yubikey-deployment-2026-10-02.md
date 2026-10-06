# YubiKey Production Android Signing Deployment Report

Date: 2026-10-02
Repository: `billradar/rustdesk-custom`
Branch: `main`

## Deployment status

| Check | Result | Evidence |
|---|---|---|
| Host | PASS | Raspberry Pi host, Debian GNU/Linux 13, AArch64 / Debian arm64. |
| Runner installation | PASS | Official GitHub Actions Runner 2.337.0 ARM64 distribution is installed under `/opt/github-runner-rustdesk-signing`; runner executable, `bin/`, `externals/`, `run.sh`, `config.sh`, and `_work/` are present. The downloaded distribution checksum was verified before installation. |
| Runner service | PASS | `rustdesk-actions-runner.service` is `active/running`; `NRestarts=0`. Dedicated `github-runner` account is used. The stable launcher is root-owned; runner runtime and workspace are owned by `github-runner`. |
| Runner GitHub Online | PASS | GitHub API reports `raspberrypi-rustdesk-signing`, `online`, `busy=false`. |
| Runner labels | PASS | GitHub API reports `self-hosted`, `Linux`, `ARM64`, `rustdesk-signing`, `android-signing`, `yubikey`. |
| YubiKey discovery | PASS | As `github-runner`, OpenSC lists the YubiKey reader and PKCS#11 lists its token/slot without logging in or entering a PIN. |
| OpenSC / PC/SC | PASS | OpenSC 0.26.1; pcsc-lite 2.3.3. The runner account belongs to the dedicated `rustdesk-yubikey` group. |
| Java 21 | PASS | OpenJDK 21.0.12.1. |
| SunPKCS11 | PASS | As `github-runner`, Java dynamically configured `/etc/rustdesk-signing/yubikey-piv.cfg` and reported provider `SunPKCS11-YubiKeyPIV`. |
| 9C `PrivateKeyEntry` / Java alias | PASS (previously verified) | The deployment task records a prior actual Java KeyStore inspection: alias `Certificate for Digital Signature`, entry type `PrivateKeyEntry`, signer fingerprint matching the expected value. It was not re-enumerated in this run because no PIN was entered. |
| Expected signer | PASS | `559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5` is the fail-closed workflow fingerprint gate. |
| GitHub Environment | PASS | `android-production-signing` exists. It was created because it did not exist; no pre-existing protection rules were removed. |
| `YUBIKEY_PIV_PIN` | PRESENT | `gh secret list --env android-production-signing` returned the secret name and update time only. The value was not read, displayed, or tested. |
| Workflow static validation | PASS | actionlint v1.7.12 passed for all repository workflows; 81 Python tests passed and 3 were skipped; the focused Android signing tests passed (7/7); Python compilation and `git diff --check` passed. |
| Workflow security gates | PASS | Signing is restricted to the target repository, `main`, and two allowlisted caller workflows. It rejects untrusted PR/fork and arbitrary workflow callers; uses the dedicated runner labels; has a non-canceling YubiKey concurrency group; checks same-run artifact provenance, checksums, package/ABI and signer fingerprint; and injects the Environment secret only into the `apksigner sign` step. |
| Workflow deployment | PASS | Validated workflow changes were pushed to `billradar/rustdesk-custom` on `main` as commit `bea5532`. |

## PKCS#11 signing invocation

Installed apksigner version: 0.9. Its local `sign --help` documents `--ks-type`, `--ks-provider-class`, `--ks-provider-arg`, and password sources. The workflow uses the SunPKCS11 provider configuration and Java alias recorded above, with `--ks-pass env:YUBIKEY_PIV_PIN`. The Environment Secret is scoped to the one signing step; no PIN is placed in a command-line literal, file, workflow-level environment, or job-level environment. Shell tracing is disabled in that step.

## Safety status

- No YubiKey PIV operation that changes slot 9C was performed. No key was generated, reset, exported, deleted, or overwritten.
- The Root CA private-key file was not read or changed.
- The PIN value was not accessed by Codex. The only PIN-related GitHub operation checked secret metadata.
- The changed-file audit found no private-key markers, credential-token patterns, literal PIN assignments, or runner registration tokens. Runner registration credentials were not committed.
- No production APK signing workflow or Release was triggered as part of deployment verification.
- `APK PRODUCTION SIGNING: NOT VALIDATED`
- `LEGACY ANDROID SIGNING IDENTITY: NOT RECOVERED / NOT VALIDATED`

Environment Secret automation permits unattended signing. An attacker who can schedule the trusted signing workflow, use the Environment Secret, and execute code on the signing runner could request malicious signatures while the YubiKey is connected. The hardware keeps the private key non-exportable, but does not by itself prevent misuse of an authorized signing operation.
