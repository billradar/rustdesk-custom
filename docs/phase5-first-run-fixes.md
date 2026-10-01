# Phase 5 first cross-platform run and fixes

Run: [36889364030](https://github.com/billradar/rustdesk-custom/actions/runs/36889364030), source maintenance commit `152a6096eb525f7f9db37d6cc8a74d356d070709`.
CI push run [36888747440](https://github.com/billradar/rustdesk-custom/actions/runs/36888747440): PASS.

The cross-platform run is FAIL, with aggregate PARTIAL and required Windows gate PASS. No Draft was created. Existing Releases were not modified.

| Targets | Observed result | Failure classification |
|---|---|---|
| Windows x86_64 Standard/SOS | Complete build/artifact/pair validation PASS | None |
| Android ARM64 Standard | Package/checksum/architecture/config/provenance gates and artifact PASS | None; remains experimental pending promotion review |
| Android ARMv7/x86_64 Standard | APK generated; password byte search failed | PLATFORM_API; contiguous-byte search is insufficient for optimized short strings |
| macOS x86_64 Standard/SOS | DMG generated; API byte search failed | PLATFORM_API; native API must decide whether configuration is correct |
| macOS ARM64 Standard/SOS | Native password probe PASS; DMG library comparison failed | PACKAGE; validator searched the wrong embedded library basename |
| Linux x86_64/ARM64 Standard/SOS | Native build and deb/rpm complete; native probe failed | PLATFORM_API; original probe hid the child failure stage, so exact cause remains unresolved |

Parallel execution was observed: Windows Standard 16:17:38–16:46:30 UTC and Android ARM64 16:17:36–16:47:40 UTC overlapped; all 13 targets began within 16:17:36–16:17:45 UTC. `fail-fast: false` preserved other jobs after individual failures.

## Repair scope

- macOS validates `liblibrustdesk.dylib`, the exact basename referenced by the official Xcode project, against the actual Xcode bundle copy. It then checks architecture and password/API via the library inside the mounted DMG. Xcode copy/signing/stripping transformations no longer require equality to the unprocessed Cargo output.
- macOS API configuration is verified through the existing generated native Bridge API, with no UI/server/remote-session launch.
- Android retains package/library byte identity and architecture checks. The actual Rust library compiler invocation additionally emits MIR, checking password, verification method, Relay and API constants in their compiled customization functions. This replaces password substring detection; it does not prove runtime authentication. A failed compiler/config check remains fatal.
- MIR contains client configuration, including the password. It is private runner-temporary data, never a workflow artifact, source manifest, build-info field or log snippet. The public build-info records the validation method only.
- Linux keeps the official Ubuntu 18.04 compile/package recipe but performs the mandatory native configuration probe on the reviewed native Ubuntu runner with explicit runtime dependencies. The gate is executed directly by package validation; a caller cannot assert an unchecked boolean PASS. Minimum Ubuntu 18.04 runtime compatibility is not claimed.
- Probe failures now distinguish library loading, missing Bridge symbol, initialization, password/verification and API stages. Loader diagnostics disclose only missing library basenames, not arbitrary native output or configured values.

This repair has local regression coverage, but **repaired platform Actions results remain PENDING**. Linux's original root cause cannot be claimed fixed until a fresh run passes or yields the new diagnostic. Frozen v1/v2 patches, resolver, Prepared Source and old Releases are unchanged.

Local verification: 65 tests, 64 PASS / 1 SKIPPED. The skipped test requires a real Rust compiler, absent on this local host; Compatibility CI installs the reviewed toolchain and executes that compiler/MIR integration test. Python syntax, shell syntax and tracked known credential checks also pass. No claim of complete repaired platform build validation is made.

Rerun the Stable workflow from current `main`, tag `1.4.9`, with force-rebuild, artifacts-only/dry-run and experimental targets enabled. GitHub's rerun button uses the old commit and cannot test these code changes.

Runtime/UI: SKIPPED BY USER. Real remote session: NOT TESTED. Production code signing: NOT ENABLED. Password Security V2: DEFERRED. Old repositories: ZERO WRITES.
