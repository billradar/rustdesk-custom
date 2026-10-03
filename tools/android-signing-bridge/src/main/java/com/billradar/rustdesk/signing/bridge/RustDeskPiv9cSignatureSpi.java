package com.billradar.rustdesk.signing.bridge;

import java.security.InvalidKeyException;
import java.security.InvalidParameterException;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.SignatureException;
import java.security.SignatureSpi;
import java.security.NoSuchAlgorithmException;
import java.security.spec.AlgorithmParameterSpec;
import java.util.Arrays;
import java.util.HexFormat;

/** SHA256withECDSA bridge that requires context-specific PKCS#11 authentication per sign. */
public final class RustDeskPiv9cSignatureSpi extends SignatureSpi {
    static final String MECHANISM = "CKM_ECDSA";
    private final Pkcs11Signer signer;
    private final PinSupplier pinSupplier;
    private final SigningIdentity expectedIdentity;
    private final String digestAlgorithm;
    private MessageDigest digest;
    private boolean initialized;
    private RustDeskPivPrivateKey currentKey;

    RustDeskPiv9cSignatureSpi(
            Pkcs11Signer signer, PinSupplier pinSupplier, SigningIdentity expectedIdentity) {
        this(signer, pinSupplier, expectedIdentity, "SHA-256");
    }

    RustDeskPiv9cSignatureSpi(
            Pkcs11Signer signer, PinSupplier pinSupplier, SigningIdentity expectedIdentity,
            String digestAlgorithm) {
        this.signer = signer;
        this.pinSupplier = pinSupplier;
        this.expectedIdentity = expectedIdentity;
        this.digestAlgorithm = digestAlgorithm;
    }

    @Override
    protected void engineInitVerify(PublicKey publicKey) throws InvalidKeyException {
        initialized = false;
        currentKey = null;
        throw new InvalidKeyException("This provider exposes signing only");
    }

    @Override
    protected void engineInitSign(PrivateKey privateKey) throws InvalidKeyException {
        initialized = false;
        currentKey = null;
        if (!(privateKey instanceof RustDeskPivPrivateKey pivKey)) {
            throw new InvalidKeyException("Expected the configured non-exportable PIV key handle");
        }
        if (!"EC".equalsIgnoreCase(pivKey.getAlgorithm())
                || !SigningIdentity.PIV_9C_OBJECT_ID.equals(pivKey.identity().objectId())
                || !expectedIdentity.matches(pivKey.identity())) {
            throw new InvalidKeyException("PIV signing key identity does not match policy");
        }
        try {
            digest = MessageDigest.getInstance(digestAlgorithm);
        } catch (NoSuchAlgorithmException e) {
            throw new InvalidKeyException("SHA-256 is unavailable", e);
        }
        initialized = true;
        currentKey = pivKey;
    }

    @Override
    protected void engineUpdate(byte input) throws SignatureException {
        ensureInitialized();
        digest.update(input);
    }

    @Override
    protected void engineUpdate(byte[] input, int offset, int length) throws SignatureException {
        ensureInitialized();
        if (input == null || offset < 0 || length < 0 || offset > input.length - length) {
            throw new SignatureException("Invalid message range");
        }
        digest.update(input, offset, length);
    }

    @Override
    protected byte[] engineSign() throws SignatureException {
        ensureInitialized();
        byte[] hash = digest.digest();
        char[] pin = null;
        Pkcs11Session session = null;
        byte[] raw = null;
        byte[] der = null;
        SignatureException failure = null;
        boolean operationSucceeded = false;
        try {
            session = signer.openSession(expectedIdentity);
            if (session.certificateComponentBytes() != currentKey.componentBytes()) {
                throw new IllegalStateException("PIV key handle curve does not match the pinned certificate");
            }
            pin = pinSupplier.getPin();
            if (pin == null || pin.length == 0) {
                throw new IllegalStateException("PIN supplier returned no credential");
            }
            session.loginUser(pin);
            byte[] expectedId = HexFormat.of().parseHex(expectedIdentity.objectId());
            Pkcs11Session.KeyInfo keyInfo = session.findPrivateKey(expectedId);
            if (keyInfo == null || !Arrays.equals(expectedId, keyInfo.id())
                    || !Long.valueOf(org.xipki.pkcs11.wrapper.PKCS11Constants.CKK_EC)
                            .equals(keyInfo.keyType())
                    || !Boolean.TRUE.equals(keyInfo.canSign())
                    || !Boolean.TRUE.equals(keyInfo.alwaysAuthenticate())) {
                throw new IllegalStateException("Matching sign-capable EC private key is unavailable");
            }
            session.signInit(MECHANISM);
            session.contextSpecificLogin(pin);
            raw = session.sign(hash);
            der = RawEcdsaToDer.encode(raw, currentKey.componentBytes());
            operationSucceeded = true;
        } catch (Pkcs11Exception e) {
            failure = new SignatureException("Fail-closed PKCS#11 operation failed: " + e.returnCode());
        } catch (IllegalArgumentException | IllegalStateException e) {
            failure = new SignatureException("Fail-closed signing operation failed");
        } catch (Exception e) {
            failure = new SignatureException("Fail-closed signing operation failed; details suppressed");
        } finally {
            if (pin != null) {
                Arrays.fill(pin, '\0');
            }
            if (raw != null) {
                Arrays.fill(raw, (byte) 0);
            }
            Arrays.fill(hash, (byte) 0);
            digest.reset();
            initialized = false;
            currentKey = null;
            if (session != null) {
                try {
                    session.finishOperation(operationSucceeded);
                } catch (Pkcs11Exception closeFailure) {
                    if (failure == null) {
                        failure = new SignatureException(
                                "Failed to close PKCS#11 session: " + closeFailure.returnCode());
                    }
                }
            }
        }
        if (failure != null) {
            throw failure;
        }
        if (der != null) {
            return der;
        }
        throw new SignatureException("Signing failed without an error result");
    }

    @Override
    protected boolean engineVerify(byte[] signature) throws SignatureException {
        throw new SignatureException("This provider exposes signing only");
    }

    @Override
    @Deprecated
    protected void engineSetParameter(String parameter, Object value) {
        throw new InvalidParameterException("Parameters are not supported");
    }

    @Override
    @Deprecated
    protected Object engineGetParameter(String parameter) {
        throw new InvalidParameterException("Parameters are not supported");
    }

    private void ensureInitialized() throws SignatureException {
        if (!initialized || digest == null) {
            throw new SignatureException("Signature is not initialized for signing");
        }
    }
}
