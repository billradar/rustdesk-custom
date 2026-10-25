# Wayland unattended builds inside Tag and Nightly

`wayland.yml` is now a **reusable internal workflow**, without a separate manual
entry point. `tag.yml` and `nightly.yml` call it with their own locked upstream
SHA, version, channel, patchset and same-run prepared Standard artifact. Common
patch policy, including forced-off software rendering, is shared with the normal
builds. No second resolve/fetch/prepare occurs in the Wayland lane.

Both parent workflows expose `include_wayland` (boolean, default **true**).
It builds native amd64 (`ubuntu-22.04`) and ARM64 (`ubuntu-22.04-arm`) DEBs. To build
an older unsupported source such as 1.4.9, explicitly disable this option. A
missing or unreviewed DRM interface fails before bridge dependencies are installed.

The matrix rows remain experimental and `enabled: false` for the ordinary matrix;
`workflow_enabled: true` selects only the reusable Wayland lane. They are not
replacements for ordinary Standard/SOS qualification. Source variant is Standard;
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
output for this flavor. Both architectures must validate in the same workflow run.

## Aggregate and Release behavior

When enabled, both parents wait for the Wayland lane before their final aggregate.
The packages download into a separate directory so they cannot accidentally satisfy
ordinary platform targets. The final aggregate validates both DEBs again and binds
their source-manifest identity, prepare run, Common patch hash and configuration
fingerprint to the ordinary Standard build. Missing, duplicate, stale, cross-channel
or mismatched-source packages block aggregation.

Tag draft/release jobs download and revalidate the Wayland pair again in the
publication job, add both DEBs to the normal asset directory, and regenerate the
public SHA256SUMS. Release metadata records the Wayland policy digest and its
experimental scope. Existing immutable releases/drafts are never appended to or
overwritten: requesting Wayland while reusing an older revision without matching
Wayland evidence fails. Disable the option to reuse that old revision, or build a
new patch identity through the existing revision mechanism.

Nightly includes both DEBs in its aggregated Actions package artifact and remains
artifact-only. No new publication, Android production signing, YubiKey access or
PIN authorization is introduced by this integration.

Per-target artifacts remain `rustdesk-wayland-<version>-<upstream-sha>-<arch>`;
`wayland-qualification-<run-id>` records the pair, with `stable`/`nightly` channel
identity. Parent aggregate reports also contain this separate Wayland result.

The package conflicts with ordinary RustDesk. The earlier 1.5.0 package worked in
one user-confirmed locked-screen session after disabling forced software rendering;
that is not runtime evidence for these new builds, ARM64, login/reboot or other GPUs.

Local contracts: `scripts/platform/wayland_contract.py`,
`scripts/release/nightly_contract.py`, `scripts/release/channel_contract.py`,
`scripts/release/qualification_contract.py` and `scripts/validation/repository_contract.py`.
