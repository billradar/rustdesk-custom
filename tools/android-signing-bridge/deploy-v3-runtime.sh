#!/usr/bin/env bash
# Manually deploy the already-reviewed v2+v3 bridge to the dedicated signing runner.
# This performs build/unit tests and read-only post-deploy checks only; it never signs an APK.
set -Eeuo pipefail

if [[ "${AUTHORIZE_V3_RUNTIME_DEPLOY:-}" != "YES" ]]; then
  printf '%s\n' 'Refusing deployment. Set AUTHORIZE_V3_RUNTIME_DEPLOY=YES after reviewing the diff.' >&2
  exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)
BRIDGE="$REPO_ROOT/tools/android-signing-bridge"
INSTALL_ROOT=/opt/rustdesk-signing-bridge
STABLE=/usr/local/bin/rustdesk-sign
JAVA_JAR="$INSTALL_ROOT/lib/rustdesk-android-signing-bridge.jar"

[[ "$(git -C "$REPO_ROOT" remote get-url origin)" == "https://github.com/billradar/rustdesk-custom.git" ]] || {
  printf '%s\n' 'Repository remote mismatch; refusing deployment.' >&2
  exit 2
}
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "main" ]] || {
  printf '%s\n' 'Deployment must run from the reviewed main branch.' >&2
  exit 2
}
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
  printf '%s\n' 'Working tree is not clean; refusing deployment.' >&2
  exit 2
}
[[ -f "$BRIDGE/src/main/java/com/billradar/rustdesk/signing/bridge/RealYubikeyApksigOneShot.java" ]]
grep -Fq 'EXPECTED_HARDWARE_SIGNATURE_COUNT = 3' "$BRIDGE/src/main/java/com/billradar/rustdesk/signing/bridge/RealYubikeyApksigOneShot.java"
grep -Fq '"setV3SigningEnabled", boolean.class, true' "$BRIDGE/src/main/java/com/billradar/rustdesk/signing/bridge/RealYubikeyApksigOneShot.java"

command -v mvn >/dev/null
command -v jar >/dev/null
sudo -v

# Unit tests do not access the YubiKey or perform a private-key operation.
(cd "$BRIDGE" && mvn -q clean test package)

STAGE=$(mktemp -d /tmp/rustdesk-v3-runtime-deploy.XXXXXX)
BACKUP=''
ROLLBACK_REQUIRED=0
cleanup() {
  status=$?
  if [[ "$ROLLBACK_REQUIRED" == 1 && -n "$BACKUP" ]]; then
    printf '%s\n' 'Deployment check failed; restoring previous runtime files.' >&2
    sudo install -o root -g root -m 755 "$BACKUP/rustdesk-sign" "$INSTALL_ROOT/bin/rustdesk-sign"
    sudo install -o root -g root -m 644 "$BACKUP/bridge.jar" "$JAVA_JAR"
    sudo install -o root -g root -m 644 "$BACKUP/VERSION" "$INSTALL_ROOT/VERSION"
    sudo install -o root -g root -m 644 "$BACKUP/MANIFEST.sha256" "$INSTALL_ROOT/MANIFEST.sha256"
  fi
  if [[ -n "$BACKUP" ]]; then sudo rm -rf -- "$BACKUP"; fi
  rm -rf -- "$STAGE"
  exit "$status"
}
trap cleanup EXIT

jar --create --file "$STAGE/rustdesk-android-signing-bridge.jar" -C "$BRIDGE/target/classes" .
jar tf "$STAGE/rustdesk-android-signing-bridge.jar" | grep -Fxq \
  'com/billradar/rustdesk/signing/bridge/RealYubikeyApksigOneShot.class'
printf '%s\n' '0.2.0-v2-v3' > "$STAGE/VERSION"

[[ -d "$INSTALL_ROOT/lib" && -d "$INSTALL_ROOT/bin" ]]
[[ -r "$INSTALL_ROOT/lib/ipkcs11wrapper-1.0.9.jar" && -r "$INSTALL_ROOT/lib/apksig-0.9.jar" ]]
[[ -L "$STABLE" && "$(readlink -f "$STABLE")" == "$INSTALL_ROOT/bin/rustdesk-sign" ]]

BACKUP=$(sudo mktemp -d /tmp/rustdesk-v3-runtime-backup.XXXXXX)
sudo cp -a "$INSTALL_ROOT/bin/rustdesk-sign" "$BACKUP/rustdesk-sign"
sudo cp -a "$JAVA_JAR" "$BACKUP/bridge.jar"
sudo cp -a "$INSTALL_ROOT/VERSION" "$BACKUP/VERSION"
sudo cp -a "$INSTALL_ROOT/MANIFEST.sha256" "$BACKUP/MANIFEST.sha256"
ROLLBACK_REQUIRED=1

sudo install -o root -g root -m 755 "$BRIDGE/packaging/rustdesk-sign" "$INSTALL_ROOT/bin/rustdesk-sign"
sudo install -o root -g root -m 644 "$STAGE/rustdesk-android-signing-bridge.jar" "$JAVA_JAR"
sudo install -o root -g root -m 644 "$STAGE/VERSION" "$INSTALL_ROOT/VERSION"
sudo bash -euc 'cd "$1"; sha256sum bin/rustdesk-sign lib/rustdesk-android-signing-bridge.jar lib/ipkcs11wrapper-1.0.9.jar lib/apksig-0.9.jar VERSION > MANIFEST.sha256; chown root:root MANIFEST.sha256; chmod 644 MANIFEST.sha256' _ "$INSTALL_ROOT"

sudo "$STABLE" --verify-install
CAPABILITIES=$(sudo -n -u github-runner "$STABLE" --capabilities)
printf '%s\n' "$CAPABILITIES"
grep -Fq 'APK SIGNING SCHEMES: v1=YES, v2=YES, v3=YES, v3.1=NO, v4=NO' <<< "$CAPABILITIES"
grep -Fq 'PIN REQUESTED: NO' <<< "$CAPABILITIES"
grep -Fq 'PRIVATE KEY OPERATION: NO' <<< "$CAPABILITIES"

# Read-only token/certificate discovery only. No PIN is injected and no signing is performed.
SELF_TEST=$(sudo -n -u github-runner "$STABLE" --self-test)
printf '%s\n' "$SELF_TEST"
grep -Fq 'INSTALLED BRIDGE SELF-TEST: PASS' <<< "$SELF_TEST"
grep -Fq 'PIN REQUESTED: NO' <<< "$SELF_TEST"
grep -Fq 'PRIVATE KEY OPERATION: NO' <<< "$SELF_TEST"

ROLLBACK_REQUIRED=0
printf '%s\n' 'V2+V3 RUNTIME DEPLOYMENT: PASS' 'APK SIGNING PERFORMED: NO'
