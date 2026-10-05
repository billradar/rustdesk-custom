# Android signing runner security

The production signer uses a dedicated Raspberry Pi ARM64 runner with labels:

`self-hosted`, `linux`, `arm64`, `rustdesk-signing`, `android-signing`, `yubikey`.

## Required controls

- Dedicated runner account and service.
- OpenSC/PCSC access restricted to the runner account/group.
- YubiKey PIV 9C private key is never exported.
- Signing Environment is `android-production-signing`.
- `YUBIKEY_PIV_PIN` is injected only at the signing boundary.
- Signing job uses a non-canceling concurrency group.
- Workflow checks repository, branch and caller identity before hardware use.
- Artifact provenance and signer certificate fingerprint are checked before accepting a signature.
- Ordinary CI and reusable build workflows cannot request production signing.

## Hardware identity

The pinned production certificate fingerprint is:

`559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5`

PIV slot: `9C`; PKCS#11 object ID: `02`.

Read-only hardware discovery and the subsequent real signing validation are historical evidence in `docs/archive/signing/`; this document is the current security contract.

## Threat boundary

Hardware non-exportability does not prevent an authorized workflow from asking the key to sign malicious input. Therefore the main protection is strict workflow authorization plus same-run artifact/provenance validation, not the YubiKey alone.
