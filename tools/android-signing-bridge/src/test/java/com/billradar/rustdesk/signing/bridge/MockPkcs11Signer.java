package com.billradar.rustdesk.signing.bridge;

import java.security.GeneralSecurityException;
import java.security.PrivateKey;
import java.security.Signature;
import java.security.interfaces.ECPrivateKey;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Software-only PKCS#11 simulation. It never loads a native module. */
final class MockPkcs11Signer implements Pkcs11Signer {
    enum FailurePoint { NONE, OPEN, USER_LOGIN, LOGIN, RUNTIME_LOGIN, SIGN, CLOSE }

    final List<String> calls = new ArrayList<>();
    final SigningIdentity actualIdentity;
    final PrivateKey softwareKey;
    FailurePoint failurePoint = FailurePoint.NONE;
    int contextLoginCount;
    int signCount;
    int lastRawLength;
    final List<Integer> digestLengths = new ArrayList<>();
    boolean signCalled;
    byte[] lastDigest;
    String lastMechanism;

    MockPkcs11Signer(SigningIdentity actualIdentity, PrivateKey softwareKey) {
        this.actualIdentity = actualIdentity;
        this.softwareKey = softwareKey;
    }

    @Override
    public Pkcs11Session openSession(SigningIdentity expectedIdentity) throws Pkcs11Exception {
        calls.add("OPEN");
        if (failurePoint == FailurePoint.OPEN || !actualIdentity.matches(expectedIdentity)) {
            throw new Pkcs11Exception("CKR_OBJECT_HANDLE_INVALID");
        }
        return new Session();
    }

    private final class Session implements Pkcs11Session {
        private boolean initialized;
        private boolean loggedIn;
        private boolean contextLoggedIn;
        private boolean closed;

        @Override
        public int certificateComponentBytes() {
            return ((((ECPrivateKey) softwareKey).getParams().getOrder().bitLength()) + 7) / 8;
        }

        @Override
        public void loginUser(char[] pin) throws Pkcs11Exception {
            require(!closed && !loggedIn, "CKR_USER_ALREADY_LOGGED_IN");
            calls.add("USER_LOGIN");
            if (failurePoint == FailurePoint.USER_LOGIN) throw new Pkcs11Exception("CKR_PIN_INCORRECT");
            loggedIn = true;
        }

        @Override
        public KeyInfo findPrivateKey(byte[] expectedId) throws Pkcs11Exception {
            require(loggedIn && !initialized && !closed, "CKR_USER_NOT_LOGGED_IN");
            calls.add("KEY_DISCOVERY");
            byte[] actualId = java.util.HexFormat.of().parseHex(actualIdentity.objectId());
            if (!Arrays.equals(actualId, expectedId)) return null;
            return new KeyInfo(actualId, org.xipki.pkcs11.wrapper.PKCS11Constants.CKK_EC,
                    true, true);
        }

        @Override
        public void signInit(String mechanism) throws Pkcs11Exception {
            require(!closed && loggedIn && !initialized, "CKR_OPERATION_ACTIVE");
            calls.add("SIGN_INIT");
            lastMechanism = mechanism;
            if (!RustDeskPiv9cSignatureSpi.MECHANISM.equals(mechanism)) {
                throw new Pkcs11Exception("CKR_MECHANISM_INVALID");
            }
            initialized = true;
        }

        @Override
        public void contextSpecificLogin(char[] pin) throws Pkcs11Exception {
            require(initialized && loggedIn && !contextLoggedIn, "CKR_OPERATION_NOT_INITIALIZED");
            calls.add("CONTEXT_LOGIN");
            contextLoginCount++;
            if (failurePoint == FailurePoint.LOGIN) {
                throw new Pkcs11Exception("CKR_PIN_INCORRECT");
            }
            if (failurePoint == FailurePoint.RUNTIME_LOGIN) {
                throw new IllegalStateException("mock runtime failure");
            }
            contextLoggedIn = true;
        }

        @Override
        public byte[] sign(byte[] digest) throws Pkcs11Exception {
            require(initialized && loggedIn && contextLoggedIn && !closed, "CKR_USER_NOT_LOGGED_IN");
            calls.add("SIGN");
            signCount++;
            signCalled = true;
            if (failurePoint == FailurePoint.SIGN) {
                throw new Pkcs11Exception("CKR_GENERAL_ERROR");
            }
            if (digest.length != 32 && digest.length != 48 && digest.length != 64) {
                throw new Pkcs11Exception("CKR_DATA_LEN_RANGE");
            }
            digestLengths.add(digest.length);
            lastDigest = digest.clone();
            try {
                Signature softwareSignature = Signature.getInstance("NONEwithECDSA");
                softwareSignature.initSign(softwareKey);
                softwareSignature.update(digest);
                byte[] der = softwareSignature.sign();
                int componentBytes = ((((ECPrivateKey) softwareKey).getParams().getOrder().bitLength()) + 7) / 8;
                byte[] raw = RawEcdsaToDer.decode(der, componentBytes);
                lastRawLength = raw.length;
                return raw;
            } catch (GeneralSecurityException | IllegalArgumentException e) {
                throw new Pkcs11Exception("CKR_GENERAL_ERROR", e);
            }
        }

        @Override
        public void close() throws Pkcs11Exception {
            if (!closed) {
                calls.add("CLOSE");
                closed = true;
                if (failurePoint == FailurePoint.CLOSE) {
                    throw new Pkcs11Exception("CKR_GENERAL_ERROR");
                }
            }
        }

        private void require(boolean condition, String returnCode) throws Pkcs11Exception {
            if (!condition) {
                throw new Pkcs11Exception(returnCode);
            }
        }
    }
}
