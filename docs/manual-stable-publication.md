# Manual Stable publication

`tag.yml` and `nightly.yml` build only. Their supported modes are `dry-run` and
`draft`; script admission rejects `release` even if a caller bypasses the UI.
Nightly remains a private prerelease Draft with a moving `nightly` tag. Its
existing build proof remains; it does not enter native immutable publication.

`publish-stable.yml` is a separate workflow dispatched manually by repository owner billradar on main. Owner numeric identity and the rerun actor are checked; Router/bot dispatches cannot publish. There is
no schedule, workflow_run, router dispatch, signing job, compiler or asset upload.
It publishes one verified existing Stable Draft, selected by explicit inputs or
by its exact link to the latest successful Stable build.
It neither enables repository immutability nor changes historical Releases. This is not a per-release exemption in GitHub: manually publishing a Nightly Draft outside these workflows would still invoke the repository-wide immutable policy.

## Prerequisites

Enable repository immutable releases only after this build-only Nightly policy is
merged and reviewed. Create a fresh qualified Stable Draft under the intended
policy; do not retrofit protected historical v1.5.1-custom.v2.8. GitHub's native
proof appears after immutable publication, not during Draft preparation.

The existing release App must be installed on this repository. The publisher
requests only Contents write, Actions read, Attestations read and Administration
read. Administration read is necessary to check `/immutable-releases` BEFORE
publication; no Administration write is requested. Grant the App this additional
read permission and approve the updated installation before using the workflow.
The shared build/Draft token retains its existing permissions. App keys/tokens
remain isolated from builds and hardware signing and are revoked after the job.

## Manual operation

Trigger **Publish verified Stable Draft** on `main` in either mode:

- Leave all three fields blank: query the latest successful main-branch manual
  `tag.yml` run, then find its unique private Stable Draft. The manifest's verified
  `build_run` must match that exact run; a matching source commit alone is
  insufficient. Read the canonical tag and manifest SHA256 from that Draft.
- Fill all three fields: use the exact Release ID, canonical custom Stable tag
  and manifest SHA256 (without a `sha256:` prefix).

Partial inputs fail before discovery or publication. Automatic discovery follows
all Release pages, excludes Nightly, published objects and protected 1.5.1 v2.8,
and never sorts by Release creation time. No match, duplicates, invalid evidence
or incomplete inventory stop publication. If the latest successful run is a
dry-run or no-op without its own Draft, automatic selection stops; it never falls
back to an older build. Explicit inputs remain available for a reviewed Draft.

Discovery runs once. The selected ID, tag, manifest digest and verified build run
are recorded in logs and the publication receipt. Later checks operate on those
locked values even if another build completes. An automatic rerun does not select
an already published object: to reverify a published result, fill its exact three
values from the previous receipt.

Before a write, the workflow verifies:

- repository immutability is already enabled and the reviewed CLI is available;
- the selected object and locked manifest digest agree;
- the manifest and all installer API sizes/digests agree with a valid registry build
  proof bound to the trusted main Tag workflow and exact source/run;
- the Profile is Stable-eligible and its patch hashes are in reviewed history;
- the real tag resolves to the manifest's custom commit, and its build run was a
  successful main-branch workflow_dispatch of `tag.yml`;
- a second full verification finds unchanged Draft identity and asset inventory.

It issues exactly one PATCH to publish the existing object. It does not create,
move or delete tags, rebuild, sign, overwrite attachments or upload a fake native
proof. GitHub generates the native Release v0.2 proof. The maintained,
checksum-pinned gh 2.103.3 verifies its GitHub CA/service identity and TSA evidence;
additional policy binds numeric owner/repository and Release IDs, tag/purl, the
actual Git object (including annotated tags) and the exact complete asset set.

## Failure and retry semantics

Only reads retry after publication while GitHub's proof becomes available. A
transport error on the publication request is recorded as **UNKNOWN**; there is
no automatic retry of a possibly successful write. Inspect the exact Release ID.

The Actions receipt records publication separately from native verification.
If publication succeeded but proof verification failed, the workflow fails while
recording that the Release is already published. Never rebuild, delete, overwrite
or republish it to make the job green. Rerunning the workflow with the same inputs
may verify the already immutable object read-only; it does not publish again.

The native proof is the sole client-facing update proof. `update-manifest.json`
remains the typed installer selector. Build SLSA evidence stays in the registry and
internal Actions handoff for pre-publication qualification; the custom
`release-attestation.json` is not uploaded. v3.4 clients verify GitHub's native
proof using the service CA/TSA and strict Release/tag/inventory binding. APK v2/v3
signatures and device testing remain independent.

## Verification scope

Run `scripts.release.publish_stable_contract` plus affected build/release/router
contracts. Rust 1.75 native tests include a genuine GitHub Release proof with its
GitHub service trust root and TSA, alongside signature/digest/root/timestamp
negative cases. No actual repository setting change or Release publication is
performed by these tests. The first real manual publication still needs explicit
user authorization, appropriate installation permissions and post-publication
verification; passing CI is not that authorization.
