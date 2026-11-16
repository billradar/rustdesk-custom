# PR #261 connection-race audit

Read-only baseline: `d353a4d747d50c8c6eed352eaf28faeff25b6308`, branch `audit/ipv6-api-failover-review`, Draft PR #261. Audited 2026-11-16 before runtime edits. This report supersedes earlier delivery claims for the new race acceptance criteria.

## Confirmed baseline

| Path / symbol | Actual behavior | Assessment |
| --- | --- | --- |
| v3 `0007-api-failover.patch`, `api_failover::send_for`, `client` | Serial primary send, then fallback only for setup / `is_connect` failures; new Client each time; primary DNS 3s plus connect 3s; 12s request timeout | Implemented serial failover; no 250ms race, no retained pool |
| `State`, `unavailable`, `use_primary` | Mutex/generation shared state; 60s cooldown; caller awaits no-auth HEAD recovery; any HTTP response healthy | Partial recovery; probe blocks initiating request; lease bounds cancellation but no background task |
| `client` proxy branch | Explicit proxy causes unconditional primary rejection | Violates new prohibition on environment-based selection |
| `common::post_request_http`, `http_request_http` | Body consumed after selector returns Response; body failures never update selector | Confirmed current-head review defect (P2) |
| `send_for` error classification | All `is_connect` failures may fall back, including certificate verification errors | Security visibility gap; strict verification alone does not prevent hiding a broken primary certificate |
| `common::http_request_sync`, `post_request_sync` | Current-thread Tokio runtime created per synchronous call | A global async Client alone cannot safely supply persistent live pooling across these runtime lifetimes |
| `flutter/lib/utils/http_service.dart`, `ui_interface::get_async_http_status` | Managed requests go through existing Rust bridge; unique polling fragment consumed on terminal read | Implemented; fragment excluded from HTTP; web excluded |
| `hbbs_http/account.rs`, Flutter `user_model.dart` | OIDC auth/query and currentUser share managed HTTP wrappers; logical account/API identity remains primary | Source inspected; real OIDC/backend token integration NOT RUN |
| `hbbs_http/record_upload.rs`, `recording_endpoint` | HEAD selects endpoint before a separate blocking streaming request; no upload replay | Partial common policy; does NOT reuse the probed connection, not TLS connection racing |
| `prepare-source.yml:117-119`, `source/api_policy.py:resolve/sources`, `prepared_source.py` | Actions public variables validated and frozen before variant fork; rendered Rust/Dart plus digest inventoried and verified; Standard/SOS digest equality checked | Implemented; missing fallback explicitly disables feature; no production host in patch |
| `api_failover_transport.py`, fixture `scenarios.rs` | Actual patched module + pinned reqwest with hbb_common facade; local trusted/untrusted TLS, body/request loss, no-auth HEAD, origin and concurrent-send counts | Runtime tests, but NOT deterministic race timing tests or full application builds; proxy helper mocked |

The complete PR diff also archives v1/v2 and blocks new builds. Those previously authorized changes are outside this follow-up and remain unchanged. ID/Relay remain outside scope. Public Variables read/write was denied by GitHub integration (403); actual repository values UNKNOWN.

## Blocking library boundary (high)

Pinned upstream dependency is reqwest **0.12.28** (`Cargo.lock`; root `Cargo.toml` reqwest 0.12). Its public `Client` request/execute methods start HTTP operations; it exposes no preconnect/connection lease/pool insertion API. `async_impl/client.rs:2449-2458` exposes `connector_layer`, but its service request/response are `connect.rs` private-module `sealed::Unnameable` / `Conn`. `Unnameable` contains a private URI (`connect.rs:1290`); a generic layer can observe completion/cancel the existing connect, but cannot simply redirect this opaque request to another origin with correct TLS identity. The connector is also bypassed on healthy pool hits.

Library source: [client.rs at v0.12.28](https://github.com/seanmonstar/reqwest/blob/v0.12.28/src/async_impl/client.rs), [connect.rs](https://github.com/seanmonstar/reqwest/blob/v0.12.28/src/connect.rs). This is a limitation of the supported interface, not a claim that arbitrary private-type interception is mathematically impossible.

Racing two `send()` futures risks both writing business bytes. Racing two HEAD responses chooses response latency, not TLS readiness, and does not transfer the selected connection. A type-erased private connection handoff between preparation/business clients would introduce connection ownership, pool-miss sentinels, cancellation coordination and runtime migration rather than reuse a supported interface. It is intentionally NOT implemented. No 250ms timer is added to give a false impression of connection racing. A supported reqwest upstream preconnect/custom connector handoff, or an explicitly reviewed larger transport adaptation, is needed to meet all requested constraints together.

## CI at audited head

- API transport run [43911771564](https://github.com/billradar/rustdesk-custom/actions/runs/43911771564): Linux x64, Windows x64, macOS runner standalone module PASS.
- Patch/build compatibility [43911771578](https://github.com/billradar/rustdesk-custom/actions/runs/43911771578): contracts, Standard/SOS source, updater checks, bridge generation and Flutter analysis PASS; Windows helper and documentation-only jobs SKIPPED.
- Action runtime [43911771535](https://github.com/billradar/rustdesk-custom/actions/runs/43911771535): PASS.
- Full Windows/Linux/macOS/Android application builds, ARM variants, real OIDC/refresh/upload lifecycle: NOT RUN. These green checks do not certify those targets.

## Minimal follow-up scope and risks

Fix body-read feedback without replay; classify TLS invalid-data as terminal security/negotiation failure conservatively; use actual connection outcomes even with configured proxy; reduce connect target to 2s and cooldown to 15s; bound DNS+connect preparation with a single deadline. Keep existing APIs/build snapshot/variants/archive unchanged. Tests must add body truncation and stall, security-terminal certificates, all requested HTTP error statuses, immediate failures, and explicit timing assertions for the serial limits. Recovery remains synchronous; persistent pool, nonblocking recovery, limited backoff and the 250ms connection race remain NOT IMPLEMENTED. No claim of Ready for Review against the new acceptance criteria.

## Follow-up implementation and local evidence

`0007-api-failover.patch` changes only the current v3 candidate revision:

- `client`: 2s shared DNS+TCP/TLS preparation budget; explicit proxy still attempts primary, with DNS/TLS delegated to reqwest. No environment probing or new Variables/dependencies.
- `tls_security_error`, `send_for`, `recording_endpoint`: nested `io::Error::get_ref` traversal preserves TLS InvalidData classification. Such errors terminate rather than send to fallback. This conservatively also stops some non-certificate TLS negotiation failures.
- `read_text` / `read_text_for`, both managed `common` body consumers: truncated/stalled primary response changes shared state for subsequent operations; current operation is never replayed.
- `COOLDOWN`: 15s. Existing generation guards and no-auth HEAD remain; this is still caller-driven synchronous recovery, not the requested background recovery.
- `api_failover_transport.py` / `scenarios.rs`: add accepted-POST body truncation/stall, cert-security terminal behavior, 429/502/504, 15s remaining-cooldown assertion and HEAD 404/405 recovery. TLS counters assert no fallback operation for the failed current request, followed by a distinct next request using fallback.

Local Rust 1.75 and installed stable actual-source TLS tests + Clippy PASS (`transport-msrv-results.json`, `transport-results.json`, source/fixture/runner digests recorded). Formatting of selector PASS. Standard/SOS exact 1.5.3 patch application, structural contracts and native configuration helper compile PASS (`race-source-results.json`); not a complete product compile. API policy (3), Profile (10), retirement (3), content-version (11) contracts and content verification PASS. Actionlint 1.7.12 PASS. Follow-up diff leaves archived bytes, retirement metadata and all workflow files unchanged.

| Requested scenario | Current evidence / status |
| --- | --- |
| Primary 50ms / 200ms / 500ms, delayed fallback at 250ms, simultaneous TLS winners | NOT IMPLEMENTED / NOT RUN; no connection racing interface |
| Missing primary AAAA, DNS failure, TCP refusal, TLS blackhole | Local actual TLS serial fallback PASS; blackhole bounded (<5s integration assertion including fallback), not 250ms takeover |
| Primary/fallback selected | Local IPv6/IPv4 remote-address, Host and authorization assertions PASS |
| HTTP 401/403/429/500/502/503/504 | PASS; no fallback business operation |
| Request accepted then response lost; body truncated/stalled | PASS; no replay; body failures cool down future requests |
| Both unavailable | Serial error PASS; no retry loop |
| Cooldown, concurrent recovery, HEAD 401/404/405, primary recovered | PASS; state expiry simulated; recovery HEAD has no authorization; business-send count equals logical-request count |
| Token refresh, OIDC login, streaming upload interruption | Shared route source audited; real backend/flow NOT RUN; no claim of full integration safety |
| Request cancellation, background/exit, client disposal, rapid network changes, pool leaks | Recovery lease source inspected; complete lifecycle runtime tests NOT RUN |
| Fallback variable empty | Policy contract PASS; disabled, no implicit address; full client run NOT RUN |
| Cooldown load storm, limited backoff | Basic concurrent selector test PASS; load/lifecycle/backoff NOT RUN / NOT IMPLEMENTED |
| Healthy pool/HTTP2 reuse | NOT IMPLEMENTED; per-request clients and per-call runtimes remain |
| Android ARM64/ARMv7/x64, Linux ARM64, macOS Intel/ARM64, Windows full clients, SOS packages | Full application builds NOT RUN; desktop standalone transport CI must be reported separately |

Residual **high**: requested connection racing/pooling/nonblocking recovery unavailable; PR remains Draft and NOT Ready for Review. Residual **medium**: real OIDC/token/upload/proxy/device lifecycle tests absent. Recording still probes and then opens a distinct connection. Follow-up review identified proxy-peer pinning: fixed by snapshotting the explicit proxy in `RecordingEndpoint`, using it for both HEAD and the production blocking upload client, and pinning only direct peers. Local IPv4/IPv6 CONNECT and direct upload tests now cover this exact client builder; real application proxy configuration parsing remains unverified. No new claim of unified streaming race semantics. Residual **operational UNKNOWN**: actual Actions Variables and production endpoint/backend compatibility. Native ID/Relay, archive policy and historical artifacts remain unchanged.


Follow-up review of `50e6fde` found recording proxy-peer pinning (P2). `RecordingEndpoint` now carries the selected URL, direct-only address and cloned explicit proxy. `client_with_proxy` and the recording client use the same snapshot; recording selection accepts a verified proxied TLS connection regardless of proxy peer address family. Added actual loopback IPv4/IPv6 HTTP CONNECT proxies and a direct control, testing the production blocking client, Host, authorization, single chunk and exactly one business operation at primary, none at fallback. This fixes transport configuration preservation; it does not add network-environment recognition or connection racing. Generic unavailable logging now covers response-body failures accurately.
