package com.billradar.rustdesk.signing.bridge;

import org.xipki.pkcs11.wrapper.AttributeVector;
import org.xipki.pkcs11.wrapper.Mechanism;
import org.xipki.pkcs11.wrapper.PKCS11Exception;
import org.xipki.pkcs11.wrapper.PKCS11Module;
import org.xipki.pkcs11.wrapper.Session;
import org.xipki.pkcs11.wrapper.Slot;
import org.xipki.pkcs11.wrapper.TokenInfo;

import java.io.ByteArrayInputStream;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import java.util.LinkedHashSet;

import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKA_CERTIFICATE_TYPE;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKA_ID;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKA_KEY_TYPE;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKA_LABEL;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKA_SIGN;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKA_ALWAYS_AUTHENTICATE;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKA_VALUE;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKC_X_509;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKO_CERTIFICATE;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKO_PRIVATE_KEY;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKU_CONTEXT_SPECIFIC;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKU_USER;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKM_ECDSA;

/** XiPKI/OpenSC adapter. It discovers certificates before login and private keys only after CKU_USER. */
public final class XiPkiAdaptiveBackend implements AdaptiveSigningFlow.Backend, Pkcs11Signer, AutoCloseable {
    public static final String MODULE_PATH = "/usr/lib/aarch64-linux-gnu/opensc-pkcs11.so";

    private PKCS11Module module;
    private boolean initialized;
    private int expectedSignCount = Integer.MAX_VALUE;
    private int actualSignCount;
    private final Set<JcaSession> jcaSessions = new LinkedHashSet<>();

    @Override
    public List<AdaptiveSigningFlow.CertificateCandidate> discoverCertificates() throws Exception {
        requireRunnerUser();
        if (!initialized) {
            module = PKCS11Module.getInstance(MODULE_PATH);
            module.initialize();
            initialized = true;
        }
        List<AdaptiveSigningFlow.CertificateCandidate> results = new ArrayList<>();
        for (Slot slot : module.getSlotList(true)) {
            TokenInfo info = slot.getToken().getTokenInfo();
            Session session = slot.getToken().openSession(false);
            try {
                long[] handles = session.findObjectsSingle(
                        new AttributeVector().class_(CKO_CERTIFICATE), 512);
                if (handles.length == 512) {
                    throw new IllegalStateException("Certificate enumeration reached its safety limit");
                }
                for (long handle : handles) {
                    AttributeVector attrs = session.getAttrValues(handle,
                            CKA_ID, CKA_LABEL, CKA_CERTIFICATE_TYPE, CKA_VALUE);
                    Long type = attrs.getLongAttrValue(CKA_CERTIFICATE_TYPE);
                    if (type == null || type.longValue() != CKC_X_509) continue;
                    byte[] der = attrs.getByteArrayAttrValue(CKA_VALUE);
                    if (der == null || der.length == 0) {
                        throw new IllegalStateException("Enumerated X.509 certificate has no value");
                    }
                    X509Certificate certificate = (X509Certificate) CertificateFactory.getInstance("X.509")
                            .generateCertificate(new ByteArrayInputStream(der));
                    byte[] id = attrs.getByteArrayAttrValue(CKA_ID);
                    String label = attrs.getStringAttrValue(CKA_LABEL);
                    results.add(new AdaptiveSigningFlow.CertificateCandidate(
                            tokenIdentity(info), slot.getSlotID(), id, label, certificate));
                    Arrays.fill(der, (byte) 0);
                }
            } finally {
                session.closeSession();
            }
        }
        return List.copyOf(results);
    }

    public synchronized void setExpectedSignCount(int expected) {
        if (expected < 1 || actualSignCount != 0) {
            throw new IllegalStateException("Signature limit must be set before private-key operations");
        }
        expectedSignCount = expected;
    }

    public synchronized int actualSignCount() { return actualSignCount; }

    private synchronized void beginHardwareSign() throws Pkcs11Exception {
        if (actualSignCount >= expectedSignCount) {
            throw new Pkcs11Exception("CKR_FUNCTION_REJECTED");
        }
        actualSignCount++;
    }

    @Override
    public AdaptiveSigningFlow.Target open(AdaptiveSigningFlow.CertificateCandidate selected)
            throws Exception {
        if (!initialized || selected == null) throw new IllegalStateException("Certificate discovery required");
        Slot found = null;
        for (Slot slot : module.getSlotList(true)) {
            if (slot.getSlotID() == selected.slotId()
                    && tokenIdentity(slot.getToken().getTokenInfo()).equals(selected.tokenIdentity())) {
                if (found != null) throw new IllegalStateException("Token slot identity is ambiguous");
                found = slot;
            }
        }
        if (found == null) throw new IllegalStateException("Discovered token is no longer present");
        return new HardwareTarget(found.getToken().openSession(false));
    }

    @Override
    public Pkcs11Session openSession(SigningIdentity expectedIdentity) throws Pkcs11Exception {
        try {
            for (JcaSession open : jcaSessions) {
                if (!open.isClosed()) {
                    if (!open.identity.matches(expectedIdentity)) {
                        throw new IllegalStateException("A different identity is already bound to this process");
                    }
                    return open;
                }
            }
            SigningPolicy policy = new SigningPolicy(
                    expectedIdentity.certificateSha256(), "SHA256withECDSA");
            AdaptiveSigningFlow.CertificateCandidate certificate = AdaptiveSigningFlow
                    .selectCertificate(discoverCertificates(), policy);
            String tokenLabel = certificate.tokenIdentity().split("\\|", -1)[0];
            byte[] expectedId = HexFormat.of().parseHex(expectedIdentity.objectId());
            if (!expectedIdentity.tokenLabel().equals(tokenLabel)
                    || !Arrays.equals(expectedId, certificate.certificateId())) {
                throw new IllegalStateException("Production token or certificate object identity mismatch");
            }
            JcaSession session = new JcaSession((HardwareTarget) open(certificate), expectedIdentity,
                    AdaptiveSigningRules.ecComponentBytes(certificate.certificate().getPublicKey()));
            jcaSessions.add(session);
            return session;
        } catch (org.xipki.pkcs11.wrapper.PKCS11Exception e) {
            throw new Pkcs11Exception(e.getErrorName(), e);
        } catch (Exception e) {
            throw new Pkcs11Exception("CKR_GENERAL_ERROR", e);
        }
    }

    @Override
    public void close() throws Exception {
        Exception sessionFailure = null;
        for (JcaSession session : List.copyOf(jcaSessions)) {
            try { session.close(); }
            catch (Exception e) { sessionFailure = e; }
        }
        jcaSessions.clear();
        if (module != null && initialized) {
            PKCS11Module current = module;
            module = null;
            initialized = false;
            current.finalize(null);
        }
        if (sessionFailure != null) throw sessionFailure;
    }

    private static void requireRunnerUser() {
        if (!"github-runner".equals(System.getProperty("user.name"))) {
            throw new IllegalStateException("Must run as github-runner");
        }
    }

    private static String tokenIdentity(TokenInfo info) {
        return String.join("|", safe(info.getLabel()), safe(info.getManufacturerID()),
                safe(info.getModel()), safe(info.getSerialNumber()));
    }

    private static String safe(String value) { return value == null ? "" : value.trim(); }

    private final class HardwareTarget implements AdaptiveSigningFlow.Target {
        private final Session session;
        private AdaptiveSigningFlow.KeyCandidate selectedKey;
        private boolean closed;

        private HardwareTarget(Session session) { this.session = session; }

        private Pkcs11Session.KeyInfo findPrivateKey(byte[] expectedId) throws Exception {
            try {
                List<AdaptiveSigningFlow.KeyCandidate> keys = findPrivateKeys(expectedId.clone());
                AdaptiveSigningFlow.KeyCandidate key = AdaptiveSigningRules
                        .requirePrivateKeyForCertificateId(keys, expectedId,
                                AdaptiveSigningFlow.KeyCandidate::id);
                return new Pkcs11Session.KeyInfo(
                        key.id(), key.keyType(), key.canSign(), key.alwaysAuthenticate());
            } catch (Exception e) { throw e; }
        }

        @Override
        public void loginUser(char[] pin) throws Exception {
            requireOpen();
            session.login(CKU_USER, pin);
        }

        @Override
        public List<AdaptiveSigningFlow.KeyCandidate> findPrivateKeys(byte[] certificateId)
                throws Exception {
            requireOpen();
            long[] handles = session.findObjectsSingle(
                    new AttributeVector().class_(CKO_PRIVATE_KEY).id(certificateId.clone()), 128);
            List<AdaptiveSigningFlow.KeyCandidate> keys = new ArrayList<>(handles.length);
            for (long handle : handles) {
                byte[] id = readBytes(handle, CKA_ID);
                String label = readString(handle, CKA_LABEL);
                Long keyType = readLong(handle, CKA_KEY_TYPE);
                Boolean canSign = readBoolean(handle, CKA_SIGN);
                Boolean alwaysAuth = readBoolean(handle, CKA_ALWAYS_AUTHENTICATE);
                keys.add(new AdaptiveSigningFlow.KeyCandidate(
                        handle, id, label, keyType, canSign, alwaysAuth));
            }
            selectedKey = handles.length == 1 ? keys.get(0) : null;
            return List.copyOf(keys);
        }

        @Override
        public void signInit(String mechanism) throws Exception {
            requireOpen();
            if (selectedKey == null) throw new IllegalStateException("Unique private key was not selected");
            if (!"CKM_ECDSA".equals(mechanism)) throw new IllegalArgumentException("Unsupported mechanism");
            session.signInit(new Mechanism(CKM_ECDSA), selectedKey.handle());
        }

        @Override
        public void contextSpecificLogin(char[] pin) throws Exception {
            requireOpen();
            session.login(CKU_CONTEXT_SPECIFIC, pin);
        }

        @Override
        public byte[] sign(byte[] digest) throws Exception {
            requireOpen();
            if (selectedKey == null) throw new IllegalStateException("Unique private key was not selected");
            beginHardwareSign();
            try {
                return module.getPKCS11Module().C_Sign(session.getSessionHandle(), digest);
            } catch (iaik.pkcs.pkcs11.wrapper.PKCS11Exception e) {
                throw new PKCS11Exception(e.getErrorCode());
            }
        }

        @Override
        public void close() throws Exception {
            if (!closed) {
                closed = true;
                session.closeSession();
            }
        }

        private void requireOpen() {
            if (closed) throw new IllegalStateException("PKCS#11 session is closed");
        }

        private byte[] readBytes(long handle, long type) {
            try { return session.getAttrValues(handle, type).getByteArrayAttrValue(type); }
            catch (PKCS11Exception e) { return null; }
        }
        private String readString(long handle, long type) {
            try { return session.getAttrValues(handle, type).getStringAttrValue(type); }
            catch (PKCS11Exception e) { return null; }
        }
        private Long readLong(long handle, long type) {
            try { return session.getAttrValues(handle, type).getLongAttrValue(type); }
            catch (PKCS11Exception e) { return null; }
        }
        private Boolean readBoolean(long handle, long type) {
            try { return session.getAttrValues(handle, type).getBooleanAttrValue(type); }
            catch (PKCS11Exception e) { return null; }
        }
    }

    private static final class JcaSession implements Pkcs11Session {
        private final HardwareTarget target;
        private final SigningIdentity identity;
        private final int componentBytes;
        private KeyInfo keyInfo;
        private boolean userLoggedIn;
        private boolean closed;
        private JcaSession(HardwareTarget target, SigningIdentity identity, int componentBytes) {
            this.target = target;
            this.identity = identity;
            this.componentBytes = componentBytes;
        }
        @Override public int certificateComponentBytes() { return componentBytes; }
        @Override public void loginUser(char[] pin) throws Pkcs11Exception {
            if (userLoggedIn) return;
            invoke(() -> target.loginUser(pin));
            userLoggedIn = true;
        }
        @Override public KeyInfo findPrivateKey(byte[] expectedId) throws Pkcs11Exception {
            if (!userLoggedIn || closed) throw new Pkcs11Exception("CKR_USER_NOT_LOGGED_IN");
            if (keyInfo != null) {
                if (!Arrays.equals(keyInfo.id(), expectedId)) {
                    throw new Pkcs11Exception("CKR_OBJECT_HANDLE_INVALID");
                }
                return keyInfo;
            }
            try {
                keyInfo = target.findPrivateKey(expectedId);
                return keyInfo;
            }
            catch (org.xipki.pkcs11.wrapper.PKCS11Exception e) {
                throw new Pkcs11Exception(e.getErrorName(), e);
            } catch (Exception e) { throw new Pkcs11Exception("CKR_GENERAL_ERROR", e); }
        }
        @Override public void signInit(String mechanism) throws Pkcs11Exception {
            invoke(() -> target.signInit(mechanism));
        }
        @Override public void contextSpecificLogin(char[] pin) throws Pkcs11Exception {
            invoke(() -> target.contextSpecificLogin(pin));
        }
        @Override public byte[] sign(byte[] digest) throws Pkcs11Exception {
            try { return target.sign(digest); }
            catch (org.xipki.pkcs11.wrapper.PKCS11Exception e) {
                throw new Pkcs11Exception(e.getErrorName(), e);
            } catch (Exception e) { throw new Pkcs11Exception("CKR_GENERAL_ERROR", e); }
        }
        @Override public void finishOperation(boolean succeeded) throws Pkcs11Exception {
            if (!succeeded) close();
        }
        @Override public void close() throws Pkcs11Exception {
            if (!closed) {
                closed = true;
                invoke(target::close);
            }
        }
        private boolean isClosed() { return closed; }
        private static void invoke(ThrowingAction action) throws Pkcs11Exception {
            try { action.run(); }
            catch (org.xipki.pkcs11.wrapper.PKCS11Exception e) {
                throw new Pkcs11Exception(e.getErrorName(), e);
            } catch (Exception e) { throw new Pkcs11Exception("CKR_GENERAL_ERROR", e); }
        }
        @FunctionalInterface private interface ThrowingAction { void run() throws Exception; }
    }
}
