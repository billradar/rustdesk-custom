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
