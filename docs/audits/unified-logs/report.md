# Unified diagnostic logs — implementation and acceptance record

Status: DRAFT; READY FOR REVIEW: NO. This is development evidence, not a release, device-validation or WSS-fix claim.

## Identity and read-only audit

Custom base `83bbff7a047eae5a2fdc57026c779050c02c8063`; official 1.5.3 `95cca3f661f635b3cc85c04935fe8d96d8f432ef`; hbb_common `fae47e024dd83cef6aaecde0aa7d11731df11649`. The pre-implementation [design](design.md) records the original audit. Actual installed Android APK identity remains UNKNOWN; #262 is not resolved by these source changes.

Confirmed upstream paths:

- `libs/hbb_common/src/lib.rs::init_log` (upstream lines 427–493): Once-guarded global log facade; env_logger in debug, flexi_logger in release. Existing file output used unrestricted formatted text, daily/16 MiB rotation and 90 closed files, not one total quota.
- `src/flutter_ffi.rs::initialize` (upstream lines 42–90): Android debug and release use different log initializers. Desktop Flutter initializes the common logger separately from the core executable/process.
- `src/platform/android_log.rs::{initialize,DocumentWriter::write}`: existing release file/SAF adapter, with synchronous JNI callbacks on some writes. Reuse its existing logger; do not install another global Logger.
- `flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/{DocumentLogs,MainActivity}.kt`: existing document storage and ACTION_CREATE_DOCUMENT export. New export uses only the existing `export_file` action, not legacy raw-log export.
- `flutter/lib/desktop/pages/desktop_setting_page.dart::{SettingsTabKey,_settingTabs,_children}` and `flutter/lib/mobile/pages/settings_page.dart::_SettingsState.build`: desktop tabs and mobile first-level sections. v3 Common is applied before SOS restrictions.
- Native Android logs also bypassed imported `Log`: `KeyboardKeyEventMapper.kt` printed keyboard codes; `FloatingWindowService.kt`, `MainService.kt` and `common.kt` printed arbitrary exception stacks. The new adapter replaces those calls without recording their values.

## Implementation and changed runtime paths

The v3 submodule adaptation is appended to `patchsets/v3/common/0001-hbb-server-defaults.patch` because existing `apply_patches.sh` deliberately routes that file to hbb_common. Other runtime changes are isolated in `0009-unified-diagnostic-logs.patch`. No archived patch bytes change.

- `libs/radar_diagnostics/src/lib.rs::{Settings::validate,Engine::start,Engine::capture,Engine::request}`: defaults off / Info / 1h / 20 MiB / 100 MiB / 7 days; closed typed event schema; HMAC endpoint/session/thread identifiers; bounded 1024-event queue and 16-command queue. Capture uses try_lock/try_send, never storage or a blocking queue send.
- `Store::{command,tick,write,files,persist}`: worker-owned writes, UTC schedule/end persisted across restarts plus monotonic active deadline, independent runtime end versus user-configured end, rotation, retention, oldest-closed-file cleanup, pin/active protection and quota failure status. fs2 process file locks protect active files and shared operations. Contention is normalized on Windows/Unix and counted as dropped events rather than disabling capture.
- `visit_records`, `validate_event`, `ValidatedReader`: bounded record decoding; reject unknown fields, raw identifiers, invalid enum/identifier/time/status fields, symlinks and corrupt records before viewer/export. Never copy a raw legacy file.
- `Store::command(Export)`: revalidate then stream canonical records into tar with safe build/platform metadata; no full-file buffer or intermediate log copy. Private archives count toward the configured cap, need verified free disk space, and partial archives are removed on failure. Export may safely fail when no temporary budget remains. The UI deletes a temporary archive after the platform picker completes; stale closed private archives are eligible for cleanup after one day. User-selected exported destinations are not managed/deleted.
- `hbb_common::{DiagnosticWriter,diagnostic_format,init_log}`: reuse existing logger; optional typed capture plus metadata-only necessary error output. Non-error records do not create blank legacy file lines. Arbitrary record arguments are never formatted into the managed store.
- `src/flutter_ffi.rs::main_diagnostics`: one asynchronous bridge management API; only sanitized codes are returned. Existing Build Identity JSON feeds a strict numeric/hash/variant/channel allowlist, without changing its production generator.
- `flutter/lib/common/{diagnostic_events.dart,widgets/logs_page.dart}`: shared desktop/mobile Logs page; enable/stop, all requested duration/size/capacity/retention presets and custom values, local schedule controls, status, directory selection/open, paged viewer with time/level/module/keyword filters, pinning, multi-selection export and confirmed cleanup. Flutter debug/error adapters omit arbitrary text/stacks and keep at most one bridge event in flight.
- Android `DiagnosticLog.kt` and `android_log.rs`: native metadata enters the same Rust engine. No new storage permission. Active files stay private; SAF transfers only the validated archive. Desktop directory selection uses existing file_picker.
- `hbb_common/websocket.rs::WsFramedStream::try_connect`: typed scheme/port/route/HTTP-status events, including 301/101, without URL, Host, SNI, TLS verification, fallback, redirect or protocol behavior changes. This provides evidence for #262; it does not assume its cause.

No new build variable or production domain is introduced. No production workflow is modified. The new diagnostic workflow is read-only, PR-only, GitHub-hosted, without Secrets, signing, dispatch or publication.

## Privacy boundary and risks

- HIGH / OPEN — Typed diagnostic detail and per-remote-session correlation are not yet complete across every subsystem. Legacy facade events expose module/severity/type metadata, not arbitrary error strings. WSS receives explicit transport/status fields; broader API/config/session/audio/video/transfer/permission fields still need review and integration before claiming complete diagnostic coverage.
- HIGH / OPEN — Full Flutter bridge/UI and Android JNI/SAF builds/runtime remain unverified. Core success does not establish that an installed APK can display/export logs or explain its 301.
- MEDIUM / OPEN — OS-owned crash/driver reports, third-party direct stdout/stderr and historical raw logs are not sanitized by the managed exporter. They are excluded, not imported. This is not an OS-wide privacy guarantee. Do not offer raw-log import/export through the new page.
- MEDIUM / OPEN — Schedule/backend/SAF permissions and sleep/time changes require actual platform testing. The UI expressly says collection requires the process to run and Android may suspend it. Cross-process configuration is polled; no claim of instantaneous policy propagation across all services/users.
- VERIFIED IN CORE TESTS — Processes in the same user store share a private recording key/identifier, persisted outside log files and excluded from public settings/view/export. An older process cannot persist an automatic stop over a newer recording. Real service/user-boundary behavior remains NOT RUN.
- LOW — Damaged managed files fail closed; users must exclude them from export. Salvaging a validated prefix is not implemented. Protected usage can stop optional writing; the UI offers cleanup and explicit restart.

Necessary application error handling is preserved; optional collection is local and off by default. Exceptions/messages/headers/bodies/passwords/tokens/cookies/keys/keyboard/screens/clipboard/file contents never enter the new event schema. Legacy necessary error files now retain sanitized error metadata. This intentionally reduces legacy free-text detail; typed coverage must compensate rather than reintroducing raw strings.

## Verification

| Check | Result | Scope/evidence |
|---|---|---|
| Rust 1.75 actual engine unit/runtime tests | PASS | 15 Rust cases (including child-process helper), actual source via `diagnostic_logs.py`; see [core-results.json](core-results.json) |
| Pre-write privacy / payload not formatted | PASS | Typed schema, poisoned fields, build allowlist, HMAC checks and a Display implementation that panics if formatted |
| Concurrent writer/quota protection | PASS | Actual child processes and OS file locks; active/pinned files protected |
| Rotation, quota, retention, archive budget | PASS | Runtime filesystem tests, closed/pinned/active and private-export cases |
| Schedule/restart/time deadline | PASS | Deterministic state/deadline tests; not real OS suspend/background behavior |
| Queue contention/overflow | PASS | Concurrent producers and held-state lock test; counts drops, no recursive logging |
| Query/export/corruption | PASS | Bounded pages, valid tar, traversal/unknown fields/corrupt file rejection, failed-export cleanup |
| Rustfmt and Clippy -D warnings | PASS | Rust 1.75 actual engine, same pinned dependency graph |
| Existing logger adapter compile | PASS | Extracted actual common formatter/init in debug and release, plus Android format callback signature; isolated mock Config, not full hbb_common/client |
| Standard / SOS patch application | PASS | Fresh exact official/hbb_common trees; rechecked after final patch freeze |
| Profile/content/retirement contracts | PASS | See [domain-results.json](domain-results.json); old patch bytes/routing remain protected |
| Repository contract | PASS on ordinary clone snapshot | Worktree `.git` file triggers a pre-existing root-file false positive; equivalent ordinary clone snapshot passes, without weakening the contract |
| Actions static validation | PASS | actionlint on new read-only workflow |
| Windows/Linux x64+ARM64/macOS Intel+ARM core runtime | CI pending | Native core matrix; not full client/runtime UI |
| Android ARM64/ARMv7/x64 core compilation | CI pending | Rust std target checks only; no APK, SDK/JNI/SAF or production signing |
| Flutter analyze / generated bridge | CI pending | New files included in existing compatibility analysis |
| Full clients / native UI / actual Android SAF/device | NOT RUN | No devices or complete local SDK/toolchain; Flutter download returned HTTP 403 |
| Actual disk-full, storage revocation, crash/sleep/A/V impact | NOT RUN | Directory/corrupt/quota fault paths tested; not equivalent to actual OS/device faults |

## Operational status

DEPLOYMENT: NOT PERFORMED
RELEASE: NOT PERFORMED
PRODUCTION SIGNING: NOT PERFORMED
PRODUCTION CONFIG CHANGES: NONE
STABLE VERSION CHANGES: NONE
PR STATUS: DRAFT
READY FOR REVIEW: NO
