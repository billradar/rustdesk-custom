# Patchset content revision workflow

`patchsets/vN/patchset.json.revision` is the single current content revision. `versioning.history` is its append-only identity and reviewed semantic history; CHANGELOG.md is deterministically rendered from it. v1.1 and v2.7 establish migration baselines, not invented historical content counts. No patch bytes changed in this stage. Production activation remains blocked by the phase-1 cutover contract.

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

The allocation records the exact base commit, not its merge-base. The independent read-only `Patchset content version contract` workflow fetches the current PR target and refuses an allocation based on an earlier main. Rebase/merge latest main and rerun bump if a competing PR lands. Protected main must require this check and up-to-date branches (or a merge queue); this change does not alter repository branch protection. A green result on a stale head is not authorization to merge. For stacked PRs the current target is the preceding stage; revalidate against main when retargeted after integration.

The bootstrap path is special: it accepts only the exact audited main SHA, unchanged patch bytes and the explicit initial revision floor. Any other baseline requires a fresh reviewed audit. Production code must not silently infer that legacy Release numbers are content versions from their spelling.

Current features are separately maintained under `versioning.features`; revision categories describe only that revision's delta. Neither tooling nor CI invents semantic descriptions. The initial baseline explicitly states metadata migration only, with historical validation limits preserved.
