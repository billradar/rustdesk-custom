package com.billradar.rustdesk.signing.bridge;

import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.NoSuchAlgorithmException;
import java.security.spec.ECGenParameterSpec;
import java.security.PublicKey;
import java.security.Principal;
import java.math.BigInteger;
import java.util.Date;
import java.util.Set;
import java.util.Collection;
import java.util.List;
import java.security.cert.X509Certificate;
import java.security.cert.CertificateException;
import java.security.cert.CertificateEncodingException;
import java.security.cert.CertificateExpiredException;
import java.security.cert.CertificateNotYetValidException;
import java.security.SignatureException;
import java.security.InvalidKeyException;
import java.security.NoSuchProviderException;

final class TestFixtures {
    static final String FAKE_CERT_FINGERPRINT =
            "00112233445566778899AABBCCDDEEFF00112233445566778899AABBCCDDEEFF";
    static final SigningIdentity IDENTITY = new SigningIdentity(
            "mock-token", SigningIdentity.PIV_9C_OBJECT_ID, FAKE_CERT_FINGERPRINT);

    private TestFixtures() { }

    static KeyPair p256KeyPair() throws NoSuchAlgorithmException, java.security.InvalidAlgorithmParameterException {
        return ecKeyPair("secp256r1");
    }

    static KeyPair ecKeyPair(String curve)
            throws NoSuchAlgorithmException, java.security.InvalidAlgorithmParameterException {
        KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
        generator.initialize(new ECGenParameterSpec(curve));
        return generator.generateKeyPair();
    }

    static final class FakeCertificate extends X509Certificate {
        private static final long serialVersionUID = 1L;
        private final byte[] encoded;
        private final PublicKey publicKey;

        FakeCertificate(byte[] encoded, PublicKey publicKey) {
            this.encoded = encoded.clone();
            this.publicKey = publicKey;
        }
        @Override public byte[] getEncoded() { return encoded.clone(); }
        @Override public PublicKey getPublicKey() { return publicKey; }
        @Override public void checkValidity() { }
        @Override public void checkValidity(Date date) { }
        @Override public int getVersion() { return 3; }
        @Override public BigInteger getSerialNumber() { return BigInteger.ONE; }
        @Override public Principal getIssuerDN() { return () -> "CN=Mock"; }
        @Override public Principal getSubjectDN() { return () -> "CN=Mock"; }
        @Override public Date getNotBefore() { return new Date(0); }
        @Override public Date getNotAfter() { return new Date(Long.MAX_VALUE); }
        @Override public byte[] getTBSCertificate() { return encoded.clone(); }
        @Override public byte[] getSignature() { return new byte[0]; }
        @Override public String getSigAlgName() { return "NONE"; }
        @Override public String getSigAlgOID() { return "0.0"; }
        @Override public byte[] getSigAlgParams() { return null; }
        @Override public boolean[] getIssuerUniqueID() { return null; }
        @Override public boolean[] getSubjectUniqueID() { return null; }
        @Override public boolean[] getKeyUsage() { return null; }
        @Override public int getBasicConstraints() { return -1; }
        @Override public boolean hasUnsupportedCriticalExtension() { return false; }
        @Override public Set<String> getCriticalExtensionOIDs() { return Set.of(); }
        @Override public Set<String> getNonCriticalExtensionOIDs() { return Set.of(); }
        @Override public byte[] getExtensionValue(String oid) { return null; }
        @Override public Collection<List<?>> getSubjectAlternativeNames() { return null; }
        @Override public Collection<List<?>> getIssuerAlternativeNames() { return null; }
        @Override public void verify(PublicKey key) { }
        @Override public void verify(PublicKey key, String provider) { }
        @Override public String toString() { return "Mock X.509 certificate"; }
    }
}
