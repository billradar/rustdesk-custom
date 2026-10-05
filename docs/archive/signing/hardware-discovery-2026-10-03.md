# XiPKI / OpenSC Read-Only Hardware Discovery Results

Date: 2026-10-03 (Asia/Shanghai)

## Environment and pinned artifacts

- OS: Debian GNU/Linux 13.7 (trixie)
- Architecture: Linux AArch64 (`aarch64`), Raspberry Pi kernel `6.18.54+rpt1~beta1`
- JDK: OpenJDK 21.0.12.1+1-1~deb13u1
- OpenSC: package `0.26.1-2`
- OpenSC module: `/usr/lib/aarch64-linux-gnu/opensc-pkcs11.so`
- OpenSC module SHA-256: `18c430b0614a2a375c7ce8f88132224d54e7d45ca2dcd756fe173d9f8f167e2b`
- XiPKI coordinates: `org.xipki:ipkcs11wrapper:1.0.9`
- XiPKI source: official XiPKI Maven Central release; Maven metadata lists 1.0.9 as release/latest. The prior candidate survey identified source commit `2b086bd8a1d7a1f1091fd7adbabeaeb5f6118d54` but did not record an expected artifact version.
- XiPKI JAR SHA-256: `b7deea6cde2f5f540f0bf612402d9db5adab13f4751f01f49d643c740b313f62`
- XiPKI source JAR SHA-256: `2ef73f978bc2cd456d83ae59a148a53a692514603c0cf28af5b6c1ff78025ee0`
- Bundled XiPKI native library: `natives/unix/linux-aarch64/release/libpkcs11wrapper.so`
- Native architecture: ELF 64-bit LSB shared object, ARM AArch64
- Native library SHA-256: `ec55efcef1073a0387b4a6045bd14e9f2614dcc2e549b82c05134334e313e3b1`
- License: XiPKI POM identifies the IAIK PKCS#11 Wrapper License for the included IAIK component and Apache License 2.0 for the remaining code.
- `mvn dependency:tree -Dverbose`: PASS; XiPKI is the sole compile/runtime application dependency, JUnit is test scope.

The 1.0.9 source JAR was compared with the previously inspected checkout. `PKCS11Module.java` and `Session.java` contain later source changes, while the relevant 1.0.9 API exposes the same initialization, slot/token discovery, read-only session, certificate attribute, and cleanup methods. The bundled 1.0.9 AArch64 native library SHA-256 matches the native library in the inspected checkout. The release was pinned; no SNAPSHOT or floating version was used.

## Execution

- Run as: `github-runner`
- Invocation: explicit Java invocation of `XiPkiPkcs11Discovery`, with the temporary OpenSC `pkcs11-spy` module delegating to `/usr/lib/aarch64-linux-gnu/opensc-pkcs11.so`.
- The process had `OPENSC_CONF` unset. No system OpenSC configuration was changed.
- Startup displayed `READ-ONLY YUBIKEY DISCOVERY`, `NO PIN`, `NO LOGIN`, `NO PRIVATE KEY OPERATION`, and `NO SIGNING` before loading the module.
- `PKCS11_TEMP_DIR` and `PKCS11SPY_OUTPUT` pointed inside a temporary directory. The temporary directory, trace, copied classes/JAR, and extracted JNI library were removed after the run.
- `opensc-tool -l` as `github-runner` found a present `Yubico YubiKey OTP+FIDO+CCID` reader/token.

## Discovery result

| Check | Result |
|---|---|
| Module load and initialization | PASS |
| Present slot discovery | PASS |
| `C_GetSlotInfo` wrapper call | NOT RUN by this utility; `opensc-tool -l` separately identified the Yubico reader |
| Target token | FOUND; exactly one matching token |
| Slot ID | `0` (discovered at runtime; not hard-coded) |
| Token label | `bill-yubikey-auth` |
| Token manufacturer | `piv_II` |
| Token model | `PKCS#15 emulated` |
| Token serial (local report only) | `b522f1bd9c14b23d` |
| Token flags | `0x40d` |
| Session | READ ONLY; wrapper logged `C_OpenSession` flags `0x00000004` (`CKF_SERIAL_SESSION`, without `CKF_RW_SESSION`) |
| Certificate search | `CKO_CERTIFICATE` only, with `CKA_ID = 02`; exactly one result |
| Certificate label | `Certificate for Digital Signature` |
| Certificate subject | `CN=bill-yubikey-sign, OU=Signature, O=BillLab, C=SG` |
| Certificate issuer | `CN=BillLab Root CA, OU=Certificate Authority, O=BillLab, C=SG` |
| Certificate serial | `7a0f4a92bfbcb97f513b99df4ba00de81d418c80` |
| Validity | 2026-10-02T03:40:28Z to 2035-07-07T03:40:28Z |
| Certificate public key | EC, 384 bits |
| Certificate SHA-256 | `559C1EDE0FBE3A01F29BCAC9D0B34BD9691DF3562C83E3019A930506FBC7B6F5` |
| Expected certificate SHA-256 | `559C1EDE0FBE3A01F29BCAC9D0B34BD9691DF3562C83E3019A930506FBC7B6F5` |
| Fingerprint comparison | PASS; Java `MessageDigest.isEqual` |
| Read-only hardware discovery | PASS |

OpenSC returned an unset token UTC-time field; XiPKI emitted a warning and substituted local time for its token-time metadata. Certificate validity values above came from the X.509 certificate itself.

## Prohibited operations and evidence

- PIN requested: NO
- PIN read from environment: NO
- PIN used: NO
- Private-key object searched/read/used: NO
- Token/PIV object modified: NO
- APK signed: NO
- Workflow modified: NO
- Commit/push: NO

Source-path audit of `XiPkiPkcs11Discovery` and the invoked XiPKI wrapper methods found only module initialization/info, slot list, token info, `C_OpenSession`, certificate-only `C_FindObjects*`, public certificate `C_GetAttributeValue`, `C_CloseSession`, and `C_Finalize`. The discovery code does not call login, signing, private-key search, or object mutation APIs. Runtime wrapper output recorded module initialization and the read-only session flags; the Java process exited 0 after cleanup.

The OpenSC spy trace file was created, but the post-run counter parser did not recognize the installed spy's record format: it returned zero for known discovery calls as well as prohibited calls. Those parsed zeros are invalid and are not claimed as runtime counts. Accordingly, the prohibited function counters are UNKNOWN at the low-level trace layer; `NOT CALLED` is supported by the audited discovery call path, not by a parsed counter. This evidence limit is retained rather than claiming unverified counts.

| PKCS#11 operation | Result |
|---|---|
| `C_Login` | NOT CALLED by audited path; runtime counter UNKNOWN |
| `C_SignInit` | NOT CALLED by audited path; runtime counter UNKNOWN |
| `C_Sign` | NOT CALLED by audited path; runtime counter UNKNOWN |
| `C_SignUpdate` | NOT CALLED by audited path; runtime counter UNKNOWN |
| `C_SignFinal` | NOT CALLED by audited path; runtime counter UNKNOWN |
| `C_CreateObject` | NOT CALLED by audited path; runtime counter UNKNOWN |
| `C_DestroyObject` | NOT CALLED by audited path; runtime counter UNKNOWN |
| `C_SetAttributeValue` | NOT CALLED by audited path; runtime counter UNKNOWN |

## Cleanup and phase status

- Session close: PASS (called from `finally`; no close error)
- Module finalize: PASS (called from `finally`; no finalize error)
- Temporary-file cleanup: PASS
- Default `mvn clean test`: PASS, 17 tests, 0 failures/errors/skips; no hardware access
- Production signing backend integration: NOT DONE
- Real private-key operation: NOT DONE
- APK production signing: NOT VALIDATED
- Legacy Android signing identity: NOT RECOVERED / NOT VALIDATED

The Phase 5.1 read-only hardware discovery STOP condition was reached. No context-specific login, signing, APK signing, workflow change, commit, or push was performed.
