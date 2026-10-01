#!/usr/bin/env bash
set -euo pipefail
variant=${1:?Variant required}
ref=${2:?Upstream ref required}
[[ "$variant" == standard || "$variant" == sos ]] || exit 1
[[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* ]] || { echo 'Windows x86_64 Git Bash is required.' >&2; exit 1; }
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python3 "$root/scripts/verify-source.py" --config-only
mkdir -p "$root/.work" "$root/artifacts"
workspace=$(mktemp -d "$root/.work/$variant.XXXXXX")
bash "$root/scripts/prepare.sh" "$ref" "$workspace"
if [[ -z "${PATCHSET:-}" ]]; then
    sha=$(git -C "$workspace" rev-parse HEAD)
    bash "$root/scripts/select-patchset.sh" "$sha" --source "$workspace" --report "$workspace/patchset-selection.json"
    export PATCHSET=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["selected"])' "$workspace/patchset-selection.json")
fi
bash "$root/scripts/apply-patches.sh" "$workspace" "$variant"
[[ "$PATCHSET" == v1 ]] || export AUTOMATION_MODE=1
python3 "$root/scripts/verify-source.py" "$workspace" "$variant" ${AUTOMATION_MODE:+--automation}
if [[ -n "${AUTOMATION_MODE:-}" ]]; then
    python3 - "$workspace" "$variant" "$root/scripts" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from compatibility import contracts
contracts(Path(sys.argv[1]), sys.argv[2])
PY
fi
# Bridge files must have been generated from this exact official baseline.
: "${RUSTDESK_BRIDGE_DIR:?Generate the official Flutter bridge first (see test-build.yml)}"
python3 "$root/scripts/package.py" restore-bridge "$workspace" "$RUSTDESK_BRIDGE_DIR"
pushd "$workspace" >/dev/null
# The corresponding official build.py owns Rust/Cargo and Flutter compilation.
python3 build.py --portable --flutter --skip-portable-pack --hwcodec --vram
popd >/dev/null
python3 "$root/scripts/package.py" package "$workspace" "$variant" "$ref" "$root/artifacts" "$root"
