package com.billradar.rustdesk.signing.bridge;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Generic RustDesk Standard Android APK input policy; independent of signing and PIN handling. */
public final class ApkInputPolicy {
    public static final String EXPECTED_PACKAGE = "com.carriez.flutter_hbb";
    private static final Set<String> SUPPORTED_ABIS = Set.of("arm64-v8a", "armeabi-v7a", "x86_64");
    private static final Pattern PACKAGE_LINE = Pattern.compile("(?m)^package: name='([^']+)'(?: |$)");
    private static final int MAX_AAPT_OUTPUT = 1_048_576;

    public record ApkIdentity(String packageName, String abi) { }
    public record CheckedPaths(Path input, Path output) { }
    @FunctionalInterface interface MetadataReader { String badging(Path apk) throws Exception; }

    private final MetadataReader metadataReader;

    public ApkInputPolicy() {
        this(ApkInputPolicy::readBadging);
    }

    ApkInputPolicy(MetadataReader metadataReader) {
        this.metadataReader = metadataReader;
    }

    public ApkIdentity validate(Path input, Path output) throws Exception {
        CheckedPaths paths = validatePaths(input, output);
        return validateApk(paths.input());
    }

    public CheckedPaths validatePaths(Path input, Path output) throws IOException {
        Path source = checkedPath(input, true);
        Path destination = checkedPath(output, false);
        if (source.equals(destination)) {
            throw new IllegalArgumentException("Input and output must be different files");
        }
        if (Files.exists(destination, LinkOption.NOFOLLOW_LINKS)) {
            throw new IllegalArgumentException("Output already exists; refusing to overwrite");
        }
        Path outputParent = destination.getParent();
        if (outputParent == null || !Files.isDirectory(outputParent, LinkOption.NOFOLLOW_LINKS)
                || !Files.isWritable(outputParent)) {
            throw new IllegalArgumentException("Output parent must be an existing writable directory");
        }
        return new CheckedPaths(source, destination);
    }

    public ApkIdentity validateApk(Path source) throws Exception {
        source = checkedPath(source, true);
        String badging = metadataReader.badging(source);
        Matcher packageMatch = PACKAGE_LINE.matcher(badging);
        if (!packageMatch.find() || !EXPECTED_PACKAGE.equals(packageMatch.group(1))) {
            throw new IllegalArgumentException("APK package policy rejected input");
        }

        List<String> rustDeskAbis = new ArrayList<>();
        try (ZipFile zip = new ZipFile(source.toFile())) {
            var entries = zip.entries();
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                String name = entry.getName();
                if (!name.startsWith("lib/") || !name.endsWith("/librustdesk.so")) continue;
                String abi = name.substring("lib/".length(), name.length() - "/librustdesk.so".length());
                if (!SUPPORTED_ABIS.contains(abi)) {
                    throw new IllegalArgumentException("APK contains an unsupported RustDesk ABI");
                }
                if (entry.isDirectory() || entry.getSize() <= 0) {
                    throw new IllegalArgumentException("APK RustDesk native library is empty");
                }
                try (InputStream stream = zip.getInputStream(entry)) {
                    byte[] buffer = new byte[32 * 1024];
                    long count = 0;
                    int read;
                    while ((read = stream.read(buffer)) != -1) count += read;
                    java.util.Arrays.fill(buffer, (byte) 0);
                    if (count == 0 || count != entry.getSize()) {
                        throw new IllegalArgumentException("APK RustDesk native library is incomplete");
                    }
                }
                rustDeskAbis.add(abi);
            }
        } catch (IOException e) {
            throw new IllegalArgumentException("Input is not a parseable APK archive", e);
        }
        if (rustDeskAbis.size() != 1) {
            throw new IllegalArgumentException("APK must contain exactly one supported RustDesk ABI");
        }
        return new ApkIdentity(EXPECTED_PACKAGE, rustDeskAbis.getFirst());
    }

    private static Path checkedPath(Path path, boolean mustExist) throws IOException {
        if (path == null) throw new IllegalArgumentException("Input/output path is required");
        Path absolute = path.toAbsolutePath().normalize();
        Path current = absolute.getRoot();
        for (Path component : absolute) {
            current = current.resolve(component);
            if (Files.isSymbolicLink(current)) {
                throw new IllegalArgumentException("Symbolic links are not allowed in input/output paths");
            }
        }
        if (mustExist) {
            if (!Files.isRegularFile(absolute, LinkOption.NOFOLLOW_LINKS) || !Files.isReadable(absolute)) {
                throw new IllegalArgumentException("Input must be an existing readable regular file");
            }
        }
        return absolute;
    }

    private static String readBadging(Path apk) throws Exception {
        ProcessBuilder builder = new ProcessBuilder("/usr/bin/aapt", "dump", "badging", apk.toString());
        builder.redirectErrorStream(true);
        builder.environment().clear();
        builder.environment().put("PATH", "/usr/bin:/bin");
        builder.environment().put("LC_ALL", "C");
        Process process = builder.start();
        byte[] output;
        try (InputStream stream = process.getInputStream()) {
            output = stream.readNBytes(MAX_AAPT_OUTPUT + 1);
        }
        if (!process.waitFor(20, java.util.concurrent.TimeUnit.SECONDS)) {
            process.destroyForcibly();
            throw new IllegalArgumentException("APK metadata parser timed out");
        }
        if (output.length > MAX_AAPT_OUTPUT || process.exitValue() != 0) {
            throw new IllegalArgumentException("APK metadata parser rejected input");
        }
        String text = new String(output, java.nio.charset.StandardCharsets.UTF_8);
        java.util.Arrays.fill(output, (byte) 0);
        return text;
    }
}
