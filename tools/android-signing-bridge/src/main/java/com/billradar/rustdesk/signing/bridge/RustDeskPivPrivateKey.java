package com.billradar.rustdesk.signing.bridge;

import java.security.PrivateKey;
import java.security.interfaces.ECPublicKey;
import java.util.Objects;

/** Opaque, non-exportable reference to the configured PIV 9C key. Contains no private material. */
public final class RustDeskPivPrivateKey implements PrivateKey {
    private static final long serialVersionUID = 1L;
    private final SigningIdentity identity;
    private final int componentBytes;

    public RustDeskPivPrivateKey(SigningIdentity identity) {
        this(identity, 32);
    }

    public RustDeskPivPrivateKey(SigningIdentity identity, ECPublicKey publicKey) {
        this(identity, componentSize(publicKey));
    }

    private RustDeskPivPrivateKey(SigningIdentity identity, int componentBytes) {
        this.identity = Objects.requireNonNull(identity, "identity");
        if (componentBytes < 1 || componentBytes > 128) {
            throw new IllegalArgumentException("Invalid EC component size");
        }
        this.componentBytes = componentBytes;
    }

    public SigningIdentity identity() {
        return identity;
    }

    public int componentBytes() { return componentBytes; }

    private static int componentSize(ECPublicKey key) {
        Objects.requireNonNull(key, "publicKey");
        return (key.getParams().getOrder().bitLength() + 7) / 8;
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
