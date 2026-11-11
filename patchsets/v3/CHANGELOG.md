# Patchset v3 changelog

Content revisions are independent of RustDesk versions. Legacy release allocations retain their original semantics.

## Current included features

### Common

- Configured server and client defaults, hidden connection-manager setting, and manual-only connection-manager visibility.
- Forced hardware rendering policy; latest-only custom repository updates with exact package and API size/SHA256 checks.
- Public display branding, About version/variant labels and Windows printer payload integration; native package identity is unchanged.

### Sos

- SOS built-in mode with simplified desktop home and restricted settings tabs, layered over Common.

## Revision history

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
