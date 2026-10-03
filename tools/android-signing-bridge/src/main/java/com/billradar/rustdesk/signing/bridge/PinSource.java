package com.billradar.rustdesk.signing.bridge;

/** Supplies a mutable PIN buffer for a single signing process. */
@FunctionalInterface
public interface PinSource {
    char[] readPin() throws Exception;
}
