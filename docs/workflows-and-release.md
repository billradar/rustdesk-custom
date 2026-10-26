# Workflows and releases

[English](workflows-and-release.md) · [简体中文](workflows-and-release-zh.md)

## Workflow roles

| Workflow | Role |
| --- | --- |
| `ci.yml` | Classify PR/push/manual changes; run lightweight documentation checks or functional compatibility/qualification |
| `compat-check.yml` | Reusable upstream, patchset, architecture-contract, and compatibility checks |
| `prepare-source.yml` | Prepare Standard/SOS source with explicit provenance |
| `build.yml`, `build-platform.yml` | Plan targets, build, and transfer artifacts |
| `build-stable-windows.yml`, `build-stable-platforms.yml`, `build-stable-android.yml` | Stable platform build entry points |
| `tag.yml` | Stable resolution, preflight, build, aggregation, signing gates, and dry-run/draft/release decisions |
| `upstream-stable.yml` | Discover official Stable releases and route to private Draft builds |
| `upstream-main-compatibility.yml` | Check the upstream default branch; does not build or publish Nightly |
| `android-yubikey-signing-test.yml` | Explicitly authorized signing smoke test; does not publish |

Workflow files and contracts define actual triggers, permissions, inputs, dependencies, and publication behavior. New PRs use the [PR template](../.github/PULL_REQUEST_TEMPLATE.md).

## CI and upstream compatibility

PRs, supported pushes, and manual runs begin with change classification. Documentation-only changes use a lightweight path; functional or ambiguous changes receive functional checks. `force_rebuild` belongs to `ci.yml` and does not imply a same-named Stable input.

`upstream-main-compatibility.yml` resolves the current upstream default-branch SHA and checks compatibility. It does not trigger Nightly or replace Stable qualification. Nightly is an independent channel and cannot bypass source, patch, interface, or package checks.

## Stable qualification and release

Stable identity binds the exact custom commit, official upstream Stable version/SHA, and current patch identity.

~~~text
Official Stable discovery → resolve exact upstream SHA → private Draft route
→ Draft/revision preflight → source preparation and platform builds
→ artifact validation and aggregation → authorized Android signing
→ final preflight → dry-run / Draft / Release
~~~

Qualification from one custom commit cannot be reused for another commit, upstream SHA, patchset, revision, or build configuration. A dry-run does not create a release. Draft and public Release are separate operations; public release requires explicit intent and all aggregate gates.

Stable identity includes upstream SHA, custom SHA, patchset and Common/SOS patch hashes, Wayland selection, and Wayland policy SHA-256 when enabled. Reuse requires a completion marker, matching identity, exact asset inventory, uploaded state, sizes, and GitHub SHA-256 digests. Incomplete or mismatched assets stop the workflow. Existing releases are immutable.

The Stable router triggers signed private Drafts only. It skips complete matching builds and active same-identity runs; it never authorizes public release.

## Wayland

`wayland.yml` is a reusable experimental amd64/ARM64 build called by Tag and Nightly through `include_wayland` (default true). Stable Draft/Release revalidates and attaches both DEBs; Nightly includes them in its aggregate. See [Wayland build gates](wayland-unattended.md).

## Nightly synchronization and builds

Official `flutter-nightly.yml` starts daily at 00:00 UTC (08:00 Hong Kong time). `upstream-nightly.yml` polls at :07/:22/:37/:52 and routes newly successful official builds to `nightly.yml`. Schedules may be delayed. The router binds the official repository, default branch, workflow path, successful run ID, and full SHA; it does not trust a potentially stale `nightly` tag or unfinished upstream build.

Nightly reuses shared source preparation and platform build components, deriving Standard/SOS from one prepared source batch. Android remains Standard-only. Windows ARM64 is experimental. Wayland is a separately qualified experimental lane. Unknown build interfaces remain blocked.

Automatic routing runs from repository `main`. Deduplication uses upstream SHA, custom SHA, release mode, and Wayland selection; run ID is provenance, not a reason to rebuild unchanged source. Matching active/successful identities are skipped. Automatic retries are bounded; changes in code, source SHA, or Wayland selection create a new identity.

Production Draft mode requires all build, aggregate, and Android signing checks to pass. Public Nightly prerelease requires an explicit manual `release` mode and complete matching Draft. A successful build does not establish locked-screen or real remote-session behavior.

## Unknown upstream interface review

The upstream monitor performs read-only inspection alongside compatibility checks. Known signatures need no review. Unknown interfaces produce a same-run JSON report with observed interfaces, changed critical fingerprints, an upstream comparison, and patch/API structure results. Compilation, bridge generation, Flutter analysis, and runtime are not run on this unapproved path; normal compatibility remains blocked pending review.

A trusted-main writer may propose a draft, report-only PR with limited contents/PR permissions. It cannot change approved profiles, patches, signing, or release settings. No PAT or production configuration is used. A human must review the report, update profiles if appropriate, and run full compatibility checks. Nothing is automatically approved, merged, or published.

## Android signing

Production signing runs in a separately protected job using the configured hardware-backed identity. Ordinary build and draft jobs do not receive the signing PIN. See [Android production signing](android-production-signing.md) for safeguards and verification.
