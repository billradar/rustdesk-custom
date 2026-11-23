# Patchset v4 changelog

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

### v4.1 — migration-baseline

Scope: common, sos

Reason: Create an isolated SHA-specific v4 compatibility candidate without modifying v3 or approving Stable.

#### Added


#### Changed


#### Fixed

- Rebase hbb_common TCP/DNS/proxy diagnostic events onto the upstream 450cc1d7 error-preserving FramedStream implementation.

#### Removed


#### Security


#### Compatibility

- Retain upstream last_error and anyhow context; inherit other v3 Common/SOS patches provisionally until applicability is verified.

References: https://github.com/billradar/rustdesk-custom/pull/274

Upstream compatibility: Official RustDesk 9724512429b053be04cdb843345e99ddcccdb80e (1.5.3), hbb_common 450cc1d7b729cfa8d19b5a7527c9cc2fe54cf5eb; source patch checks and full builds pending.

Known limitations: No claim of whole patchset applicability, native compilation, Flutter/Android builds, generated bridge, packaging, TLS functionality or real remote sessions.

Allocation base: `54127ffd79e567c6c4b1d386a7d9770560ef395a`

- common: `47089990ecd806ca3ffe4b92c88cdd175186ba0f86480d6f2a6f5936731e604a` → `47089990ecd806ca3ffe4b92c88cdd175186ba0f86480d6f2a6f5936731e604a`
- sos: `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813` → `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`
