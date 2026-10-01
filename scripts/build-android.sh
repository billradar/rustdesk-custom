#!/usr/bin/env bash
set -euo pipefail
: "${PLATFORM_ARCH:?}" "${PREPARED_SOURCE_DIR:?}"
[[ "$VARIANT" == standard ]] || { echo 'Android SOS forbidden';exit 1; }
source=$PREPARED_SOURCE_DIR
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
export CONFIG_MIR_DIR="$PWD/.work/compiler-config"
trap 'rm -rf "$CONFIG_MIR_DIR"' EXIT
export RUSTC_WRAPPER="$PWD/scripts/config_mir.py"
python3 scripts/production_config.py inputs
python3 scripts/platform_adapter.py "$source" --platform android --arch "$PLATFORM_ARCH" --output .work/platform-profile.json
sdk=$(dirname "$(dirname "$(command -v flutter)")")
git -C "$sdk" apply --check "$source/.github/patches/flutter_3.24.4_dropdown_menu_enableFilter.diff"
git -C "$sdk" apply "$source/.github/patches/flutter_3.24.4_dropdown_menu_enableFilter.diff"
python3 scripts/platform_commands.py "$source" android "$PLATFORM_ARCH" deps
python3 scripts/platform_commands.py "$source" android "$PLATFORM_ARCH" native
# The reviewed official job uses debug signing. This is TEST SIGNED, never production signed.
python3 scripts/platform_commands.py "$source" android "$PLATFORM_ARCH" package
python3 scripts/platform_package.py create --tree "$source" --platform android --arch "$PLATFORM_ARCH" --variant standard
