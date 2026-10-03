package com.billradar.rustdesk.signing.bridge;

import static org.junit.jupiter.api.Assertions.*;

import java.security.KeyPairGenerator;
import java.security.Signature;
import java.security.spec.ECGenParameterSpec;
import org.junit.jupiter.api.Test;

class WrongKeyTest {
    private final SigningIdentity allowed = TestFixtures.IDENTITY;

    @Test
    void rejectsSoftwareEcAndRsaKeys() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var provider = new RustDeskSigningProvider(
                new MockPkcs11Signer(allowed, pair.getPrivate()), () -> new char[]{'1'}, allowed);
        Signature signature = Signature.getInstance("SHA256withECDSA", provider);
        assertThrows(java.security.InvalidKeyException.class, () -> signature.initSign(pair.getPrivate()));

        var rsa = KeyPairGenerator.getInstance("RSA");
        rsa.initialize(2048);
        var rsaPair = rsa.generateKeyPair();
        assertThrows(java.security.InvalidKeyException.class, () -> signature.initSign(rsaPair.getPrivate()));
    }

    @Test
    void rejectsDifferentTokenObjectIdAndCertificateFingerprint() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var provider = new RustDeskSigningProvider(
                new MockPkcs11Signer(allowed, pair.getPrivate()), () -> new char[]{'1'}, allowed);
        Signature signature = Signature.getInstance("SHA256withECDSA", provider);

        assertThrows(java.security.InvalidKeyException.class, () -> signature.initSign(
                new RustDeskPivPrivateKey(new SigningIdentity("other-token", "02", TestFixtures.FAKE_CERT_FINGERPRINT))));
        assertThrows(java.security.InvalidKeyException.class, () -> signature.initSign(
                new RustDeskPivPrivateKey(new SigningIdentity("mock-token", "01", TestFixtures.FAKE_CERT_FINGERPRINT))));
        assertThrows(java.security.InvalidKeyException.class, () -> signature.initSign(
                new RustDeskPivPrivateKey(new SigningIdentity("mock-token", "02",
                        "FFEEDDCCBBAA99887766554433221100FFEEDDCCBBAA99887766554433221100"))));
    }

    @Test
    void failsClosedWhenBackendCertificateIdentityDiffers() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var wrongActual = new SigningIdentity("mock-token", "02",
                "FFEEDDCCBBAA99887766554433221100FFEEDDCCBBAA99887766554433221100");
        var mock = new MockPkcs11Signer(wrongActual, pair.getPrivate());
        char[] pin = {'1', '2', '3', '4', '5', '6'};
        java.util.concurrent.atomic.AtomicInteger pinRequests = new java.util.concurrent.atomic.AtomicInteger();
        Signature signature = Signature.getInstance("SHA256withECDSA",
                new RustDeskSigningProvider(mock, () -> {
                    pinRequests.incrementAndGet();
                    return pin;
                }, allowed));
        signature.initSign(new RustDeskPivPrivateKey(allowed));
        signature.update((byte) 1);
        assertThrows(java.security.SignatureException.class, signature::sign);
        assertEquals(0, mock.contextLoginCount);
        assertFalse(mock.signCalled);
        assertEquals(0, pinRequests.get());
        assertArrayEquals(new char[]{'1', '2', '3', '4', '5', '6'}, pin);
    }
}
