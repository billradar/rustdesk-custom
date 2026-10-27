# Wayland unattended builds inside Tag and Nightly

`wayland.yml` is now a **reusable internal workflow**, without a separate manual
entry point. `tag.yml` and `nightly.yml` call it with their own locked upstream
SHA, version, channel, patchset and same-run prepared Standard and SOS artifacts. Common
patch policy, including forced-off software rendering, is shared with the normal
builds. No second resolve/fetch/prepare occurs in the Wayland lane.

Both parent workflows expose `include_wayland` (boolean, default **true**).
It builds Standard and SOS DEBs on native amd64 (`ubuntu-22.04`) and ARM64
(`ubuntu-22.04-arm`) runners, for four targets in total. To build
an older unsupported source such as 1.4.9, explicitly disable this option. A
missing or unreviewed DRM interface fails before bridge dependencies are installed.

The matrix rows remain experimental and `enabled: false` for the ordinary matrix;
`workflow_enabled: true` selects only the reusable Wayland lane. They are not
replacements for ordinary Standard/SOS qualification. Source variant is `standard` or `sos`;
`build_flavor: unattended-wayland` identifies the distinct captured feature set.

## Reviewed interfaces and package gates

`metadata/build/wayland-policy.json` records paired exact DRM-job/build.py hashes
and dependency pins for upstream 1.5.0 (`libdrmtap 0.5.8`) and reviewed 1.5.1 snapshot
1297da6d (`libdrmtap 0.5.12`). Unknown combinations fail closed. The library pin
must also match the exact build.py hash in the prepared-source manifest, not just
an approved library version. Ordinary Linux adapter signatures remain mandatory.

The 1.5.1 review covers the official DRM job's additional tests and the library's
0.5 ABI, frame lifetime/descriptor checks and privileged-environment hardening.
This is source review, not successful package or runtime evidence for the new pin.

The helper-disabled EGL library is built natively; compilation/package stages use
the reviewed Linux recipe with `drm` and `drm-wake`. The 1.5.0 profile has eight test groups; 1.5.1 has twelve including DRM pacing,
CRTC refresh, loader and clipboard tests. Each must
execute at least one test. DEBs must pass architecture, libc floor, EGL/capture/wake
markers, stock-package Conflicts/Provides/Replaces, exact library/soname, checksum,
configuration, credential and prepared-source provenance checks. There is no RPM
output for this flavor. All four variant/architecture combinations must validate in the same workflow run.
The native ABI probe reads the compiled `sos-mode` flag, requiring `Y` for SOS and
an empty value for Standard, before the DEB is labeled or uploaded.

## Aggregate and Release behavior

When enabled, both parents wait for the Wayland lane before their final aggregate.
The packages download into a separate directory so they cannot accidentally satisfy
ordinary platform targets. The final aggregate validates all four DEBs again and binds
their source-manifest identity, prepare run, Common patch hash and configuration
fingerprint to the ordinary Linux build with the same source variant and architecture,
including its SOS patch hash when applicable. Missing, duplicate, stale, cross-channel
or mismatched-source packages block aggregation.

Tag draft/release jobs download and revalidate the Wayland set again in the
publication job, add all four DEBs to the normal asset directory, and regenerate the
public SHA256SUMS. Release metadata records the Wayland policy digest and its
experimental scope. Existing immutable releases/drafts are never appended to or
overwritten: requesting Wayland while reusing an older revision without matching
Wayland evidence fails. Disable the option to reuse that old revision, or build a
new patch identity through the existing revision mechanism.

Nightly includes all four DEBs in its aggregated Actions package artifact and, in
protected-main draft mode, its prerelease Draft. Android signing in that mode uses
the same separately protected direct YubiKey job as Tag. Wayland itself never
receives a PIN or signing-host access; public Nightly publication requires its
separate explicit release mode and verified-draft gates.

Per-target artifacts remain `rustdesk-wayland-<version>-<upstream-sha>-<variant>-<arch>`;
`wayland-qualification-<run-id>` records all four targets, with `stable`/`nightly` channel
identity. Parent aggregate reports also contain this separate Wayland result.

Downloads are named `rustdesk-unattended-wayland-<standard|sos>-<version>-<arch>.deb`.
The DEB's Description names its source variant; the Debian Package field remains
`rustdesk-unattended-wayland` for both. Installing Standard or SOS replaces the
other variant because they share service and configuration paths; parallel
installation is not supported. Labeling changes only the package description,
not the executable payload, maintainer scripts or upstream packaging source.
Actual installed upgrades, configuration retention and service restart behaviour
still require device tests. SOS reuses the existing UI-focused patches; it is not
a new backend restriction against all outgoing connections.

Policy schema v2 binds the four-target requirement and naming convention into the
Stable/Nightly build identity. An old two-package release cannot satisfy this
new policy, and existing releases are never appended to in place.

The package conflicts with ordinary RustDesk. The earlier 1.5.0 package worked in
one user-confirmed locked-screen session after disabling forced software rendering;
that is not runtime evidence for these new builds, ARM64, login/reboot or other GPUs.

Local contracts: `scripts/platform/wayland_contract.py`,
`scripts/release/nightly_contract.py`, `scripts/release/channel_contract.py`,
`scripts/release/qualification_contract.py` and `scripts/validation/repository_contract.py`.

## ARM64 post-build packaging validation

The official Linux ARM recipe replaces the Flutter Linux command with
flutter-elinux and changes x64/release paths to arm64/release in build.py. Run
40202174271 built its ARM64 binary and DEB successfully, then our final package
check incorrectly compared this transformed script to the pristine fingerprint.
Finalization now retrieves build.py from the locked Git object, verifies its hash
against the prepared inventory and DRM policy, and accepts exactly those two
reviewed substitutions for ARM64 (no substitutions for amd64). Extra changes,
wrong source SHAs and modified inventories remain blocked. This fixes the check;
a fresh full build is still required to validate the resulting artifact.
