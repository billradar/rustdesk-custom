#!/usr/bin/env bash
set -euo pipefail
: "${PLATFORM_ARCH:?}" "${VARIANT:?}" "${PREPARED_SOURCE_DIR:?}"
root=$PWD
source=$PREPARED_SOURCE_DIR
python3 scripts/signing/production_config.py inputs
export BUILD_FLAVOR=unattended-wayland
[[ "$VARIANT" == standard || "$VARIANT" == sos ]] || { echo 'PROVENANCE: unreviewed source variant'; exit 1; }
python3 scripts/platform/wayland.py recipe --tree "$source" --arch "$PLATFORM_ARCH" --variant "$VARIANT" --out .work/linux-recipe
python3 scripts/platform/platform_adapter.py "$source" --platform linux --arch "$PLATFORM_ARCH" --variant "$VARIANT" --output .work/platform-profile.json
triplet=$(python3 -c 'import json;print(json.load(open(".work/platform-profile.json"))["triplet"])')
# Same small crate-type adjustment as the official Linux job, after input verification.
python3 - "$source/Cargo.toml" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]);s=p.read_text();old='["cdylib", "staticlib", "rlib"]'
if s.count(old)!=1:raise ValueError('BUILD_COMPAT: Linux crate-type interface changed')
p.write_text(s.replace(old,'["cdylib"]'))
PY
sudo apt-get update -y
sudo apt-get install -y nasm libva-dev rpm rpm2cpio cpio libxdo3 libgtk-3-0 libpam0g libpulse0 libasound2 libxfixes3 libxrandr2 libxtst6 libxcb-shape0 libxcb-xfixes0 libgbm1 libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 libayatana-appindicator3-1
"$VCPKG_ROOT/vcpkg" install --triplet "$triplet" --x-install-root="$VCPKG_ROOT/installed" --x-manifest-root="$source"
# Build the pinned capture library natively; Bionic's Meson is too old.
sudo apt-get install -y meson ninja-build pkg-config libdrm-dev libegl1-mesa-dev libgles2-mesa-dev
python3 - "$source" <<'PYCODE'
import importlib.util,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
spec=importlib.util.spec_from_file_location('upstream_build',root/'build.py')
module=importlib.util.module_from_spec(spec)
sys.argv=['build.py'];spec.loader.exec_module(module)
module.build_libdrmtap_so()
PYCODE
# No runtime source/config in an image layer. Only official build dependencies are cached here.
case "$PLATFORM_ARCH" in
 x86_64) image=amd64/ubuntu:18.04 ;;
 aarch64) image=arm64v8/ubuntu:18.04 ;;
 *) exit 1 ;;
esac
printf 'FROM %s\nCOPY install.sh /install.sh\nRUN bash /install.sh\n' "$image" > .work/linux-recipe/Dockerfile
docker build --tag "rustdesk-build-$PLATFORM_ARCH-$GITHUB_RUN_ID" .work/linux-recipe
# Forward only client build inputs, by environment name. No GitHub token or CI credentials.
args=()
for n in RUSTDESK_ID_SERVER RUSTDESK_RELAY_SERVER RUSTDESK_API_SERVER RUSTDESK_KEY RUSTDESK_PASSWORD;do args+=(-e "$n");done
docker run --rm "${args[@]}" -v "$source:/workspace" -v "$root:/custom:ro" -v "$root/.work/linux-recipe:/recipe:ro" -v /opt/artifacts:/opt/artifacts "rustdesk-build-$PLATFORM_ARCH-$GITHUB_RUN_ID" bash /recipe/build.sh
sudo chown -R "$(id -u):$(id -g)" "$source"
# Run the native ABI gate on the reviewed native runner with explicit runtime dependencies.
# The Ubuntu 18.04 container remains the official compiler/package environment.
python3 scripts/platform/platform_package.py create --tree "$source" --platform linux --arch "$PLATFORM_ARCH" --variant "$VARIANT"
