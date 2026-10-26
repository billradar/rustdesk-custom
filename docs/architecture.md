# Architecture and design principles

[English](architecture.md) · [简体中文](architecture-zh.md)

## Project scope

RustDesk Custom is a maintenance, build, validation, and release repository for upstream RustDesk. It is not a long-lived mirror of the full upstream source. Customizations are kept as reviewed patchsets and applied to an exact upstream revision.

## Data flow

~~~text
Official RustDesk source → resolve and review → select patchset
       → prepare Standard / SOS source → platform builds
       → validate packages and provenance → aggregate and qualify
       → optional authorized Android signing → Stable Draft / Release
~~~

Each stage validates its own inputs and outputs. A successful build is not a qualification result, and a qualification result is not a published release.

## Repository areas

| Path | Responsibility |
| --- | --- |
| `.github/workflows/` | Workflow orchestration, permissions, conditions, and artifact transfer |
| `.github/actions/` | Reusable action implementations |
| `scripts/upstream/` | Upstream resolution, patchset selection, and integrity checks |
| `scripts/source/` | Source retrieval, patch application, and prepared-tree verification |
| `scripts/build/` | Build entry points and configuration |
| `scripts/platform/` | Platform adaptation, packaging, and artifact checks |
| `scripts/release/` | Channel identity, qualification, aggregation, and release gates |
| `scripts/signing/` | Android signing identity and production signing helpers |
| `scripts/validation/` | Repository, compatibility, and configuration contracts |
| `metadata/` | Machine-readable platform, release, upstream, and signing records |
| `patchsets/` | Reviewed custom patches |

## Build identity and traceability

An auditable build must identify the upstream repository, ref, and resolved commit SHA; the selected patchset and patch hashes; variant and target architecture; custom repository commit; workflow run; and artifact checksums and validation results. A version string, branch name, or filename alone does not establish provenance.

## Sources of truth

- Platform enablement, required targets, and support status: `metadata/platform/matrix.json`.
- Reviewed upstream build adapters: `metadata/platform/adapter-profiles.json`.
- Android package and signing identity: `metadata/signing/android-standard.json` plus the identity metadata used by the signing workflow.
- Release identity: `metadata/release/identity.json` as consumed by current code.
- Runtime behavior: the relevant script, reusable workflow, and caller conditions.

Documentation should explain these records rather than copy them into a second configuration that can drift.

## Fail closed

Stop when source SHAs differ, patches fail, artifact provenance is incomplete, a target is outside the reviewed matrix, or package/ABI/certificate checks fail. Do not bypass a failed gate by ignoring errors, weakening contracts, substituting signing identities, or fabricating validation results.
