# Platform support — Phase 5 accepted

SUPPORTED means **BUILD SUPPORT ONLY**, never runtime validation. Machine-readable authority: `metadata/platform-matrix.json`. Actual cross-platform evidence: [run 36902005326](https://github.com/billradar/rustdesk-custom/actions/runs/36902005326); CI gate: [36940045038](https://github.com/billradar/rustdesk-custom/actions/runs/36940045038).

| Platform | Architecture | Standard | SOS | Package | Signing | Runtime/UI | Notes |
|---|---|---|---|---|---|---|---|
| Windows | x86_64 | SUPPORTED | SUPPORTED | Portable Flutter ZIP | NOT ENABLED | SKIPPED BY USER | Phase 4 retained; Phase 5 regression PASS |
| Windows | ARM64 | PLANNED | PLANNED | Portable Flutter bundle planned | NOT ENABLED | SKIPPED BY USER | Dedicated ARM Flutter/Bridge adapter pending; not built |
| Linux | x86_64 | SUPPORTED | SUPPORTED | deb, rpm | NOT ENABLED | SKIPPED BY USER | Official Ubuntu 18.04 compiler container; native package/config gates PASS |
| Linux | ARM64 | SUPPORTED | SUPPORTED | deb, rpm | NOT ENABLED | SKIPPED BY USER | Native ARM runner; package/config gates PASS |
| macOS | x86_64 | SUPPORTED | SUPPORTED | unsigned DMG | NOT ENABLED | SKIPPED BY USER | Intel runner; packaged bundle/native gates PASS |
| macOS | ARM64 | SUPPORTED | SUPPORTED | unsigned DMG | NOT ENABLED | SKIPPED BY USER | ARM runner; packaged bundle/native gates PASS |
| Android | ARM64, ARMv7, x86_64 | SUPPORTED — BUILD ONLY | UNSUPPORTED | split APK | DEBUG/TEST RECIPE ONLY; production identity NOT VALIDATED | SKIPPED BY USER | Build/package gates PASS; production signing identity deferred to Phase 5.1 |
| iOS | ARM64 | PLANNED | UNSUPPORTED | archive / IPA planned | NOT ENABLED | SKIPPED BY USER | Not attempted; provisioning constraints remain |
| Web | web | BLOCKED | UNSUPPORTED | web bundle planned | N/A | SKIPPED BY USER | Official job disabled in both audited snapshots |

Android SOS, iOS SOS and Web SOS: **NOT IMPLEMENTED / NOT PLANNED**. No AppImage/Flatpak/Arch package promotion is claimed. Stable defaults to all 13 SUPPORTED required targets; future missing/invalid required artifacts block a new Draft. Experimental inclusion does not silently remove failing targets. This promotion is based on Stable 1.4.9/v1; non-Windows full Nightly/v2 builds are NOT TESTED.

Runtime/UI remains SKIPPED BY USER; real remote sessions NOT TESTED. Code signing NOT ENABLED. Android APK build success is not production signer/certificate/upgrade-identity validation. Phase 5.1 has not started. Frozen patch sets, historical Releases, existing Draft and both old repositories are unchanged.
