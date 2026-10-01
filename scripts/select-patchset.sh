#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# First argument must be the already-resolved immutable SHA, never a floating ref.
python3 "$root/scripts/patchsets.py" "$@"
