package com.billradar.rustdesk.signing.bridge;

/** Narrow, sign-only session contract. Implementations must bind this session to the expected identity. */
public interface Pkcs11Session extends AutoCloseable {
    int certificateComponentBytes() throws Pkcs11Exception;

    record KeyInfo(byte[] id, Long keyType, Boolean canSign, Boolean alwaysAuthenticate) {
        public KeyInfo { id = id == null ? null : id.clone(); }
        @Override public byte[] id() { return id == null ? null : id.clone(); }
    }

    void loginUser(char[] pin) throws Pkcs11Exception;

    KeyInfo findPrivateKey(byte[] expectedId) throws Pkcs11Exception;

    void signInit(String mechanism) throws Pkcs11Exception;

    void contextSpecificLogin(char[] pin) throws Pkcs11Exception;

    /** Signs the already-computed digest using the initialized operation and returns raw r || s. */
    byte[] sign(byte[] digest) throws Pkcs11Exception;

    /** Releases an operation lease. Session providers may keep one authenticated session per process. */
    default void finishOperation(boolean succeeded) throws Pkcs11Exception { close(); }

    @Override
    void close() throws Pkcs11Exception;
}
