#!/usr/bin/env bash
# Shared official Flutter 3.44 Bridge generator; callers own admission/receipts.
set -euo pipefail
: "${UPSTREAM_EXPECTED_SHA:?}" "${CARGO_EXPAND:?}" "${FRB:?}" "${BRIDGE_FLUTTER:?}"
[[ "$UPSTREAM_EXPECTED_SHA" =~ ^[0-9a-f]{40}$ && "$(git rev-parse HEAD)" == "$UPSTREAM_EXPECTED_SHA" ]] || { echo 'Bridge source mismatch' >&2; exit 1; }
[[ "$CARGO_EXPAND" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$FRB" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
flutter --version --machine | python3 -c 'import json,os,sys; actual=json.load(sys.stdin)["frameworkVersion"]; sys.exit(0 if actual==os.environ["BRIDGE_FLUTTER"] else "Bridge Flutter SDK mismatch")'
cargo install cargo-expand --version "$CARGO_EXPAND" --locked
cargo install flutter_rust_bridge_codegen --version "$FRB" --features uuid --locked
bash .github/patches/apply_flutter_3.44_source_patches.sh
(cd flutter && flutter pub get)
flutter_rust_bridge_codegen --rust-input ./src/flutter_ffi.rs --dart-output ./flutter/lib/generated_bridge.dart --c-output ./flutter/macos/Runner/bridge_generated.h
cp flutter/macos/Runner/bridge_generated.h flutter/ios/Runner/bridge_generated.h
