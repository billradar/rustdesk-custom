package com.billradar.rustdesk.signing.bridge;

import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Locale;
import java.util.Objects;

/** Non-secret caller policy. Certificate fingerprint is the identity trust anchor. */
public final class SigningPolicy {
    private final byte[] expectedCertificateSha256;
    private final String signatureAlgorithm;

    public SigningPolicy(String expectedCertificateSha256, String signatureAlgorithm) {
        Objects.requireNonNull(expectedCertificateSha256, "expectedCertificateSha256");
        Objects.requireNonNull(signatureAlgorithm, "signatureAlgorithm");
        try {
            this.expectedCertificateSha256 = HexFormat.of().parseHex(expectedCertificateSha256);
        } catch (IllegalArgumentException e) {
            throw new IllegalArgumentException("Expected certificate fingerprint must be hex", e);
        }
        if (this.expectedCertificateSha256.length != 32) {
            throw new IllegalArgumentException("Expected certificate fingerprint must be SHA-256");
        }
        this.signatureAlgorithm = signatureAlgorithm;
    }

    public static SigningPolicy production() {
        return new SigningPolicy(SigningIdentity.PRODUCTION_CERTIFICATE_SHA256, "SHA256withECDSA");
    }

    public String expectedCertificateSha256() {
        return HexFormat.of().withUpperCase().formatHex(expectedCertificateSha256);
    }

    public String signatureAlgorithm() {
        return signatureAlgorithm;
    }

    public String digestAlgorithm() {
        if ("SHA256withECDSA".equalsIgnoreCase(signatureAlgorithm)) return "SHA-256";
        if ("SHA384withECDSA".equalsIgnoreCase(signatureAlgorithm)) return "SHA-384";
        if ("SHA512withECDSA".equalsIgnoreCase(signatureAlgorithm)) return "SHA-512";
        throw new IllegalArgumentException("Unsupported signing policy algorithm");
    }

    public String pkcs11Mechanism() {
        if (!signatureAlgorithm.toUpperCase(Locale.ROOT).endsWith("WITHECDSA")) {
            throw new IllegalArgumentException("Only ECDSA signing policies are supported");
        }
        digestAlgorithm();
        return "CKM_ECDSA";
    }

    public boolean matchesCertificate(byte[] der) throws Exception {
        byte[] actual = MessageDigest.getInstance("SHA-256").digest(der);
        return MessageDigest.isEqual(expectedCertificateSha256, actual);
    }
}
