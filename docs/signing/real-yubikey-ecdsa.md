# Real YubiKey PIV 9C Adaptive ECDSA Validation

Status: **PASS**

Evidence was supplied from the user's real terminal run. The PIN value was not included in the output and was not received or recorded by Codex.

## Results

| Check | Result |
|---|---|
| PIN input count | 1, entered by the user in the real terminal |
| `CKU_USER` login | PASS |
| Private key discovery after login | Exactly one key |
| Private key label / ID / type | `SIGN key` / `02` / EC |
| `CKA_ALWAYS_AUTHENTICATE` | TRUE |
| Mechanism / digest | `CKM_ECDSA` / SHA-256 |
| `C_SignInit` | PASS |
| `CKU_CONTEXT_SPECIFIC` login | PASS |
| `C_Sign` | PASS |
| Raw signature length | 96 bytes |
| Raw ECDSA signature to DER conversion | PASS (terminal output: `RAW?DER: PASS`) |
| Certificate public-key verification | PASS |
| PIN zeroization | PASS |
| Session close / module finalize | PASS |
| Private key exported | NO |
| YubiKey modified | NO |
| APK signed | NO |
| Workflow modified | NO |

**REAL YUBIKEY ADAPTIVE ECDSA VALIDATION: PASS**

The result demonstrates that the tested path can discover the private key after user login, perform context-specific authentication for the `CKA_ALWAYS_AUTHENTICATE` key, sign once, convert the raw ECDSA signature to DER, and verify it against the certificate public key. It does not validate Android APK signing.

## Scope status

- **APK PRODUCTION SIGNING: NOT VALIDATED**
- **LEGACY ANDROID SIGNING IDENTITY: NOT RECOVERED / NOT VALIDATED**
- No APK signing, workflow modification, commit, or push was performed as part of this validation result.
