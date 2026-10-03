# Phase 5.1 — Local Android Production Signing Validation

**Result: PASS**
**Date:** 2026-10-03 (Asia/Shanghai)
**Source repository:** `billradar/rustdesk-custom`
**Source run:** [36902005326](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326)
**Source type:** Successful Stable workflow artifact
**Version:** RustDesk 1.4.9 (recorded; version is not a validation requirement)

## Candidate provenance

The selected input is the Standard Android aarch64 APK from successful Stable workflow run `36902005326` (workflow run head SHA `ad65879a7d3588a661910116abd2f6bc57d5f543`). Its build artifact was `rustdesk-stable-1.4.9-6c578292e8ebbbec708b76986ba8c4bc7c509747-standard-android-aarch64`, artifact ID `11186832321` (41,759,340 bytes; not expired at the time checked). The APK within it was `packages/standard-rustdesk-1.4.9-aarch64.apk`, 28,707,936 bytes.

The APK is package `com.carriez.flutter_hbb`, version code `2067`, version name `1.4.9`, with `arm64-v8a` native libraries. The artifact build metadata identifies upstream RustDesk `1.4.9` / commit `6c578292e8ebbbec708b76986ba8c4bc7c509747`, custom source commit `ad65879a7d3588a661910116abd2f6bc57d5f543`, and labels the source as a debug-signed APK / not production signed.

- **Input APK SHA-256:** `596591B25C4910D7E17FBD2EC499DC2592B06256965F6C50A885B538F6E81325`
- **Artifact archive checksums:** all 9 entries in `SHA256SUMS` passed verification.
- **Original signer:** `CN=Android Debug`, RSA 2048; SHA-256 `cc113bdbce8bb6985a6da4e2d65c7eae6e1af3fffc6bf26af58a4348063dcb2f`.
- **Original APK verification:** passed; v1/v2 present, v3/v3.1/v4 absent.

This artifact serves as both A (Bridge integration validation) and B (production signing identity validation). As directed by `key10.md`, these are two evidence classifications from one already completed signing run, not two signing tests. Version, tag, and release status are not prerequisites for the identity-validation objective.

## Real hardware signing evidence

The real-terminal result supplied for run `36902005326` records:

| Check | Result |
|---|---|
| Real YubiKey 9C ECDSA / JCA signature | PASS |
| Production certificate identity | PASS; SHA-256 `559C1EDE0FBE3A01F29BCAC9D0B34BD9691DF3562C83E3019A930506FBC7B6F5` |
| Real apksig APK signing | PASS |
| Expected / actual hardware signature operations | 2 / 2 |
| Schemes | v1 yes; v2 yes; v3, v3.1, v4 no |
| apksigner verification | PASS |
| Final signer count | 1 |
| Final signer SHA-256 | `559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5` |
| Input APK unchanged | PASS |
| Private key exported | NO |
| PIN input count / zeroization | 1 / PASS (entered by user in a real terminal; value not received or recorded here) |
| Session close / module finalize | PASS |

The final APK is present at `/tmp/rustdesk-phase5-1-validation-36902005326/signed-production-test.apk` (28,706,038 bytes; SHA-256 `f95d23bf2289d2064fb898b49bdeb6be7425440ae62d82609eb40604016d01c1`). This turn independently performed only public, read-only `apksigner verify --verbose --print-certs` on that output. It reported verification success, one signer, v1/v2 true and v3/v3.1/v4 false, EC 384-bit key, signer DN `CN=bill-yubikey-sign, OU=Signature, O=BillLab, C=SG`, and the exact production certificate SHA-256 above. The source input still has the recorded input SHA-256.

The two-operation count matches the instrumented apksig mock analysis for this APK profile: v1 uses `SHA256withECDSA`, v2 uses `SHA512withECDSA`; each scheme requires one JCA signature operation. The real-terminal report records two corresponding hardware operations. The mock trace supports expected operation count; the user-provided real run supplies the hardware count and success evidence.

## Phase 5.1 decision

The evidence satisfies the `key10.md` acceptance criteria for a successful trusted artifact, fixed input identity, real YubiKey-backed apksig signing, expected hardware-operation count, signer identity match, independent APK verification, input immutability, private-key non-export, and PIN zeroization. The existing run is accepted for both A and B without repeating any authentication or signature operation.

```text
ANDROID HARDWARE SIGNING BRIDGE: VALIDATED
PRODUCTION SIGNING IDENTITY: VALIDATED
APK PRODUCTION SIGNING: LOCALLY VALIDATED
PHASE 5.1: PASS

GIT TAG: NOT AVAILABLE
ANDROID RELEASE ASSET: NOT AVAILABLE
RELEASE PUBLISHING: NOT VALIDATED
GITHUB ACTIONS AUTOMATED HARDWARE SIGNING: NOT VALIDATED
UPGRADE INSTALLATION COMPATIBILITY: NOT VALIDATED
LEGACY ANDROID SIGNING IDENTITY: NOT RECOVERED / NOT VALIDATED

PIN USED THIS ROUND: NO
PRIVATE KEY OPERATION THIS ROUND: NO
YUBIKEY MODIFIED: NO
WORKFLOW MODIFIED: NO
RELEASE MODIFIED: NO
COMMIT / PUSH: NO
```

No next phase was started. No APK was signed again. Run `36902005326` remains the historical Bridge integration result and is additionally accepted as production signing identity evidence under the revised candidate policy.
