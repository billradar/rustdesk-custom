package com.billradar.rustdesk.signing.bridge;

import java.security.PrivateKey;
import java.util.Objects;

/** Opaque, non-exportable reference to the configured PIV 9C key. Contains no private material. */
public final class RustDeskPivPrivateKey implements PrivateKey {
    private static final long serialVersionUID = 1L;
    private final SigningIdentity identity;

    public RustDeskPivPrivateKey(SigningIdentity identity) {
        this.identity = Objects.requireNonNull(identity, "identity");
    }

    public SigningIdentity identity() {
        return identity;
    }

    @Override
    public String getAlgorithm() {
        return "EC";
    }

    @Override
    public String getFormat() {
        return null;
    }

    @Override
    public byte[] getEncoded() {
        return null;
    }
}
