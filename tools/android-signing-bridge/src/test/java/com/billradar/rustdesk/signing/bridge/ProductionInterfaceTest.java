package com.billradar.rustdesk.signing.bridge;

import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class ProductionInterfaceTest {
    private static final String PHASE51_SHA256 =
            "596591B25C4910D7E17FBD2EC499DC2592B06256965F6C50A885B538F6E81325";
    @TempDir Path temp;

    @Test
    void acceptsDifferentValidStandardApksAndThePhase51RegressionIdentity() throws Exception {
        Path apkA = apk("standard-a.apk", "arm64-v8a", "one".getBytes(StandardCharsets.UTF_8));
        Path apkB = apk("standard-b.apk", "x86_64", "two".getBytes(StandardCharsets.UTF_8));
        ApkInputPolicy policy = acceptedPolicy();
        assertEquals("arm64-v8a", policy.validate(apkA, temp.resolve("out-a.apk")).abi());
        assertEquals("x86_64", policy.validate(apkB, temp.resolve("out-b.apk")).abi());
        assertEquals(64, PHASE51_SHA256.length());
        assertEquals("com.carriez.flutter_hbb", policy.validate(apkA, temp.resolve("out-c.apk")).packageName());
        assertFalse(javaMainSourceContains(PHASE51_SHA256));
    }

    @Test
    void rejectsWrongPackageMalformedMissingSameAndUnsafePaths() throws Exception {
        Path apk = apk("valid.apk", "arm64-v8a", new byte[]{1, 2, 3});
        ApkInputPolicy wrongPackage = new ApkInputPolicy(ignored -> "package: name='attacker.example' versionCode='1'\n");
        assertThrows(IllegalArgumentException.class, () -> wrongPackage.validate(apk, temp.resolve("wrong.apk")));

        Path malformed = temp.resolve("malformed.apk");
        Files.writeString(malformed, "not a zip");
        assertThrows(IllegalArgumentException.class, () -> acceptedPolicy().validate(malformed, temp.resolve("malformed-out.apk")));
        assertThrows(IllegalArgumentException.class, () -> acceptedPolicy().validate(temp.resolve("missing.apk"), temp.resolve("missing-out.apk")));
        assertThrows(IllegalArgumentException.class, () -> acceptedPolicy().validate(apk, apk));
        Files.writeString(temp.resolve("already.apk"), "existing");
        assertThrows(IllegalArgumentException.class, () -> acceptedPolicy().validate(apk, temp.resolve("already.apk")));

        Path symlink = temp.resolve("symlink.apk");
        Files.createSymbolicLink(symlink, apk.getFileName());
        assertThrows(IllegalArgumentException.class, () -> acceptedPolicy().validate(symlink, temp.resolve("symlink-out.apk")));
    }

    @Test
    void environmentSourceRequiresExplicitSelectionAndDoesNotPrintDummyPin() throws Exception {
        AtomicInteger reads = new AtomicInteger();
        PinSource console = PinSources.select("console");
        assertInstanceOf(InteractivePinSource.class, console);
        assertEquals(0, reads.get(), "console selection must not read environment data");

        char[] dummy = new EnvironmentPinSource(() -> { reads.incrementAndGet(); return "dummy-test-pin"; }).readPin();
        assertEquals(1, reads.get());
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        PrintStream original = System.out;
        try {
            System.setOut(new PrintStream(bytes, true, StandardCharsets.UTF_8));
            Arrays.fill(dummy, '\0');
        } finally {
            System.setOut(original);
        }
        assertFalse(bytes.toString(StandardCharsets.UTF_8).contains("dummy-test-pin"));
        assertArrayEquals(new char[dummy.length], dummy);
        assertThrows(IllegalStateException.class, () -> new EnvironmentPinSource(() -> null).readPin());
        assertThrows(IllegalStateException.class, () -> new EnvironmentPinSource(() -> "").readPin());
        assertThrows(IllegalArgumentException.class, () -> PinSources.select("automatic-fallback"));
    }

    @Test
    void nonTtyMockFlowZeroizesBuffersOnSuccessAndExceptionWithoutPkcs11() throws Exception {
        Path input = apk("mock-input.apk", "arm64-v8a", new byte[]{4, 5, 6});
        Path output = temp.resolve("mock-output.apk");
        char[] successPin = "dummy-ci-pin".toCharArray();
        String hash = new MockSigningFlow(acceptedPolicy()).run(input, output, () -> successPin);
        assertEquals(sha256(input), hash);
        assertArrayEquals(new char[successPin.length], successPin);
        assertArrayEquals(Files.readAllBytes(input), Files.readAllBytes(output));

        Path failedOutput = temp.resolve("failed-output.apk");
        char[] failedPin = "dummy-failure-pin".toCharArray();
        assertThrows(IllegalStateException.class, () -> new MockSigningFlow(acceptedPolicy()).run(
                input, failedOutput, () -> failedPin,
                (in, out, operationPin) -> {
                    assertFalse(Arrays.equals(new char[operationPin.length], operationPin));
                    Files.write(out, new byte[]{7});
                    throw new IllegalStateException("mock failure");
                }));
        assertArrayEquals(new char[failedPin.length], failedPin);
        assertFalse(Files.exists(failedOutput));
        assertEquals(sha256(input), hash);
    }

    private ApkInputPolicy acceptedPolicy() {
        return new ApkInputPolicy(ignored -> "package: name='com.carriez.flutter_hbb' versionCode='1' versionName='test'\n");
    }

    private Path apk(String name, String abi, byte[] library) throws Exception {
        Path path = temp.resolve(name);
        try (ZipOutputStream zip = new ZipOutputStream(Files.newOutputStream(path))) {
            zip.putNextEntry(new ZipEntry("AndroidManifest.xml"));
            zip.write(new byte[]{1, 2, 3});
            zip.closeEntry();
            zip.putNextEntry(new ZipEntry("lib/" + abi + "/librustdesk.so"));
            zip.write(library);
            zip.closeEntry();
        }
        return path;
    }

    private static boolean javaMainSourceContains(String text) throws Exception {
        Path root = Path.of("src/main/java");
        try (var files = Files.walk(root)) {
            return files.filter(p -> p.toString().endsWith(".java"))
                    .anyMatch(p -> {
                        try { return Files.readString(p).contains(text); }
                        catch (Exception e) { throw new RuntimeException(e); }
                    });
        }
    }

    private static String sha256(Path path) throws Exception {
        return HexFormat.of().withUpperCase().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path)));
    }
}
