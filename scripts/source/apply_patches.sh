#!/usr/bin/env bash
set -euo pipefail
source_tree=${1:?Source workspace required}
variant=${2:?Variant required}
[[ "$variant" == standard || "$variant" == sos ]] || exit 1
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
patchset=${PATCHSET:-v1}
[[ "$patchset" =~ ^v[1-9][0-9]*$ ]] || exit 1
PYTHONPATH="$root" python3 - "$root/scripts" "$patchset" "$source_tree" <<'PYCODE'
import sys, os, re
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from scripts.upstream.patchsets import verify, require_selection
verify(sys.argv[2])
version = re.search(r'^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"',
                    (Path(sys.argv[3]) / 'Cargo.toml').read_text(), re.M)
if not version:
    raise ValueError('Numeric source version required before patching')
require_selection(version.group(1), sys.argv[2], os.environ.get('BUILD_CHANNEL', 'ci'))
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
