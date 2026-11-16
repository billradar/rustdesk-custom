# Android WebSocket / HTTPS 443 audit (no runtime fix)

Audit base: custom repository `290b2a4672ac4b5db8a6b724e1f1a51f7186ea57` (main after PR #261). Independent branch: `audit/android-wss-443`. **Actual installed APK identity and root cause are NOT CONFIRMED. No runtime patch is introduced.** The user explicitly requires an audit-only outcome when the incident cannot be attributed safely.

## Evidence and identity

No APK exists in the supplied workspace; no APK download URL, installed About/Build Identity, SHA256, device logs or actual saved API setting was supplied. A question requesting non-secret identity/configuration text is pending. Repository metadata or an available Release does not establish which APK is installed.

Reference source inspected (not an assertion about the installed APK): official RustDesk 1.5.3 `95cca3f661f635b3cc85c04935fe8d96d8f432ef`; verified clean tree and `libs/hbb_common` gitlink/checkout `fae47e024dd83cef6aaecde0aa7d11731df11649`. Profile `rd-1.5.3` selects v3. Current main v3 is revision 5; do not confuse that with packages built earlier.

Read-only GitHub Release metadata identifies these **candidates**, not the incident APK:

| Candidate | Published metadata observed |
| --- | --- |
| Draft `v1.5.3-custom.v3.1` | upstream `95cca3f…`; custom `c1d6942ee173979a8d73c393a7ceb12abda20186`; build identity `be27f15f4682731d654dab332fce6c93f932894c3d98aca7fff56d9def568a50`; prepare/build run `43146078797` |
| Draft `v1.5.1-custom.v2.8` | upstream `23e5bb471a040d62f0a6ad52591fb30784265b73`; custom `7431f341394f12ce930735e6c6552c95646c9006`; build identity `352b0b4a9e4912c01533b00bf57bb4b9acb7cc7d5edeaad594491b474072717c`; run `41759881917` |
| Draft Nightly | Android asset names indicate 1.5.3; body references successful run `43796320397`, custom SHA `7e346edef8914045d07bfbf0762f9bc0a445c06a`. This alone does not identify a specific installed binary or its upstream lock. |

Commands: `gh api repos/billradar/rustdesk-custom/releases`, `gh api repos/billradar/rustdesk-custom/actions/runs/43796320397`. Draft visibility is not public publication. No release/signing operation was performed.

The supplied server/Termux 101 and HTTP 301 results are **USER-VERIFIED**, not rerun by this audit. HTTPS can itself return an HTTP redirect, so the text “301” alone does not prove a plaintext connection.

## Source call chain

Links below pin the exact reference revisions; local paths are relative to the official source root, not this automation repository.

1. Android Flutter setting: [`flutter/lib/mobile/pages/settings_page.dart:794-805`](https://github.com/rustdesk/rustdesk/blob/95cca3f661f635b3cc85c04935fe8d96d8f432ef/flutter/lib/mobile/pages/settings_page.dart#L794). `mainSetBoolOption(kOptionAllowWebSocket, v)` calls [`flutter/lib/common.dart:1650`](https://github.com/rustdesk/rustdesk/blob/95cca3f661f635b3cc85c04935fe8d96d8f432ef/flutter/lib/common.dart#L1650), serializing an enabled `allow-` option as `Y`, then existing `mainSetOption` bridge. `kOptionAllowWebSocket` is `allow-websocket` (`consts.dart:198`).
2. [`src/flutter_ffi.rs:1024,1070-1087`](https://github.com/rustdesk/rustdesk/blob/95cca3f661f635b3cc85c04935fe8d96d8f432ef/src/flutter_ffi.rs#L1070): stores the option, restarts Android RendezvousMediator and tests rendezvous addresses; API-setting changes also restart it. [`hbb_common/src/config.rs:2938`](https://github.com/rustdesk/hbb_common/blob/fae47e024dd83cef6aaecde0aa7d11731df11649/src/config.rs#L2938) `use_ws()` reads that saved/default/overwrite option. `Config::get_option` precedence is overwrite → saved → defaults (`config.rs:1381`).
3. ID registration: [`src/rendezvous_mediator.rs:630-632`](https://github.com/rustdesk/rustdesk/blob/95cca3f661f635b3cc85c04935fe8d96d8f432ef/src/rendezvous_mediator.rs#L630) normalizes host to the rendezvous port, logs `start tcp: <check_ws result>` and calls `connect_tcp`. Controller requests also use `src/client.rs:826`. Plain UDP is a separate `start_udp` flow (`rendezvous_mediator.rs:407`), not an HTTP API request.
4. [`hbb_common/src/socket_client.rs:127-147`](https://github.com/rustdesk/hbb_common/blob/fae47e024dd83cef6aaecde0aa7d11731df11649/src/socket_client.rs#L127) `connect_tcp`: `check_ws(target)` → `WsFramedStream::new` for a WS endpoint, otherwise unchanged `connect_tcp_local`. `split_host_port` is at line 55. UI hostname validation and internal support for an already-built WS URL are different interfaces; do not tell users to paste `wss://` into an ID hostname field.
5. Relay: [`src/client.rs:1864-1871`](https://github.com/rustdesk/rustdesk/blob/95cca3f661f635b3cc85c04935fe8d96d8f432ef/src/client.rs#L1864) normalizes the actual relay address (including one supplied by the peer/server), applies proxy-aware handling, and uses the same `connect_tcp` conversion. Relay can have a different host; a successful ID handshake does not prove relay reachability.
6. [`hbb_common/src/websocket.rs:470-534`](https://github.com/rustdesk/hbb_common/blob/fae47e024dd83cef6aaecde0aa7d11731df11649/src/websocket.rs#L470) `check_ws`:
   - disabled or empty → unchanged; explicit internal `ws://` / `wss://` → unchanged;
   - rendezvous/online native ports → ID; relay/native fallback ports → relay;
   - domain → `/ws/id` or `/ws/relay`, default port determined by WS/WSS; own-server `websocket-port` override uses `websocket_port` at line 538;
   - numeric IPv4/IPv6 → original native WS port arithmetic (21118/21119 for default ID/relay); does not globally convert numeric native servers to WSS;
   - **domain scheme is chosen ONLY from `Config::get_option("api-server").starts_with("https")`**, not the effective app API resolver or a TLS attempt.
7. TLS/HTTP upgrade: [`websocket.rs:130-301`](https://github.com/rustdesk/hbb_common/blob/fae47e024dd83cef6aaecde0aa7d11731df11649/src/websocket.rs#L130): constructs the request from that URL; direct tungstenite connection or configured proxy tunnel; default WSS port 443 / WS port 80. A 3xx upgrade is reported as an error, not safely followed. Rustls/native TLS retries retain the original URL; they do not turn a confirmed WSS URL into WS. `TlsType::Plain` is selected for plaintext schemes by the TLS cache helper, not proof that this incident used it.
8. [`tls.rs:84-97`](https://github.com/rustdesk/hbb_common/blob/fae47e024dd83cef6aaecde0aa7d11731df11649/src/tls.rs#L84): when `allow-insecure-tls-fallback` is off, certificate acceptance is explicitly `Some(false)`. Upstream has optional insecure acceptance paths when the user enables that separate setting. This task does not enable, bypass or use them as a fix.

## API versus WebSocket; upstream versus custom

API HTTPS is `src/common.rs:get_api_server` / `get_api_server_` (reference lines 1270/1287); it is not the ID/relay socket. Explicit API configuration wins; a configured custom rendezvous may derive `http://host:21114`; otherwise the upstream default is `https://admin.rustdesk.com`. v3 `0002-client-defaults.patch` changes only that final API default to `env!("RUSTDESK_API_SERVER")`, and supplies unrelated custom defaults. It does **not** write that value into `Config::get_option("api-server")`. v3 `0001` changes the ID-server constant/key. `0007` handles HTTPS API failover, not ID/relay WS handshakes.

Search of all current v3 and archived v1/v2 patches found no modifications to `check_ws`, WS URL construction, or the WS connector. Therefore the scheme decision above is an upstream behavior, with a potentially relevant custom-default integration gap. It is **not** established as the installed APK's failure. A new global HTTPS default could also change explicit custom-server behavior and is not an evidence-free safe fix.

## Reproduction and root-cause status

Run `source "$HOME/.cargo/env"` then:

```sh
RUSTUP_TOOLCHAIN=1.75.0 CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse \
CARGO_TARGET_DIR=/tmp/wss-url-audit \
python3 docs/audits/android-wss-443/reproduce_url.py \
  /path/to/clean/locked/rustdesk-1.5.3 --output /tmp/wss-url-results.json
```

The script checks exact source/submodule identities and cleanliness, extracts the original seven URL/IP functions unchanged, and compiles them with a clearly labeled Config facade and pinned regex version. Results: **18 URL cases PASS**; hashes/compiler and individual outputs are in `url-results.json`. It does not replace actual configuration, network, TLS or Android integration tests.

| Same hostname/native input | Saved/default API option | Observed extracted function result |
| --- | --- | --- |
| `example.test:21116` | empty | `ws://example.test/ws/id` |
| `example.test:21117` | empty | `ws://example.test/ws/relay` |
| `example.test:21116` | `https://example.test` | `wss://example.test/ws/id` |
| `example.test:21117` | `https://example.test` | `wss://example.test/ws/relay` |

The same conditional applies to the incident hostname. With verified empty/HTTP API option and matching binary, it is a plausible explanation for the server's HTTP→HTTPS redirect. With a verified HTTPS option or `start tcp: wss://…` log, this explanation does not establish the failure; investigate the actual URL/path, relay hostname, redirect Location and proxy response instead. **No incident root cause is claimed.**

## Checks and limits

| Check | Result |
| --- | --- |
| Actual extracted URL functions, Rust 1.75 | PASS (18 cases): ID/online/relay, WS/WSS, IPv4/IPv6, native/custom ports, own-server reverse-proxy port, explicit internal URLs, WS-disabled TCP addresses |
| Existing v3 Standard/SOS apply/structure/config helper | PASS; `patch-results.json`; no new patch |
| Profile contract / v1-v2 retirement inventory | PASS (10 / 3 tests) |
| Full hbb_common `websocket::tests::test_check_ws` | BLOCKED BEFORE COMPILATION: workspace resolves rust-webm/libwebm, Chromium googlesource fetch gets CONNECT 403 |
| Actual local WS/WSS 101, HTTP 301, strict bad-certificate behavior, proxy tunnels, TCP/UDP traffic | NOT RUN in this audit; URL-only results cannot establish them |
| Android APK build | NOT RUN: no Flutter/Android SDK/adb available, and no justified runtime change to build |
| Android actual installed binary/session | NOT RUN / identity UNKNOWN |
| Related new PR CI | Report exact head/checks in PR; a documentation-only CI success is not Android compilation |

## Change scope, risk, next evidence

Only this report, URL audit reproducer and result records are added. No production domains are embedded in generic source, no version revision allocated, no shared build variables, runtime code, archived v1/v2 bytes or workflows changed. v2 Stable artifacts/signatures and archived content are unaffected; v1/v2 remain retired and are not maintained. No production access, TLS bypass, redirect acceptance, build signing, release or merge was performed.

**High uncertainty:** actual APK identity/configuration/logged target missing. **Medium compatibility risk for a speculative fix:** forcing WSS could break intentional WS, numeric endpoints, custom native ports or another relay host; filling a global API option could reroute independent API traffic. **Security constraint:** do not enable insecure TLS fallback to make a handshake pass.

Device verification steps (no server changes):

1. Record About version/custom revision/Build Identity, download run/link and APK SHA256; do not replace the installed APK without considering its signing identity and saved settings.
2. Keep ID hostname `rustdesk.houxnan.com`. Record the actual API field, relay override and WebSocket port (if present), plus explicit proxy configuration without credentials. Leave insecure TLS fallback disabled.
3. Export the existing client application log around one controlled reconnect. Capture `start tcp: …` (effective ID WS URL), relay connection error/host, timestamp and full 301/Location if available. Remove IDs, access tokens, passwords and authorization/cookie values before sharing.
4. Compare actual built URL with the source revision above. A WSS log plus 301 is not the empty-option/plain-WS case; do not apply a scheme-only patch.
5. Once causality is confirmed, add only a scoped v3 fix and run real WS/WSS 101, redirect rejection, bad-cert rejection, ID/relay, IPv4/IPv6, proxy/custom-port and ordinary TCP/UDP tests; build Android with test signing only.
6. Install the verified test package on a suitable test device and verify ID registration **and** an actual relay session over 443, app restart and WS-disabled native connectivity. Record this separately from compilation.

Until the missing evidence is available, remain at audit stage as requested.
