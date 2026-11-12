# Release inventory and native attestation

New Stable and Nightly Drafts upload `update-manifest.json` as their only public
metadata asset. They never upload `release-attestation.json` or `SHA256SUMS`.
The manifest retains the deterministic `rustdesk-release-manifest-v2` schema:
source/build identity, numeric repository/owner IDs, patch hashes and content
revision, signing/Wayland options and exact installer name, size, SHA256 and
OS/architecture/variant/flavor/package selectors.

## Draft qualification and internal build evidence

An unpublished Draft cannot have GitHub's native Release proof. Main dispatch
aggregate jobs continue to generate SLSA v1 build evidence after qualification;
the bundle is handed to the writer through an internal same-run Actions artifact.
The writer regenerates the manifest, verifies the proof, exact source/run and
package bytes, and uploads only installers plus `update-manifest.json`. The
bundle must not be present in the upload directory.

Existing-Draft/ownership verification obtains build evidence from GitHub's
attestations registry by the manifest digest using `gh attestation verify`,
without reading a custom Release proof asset. It retains the trusted main
Tag/Nightly workflow, hosted-runner, numeric owner/repository, exact custom source,
dispatch and build-run certificate/provenance checks. Missing registry evidence
fails closed. Ordinary CI and dry-run cannot mint proofs or publish.

## Sole client proof: GitHub native Release attestation

Only the owner-manually dispatched `publish-stable.yml` publishes a qualified
Stable Draft. Repository immutability must already be enabled. GitHub generates
the native **Release attestation (json)** after publication; the workflow verifies
it and records the outcome. Nightly stays Draft-only and never enters native
publication. See [Manual Stable publication](manual-stable-publication.md).

The v3.4 client queries the repository attestations API by the exact manifest
SHA256, with `predicate_type=release&initiator=github`, using HTTPS without a token.
Discovery is untrusted: the native verifier checks the DSSE signature using the
bundled GitHub service CA, exact `https://dotcom.releases.github.com` identity and
signed RFC3161 TSA evidence. This GitHub service uses its own CA/TSA instead of
public Fulcio/Rekor/SCT; public Actions build proofs are not accepted by clients.

The signed Release v0.2 statement must bind the exact numeric Release ID,
repository name/ID, owner ID, tag and package URL. Its subjects must cover exactly
one Git tag object plus the manifest and every installer SHA256, with no missing,
extra or duplicate subject. Annotated Git tags are resolved separately and their
commit must equal the manifest's custom source. The API Release must be immutable,
published Stable. Missing/ambiguous proof, mutable release or any mismatch stops
updates; there is no fallback to the old bundle, Release prose or checksums.

`update-manifest.json` remains essential for typed selection and attested package
sizes; the native proof covers its exact bytes and installer digests. This proof
establishes publication identity and asset integrity, not a client-side SLSA
builder assertion, APK certificate continuity, OS code signing or device upgrades.
Internal build evidence remains a separate publication admission gate.

## Direct cutover and historical protection

Historical v1/v2.8 and v3.1-v3.3 content, tags and Releases stay unchanged. v3.4
allocates a new Common content revision. Older installed clients need a manual
upgrade to the new verifier. New build/reuse paths reject legacy custom-proof
Release inventories; create a fresh qualified Draft, never retrofit or overwrite
a historical object. Existing Nightly migration still requires explicit review.

Internal source/build checksums remain unchanged. Release prose has no machine
identity authority. Run `scripts.release.attestation_contract`,
`scripts.release.publish_stable_contract`, `scripts.validation.client_update_contract`
and `scripts.validation.update_manifest_native`, plus affected release contracts.
Tests use a genuine GitHub native reference proof and negative signature, digest,
TSA, identity and inventory cases. The schema-v2 parser fixture is unsigned;
this does not claim a fresh published RustDesk proof or real device validation.
