package com.billradar.rustdesk.signing.bridge;

import java.security.Provider;
import java.util.List;

/** Narrow provider offering only Android apksig-required ECDSA digest variants. */
public final class RustDeskSigningProvider extends Provider {
    public static final String PROVIDER_NAME = "RustDeskSigning";

    public RustDeskSigningProvider(
            Pkcs11Signer signer, PinSupplier pinSupplier, SigningIdentity expectedIdentity) {
        super(PROVIDER_NAME, "1.0", "RustDesk sign-only PIV 9C bridge prototype");
        if (signer == null || pinSupplier == null || expectedIdentity == null) {
            throw new IllegalArgumentException("Signer, PIN supplier, and identity are required");
        }
        register("SHA256withECDSA", "SHA-256", List.of("SHA256WITHECKDSA"),
                signer, pinSupplier, expectedIdentity);
        register("SHA512withECDSA", "SHA-512", List.of("SHA512WITHECKDSA"),
                signer, pinSupplier, expectedIdentity);
    }

    /** Creates the production-scoped provider with the pinned token, PIV object ID, and certificate. */
    public static RustDeskSigningProvider forProduction(Pkcs11Signer signer, PinSupplier pinSupplier) {
        return new RustDeskSigningProvider(signer, pinSupplier, SigningIdentity.production());
    }

    private void register(String algorithm, String digestAlgorithm, List<String> aliases,
                          Pkcs11Signer signer, PinSupplier pinSupplier, SigningIdentity identity) {
        putService(new Provider.Service(this, "Signature", algorithm,
                RustDeskPiv9cSignatureSpi.class.getName(), aliases, java.util.Map.of()) {
            @Override public Object newInstance(Object parameter) {
                if (parameter != null) throw new IllegalArgumentException("Parameters are not supported");
                return new RustDeskPiv9cSignatureSpi(signer, pinSupplier, identity, digestAlgorithm);
            }
        });
    }
}
