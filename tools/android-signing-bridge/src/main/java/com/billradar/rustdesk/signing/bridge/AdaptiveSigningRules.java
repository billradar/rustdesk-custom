package com.billradar.rustdesk.signing.bridge;

import java.security.interfaces.ECPublicKey;
import java.security.PublicKey;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.function.Function;

/** Pure certificate/key binding and capability rules shared by hardware and mock paths. */
public final class AdaptiveSigningRules {
    private AdaptiveSigningRules() { }

    public static int requireUniqueMatch(int count, String objectDescription) {
        if (count != 1) {
            throw new IllegalStateException(objectDescription + ": expected exactly one match; found " + count);
        }
        return count;
    }

    public static <T> T requirePrivateKeyForCertificateId(
            List<T> visibleKeys, byte[] certificateId, Function<T, byte[]> idReader) {
        if (certificateId == null || certificateId.length == 0) {
            throw new IllegalStateException("Matched certificate has no CKA_ID");
        }
        List<T> matching = new ArrayList<>();
        for (T key : visibleKeys) {
            byte[] keyId = idReader.apply(key);
            if (keyId != null && Arrays.equals(certificateId, keyId)) matching.add(key);
        }
        requireUniqueMatch(matching.size(), "Private key for matched certificate CKA_ID");
        return matching.get(0);
    }

    public static int ecComponentBytes(PublicKey publicKey) {
        if (!(publicKey instanceof ECPublicKey ec)) {
            throw new IllegalArgumentException("Pinned certificate public key is not EC");
        }
        int orderBits = ec.getParams().getOrder().bitLength();
        if (orderBits <= 0) throw new IllegalArgumentException("Invalid EC order size");
        return (orderBits + 7) / 8;
    }

    public static boolean requiresContextSpecificLogin(Boolean alwaysAuthenticate) {
        if (alwaysAuthenticate == null) {
            throw new IllegalStateException("CKA_ALWAYS_AUTHENTICATE is unavailable");
        }
        return alwaysAuthenticate;
    }

    public static void requireEcdsaCapabilities(Long keyType, Boolean canSign) {
        if (keyType == null || canSign == null) {
            throw new IllegalStateException("Private-key capabilities are unavailable");
        }
        if (keyType.longValue() != org.xipki.pkcs11.wrapper.PKCS11Constants.CKK_EC) {
            throw new IllegalStateException("Private key type is not EC");
        }
        if (!canSign) throw new IllegalStateException("Private key does not permit signing");
    }
}
