# Production signing interface

## Inputs

The production signing action consumes only the exact Stable Standard Android artifacts selected by the qualification/preparation chain.

Required identity inputs:

- upstream SHA
- upstream version
- patchset
- expected certificate fingerprint
- expected Android package: `com.carriez.flutter_hbb`

Required hardware secret:

- GitHub Environment secret `YUBIKEY_PIV_PIN`

## Outputs

For each supported Android ABI, the action produces a signed artifact and validation metadata. The signer certificate must match the pinned production identity.

## Failure policy

Signing fails closed when:

- the Environment secret is unavailable;
- artifact provenance/checksum does not match;
- package identity is unexpected;
- ABI is unexpected;
- the signer fingerprint differs from the pinned identity;
- the signing helper or hardware operation fails.

No fallback software key is permitted.
