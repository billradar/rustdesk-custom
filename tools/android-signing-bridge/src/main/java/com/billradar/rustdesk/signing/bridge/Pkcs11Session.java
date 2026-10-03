package com.billradar.rustdesk.signing.bridge;

/** Narrow, sign-only session contract. Implementations must bind this session to the expected identity. */
public interface Pkcs11Session extends AutoCloseable {
    void signInit(String mechanism) throws Pkcs11Exception;

    void contextSpecificLogin(char[] pin) throws Pkcs11Exception;

    /** Signs the already-computed digest using the initialized operation and returns raw r || s. */
    byte[] sign(byte[] digest) throws Pkcs11Exception;

    @Override
    void close() throws Pkcs11Exception;
}
