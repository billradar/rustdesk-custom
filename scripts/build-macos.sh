#!/usr/bin/env bash
set -euo pipefail
: "${PLATFORM_ARCH:?}" "${VARIANT:?}" "${PREPARED_SOURCE_DIR:?}"
source=$PREPARED_SOURCE_DIR
python3 scripts/production_config.py inputs
python3 scripts/platform_adapter.py "$source" --platform macos --arch "$PLATFORM_ARCH" --output .work/platform-profile.json
python3 scripts/platform_commands.py "$source" macos "$PLATFORM_ARCH" setup
triplet=$(python3 -c 'import json;print(json.load(open(".work/platform-profile.json"))["triplet"])')
"$VCPKG_ROOT/vcpkg" install --triplet "$triplet" --x-install-root="$VCPKG_ROOT/installed" --x-manifest-root="$source"
# Follow the exact official macOS ARM deployment-target adjustments.
python3 scripts/platform_commands.py "$source" macos "$PLATFORM_ARCH" build
cd "$source"
create-dmg --icon 'RustDesk.app' 200 190 --hide-extension 'RustDesk.app' --window-size 800 400 --app-drop-link 600 185 "rustdesk-$UPSTREAM_VERSION-$PLATFORM_ARCH-unsigned.dmg" ./flutter/build/macos/Build/Products/Release/RustDesk.app
cd - >/dev/null
python3 scripts/platform_package.py create --tree "$source" --platform macos --arch "$PLATFORM_ARCH" --variant "$VARIANT"
