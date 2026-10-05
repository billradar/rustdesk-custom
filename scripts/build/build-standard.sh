#!/usr/bin/env bash
set -euo pipefail
exec bash "$(dirname "${BASH_SOURCE[0]}")/build-windows.sh" standard "${1:-005a8b4a04fd906c707eefd69c4898aa2c696202}"
