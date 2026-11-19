# Unified diagnostic logs — implementation and acceptance record

Status: DRAFT; READY FOR REVIEW: NO. This is development evidence, not a release, device-validation or WSS-fix claim.

## Nightly patch-context repair (v3.9; 2026-11-19)

Compatibility run [44510913873](https://github.com/billradar/rustdesk-custom/actions/runs/44510913873) stopped Standard and SOS on `0009-unified-diagnostic-logs.patch`, `src/server/connection.rs:5306`, using official SHA `dcb6291116158c7cbd9cb40b5a5c5f7986468904`. Relative to the formal 1.5.3 SHA `95cca3f661f635b3cc85c04935fe8d96d8f432ef`, upstream added `#[cfg(windows)] self.privacy_preparation.take();` between `self.closed = true;` and the voice-call cleanup comment. The old hunk required immediate adjacency and failed at `git apply --check`.

The v3.9 fix changes only the context of the existing typed session-disconnect insertion: it now anchors on the unchanged voice-call comments. On newer Windows upstream, the existing privacy cleanup stays immediately after `self.closed` and before the diagnostic event; on official 1.5.3, the resulting code is unchanged. No cleanup statement, diagnostic payload, public API, source variant policy or runtime feature was removed.

Read-only checks on the formal 1.5.3 SHA, failed Nightly SHA and newer official master SHA `c50ae975128e3061ee5c209f4eb8fb4a2605380f` confirmed success for the revised `connection.rs` hunk; the failing Nightly hunk was independently reproduced before changing it. Independent sparse upstream worktrees then passed sequential root Common `0002–0009` application and SOS `0001–0003` application on all three SHAs. Unchanged `0001` and `0010` were also applied successfully to the shared locked hbb_common SHA `fae47e024dd83cef6aaecde0aa7d11731df11649`. The diagnostic adapter source contract passed. Full native compilation, Flutter/Android clients and physical-device testing remain unverified; a successful source patch check does not establish Nightly build/release readiness. New patch content is tracked by the reviewed v3.9 revision and Common digest in `patchsets/v3/patchset.json`.

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
- `Store::command(Export)`: revalidate then stream canonical records into tar with safe build/platform metadata; no full-file buffer or intermediate log copy. Private archives count toward the configured cap, need verified free disk space, and partial archives are removed on failure. Export may safely fail when no temporary budget remains. The UI deletes a temporary archive after the platform picker completes; confirmed cleanup also removes closed private temporary archives; stale closed private archives are eligible for cleanup after one day. User-selected exported destinations are not managed/deleted.
- `hbb_common::{DiagnosticWriter,diagnostic_format,init_log}`: reuse existing logger; optional typed capture plus metadata-only necessary error output. Non-error records do not create blank legacy file lines. Arbitrary record arguments are never formatted into the managed store.
- `src/flutter_ffi.rs::{main_set_local_option,main_get_local_option}`: reuse the existing bridge ABI with reserved `radar-diagnostic-request:` / `radar-diagnostic-result:` namespaces. Async submission is intercepted before ordinary option persistence; sync polling touches only a bounded in-memory result registry. No new generated bridge method or production bridge recipe change is required; only sanitized codes are returned. Existing Build Identity JSON feeds a strict numeric/hash/variant/channel allowlist, without changing its production generator.
- `flutter/lib/common/{diagnostic_events.dart,widgets/logs_page.dart}`: shared desktop/mobile Logs page; enable/stop, all requested duration/size/capacity/retention presets and custom values, local schedule controls, status, directory selection/open, paged viewer with time/level/module/keyword filters, pinning, multi-selection export and confirmed cleanup. Flutter debug/error adapters omit arbitrary text/stacks and keep at most one bridge event in flight.
- Android `DiagnosticLog.kt` and `android_log.rs`: native metadata enters the same Rust engine. No new storage permission. Active files and private state use internal application files storage derived from the existing PathProvider documents root, not Android external file-transfer home; canonical paths remain within the existing SAF export allowlist. Missing/unrecognized private-root identity fails closed. SAF transfers only the validated archive. Desktop directory selection uses existing file_picker.
- `hbb_common/websocket.rs::WsFramedStream::try_connect`: typed scheme/port/route/HTTP-status events, including 301/101, without URL, Host, SNI, TLS verification, fallback, redirect or protocol behavior changes. This provides evidence for #262; it does not assume its cause.

No new build variable or production domain is introduced. No production workflow is modified. The new diagnostic workflow is read-only, PR-only, GitHub-hosted, without Secrets, signing, dispatch or publication.

## Privacy boundary and risks

- HIGH / ACCEPTANCE OPEN — Typed hooks now cover the requested module families and local async/thread session propagation; see [module-coverage.md](module-coverage.md) for exact functions, boundaries and runtime evidence. Full client/module execution and cross-process attribution remain unverified; do not claim exhaustive end-to-end coverage. Legacy text is still omitted, not reintroduced.
- HIGH / OPEN — Full Flutter bridge/UI and Android JNI/SAF builds/runtime remain unverified. Core success does not establish that an installed APK can display/export logs or explain its 301.
- MEDIUM / OPEN — OS-owned crash/driver reports, third-party direct stdout/stderr and historical raw logs are not sanitized by the managed exporter. They are excluded, not imported. This is not an OS-wide privacy guarantee. Do not offer raw-log import/export through the new page.
- MEDIUM / OPEN — Schedule/backend/SAF permissions and sleep/time changes require actual platform testing. The UI expressly says collection requires the process to run and Android may suspend it. Cross-process configuration is polled; no claim of instantaneous policy propagation across all services/users.
- VERIFIED IN CORE TESTS — Processes in the same user store share a private recording key/identifier, persisted outside log files and excluded from public settings/view/export. An older process cannot persist an automatic stop over a newer recording. Real service/user-boundary behavior remains NOT RUN.
- LOW — Damaged managed files fail closed; users must exclude them from export. Salvaging a validated prefix is not implemented. Protected usage can stop optional writing; the UI offers cleanup and explicit restart.

Necessary application error handling is preserved; optional collection is local and off by default. Exceptions/messages/headers/bodies/passwords/tokens/cookies/keys/keyboard/screens/clipboard/file contents never enter the new event schema. Legacy necessary error files now retain sanitized error metadata. This intentionally reduces legacy free-text detail; typed coverage must compensate rather than reintroducing raw strings.

## Initial CI failures and corrections

Initial head `9bf6853` runs: diagnostic `44070213610`, compatibility `44070213424`. Windows x64, Linux x64, both macOS architectures passed the diagnostic engine; all three Android Rust core target checks passed in the Linux job. Linux ARM64 exposed a test requiring every writer to acquire a non-fair file lock within 100 ms. The test now releases both real processes through a start barrier, requires progress by each, checks every attempted event is accounted as written or contention-dropped, and joins both children before cleanup. It preserves quota/protection assertions and reflects the production nonblocking drop policy instead of assuming lock fairness. Fresh CI remains necessary.

Existing Ubuntu Python 3.10 lacked stdlib tomllib: reuse already-pinned tomli instead of changing the workflow/toolchain. Latest compatibility source `54416dcaa127d209f2cfbdc4b08235bae78ccfe6` adds an import beside DocumentLogs' Log import: use qualified sanitized calls in its stable method bodies, preserving the upstream imports/FFI differences. Existing bridge generation uses unpatched official source, so the draft's added bridge function was replaced by the original ABI's ephemeral request/result namespaces; ordinary config files never receive those request payloads. No failed check was skipped or production gate modified.

Codex review of `8ec1930` found P1 first-initializer bypass and P2 stale-enable restart. The first FFI initialization now uses the private resolver, with negative adapter tests rejecting the old direct path and any new bridge ABI. Starting is a distinct backend operation: ordinary configuration preserves authorization and the current window/key, ignores stale enabled flags, checks for expiry and respects another process's stopped state under the persisted-state lock. The page refreshes only the backend-owned enabled flag while preserving unsaved form edits. Schedule edits apply on the next explicit start. New runtime regressions cover stopped/expired/cross-process cases and freezing elapsed time on manual stop. File lists are capped at 200 entries per page before crossing the sync result bridge; export selection is bounded. Android's known per-key log calls are removed entirely rather than emitted as per-key metadata. Existing necessary native system messages retain sanitized levels.

The next ARM64 run also exposed cross-case fork inheritance: while one case held a fixture lock, another case spawned a child that briefly retained the open-file description until exec, yielding the expected nonblocking busy result in a case with no intentional contention. The harness now runs cases sequentially. The producer test still runs eight threads; the cooperating-writer case still releases two real processes together, requires progress/accounting from both and enforces quota/active/pin assertions. No concurrency case or assertion is disabled; no production lock timeout is relaxed.

## Typed module/session follow-up

Added a closed Action vocabulary, random DiagnosticContext, poll-scoped async propagation and explicit decoder/child-task propagation. Incoming/outgoing contexts are independent; nested network/API operations retain their parent local identity. Context is restored before yielding and on unwind. Module-family state hooks are coalesced, without reading content. Typed API selection/status, config, DNS/TCP/UDP/proxy/TLS, rendezvous/relay/NAT, OIDC/upload, login/permission and media/transfer/clipboard hooks are inventoried in [module-coverage.md](module-coverage.md). Existing network retries/authentication/TLS policy remain unchanged. The TLS selector harness now links the actual diagnostic crate instead of a mock logging sink, and verifies private material does not reach its managed records. Previous e780a45 CI is historical evidence only; the follow-up needs fresh CI.

## Verification

| Check | Result | Scope/evidence |
|---|---|---|
| Rust 1.75 actual engine unit/runtime tests | PASS | 22 Rust cases (including child-process helper), isolated test-case scheduling with explicit concurrent thread/process tests, actual source via `diagnostic_logs.py`; see [core-results.json](core-results.json) |
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
| Windows/Linux x64+ARM64/macOS Intel+ARM core runtime | PASS on `8ec1930`; new head pending | Native core matrix; not full client/runtime UI |
| Android ARM64/ARMv7/x64 core compilation | PASS on `8ec1930`; new head pending | Rust std target checks only; no APK, SDK/JNI/SAF or production signing |
| Flutter analyze / generated bridge | PASS on `8ec1930`; new head pending | New files included in existing compatibility analysis |
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
