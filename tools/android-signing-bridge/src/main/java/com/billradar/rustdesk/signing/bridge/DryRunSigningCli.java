package com.billradar.rustdesk.signing.bridge;

import java.nio.file.Path;

/** Explicit mock-only CLI. It never initializes PKCS#11 or a YubiKey session. */
public final class DryRunSigningCli {
    private DryRunSigningCli() { }

    public static void main(String[] args) {
        try {
            Path input = null;
            Path output = null;
            String pinSource = "console";
            for (int i = 0; i < args.length; i++) {
                switch (args[i]) {
                    case "--input" -> { if (++i >= args.length || input != null) throw new IllegalArgumentException(); input = Path.of(args[i]); }
                    case "--output" -> { if (++i >= args.length || output != null) throw new IllegalArgumentException(); output = Path.of(args[i]); }
                    case "--pin-source" -> { if (++i >= args.length) throw new IllegalArgumentException(); pinSource = args[i]; }
                    default -> throw new IllegalArgumentException();
                }
            }
            if (input == null || output == null || !"env".equals(pinSource)) {
                throw new IllegalArgumentException("usage: --dry-run --input <input.apk> --output <mock-output.apk> --pin-source env");
            }
            String digest = new MockSigningFlow().run(input, output, PinSources.select(pinSource));
            System.out.println("MOCK SIGNING: PASS");
            System.out.println("INPUT SHA256: " + digest);
            System.out.println("INPUT UNCHANGED: PASS");
            System.out.println("MUTABLE PIN BUFFERS: ZEROIZED");
            System.out.println("PKCS#11 / YUBIKEY OPERATION: NO");
            System.out.println("OUTPUT: MOCK COPY; NOT SIGNED");
        } catch (Throwable e) {
            System.err.println("MOCK SIGNING: FAIL (" + e.getClass().getSimpleName() + ")");
            System.exit(1);
        }
    }
}
