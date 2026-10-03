package com.billradar.rustdesk.signing.bridge;

import java.util.HexFormat;
import java.util.Objects;

/** Non-secret identity metadata. The fingerprint is the SHA-256 of the certificate DER. */
public final class SigningIdentity {
    public static final String PRODUCTION_CERTIFICATE_SHA256 =
            "559C1EDE0FBE3A01F29BCAC9D0B34BD9691DF3562C83E3019A930506FBC7B6F5";
    public static final String PIV_9C_OBJECT_ID = "02";

    private final String tokenLabel;
    private final String objectId;
    private final byte[] certificateFingerprint;

    public SigningIdentity(String tokenLabel, String objectId, String certificateSha256) {
        this.tokenLabel = Objects.requireNonNull(tokenLabel, "tokenLabel");
        this.objectId = Objects.requireNonNull(objectId, "objectId").toUpperCase(java.util.Locale.ROOT);
        this.certificateFingerprint = HexFormat.of().parseHex(
                Objects.requireNonNull(certificateSha256, "certificateSha256"));
        if (this.certificateFingerprint.length != 32) {
            throw new IllegalArgumentException("Certificate SHA-256 must contain 32 bytes");
        }
    }

    public static SigningIdentity production() {
        return new SigningIdentity(
                "bill-yubikey-auth", PIV_9C_OBJECT_ID, PRODUCTION_CERTIFICATE_SHA256);
    }

    public String tokenLabel() {
        return tokenLabel;
    }

    public String objectId() {
        return objectId;
    }

    public String certificateSha256() {
        return HexFormat.of().withUpperCase().formatHex(certificateFingerprint);
    }

    public boolean matches(SigningIdentity other) {
        return other != null
                && tokenLabel.equals(other.tokenLabel)
                && objectId.equals(other.objectId)
                && java.security.MessageDigest.isEqual(
                        certificateFingerprint, other.certificateFingerprint);
    }

    @Override
    public String toString() {
        return "SigningIdentity[tokenLabel=" + tokenLabel + ", objectId=" + objectId
                + ", certificateSha256=" + certificateSha256() + "]";
    }
}
