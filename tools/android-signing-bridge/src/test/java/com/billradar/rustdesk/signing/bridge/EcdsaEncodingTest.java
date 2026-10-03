package com.billradar.rustdesk.signing.bridge;

import static org.junit.jupiter.api.Assertions.*;

import java.util.Arrays;
import org.junit.jupiter.api.Test;

class EcdsaEncodingTest {
    @Test
    void encodesOrdinaryComponentsAndRoundTrips() {
        byte[] raw = new byte[64];
        raw[31] = 0x7f;
        raw[63] = 0x01;
        byte[] der = RawEcdsaToDer.encode(raw, 32);
        assertEquals(0x30, der[0] & 0xff);
        assertArrayEquals(raw, RawEcdsaToDer.decode(der, 32));
    }

    @Test
    void insertsPositiveIntegerPaddingForHighBitInRAndS() {
        byte[] raw = new byte[64];
        raw[0] = (byte) 0x80;
        raw[32] = (byte) 0xff;
        byte[] der = RawEcdsaToDer.encode(raw, 32);
        assertEquals(0x00, der[4] & 0xff);
        int sIntegerTag = 2 + 2 + 33;
        assertEquals(0x02, der[sIntegerTag] & 0xff);
        assertEquals(0x00, der[sIntegerTag + 2] & 0xff);
        assertArrayEquals(raw, RawEcdsaToDer.decode(der, 32));
    }

    @Test
    void removesLeadingZerosAndEncodesZeroAsOneByteInteger() {
        byte[] raw = new byte[64];
        raw[30] = 0x01;
        raw[31] = 0x02;
        raw[63] = 0x03;
        byte[] der = RawEcdsaToDer.encode(raw, 32);
        assertArrayEquals(raw, RawEcdsaToDer.decode(der, 32));

        byte[] zero = RawEcdsaToDer.encode(new byte[64], 32);
        assertArrayEquals(new byte[]{0x30, 0x06, 0x02, 0x01, 0x00, 0x02, 0x01, 0x00}, zero);
        assertArrayEquals(new byte[64], RawEcdsaToDer.decode(zero, 32));
    }

    @Test
    void rejectsWrongRawLengthAndMalformedDer() {
        assertThrows(IllegalArgumentException.class, () -> RawEcdsaToDer.encode(new byte[63], 32));
        assertThrows(IllegalArgumentException.class, () -> RawEcdsaToDer.decode(
                new byte[]{0x30, 0x03, 0x02, 0x01, 0x01}, 32));
        assertThrows(IllegalArgumentException.class, () -> RawEcdsaToDer.encode(new byte[0], 32));
    }

    @Test
    void usesCanonicalP256DerSequenceLength() {
        byte[] raw = new byte[64];
        Arrays.fill(raw, (byte) 0x80);
        byte[] der = RawEcdsaToDer.encode(raw, 32);
        assertEquals(0x30, der[0] & 0xff);
        assertEquals(der.length - 2, der[1] & 0xff);
        assertTrue((der[1] & 0x80) == 0);
        assertEquals(64, RawEcdsaToDer.decode(der, 32).length);
    }
}
