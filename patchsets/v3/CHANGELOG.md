# Patchset v3 changelog

Content revisions are independent of RustDesk versions. Legacy release allocations retain their original semantics.

## Current included features

### Common

- Configured server and client defaults, hidden connection-manager setting, and manual-only connection-manager visibility.
- Forced hardware rendering policy; latest-only custom repository updates with native immutable Release proofs, typed JSON package selection and size/SHA256 verification.
- Public display branding, About version/variant labels and Windows printer payload integration; native package identity is unchanged.
- Public RPM filenames use one OS/architecture selector, with a distinct SUSE family suffix; the v3 updater matches this normalized convention.
- Strict IPv6-primary API transport with an Actions-configured IPv4 HTTPS fallback, conservative no-replay rules and opportunistic recovery; existing native ID/Relay dual-stack behavior is unchanged.
- Default-hidden Android client Deploy UI with shared menu/prompt/dialog policy; backend/CLI unchanged.
- Optional unified typed diagnostic storage, shared Logs settings and sanitized native/Flutter/Rust adapters; complete runtime acceptance is pending.
- Strict-TLS WSS primary/fallback handshake for the verified own ID/same-host relay, independently selected from frozen HTTPS API origins; peer relays are never redirected.

### Sos

- SOS built-in mode with simplified desktop home and restricted settings tabs, layered over Common.

## Revision history

### v3.8 — content-change

Scope: common

Reason: Implement an owned-host WSS fallback handshake with strict certificate validation; preserve independent HTTP API transport behavior.

#### Added

- Add a frozen-primary/fallback WSS transport selector for owned ID and same-host relay handshake endpoints.

#### Changed

- Build-source preparation now injects WSS domain constants from the immutable HTTPS origin snapshot; patch application routes the new Common patch to hbb_common.

#### Fixed

- Prefer WSS for the compiled own HTTPS primary when no runtime API server is configured, avoiding HTTP 301 on WS.

#### Removed


#### Security

- Reject permissive TLS certificate retries on managed WSS endpoints; do not fail over on TLS, HTTP or protocol errors.

#### Compatibility


References: https://github.com/billradar/rustdesk-custom/pull/269

Upstream compatibility: RustDesk 1.5.3 locked hbb_common fae47e024dd83cef6aaecde0aa7d11731df11649. Common applies to Standard and SOS; archived v1/v2 remain unchanged.

Known limitations: Draft: native compilation, actual DNS/proxy/TLS WSS harness and Android real-device failover remain unverified. Only the default WSS port 443 and an owned endpoint matching the frozen primary host are eligible; hostname fallback shares the same origin Nginx.

Allocation base: `c027a877d4463d6fe1e1533248917d45d1bcd07d`

- common: `89aa4fdb04c4c2dd42a25332f9084d437d57d20b0b04d7eb483a5b001f4c56cd` → `4c5c33a4f18537e61459a995f1c837d432eabd7f514c5a48f910f2720810e889`
- sos: `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813` → `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`

### v3.7 — content-change

Scope: common

Reason: Introduce one optional typed diagnostic store and shared settings page for v3, with bounded asynchronous capture and pre-write privacy enforcement.

#### Added

- Add a shared Logs settings page with level, schedule, file/total limits, retention, viewer, pinning, confirmed cleanup and local export.
- Add a typed NDJSON engine with a bounded nonblocking capture queue, process file locks, rotation, quota protection and allowlisted export metadata.
- Add Rust 1.75 runtime/privacy/concurrent-process tests and read-only three-platform diagnostic compatibility CI.
- Add poll-scoped local session correlation, typed module/action hooks and actual local-TLS request/body privacy and association tests.

#### Changed


#### Fixed


#### Removed


#### Security

- Omit arbitrary Rust/third-party messages, Flutter debug/error text and Android native messages before app-managed persistence. Keep endpoint and session identifiers as per-recording HMAC pseudonyms.
- Record typed WebSocket transport/port/route/status events without changing TLS, redirects or retry policy.

#### Compatibility


References: 83bbff7a047eae5a2fdc57026c779050c02c8063, https://github.com/billradar/rustdesk-custom/pull/266

Upstream compatibility: v3 Common is shared by Standard and SOS. Exact Profile routing, archived v1/v2 bytes, signing, package identity, native connection policy and production workflows are unchanged.

Known limitations: Draft acceptance remains open. Typed module hooks and local poll/thread session correlation are implemented and runtime-tested in isolation; full client/module execution, Flutter rendering, Android JNI/SAF and physical devices remain unverified. Cross-process matching is not inferred.

Allocation base: `83bbff7a047eae5a2fdc57026c779050c02c8063`

- common: `e15c571660b4df61b229862707606ffc879ebdae32fa9b5fd835e3722ab25854` → `89aa4fdb04c4c2dd42a25332f9084d437d57d20b0b04d7eb483a5b001f4c56cd`
- sos: `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813` → `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`

### v3.6 — content-change

Scope: common

Reason: Hide client-visible Android device deployment entry points with one v3 UI policy while retaining provisioning APIs and CLI.

#### Added

- Add a shared v3 Dart deployment UI policy, disabled by default.

#### Changed

- Omit the Android settings tile and automatic prompt handler; guard both dialog entry functions.

#### Fixed

- Prevent server-triggered or direct dialog paths from re-exposing hidden deployment UI.

#### Removed


#### Security

- Retain backend deployment authorization; do not bypass server provisioning requirements.

#### Compatibility

- Preserve install/update/service/network/file-transfer behavior, all native deployment APIs and CLI, archived v1/v2 and signing/release mechanisms.

References: https://github.com/billradar/rustdesk-custom/pull/265

Upstream compatibility: v3 Standard/SOS only; exact 1.5.3 and existing maintained-profile compatibility routing. No Rust bridge changes.

Known limitations: Rendered Android UI and full native packages require device/build validation; desktop Deploy UI is not applicable. Server-side deployment requirements are not bypassed.

Allocation base: `290b2a4672ac4b5db8a6b724e1f1a51f7186ea57`

- common: `b32900b86d1b1fea1b00e50cd90c6b81f6ce0b4486fa8ba55e04dfefed972680` → `e15c571660b4df61b229862707606ffc879ebdae32fa9b5fd835e3722ab25854`
- sos: `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813` → `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`

### v3.5 — content-change

Scope: common

Reason: Add an isolated strict IPv6-primary API transport with safe IPv4 HTTPS fallback without changing historical builds.

#### Added

- Use strict HTTPS API fallback with a 60-second recovery cooldown, bounded DNS/connect/request budgets and no-auth recovery HEAD probes.

#### Changed

- Route managed Flutter API, background synchronization, OIDC and recording transport through one endpoint policy; keep logical account identity at the primary origin.

#### Fixed

- Use unique non-transmitted polling fragments for concurrent managed Flutter HTTP requests and consume their terminal responses.
- Handle HTTPS IPv6-literal origins directly as IPv6 socket addresses, preserving strict IP certificate verification and recovery instead of attempting bracketed-name DNS.
- Feed primary response-body failures into cooldown without replay; preserve primary attempts with explicit proxies; share DNS/connect budget (2s) and use 15s cooldown.
- Preserve a frozen explicit proxy for recording HEAD and upload; never pin the proxy peer as an origin address. Verify with direct and IPv4/IPv6 CONNECT tests.

#### Removed


#### Security

- Never replay HTTP statuses or uncertain post-connection operations; bypass upstream certificate relaxation and raw-TCP replay for the managed origin.
- Make nested TLS InvalidData failures terminal rather than conceal certificate/negotiation errors through fallback.
- Propagate terminal TLS errors from recovery HEAD probes to the initiating API/recording operation; never conceal them by sending that operation to fallback.

#### Compatibility

- Read and freeze v3 API origins from Actions Variables into prepared source; bind both rendered policies and the snapshot digest to the verified source inventory.

References: https://github.com/billradar/rustdesk-custom/pull/261

Upstream compatibility: v3 only; official 1.5.3 and compatibility-test-only later sources retain active Profile routing. Legacy v1/v2 bytes are preserved in archives, but all new builds using them are forbidden. Production signing requirements and existing server fingerprint fields remain unchanged.

Known limitations: Connection-level 250ms racing is blocked by the supported reqwest preconnect/pool interface; serial fallback remains. Pool reuse, nonblocking recovery and complete application/platform/OIDC/upload validation remain pending. See PR #261 race audit.

Allocation base: `7e346edef8914045d07bfbf0762f9bc0a445c06a`

- common: `972dc3b04e6854bb5ebddd594e495892b0c0fdcc22392746433fd709d9856e67` → `b32900b86d1b1fea1b00e50cd90c6b81f6ce0b4486fa8ba55e04dfefed972680`
- sos: `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813` → `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`

### v3.4 — content-change

Scope: common

Reason: Use GitHub native immutable Release attestations as the sole client update proof and remove the custom public bundle.

#### Added


#### Changed

- Verify GitHub native Release v0.2 proofs using the dedicated GitHub CA and signed TSA evidence.

#### Fixed


#### Removed

- Remove release-attestation.json from new public Release inventories; retain SLSA build evidence internally for Draft qualification.

#### Security

- Bind numeric repository/owner/Release identity, exact tag Git object, manifest digest and complete installer inventory before matching or download.

#### Compatibility


References: https://github.com/billradar/rustdesk-custom/commit/3f9dd6aa54942a23e6249e44ccff0b32582aacec

Upstream compatibility: Official 1.5.3 source and Rust 1.75 verifier; historical v1/v2 and v3.1-v3.3 content is preserved.

Known limitations: Fresh immutable schema-v2 publication, full native package builds and device upgrade validation remain required.

Allocation base: `3f9dd6aa54942a23e6249e44ccff0b32582aacec`

- common: `2fc6754d391c850ecc5e92b6494965684792dadd9ef14e3cfb44280aba3e4269` → `972dc3b04e6854bb5ebddd594e495892b0c0fdcc22392746433fd709d9856e67`
- sos: `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813` → `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`

### v3.3 — content-change

Scope: common

Reason: Move current-generation client updates and release reuse to one attested JSON inventory so human release notes no longer carry machine identity.

#### Added


#### Changed

- Select updates by signed OS, architecture, Standard/SOS variant, ordinary/Wayland flavor and installer format instead of predicting filenames.

#### Fixed

- Detect the package manager owning the running executable, using the unattended Wayland Debian identity for that flavor, and distinguish installed Windows MSI clients from portable clients.

#### Removed


#### Security

- Verify the manifest using offline Sigstore certificate, transparency-log and provenance checks before selecting or downloading an installer.

#### Compatibility

- Manual upgrade is required for older clients; this generation requires the new attested JSON release format.

References: 19783a6fd5d3fa02a676532b5ec4aa056d937cbc

Upstream compatibility: Targets official 1.5.3 with a local path verifier crate; preserves historical v1/v2 patches and v3.1/v3.2 content histories. Complete native workspace builds require hosted CI.

Known limitations: Native builds on all targets, generated bridge, Flutter analysis, device upgrades, runtime UI and remote sessions require fresh validation; existing clients need a manual upgrade.

Allocation base: `19783a6fd5d3fa02a676532b5ec4aa056d937cbc`

- common: `8fdc855986c8c21e9b4a42f269d4e57fa9eca0d12d6fe4b60be154d1b7a859e3` → `2fc6754d391c850ecc5e92b6494965684792dadd9ef14e3cfb44280aba3e4269`
- sos: `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813` → `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`

### v3.2 — content-change

Scope: common

Reason: Remove redundant RPM release/architecture suffixes from public assets and synchronize the v3 client package selector for every Standard/SOS and x86_64/ARM64 RPM family.

#### Added


#### Changed


#### Fixed

- Use one OS/architecture prefix in all v3 RPM and SUSE RPM asset names and match those exact names in the v3 updater.

#### Removed


#### Security


#### Compatibility

- Keep v1/v2 RPM naming unchanged; do not rename historical v3.1 assets or change RPM internal package identity.

References: c1d6942ee173979a8d73c393a7ceb12abda20186

Upstream compatibility: Official RustDesk 1.5.3 source 95cca3f661f635b3cc85c04935fe8d96d8f432ef uses v3.2. v1/v2 retain their legacy public RPM naming and immutable patch bytes. Existing v3.1 Draft assets remain unchanged.

Known limitations: Old RPM clients with fixed legacy filename selectors require manual upgrade to v3.2 or later before consuming normalized RPM names. Native RPM installation and device upgrades are not tested. Client consumption of the attested JSON manifest remains separate.

Allocation base: `c1d6942ee173979a8d73c393a7ceb12abda20186`

- common: `5ea2ba8cc9c55e7e85dde4c6a79dd1e6a934e5d80583e26283a635f74e323f93` → `8fdc855986c8c21e9b4a42f269d4e57fa9eca0d12d6fe4b60be154d1b7a859e3`
- sos: `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813` → `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`

### v3.1 — migration-baseline

Scope: common, sos

Reason: Create an isolated candidate patch generation derived from v2 revision 8; retain the complete upstream DPI-aware CM resize branches.

#### Added


#### Changed


#### Fixed


#### Removed


#### Security


#### Compatibility

- Rebase only the CM chat-window visibility hooks around upstream Windows monitor/DPI-aware bounds handling. All other Common and SOS patch bytes are inherited from v2.8.

References: https://github.com/billradar/rustdesk-custom/pull/247

Upstream compatibility: Candidate source 05b9f2d8919b5cdfaa0bb3280601a02881556a42 reports 1.5.3; this is not a release tag or Stable approval.

Known limitations: Native builds, generated bridge, Flutter analysis, runtime UI and remote sessions require fresh validation.

Allocation base: `3c53d9e5677b6a322be7d195f1c40b04ef2707e4`

- common: `5ea2ba8cc9c55e7e85dde4c6a79dd1e6a934e5d80583e26283a635f74e323f93` → `5ea2ba8cc9c55e7e85dde4c6a79dd1e6a934e5d80583e26283a635f74e323f93`
- sos: `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813` → `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`
