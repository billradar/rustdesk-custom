# BRF Phase 2 dependency and cache audit

## Verified baseline

Audited BRF PR #278 at `e41fada0f4243183ba67ff8689d453685d1d0c96` and the exact v4 fixture source `51f94394ce61e1f3d26229565c326b2862cbdd1f`. Ordinary CI and the PR matrix passed. The PR, Nightly, and Stable aggregate reports each recorded PASS, 13 targets, and `release_eligible=false`.

| Run | Result | Aggregate artifact |
| --- | --- | --- |
| [PR validation](https://github.com/billradar/rustdesk-custom/actions/runs/46099027815/attempts/1) | Pass on attempt 1 | 15248462923 |
| [Nightly formal dry-run](https://github.com/billradar/rustdesk-custom/actions/runs/46108695425/attempts/1) | Pass on attempt 1 | 15252060333 |
| [Stable formal dry-run](https://github.com/billradar/rustdesk-custom/actions/runs/46108693080/attempts/3) | Pass on attempt 3 after targeted Mac Intel SOS rerun | 15254656255 |

The Stable rerun job `140899620435` and aggregate job `140913395466` passed. Signing and draft creation were skipped. The original runner communication loss and subsequent cancellation remain infrastructure observations. The three PR Android logs and six channel Android logs had no Maven 429 or BRF recovery event. Phase 1 canary acceptance uses offline recovery contracts and the passing hosted normal-build and aggregate checks. Successful hosted recovery after the revised 240–288 second wait remains unobserved and will be tracked during rollout. This audit adds no cache configuration.

## Dependency inventory

| Area | Observed at the pinned source and workflow | Cache boundary |
| --- | --- | --- |
| Gradle and Maven | Android uses Java 17 and Gradle 8.11.1 from the wrapper. `settings.gradle` includes Flutter's Gradle build using `flutter.sdk` and lists Google, Maven Central and the plugin portal. The tracked Android project has no Gradle dependency lock or verification metadata, and the wrapper properties lack a distribution checksum. The observed 429 is in the included build's `:gradle:compileClasspath`. | First candidate. Audit the included Flutter project's dependency graph as well as the Android root project. Require reviewed integrity inputs before making a warm cache authoritative or enabling offline mode. Keep live resolution in the initial experiment. |
| Cargo | The source tracks a root `Cargo.lock` and separate package locks. The Mac Intel canary runs locked, target-specific Cargo prefetch before the audited build and explicitly uses the Git CLI. | Candidate after Maven. Use a dedicated Cargo home during validation and inventory registry and Git download directories. Require the exact target, lockfile digests, source and recipe identity and Cargo version. Exclude Cargo credentials, installed executables, checkout overrides, and `target/`. |
| Flutter and Pub | The pinned flutter-action defaults SDK caching to false. An empty Pub cache input follows the SDK cache toggle. Its Pub cache key appends a workspace-wide `hashFiles('**/pubspec.lock')`. `flutter/pubspec.lock` is tracked in the upstream tree and workflows acquire prepared source separately. The Flutter SDK is patched for Android, and formal Windows installs a custom engine. | Treat Pub, SDK and engine separately. Bind Pub to the exact prepared lockfile and SDK identity. Any SDK cache must contain the verified pristine SDK before job-local patching. Never save the mutated SDK as a reusable toolchain. |
| Android SDK and NDK | The SDK preflight has staged installation and per-component validation. The pinned setup-ndk action's `local-cache` input defaults to false and its runner tool cache is separate. | Measure existing valid SDK reuse and install counts before introducing repository cache. Future reuse needs an exact component/version inventory and integrity validation, with downloads staged outside the destination. |
| vcpkg | Current build workers pass `doNotCache: true`. The pinned run-vcpkg action specifies this input controls its executable and data cache. Native binary caching has separate `VCPKG_BINARY_SOURCES` controls. Archived upstream recipe profiles contain an x-gha setting. No assignment was found in the checked-in build workflows or scripts. | Preserve `doNotCache: true`. Confirm effective runner environment and vcpkg diagnostics before claiming binary caching is disabled or available. Review ABI, triplet, compiler, tool revision, manifest, feature and overlay inputs before any binary-cache change. |
| Flutter engine and Bridge | Windows x64 fetches a custom engine from the moving upstream release label and computes a digest after retrieval. The Bridge script verifies source and Flutter version, uses versioned `cargo install --locked`, then generates outputs that travel through source-bound receipts. | Defer the custom engine until an approved immutable input digest is available. A later Bridge experiment may measure locked tool downloads. Keep generated bindings and transformed source on the existing verified artifact path. |

The repository Actions cache API returned zero entries at audit time. That inventory does not include tools preinstalled on hosted runners, vcpkg local stores, or files reused within a job.

## Android timing baseline

These nine Standard APK results use the same custom SHA, upstream SHA and online recipe. For Stable, attempt 1 supplied the successful Android jobs reused by attempt 3. Build-step time is the hosted timestamp interval for `Shared Stable build core with fictional fixture only`, including native work. Gradle time is Flutter's `assembleRelease` duration; it includes Gradle setup, dependency resolution and build work. It neither isolates Maven downloads nor proves a cold dependency store.

| Entry | ABI | Job log | Shared build step (s) | Gradle assembleRelease (s) |
| --- | --- | --- | ---: | ---: |
| PR | aarch64 | [140839064412](https://github.com/billradar/rustdesk-custom/actions/runs/46099027815/job/140839064412) | 1359 | 317.8 |
| PR | x86_64 | [140839064448](https://github.com/billradar/rustdesk-custom/actions/runs/46099027815/job/140839064448) | 1338 | 338.6 |
| PR | armv7 | [140839064476](https://github.com/billradar/rustdesk-custom/actions/runs/46099027815/job/140839064476) | 1271 | 293.5 |
| Stable | aarch64 | [140869002632](https://github.com/billradar/rustdesk-custom/actions/runs/46108693080/job/140869002632) | 1251 | 291.0 |
| Stable | x86_64 | [140869002650](https://github.com/billradar/rustdesk-custom/actions/runs/46108693080/job/140869002650) | 1211 | 282.2 |
| Stable | armv7 | [140869002665](https://github.com/billradar/rustdesk-custom/actions/runs/46108693080/job/140869002665) | 1258 | 290.3 |
| Nightly | aarch64 | [140869070920](https://github.com/billradar/rustdesk-custom/actions/runs/46108695425/job/140869070920) | 1240 | 282.1 |
| Nightly | x86_64 | [140869070958](https://github.com/billradar/rustdesk-custom/actions/runs/46108695425/job/140869070958) | 1221 | 307.9 |
| Nightly | armv7 | [140869070959](https://github.com/billradar/rustdesk-custom/actions/runs/46108695425/job/140869070959) | 1264 | 292.3 |

Median Gradle time was 292.3 s (282.1–338.6 s). Median shared build step time was 1258 s (1211–1359 s). No 429 or BRF retry was present in these logs. Standard verbosity did not expose reliable transfer counts, byte totals or cache hits. Those fields are unmeasured for this baseline.

For the first controlled comparison, start with x86_64 Standard, the observed Nightly failure target. Keep the exact source, Java and Flutter identities and the existing packaging command fixed. Use an empty job-local Gradle user home for the cold sample. In the paired sample, seed only Gradle's supported dependency-cache files from the isolated cold run and build in a clean checkout. Retain normal online resolution. Compare the included-build classpath timing and observable transfers as separate measurements from the total Gradle and package times. Collect only numeric or enumerated metrics; leave missing counters null. Verify both resulting package reports using the existing fixture checks before interpreting any speedup.

## Proposed first experiment

1. On the credential-free Android fixture, compare cold and warm dependency preparation with the existing recipe and HTTPS repositories. Instrument the included Flutter Gradle build that failed, and prove the experiment resolves its actual classpath before judging coverage. Record whether prefetch duplicates transfers that the regular APK step would have done.
2. If integrity and path review pass, trial dependency-only Gradle reuse using Gradle's supported dependency-cache layout. Seed in an isolated Gradle user home from a reviewed exact-source run. Include OS, runner and Java identity, target ABI, Gradle distribution, Flutter SDK and patch identity, upstream SHA, patch profile and digest of the effective Gradle dependency inputs. Start with exact keys in the fixture trust domain. Exclude Gradle user configuration and scripts, locks, daemon state, transformed or compiled output, signing configuration and production secrets. Keep readers and writers isolated from an actively written cache.
3. Record dependency preparation and package times, dependency transfer counts and bytes where available, hit or miss, 429s, and evidence completeness. Compare runs on the same recipe and target. Run offline fault tests for corrupt or missing cache entries, mismatched keys, and unsupported graphs. A rejected entry should follow the existing verified online path or leave a hard failure. Package and aggregate verification still run after any cache hit.
4. Keep all production restores outside this trial. Before expanding scope, verify the effective GitHub cache ref permissions and version behavior using trusted and PR fixtures. Use no broad restore keys, and set deletion, retention and size limits based on measured entries.

## Follow-up items

- Track genuine rate-limit recovery separately from Phase 2 timing. Continue collecting passive evidence under the revised policy.
- Record hosted runner communication loss under Phase 3 workflow recovery. Start with formal dry-runs, GitHub check evidence, a missing report and a live attempt check. Review the downstream graph before allowing one automated target rerun. Treat log-storage BlobNotFound as evidence availability and keep cancellation terminal for automation.
- Leave Maven mirrors, Gradle offline mode, production cache restoration, vcpkg binary reuse and cache-backed Bridge output out of the first experiment.

## Sources inspected

- Current branch workflows `build-validation.yml`, `build-validation-linux.yml`, `build-platform.yml`, `build-stable-windows.yml`, `prepare-source.yml`; Android SDK preflight, platform launcher, and Bridge generator.
- [Exact v4 upstream source](https://github.com/rustdesk/rustdesk/tree/51f94394ce61e1f3d26229565c326b2862cbdd1f)
- [Pinned Flutter action](https://github.com/subosito/flutter-action/blob/1a449444c387b1966244ae4d4f8c696479add0b2/action.yaml)
- [Pinned setup-ndk action](https://github.com/nttld/setup-ndk/blob/ed92fe6cadad69be94a966a7ee3271275e62f779/action.yml)
- [Pinned run-vcpkg action](https://github.com/lukka/run-vcpkg/blob/b1a0dd252f06b9e25b3c022a9a03bd7a427fb6a2/action.yml)

## Paired fixture implementation

The stacked Phase 2 pull request runs the pair in its Android x86_64 Standard matrix cell. It keeps the fixture tree and verified native inputs at their canonical paths, snapshots the Flutter project before the first APK command, and restores that snapshot for the second command. Each sample starts with its own Gradle home and Pub cache. The warm sample receives only Gradle's `caches/modules-2` dependency files, excluding locks and garbage collection state. Both samples resolve online with task-output caching and persistent Gradle daemons disabled.

The numeric report records package wall time, observable download log lines and rate-limit messages, Flutter's aggregate Gradle time, and observed resolution intervals for the included Flutter build's root `compileClasspath`. Download lines are not byte counts or a cache hit ratio. A missing timing appears as an empty sample list and needs investigation before drawing conclusions. Both APKs use the existing fixture verifier, and the warm package report remains the normal matrix input. Only JSON metadata is uploaded. The dependency contents, tool homes and APKs remain local to the fixture job.
