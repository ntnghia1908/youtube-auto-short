"""Minimal valid PNG / JPEG byte strings for CP8.15 image tests (no Pillow: stdlib only, like the app itself).
The JPEG is a syntactically valid header (SOI, APP0/JFIF, SOF0, EOI) with no real scan data — enough for
``auto_short.post.images.sniff`` (magic bytes + header dimensions), which is all the app reads."""

from __future__ import annotations

import struct
import zlib


def make_png(w: int, h: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit RGB, no interlace
    row = b"\x00" + b"\x00\x00\x00" * w
    idat = zlib.compress(row * h)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def make_jpeg(w: int, h: int) -> bytes:
    def u16(x: int) -> bytes:
        return struct.pack(">H", x)

    soi = b"\xff\xd8"
    app0 = b"\xff\xe0" + u16(16) + b"JFIF\x00" + b"\x01\x01" + b"\x00" + u16(1) + u16(1) + b"\x00\x00"
    sof_content = bytes([8]) + u16(h) + u16(w) + bytes([3]) + bytes([1, 0x11, 0, 2, 0x11, 1, 3, 0x11, 1])
    sof0 = b"\xff\xc0" + u16(len(sof_content) + 2) + sof_content
    eoi = b"\xff\xd9"
    return soi + app0 + sof0 + eoi
