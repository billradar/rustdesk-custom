package com.billradar.rustdesk.signing.bridge;

import static org.junit.jupiter.api.Assertions.*;

import java.security.Provider;
import java.security.Security;
import org.junit.jupiter.api.Test;

class ProviderTest {
    @Test
    void registersOnlyTheNarrowSignatureServiceAndCanBeSelectedByName() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var mock = new MockPkcs11Signer(TestFixtures.IDENTITY, pair.getPrivate());
        var provider = new RustDeskSigningProvider(
                mock, () -> new char[]{'1', '2', '3', '4', '5', '6'}, TestFixtures.IDENTITY);
        Provider previous = Security.getProvider(RustDeskSigningProvider.PROVIDER_NAME);
        int previousPosition = previous == null ? -1 : indexOf(Security.getProviders(), previous.getName()) + 1;
        try {
            if (previous != null) {
                Security.removeProvider(previous.getName());
            }
            assertTrue(Security.addProvider(provider) > 0);
            assertEquals(2, provider.getServices().size());
            assertTrue(provider.getServices().stream().allMatch(s -> s.getType().equals("Signature")));
            assertTrue(provider.getServices().stream().anyMatch(s -> s.getAlgorithm().equals("SHA256withECDSA")));
            assertTrue(provider.getServices().stream().anyMatch(s -> s.getAlgorithm().equals("SHA512withECDSA")));
            assertEquals(RustDeskPiv9cSignatureSpi.class.getName(),
                    provider.getService("Signature", "SHA256withECDSA").getClassName());
            assertEquals(provider, java.security.Signature
                    .getInstance("SHA256withECDSA", RustDeskSigningProvider.PROVIDER_NAME).getProvider());
            assertFalse(provider.getServices().stream().anyMatch(s ->
                    s.getType().equals("KeyStore") || s.getType().equals("MessageDigest")));
        } finally {
            Security.removeProvider(RustDeskSigningProvider.PROVIDER_NAME);
            if (previous != null) {
                Security.insertProviderAt(previous, previousPosition);
            }
        }
        assertSame(previous, Security.getProvider(RustDeskSigningProvider.PROVIDER_NAME));
    }

    @Test
    void unqualifiedJcaLookupSelectsProviderWhenInsertedFirstAndRestoresOrder() throws Exception {
        var pair = TestFixtures.p256KeyPair();
        var provider = new RustDeskSigningProvider(
                new MockPkcs11Signer(TestFixtures.IDENTITY, pair.getPrivate()),
                () -> new char[]{'1'}, TestFixtures.IDENTITY);
        Provider[] before = Security.getProviders();
        Provider previous = Security.getProvider(RustDeskSigningProvider.PROVIDER_NAME);
        int previousPosition = previous == null ? -1 : indexOf(before, previous.getName()) + 1;
        try {
            if (previous != null) {
                Security.removeProvider(previous.getName());
            }
            assertEquals(1, Security.insertProviderAt(provider, 1));
            assertEquals(provider, java.security.Signature
                    .getInstance("SHA256withECDSA").getProvider());
        } finally {
            Security.removeProvider(RustDeskSigningProvider.PROVIDER_NAME);
            if (previous != null) {
                Security.insertProviderAt(previous, previousPosition);
            }
        }
        Provider[] after = Security.getProviders();
        assertEquals(before.length, after.length);
        for (int i = 0; i < before.length; i++) {
            assertSame(before[i], after[i]);
        }
    }

    @Test
    void productionIdentityIsPinnedToExpectedTokenObjectAndCertificate() {
        SigningIdentity production = SigningIdentity.production();
        assertEquals("bill-yubikey-auth", production.tokenLabel());
        assertEquals("02", production.objectId());
        assertEquals(SigningIdentity.PRODUCTION_CERTIFICATE_SHA256,
                production.certificateSha256());
    }

    private int indexOf(Provider[] providers, String name) {
        for (int i = 0; i < providers.length; i++) {
            if (providers[i].getName().equals(name)) {
                return i;
            }
        }
        return -1;
    }
}
