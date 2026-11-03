# Patchset v1 changelog

Content revisions are independent of RustDesk versions. Legacy release allocations retain their original semantics.

## Current included features

### Common

- Configured server and client defaults, hidden connection-manager setting, and manual-only connection-manager visibility.
- Forced hardware rendering policy; latest-only custom repository updates with exact package and API size/SHA256 checks.
- Public display branding, About version/variant labels and Windows printer payload integration; native package identity is unchanged.

### Sos

- SOS built-in mode with simplified desktop home and restricted settings tabs, layered over Common.

## Revision history

### v1.2 — content-change

Scope: common

Reason: Separate content-version provenance from Stable update eligibility and reject ambiguous legacy release semantics during migration.

#### Added


#### Changed

- Record explicit content semantics and Patchset Version independently of the Stable revision; display Nightly/CI channel labels without granting Stable identity.

#### Fixed

- Reject unknown same-format legacy tags; require explicit modern content-version metadata to match the target Tag before offering an update.

#### Removed


#### Security


#### Compatibility

- Preserve old installed-build parsing and the two audited legacy Stable release identities; retain upstream numeric version priority and exact Standard/SOS/Wayland asset checks.

References: https://github.com/billradar/rustdesk-custom/pull/195, https://github.com/billradar/rustdesk-custom/pull/194

Upstream compatibility: The upstream selection boundary and numeric upstream-first update ordering are unchanged. Known legacy releases are recognized only by audited tag/source/hash mappings; unmarked unknown tags fail closed.

Known limitations: Production cutover remains blocked. No device installation or runtime remote-session test was performed; independent update signatures remain deferred.

Allocation base: `c91c406093320e3bfa5751e870d87b98f6e7e3fb`

- common: `9547414fe66d922c274256a2bb6b681b4458f597dbb1d322e99cdc5a38c03790` → `d27727be60dd73c4885bbd713caa89e470c895e46b05a41becd073ec86f6bba7`
- sos: `d752022800a8008b10aedd1a79412a00af027464b1754b068c35a0b5b439ea34` → `d752022800a8008b10aedd1a79412a00af027464b1754b068c35a0b5b439ea34`

### v1.1 — migration-baseline

Scope: common, sos

Reason: Establish an explicit content-version baseline without reinterpreting historical Stable release allocation numbers.

#### Added


#### Changed


#### Fixed


#### Removed


#### Security


#### Compatibility

- Metadata migration only: patch bytes are unchanged; this baseline does not claim new functionality or reconstruct missing historical revisions.

References: 2b871ad992a62fcac2d39b83e6ad045f3083b916

Upstream compatibility: Generation selection remains upstream <1.5.0 for v1 and >=1.5.0 for v2. Existing compatibility snapshots retain their original evidence scope.

Known limitations: Migration activation remains blocked until shared Coordinator identity and legacy reconciliation are reviewed. Runtime UI and remote sessions are not tested; independent update signatures are deferred.

Allocation base: `2b871ad992a62fcac2d39b83e6ad045f3083b916`

- common: `9547414fe66d922c274256a2bb6b681b4458f597dbb1d322e99cdc5a38c03790` → `9547414fe66d922c274256a2bb6b681b4458f597dbb1d322e99cdc5a38c03790`
- sos: `d752022800a8008b10aedd1a79412a00af027464b1754b068c35a0b5b439ea34` → `d752022800a8008b10aedd1a79412a00af027464b1754b068c35a0b5b439ea34`
