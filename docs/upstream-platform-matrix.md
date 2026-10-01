# Official exact-SHA platform matrix audit

Stable: 1.4.9 / 6c578292e8ebbbec708b76986ba8c4bc7c509747. Development: master / 1.5.0 / fada664df7a294d1d1a9ca3e7cd3637069122f17.

Both snapshots reviewed from official Git history, including CI/Tag/Nightly/Bridge and referenced build.py, helper, Android dependencies/NDK scripts. Toolchain profiles are machine-readable in metadata/platform-adapter-profiles.json. These are official definitions, not proof our customization builds on those platforms.

| SHA | Platform | Arch | Runner | Rust | Flutter | vcpkg | Package / official status |
|---|---|---|---|---|---|---|---|
| 6c578292 | linux | x86_64 | ubuntu-22.04 | 1.75 | 3.24.5 | 120deac30621 | deb/rpm; AppImage/Flatpak downstream helpers |
| 6c578292 | linux | aarch64 | ubuntu-22.04-arm | 1.75 | 3.24.5 | 120deac30621 | deb/rpm; AppImage/Flatpak downstream helpers |
| 6c578292 | macos | x86_64 | macos-15-intel | 1.81 | 3.24.5 | 120deac30621 | unsigned DMG or signed/notarized DMG |
| 6c578292 | macos | aarch64 | macos-14 | 1.81 | 3.24.5 | 120deac30621 | unsigned DMG or signed/notarized DMG |
| 6c578292 | android | aarch64 | ubuntu-24.04 | 1.75 | 3.24.5 | 120deac30621 | per-ABI APK (official debug signing then optional production signer) |
| 6c578292 | android | armv7 | ubuntu-24.04 | 1.75 | 3.24.5 | 120deac30621 | per-ABI APK (official debug signing then optional production signer) |
| 6c578292 | android | x86_64 | ubuntu-24.04 | 1.75 | 3.24.5 | 120deac30621 | per-ABI APK (official debug signing then optional production signer) |
| 6c578292 | ios | aarch64 | macos-latest | 1.75 | 3.24.5 | 120deac30621 | static lib + no-codesign archive; IPA requires provisioning |
| 6c578292 | windows | x86_64 | windows-2022 | 1.75 | 3.24.5 | 120deac30621 | portable EXE/bundle; helper required |
| 6c578292 | windows | aarch64 | windows-11-arm | 1.75 | 3.24.5 | 120deac30621 | portable EXE/bundle; helper required |
| 6c578292 | web | web | ubuntu-22.04 | 1.75 | 3.24.5 | 120deac30621 | PREVIEW recipe explicitly disabled: if false |
| fada664d | linux | x86_64 | ubuntu-22.04 | 1.75 | 3.24.5 | 9e593bb18ea6 | deb/rpm; AppImage/Flatpak downstream helpers |
| fada664d | linux | aarch64 | ubuntu-22.04-arm | 1.75 | 3.24.5 | 9e593bb18ea6 | deb/rpm; AppImage/Flatpak downstream helpers |
| fada664d | macos | x86_64 | macos-15-intel | 1.81 | 3.24.5 | 9e593bb18ea6 | unsigned DMG or signed/notarized DMG |
| fada664d | macos | aarch64 | macos-14 | 1.81 | 3.24.5 | 9e593bb18ea6 | unsigned DMG or signed/notarized DMG |
| fada664d | android | aarch64 | ubuntu-24.04 | 1.75 | 3.24.5 | 9e593bb18ea6 | per-ABI APK (official debug signing then optional production signer) |
| fada664d | android | armv7 | ubuntu-24.04 | 1.75 | 3.24.5 | 9e593bb18ea6 | per-ABI APK (official debug signing then optional production signer) |
| fada664d | android | x86_64 | ubuntu-24.04 | 1.75 | 3.24.5 | 9e593bb18ea6 | per-ABI APK (official debug signing then optional production signer) |
| fada664d | ios | aarch64 | macos-latest | 1.75 | 3.24.5 | 9e593bb18ea6 | static lib + no-codesign archive; IPA requires provisioning |
| fada664d | windows | x86_64 | windows-2022 | 1.75 | 3.24.5 | 9e593bb18ea6 | portable EXE/bundle; helper required |
| fada664d | windows | aarch64 | windows-11-arm | 1.75 | 3.24.5 | 9e593bb18ea6 | portable EXE/bundle; helper required |
| fada664d | web | web | ubuntu-22.04 | 1.75 | 3.24.5 | 9e593bb18ea6 | PREVIEW recipe explicitly disabled: if false |

## Commands and dependency identity

| Platform | Official command/path | Bridge/helper | Signing | Official artifact identity |
|---|---|---|---|---|
| Windows | build.py --portable --flutter --skip-portable-pack --hwcodec, x64 --vram | bridge-artifact on x64; dedicated ARM bridge/Flutter versions on ARM64; WindowInjection per arch | optional service, not enabled here | version + arch .exe |
| Linux | cargo build --locked --lib --features hwcodec,flutter,unix-file-copy-paste --release; build.py --flutter --skip-cargo; rpmbuild res/rpm-flutter{,-suse}.spec | generated default bridge; native x64/ARM64 Ubuntu18.04 container; ARM flutter-elinux | none | rustdesk-VERSION-ARCH.deb / .rpm |
| macOS | build.py --flutter --hwcodec --unix-file-copy-paste; ARM --screencapturekit; create-dmg | generated default bridge; macOS deployment-target delta | unsigned branch exists, developer cert/notarization separate | rustdesk-VERSION-ARCH.dmg |
| Android | build_android_deps.sh; cargo-ndk/ndk_{arm64,arm,x64}.sh; flutter build apk --release --target-platform ... --split-per-abi | default generated bridge; NDK r28c; cargo-ndk 3.1.2; JDK17 | upstream package initially debug signed; production signer optional | rustdesk-VERSION-ARCH.apk |
| iOS | cargo build --locked --features flutter,hwcodec --release --target aarch64-apple-ios --lib; flutter build ipa --release --no-codesign | generated headers; macOS runner; arm64-ios vcpkg | no production provisioning available | liblibrustdesk.a / archive, no guaranteed IPA |
| Web | yarn build in flutter/web/js; preview dependency archive; flutter build web --release | TypeScript/protobuf/web dependencies, not native helper | none | preview tar.gz, job explicitly disabled |

## Stable vs development differences

Stable vcpkg: 120deac3062162151622ca4860575a33844ba10b. Development: 9e593bb18ea69cc5095e012465dcd675a822ed0d. Development Linux ARM64 explicitly adds CMake 4.3.0. Windows ARM Flutter changes from 3.44.0 to 3.44.9; ARM Bridge profile differs. These cannot be silently replaced with x64/default Bridge artifacts. Development additionally requests a source SBOM.

Rust default 1.75, macOS 1.81, default Flutter 3.24.5, LLVM15.0.6. macOS Intel runner macos-15-intel, ARM runner macos-14; Linux native ARM runner ubuntu-22.04-arm; Android ubuntu-24.04. Runner availability remains Actions evidence, not assumed support.

## Entrypoints

CI is PR/push to master/manual; official Tag is version tag push/manual; official Nightly publishes its own nightly release. Our resolver-based entrypoints remain unchanged, Stable Draft only and Nightly Actions artifacts only. Exact official build/bridge definitions gate adapters; unreviewed changes fail closed.

## Source links

- https://github.com/rustdesk/rustdesk/blob/6c578292e8ebbbec708b76986ba8c4bc7c509747/.github/workflows/flutter-build.yml
- https://github.com/rustdesk/rustdesk/blob/6c578292e8ebbbec708b76986ba8c4bc7c509747/.github/workflows/flutter-tag.yml
- https://github.com/rustdesk/rustdesk/blob/6c578292e8ebbbec708b76986ba8c4bc7c509747/.github/workflows/flutter-nightly.yml
- https://github.com/rustdesk/rustdesk/blob/6c578292e8ebbbec708b76986ba8c4bc7c509747/.github/workflows/flutter-ci.yml
- https://github.com/rustdesk/rustdesk/blob/6c578292e8ebbbec708b76986ba8c4bc7c509747/.github/workflows/bridge.yml
- https://github.com/rustdesk/rustdesk/blob/fada664df7a294d1d1a9ca3e7cd3637069122f17/.github/workflows/flutter-build.yml
- https://github.com/rustdesk/rustdesk/blob/fada664df7a294d1d1a9ca3e7cd3637069122f17/.github/workflows/flutter-tag.yml
- https://github.com/rustdesk/rustdesk/blob/fada664df7a294d1d1a9ca3e7cd3637069122f17/.github/workflows/flutter-nightly.yml
- https://github.com/rustdesk/rustdesk/blob/fada664df7a294d1d1a9ca3e7cd3637069122f17/.github/workflows/flutter-ci.yml
- https://github.com/rustdesk/rustdesk/blob/fada664df7a294d1d1a9ca3e7cd3637069122f17/.github/workflows/bridge.yml
