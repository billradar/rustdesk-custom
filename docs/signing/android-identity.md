# Android production signing identity

The production identity is anchored to the certificate fingerprint rather than to a filename, alias alone, or software keystore.

- Package: `com.carriez.flutter_hbb`
- PIV slot: `9C`
- PKCS#11 object ID: `02`
- Certificate SHA-256: `559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5`

The machine-readable source of truth is `metadata/signing/android-standard.json`. Legacy and current production identities are stored as separate fields because their certificates are intentionally different.

The repository's Android signing contract verifies that workflow configuration, signing helper and identity metadata remain aligned.
