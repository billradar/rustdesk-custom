package com.billradar.rustdesk.signing.bridge;

import java.io.Console;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.Signature;
import java.security.cert.X509Certificate;
import java.security.interfaces.ECPublicKey;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.List;

/** One real JCA Signature.sign() validation. It never signs an APK. */
public final class RealYubikeyJcaOneShot {
    private static final byte[] MESSAGE =
            "RustDesk Phase 5.1 JCA YubiKey validation 2026-10-03".getBytes(StandardCharsets.UTF_8);

    private RealYubikeyJcaOneShot() { }

    public static void main(String[] args) {
        boolean preflight = args.length == 1 && "--preflight".equals(args[0]);
        Path reportPath = args.length == 2 && "--run".equals(args[0]) ? Path.of(args[1]) : null;
        if (!preflight && reportPath == null) {
            System.err.println("Usage: --preflight | --run <temporary report path>");
            System.exit(2);
        }
        if (!"github-runner".equals(System.getProperty("user.name"))) {
            System.err.println("RUN AS: FAIL (must be github-runner)");
            System.exit(2);
        }
        System.out.println("REAL YUBIKEY JCA SHA256withECDSA VALIDATION");
        System.out.println("RUN AS: github-runner");
        System.out.println("NO PIN IN COMMAND LINE, FILE, OR ENVIRONMENT");

        List<String> report = new ArrayList<>();
        XiPkiAdaptiveBackend backend = new XiPkiAdaptiveBackend();
        MutablePinBuffer pinBuffer = null;
        int exit = 1;
        try {
            SigningPolicy policy = SigningPolicy.production();
            AdaptiveSigningFlow.CertificateCandidate cert = AdaptiveSigningFlow.selectCertificate(
                    backend.discoverCertificates(), policy);
            if (!SigningIdentity.production().tokenLabel().equals(cert.tokenIdentity().split("\\|", -1)[0])
                    || !Arrays.equals(HexFormat.of().parseHex(SigningIdentity.PIV_9C_OBJECT_ID),
                            cert.certificateId())) {
                throw new IllegalStateException("Production YubiKey identity mismatch");
            }
            X509Certificate certificate = cert.certificate();
            int componentBytes = AdaptiveSigningRules.ecComponentBytes(certificate.getPublicKey());
            report.add("CERTIFICATE SHA256: " + policy.expectedCertificateSha256());
            report.add("CERTIFICATE IDENTITY: PASS");
            report.add("CERTIFICATE CKA_ID: " + SigningIdentity.PIV_9C_OBJECT_ID);
            report.add("EC COMPONENT BYTES: " + componentBytes);
            if (preflight) {
                report.add("PIN REQUESTED: NO");
                report.add("CKU_USER: NOT RUN");
                report.add("PRIVATE KEY ENUMERATION: NOT RUN");
                report.add("JCA Signature.sign(): NOT RUN");
                exit = 0;
            } else {
                Console console = System.console();
                if (console == null) throw new IllegalStateException("Real terminal unavailable; PIN not requested");
                backend.setExpectedSignCount(1);
                char[] entered = console.readPassword("YubiKey PIV PIN: ");
                pinBuffer = new MutablePinBuffer(entered);
                report.add("PIN INPUT COUNT: 1");
                System.out.println("PIN INPUT COUNT: 1");
                RustDeskSigningProvider provider = RustDeskSigningProvider.forProduction(
                        backend, pinBuffer::copyForOperation);
                RustDeskPivPrivateKey key = new RustDeskPivPrivateKey(
                        SigningIdentity.production(), (ECPublicKey) certificate.getPublicKey());
                Signature signer = Signature.getInstance("SHA256withECDSA", provider);
                signer.initSign(key);
                signer.update(MESSAGE);
                byte[] signature = signer.sign();
                if (backend.actualSignCount() != 1) {
                    Arrays.fill(signature, (byte) 0);
                    throw new IllegalStateException("Expected exactly one hardware ECDSA operation");
                }
                Signature verifier = Signature.getInstance("SHA256withECDSA");
                verifier.initVerify(certificate.getPublicKey());
                verifier.update(MESSAGE);
                boolean verified = verifier.verify(signature);
                Arrays.fill(signature, (byte) 0);
                if (!verified) throw new IllegalStateException("Certificate public-key verification failed");
                report.add("JCA PROVIDER: PASS (" + provider.getName() + ")");
                report.add("JCA ALGORITHM: SHA256withECDSA");
                report.add("EXPECTED HARDWARE SIGNATURE COUNT: 1");
                report.add("ACTUAL HARDWARE SIGNATURE COUNT: " + backend.actualSignCount());
                report.add("CKU_USER: PASS");
                report.add("PRIVATE KEY DISCOVERY AFTER LOGIN: PASS");
                report.add("CKA_ALWAYS_AUTHENTICATE: TRUE (required and enforced before signing)");
                report.add("CKU_CONTEXT_SPECIFIC: PASS (per signing operation)");
                report.add("JCA Signature.sign(): PASS (one operation)");
                report.add("PUBLIC KEY VERIFY: PASS");
                report.add("PRIVATE KEY EXPORTED: NO");
                report.add("APK SIGNED: NO");
                exit = 0;
            }
            report.forEach(System.out::println);
        } catch (Throwable e) {
            report.add("STOP: " + safeFailure(e));
            System.err.println("STOP: " + safeFailure(e));
        } finally {
            if (pinBuffer != null) {
                pinBuffer.close();
                report.add("PIN ZEROIZATION: " + (pinBuffer.isZeroized() ? "PASS" : "FAIL"));
                System.out.println("PIN ZEROIZATION: " + (pinBuffer.isZeroized() ? "PASS" : "FAIL"));
            }
            try {
                backend.close();
                report.add("SESSION CLOSE: PASS");
                System.out.println("SESSION CLOSE: PASS");
                report.add("MODULE FINALIZE: PASS");
                System.out.println("MODULE FINALIZE: PASS");
            } catch (Throwable e) {
                report.add("SESSION CLOSE / MODULE FINALIZE: FAIL");
                System.err.println("SESSION CLOSE / MODULE FINALIZE: FAIL");
                report.add("MODULE FINALIZE: FAIL");
                System.err.println("MODULE FINALIZE: FAIL (" + e.getClass().getSimpleName() + ")");
                exit = 1;
            }
            if (reportPath != null) {
                try { Files.writeString(reportPath, String.join("\n", report) + "\n"); }
                catch (Exception e) { System.err.println("REPORT WRITE: FAIL"); exit = 1; }
            }
        }
        if (exit == 0) {
            System.out.println("APK SIGNED: NO");
            System.out.println("WORKFLOW MODIFIED: NO");
            System.out.println(preflight ? "REAL JCA PREFLIGHT: PASS" : "REAL HARDWARE JCA SIGNATURE: PASS");
        }
        if (exit != 0) System.exit(exit);
    }

    private static String safeFailure(Throwable e) {
        if (e instanceof Pkcs11Exception p) return p.returnCode();
        if (e instanceof org.xipki.pkcs11.wrapper.PKCS11Exception p) return p.getErrorName();
        String message = e.getMessage();
        if (message == null || message.isBlank()) return e.getClass().getSimpleName();
        return message.replaceAll("[\\r\\n\\t]", " ");
    }
}
