#!/usr/bin/env bash
set -euo pipefail
: "${PLATFORM_ARCH:?}" "${PREPARED_SOURCE_DIR:?}"
[[ "$VARIANT" == standard ]] || { echo 'Android SOS forbidden';exit 1; }
source=$PREPARED_SOURCE_DIR
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
if [[ "${BUILD_CHANNEL:-stable}" == ci ]]; then
    [[ "${PLATFORM:-}" == android ]] || exit 1
    source scripts/build/platform_ci_guard.sh
else
    export CONFIG_MIR_DIR="$PWD/.work/compiler-config"
    trap 'rm -rf "$CONFIG_MIR_DIR"' EXIT
    export RUSTC_WRAPPER="$PWD/scripts/build/config_mir.py"
    python3 scripts/signing/production_config.py inputs
fi
python3 scripts/platform/platform_adapter.py "$source" --platform android --arch "$PLATFORM_ARCH" --output .work/platform-profile.json
sdk=$(dirname "$(dirname "$(command -v flutter)")")
git -C "$sdk" apply --check "$source/.github/patches/flutter_3.24.4_dropdown_menu_enableFilter.diff"
git -C "$sdk" apply "$source/.github/patches/flutter_3.24.4_dropdown_menu_enableFilter.diff"
python3 scripts/platform/platform_commands.py "$source" android "$PLATFORM_ARCH" deps
python3 scripts/platform/platform_commands.py "$source" android "$PLATFORM_ARCH" native
# The reviewed official job uses debug signing. This is TEST SIGNED, never production signed.
python3 scripts/platform/platform_commands.py "$source" android "$PLATFORM_ARCH" package
if [[ "${BUILD_CHANNEL:-stable}" == ci ]]; then
    python3 -m scripts.build.platform_ci_report "$source" android "$PLATFORM_ARCH" standard
else
    python3 scripts/platform/platform_package.py create --tree "$source" --platform android --arch "$PLATFORM_ARCH" --variant standard
fi
