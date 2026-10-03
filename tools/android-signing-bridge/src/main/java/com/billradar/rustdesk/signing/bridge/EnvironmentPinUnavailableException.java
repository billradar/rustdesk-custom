package com.billradar.rustdesk.signing.bridge;

/** Safe marker for an absent or empty environment PIN, without including its value. */
final class EnvironmentPinUnavailableException extends IllegalStateException {
    private static final long serialVersionUID = 1L;

    EnvironmentPinUnavailableException() {
        super("Environment PIN source is unavailable or empty");
    }
}
