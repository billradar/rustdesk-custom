# Android signing operations

## Normal CI

Normal CI builds and validates Android artifacts without exposing the production PIN or invoking the YubiKey signer.

## Stable production signing

Production signing requires an explicitly dispatched Stable workflow satisfying all authorization gates. The dedicated signing job then:

1. checks the public signing identity metadata;
2. verifies Environment secret availability without printing its value;
3. downloads the exact build artifacts;
4. validates provenance and package/ABI constraints;
5. performs hardware-backed signing;
6. verifies the resulting certificate identity;
7. uploads signed artifacts for downstream aggregation.

Do not repeat hardware signing merely to reproduce historical evidence. Use the existing validation records unless a new production decision requires a fresh run.

## Incident response

If signer identity, workflow authorization, artifact provenance or runner integrity is uncertain, stop production signing. Do not bypass the fingerprint gate or substitute a software keystore.
