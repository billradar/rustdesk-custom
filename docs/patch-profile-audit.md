# Patch Profile audit — 2026-11-12

## Scope and branch evidence

Before edits, main was `3c53d9e5677b6a322be7d195f1c40b04ef2707e4`, development was `d6d402ef08b9e9a1a2b8631e6885c22b4031ed33`. Development was 47 commits behind, with no unique commits; its head was the merge base. PR #247 was an open draft based on main with head `3656400c2b737061e16d2ab84b8a9ed45fb471d7`. Its final diff contained only YAML hash normalization and one regression test. Intermediate CM edits had been reverted; one intermediate patch had a concatenated diff header and must not be restored.

Work reused the PR's hash fix, adding collision/order regression coverage, explicit version Profiles and an isolated candidate v3. Existing v1/v2 patch trees, metadata, changelogs and revision histories remain byte-identical to main. v2 remains revision 8 with Common `a9a8ef83aa02890f09beb19e0b4818b268d4d873362f9ccf7ee9b09d3415e5b0` and SOS `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`.

## Immutable source checks

| Source | SHA | Patchset | Standard | SOS |
| --- | --- | --- | --- | --- |
| Official `1.5.1` Git tag fetched for this audit | `23e5bb471a040d62f0a6ad52591fb30784265b73` | v2.8 | Apply/check + structural contracts PASS | Apply/check + structural contracts PASS |
| 1.5.3 candidate from failed run 42572512338 | `05b9f2d8919b5cdfaa0bb3280601a02881556a42` | v3.1 | Apply/check + structural contracts PASS | Apply/check + structural contracts PASS |

Both snapshots lock hbb_common to `fae47e024dd83cef6aaecde0aa7d11731df11649`. Each variant was tested in an independent clean copy. The integration harness checks exact source/submodule identities, actual Common→SOS patch order, all per-patch `git apply --check` calls and compatibility contracts. It reproduces the original v2 candidate conflict in `flutter/lib/models/chat_model.dart` at Common 0004. The entire candidate chat file, after reversing only the intended visibility hooks, equals upstream; the Windows DPI helper is byte-identical in both variants.

Reproduce with clean local snapshots:

```sh
python3 -m scripts.upstream.patch_profile_sources_contract \
  --stable /path/to/23e5bb471a040d62f0a6ad52591fb30784265b73 \
  --candidate /path/to/05b9f2d8919b5cdfaa0bb3280601a02881556a42
```

The candidate SHA is not a release tag. No 1.5.2 source or official release was validated. Neither candidate nor unknown-version fallback can allocate a Stable revision, lock or client identity; a passing compatibility test cannot enable Stable.

## Local validation

All 26 commands in compat-check.yml's release/domain contract step completed successfully. The unittest runners reported 400 tests: 396 passed, four skipped. Skips were two platform-adapter snapshot fixtures absent from the unit-test harness, one real Rust update-policy compilation and one real Rust MIR compilation (rustc absent). Repository architecture/YAML checks and all three patchset content-history checks also passed. CM prepared-source wiring and three-generation policy parity passed; pure-Dart policy execution was NOT RUN because Dart was absent. The compiled native configuration helper tests used GCC; these are not RustDesk application builds.

Tests cover exact Profile preference, unknown-version latest fallback, candidate/fallback Stable rejection, profile isolation, missing-profile fail-closed behavior, patch failure stopping before subsequent Common/SOS patches, v2 hash/revision preservation, deterministic mixed-key hashing and collision rejection, new-generation parent/base anchoring, existing Stable build identity, release gates and signing boundaries.

## Remaining limitations

No native RustDesk package, generated bridge, Flutter analysis, hardware signature, device installation, native window UI or real remote session was produced/tested locally. This host lacks cargo/rustc, Flutter/Dart, CMake/Ninja and Clang. Candidate interface review still reports unapproved Linux/macOS/Android signatures; these gates are preserved. The candidate Windows/bridge signature matches existing reviewed `f13aa9d4edd1afa76be5803dd3c28cf01785c359bd393e3d2b090312797308a6`, which does not approve other platforms or imply build/runtime success. Production signature metadata and signing workflows were not modified.

CI and Codex review on the resulting PR head are separate evidence and must be checked on GitHub; this document records local validation only. main/development integration and Release publication require explicit user approval.

## CI follow-up

Run [43060851575](https://github.com/billradar/rustdesk-custom/actions/runs/43060851575), on initial implementation head `0a16798abdb76f58fd34540764623ecfee860960`, passed architecture/domain contracts, Profile selection and all six Common patches on newer upstream candidate `2fe026917dbdc0f715a8ce299da5eaf4e016587e`. The native helper verifier then failed because its isolated `base::config` fixture only recognized v2. The follow-up includes v3 in that fixture without changing production patches, and lets the exact-source integration harness execute native helper compilation whenever rustc is available. Exact Profile precedence over the historical boundary also gained a regression test (48 focused tests passed locally). New-head CI remains separate evidence.

## Nightly native-interface follow-up

Nightly run [43062159481](https://github.com/billradar/rustdesk-custom/actions/runs/43062159481), on merged custom commit `44168f81035911df415c94c01da588a657f5b65d`, stopped at native-interface preflight for exact upstream `95cca3f661f635b3cc85c04935fe8d96d8f432ef`. This is independent of the successful PR compatibility rerun on `7f948f7`; no native build, production signing or Draft creation occurred in the failed Nightly run.

The [exact-source static review](audits/nightly-interfaces-43062159481/review.json) compares the already approved `09871abd0bc13a69b4318edad031287d8d4314d2`. Linux/macOS/Android jobs and the global environment are identical. Critical changes are limited to disabling Sciter debug assertions in the Cargo development profile and advancing Flutter's build number from `1.5.3+70` to `1.5.3+71`. An upstream publication job gains a no-overwrite check; custom native recipes do not execute that job. Android scripts, Gradle, bridge/helper, build.py and build.rs are unchanged.

Only the three exact native-interface fingerprints and the matching macOS ARM64 full-workflow identity are added. Existing reviewed identities remain intact. Wayland still matches its existing DRM job, packaging source and libdrmtap pin. v2 revision 8 and candidate/fallback Stable rejection remain unchanged. Local preflight validation is separate from a successful Nightly build on a future committed head; native packages, production signatures and runtime behavior remain unverified.

Local validation on the uncommitted repair: all seven native preflight pairs and both Wayland architectures pass. Independent Standard/SOS copies pass patch checks, structural contracts and upstream DPI preservation. Critical-file/toolchain drift and the independent Mac ARM workflow-hash drift remain rejected. Repository architecture passes with umask 022; seven affected contract suites ran 116 tests (114 passed, two missing-snapshot fixtures skipped). Native helper compilation was not run because rustc is unavailable. No workflow was dispatched and no production signing or release API was invoked.
