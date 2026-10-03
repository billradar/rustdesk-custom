package com.billradar.rustdesk.signing.bridge;

import java.util.Arrays;
import java.util.function.Supplier;

/** Explicitly selected environment PIN source. The environment String cannot be reliably zeroized. */
public final class EnvironmentPinSource implements PinSource {
    public static final String VARIABLE = "YUBIKEY_PIV_PIN";
    private final Supplier<String> environmentLookup;

    public EnvironmentPinSource() {
        this(() -> System.getenv(VARIABLE));
    }

    EnvironmentPinSource(Supplier<String> environmentLookup) {
        this.environmentLookup = environmentLookup;
    }

    @Override
    public char[] readPin() {
        String value = environmentLookup.get();
        if (value == null || value.isEmpty()) {
            throw new IllegalStateException("Environment PIN source is unavailable or empty");
        }
        char[] mutable = value.toCharArray();
        if (mutable.length == 0) {
            Arrays.fill(mutable, '\0');
            throw new IllegalStateException("Environment PIN source is unavailable or empty");
        }
        return mutable;
    }
}
