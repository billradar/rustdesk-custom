package com.billradar.rustdesk.signing.bridge;

/** Non-secret PKCS#11 failure information. Never include credential material. */
public final class Pkcs11Exception extends Exception {
    private final String returnCode;

    public Pkcs11Exception(String returnCode) {
        super("PKCS#11 operation failed: " + returnCode);
        this.returnCode = returnCode;
    }

    public Pkcs11Exception(String returnCode, Throwable cause) {
        super("PKCS#11 operation failed: " + returnCode, cause);
        this.returnCode = returnCode;
    }

    public String returnCode() {
        return returnCode;
    }
}
