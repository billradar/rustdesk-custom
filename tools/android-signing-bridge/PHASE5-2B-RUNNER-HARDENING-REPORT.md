# Phase 5.2B-1 — Signing Runner Hardening and Frozen Bridge Deployment

**Phase 5.1:** PASS / FROZEN (historical user-provided real-hardware evidence)
**Phase 5.2A:** PASS (LOCAL MOCK + STATIC; GitHub workflow not dispatched)
**Phase 5.2B-1:** FAIL-CLOSED / HARDENING COMPLETED
**Phase 5.2B-1.1:** PASS — generic production interface is implemented and deployed; remote authorization blockers remain. See [the Phase 5.2B-1.1 report](PHASE5-2B1-1-PRODUCTION-INTERFACE-REPORT.md).

No Phase 5.2B-2 operation was attempted.

## Frozen Bridge installation

The frozen cryptographic core baseline is `6eb2513262d89c377c9ad6d48d41da92a6cd5644`. This follow-on changes only the outer CLI, APK input policy, PIN-source adapter, packaging launcher, and tests. PKCS#11 backend, adaptive discovery, `CKA_ALWAYS_AUTHENTICATE` / `CKU_CONTEXT_SPECIFIC` handling, JCA SPI, ECDSA conversion, and apksig configuration remain unchanged. The installed package was built from an uncommitted working tree based on that baseline.

Build environment: OpenJDK `21.0.12.1+1-1~deb13u1`, Maven `3.9.9`, XiPKI wrapper `1.0.9`, apksig `0.9`; `mvn --batch-mode --file tools/android-signing-bridge/pom.xml clean package` passed 34 tests.

```text
/opt/rustdesk-signing-bridge/                 root:root 0755
  bin/rustdesk-sign                            root:root 0755
  lib/rustdesk-android-signing-bridge.jar      root:root 0644
  lib/ipkcs11wrapper-1.0.9.jar                 root:root 0644
  lib/apksig-0.9.jar                            root:root 0644
  VERSION                                       root:root 0644
  MANIFEST.sha256                               root:root 0644
/usr/local/bin/rustdesk-sign                   root-owned symlink into /opt
```

Installed identity:

```text
BRIDGE_VERSION=0.1.0-SNAPSHOT
INTERFACE_REVISION=phase5.2b-1.1
SOURCE_BASELINE_COMMIT=6eb2513262d89c377c9ad6d48d41da92a6cd5644
SOURCE_TREE=UNCOMMITTED_WORKTREE_BUILD
BRIDGE ARTIFACT SHA256: 6d8c42b0700544ad082257de0044698ec3d097519acdf029adddd2452f6a2710
LAUNCHER SHA256: 93c5f849328b9ac4029951906529b881d77e37ae42e2ee591cff0115c027b221
MANIFEST FILE SHA256: 0dfa1793c62d8141ab797c902d8e0ad541293717b3e292334d1d4665ba2620c2
VERSION SHA256: 38d32f09783597c7cabdbab03ab3564af2dfc80ce36f018d4e1233ec05ae077f
```

The manifest additionally covers the XiPKI and apksig runtime jars. `sha256sum --check` and `/usr/local/bin/rustdesk-sign --verify-install` passed after deployment. Deployment tests verified that `github-runner` cannot modify the installation, launcher, or stable link.

## Generic production CLI

The installed production syntax is:

```text
/usr/local/bin/rustdesk-sign --input <input.apk> --output <new-output.apk> [--pin-source console|env]
```

The PIN source defaults to `console`; environment access requires explicit `--pin-source env`. The input policy rejects missing/non-regular inputs, symlink paths, output/input equality, an existing output, malformed APKs, an unexpected package, unsupported RustDesk ABI, and APKs without exactly one supported `librustdesk.so` ABI. Supported ABIs are `arm64-v8a`, `armeabi-v7a`, and `x86_64`. It records the input SHA-256 before metadata policy validation, signs to a private same-directory staging file, checks the input SHA-256 again, and publishes the output without replacing an existing path.

The APK itself establishes package and ABI. The trusted reusable workflow additionally gates artifact provenance and the Standard variant from the same-run build manifest and checksum chain. The generic local CLI does not claim that an APK alone proves its build provenance or Standard variant.

The Phase 5.1 fixed input digest was removed from the production signer. Its historical digest remains in a regression test and historical evidence only.

## PIN handling

`InteractivePinSource` uses `Console.readPassword()`. `EnvironmentPinSource` reads `YUBIKEY_PIV_PIN` only when explicitly selected and fails closed when the variable is missing or empty. It does not log the value or its length and never puts the PIN in argv, a file, a GitHub output, or an artifact.

`System.getenv` returns a Java `String` that cannot be deterministically zeroized. This limitation is documented; the String is not stored in a static, singleton, provider-global, or cache field. The Bridge copies it into mutable `char[]` buffers and clears the Bridge-owned source and operation buffers. Success and exception cleanup were tested using dummy values only.

The runner is trusted computing base. Because `github-runner` is authorized to use PC/SC, a compromised runner workflow could bypass the root-owned Bridge and call OpenSC/PKCS#11 directly. Environment approval protects repository/workflow authorization; it does not defend against a fully compromised signing runner.

## PC/SC and GitHub authorization

The persistent `/etc/systemd/system/pcscd.socket.d/override.conf` sets `SocketUser=root`, `SocketGroup=rustdesk-yubikey`, `SocketMode=0660`. The active socket was verified as `root:rustdesk-yubikey` mode `0660`; the runner has the dedicated group. Deployment tests confirmed `github-runner` can enumerate the reader and `nobody` is denied socket access. OpenSC is `0.26.1-2`; pcsc-lite is `2.3.3-1`. System `/etc/opensc/opensc.conf` was not changed.

Earlier metadata checks confirmed Environment `android-production-signing`, secret name `YUBIKEY_PIV_PIN`, branch policy `main`, required reviewer `billradar`, and self-review prevention. The value was never read. `billradar` is the only collaborator, so self-approval is blocked. `main` branch protection is not configured; no repository protection settings were changed.

## Workflow state

`.github/workflows/sign-android.yml` uses the installed CLI syntax and maps the Environment Secret only at the signing step. The step has an unconditional `if: false` guard for this phase. No real secret injection, hardware signing, or Actions dispatch occurred. The workflow continues to gate repository, ref, caller workflow, same-run provenance, package, architecture, and Standard variant; stock direct SunPKCS11/apksigner signing is absent from the production workflow.

The separate Phase 5.2A mock workflow remains workflow-dispatch-only with read-only permissions and no production Environment or secret. It was not dispatched. Actionlint passed over all workflow YAML.

## Validation summary

```text
FROZEN BRIDGE DEPLOYED: PASS
BRIDGE ROOT-OWNED: PASS
RUNNER CANNOT MODIFY BRIDGE: PASS
INSTALLED HASH VERIFICATION: PASS
NO-PIN SELF-TEST: PASS
GENERIC INSTALLED CLI: PASS (two Standard APK inputs; mock only)
PHASE5.1 FIXED HASH REMOVED FROM PRODUCTION PATH: PASS
PCSC AUTHORIZED RUNNER: PASS
PCSC UNAUTHORIZED USER: DENIED
ENVIRONMENT AUTHORIZATION: BLOCKED BY SINGLE-COLLABORATOR SELF-REVIEW
MAIN BRANCH PROTECTION: NOT CONFIGURED
PRODUCTION WORKFLOW SIGNER: /usr/local/bin/rustdesk-sign (hard-disabled)
STOCK SUNPKCS11 PRODUCTION SIGNING: DISABLED
PIN USED THIS ROUND: NO
PRIVATE KEY OPERATION: NO
APK PRODUCTION SIGNING THIS ROUND: NO
YUBIKEY MODIFIED: NO
RELEASE: NO
COMMIT: NO
PUSH: NO
```

The real production step must remain disabled until a later explicit phase authorizes a hardware operation and resolves the independent reviewer and branch-protection items. Stop here; do not begin Phase 5.2B-2.
