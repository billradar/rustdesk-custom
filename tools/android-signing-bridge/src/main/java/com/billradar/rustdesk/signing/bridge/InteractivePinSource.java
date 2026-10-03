package com.billradar.rustdesk.signing.bridge;

import java.io.Console;

/** Reads the PIN only from the current interactive Java console. */
public final class InteractivePinSource implements PinSource {
    @Override
    public char[] readPin() {
        Console console = System.console();
        if (console == null) throw new IllegalStateException("Interactive console unavailable; PIN not requested");
        char[] pin = console.readPassword("YubiKey PIV PIN: ");
        if (pin == null || pin.length == 0) {
            if (pin != null) java.util.Arrays.fill(pin, '\0');
            throw new IllegalStateException("Interactive PIN input was empty");
        }
        return pin;
    }
}
