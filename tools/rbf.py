#!/usr/bin/env python3
"""Cyclone IV E (EP4CE22) uncompressed .rbf container: parse, edit, re-CRC.

Layout (718569 bytes, decoded from Quartus 13.1 output; see NOTES.md):
  [0:32)        0xFF padding
  [32]          0x6A sync
  [33:73)       option header (40 bytes; contains JTAG USERCODE)
  [73:75)       CRC-16 over [33:73), little-endian
  [75:330)      0xFF padding
  [330:7482)    periphery block, 1788 bytes each repeated 4x: 6 logical frames x 298 bytes, same
                layout as the CRAM frames (lead byte, 295 data bytes, CRC-16 over 1..295, LE)
  [7482:...)    2386 frames x 298 bytes:
                  byte 0      always 0x00 (not in CRC)
                  bytes 1..295 configuration data
                  bytes 296..297 CRC-16 over bytes 1..295, little-endian
  tail          59 bytes 0xFF
CRC-16: poly 0x8005 reflected (0xA001), init 0xFFFF, no xorout (CRC-16/MODBUS).
"""
import sys

SIZE = 718569
HDR, HDR_END = 33, 73
PERIPH, PERIPH_LEN = 330, 1788 * 4
F0, FLEN, NFRAMES = 7482, 298, 2386


def crc16(data, c=0xFFFF):
    for x in data:
        c ^= x
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c


class Rbf:
    def __init__(self, data):
        self.d = bytearray(data)
        assert len(self.d) == SIZE, f"unexpected size {len(self.d)}"
        assert self.d[32] == 0x6A, "missing sync byte"

    @classmethod
    def load(cls, path):
        return cls(open(path, "rb").read())

    def frame_off(self, f):
        return F0 + FLEN * f

    def frame(self, f):
        o = self.frame_off(f)
        return bytes(self.d[o + 1:o + 296])

    def get_bit(self, f, byte, bit):
        """byte is the offset within the 298-byte frame (1..295)."""
        return (self.d[self.frame_off(f) + byte] >> bit) & 1

    def set_bit(self, f, byte, bit, v):
        o = self.frame_off(f) + byte
        assert 1 <= byte <= 295
        self.d[o] = (self.d[o] & ~(1 << bit)) | ((v & 1) << bit)

    def periph(self):
        return bytes(self.d[PERIPH + 4 * k] for k in range(PERIPH_LEN // 4))

    def set_periph(self, k, v):
        self.d[PERIPH + 4 * k:PERIPH + 4 * k + 4] = bytes([v]) * 4

    def fix_crcs(self):
        c = crc16(self.d[HDR:HDR_END])
        self.d[HDR_END:HDR_END + 2] = c.to_bytes(2, "little")
        L = self.periph()
        for f in range(len(L) // FLEN):
            o = FLEN * f
            for k, v in zip((o + 296, o + 297), crc16(L[o + 1:o + 296]).to_bytes(2, "little")):
                self.set_periph(k, v)
        for f in range(NFRAMES):
            o = self.frame_off(f)
            c = crc16(self.d[o + 1:o + 296])
            self.d[o + 296:o + 298] = c.to_bytes(2, "little")

    def check(self):
        errs = []
        if crc16(self.d[HDR:HDR_END]) != int.from_bytes(self.d[HDR_END:HDR_END + 2], "little"):
            errs.append("header")
        for f in range(NFRAMES):
            o = self.frame_off(f)
            if self.d[o] != 0:
                errs.append(f"frame {f} lead byte")
            if crc16(self.d[o + 1:o + 296]) != int.from_bytes(self.d[o + 296:o + 298], "little"):
                errs.append(f"frame {f} crc")
        L = self.periph()
        for f in range(len(L) // FLEN):
            o = FLEN * f
            if crc16(L[o + 1:o + 296]) != int.from_bytes(L[o + 296:o + 298], "little"):
                errs.append(f"periphery frame {f} crc")
        blk = self.d[PERIPH:PERIPH + PERIPH_LEN]
        if any(blk[i:i + 4] != bytes([blk[i]]) * 4 for i in range(0, len(blk), 4)):
            errs.append("periphery not 4x")
        return errs

    def save(self, path):
        open(path, "wb").write(self.d)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        e = Rbf.load(p).check()
        print(p, "OK" if not e else e[:5])
