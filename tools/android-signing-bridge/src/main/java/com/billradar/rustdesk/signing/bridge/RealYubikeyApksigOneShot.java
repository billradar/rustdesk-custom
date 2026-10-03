package com.billradar.rustdesk.signing.bridge;

import java.io.Console;
import java.io.File;
import java.io.InputStream;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.Provider;
import java.security.Security;
import java.security.cert.X509Certificate;
import java.security.interfaces.ECPublicKey;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.List;

/** One isolated real apksig signing process; this class never exports private key material. */
public final class RealYubikeyApksigOneShot {
    private static final int EXPECTED_HARDWARE_SIGNATURE_COUNT = 2;
    private static final String EXPECTED_INPUT_SHA256 =
            "596591B25C4910D7E17FBD2EC499DC2592B06256965F6C50A885B538F6E81325";

    private RealYubikeyApksigOneShot() { }

    public static void main(String[] args) {
        if (args.length != 3 || !"--run".equals(args[0])) {
            System.err.println("Usage: --run <read-only input APK> <new output APK>");
            System.exit(2);
        }
        if (!"github-runner".equals(System.getProperty("user.name"))) {
            System.err.println("RUN AS: FAIL (must be github-runner)");
            System.exit(2);
        }

        Path input = Path.of(args[1]).toAbsolutePath().normalize();
        Path output = Path.of(args[2]).toAbsolutePath().normalize();
        XiPkiAdaptiveBackend backend = new XiPkiAdaptiveBackend();
        MutablePinBuffer pinBuffer = null;
        Provider provider = null;
        String beforeHash = null;
        boolean outputMayBeOurs = false;
        int exit = 1;
        try {
            if (!Files.isRegularFile(input) || !Files.isReadable(input)
                    || input.equals(output) || Files.exists(output)) {
                throw new IllegalStateException("Input/output path preflight failed");
            }
            beforeHash = sha256(input);
            if (!EXPECTED_INPUT_SHA256.equals(beforeHash)) {
                throw new IllegalStateException("Candidate APK SHA-256 does not match the reviewed artifact");
            }
            SigningPolicy policy = SigningPolicy.production();
            AdaptiveSigningFlow.CertificateCandidate cert = AdaptiveSigningFlow.selectCertificate(
                    backend.discoverCertificates(), policy);
            SigningIdentity identity = SigningIdentity.production();
            if (!identity.tokenLabel().equals(cert.tokenIdentity().split("\\|", -1)[0])
                    || !Arrays.equals(HexFormat.of().parseHex(identity.objectId()), cert.certificateId())) {
                throw new IllegalStateException("Production token/certificate identity mismatch");
            }
            X509Certificate certificate = cert.certificate();
            backend.setExpectedSignCount(EXPECTED_HARDWARE_SIGNATURE_COUNT);
            Console console = System.console();
            if (console == null) throw new IllegalStateException("Real terminal unavailable; PIN not requested");

            System.out.println("ISOLATED APKSIG APK SIGNING");
            System.out.println("RUN AS: github-runner");
            System.out.println("INPUT SHA256: " + beforeHash);
            System.out.println("PRODUCTION CERTIFICATE IDENTITY: PASS");
            System.out.println("SIGNING SCHEMES: v1=YES, v2=YES, v3=NO, v3.1=NO, v4=NO");
            System.out.println("EXPECTED HARDWARE SIGNATURE COUNT: " + EXPECTED_HARDWARE_SIGNATURE_COUNT);
            char[] entered = console.readPassword("YubiKey PIV PIN: ");
            pinBuffer = new MutablePinBuffer(entered);
            System.out.println("PIN INPUT COUNT: 1");

            provider = RustDeskSigningProvider.forProduction(backend, pinBuffer::copyForOperation);
            if (Security.insertProviderAt(provider, 1) != 1) {
                throw new IllegalStateException("Unable to register RustDeskSigning at priority 1");
            }
            RustDeskPivPrivateKey privateKey = new RustDeskPivPrivateKey(
                    identity, (ECPublicKey) certificate.getPublicKey());
            outputMayBeOurs = true;
            invokeApksig(input, output, privateKey, certificate);

            if (backend.actualSignCount() != EXPECTED_HARDWARE_SIGNATURE_COUNT) {
                throw new IllegalStateException("Actual hardware signature count did not match the preflight");
            }
            String afterHash = sha256(input);
            if (!beforeHash.equals(afterHash)) throw new IllegalStateException("Input APK changed during signing");
            System.out.println("ACTUAL HARDWARE SIGNATURE COUNT: " + backend.actualSignCount());
            System.out.println("INPUT SHA256 AFTER: " + afterHash);
            System.out.println("INPUT UNCHANGED: PASS");
            System.out.println("SIGNED APK: " + output);
            System.out.println("PRIVATE KEY EXPORTED: NO");
            exit = 0;
        } catch (Throwable e) {
            System.err.println("APKSIG SIGNING: FAIL (" + safeFailure(e) + ")");
        } finally {
            if (pinBuffer != null) {
                pinBuffer.close();
                System.out.println("PIN ZEROIZATION: " + (pinBuffer.isZeroized() ? "PASS" : "FAIL"));
                if (!pinBuffer.isZeroized()) exit = 1;
            }
            if (provider != null) Security.removeProvider(provider.getName());
            try {
                backend.close();
                System.out.println("SESSION CLOSE / MODULE FINALIZE: PASS");
            } catch (Throwable e) {
                System.err.println("SESSION CLOSE / MODULE FINALIZE: FAIL");
                exit = 1;
            }
            if (exit != 0 && outputMayBeOurs) {
                try { Files.deleteIfExists(output); }
                catch (Exception e) { System.err.println("FAILED OUTPUT CLEANUP: FAIL"); }
            }
        }
        if (exit == 0) System.out.println("APKSIG APK SIGNING: PASS (isolated test candidate; not a release)");
        System.exit(exit);
    }

    private static void invokeApksig(Path input, Path output,
                                     RustDeskPivPrivateKey key, X509Certificate certificate)
            throws Exception {
        Class<?> signerConfigBuilder = Class.forName("com.android.apksig.ApkSigner$SignerConfig$Builder");
        Object configBuilder = signerConfigBuilder
                .getConstructor(String.class, java.security.PrivateKey.class, List.class)
                .newInstance("rustdesk-production-test", key, List.of(certificate));
        Object signerConfig = signerConfigBuilder.getMethod("build").invoke(configBuilder);
        Class<?> apkSigner = Class.forName("com.android.apksig.ApkSigner");
        Class<?> builderClass = Class.forName("com.android.apksig.ApkSigner$Builder");
        Object builder = builderClass.getConstructor(List.class).newInstance(List.of(signerConfig));
        invoke(builderClass, builder, "setInputApk", File.class, input.toFile());
        invoke(builderClass, builder, "setOutputApk", File.class, output.toFile());
        invoke(builderClass, builder, "setMinSdkVersion", int.class, 22);
        invoke(builderClass, builder, "setV1SigningEnabled", boolean.class, true);
        invoke(builderClass, builder, "setV2SigningEnabled", boolean.class, true);
        invoke(builderClass, builder, "setV3SigningEnabled", boolean.class, false);
        invoke(builderClass, builder, "setV4SigningEnabled", boolean.class, false);
        Object signer = builderClass.getMethod("build").invoke(builder);
        try {
            apkSigner.getMethod("sign").invoke(signer);
        } catch (InvocationTargetException e) {
            Throwable cause = e.getCause();
            if (cause instanceof Exception exception) throw exception;
            throw e;
        }
    }

    private static void invoke(Class<?> type, Object target, String name, Class<?> parameter, Object value)
            throws Exception {
        Method method = type.getMethod(name, parameter);
        method.invoke(target, value);
    }

    private static String sha256(Path file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream stream = Files.newInputStream(file)) {
            byte[] buffer = new byte[1024 * 1024];
            int count;
            while ((count = stream.read(buffer)) != -1) digest.update(buffer, 0, count);
            Arrays.fill(buffer, (byte) 0);
        }
        return HexFormat.of().withUpperCase().formatHex(digest.digest());
    }

    private static String safeFailure(Throwable e) {
        if (e instanceof Pkcs11Exception p) return p.returnCode();
        if (e instanceof org.xipki.pkcs11.wrapper.PKCS11Exception p) return p.getErrorName();
        Throwable cause = e instanceof InvocationTargetException i && i.getCause() != null ? i.getCause() : e;
        String message = cause.getMessage();
        if (message == null || message.isBlank()) return cause.getClass().getSimpleName();
        return message.replaceAll("[\\r\\n\\t]", " ");
    }
}
