# Radar Remote: hide client deployment UI (v3 only)

Base: `290b2a4672ac4b5db8a6b724e1f1a51f7186ea57`. Reference RustDesk: `95cca3f661f635b3cc85c04935fe8d96d8f432ef` (1.5.3). This is separate from WSS audit PR #262 and unified logging development.

## Read-only audit and intended minimal change

| Source in official tree | Purpose / platform | Policy |
| --- | --- | --- |
| `flutter/lib/mobile/pages/settings_page.dart:786-793` | Android-only Deploy settings tile, excluding outgoing-only | Omit the entire tile using one v3 UI flag; no placeholder |
| `flutter/lib/main.dart:568-576` | Android `android_needs_deploy` handler opens prompt after server asks for device deployment | Do not register this UI handler when hidden |
| `flutter/lib/mobile/widgets/deploy_dialog.dart:9,30` | Prompt → API Token/custom-ID deployment dialog | Guard both public UI entry functions against direct/stale calls |
| `src/flutter_ffi.rs:1214`, `src/ui_interface.rs:1133` | Android device provisioning bridge/backend | Retain unchanged |
| `src/core_main.rs:658` | CLI provisioning operation | Retain unchanged; this is not client-visible UI |
| `src/rendezvous_mediator.rs:270,568` | Server deployment-required notification | Retain underlying protocol/event behavior |

These entries provision/register a client device using an API Token. They are not installers, client updates, service startup, file transfer, remote sessions or GitHub deployment. No dedicated upstream hide-Deploy switch was found. Windows/Linux/macOS have no corresponding menu, navigation entry or prompt in the locked source (**NOT APPLICABLE**). Translation entries are retained.

Implementation: independent Common `0008-hide-deploy-ui.patch`, v3 only, with `flutter/lib/common/deploy_policy.dart` defining `kRadarDeployUiEnabled = false`. All four UI gates import that policy; underlying dialogs/API/CLI remain. Standard and SOS receive the same Common policy, with existing variant restrictions unchanged. No runtime/build variable or user configuration is introduced.

## CI safety before remote writes

Audited all `.github/workflows/*.yml` triggers/calls on the base above and re-fetched main before writing. No workflow file is modified.

- Isolated branch pushes do not match any `push` trigger (current push triggers are main-only).
- PR events can run `ci.yml` and path-selected read-only compatibility tests. `ci.yml` invokes `channel.py resolve --channel ci` and reusable `compat-check.yml`; it does not call Tag/Nightly/build release workflows or production signing. Workflow/artifact “publish report” steps only write CI reports/artifacts.
- `build-reliability.yml` is the sole `workflow_run` entry. Its retry-capable `observe` job explicitly excludes CI, requires main and a workflow_dispatch origin. The CI completion branch has contents/actions read permission and renders a dashboard only. `summary_dashboard.py` does not dispatch, retry, publish releases or sign.
- Stable `tag.yml`, `nightly.yml`, `publish-stable.yml` and YubiKey smoke/signing require manual dispatch / separate authorization. Upstream routers are schedule/manual main jobs, not PR/push downstreams. Reusable production build/signing jobs are not reachable from this PR CI call graph. No pull_request_target, repository_dispatch or release-trigger deployment route exists.
- No self-hosted production runner, production secret, permission escalation or privileged workflow dispatch is used by this task. No workflow is re-run, manually triggered or disabled to bypass restrictions.

Recheck this boundary before each subsequent push/PR write; independent scheduled production activity is not task authorization.

## Validation plan and compatibility boundary

Run exact 1.5.3 Standard/SOS patch application and existing structural/native-helper contracts. Add a v3 source contract that checks collection-level omission, automatic-handler guard, both dialog guards and unexpected new dialog callers. Include both new policy and existing dialog in the existing Flutter analysis inputs. This is validation tooling, not a CI/CD workflow change.

Record source checks separately from Flutter analysis, product compilation and device/UI checks. The local environment currently lacks Flutter/Dart, Android SDK and adb. A source assertion is not a rendered-menu test. Windows/Linux/macOS Deploy UI is N/A, rather than newly hidden through unnecessary platform changes.

Risk: users of a server that requires Android provisioning will no longer see its deployment prompt or token form; provisioning remains an administrator/backend/CLI concern. The server requirement is not bypassed. Existing install/update/service/network/audio/video/file/clipboard code remains untouched. There is no logging subsystem change in this PR.

v1/v2 archived patch bytes, v2.8 identity, historical Tags/Releases/signatures and their existing retirement policy are untouched. Build Identity schema, Android PIV signing configuration and Stable/Nightly mechanisms remain unchanged. New v3 patch content requires the normal reviewed content revision; this does not allocate a release or mutate historical artifacts.

## CI findings and test-fixture correction

The first functional head `0460abb` passed all three desktop API transports and Standard/SOS Flutter analysis, but failed architecture/preflight tests because four offline contracts still expected live v3.5 after the legitimate v3 candidate advanced to r6. Their current-version expectations now read the reviewed manifest; historical identities and negative cases are not changed. Only `_contract.py` tests are edited, not release, signing, identity generation or workflow implementations. The complete existing 33-command domain suite was rerun locally with placeholder GitHub tokens and isolated mocks; `domain-results.json` records individual results. No actual release/tag/signing API was called.

## Local validation and status

- PASS: exact 1.5.3 Standard/SOS patch application, UI/source contracts, native configuration helper compilation and upstream DPI preservation (`source-results.json`).
- PASS: v3 Deploy source contract verifies all four gates, unexpected callers and retained Rust entry points.
- The first content-version test run exposed a historical r1 fixture containing the new r6 patch. The fixture now excludes both post-r1 additions (0007/0008) and still checks the original r1 hashes; no runtime check is removed or weakened.
- PASS: Profile (10), retirement (3), content-version (11) contracts and base-anchored content verification. v1/v2 hashes remain unchanged; v3 candidate content advances from r5 to r6 only.
- NOT RUN locally: Flutter analyze, full Android APK compilation, rendered menu/device interaction (Flutter/Dart/Android SDK/adb absent). Current-head CI will run existing generated-bridge/Flutter analysis with the new files explicitly included. No new workflow is added.
- Android Standard: source omission/guards PASS; actual runtime UI NOT RUN. Android SOS: NOT APPLICABLE (not an enabled package variant).
- Windows x64, Linux x64/ARM64, macOS Intel/Apple Silicon: Deploy UI NOT APPLICABLE in the locked upstream; native package builds/runtime unaffected-code regression NOT RUN.
- Underlying API/CLI/protocol implementations and translation strings have no changes in `0008`; only four Dart files are patched. No Rust compile interface is changed.

The Draft PR remains unmerged; CI status must be read for its exact latest head. Review readiness is pending that verification, not production authorization.

DEPLOYMENT: NOT PERFORMED
RELEASE: NOT PERFORMED
PRODUCTION SIGNING: NOT PERFORMED
PRODUCTION CONFIG CHANGES: NONE
STABLE VERSION CHANGES: NONE
PR STATUS: DRAFT
READY FOR REVIEW: NO (validation pending)
