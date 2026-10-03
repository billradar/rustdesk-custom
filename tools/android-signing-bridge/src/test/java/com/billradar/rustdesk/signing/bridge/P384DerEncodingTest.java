package com.billradar.rustdesk.signing.bridge;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;

class P384DerEncodingTest {

    @Test
    void stripsLeadingZeroAndAddsPositiveIntegerPaddingForP384() {
        byte[] raw = new byte[96];
        raw[1] = (byte) 0x80;
        raw[49] = 0x7f;

        byte[] der = RawEcdsaToDer.encode(raw, 48);

        assertEquals(101, der.length);
        assertEquals(0x30, der[0] & 0xff);
        assertEquals(99, der[1] & 0xff);
        assertEquals(0x02, der[2] & 0xff);
        assertEquals(48, der[3] & 0xff);
        assertEquals(0, der[4] & 0xff);
        assertEquals(0x80, der[5] & 0xff);
        assertEquals(0x02, der[52] & 0xff);
        assertEquals(47, der[53] & 0xff);
        assertEquals(0x7f, der[54] & 0xff);
        assertArrayEquals(raw, RawEcdsaToDer.decode(der, 48));
    }
}
