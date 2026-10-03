package com.billradar.rustdesk.signing.bridge;

import java.security.Provider;
import java.util.List;

/** Narrow provider offering only SHA256withECDSA over the configured PIV key handle. */
public final class RustDeskSigningProvider extends Provider {
    public static final String PROVIDER_NAME = "RustDeskSigning";

    public RustDeskSigningProvider(
            Pkcs11Signer signer, PinSupplier pinSupplier, SigningIdentity expectedIdentity) {
        super(PROVIDER_NAME, "1.0", "RustDesk sign-only PIV 9C bridge prototype");
        if (signer == null || pinSupplier == null || expectedIdentity == null) {
            throw new IllegalArgumentException("Signer, PIN supplier, and identity are required");
        }
        putService(new Provider.Service(
                this,
                "Signature",
                "SHA256withECDSA",
                RustDeskPiv9cSignatureSpi.class.getName(),
                List.of("SHA256WITHECKDSA"),
                java.util.Map.of()) {
            @Override
            public Object newInstance(Object parameter) {
                if (parameter != null) {
                    throw new IllegalArgumentException("Parameters are not supported");
                }
                return new RustDeskPiv9cSignatureSpi(signer, pinSupplier, expectedIdentity);
            }
        });
    }

    /** Creates the production-scoped provider with the pinned token, PIV object ID, and certificate. */
    public static RustDeskSigningProvider forProduction(Pkcs11Signer signer, PinSupplier pinSupplier) {
        return new RustDeskSigningProvider(signer, pinSupplier, SigningIdentity.production());
    }
}
