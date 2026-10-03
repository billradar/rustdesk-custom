package com.billradar.rustdesk.signing.bridge;

/** Supplies one mutable PIN buffer for one context-specific login attempt. */
@FunctionalInterface
public interface PinSupplier {
    char[] getPin() throws Exception;
}
