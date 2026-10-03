package com.billradar.rustdesk.signing.bridge;

import java.io.ByteArrayOutputStream;
import java.math.BigInteger;
import java.util.Arrays;

/** Converts fixed-width PKCS#11 ECDSA r || s output into canonical ASN.1 DER. */
final class RawEcdsaToDer {
    private RawEcdsaToDer() { }

    static byte[] encode(byte[] raw, int componentLength) {
        if (raw == null || componentLength < 1 || raw.length != componentLength * 2) {
            throw new IllegalArgumentException("Invalid raw ECDSA signature length");
        }
        byte[] r = derInteger(Arrays.copyOfRange(raw, 0, componentLength));
        byte[] s = derInteger(Arrays.copyOfRange(raw, componentLength, raw.length));
        int contentLength = r.length + s.length;
        ByteArrayOutputStream out = new ByteArrayOutputStream(contentLength + 4);
        out.write(0x30);
        writeLength(out, contentLength);
        out.writeBytes(r);
        out.writeBytes(s);
        return out.toByteArray();
    }

    static byte[] decode(byte[] der, int componentLength) {
        if (der == null || componentLength < 1) {
            throw new IllegalArgumentException("Invalid DER ECDSA signature");
        }
        Cursor cursor = new Cursor(der);
        if (cursor.readByte() != 0x30) {
            throw new IllegalArgumentException("ECDSA signature is not a DER sequence");
        }
        int sequenceLength = cursor.readLength();
        if (sequenceLength != der.length - cursor.position) {
            throw new IllegalArgumentException("Invalid DER sequence length");
        }
        byte[] r = cursor.readInteger();
        byte[] s = cursor.readInteger();
        if (cursor.position != der.length) {
            throw new IllegalArgumentException("Trailing DER data");
        }
        byte[] raw = new byte[componentLength * 2];
        copyUnsignedComponent(r, raw, 0, componentLength);
        copyUnsignedComponent(s, raw, componentLength, componentLength);
        return raw;
    }

    private static byte[] derInteger(byte[] fixedWidth) {
        int first = 0;
        while (first < fixedWidth.length - 1 && fixedWidth[first] == 0) {
            first++;
        }
        boolean needsSignPadding = (fixedWidth[first] & 0x80) != 0;
        int valueLength = fixedWidth.length - first;
        ByteArrayOutputStream out = new ByteArrayOutputStream(valueLength + 4);
        out.write(0x02);
        writeLength(out, valueLength + (needsSignPadding ? 1 : 0));
        if (needsSignPadding) {
            out.write(0);
        }
        out.write(fixedWidth, first, valueLength);
        return out.toByteArray();
    }

    private static void writeLength(ByteArrayOutputStream out, int length) {
        if (length < 0x80) {
            out.write(length);
            return;
        }
        int bytes = 0;
        int value = length;
        while (value != 0) {
            bytes++;
            value >>>= 8;
        }
        out.write(0x80 | bytes);
        for (int shift = (bytes - 1) * 8; shift >= 0; shift -= 8) {
            out.write((length >>> shift) & 0xff);
        }
    }

    private static void copyUnsignedComponent(byte[] integer, byte[] target, int offset, int width) {
        if (integer.length == 0 || (integer[0] & 0x80) != 0) {
            throw new IllegalArgumentException("DER ECDSA integer must be positive");
        }
        int first = integer.length > 1 && integer[0] == 0 ? 1 : 0;
        int length = integer.length - first;
        if (length > width) {
            throw new IllegalArgumentException("ECDSA integer exceeds curve width");
        }
        System.arraycopy(integer, first, target, offset + width - length, length);
    }

    private static final class Cursor {
        private final byte[] data;
        private int position;

        private Cursor(byte[] data) {
            this.data = data;
        }

        private int readByte() {
            if (position >= data.length) {
                throw new IllegalArgumentException("Truncated DER signature");
            }
            return data[position++] & 0xff;
        }

        private int readLength() {
            int first = readByte();
            if ((first & 0x80) == 0) {
                return first;
            }
            int count = first & 0x7f;
            if (count == 0 || count > 4 || position + count > data.length || data[position] == 0) {
                throw new IllegalArgumentException("Invalid DER length");
            }
            int value = 0;
            for (int i = 0; i < count; i++) {
                value = (value << 8) | readByte();
            }
            if (value < 0x80) {
                throw new IllegalArgumentException("Non-minimal DER length");
            }
            return value;
        }

        private byte[] readInteger() {
            if (readByte() != 0x02) {
                throw new IllegalArgumentException("ECDSA sequence must contain INTEGERs");
            }
            int length = readLength();
            if (length == 0 || position + length > data.length) {
                throw new IllegalArgumentException("Invalid DER INTEGER length");
            }
            byte[] value = Arrays.copyOfRange(data, position, position + length);
            position += length;
            BigInteger integer = new BigInteger(value);
            if (integer.signum() < 0 || !Arrays.equals(integer.toByteArray(), value)) {
                throw new IllegalArgumentException("Non-canonical DER INTEGER");
            }
            return value;
        }
    }
}
