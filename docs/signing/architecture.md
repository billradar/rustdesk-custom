# Android production signing architecture

The production Android signing path is deliberately separated from the ordinary build graph.

## Flow

1. `tag.yml` resolves the exact upstream revision and verifies CI qualification.
2. `android-build` produces unsigned Standard Android artifacts.
3. `android-sign` runs only on the dedicated self-hosted ARM64 signing runner.
4. The `android-production-signing` Environment supplies `YUBIKEY_PIV_PIN` only to the preflight/signing steps.
5. `android_yubikey_sign.py` validates artifact provenance, package identity, ABI and the pinned signer certificate before invoking the local signing helper.
6. `aggregate` requires successful production signing before a Stable artifact can proceed to Draft/Release.

The reusable `build.yml` workflow never owns the production signer and never receives the YubiKey PIN.

## Trust boundaries

- Build runners: produce and validate unsigned artifacts.
- Signing runner: hardware-backed signing only.
- YubiKey PIV 9C: private key remains non-exportable.
- GitHub Environment: controls access to the PIN.
- Certificate fingerprint: fail-closed identity anchor.

Production release publication remains a separate manual release-mode decision.
