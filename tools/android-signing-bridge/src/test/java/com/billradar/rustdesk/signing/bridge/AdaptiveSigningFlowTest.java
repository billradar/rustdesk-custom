package com.billradar.rustdesk.signing.bridge;

import static org.junit.jupiter.api.Assertions.*;

import java.security.GeneralSecurityException;
import java.security.KeyPair;
import java.security.MessageDigest;
import java.security.Signature;
import java.security.interfaces.ECPublicKey;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class AdaptiveSigningFlowTest {
    private static final byte[] CERT_DER = {0x30, 0x03, 0x01, 0x01, 0x00};

    @Test
    void certificateCkaIdSelectsMatchingKeyAndNeverFallsBackToOtherIds() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var fixture = fixture(pair, true, List.of(
                key(0x04, pair, true), key(0x31, pair, true)));
        char[] pin = {'1', '2', '3', '4'};
        var result = AdaptiveSigningFlow.signOnce(
                "certificate-bound".getBytes(), fixture.policy, fixture.backend,
                () -> pin, fixture.events::add);
        assertEquals(0x31, fixture.backend.target.selectedId[0]);
        assertEquals(32, result.componentBytes());
        assertTrue(result.contextLoginUsed());
        assertEquals(List.of("USER_LOGIN", "KEY_DISCOVERY", "SIGN_INIT", "CONTEXT_LOGIN", "SIGN", "CLOSE"),
                fixture.backend.target.calls);
        assertTrue(allZero(pin));
    }

    @Test
    void p256P384AndP521ComponentLengthsComeFromCertificatePublicKey() throws Exception {
        assertEquals(32, AdaptiveSigningRules.ecComponentBytes(
                TestFixtures.ecKeyPair("secp256r1").getPublic()));
        assertEquals(48, AdaptiveSigningRules.ecComponentBytes(
                TestFixtures.ecKeyPair("secp384r1").getPublic()));
        assertEquals(66, AdaptiveSigningRules.ecComponentBytes(
                TestFixtures.ecKeyPair("secp521r1").getPublic()));
    }

    @Test
    void alwaysAuthenticateControlsContextLogin() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var yes = fixture(pair, true, List.of(key(0x31, pair, true)));
        AdaptiveSigningFlow.signOnce(new byte[]{1}, yes.policy, yes.backend,
                () -> new char[]{'1'}, yes.events::add);
        assertTrue(yes.backend.target.calls.contains("CONTEXT_LOGIN"));

        var no = fixture(pair, false, List.of(key(0x31, pair, false)));
        var result = AdaptiveSigningFlow.signOnce(new byte[]{2}, no.policy, no.backend,
                () -> new char[]{'2'}, no.events::add);
        assertFalse(result.contextLoginUsed());
        assertFalse(no.backend.target.calls.contains("CONTEXT_LOGIN"));
    }

    @Test
    void mismatchedCertificateStopsBeforePinSupplierOrSessionOpen() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var fixture = fixture(pair, true, List.of(key(0x31, pair, true)));
        SigningPolicy wrong = new SigningPolicy(
                "FFEEDDCCBBAA99887766554433221100FFEEDDCCBBAA99887766554433221100",
                "SHA256withECDSA");
        AtomicInteger pinRequests = new AtomicInteger();
        assertThrows(IllegalStateException.class, () -> AdaptiveSigningFlow.signOnce(
                new byte[]{1}, wrong, fixture.backend, () -> {
                    pinRequests.incrementAndGet(); return new char[]{'1'};
                }, fixture.events::add));
        assertEquals(0, pinRequests.get());
        assertEquals(0, fixture.backend.openCount);
    }

    @Test
    void certificateDiscoveryRequiresExactlyOneFingerprintMatch() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var fixture = fixture(pair, true, List.of(key(0x31, pair, true)));
        assertThrows(IllegalStateException.class, () -> AdaptiveSigningFlow.selectCertificate(
                List.of(), fixture.policy));
        assertThrows(IllegalStateException.class, () -> AdaptiveSigningFlow.selectCertificate(
                List.of(fixture.backend.candidate, fixture.backend.candidate), fixture.policy));
    }

    @Test
    void zeroOrMultipleMatchingPrivateKeysFailClosedAfterUserLogin() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var zero = fixture(pair, true, List.of(key(0x04, pair, true)));
        char[] pin0 = {'1'};
        assertThrows(IllegalStateException.class, () -> AdaptiveSigningFlow.signOnce(
                new byte[]{1}, zero.policy, zero.backend, () -> pin0, zero.events::add));
        assertTrue(zero.backend.target.calls.contains("USER_LOGIN"));
        assertFalse(zero.backend.target.calls.contains("SIGN_INIT"));
        assertFalse(zero.backend.target.calls.contains("SIGN"));
        assertTrue(allZero(pin0));

        var multiple = fixture(pair, true, List.of(
                key(0x31, pair, true), key(0x31, pair, true)));
        char[] pin2 = {'2'};
        assertThrows(IllegalStateException.class, () -> AdaptiveSigningFlow.signOnce(
                new byte[]{1}, multiple.policy, multiple.backend, () -> pin2, multiple.events::add));
        assertFalse(multiple.backend.target.calls.contains("SIGN_INIT"));
        assertTrue(allZero(pin2));
    }

    @Test
    void unknownAlwaysAuthenticateFailsBeforeSignInit() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var fixture = fixture(pair, null, List.of(key(0x31, pair, null)));
        assertThrows(IllegalStateException.class, () -> AdaptiveSigningFlow.signOnce(
                new byte[]{1}, fixture.policy, fixture.backend, () -> new char[]{'3'}, fixture.events::add));
        assertFalse(fixture.backend.target.calls.contains("SIGN_INIT"));
    }

    @Test
    void authenticationFailuresNeverRetryOrReachSignatureOperation() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var userFailure = fixture(pair, true, List.of(key(0x31, pair, true)));
        userFailure.backend.target.failUserLogin = true;
        char[] userPin = {'4'};
        assertThrows(Pkcs11Exception.class, () -> AdaptiveSigningFlow.signOnce(
                new byte[]{1}, userFailure.policy, userFailure.backend,
                () -> userPin, userFailure.events::add));
        assertEquals(List.of("USER_LOGIN", "CLOSE"), userFailure.backend.target.calls);
        assertTrue(allZero(userPin));

        var contextFailure = fixture(pair, true, List.of(key(0x31, pair, true)));
        contextFailure.backend.target.failContextLogin = true;
        char[] contextPin = {'5'};
        assertThrows(Pkcs11Exception.class, () -> AdaptiveSigningFlow.signOnce(
                new byte[]{1}, contextFailure.policy, contextFailure.backend,
                () -> contextPin, contextFailure.events::add));
        assertEquals(List.of("USER_LOGIN", "KEY_DISCOVERY", "SIGN_INIT", "CONTEXT_LOGIN", "CLOSE"),
                contextFailure.backend.target.calls);
        assertFalse(contextFailure.backend.target.calls.contains("SIGN"));
        assertTrue(allZero(contextPin));
    }

    private static KeyFixture key(int id, KeyPair pair, Boolean alwaysAuth) {
        return new KeyFixture(new byte[]{(byte) id}, "test EC key",
                org.xipki.pkcs11.wrapper.PKCS11Constants.CKK_EC, true, alwaysAuth, pair);
    }

    private static Fixture fixture(KeyPair pair, Boolean alwaysAuth, List<KeyFixture> keys) throws Exception {
        var cert = new TestFixtures.FakeCertificate(CERT_DER, pair.getPublic());
        String fingerprint = HexFormat.of().withUpperCase().formatHex(
                MessageDigest.getInstance("SHA-256").digest(CERT_DER));
        var policy = new SigningPolicy(fingerprint, "SHA256withECDSA");
        var candidate = new AdaptiveSigningFlow.CertificateCandidate(
                "mock-token", 9876, new byte[]{0x31}, "mock signing certificate", cert);
        var target = new MockTarget(keys);
        var backend = new MockBackend(candidate, target);
        return new Fixture(policy, backend, target, new ArrayList<>());
    }

    private static boolean allZero(char[] value) {
        for (char c : value) if (c != '\0') return false;
        return true;
    }

    private record KeyFixture(byte[] id, String label, Long keyType, Boolean canSign,
                              Boolean alwaysAuth, KeyPair pair) {
        private KeyFixture { id = id.clone(); }
    }
    private record Fixture(SigningPolicy policy, MockBackend backend, MockTarget target,
                           List<String> events) { }

    private static final class MockBackend implements AdaptiveSigningFlow.Backend {
        private final AdaptiveSigningFlow.CertificateCandidate candidate;
        private final MockTarget target;
        private int openCount;
        private MockBackend(AdaptiveSigningFlow.CertificateCandidate candidate, MockTarget target) {
            this.candidate = candidate; this.target = target;
        }
        @Override public List<AdaptiveSigningFlow.CertificateCandidate> discoverCertificates() {
            return List.of(candidate);
        }
        @Override public AdaptiveSigningFlow.Target open(AdaptiveSigningFlow.CertificateCandidate c) {
            openCount++;
            return target;
        }
    }

    private static final class MockTarget implements AdaptiveSigningFlow.Target {
        private final List<KeyFixture> keys;
        private List<KeyFixture> matchedKeys = List.of();
        private final List<String> calls = new ArrayList<>();
        private byte[] selectedId;
        private KeyFixture selected;
        private boolean userLogin;
        private boolean contextLogin;
        private boolean operationInitialized;
        private boolean failUserLogin;
        private boolean failContextLogin;
        private MockTarget(List<KeyFixture> keys) { this.keys = keys; }
        @Override public void loginUser(char[] pin) throws Pkcs11Exception {
            calls.add("USER_LOGIN"); userLogin = true;
            if (failUserLogin) throw new Pkcs11Exception("CKR_PIN_INCORRECT");
        }
        @Override public List<AdaptiveSigningFlow.KeyCandidate> findPrivateKeys(byte[] id) {
            calls.add("KEY_DISCOVERY");
            matchedKeys = keys.stream().filter(k -> Arrays.equals(k.id(), id)).toList();
            return matchedKeys.stream().map(k -> new AdaptiveSigningFlow.KeyCandidate(
                    k.id()[0] & 0xffL, k.id(), k.label(), k.keyType(), k.canSign(), k.alwaysAuth()))
                    .toList();
        }
        @Override public void signInit(String mechanism) {
            assertTrue(userLogin);
            calls.add("SIGN_INIT"); operationInitialized = true;
        }
        @Override public void contextSpecificLogin(char[] pin) throws Pkcs11Exception {
            assertTrue(operationInitialized);
            calls.add("CONTEXT_LOGIN"); contextLogin = true;
            if (failContextLogin) throw new Pkcs11Exception("CKR_PIN_INCORRECT");
        }
        @Override public byte[] sign(byte[] digest) throws Exception {
            assertTrue(userLogin && operationInitialized);
            calls.add("SIGN");
            KeyFixture key = matchedKeys.get(0);
            selected = key; selectedId = key.id();
            Signature signer = Signature.getInstance("NONEwithECDSA");
            signer.initSign(key.pair().getPrivate()); signer.update(digest);
            return RawEcdsaToDer.decode(signer.sign(), AdaptiveSigningRules.ecComponentBytes(key.pair().getPublic()));
        }
        @Override public void close() { calls.add("CLOSE"); }
    }
}
