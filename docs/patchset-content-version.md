# Patchset content revision workflow

`patchsets/vN/patchset.json.revision` is the single current content revision. `versioning.history` is its append-only identity and reviewed semantic history; CHANGELOG.md is deterministically rendered from it. v1.1 and v2.7 establish migration baselines, not invented historical content counts. This reviewed history is used by current Stable/Nightly version metadata; the retired Content Identity v2 cutover is not an active release gate.

```sh
git fetch origin main
python3 -m scripts.upstream.patchset_version bump --patchset v2 --base origin/main --check
python3 -m scripts.upstream.patchset_version bump --patchset v2 --base origin/main
# Fill reason, category descriptions, references, compatibility, limitations;
# set review_status=reviewed only after reviewing the actual change.
python3 -m scripts.upstream.patchset_version render --patchset v2
python3 -m scripts.upstream.patchset_version verify --base origin/main --check
```

Every command emits JSON. `bump --check` is read-only. The Common/SOS filename + NUL + CRLF-normalized bytes hash is byte-compatible with existing patchsets.py. One or both changed scopes allocate exactly base.revision+1. Repeated edits in one PR use the same base revision, and new hash changes invalidate the previous semantic review. Returning to historical bytes allocates another number. A metadata-only change cannot bump. Rewriting historical identities, missing/stale Changelog, placeholders, unreviewed entries and mismatched hashes fail verification.

The allocation records the exact base commit, not its merge-base. Version validation is executed by the repository contract suite. Rebase on the latest main and rerun the verification before merging; protect against stale Patchset revision allocations with required up-to-date CI checks or a merge queue.

The retired bootstrap/migration path is no longer accepted. A verification base must already contain reviewed `versioning` history; older unversioned branches must be rebased. Never infer Patchset revisions from historical Release numbering.

Current features are separately maintained under `versioning.features`; revision categories describe only that revision's delta. Neither tooling nor CI invents semantic descriptions. The initial baseline explicitly states metadata migration only, with historical validation limits preserved.
