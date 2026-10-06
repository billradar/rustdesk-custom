#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
PYTHONPATH="$root" python3 "$root/scripts/upstream/patchsets.py" "$@"
