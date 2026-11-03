# Patchset v2 changelog

Content revisions are independent of RustDesk versions. Legacy release allocations retain their original semantics.

## Current included features

### Common

- Configured server and client defaults, hidden connection-manager setting, and manual-only connection-manager visibility.
- Forced hardware rendering policy; latest-only custom repository updates with exact package and API size/SHA256 checks.
- Public display branding, About version/variant labels and Windows printer payload integration; native package identity is unchanged.

### Sos

- SOS built-in mode with simplified desktop home and restricted settings tabs, layered over Common.

## Revision history

### v2.8 — content-change

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

Allocation base: `472ee22a3c4e0fea598a2ebe7de46b423eb78847`

- common: `ba803951d999a4feacf6d754e263f86ebcabd2f4b53d447abe413259b019416a` → `a9a8ef83aa02890f09beb19e0b4818b268d4d873362f9ccf7ee9b09d3415e5b0`
- sos: `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813` → `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`

### v2.7 — migration-baseline

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

- common: `ba803951d999a4feacf6d754e263f86ebcabd2f4b53d447abe413259b019416a` → `ba803951d999a4feacf6d754e263f86ebcabd2f4b53d447abe413259b019416a`
- sos: `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813` → `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`
