package com.billradar.rustdesk.signing.bridge;

/** Selects a PIN source. Environment access is never an implicit fallback. */
public final class PinSources {
    private PinSources() { }

    public static PinSource select(String mode) {
        return switch (mode) {
            case "console" -> new InteractivePinSource();
            case "env" -> new EnvironmentPinSource();
            default -> throw new IllegalArgumentException("PIN source must be console or env");
        };
    }
}
