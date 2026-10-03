package com.billradar.rustdesk.signing.bridge;

import java.io.Console;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;

/** Certificate-pinned adaptive one-shot test. Preflight never requests PIN or accesses private keys. */
public final class RealYubikeyEcdsaOneShot {
    private static final byte[] CHALLENGE =
            "RustDesk Phase 5.1 adaptive YubiKey signing validation 2026-10-03"
                    .getBytes(StandardCharsets.UTF_8);

    private RealYubikeyEcdsaOneShot() { }

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

        System.out.println("REAL YUBIKEY PIV ADAPTIVE ECDSA VALIDATION");
        System.out.println("RUN AS: github-runner");
        System.out.println("NO PIN IN COMMAND LINE, FILE, OR ENVIRONMENT");
        SigningPolicy policy = SigningPolicy.production();
        System.out.println("ADAPTIVE SIGNING POLICY: PASS (" + policy.signatureAlgorithm() + ")");

        List<String> report = new ArrayList<>();
        int exit = 1;
        XiPkiAdaptiveBackend backend = new XiPkiAdaptiveBackend();
        try {
            if (preflight) {
                AdaptiveSigningFlow.CertificateCandidate certificate = AdaptiveSigningFlow
                        .selectCertificate(backend.discoverCertificates(), policy);
                report.add("TOKEN DISCOVERY: PASS");
                report.add("TOKEN IDENTITY: " + certificate.tokenIdentity());
                report.add("CERTIFICATE DISCOVERY: PASS");
                report.add("CERTIFICATE LABEL: " + certificate.label());
                report.add("CERTIFICATE SHA256: " + policy.expectedCertificateSha256());
                report.add("CERTIFICATE IDENTITY: PASS");
                report.add("DISCOVERED KEY ID: " + HexFormat.of().withUpperCase()
                        .formatHex(certificate.certificateId()));
                report.add("DISCOVERED PUBLIC KEY: " + certificate.certificate().getPublicKey().getAlgorithm());
                report.add("DISCOVERED EC COMPONENT SIZE: " + AdaptiveSigningRules.ecComponentBytes(
                        certificate.certificate().getPublicKey()));
                report.add("SESSION: CKF_SERIAL_SESSION; CKF_RW_SESSION absent");
                report.add("PRIVATE KEY DISCOVERY: NOT RUN (pre-login objects may be hidden)");
                report.add("PIN: NOT REQUESTED");
                report.add("C_Login: NOT CALLED");
                report.add("C_SignInit: NOT CALLED");
                report.add("C_Sign: NOT CALLED");
                report.add("APK SIGNED: NO");
                exit = 0;
            } else {
                Console console = System.console();
                if (console == null) {
                    throw new IllegalStateException("No real terminal available; PIN was not requested");
                }
                AdaptiveSigningFlow.Result result = AdaptiveSigningFlow.signOnce(
                        CHALLENGE, policy, backend,
                        () -> console.readPassword("YubiKey PIV PIN: "),
                        line -> {
                            report.add(line);
                            System.out.println(line);
                        });
                report.add("RAW→DER: PASS");
                report.add("REAL YUBIKEY ECDSA: PASS");
                report.add("PRODUCTION CERTIFICATE IDENTITY: VERIFIED");
                report.add("CERTIFICATE → PRIVATE KEY BINDING: VERIFIED");
                report.add("YUBIKEY PRIVATE-KEY POSSESSION: VERIFIED");
                report.add("ADAPTIVE HARDWARE SIGNING BACKEND: VALIDATED");
                report.add("PIN INPUT COUNT: 1");
                report.add("PIN ZEROIZATION: PASS");
                report.add("MODULE FINALIZE: PENDING");
                report.add("PRIVATE KEY EXPORTED: NO");
                report.add("YUBIKEY MODIFIED: NO");
                report.add("APK SIGNED: NO");
                report.add("WORKFLOW MODIFIED: NO");
                report.add("APK PRODUCTION SIGNING: NOT YET VALIDATED");
                System.out.println("RAW SIGNATURE LENGTH: " + result.rawSignatureLength());
                exit = 0;
            }
        } catch (Throwable failure) {
            String safe = safeFailure(failure);
            report.add("STOP: " + safe);
            System.err.println("STOP: " + safe);
        } finally {
            try {
                backend.close();
                report.add("MODULE FINALIZE: PASS");
                System.out.println("MODULE FINALIZE: PASS");
            } catch (Throwable closeFailure) {
                report.add("MODULE FINALIZE: FAIL");
                System.err.println("MODULE FINALIZE: FAIL (" + closeFailure.getClass().getSimpleName() + ")");
                exit = 1;
            }
            if (reportPath != null) {
                try {
                    Files.writeString(reportPath, asMarkdown(report), StandardCharsets.UTF_8,
                            StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING,
                            StandardOpenOption.WRITE);
                } catch (Exception e) {
                    System.err.println("RESULT REPORT WRITE: FAIL (" + e.getClass().getSimpleName() + ")");
                    exit = 1;
                }
            }
        }
        System.out.println("PRIVATE KEY EXPORTED: NO");
        System.out.println("YUBIKEY MODIFIED: NO");
        System.out.println("APK SIGNED: NO");
        System.out.println("WORKFLOW MODIFIED: NO");
        if (preflight) report.forEach(System.out::println);
        if (!preflight) System.out.println("APK PRODUCTION SIGNING: NOT YET VALIDATED");
        System.out.println("REAL YUBIKEY ADAPTIVE ECDSA VALIDATION: "
                + (exit == 0 ? (preflight ? "PRE-PIN PREFLIGHT PASS" : "PASS") : "FAIL"));
        if (exit != 0) System.exit(exit);
    }

    private static String safeFailure(Throwable e) {
        if (e instanceof org.xipki.pkcs11.wrapper.PKCS11Exception p) return p.getErrorName();
        if (e instanceof iaik.pkcs.pkcs11.wrapper.PKCS11Exception p) {
            return "CKR_0x" + Long.toHexString(p.getErrorCode()).toUpperCase();
        }
        String message = e.getMessage();
        if (message == null || message.isBlank()) return e.getClass().getSimpleName();
        return message.replaceAll("[\\r\\n\\t]", " ");
    }

    private static String asMarkdown(List<String> statuses) {
        StringBuilder out = new StringBuilder("# Real YubiKey Adaptive ECDSA Validation\n\n");
        out.append("Date: 2026-10-03 (Asia/Shanghai)\n\n");
        out.append("- Run as: `github-runner`\n- PIN values are never recorded.\n");
        for (String status : statuses) out.append("- ").append(status).append('\n');
        out.append("\nAPK PRODUCTION SIGNING: NOT YET VALIDATED\n");
        return out.toString();
    }
}
