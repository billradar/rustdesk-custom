# v3 WebSocket scheme fix — implementation contract (draft)

Status: v3.8 Common candidate runtime patch committed (0010-hbb-wss-primary-fallback.patch). Exact-source hunk context independently checked against locked hbb_common fae47e0 + existing 0001; GitHub CI and real-device acceptance remain pending.

## Observed failure
With `allow-websocket=Y`, an ID server endpoint `<host>:21116` is converted by upstream `hbb_common::websocket::check_ws` into `ws://<host>/ws/id` when `Config::get_option("api-server")` does not start with HTTPS. A reverse proxy redirects HTTP to HTTPS (301); the WebSocket handshake fails. The compiled API default in `src/common.rs::get_api_server_` does not automatically populate the runtime option.

## Existing configuration (no new Actions variable)
- `RUSTDESK_ID_SERVER`: authoritative own rendezvous host.
- `RUSTDESK_API_SERVER`: compiled primary HTTPS API origin.
- `RUSTDESK_API_FALLBACK_SERVER`: fallback HTTPS origin, frozen by `scripts/source/api_policy.py`; WSS may reuse its hostname **only when verified as an owned WSS endpoint**. The existing HTTP API fallback implementation remains unchanged.
- `allow-websocket`: on/off only.

## Implementation rules
1. Preserve `use_ws()` behavior. Preserve already-qualified `ws://` or `wss://` endpoints, IP endpoints, custom `websocket-port`, and unrelated third-party relay hosts.
2. Prefer an explicit nonempty runtime `api-server` for existing upstream scheme behavior; never silently override an explicit HTTP API.
3. When runtime `api-server` is empty, allow a **compile-time HTTPS primary** to select WSS **only for the configured own rendezvous host**, after normalized hostname comparison. Do not use substring or suffix matches.
4. If an own relay host differs from the rendezvous host, do not assume it supports TLS merely because the API is HTTPS. Require explicit proof/configuration before changing its scheme; otherwise preserve upstream behavior.
5. For the verified own ID/relay endpoints, derive candidate WSS origins from frozen primary/fallback HTTPS origins (`https` -> `wss`), retaining `/ws/id` or `/ws/relay`. Do not treat the HTTP API failover state as the WebSocket health state; never redirect unrelated peers or third-party relays. If the configured ID/relay host is not the frozen primary host, preserve upstream behavior unless an explicit ownership mapping is verified.
6. Attempt fallback only for eligible pre-handshake connectivity failures (DNS/TCP/timeout and carefully classified TLS transport failures); never mask certificate validation errors, authentication failures (401/403), redirects (301/302/307/308), or protocol incompatibility. A successful HTTP API response is not evidence of a successful WSS handshake. Existing sessions must not be migrated or dropped when primary recovers. Do not follow a WebSocket HTTP 301 automatically. Log scheme, endpoint role, status class and redacted cause; never log tokens, keys, URL queries or raw redirect locations.
7. Only v3 Common changes; do not touch archived v1/v2. Allocate a new v3 patch revision with correct patchset hashes/history and source identity. Do not release or sign until source, CI, and real-device validation pass.

## Tests required
- Empty runtime API + compiled HTTPS primary + own ID host => wss:///ws/id.
- Explicit HTTP API => upstream ws behavior.
- Explicit HTTPS API => upstream wss behavior.
- API primary unreachable and fallback selected for /api/ => WSS state remains independent; the own ID host uses primary unless its own handshake fails.
- Own ID primary WSS DNS/TCP failure => one fallback WSS handshake on frozen fallback hostname; verify expected `/ws/id` and protocol registration.
- Own relay primary WSS connectivity failure => fallback `/ws/relay` only if the relay is explicitly verified as owned and equivalent; preserve peer-supplied relay destinations.
- Different fallback API hostname => route only eligible owned WSS paths, never arbitrary ID/relay endpoints.
- Both endpoints fail => bounded error, no infinite retry; primary recovery affects new connections only.
- 301, TLS certificate mismatch, 401/403, 5xx, malformed Upgrade => classified and tested without blind fallback.
- Third-party relay, own relay on distinct host, IP address, explicit ws/wss, nonstandard websocket-port, disabled WebSocket => preserved behavior.
- Reproduce HTTP 301 on WS; validate WSS handshake against a local TLS test server, including certificate validation.
- Both Standard and SOS source preparation, patch hash/content-version contracts, Android native compile and real remote session.

## Critical verification before code change
Inspect the **locked hbb_common submodule revision** in the official 1.5.3 source snapshot and the final patched `src/websocket.rs` after existing v3 Common patches. Verify whether the compiled primary can be accessed safely inside hbb_common without creating a circular dependency; prefer a build-time constant passed to hbb_common if necessary. Confirm that ID and API hosts match before assuming WSS is available.

## User-supplied Nginx evidence (2026-11-18)

Both `rustdesk.houxnan.com` and `rustdesk-backup.houxnan.com` are named in one TLS-enabled Nginx server block listening on IPv4/IPv6 port 443. HTTP port 80 is redirected to HTTPS with 301. The included `/www/sites/rustdesk.houxnan.com/proxy/*.conf` files are not present in the supplied excerpt; the user states that primary and backup WSS are verified. The shared server block does **not** prove distinct backend fault domains or establish per-path WebSocket Upgrade results, and the certificate SAN must cover both names.

## Runtime acceptance gates

1. Read the locked upstream 1.5.3 hbb_common source and v3 patched `src/websocket.rs` before implementing. Confirm where connection lifecycle and retry policy can be safely inserted without modifying arbitrary peer endpoints.
2. v3 Common patch, source-policy generation and v3.8 patchset version/hash/history are committed. Verify with the project's native contract tools and GitHub CI before acceptance.
3. Validate patch application for Standard and SOS, transport unit tests, certificate/SNI/Host/Upgrade behavior, and Android actual connection registration.
4. No automatic merging, signing, publication, or server changes. This contract alone is not a working fix.

## Security blocker found in upstream hbb_common websocket connector

Read-only inspection of `rustdesk/hbb_common/src/websocket.rs` (current upstream, not yet verified against locked 1.5.3 submodule) shows `WsStream::try_connect` retrying with `danger_accept_invalid_cert = Some(true)` after rustls failure and then trying native TLS. This can turn a certificate failure into a successful connection without ordinary PKI verification. **A WSS failover feature must not call that permissive retry path**. First establish an explicit strict-TLS connection method, or prove the locked submodule's implementation is different. A permissive TLS cache must not be reused for failover candidates.

## Concrete candidate selection contract

- Eligibility: `allow-websocket` enabled; an unqualified endpoint whose normalized hostname equals the frozen primary API hostname and belongs to the configured own ID server or a verified own relay; neither a peer-supplied relay nor arbitrary IP address is eligible.
- Derivation: frozen `https://primary[:port]` and `https://fallback[:port]` become `wss://primary[:port]/ws/id` and `wss://fallback[:port]/ws/id` respectively (or `/ws/relay` for a verified own relay). Explicit runtime WS/WSS URLs and explicit custom port configuration must not be silently overwritten.
- API and WSS state machines are independent. Do not copy API's 15-second cooldown without testing WebSocket connection lifecycle. Cache WSS preference only per verified endpoint role and logical identity; never persist fallback as a user's configured ID server.
- One primary attempt, at most one fallback attempt per new logical connection; bounded deadlines and cancellation. No application-level message replay before registration is proven idempotent.
- Failover classification: DNS failure, connect refused/unreachable, or bounded connect timeout can trigger fallback; TLS certificate errors, TLS alerts of uncertain cause, HTTP redirects, 401/403, malformed 101 Upgrade and application protocol errors must not. Avoid classifying only from a stringified anyhow error.
- Successful fallback must preserve the original logical rendezvous identity and key/authentication policy; do not replace or rewrite configured server keys, account origins or tokens.
- Primary recovery: only future new connections or explicit reconnects may migrate. Existing healthy connections stay attached.
- Separate common infrastructure failure: both hostnames may share one Nginx and RustDesk backend; hostname fallback covers path/IPv6 problems, not origin outages.

## Verification matrix and exit criteria

| Case | Expected |
| --- | --- |
| Primary IPv6 unreachable, fallback IPv4 WSS 101 | fallback selected and protocol registration completes |
| Primary HTTP 301 | report scheme/proxy misconfiguration, do not auto-follow |
| Primary TLS wrong SAN, expired certificate, untrusted CA | fail closed, never retry insecurely |
| Fallback TLS wrong SAN | fail closed, no connection |
| Primary HTTP 401/403 or malformed Upgrade | no failover |
| API primary down, WSS primary healthy | WSS remains primary |
| WSS primary down, API primary healthy | only WSS falls back |
| Peer-supplied relay address | unchanged, never replaced with API fallback |
| Explicit ws/wss URL, IP endpoint, websocket-port | existing behavior preserved unless explicitly covered by verified owned mapping |
| Fallback fails or times out | finite error, no reconnect storm |
| Primary recovers while fallback session healthy | no forced disconnect |
| Concurrent ID/Relay connection attempts | no duplicated registration or cross-role health contamination |
| Explicit SOCKS/HTTP proxy | same proxy, SNI, Host and TLS verification; no unintended direct bypass |
| Standard/SOS prepared source | patch applies cleanly; content hash and version history pass |
| Android real device | WSS handshake and authenticated ID/Relay session proven by redacted logs |

**Release gate:** do not mark Ready for Review based on policy-only tests. Require actual patched hbb_common compilation, a deterministic local TLS/WSS harness and real-device confirmation. No production server changes, CI publishing, signing or merging as part of this audit.

## Implemented candidate scope (not proof of runtime success)

- `patchsets/v3/common/0010-hbb-wss-primary-fallback.patch` adds strict WSS handshake primary/fallback for exact owned host and default HTTPS/WSS 443 origin pair; no shared API health state and no transport retry after WebSocket handshake.
- `scripts/source/apply_patches.sh` explicitly routes 0010 to the locked `libs/hbb_common`; `scripts/source/api_policy.py` generates and verifies the same frozen origin policy in the hbb submodule.
- `scripts/validation/api_policy_contract.py` now checks generated hbb file tampering; `scripts/validation/wss_failover_policy_contract.py` is run by compatibility CI.
- Explicit limitations: no WSS IP-family forcing, no cross-host peer relay failover, no subprotocol-level session reconnection, no automatic migration of healthy sessions. TLS, HTTP and protocol errors fail closed.
