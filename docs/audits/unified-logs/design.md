# Unified diagnostic logs: audit and implementation design

Read-only audit base: `290b2a4672ac4b5db8a6b724e1f1a51f7186ea57`; RustDesk 1.5.3 `95cca3f661f635b3cc85c04935fe8d96d8f432ef`, hbb_common `fae47e024dd83cef6aaecde0aa7d11731df11649`. This document was written before logging runtime changes; current implementation and gaps are tracked in [report.md](report.md). Separate branch `feature/unified-logs-v3`; do not mix into WSS #262 or Deploy UI #265.

## Existing implementation

- `libs/hbb_common/src/lib.rs:427-493`, `init_log`: Once-guarded global logger. Debug uses env_logger; release uses flexi_logger 0.27. Release defaults to debug with third-party module overrides, direct or async mode, 16 MiB/day rotation and 90 closed files. This is count-based retention, not a shared total quota. It formats unrestricted free text.
- `Config::log_path` (`config.rs:951`) chooses per-user locations (macOS Library/Logs, Linux .local/share/logs, Android application home, Windows config parent/log). `src/core_main.rs:183`, `service.rs:17` and desktop `flutter_ffi.rs:85` initialize distinct process/library instances; do not install a second global Logger.
- Android `flutter_ffi.rs:58-68`: debug android_logger, release `platform/android_log.rs::initialize`. Its DocumentWriter can synchronously call JNI/SAF on a log call, otherwise writes a rotating private log. JNI-target logs avoid callback recursion. Existing `DocumentLogs.kt` has a persisted restricted Documents grant, rotation, locks and export, but this is a separate Android path, not the new global policy. It accepts unrestricted formatted text.
- Flutter uses distributed `debugPrint`, `debugPrintStack` and framework error handlers. They are not unified with Rust or a per-user collection setting. Android Kotlin uses `android.util.Log` throughout service/activity/storage modules. C/C++/OS-owned crash and driver reports have independent lifetimes.
- Android MainActivity already has file/tree selection and export through the existing method channel/SAF; desktop already depends on file_picker and path_provider. Reuse them, add no storage permission.
- Desktop settings navigation is `desktop_setting_page.dart` (SettingsTabKey/_settingTabs/_children). Android mobile settings is `mobile/pages/settings_page.dart`; both can host the same Logs page/widget.
- v3 Common patches are shared by Standard and SOS, then existing SOS restrictions apply. Exact 1.5.3 routing and unadapted compatibility policy must stay. v1/v2 are archived and retired; neither bytes nor routing/signing/release mechanisms may change.

## Privacy contract

A central Rust library owns event schemas, capture gates, storage and management. Native/Flutter adapters feed it; none creates another log store or global Logger. Each event has a numeric/timezone-bearing timestamp, severity, a closed module/event/code vocabulary, process/thread identity and recording/session identifiers.

**Do not attempt to make arbitrary formatted text safe using regex.** Legacy Rust/third-party/Flutter/native free text, exception messages and payloads are omitted, not copied to the optional store or formatted into queues. Preserve useful metadata/source fingerprints; add typed, allowlisted diagnostic fields where actual transport/status detail is needed. Endpoints, peer IDs and paths become HMAC pseudonyms with a private per-recording key shared through private state among same-user processes; private keys/config never enter log exports. Never collect keyboard/screens/clipboard/file content or network bodies. Unknown field names/types are rejected.

Necessary existing errors/crash/system reporting remains, with app-managed file output routed through the sanitized formatter. OS-owned dumps/driver logs and existing historical raw logs are not magically sanitized: they must not be imported into the new viewer/exporter. Document that boundary; do not claim an OS-wide privacy guarantee. Export only validated new managed records plus a safe metadata allowlist.

## Shared engine

- One bounded, nonblocking producer queue; all event content safe before enqueue. Queue-full drops increment atomic counters without recursive log calls. Management commands use a separate bounded channel and the existing asynchronous Flutter setter plus an in-memory result polling namespace; no new generated bridge ABI is required.
- A worker owns file I/O, rotation, cleanup, scheduling and export; no storage operation on network/audio/video/UI producers. File locks serialize cooperating processes and protect active logs; a mutex alone is insufficient for service/main/CM processes.
- Defaults: optional persistence off; Info; 1h; 20 MB/file; 100 MB total; 7 days. Warn is included by Info. Level gates control capture, not just viewer filtering. Range-check custom sizes, total>=single, finite durations and start<end.
- Fixed schema NDJSON in application-owned files. Rotation closes a file before allocating the next; quota cleanup removes oldest unlocked/unpinned managed files only. Never delete active/pinned/unrecognized files. If protected usage leaves insufficient room, pause optional writes with an explicit status/error. Test disk errors and contention, not only happy paths.
- Persist schedule/settings outside exportable log files. Re-evaluate UTC start/end at boot/wake and bound active durations with a monotonic clock. Clock rollback must not extend an active budget indefinitely. Never promise collection when the app/process is not running; the UI must state this, especially on Android.
- Private default directory; desktop picker selects an application-owned subdirectory. On an unavailable custom directory preserve user settings, report the cause and use only an explicit/default safe fallback. Android active logs remain private; SAF is the authorized transfer/destination adapter, with revocation reported and no Root/full-disk permission.
- Viewer is bounded/paged, with time/level/module/keyword filters. File pin/unpin and confirmed cleanup are serialized. Export one/multiple closed logs as a standard archive with validated records and diagnostic metadata; no automatic upload, raw legacy import, key, token, real endpoint or filesystem path in metadata.

## UI and module integration

One shared Flutter Logs page is embedded as a first-level desktop setting tab and a first-level mobile setting section/page. It exposes all requested presets/custom controls, schedule disclosure, status/time/size/count/drops/errors, directory selection/opening, viewer/search, pinning, export and confirmed cleanup. Use existing platform picker/export APIs. Web is not a target and must fail explicitly rather than write browser storage.

Rust `log` routing covers core/config/network/rendezvous/session/audio/video/file/clipboard/FFI/permission modules and third-party metadata. Flutter debug/framework exceptions and Android native log calls feed the same engine. Add typed network/config/lifecycle events instead of a WSS/API-specific logger. Keep transport behavior and authentication unchanged.

## Verification and operational constraints

Test actual core code on Rust 1.75: gating, all presets/validation, deterministic scheduling and time jumps, restart, rotation/quota/retention/pins/active protection, queue overflow, concurrent/multiprocess access, storage fault injection/corrupt lines, privacy sentinels/schema rejection and bounded query/archive export. Test UI semantics separately from rendering/device tests. Desktop/Android builds, SAF grant revocation and real crash/restart must be marked PASS/FAIL/NOT RUN individually.

Before every remote write, re-audit current workflow trigger/call/downstream safety. The existing PR compatibility path and CI completion dashboard are non-production; manual/scheduled protected-main routers, Tag/Nightly/Release/signing and self-hosted PIV jobs are not invoked. No workflow disabling, dispatch/re-run, privileged secret, production configuration, release/tag operation, main/development push or merge is authorized.

This is the pre-implementation design, not a claim of completion or tested guarantees.
