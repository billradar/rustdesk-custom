package com.billradar.rustdesk.signing.bridge;

import java.io.IOException;
import java.util.Arrays;

/** Reads a non-echoed, newline-terminated numeric PIN from standard input. */
public final class StandardInputPinSource implements PinSource {
    private static final int MAX_PIN_LENGTH = 64;

    @Override
    public char[] readPin() {
        byte[] bytes = new byte[MAX_PIN_LENGTH];
        char[] chars = new char[MAX_PIN_LENGTH];
        int length = 0;
        try {
            while (true) {
                int value = System.in.read();
                if (value == -1 || value == '\n') break;
                if (value == '\r') continue;
                if (value < '0' || value > '9' || length == MAX_PIN_LENGTH) {
                    throw new IllegalArgumentException("standard input PIN format is invalid");
                }
                bytes[length] = (byte) value;
                chars[length] = (char) value;
                length++;
            }
            if (length == 0) throw new IllegalArgumentException("standard input PIN is unavailable");
            return Arrays.copyOf(chars, length);
        } catch (IOException e) {
            throw new IllegalStateException("standard input PIN is unavailable", e);
        } finally {
            Arrays.fill(bytes, (byte) 0);
            Arrays.fill(chars, '\0');
        }
    }
}
