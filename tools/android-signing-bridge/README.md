# RustDesk Android Signing Bridge Prototype

This isolated prototype contains the mock JCA bridge and an adaptive, certificate-pinned XiPKI/OpenSC one-shot YubiKey validation path. It does not modify RustDesk workflows.

## Adaptive hardware flow

`SigningPolicy` pins the expected production certificate SHA-256 and the caller-selected signature algorithm (`SHA256withECDSA`). The XiPKI backend discovers token slots dynamically, matches exactly one certificate by fingerprint, and derives its CKA_ID, public-key type, EC order size, and verification key from that certificate. It does not choose a slot, key ID, or curve as a fallback.

The pre-PIN path reads public certificate objects only. After hidden terminal input, the one-shot flow calls `C_Login(CKU_USER)`, searches private objects using the matched certificate CKA_ID, and requires exactly one match. It reads key type, sign capability, and `CKA_ALWAYS_AUTHENTICATE`; unavailable capability metadata fails closed. `C_SignInit(CKM_ECDSA)` is followed by `CKU_CONTEXT_SPECIFIC` only when the target key reports `CKA_ALWAYS_AUTHENTICATE=true`, then one `C_Sign`. The raw ECDSA signature is converted using the certificate-derived component size and verified against that same certificate.

The XiPKI `Session.login(long, char[])` bytecode forwards the mutable `char[]` directly to IAIK's `C_Login(long, long, char[], boolean)` API without making a Java-side `String` or another Java `char[]`. The bridge zeroes the caller-owned array in `finally`. Native-wrapper internal memory behavior is outside the Java bytecode and is not claimed as verified.

## PIN and hardware boundary

- `--preflight` loads the module, discovers and verifies the certificate, and never queries private-key objects or prompts for a PIN.
- The default run mode requires a real terminal and calls `Console.readPassword()` once, only after the fingerprint match.
- PIN is not passed in an argument, environment variable, file, or report.
- There is no retry, fallback key, object mutation, APK signing, or workflow integration in this validation utility.
- To run mock tests: `mvn clean test`.
- To run the read-only hardware preflight: `./run-real-yubikey-once --preflight` as a user who can invoke `sudo -u github-runner`.
- The default one-shot runner is intentionally reserved for a human at a real terminal after reviewing the current pre-PIN report.

## Current status

Mock tests pass. The latest real preflight matched the production certificate and derived CKA_ID `02`, EC, and 48-byte component size. No PIN has been entered by Codex; no login or private-key operation has been performed by the adaptive flow. Real YubiKey ECDSA and APK production signing remain **NOT VALIDATED**.
