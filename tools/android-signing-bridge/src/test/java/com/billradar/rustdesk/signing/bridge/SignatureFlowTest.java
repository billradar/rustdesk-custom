package com.billradar.rustdesk.signing.bridge;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.Signature;
import java.util.Arrays;
import java.util.List;
import org.junit.jupiter.api.Test;

class SignatureFlowTest {
    @Test
    void hashesOnceSignsInRequiredOrderAndProducesVerifiableDer() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var mock = new MockPkcs11Signer(TestFixtures.IDENTITY, pair.getPrivate());
        char[] testPin = {'1', '2', '3', '4', '5', '6'};
        var provider = new RustDeskSigningProvider(mock, () -> testPin, TestFixtures.IDENTITY);
        var key = new RustDeskPivPrivateKey(TestFixtures.IDENTITY);
        byte[] message = "mock-only rustdesk signing bridge".getBytes(StandardCharsets.UTF_8);

        Signature signature = Signature.getInstance("SHA256withECDSA", provider);
        signature.initSign(key);
        signature.update(message);
        byte[] der = signature.sign();

        assertEquals(List.of("OPEN", "SIGN_INIT", "CONTEXT_LOGIN", "SIGN", "CLOSE"), mock.calls);
        assertEquals("CKM_ECDSA", mock.lastMechanism);
        assertEquals(1, mock.contextLoginCount);
        assertEquals(1, mock.signCount);
        assertArrayEquals(MessageDigest.getInstance("SHA-256").digest(message), mock.lastDigest);
        assertEquals(32, mock.lastDigest.length);
        assertTrue(der.length >= 8 && der[0] == 0x30);

        Signature verifier = Signature.getInstance("SHA256withECDSA");
        verifier.initVerify(pair.getPublic());
        verifier.update(message);
        assertTrue(verifier.verify(der));
        assertArrayEquals(new char[testPin.length], testPin);
    }

    @Test
    void reportsNonExportableOpaqueKey() {
        var key = new RustDeskPivPrivateKey(TestFixtures.IDENTITY);
        assertEquals("EC", key.getAlgorithm());
        assertNull(key.getFormat());
        assertNull(key.getEncoded());
    }
}
