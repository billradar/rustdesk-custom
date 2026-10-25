# Wayland unattended builds

`wayland.yml` is a separate manually dispatched build flow for the
`unattended-wayland` Linux flavor. It resolves an official Stable tag (default
`1.5.0`) to an immutable SHA, selects the normal version-bounded patchset, and
uses the same prepared Common/Standard source as the tag pipeline. It does not
join the separate Nightly channel, publish a release, sign Android artifacts,
or qualify the existing Stable target set.

## Targets and source identity

The canonical target entries are in `metadata/platform/matrix.json`:

- `linux-x86_64-unattended-wayland`: native `ubuntu-22.04`, DEB `amd64`.
- `linux-aarch64-unattended-wayland`: native `ubuntu-22.04-arm`, DEB `arm64`.

Both are experimental and selected only by this dedicated workflow. `enabled:
false` excludes them from the existing generic CI/Stable planner, including its
experimental mode. `workflow_enabled: true` opts them into this workflow. This
configuration is not evidence that either build or a real locked remote session
has passed. In particular, upstream's dedicated DRM job directly targets x86_64;
ARM64 adapts its reviewed native Linux recipe and must pass independent gates.
ARMv7 is not part of this flow.

The source variant remains `standard` in the immutable source manifest because
no new source patch layer is applied. `build_flavor: unattended-wayland` separately
identifies the compiled features and package. Standard, SOS and unattended
packages cannot be interchanged as qualification evidence.

## Fail-closed contracts

`metadata/build/wayland-policy.json` pins the reviewed upstream DRM job,
`build.py`, and libdrmtap repository/commit. Existing platform adapter signatures
remain mandatory. A changed upstream interface requires a new explicit review;
there is no automatic approval or fallback to a stock package.

Before expensive dependencies, the target checks the prepared source identity,
Linux/Standard/Stable scope, native runner, and reviewed DRM interface. The native
runner builds the pinned libdrmtap with upstream's helper-disabled and EGL checks.
The existing Ubuntu 18.04 native compilation recipe is adapted to request both
`drm` and `drm-wake`; all eight upstream DRM test filters must execute at least
one test. RPM packaging is deliberately excluded because upstream's DRM path
supports DEB only.

Each artifact must pass the existing compiled configuration, credential scan,
checksum, source provenance and client ELF architecture gates, plus:

- DEB architecture and `rustdesk-unattended-wayland` package identity;
- `Conflicts`, `Provides` and `Replaces` relationships with `rustdesk`;
- DRM/EGL/GLES runtime dependencies;
- versioned libdrmtap, contained soname link and matching ELF machine;
- EGL capture markers and absence of the privileged helper fallback;
- compiled capture and display-wake markers;
- exact dependency pin, policy identity and positive DRM test execution.

The aggregate independently revalidates both packages and rejects missing,
duplicate, stale-run, mixed-source, mixed-flavor or mismatched-policy artifacts.
One successful architecture does not qualify the pair. Successful qualification
is **experimental build/package evidence only**, never proof of runtime support.

## Running and reviewing

After integration to the default branch, select **Wayland Unattended Build** in
Actions, choose the desired branch and official Stable tag, and run it. Validated
packages are in `rustdesk-wayland-<version>-<upstream-sha>-<arch>` artifacts. The
pair result is `wayland-qualification-<run-id>`. Failed targets upload redacted
diagnostics separately; no failed client bundle is uploaded.

The package conflicts with the ordinary RustDesk installation. Back up local
configuration and retain a local recovery path before installation; this flow
does not install anything on the user's computer. Test locked-screen access,
logout, reboot/login screen, multi-monitor and Intel/NVIDIA behavior separately.

Local contracts:

```sh
PYTHONPATH=. python3 scripts/platform/wayland_contract.py
PYTHONPATH=. python3 scripts/validation/repository_contract.py
PYTHONPATH=. python3 scripts/release/qualification_contract.py
PYTHONPATH=. python3 scripts/release/channel_contract.py
```
