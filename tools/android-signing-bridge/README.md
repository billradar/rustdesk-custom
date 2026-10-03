# RustDesk Android Signing Bridge Prototype

This isolated prototype contains the JCA signing bridge and an adaptive, certificate-pinned XiPKI/OpenSC YubiKey path. It does not modify RustDesk workflows.

## Adaptive hardware flow

`SigningPolicy` pins the expected production certificate SHA-256 and the caller-selected signature algorithm (`SHA256withECDSA`). The XiPKI backend discovers token slots dynamically, matches exactly one certificate by fingerprint, and derives its CKA_ID, public-key type, EC order size, and verification key from that certificate. It does not choose a slot, key ID, or curve as a fallback.

The pre-PIN path reads public certificate objects only. After hidden terminal input, the one-shot flow calls `C_Login(CKU_USER)`, searches private objects using the matched certificate CKA_ID, and requires exactly one match. It reads key type, sign capability, and `CKA_ALWAYS_AUTHENTICATE`; unavailable capability metadata fails closed. `C_SignInit(CKM_ECDSA)` is followed by `CKU_CONTEXT_SPECIFIC` only when the target key reports `CKA_ALWAYS_AUTHENTICATE=true`, then one `C_Sign`. The raw ECDSA signature is converted using the certificate-derived component size and verified against that same certificate.

The XiPKI `Session.login(long, char[])` bytecode forwards the mutable `char[]` directly to IAIK's `C_Login(long, long, char[], boolean)` API without making a Java-side `String` or another Java `char[]`. The JCA runtime owns one mutable PIN buffer for one process, supplies disposable copies for operation logins, and clears each copy and the owner buffer. Native-wrapper internal memory behavior is outside the Java bytecode and is not claimed as verified.

## PIN and hardware boundary

- `--preflight` and `--jca-preflight` load the module, discover and verify the certificate, and never query private-key objects or prompt for a PIN.
- `--jca-run` requires a real terminal and calls `Console.readPassword()` once, only after the fingerprint match.
- PIN is not passed in an argument, environment variable, file, or report.
- There is no retry, fallback key, object mutation, release, or workflow integration in this validation utility.
- To run mock tests: `mvn clean test`.
- To run the read-only hardware preflight: `./run-real-yubikey-once --preflight` as a user who can invoke `sudo -u github-runner`.
- Both one-shot runners are reserved for a human at a real terminal after reviewing the pre-PIN report.

## Current status

Mock tests pass. The user supplied real-terminal results for a JCA signature and Run `36902005326` APK hardware signing with independent `apksigner` verification. Under the revised key10.md policy, the same trusted APK validates both layer A (Bridge integration) and layer B (production signing identity); no second signing run was needed. Phase 5.1 is **PASS**, and APK production signing is **LOCALLY VALIDATED** for that APK. Git tag and Android release asset are unavailable; release publishing, GitHub Actions automated hardware signing, and upgrade installation compatibility remain **NOT VALIDATED**. See [the Phase 5.1 report](PHASE5-1-LOCAL-VALIDATION-REPORT.md). The real signing command is not to be rerun for this validation.
