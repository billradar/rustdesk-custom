package com.billradar.rustdesk.signing.bridge;

import java.security.MessageDigest;
import java.security.Signature;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.List;
import java.util.function.Consumer;

/** Certificate-pinned one-shot flow. The backend owns all PKCS#11-specific calls. */
public final class AdaptiveSigningFlow {
    private AdaptiveSigningFlow() { }

    public interface Backend {
        /** Enumerates public certificates only. Implementations must not log in or query private keys. */
        List<CertificateCandidate> discoverCertificates() throws Exception;
        Target open(CertificateCandidate selected) throws Exception;
    }

    public interface Target extends AutoCloseable {
        void loginUser(char[] pin) throws Exception;
        List<KeyCandidate> findPrivateKeys(byte[] certificateId) throws Exception;
        void signInit(String mechanism) throws Exception;
        void contextSpecificLogin(char[] pin) throws Exception;
        byte[] sign(byte[] digest) throws Exception;
        @Override void close() throws Exception;
    }

    public record CertificateCandidate(
            String tokenIdentity, long slotId, byte[] certificateId, String label,
            X509Certificate certificate) {
        public CertificateCandidate {
            certificateId = certificateId == null ? null : certificateId.clone();
        }
        @Override public byte[] certificateId() {
            return certificateId == null ? null : certificateId.clone();
        }
    }

    public record KeyCandidate(
            long handle, byte[] id, String label, Long keyType, Boolean canSign,
            Boolean alwaysAuthenticate) {
        public KeyCandidate { id = id == null ? null : id.clone(); }
        @Override public byte[] id() { return id == null ? null : id.clone(); }
    }

    public record Result(CertificateCandidate certificate, int componentBytes,
                         int rawSignatureLength, boolean contextLoginUsed) { }

    /** Finds exactly one fingerprint match without PIN input, suitable for a read-only preflight. */
    public static CertificateCandidate selectCertificate(
            List<CertificateCandidate> candidates, SigningPolicy policy) throws Exception {
        List<CertificateCandidate> matches = new ArrayList<>();
        for (CertificateCandidate candidate : candidates) {
            if (candidate.certificate() != null
                    && policy.matchesCertificate(candidate.certificate().getEncoded())) {
                matches.add(candidate);
            }
        }
        AdaptiveSigningRules.requireUniqueMatch(matches.size(), "Production certificate fingerprint");
        CertificateCandidate selected = matches.get(0);
        if (selected.certificateId() == null || selected.certificateId().length == 0) {
            throw new IllegalStateException("Matched certificate has no CKA_ID");
        }
        if (selected.certificate().getPublicKey() == null) {
            throw new IllegalStateException("Matched certificate has no public key");
        }
        policy.pkcs11Mechanism();
        if (!"EC".equalsIgnoreCase(selected.certificate().getPublicKey().getAlgorithm())) {
            throw new IllegalStateException("Signing policy requires an EC certificate key");
        }
        AdaptiveSigningRules.ecComponentBytes(selected.certificate().getPublicKey());
        return selected;
    }

    /** Performs exactly one user login, optional context login, and signature. Never retries. */
    public static Result signOnce(
            byte[] message, SigningPolicy policy, Backend backend, PinSupplier pinSupplier,
            Consumer<String> status) throws Exception {
        CertificateCandidate selected = selectCertificate(backend.discoverCertificates(), policy);
        status.accept("TOKEN DISCOVERY: PASS");
        status.accept("TOKEN IDENTITY: " + selected.tokenIdentity());
        status.accept("CERTIFICATE DISCOVERY: PASS");
        status.accept("CERTIFICATE SHA256: " + policy.expectedCertificateSha256());
        status.accept("CERTIFICATE IDENTITY: PASS");
        status.accept("CERTIFICATE LABEL: " + selected.label());

        int componentBytes = AdaptiveSigningRules.ecComponentBytes(
                selected.certificate().getPublicKey());
        status.accept("DISCOVERED KEY ID: " + HexFormat.of().withUpperCase()
                .formatHex(selected.certificateId()));
        status.accept("DISCOVERED PUBLIC KEY: EC");
        status.accept("DISCOVERED EC COMPONENT SIZE: " + componentBytes);
        Target target = backend.open(selected);
        char[] pin = null;
        byte[] digest = null;
        byte[] raw = null;
        byte[] der = null;
        try {
            pin = pinSupplier.getPin();
            if (pin == null || pin.length == 0) throw new IllegalStateException("No PIN was supplied");
            status.accept("PIN INPUT COUNT: 1");
            target.loginUser(pin);
            status.accept("CKU_USER: PASS");

            byte[] certificateId = selected.certificateId();
            List<KeyCandidate> visible = target.findPrivateKeys(certificateId.clone());
            KeyCandidate key = AdaptiveSigningRules.requirePrivateKeyForCertificateId(
                    visible, certificateId, KeyCandidate::id);
            status.accept("PRIVATE KEY AFTER LOGIN: EXACTLY ONE");
            status.accept("PRIVATE KEY LABEL: " + (key.label() == null ? "UNAVAILABLE" : key.label()));
            status.accept("DISCOVERED KEY ID: " + HexFormat.of().withUpperCase().formatHex(key.id()));
            if (!Arrays.equals(certificateId, key.id())) {
                throw new IllegalStateException("Private-key CKA_ID does not match certificate CKA_ID");
            }
            AdaptiveSigningRules.requireEcdsaCapabilities(key.keyType(), key.canSign());
            boolean contextLogin = AdaptiveSigningRules
                    .requiresContextSpecificLogin(key.alwaysAuthenticate());
            status.accept("PRIVATE KEY TYPE: EC");
            status.accept("CKA_ALWAYS_AUTHENTICATE: " + (contextLogin ? "TRUE" : "FALSE"));

            digest = MessageDigest.getInstance(policy.digestAlgorithm()).digest(message);
            status.accept("MECHANISM: " + policy.pkcs11Mechanism());
            status.accept("MESSAGE HASH: " + policy.digestAlgorithm());
            target.signInit(policy.pkcs11Mechanism());
            status.accept("C_SignInit: PASS");
            if (contextLogin) {
                target.contextSpecificLogin(pin);
                status.accept("CKU_CONTEXT_SPECIFIC: PASS");
            } else {
                status.accept("CKU_CONTEXT_SPECIFIC: NOT REQUIRED");
            }
            raw = target.sign(digest);
            status.accept("C_Sign: PASS");
            if (raw.length != componentBytes * 2) {
                throw new IllegalStateException("Raw signature length does not match certificate EC order");
            }
            status.accept("RAW SIGNATURE LENGTH: " + raw.length);
            der = RawEcdsaToDer.encode(raw, componentBytes);
            status.accept("RAW→DER: PASS");
            Signature verifier = Signature.getInstance(policy.signatureAlgorithm());
            verifier.initVerify(selected.certificate().getPublicKey());
            verifier.update(message);
            if (!verifier.verify(der)) throw new IllegalStateException("Certificate public-key verify failed");
            status.accept("PUBLIC KEY VERIFY: PASS");
            return new Result(selected, componentBytes, raw.length, contextLogin);
        } finally {
            if (pin != null) Arrays.fill(pin, '\0');
            if (digest != null) Arrays.fill(digest, (byte) 0);
            if (raw != null) Arrays.fill(raw, (byte) 0);
            boolean pinZeroized = pin == null || allZero(pin);
            Exception closeFailure = null;
            try { target.close(); } catch (Exception e) { closeFailure = e; }
            status.accept("PIN ZEROIZATION: " + (pinZeroized ? "PASS" : "FAIL"));
            status.accept("SESSION CLOSE: " + (closeFailure == null ? "PASS" : "FAIL"));
            if (closeFailure != null) throw closeFailure;
        }
    }

    private static boolean allZero(char[] chars) {
        for (char ch : chars) if (ch != '\0') return false;
        return true;
    }
}
