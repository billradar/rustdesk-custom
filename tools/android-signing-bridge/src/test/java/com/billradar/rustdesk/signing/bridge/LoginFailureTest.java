package com.billradar.rustdesk.signing.bridge;

import static org.junit.jupiter.api.Assertions.*;

import java.security.Signature;
import java.security.SignatureException;
import java.util.List;
import org.junit.jupiter.api.Test;

class LoginFailureTest {
    @Test
    void contextLoginFailureAbortsWithoutRetryOrSign() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var mock = new MockPkcs11Signer(TestFixtures.IDENTITY, pair.getPrivate());
        mock.failurePoint = MockPkcs11Signer.FailurePoint.LOGIN;
        char[] pin = {'1', '2', '3', '4', '5', '6'};
        var provider = new RustDeskSigningProvider(mock, () -> pin, TestFixtures.IDENTITY);
        Signature signature = Signature.getInstance("SHA256withECDSA", provider);
        signature.initSign(new RustDeskPivPrivateKey(TestFixtures.IDENTITY));
        signature.update((byte) 7);

        assertThrows(SignatureException.class, signature::sign);
        assertEquals(List.of("OPEN", "SIGN_INIT", "CONTEXT_LOGIN", "CLOSE"), mock.calls);
        assertEquals(1, mock.contextLoginCount);
        assertEquals(0, mock.signCount);
        assertFalse(mock.signCalled);
        assertArrayEquals(new char[pin.length], pin);
    }
}
