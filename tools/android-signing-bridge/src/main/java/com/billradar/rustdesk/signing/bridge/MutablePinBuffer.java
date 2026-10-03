package com.billradar.rustdesk.signing.bridge;

import java.util.Arrays;

/** Process-scoped mutable PIN owner. Callers receive disposable copies for individual operations. */
final class MutablePinBuffer implements AutoCloseable {
    private char[] value;

    MutablePinBuffer(char[] ownedValue) {
        if (ownedValue == null || ownedValue.length == 0) {
            if (ownedValue != null) Arrays.fill(ownedValue, '\0');
            throw new IllegalArgumentException("A non-empty PIN buffer is required");
        }
        value = ownedValue;
    }

    synchronized char[] copyForOperation() {
        if (value == null) throw new IllegalStateException("PIN buffer has been cleared");
        return value.clone();
    }

    @Override
    public synchronized void close() {
        if (value != null) {
            Arrays.fill(value, '\0');
            value = null;
        }
    }

    synchronized boolean isZeroized() {
        if (value == null) return true;
        for (char c : value) if (c != '\0') return false;
        return true;
    }
}
