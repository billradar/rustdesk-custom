package com.billradar.rustdesk.signing.bridge;

/** Opens an operation-scoped session for the configured token/key/certificate identity. */
@FunctionalInterface
public interface Pkcs11Signer {
    /** Opens a public-identity-verified session. Private objects are discovered only after login. */
    Pkcs11Session openSession(SigningIdentity expectedIdentity) throws Pkcs11Exception;
}
