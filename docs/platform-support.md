# Platform support — Phase 5 checkpoint

SUPPORTED means build-supported, not runtime-validated. Machine-readable authority: `metadata/platform-matrix.json`. No new platform has Actions validation yet.

| Platform | Architecture | Standard | SOS | Package | Signing | Runtime | Notes |
|---|---|---|---|---|---|---|---|
| Windows | x86_64 | SUPPORTED | SUPPORTED | Portable Flutter ZIP | NOT ENABLED | SKIPPED BY USER | Phase 4 evidence; Phase 5 regression pending |
| Windows | ARM64 | PLANNED | PLANNED | Portable Flutter bundle | NOT ENABLED | NOT TESTED | Dedicated official ARM Flutter/Bridge adapter pending |
| Linux | x86_64 | EXPERIMENTAL | EXPERIMENTAL | deb, rpm | NOT ENABLED | NOT TESTED | Exact official Ubuntu 18.04 container recipe; not built yet |
| Linux | ARM64 | EXPERIMENTAL | EXPERIMENTAL | deb, rpm | NOT ENABLED | NOT TESTED | Native ARM runner; not built yet |
| macOS | x86_64 | EXPERIMENTAL | EXPERIMENTAL | unsigned DMG | NOT ENABLED | NOT TESTED | Official Intel runner; not built yet |
| macOS | ARM64 | EXPERIMENTAL | EXPERIMENTAL | unsigned DMG | NOT ENABLED | NOT TESTED | Official ARM runner; not built yet |
| Android | ARM64, ARMv7, x86_64 | EXPERIMENTAL | UNSUPPORTED | split APK | DEBUG/TEST ONLY | NOT TESTED | Not built yet; no production signing credentials |
| iOS | ARM64 | PLANNED | UNSUPPORTED | archive / IPA | NOT ENABLED | NOT TESTED | Not attempted; IPA provisioning constraints must be reported separately |
| Web | web | BLOCKED | UNSUPPORTED | web bundle | N/A | NOT TESTED | Official job `if: false` in both audited snapshots |

Android SOS, iOS SOS and Web SOS: **NOT IMPLEMENTED / NOT PLANNED**.
No AppImage/Flatpak/Arch package promotion is claimed. Required Stable targets remain only existing SUPPORTED entries. Experimental Nightly failures remain recorded, not silently removed.
