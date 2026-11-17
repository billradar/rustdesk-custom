# Typed diagnostics and local session correlation

Scope: PR #266, v3 only, official `95cca3f661f635b3cc85c04935fe8d96d8f432ef` and hbb_common `fae47e024dd83cef6aaecde0aa7d11731df11649`.

This records actual source hooks, not a claim that every platform or remote session has been exercised. Full client, Android JNI/SAF and device acceptance remain NOT RUN.

## Correlation model

`radar_diagnostics::DiagnosticContext` creates a random local identity, never a peer ID, credential or key. `Remote::new` owns an outgoing context for the Remote object's lifetime (including reconnect rounds); `Remote::io_loop` enters it per future poll. `Connection::start` creates an independent incoming context. The client video/audio workers explicitly carry the creating context into their threads. Session-owned ICE, initial-clipboard and server child tasks explicitly carry context into spawned futures.

`Instrumented::poll` enters context only while polling, restores before Pending/Ready and restores on unwind. It never leaves thread-local state installed across await. Nested operation actions retain the same identity. Unrelated API calls, OIDC flows and remote sessions receive separate identities. The existing logger adapter inherits the active identity without formatting arbitrary arguments. Actual IDs are HMACed with the private recording key before enqueue, so exporting two recordings does not expose a stable peer identifier.

High-frequency audio/video/clipboard/file-family evidence is coalesced to one event per action per 30-second window per context; disabled capture does not consume a window. It never records each input, frame, clipboard value or file content. Permission changes and authentication results have explicit transitions. Lifetime guards record local start/end even on early return/cancellation; a generic end does not invent an error or reason. Explicit local Close records Cancelled. Unknown transport failures remain Unknown rather than classifying free text.

Cross-process host/client matching is deliberately not inferred from peer/IP/timestamp. Flutter framework and native process events without an explicit remote context remain independent. An external hbbs/hbbr/server is not instrumented. This is local diagnostic correlation, not a distributed trace or a claim of complete cross-process attribution.

## Hook inventory

| Module | Actual source functions | Typed evidence / context |
|---|---|---|
| App | `libs/radar_diagnostics/src/lib.rs::initialize`, existing `set_build` | AppLifecycle start; allowlisted build metadata, no identity generator changes |
| Configuration | `libs/hbb_common/src/config.rs::{load_path,store_path}` | ConfigLoad lifetime / ConfigWrite attempt, completion, failure; no keys/values/paths |
| DNS/TCP/proxy | `libs/hbb_common/src/tcp.rs::FramedStream::{new,connect}` | DnsResolve and TcpConnect / ProxyConnect stages; existing retries and timeout unchanged |
| UDP | `libs/hbb_common/src/udp.rs::FramedSocket::new_reuse` | UdpBind outcome; no datagrams or addresses |
| TLS | `libs/hbb_common/src/verifier.rs::FallbackPlatformVerifier::verify_server_cert`, `src/hbbs_http/api_failover.rs` security branches | Verification outcome / terminal TLS failure; no certificate/SNI/token text; existing security policy unchanged |
| WebSocket | `libs/hbb_common/src/websocket.rs::WsFramedStream::try_connect` | WebsocketUpgrade; actual transport/port/route/HTTP status retained from existing typed hooks, with current session context |
| ID / heartbeat / relay | `src/rendezvous_mediator.rs::{start_udp,start_tcp,register_peer,register_pk,create_relay}` | RendezvousRegister, Heartbeat, RelayConnect; no protocol/endpoint policy changes |
| NAT | `src/common.rs::test_nat_type_` | NatTest attempt/result; no network-type/VPN/TUN detection added |
| API | `src/common.rs::{http_request_http,post_request_http}`, `src/hbbs_http/api_failover.rs::{send_for,use_primary}`, `flutter/lib/utils/http_service.dart::HttpService.sendRequest` | ApiRequest / ApiRecovery; selected-origin HMAC plus HTTP status; Response extensions retain context into ApiResponseBody completion/failure; no headers/bodies; no added requests/replays |
| OIDC / account | `src/hbbs_http/account.rs::OidcSession::auth_task` | Independent OidcLogin context and lifecycle; existing request-path diagnostics; no auth URL, token or response text |
| Token handling | Current `UserModel.refreshCurrentUser` uses HttpService; no separate refresh-token endpoint was found in the audited paths | Existing profile/API operations use ApiRequest; do not falsely label profile refresh as token refresh |
| Recording upload | `src/hbbs_http/record_upload.rs::RecordUploader::send` | RecordingUpload attempt/status/outcome; upload/query/file bytes omitted |
| Remote session | `src/client.rs::Client::start`, `src/client/io_loop.rs::Remote::{new,io_loop,handle_msg_from_peer}`, `src/server/connection.rs::Connection::{start,on_close}` | SessionConnect / SessionLifetime, connected/disconnected, incoming/outgoing independent IDs |
| Authentication / permissions | login-response arms in Remote; `Connection::{send_login_error,send_permission}` and authorization transition | Login completion/rejection, Authentication code, permission enabled/disabled; no password/hash/PIN |
| Audio/video | `src/client.rs::{start_audio_thread,start_video_thread}`; Remote audio/video message arms | Decoder worker context/lifetime, coalesced activity; existing codec/error logs now inherit local session |
| Transfer | Remote file-response arm; Connection file-family handlers and read done/error hooks | Coalesced Transfer state / existing error metadata, with current session; no names/paths/bytes |
| Clipboard | Remote/Connection clipboard-family arms and session-owned initial-clipboard task | Coalesced ClipboardSync state, no values or per-key events |
| Flutter/FFI/native | `diagnostic_events.dart`, existing request/result bridge, `android_log.rs::Java_*_DiagnosticLog_nativeEvent`, original logger facade | Closed action/module/kind/code input; status/endpoint/session go through the same pre-write sanitizer; native PlatformCall; no new bridge ABI |

The legacy classifier now checks audio/video/clipboard/file before generic client and recognizes platform/IPC metadata, preventing `client::audio` from becoming a generic Session event. Arbitrary legacy text remains omitted. OS-owned dumps, third-party direct stdout/stderr and historical raw files remain excluded from the managed viewer/exporter.

## Runtime evidence

- PASS: actual core tests for interleaved pending futures, migration to another thread, cancellation/drop, nested restoration and panic/unwind.
- PASS: actual capture receiver verifies same-context correlation, distinct contexts, HMAC before enqueue, new-key separation, old schema decode, rejection of unknown action/secret fields.
- Actual selector/local-TLS regression now uses the real diagnostic crate, enables its store, checks HTTP status events and independent request contexts, and rejects fixture credentials/body/host material in the managed records. See `api-context-results.json` for result; existing 401/5xx/no-replay/TLS/proxy assertions remain enabled.
- NOT RUN: full client/module execution, native UI/JNI/SAF and real remote sessions on physical platforms. Source inventory/Flutter analyze do not substitute for these tests.

Local full hbb_common/workspace check: NOT RUN to compilation. Dependency fetch for `rust-webm` libwebm submodule at `chromium.googlesource.com` was blocked with CONNECT HTTP 403. No network/TLS bypass or dependency substitution was attempted. The isolated real core and real API selector compile/runtime results are separate evidence.

Schema compatibility: the new reader accepts older records without action. Older strict readers may reject new action fields; they must fail closed rather than export unvalidated records. No historical v1/v2 log file is imported.
