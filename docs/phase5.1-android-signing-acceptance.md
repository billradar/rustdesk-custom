# Phase 5.1 — Android existing production signing identity

Phase 5.1: **FAIL / NOT YET ACCEPTED — real Actions validation pending**.

## Baseline and scope

- Repository: `billradar/rustdesk-custom`; branch: `main`.
- Starting HEAD / Phase 5 baseline: `53e6586324db41a6293d125e00825af241085b94` (`53e6586`). They are identical.
- Phase 5: PASS. CI `36940045038`; cross-platform run `36902005326`; draft preflight verification `36940172133`.
- Only Android signing and related orchestration/gates change. The 13 enabled target definitions, desktop support and native recipes remain unchanged.
- Android packaging: three per-ABI split APKs: `arm64-v8a`, `armeabi-v7a`, `x86_64`. Every final APK must match the same legacy certificate and package.
- Android SOS: NOT IMPLEMENTED. Runtime/UI: SKIPPED BY USER. Real Remote Session: NOT TESTED. Phase 6: NOT STARTED.

## Legacy repository audit — PASS

Legacy Repository Writes: ZERO. Read-only source audit at Standard repository `billradar/rustdesk` HEAD `7bf94bf7296c054a34828ea5d8958e18395ab3e6`.

The actual `.github/workflows/flutter-build.yml` uses `r0adkll/sign-android-release@349ebdef58775b1e0d8099458af0816dc79b6407`. Secret schema preserved exactly:

- `ANDROID_SIGNING_KEY`: base64-encoded existing keystore.
- `ANDROID_KEY_STORE_PASSWORD`
- `ANDROID_KEY_PASSWORD`
- `ANDROID_ALIAS`

The Gradle application ID is `com.carriez.flutter_hbb`. The release configuration reads optional `key.properties`; the reviewed build recipe replaces `signingConfigs.release` with `signingConfigs.debug` before Flutter packaging. Phase 5 already consumes this exact reviewed Android recipe via its fingerprint gate. Production signing stays after native compilation and packaging. No new keystore, key pair or certificate has been generated. Secrets were not read/exported from the old repository.

### Third-party Action audit

Inspected `action.yml`, `src/main.ts`, `src/signing.ts` and the **actual executable** `lib/main.js`, `lib/signing.js` at the pinned commit. `action.yml` declares node12; runner compatibility remains subject to the real Actions result. No unnecessary network upload exists in these signing entrypoints. The executable signs one APK in each isolated invocation and runs `apksigner verify`.

The Action writes `signingKey.jks` inside `releaseDirectory`, does not clean it up, and passes password arguments through `@actions/exec`. GitHub masks the four configured Secrets in logs. The new wrapper keeps the same implementation and credentials, creates a runner-temp directory with mode 0700, pre-creates the key file with mode 0600 (preserved by `writeFileSync`), and removes the entire directory with `if: always()` before uploading. Upload paths explicitly exclude the private stage. No Action upgrade or replacement is made.

Executable public source hashes:

- `lib/main.js`: `779a7eb7e2dce7fa62b8f438d7a1e181589d9a44fa61fb628f5292216a631db5`
- `lib/signing.js`: `a412a118f5553df6aa826a3d9e7de7f7620992acc2087c0435f38a259176e926`

## Legacy identity — verified from real APK

Source: existing non-draft, non-prerelease Standard Release `master`, Release ID `350806253`, asset ID `480078839`, `rustdesk-1.4.9-aarch64-signed.apk`.

[Legacy APK](https://github.com/billradar/rustdesk/releases/download/master/rustdesk-1.4.9-aarch64-signed.apk)

- APK SHA-256: `d878e398aac88d284f0a2b872fdeafc6a4bc2f6d2e81c4c7559999feecda289e`
- Package: `com.carriez.flutter_hbb`
- Certificate SHA-256: `a53de75c536ba1431f5e1c0ecaee120a63b5107b563fcdd311efd38297be103c`
- `apksigner verify --verbose --print-certs`: PASS; one signer; v1/v2/v3 verified.
- versionName: `1.4.9`; versionCode: `2067`; ABI: `arm64-v8a`.
- Canonical expected identity is fixed in `metadata/android-signing-identity.json`. Alias, subject and private signing material are not recorded there.

## New signing architecture

Prepared Source Contains Private Key: NO by design. Existing immutable preparation path is unchanged. Source and native build jobs receive no Android signing Secrets. Only Android availability preflight and isolated signing jobs reference them. Resolver, Compatibility, desktop jobs and Aggregate never receive these Secrets. Signing and validation use `contents: read`; no publish step exists.

The signed bundle retains source-manifest identity, upstream repository/ref/exact SHA, patchset/common hash, custom SHA, ABI and workflow run. Its APK, receipt and build-info receive freshly recomputed SHA256SUMS after signing. Independent validation reruns apksigner, manifest extraction, package/certificate/ABI comparisons, native library equality, checksum and provenance gates. Multiple signers, invalid signatures, missing Secrets, bad credentials, identity mismatch or leakage fail closed.

Stable non-dry-run Android requires production signing. `dry_run` and `include_experimental` retain explicit TEST SIGNED semantics. Intermediate artifacts in signing mode are labelled `android-build-input-*`, excluded from production aggregate and Draft selection. Only fully verified signed bundles use the final `rustdesk-*` naming. Draft creation also independently requires signed Android bundles, so a direct caller cannot bypass the Stable Gate. Existing Draft preflight/dedup and DRAFT ONLY policy remain.

Credential scan checks tracked maintenance files, metadata, input bundles, final staging and decompressed APK contents; forbidden key file types, JKS markers, private-key/token markers and exact base64/decoded-keystore/password values are rejected without printing them. Alias is not used as an artifact name, metadata identity or scan substring (a conventional alias can also occur in legitimate public application text). A completed Actions log scan checks visible credential patterns; exact private values stay in the signing job. GitHub redaction limits retrospective log evidence.

## Validation entrypoint

`android-signing-validation.yml`: workflow_dispatch with official stable tag (default `1.4.9`), artifacts only. It also allows a main-branch commit touching this workflow with explicit `[validate-android-signing]` in its message to start an authorized validation without exposing Secrets or requiring browser dispatch. Other pushes do not execute this signing workflow's jobs. Availability preflight precedes compatibility/preparation and all three Android builds. Compatibility uses its CI mode and omits the Windows helper. No Desktop client is rebuilt.

## Acceptance gates — pending actual Actions evidence

| Gate | Current result |
|---|---|
| Legacy audit / schema / no new identity | PASS |
| Legacy signature, package and public identity | PASS |
| Production signing stage | NOT RUN |
| Certificate Match | NOT RUN |
| Package Identity Match | NOT RUN |
| New Signature Verification | NOT RUN |
| New ABI Verification | NOT RUN |
| Signed Checksum | NOT RUN |
| Signed Provenance | NOT RUN |
| Exact signing Credential Leakage Scan | NOT RUN |
| Local regression | PASS — 81 tests, 3 skipped under existing snapshot conditions |
| CI / Real Actions validation | PENDING |

New APK hashes, certificate/package comparisons, Actions Run ID, maintenance SHA, upstream SHA, Patch Set and Prepared Source identity will be recorded from completed verification artifacts. No pending Gate is treated as PASS.

Static Upgrade Identity: NOT YET VALIDATED. Runtime Upgrade: NOT TESTED. This is an identity-validation build of `1.4.9`; a higher versionCode is not presumed. If it remains `2067`, report UPGRADE VERSION SEMANTICS NOT VALIDATED.

Android ARM64 / ARMv7 / x64 Standard Build: SUPPORTED. Production Signing Identity: NOT VERIFIED. Metadata has not been promoted.

Existing Releases: UNCHANGED. Existing Draft: UNCHANGED. Old Repositories: ZERO WRITES.
