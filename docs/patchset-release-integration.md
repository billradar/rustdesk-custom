# Current Patchset release integration

Stable and Nightly use the same reviewed Patchset manifests in `patchsets/vN/patchset.json`. The source SHA and Common/SOS patch hashes determine **Coordinator Lite** build deduplication. `dry-run` never consumes the production dedup/retry budget.

A reviewed `revision` value determines the human-readable `custom.vP.R` version and generated Changelog. Upstream updates alone do not increment this content revision. Changes to Common/SOS patch files require an explicitly reviewed revision bump.

The production release path is independent from Lite routing: exact source and prepared artifacts, variant and target qualification, signed Android certificate and APK schemes, release identity, required assets, sizes and SHA-256 checks remain mandatory. Existing drafts and tags must not be overwritten on incompatible identities. Public releases require explicit release mode and existing authorization gates.

Coordinator v1 Git-ref journals, immutable admission receipts and Content Identity v2 cutover are retired. Their historic PRs remain available from GitHub history; no production workflow may import the retired runtime.
