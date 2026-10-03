package com.billradar.rustdesk.signing.bridge;

import static org.junit.jupiter.api.Assertions.*;

import java.security.Signature;
import java.security.SignatureException;
import java.util.Arrays;
import org.junit.jupiter.api.Test;

class PinZeroizationTest {
    @Test
    void clearsPinWhenSigningThrowsAfterSuccessfulLogin() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var mock = new MockPkcs11Signer(TestFixtures.IDENTITY, pair.getPrivate());
        mock.failurePoint = MockPkcs11Signer.FailurePoint.SIGN;
        char[] pin = {'6', '5', '4', '3', '2', '1'};
        Signature signature = Signature.getInstance("SHA256withECDSA",
                new RustDeskSigningProvider(mock, () -> pin, TestFixtures.IDENTITY));
        signature.initSign(new RustDeskPivPrivateKey(TestFixtures.IDENTITY));
        signature.update((byte) 1);

        assertThrows(SignatureException.class, signature::sign);
        assertArrayEquals(new char[pin.length], pin);
        assertEquals(1, mock.contextLoginCount);
        assertTrue(mock.signCalled);
        assertTrue(mock.calls.contains("CLOSE"));
    }

    @Test
    void clearsPinWhenContextLoginThrowsRuntimeException() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var mock = new MockPkcs11Signer(TestFixtures.IDENTITY, pair.getPrivate());
        mock.failurePoint = MockPkcs11Signer.FailurePoint.RUNTIME_LOGIN;
        char[] pin = {'9', '8', '7', '6', '5', '4'};
        Signature signature = Signature.getInstance("SHA256withECDSA",
                new RustDeskSigningProvider(mock, () -> pin, TestFixtures.IDENTITY));
        signature.initSign(new RustDeskPivPrivateKey(TestFixtures.IDENTITY));
        signature.update((byte) 2);

        assertThrows(SignatureException.class, signature::sign);
        assertArrayEquals(new char[pin.length], pin);
        assertEquals(1, mock.contextLoginCount);
        assertEquals(0, mock.signCount);
        assertFalse(mock.signCalled);
        assertTrue(mock.calls.contains("CLOSE"));
    }

    @Test
    void keyAndSpiDoNotHoldPinBuffers() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var mock = new MockPkcs11Signer(TestFixtures.IDENTITY, pair.getPrivate());
        var provider = new RustDeskSigningProvider(
                mock, () -> new char[]{'1'}, TestFixtures.IDENTITY);
        var key = new RustDeskPivPrivateKey(TestFixtures.IDENTITY);
        Signature signature = Signature.getInstance("SHA256withECDSA", provider);
        signature.initSign(key);
        Object spi = provider.getService("Signature", "SHA256withECDSA").newInstance(null);
        for (var field : key.getClass().getDeclaredFields()) {
            assertNotEquals(char[].class, field.getType());
            assertNotEquals(byte[].class, field.getType());
        }
        for (var field : spi.getClass().getDeclaredFields()) {
            assertNotEquals(char[].class, field.getType());
            assertNotEquals(byte[].class, field.getType());
        }
    }
}
