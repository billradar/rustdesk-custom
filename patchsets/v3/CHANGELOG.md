# Patchset v3 changelog

Content revisions are independent of RustDesk versions. Legacy release allocations retain their original semantics.

## Current included features

### Common

- Configured server and client defaults, hidden connection-manager setting, and manual-only connection-manager visibility.
- Forced hardware rendering policy; latest-only custom repository updates with attested JSON package selection and size/SHA256 verification.
- Public display branding, About version/variant labels and Windows printer payload integration; native package identity is unchanged.
- Public RPM filenames use one OS/architecture selector, with a distinct SUSE family suffix; the v3 updater matches this normalized convention.

### Sos

- SOS built-in mode with simplified desktop home and restricted settings tabs, layered over Common.

## Revision history

### v3.3 — content-change

Scope: common

Reason: Move current-generation client updates and release reuse to one attested JSON inventory so human release notes no longer carry machine identity.

#### Added


#### Changed

- Select updates by signed OS, architecture, Standard/SOS variant, ordinary/Wayland flavor and installer format instead of predicting filenames.

#### Fixed

- Detect the package manager owning the running Linux executable and distinguish installed Windows MSI clients from portable clients.

#### Removed


#### Security

- Verify the manifest using offline Sigstore certificate, transparency-log and provenance checks before selecting or downloading an installer.

#### Compatibility

- Manual upgrade is required for older clients; this generation requires the new attested JSON release format.

References: 19783a6fd5d3fa02a676532b5ec4aa056d937cbc

Upstream compatibility: Targets official 1.5.3 with a local path verifier crate; preserves historical v1/v2 patches and v3.1/v3.2 content histories. Complete native workspace builds require hosted CI.

Known limitations: Native builds on all targets, generated bridge, Flutter analysis, device upgrades, runtime UI and remote sessions require fresh validation; existing clients need a manual upgrade.

Allocation base: `19783a6fd5d3fa02a676532b5ec4aa056d937cbc`

- common: `8fdc855986c8c21e9b4a42f269d4e57fa9eca0d12d6fe4b60be154d1b7a859e3` → `4b1291600a87fe793969888f48be75dcbbeff295a27552e256b1d64f11ed35c7`
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
