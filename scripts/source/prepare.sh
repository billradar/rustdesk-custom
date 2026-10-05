#!/usr/bin/env bash
set -euo pipefail
ref=${1:-005a8b4a04fd906c707eefd69c4898aa2c696202}
destination=${2:?Usage: prepare.sh [upstream-ref] empty-workspace}
[[ "$ref" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,100}$ ]] || { echo 'Invalid upstream ref' >&2; exit 1; }
mkdir -p "$destination"
[[ -z "$(ls -A "$destination")" ]] || { echo 'Workspace must be empty; no existing files are reset or deleted.' >&2; exit 1; }
git -C "$destination" init --quiet
git -C "$destination" remote add origin https://github.com/rustdesk/rustdesk.git
git -C "$destination" fetch --depth=1 origin "$ref"
sha=$(git -C "$destination" rev-parse 'FETCH_HEAD^{commit}')
[[ -z "${UPSTREAM_EXPECTED_SHA:-}" || "$sha" == "$UPSTREAM_EXPECTED_SHA" ]] || { echo 'Upstream SHA mismatch' >&2; exit 1; }
git -C "$destination" checkout --quiet --detach "$sha"
git -C "$destination" submodule update --init --recursive
expected_hbb=$(git -C "$destination" rev-parse HEAD:libs/hbb_common)
[[ "$(git -C "$destination/libs/hbb_common" rev-parse HEAD)" == "$expected_hbb" ]]
[[ -z "$(git -C "$destination" status --porcelain --untracked-files=all)" ]]
git -C "$destination" submodule foreach --recursive 'test -z "$(git status --porcelain --untracked-files=all)"'
printf 'Upstream ref: %s\nUpstream SHA: %s\nhbb_common SHA: %s\n' "$ref" "$sha" "$expected_hbb"
