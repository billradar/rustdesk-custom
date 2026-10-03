package com.billradar.rustdesk.signing.bridge;

/** Opens an operation-scoped session for the configured token/key/certificate identity. */
@FunctionalInterface
public interface Pkcs11Signer {
    /**
     * Opens an operation-scoped session, selects the expected token, locates its private object by
     * ID, reads the associated certificate, and compares its actual DER SHA-256 fingerprint with
     * {@code expectedIdentity} before returning. Implementations must fail closed.
     */
    Pkcs11Session openSession(SigningIdentity expectedIdentity) throws Pkcs11Exception;
}
