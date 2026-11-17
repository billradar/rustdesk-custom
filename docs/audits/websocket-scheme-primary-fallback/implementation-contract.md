# v3 WebSocket scheme fix — implementation contract (draft)

Status: revised implementation contract for WSS primary/fallback; no runtime patch applied or CI passed.

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
2. Add v3 Common patch and source-policy generation changes; update `patchset.json` revision, content hashes, and append-only history with the project's existing versioning tool.
3. Validate patch application for Standard and SOS, transport unit tests, certificate/SNI/Host/Upgrade behavior, and Android actual connection registration.
4. No automatic merging, signing, publication, or server changes. This contract alone is not a working fix.
