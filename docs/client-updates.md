# Client updates

All custom clients query only
`https://api.github.com/repos/<owner>/<repo>/releases/latest`. The build embeds its
repository from `GITHUB_REPOSITORY`; fork clients follow their own repository.
There is no client Nightly channel, embedded token or official-server fallback.
Nightly-produced clients also check the latest published Stable release.

## Current generation: v3.3

Prepared source embeds repository name, numeric repository/owner IDs, upstream
version/SHA, Standard/SOS variant, content revision and prepare run before its
inventory is frozen. Missing identity disables checking. Stable receives its
reviewed revision from Tag preflight; CI/Nightly cannot invent a Stable revision.
About labels remain display-only; native package versions are unchanged.

The client downloads the exact `update-manifest.json` and
`release-attestation.json` assets from the published Stable API record. It checks
API IDs, canonical URLs, bounded sizes and SHA256, then verifies the manifest's
Sigstore proof natively with locked `sigstore-verify` 0.11.0. No `gh` executable or
shell is required on the user's computer. Public Sigstore roots are bundled;
certificate identity/issuer, certificate transparency and Rekor evidence remain
mandatory. Certificate claims bind the exact repository and numeric owner IDs,
main workflow/ref, custom source SHA, hosted runner and build run to SLSA v1
provenance. The signer must be this repository's `tag.yml` main-branch dispatch.

Only `rustdesk-release-manifest-v2` is accepted. The client compares the complete
installer API inventory with the verified manifest. Selection uses signed fields:
OS, architecture, Standard/SOS, ordinary/unattended-Wayland and installer format.
It never predicts a filename or selects a closest alternative. Missing, duplicate
or contradictory selectors stop checking. Release body content has no authority;
there is no body, schema-v1 or public SHA256SUMS fallback.

Linux determines which package manager owns the actual canonical running
executable using `dpkg-query -S` and `rpm -qf`. Ordinary Standard/SOS clients
require the internal package name `rustdesk`; unattended Wayland Standard/SOS
clients require `rustdesk-unattended-wayland`, including the installed-status
query. Display branding never determines package ownership. A missing/ambiguous owner requires
manual selection outside this updater. RPM distributions use exact `ID`/`ID_LIKE`
SUSE tokens; Wayland unattended builds require a managed DEB. Windows portable
clients select EXE; installed clients select MSI only when the installed MSI
identity is present. Registry errors other than missing identity fail closed.
macOS selects DMG; Android selects the current ABI's Standard APK.

Stable tags are compared numerically: upstream version, patch generation, then
revision. A higher revision cannot downgrade the upstream version. Non-release
clients may move to Stable at the same version only when upstream SHAs agree.

## Download and installer boundary

Immediately before download, refresh the latest release and require the entire
verified manifest and selected API asset to remain unchanged. Restrict HTTPS
redirects to GitHub delivery hosts, bound response sizes/timeouts, and verify the
installer's attested size/SHA256 after download and again before handoff. Failed
files are removed. The upstream official verifier remains separate.

Checking, downloading and opening the system installer remain explicit UI steps.
Unattended official/root installers stay disabled for custom builds. Windows
opens EXE/MSI, macOS opens the unsigned DMG, Linux opens the package handler and
Android uses a private-cache FileProvider URI. Android system consent and
production v2/v3 signature checks remain independent. Proof verification does not
establish device upgrade success, desktop signing or remote-session behavior.

## Direct cutover and validation limits

Historical v1/v2 revision 8 and v3.1/v3.2 patches/releases remain unchanged. Their
already-installed clients retain their old body/filename logic. Install v3.3 or
later manually to use the new format; no compatibility aliases or transitional
fallback are published. A historical schema-v1 Draft cannot be promoted by the
new verifier. An old Nightly object needs explicit migration review rather than
automatic deletion based on body markers.

Drafts are unavailable to ordinary clients. Hiding latest can expose an older
published release, but numeric/source comparison prevents downgrading. With no
compatible visible release the client reports unavailability and allows retry.

Run `scripts.validation.client_update_contract` and
`scripts.validation.update_manifest_native`, prepared-source checks and affected
release contracts. Native tests verify an actual historical CD Sigstore proof,
negative identity/tamper cases and all 31 typed selectors on Rust 1.75. The v2
schema parser fixture is unsigned and explicitly fails against the old proof.
Fresh schema-v2 hosted signing, full native workspace builds on every target,
Flutter analysis, device installation and real sessions still require validation.
See [Release attestation](release-attestation.md) and [RPM naming](rpm-asset-naming.md).
