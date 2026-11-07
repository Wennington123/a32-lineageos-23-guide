#!/usr/bin/env python3
"""Build a vbmeta image the Samsung A32 LK accepts: AVB structure + zero padding to 64 KiB.

The stock vbmeta partition dumps 65614 bytes on the A32 (mt6768) while the bootloader
only accepts up to 65536. Flashing the raw dump (even with Heimdall --skip-size-check)
prints "vbmeta binary size (65614) over ... partition size" and can bootloop with
"set warranty bit: vbmeta". Truncating blindly to 65536 also fails: the AVB image
ends at 7616 bytes and the rest is slack.

This script reads a partition dump, keeps exactly the real AVB image
(256-byte header + authentication block + auxiliary block, sizes big-endian at
offsets 12 and 20), sets the vbmeta flags byte, and pads to 65536.

Usage:
    ./fix_vbmeta.py vbmeta_stock.img -o vbmeta_64k_fixed.img --flags 3
    ./fix_vbmeta.py vbmeta_stock.img -o vbmeta_64k_stock.img --flags 0

flags=3 disables avbtool hashtree + verification (what you want for custom ROMs).
flags=0 keeps the stock behaviour (rollback to stock).
"""
import argparse
import struct
import sys

MAX_SIZE = 65536


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump", help="raw partition dump (e.g. from dd)")
    ap.add_argument("-o", "--output", default="vbmeta_64k_fixed.img")
    ap.add_argument("--flags", type=lambda s: int(s, 0), default=3,
                    help="vbmeta flags byte (default 3 = disabled hashtree/verification)")
    args = ap.parse_args()

    with open(args.dump, "rb") as f:
        data = f.read()

    if data[0:4] != b"AVB0":
        print("error: not an AVB image (missing AVB0 magic)", file=sys.stderr)
        return 1

    auth = struct.unpack(">Q", data[12:20])[0]
    aux = struct.unpack(">Q", data[20:28])[0]
    image_size = 256 + auth + aux

    if image_size > MAX_SIZE:
        print(f"error: AVB image itself is {image_size} bytes (> {MAX_SIZE})", file=sys.stderr)
        return 1

    image = bytearray(data[:image_size])
    image[120] = args.flags & 0xFF
    image.extend(b"\x00" * (MAX_SIZE - len(image)))

    with open(args.output, "wb") as f:
        f.write(image)

    print(f"AVB image: {image_size} bytes (header 256 + auth {auth} + aux {aux})")
    print(f"written:   {args.output} ({len(image)} bytes, flags=0x{args.flags:02x})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
