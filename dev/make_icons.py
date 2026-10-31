#!/usr/bin/env python3
"""
Rebuild chainproxy.ico and assets/chainproxy-<size>.png from assets/chainproxy-256.png (needs Pillow).

    python3 dev/make_icons.py

Why a hand-made ICO: the old file held ONE 256x256 PNG-compressed image. Tk's iconbitmap and the
taskbar cannot always use that, and Windows then falls back to the icon of pythonw.exe (the Python
logo). This ICO has classic BMP entries for 16..128 px and a PNG only for 256 px.
"""
import io
import struct
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "chainproxy-256.png"
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128]


def bmp_entry(img):
    """DIB payload of an ICO entry: BITMAPINFOHEADER + BGRA pixels (bottom-up) + AND mask."""
    w, h = img.size
    px = img.convert("RGBA").tobytes()
    rows = [px[y * w * 4:(y + 1) * w * 4] for y in range(h)][::-1]
    bgra = bytearray()
    for row in rows:
        for i in range(0, len(row), 4):
            r, g, b, a = row[i:i + 4]
            bgra += bytes((b, g, r, a))
    mask_row = ((w + 31) // 32) * 4
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(bgra) + mask_row * h, 0, 0, 0, 0)
    return header + bytes(bgra) + bytes(mask_row * h)       # alpha channel does the masking


def main():
    base = Image.open(SRC).convert("RGBA")
    entries = []
    for s in SIZES:
        entries.append((s, bmp_entry(base.resize((s, s), Image.LANCZOS)), False))
    buf = io.BytesIO()
    base.save(buf, "PNG", optimize=True)
    entries.append((256, buf.getvalue(), True))
    out = bytearray(struct.pack("<HHH", 0, 1, len(entries)))
    offset = 6 + 16 * len(entries)
    for s, data, _png in entries:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _s, data, _png in entries:
        out += data
    (ROOT / "chainproxy.ico").write_bytes(bytes(out))
    for s in (16, 32, 48, 64, 128):
        base.resize((s, s), Image.LANCZOS).save(ROOT / "assets" / f"chainproxy-{s}.png", optimize=True)
    print(f"chainproxy.ico: {len(out) // 1024} KiB, {len(entries)} sizes; assets/chainproxy-*.png written")


if __name__ == "__main__":
    main()
