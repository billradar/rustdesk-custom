# v3 WebSocket scheme fix — implementation contract (draft)

Status: design only; no runtime patch applied or CI passed.

## Observed failure
With `allow-websocket=Y`, an ID server endpoint `<host>:21116` is converted by upstream `hbb_common::websocket::check_ws` into `ws://<host>/ws/id` when `Config::get_option("api-server")` does not start with HTTPS. A reverse proxy redirects HTTP to HTTPS (301); the WebSocket handshake fails. The compiled API default in `src/common.rs::get_api_server_` does not automatically populate the runtime option.

## Existing configuration (no new Actions variable)
- `RUSTDESK_ID_SERVER`: authoritative own rendezvous host.
- `RUSTDESK_API_SERVER`: compiled primary HTTPS API origin.
- `RUSTDESK_API_FALLBACK_SERVER`: API-only fallback HTTPS origin, frozen by `scripts/source/api_policy.py`.
- `allow-websocket`: on/off only.

## Implementation rules
1. Preserve `use_ws()` behavior. Preserve already-qualified `ws://` or `wss://` endpoints, IP endpoints, custom `websocket-port`, and unrelated third-party relay hosts.
2. Prefer an explicit nonempty runtime `api-server` for existing upstream scheme behavior; never silently override an explicit HTTP API.
3. When runtime `api-server` is empty, allow a **compile-time HTTPS primary** to select WSS **only for the configured own rendezvous host**, after normalized hostname comparison. Do not use substring or suffix matches.
4. If an own relay host differs from the rendezvous host, do not assume it supports TLS merely because the API is HTTPS. Require explicit proof/configuration before changing its scheme; otherwise preserve upstream behavior.
5. API fallback is **not** an ID/relay fallback. Never redirect `/ws/id` or `/ws/relay` to `RUSTDESK_API_FALLBACK_SERVER` as a result of API failover. API transport state must not control WebSocket scheme selection.
6. Do not follow a WebSocket HTTP 301 automatically. Log scheme, endpoint role, status class and redacted cause; never log tokens, keys, URL queries or raw redirect locations.
7. Only v3 Common changes; do not touch archived v1/v2. Allocate a new v3 patch revision with correct patchset hashes/history and source identity. Do not release or sign until source, CI, and real-device validation pass.

## Tests required
- Empty runtime API + compiled HTTPS primary + own ID host => wss:///ws/id.
- Explicit HTTP API => upstream ws behavior.
- Explicit HTTPS API => upstream wss behavior.
- API primary unreachable and fallback selected for /api/ => WebSocket own ID host and scheme unchanged.
- Different fallback API hostname => no ID/relay rerouting.
- Third-party relay, own relay on distinct host, IP address, explicit ws/wss, nonstandard websocket-port, disabled WebSocket => preserved behavior.
- Reproduce HTTP 301 on WS; validate WSS handshake against a local TLS test server, including certificate validation.
- Both Standard and SOS source preparation, patch hash/content-version contracts, Android native compile and real remote session.

## Critical verification before code change
Inspect the **locked hbb_common submodule revision** in the official 1.5.3 source snapshot and the final patched `src/websocket.rs` after existing v3 Common patches. Verify whether the compiled primary can be accessed safely inside hbb_common without creating a circular dependency; prefer a build-time constant passed to hbb_common if necessary. Confirm that ID and API hosts match before assuming WSS is available.
