package com.billradar.rustdesk.signing.bridge.discovery;

import org.xipki.pkcs11.wrapper.AttributeVector;
import org.xipki.pkcs11.wrapper.PKCS11Module;
import org.xipki.pkcs11.wrapper.Session;
import org.xipki.pkcs11.wrapper.Slot;
import org.xipki.pkcs11.wrapper.Token;
import org.xipki.pkcs11.wrapper.TokenInfo;

import java.io.ByteArrayInputStream;
import java.security.MessageDigest;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.security.interfaces.ECPublicKey;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.List;

import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKA_CERTIFICATE_TYPE;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKA_ID;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKA_LABEL;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKA_VALUE;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKC_X_509;
import static org.xipki.pkcs11.wrapper.PKCS11Constants.CKO_CERTIFICATE;

/** Explicit, read-only XiPKI/OpenSC hardware discovery. Never authenticates or signs. */
public final class XiPkiPkcs11Discovery {

  private static final String TOKEN_LABEL = "bill-yubikey-auth";
  private static final String CERTIFICATE_LABEL = "Certificate for Digital Signature";
  private static final String EXPECTED_SHA256 =
      "559C1EDE0FBE3A01F29BCAC9D0B34BD9691DF3562C83E3019A930506FBC7B6F5";
  private static final byte[] CERTIFICATE_ID = {0x02};

  private XiPkiPkcs11Discovery() {
  }

  public static void main(String[] args) {
    System.out.println("READ-ONLY YUBIKEY DISCOVERY");
    System.out.println("NO PIN");
    System.out.println("NO LOGIN");
    System.out.println("NO PRIVATE KEY OPERATION");
    System.out.println("NO SIGNING");

    if (args.length != 1 || args[0].isBlank()) {
      System.err.println("Usage: provide the explicitly selected PKCS#11 module path");
      System.exit(2);
    }

    PKCS11Module module = null;
    Session session = null;
    boolean initializationAttempted = false;
    boolean passed = false;
    try {
      module = PKCS11Module.getInstance(args[0]);
      initializationAttempted = true;
      module.initialize();
      System.out.println("MODULE LOAD: PASS");

      Slot[] tokenSlots = module.getSlotList(true);
      List<Slot> targetSlots = new ArrayList<>();
      List<TokenInfo> targetInfos = new ArrayList<>();
      for (Slot slot : tokenSlots) {
        TokenInfo info = slot.getToken().getTokenInfo();
        if (TOKEN_LABEL.equals(info.getLabel())) {
          targetSlots.add(slot);
          targetInfos.add(info);
        }
      }

      if (targetSlots.size() != 1) {
        throw new IllegalStateException("Expected exactly one target token; found " + targetSlots.size());
      }

      Slot targetSlot = targetSlots.get(0);
      TokenInfo tokenInfo = targetInfos.get(0);
      System.out.println("SLOT DISCOVERY: PASS");
      System.out.println("TOKEN: FOUND");
      System.out.println("SLOT ID: " + targetSlot.getSlotID());
      System.out.println("TOKEN LABEL: " + tokenInfo.getLabel());
      System.out.println("TOKEN MANUFACTURER: " + tokenInfo.getManufacturerID());
      System.out.println("TOKEN MODEL: " + tokenInfo.getModel());
      System.out.println("TOKEN SERIAL: " + tokenInfo.getSerialNumber());
      System.out.println("TOKEN FLAGS: 0x" + Long.toHexString(tokenInfo.getFlags()));

      Token targetToken = targetSlot.getToken();
      session = targetToken.openSession(false);
      System.out.println("SESSION: READ ONLY (CKF_SERIAL_SESSION; CKF_RW_SESSION absent)");

      AttributeVector template = new AttributeVector()
          .class_(CKO_CERTIFICATE)
          .id(CERTIFICATE_ID.clone());
      long[] matches = session.findObjectsSingle(template, 32);
      if (matches.length != 1) {
        throw new IllegalStateException("Expected exactly one CKO_CERTIFICATE with ID 02; found " + matches.length);
      }

      AttributeVector attributes = session.getAttrValues(matches[0],
          CKA_ID, CKA_LABEL, CKA_CERTIFICATE_TYPE, CKA_VALUE);
      byte[] objectId = attributes.getByteArrayAttrValue(CKA_ID);
      String objectLabel = attributes.getStringAttrValue(CKA_LABEL);
      Long certificateType = attributes.getLongAttrValue(CKA_CERTIFICATE_TYPE);
      byte[] der = attributes.getByteArrayAttrValue(CKA_VALUE);
      if (!Arrays.equals(CERTIFICATE_ID, objectId)) {
        throw new IllegalStateException("Certificate CKA_ID did not match 02");
      }
      if (!CERTIFICATE_LABEL.equals(objectLabel)) {
        throw new IllegalStateException("Certificate label did not match expected identity");
      }
      if (certificateType == null || certificateType != CKC_X_509 || der == null || der.length == 0) {
        throw new IllegalStateException("Certificate object did not provide expected X.509 value");
      }

      X509Certificate certificate = (X509Certificate) CertificateFactory.getInstance("X.509")
          .generateCertificate(new ByteArrayInputStream(der));
      byte[] digest = MessageDigest.getInstance("SHA-256").digest(der);
      byte[] expected = HexFormat.of().parseHex(EXPECTED_SHA256);
      boolean fingerprintMatches = MessageDigest.isEqual(digest, expected);

      System.out.println("CERTIFICATE ID 02: FOUND");
      System.out.println("CERTIFICATE LABEL: " + objectLabel);
      System.out.println("CERTIFICATE SUBJECT: " + certificate.getSubjectX500Principal());
      System.out.println("CERTIFICATE ISSUER: " + certificate.getIssuerX500Principal());
      System.out.println("CERTIFICATE SERIAL: " + certificate.getSerialNumber().toString(16));
      System.out.println("CERTIFICATE NOT BEFORE: " + certificate.getNotBefore().toInstant());
      System.out.println("CERTIFICATE NOT AFTER: " + certificate.getNotAfter().toInstant());
      if (certificate.getPublicKey() instanceof ECPublicKey ecPublicKey) {
        System.out.println("CERTIFICATE PUBLIC KEY: EC, "
            + ecPublicKey.getParams().getCurve().getField().getFieldSize() + " bits");
      } else {
        System.out.println("CERTIFICATE PUBLIC KEY: " + certificate.getPublicKey().getAlgorithm());
      }
      System.out.println("CERTIFICATE SHA256: " + HexFormat.of().withUpperCase().formatHex(digest));
      System.out.println("EXPECTED CERTIFICATE SHA256: " + EXPECTED_SHA256);
      System.out.println("CERTIFICATE IDENTITY MATCH: " + (fingerprintMatches ? "PASS" : "FAIL"));
      if (!fingerprintMatches) {
        throw new IllegalStateException("Certificate SHA-256 did not match production identity pin");
      }
      passed = true;
    } catch (Throwable ex) {
      System.err.println("READ-ONLY DISCOVERY: FAIL");
      System.err.println("FAILURE CLASS: " + ex.getClass().getName());
      System.err.println("FAILURE: " + safeMessage(ex));
    } finally {
      if (session != null) {
        try {
          session.closeSession();
        } catch (Throwable ex) {
          passed = false;
          System.err.println("SESSION CLOSE: FAIL (" + ex.getClass().getName() + ")");
        }
      }
      if (module != null && initializationAttempted) {
        try {
          module.finalize(null);
        } catch (Throwable ex) {
          passed = false;
          System.err.println("MODULE FINALIZE: FAIL (" + ex.getClass().getName() + ")");
        }
      }
    }

    if (passed) {
      System.out.println("READ-ONLY HARDWARE DISCOVERY: PASS");
      System.out.println("PROHIBITED PKCS#11 CALLS: NONE IN AUDITED DISCOVERY CODE PATH");
      System.out.println("PRIVATE KEY OPERATION: NO");
      System.out.println("PIN REQUESTED: NO");
      System.out.println("PIN USED: NO");
      System.out.println("TOKEN MODIFIED: NO");
      System.out.println("APK SIGNED: NO");
      System.out.println("WORKFLOW MODIFIED: NO");
      System.out.println("COMMIT: NO");
      System.out.println("PUSH: NO");
    } else {
      System.exit(1);
    }
  }

  private static String safeMessage(Throwable ex) {
    String message = ex.getMessage();
    if (message == null || message.isBlank()) {
      return "(no message)";
    }
    return message.replaceAll("[\\r\\n\\t]", " ");
  }
}
