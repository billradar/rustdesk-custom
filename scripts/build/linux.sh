#!/usr/bin/env bash
set -euo pipefail
: "${PLATFORM_ARCH:?}" "${VARIANT:?}" "${PREPARED_SOURCE_DIR:?}"
root=$PWD
source=$PREPARED_SOURCE_DIR
configuration=${BUILD_CONFIGURATION:-PRODUCTION}
case "$configuration" in
  PRODUCTION)
    # Candidate CI source must never enter production packaging/signing.
    [[ "${BUILD_CHANNEL:-stable}" != ci ]] || {
      echo 'BUILD_COMPAT: CI-only source cannot enter production Linux build' >&2
      exit 1
    }
    python3 scripts/signing/production_config.py inputs
    ;;
  CI_TEST|CI_PACKAGE_TEST)
    # Both CI modes share Stable's exact platform/vcpkg/recipe preparation.
    # CI_PACKAGE_TEST builds test-only packages, but never runs production
    # qualification, signing or artifact publication.
    [[ "${BUILD_CHANNEL:-}" == ci && "${PATCHSET:-}" == v4 &&
       "${GITHUB_ACTIONS:-}" == true &&
       ( "${GITHUB_EVENT_NAME:-}" == pull_request ||
         "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ) &&
       "${BUILD_FLAVOR:-}" == '' &&
       ( "$VARIANT" == standard || "$VARIANT" == sos ) ]] || {
      echo 'BUILD_COMPAT: CI Linux probe context forbidden' >&2
      exit 1
    }
    python3 - "$source" "$root" "${UPSTREAM_EXPECTED_SHA:?}" <<'PY'
from pathlib import Path
import re,subprocess,sys
tree=Path(sys.argv[1]).resolve()
root=Path(sys.argv[2]).resolve()
sha=sys.argv[3]
if tree != root/'.work/native/source':
    raise ValueError('BUILD_COMPAT: CI source must be the isolated staging tree')
if not re.fullmatch(r'[0-9a-f]{40}',sha):
    raise ValueError('BUILD_COMPAT: immutable upstream SHA required')
actual=subprocess.check_output(['git','-C',str(tree),'rev-parse','HEAD'],text=True).strip()
if actual!=sha:
    raise ValueError('BUILD_COMPAT: CI source identity mismatch')
PY
    source scripts/validation/test_config.sh
    [[ "$RUSTDESK_ID_SERVER" == test.invalid &&
       "$RUSTDESK_API_SERVER" == https://api.test.invalid ]] || {
      echo 'BUILD_COMPAT: CI probe must use fictional test configuration' >&2
      exit 1
    }
    ;;
  *)
    echo 'BUILD_COMPAT: invalid Linux build configuration' >&2
    exit 1
    ;;
esac
if [[ "${FORMAL_VALIDATION:-}" == true ]]; then
    [[ "$configuration" == CI_PACKAGE_TEST && "${PLATFORM:-}" == linux ]] || exit 1
    python3 -c 'import os; from scripts.build.formal_validation import worker_identity; worker_identity(os.environ["PREPARED_SOURCE_DIR"])'
fi
python3 scripts/platform/platform_adapter.py "$source" --platform linux --arch "$PLATFORM_ARCH" --channel "${BUILD_CHANNEL:-stable}" --output .work/platform-profile.json --linux-scripts .work/linux-recipe
if [[ "$configuration" == CI_TEST || "$configuration" == CI_PACKAGE_TEST ]]; then
  python3 - <<'PY'
import json
from pathlib import Path
profile=json.loads(Path('.work/platform-profile.json').read_text())
if (profile.get('ci_candidate_only') is not True or
    profile.get('stable_allowed') is not False or
    profile.get('platform_review_status')!='CI_CANDIDATE_NOT_RELEASE_APPROVED'):
    raise ValueError('BUILD_COMPAT: CI candidate cannot claim release approval')
import os
if os.environ.get('FORMAL_VALIDATION')=='true' and (profile.get('production_recipe_approved') is not True or profile.get('release_eligible') is not False):
    raise ValueError('BUILD_COMPAT: formal Linux recipe approval missing')
PY
fi
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
if [[ "$configuration" == CI_TEST ]]; then
  # Same-run Bridge was restored by Stable's hash and source identity verifier.
  test -s "$source/src/bridge_generated.rs"
  test -s "$source/src/bridge_generated.io.rs"
  test -f "$VCPKG_ROOT/installed/$triplet/lib/libavcodec.a"
  test -f "$VCPKG_ROOT/installed/$triplet/lib/libavutil.a"
  test -f "$VCPKG_ROOT/installed/$triplet/lib/libavformat.a"
  mkdir -p .work/native
  (
    cd "$source"
    cargo check --locked --lib --features hwcodec,flutter,unix-file-copy-paste 2>&1 |
      tee "$root/.work/native/cargo-native.log"
  )
  echo 'BUILD_COMPAT: Linux CI candidate native probe PASS (no package or publication)'
  exit 0
fi
# No runtime source/config in an image layer. Only official build dependencies are cached here.
case "$PLATFORM_ARCH" in
 x86_64) image=amd64/ubuntu:18.04 ;;
 aarch64) image=arm64v8/ubuntu:18.04 ;;
 *) exit 1 ;;
esac
printf 'FROM %s\nCOPY install.sh /install.sh\nRUN bash /install.sh\n' "$image" > .work/linux-recipe/Dockerfile
docker build --tag "rustdesk-build-$PLATFORM_ARCH-$VARIANT-$GITHUB_RUN_ID" .work/linux-recipe
# Forward only client build inputs, by environment name. No GitHub token or CI credentials.
args=()
for n in RUSTDESK_ID_SERVER RUSTDESK_RELAY_SERVER RUSTDESK_API_SERVER RUSTDESK_KEY RUSTDESK_PASSWORD;do args+=(-e "$n");done
docker run --rm "${args[@]}" -v "$source:/workspace" -v "$root:/custom:ro" -v "$root/.work/linux-recipe:/recipe:ro" -v /opt/artifacts:/opt/artifacts "rustdesk-build-$PLATFORM_ARCH-$VARIANT-$GITHUB_RUN_ID" bash /recipe/build.sh
sudo chown -R "$(id -u):$(id -g)" "$source"
if [[ "$configuration" == CI_PACKAGE_TEST ]]; then
  # Never call production_config/platform_package.create for fictional binaries.
  # Verify actual DEB/RPM payloads in an isolated, non-publishing CI context.
  python3 -m scripts.build.linux_ci_package \
    --tree "$source" --arch "$PLATFORM_ARCH" --variant "$VARIANT" \
    --output "$root/.work/native/package-report.json"
  echo 'BUILD_COMPAT: CI-only Linux package smoke PASS, not release eligible'
  exit 0
fi
# Run the native ABI gate on the reviewed native runner with explicit runtime dependencies.
# The Ubuntu 18.04 container remains the official compiler/package environment.
python3 scripts/platform/platform_package.py create --tree "$source" --platform linux --arch "$PLATFORM_ARCH" --variant "$VARIANT"
