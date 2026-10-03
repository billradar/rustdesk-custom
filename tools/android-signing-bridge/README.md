# RustDesk Android Signing Bridge Prototype

This Bridge contains the JCA signing provider and adaptive, certificate-pinned XiPKI/OpenSC YubiKey path, plus a generic production CLI. The real production workflow invocation remains hard-disabled pending the next authorized hardware phase.

## Adaptive hardware flow

`SigningPolicy` pins the expected production certificate SHA-256 and the caller-selected signature algorithm (`SHA256withECDSA`). The XiPKI backend discovers token slots dynamically, matches exactly one certificate by fingerprint, and derives its CKA_ID, public-key type, EC order size, and verification key from that certificate. It does not choose a slot, key ID, or curve as a fallback.

The pre-PIN path reads public certificate objects only. After PIN delivery, the unchanged one-shot flow calls `C_Login(CKU_USER)`, searches private objects using the matched certificate CKA_ID, and requires exactly one match. It reads key type, sign capability, and `CKA_ALWAYS_AUTHENTICATE`; unavailable capability metadata fails closed. `C_SignInit(CKM_ECDSA)` is followed by `CKU_CONTEXT_SPECIFIC` only when the target key reports `CKA_ALWAYS_AUTHENTICATE=true`, then one `C_Sign`. The raw ECDSA signature is converted using the certificate-derived component size and verified against that same certificate.

The XiPKI `Session.login(long, char[])` bytecode forwards the mutable `char[]` directly to IAIK's `C_Login(long, long, char[], boolean)` API without making a Java-side `String` or another Java `char[]`. The JCA runtime owns one mutable PIN buffer for one process, supplies disposable copies for operation logins, and clears each copy and the owner buffer. Native-wrapper internal memory behavior is outside the Java bytecode and is not claimed as verified.

## Production CLI and PIN boundary

- Installed signing form: `/usr/local/bin/rustdesk-sign --input <input.apk> --output <new-output.apk> [--pin-source console|env]`.
- PIN source defaults to `console`, which uses `Console.readPassword()`. `--pin-source env` is explicit and reads `YUBIKEY_PIV_PIN`; there is no implicit fallback. The Environment variable's Java `String` cannot be reliably zeroized. Bridge-owned mutable `char[]` buffers are cleared.
- Input must be a parseable APK for `com.carriez.flutter_hbb` with exactly one supported RustDesk ABI (`arm64-v8a`, `armeabi-v7a`, or `x86_64`). Symlink paths and output overwrite are rejected. The CLI hashes the input before signing and checks it again before publishing output. The trusted workflow separately gates same-run provenance and the Standard build variant.
- Mock-only form: `/usr/local/bin/rustdesk-sign --dry-run --input <input.apk> --output <mock-output.apk> --pin-source env`. It copies an approved test APK and reports that the output is **not signed**. It does not initialize PKCS#11.
- Production signing workflow contains the installed CLI command and scopes the Environment Secret to that step. Signing is disabled by default; the one-shot validation caller passes `validation_enable_signing: false`. The step also requires the exact validation caller workflow, `workflow_dispatch`, and `signing-validation` channel.
- To run unit/regression tests: `mvn --batch-mode clean test`.
- To run no-PIN installed self-test as `github-runner`: `/usr/local/bin/rustdesk-sign --self-test`.

## Current status

Phase 5.1 remains **PASS / FROZEN** based on the historical user-supplied hardware result. The Phase 5.2B-1.1 generic interface passed 34 Maven tests and installed mock validation against the historical 1.4.9 Standard APK and a separate 1.5.0 Standard APK. Those installed runs used a dummy test PIN, made no PKCS#11 calls, and produced mock copies only. No real PIN, private-key operation, APK signing, Release, commit, or push occurred. The `main` ruleset is active with PR, no-force-push, no-deletion, and review-thread-resolution protections. The authorization model is intentionally single-maintainer: the signing Environment is main-only and has no required reviewer. Production signing still depends on the workflow trust gates, dedicated self-hosted runner, protected installed Bridge, PC/SC access policy, YubiKey hardware key, and post-sign certificate verification. The hardware signing step remains disabled. See the [Phase 5.2B-1.2 GitHub authorization report](PHASE5-2B1-2-GITHUB-AUTHORIZATION-REPORT.md), [Phase 5.2B-1.1 report](PHASE5-2B1-1-PRODUCTION-INTERFACE-REPORT.md), and [Phase 5.1 report](PHASE5-1-LOCAL-VALIDATION-REPORT.md).
