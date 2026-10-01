#!/usr/bin/env bash
set -euo pipefail
source_tree=${1:?Source workspace required}
variant=${2:?Variant required}
[[ "$variant" == standard || "$variant" == sos ]] || exit 1
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
patchset=${PATCHSET:-v1}
[[ "$patchset" =~ ^v[1-9][0-9]*$ ]] || exit 1
python3 - "$root/scripts" "$patchset" <<'PYCODE'
import sys
sys.path.insert(0,sys.argv[1])
from patchsets import verify
verify(sys.argv[2])
PYCODE
apply_one() {
    local patch=$1 target=$2
    printf 'Checking %s\n' "$(basename "$patch")"
    if ! git -C "$target" apply --check "$patch"; then
        printf 'STOP: failed patch %s; no build will run.\n' "$(basename "$patch")" >&2
        return 1
    fi
    git -C "$target" apply "$patch"
}
for patch in "$root"/patchsets/"$patchset"/common/*.patch; do
    target=$source_tree
    [[ "$(basename "$patch")" != 0001-hbb-server-defaults.patch ]] || target="$source_tree/libs/hbb_common"
    apply_one "$patch" "$target"
done
if [[ "$variant" == sos ]]; then
    for patch in "$root"/patchsets/"$patchset"/sos/*.patch; do apply_one "$patch" "$source_tree"; done
fi
