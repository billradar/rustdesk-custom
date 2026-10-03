package com.billradar.rustdesk.signing.bridge;

import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HexFormat;

/** No-hardware execution path for non-TTY CI validation. It copies input to an explicitly mock output. */
public final class MockSigningFlow {
    @FunctionalInterface public interface Operation { void sign(Path input, Path output, char[] pin) throws Exception; }
    private final ApkInputPolicy policy;

    public MockSigningFlow() { this(new ApkInputPolicy()); }
    MockSigningFlow(ApkInputPolicy policy) { this.policy = policy; }

    public String run(Path input, Path output, PinSource source) throws Exception {
        return run(input, output, source, (in, out, ignored) -> Files.copy(in, out));
    }

    String run(Path input, Path output, PinSource source, Operation operation) throws Exception {
        ApkInputPolicy.CheckedPaths paths = policy.validatePaths(input, output);
        String before = sha256(paths.input());
        policy.validateApk(paths.input());
        MutablePinBuffer owner = null;
        char[] operationPin = null;
        boolean complete = false;
        try {
            owner = new MutablePinBuffer(source.readPin());
            operationPin = owner.copyForOperation();
            operation.sign(paths.input(), paths.output(), operationPin);
            if (!Files.isRegularFile(paths.output()) || Files.size(paths.output()) == 0) {
                throw new IllegalStateException("Mock operation did not produce an output file");
            }
            String after = sha256(paths.input());
            if (!MessageDigest.isEqual(before.getBytes(java.nio.charset.StandardCharsets.US_ASCII),
                    after.getBytes(java.nio.charset.StandardCharsets.US_ASCII))) {
                throw new IllegalStateException("Input changed during mock signing");
            }
            complete = true;
            return after;
        } finally {
            if (operationPin != null) Arrays.fill(operationPin, '\0');
            if (owner != null) owner.close();
            if (!complete) Files.deleteIfExists(paths.output());
        }
    }

    private static String sha256(Path path) throws Exception {
        var digest = MessageDigest.getInstance("SHA-256");
        try (var stream = Files.newInputStream(path)) {
            byte[] buffer = new byte[32 * 1024];
            int count;
            while ((count = stream.read(buffer)) != -1) digest.update(buffer, 0, count);
            Arrays.fill(buffer, (byte) 0);
        }
        return HexFormat.of().withUpperCase().formatHex(digest.digest());
    }
}
