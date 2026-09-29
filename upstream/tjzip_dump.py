#!/usr/bin/env python3
"""TJZIP / HIG! WAD decompressor.

Implements the byte-oriented TJZIP decoder used

  - TJZIP_ParseRawDataBlock__FPPUcT0PUi
  - TJZIP_ParseDictionaryCode__FPPUcT0PUi
  - TJZIP_Decompress__FPUcT0UiPUiT0PFPUc_PUc

This tool focuses on dumping the fully-decompressed payload from a single-file
"HIG!" WAD (e.g. 17.WAD). It does not attempt post-processing/fixups.

Usage examples:
  python3 tjzip_dump.py /path/to/17.WAD -o out.bin
  python3 tjzip_dump.py /path/to/17.WAD -o out.bin --verify /path/to/known_out.bin

Notes:
  - CRC computation is optional. If you have a CRC table dump, you can wire it
    in via --crc-table (space-delimited bytes or raw 1024-byte table).
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path
from typing import Optional, Tuple, List


HEADER_MAGIC = b"HIG!"


class TJZIPError(RuntimeError):
    pass


def _u32le(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def parse_hig_wad(blob: bytes, *, base_off: int = 0) -> Tuple[int, int, int]:
    """Return (header_size, comp_off, decomp_size) for a HIG! wad at base_off."""
    if blob[base_off:base_off + 4] != HEADER_MAGIC:
        raise TJZIPError("Not a HIG! WAD at given offset")
    header_size = _u32le(blob, base_off + 4)
    if header_size < 0x40 or header_size > len(blob) - base_off:
        raise TJZIPError(f"Unreasonable header_size=0x{header_size:x}")
    decomp_size = _u32le(blob, base_off + 0x3C)
    comp_off = base_off + header_size
    if comp_off > len(blob):
        raise TJZIPError("Compressed offset past EOF")
    return header_size, comp_off, decomp_size


def load_crc_table(path: Path) -> List[int]:
    """Load CRC table as 256 u32 entries.

    Accepts either:
      - raw 1024 bytes (little-endian u32 table)
      - ASCII space/newline delimited bytes (0-255). If ASCII, length must be 1024.
    """
    data = path.read_bytes()
    # Try raw
    if len(data) == 1024:
        return list(struct.unpack("<256I", data))
    # Try ASCII bytes
    try:
        txt = data.decode("ascii", errors="strict")
    except Exception as e:
        raise TJZIPError(f"Unsupported CRC table format: {e}")
    parts = [p for p in txt.replace("\n", " ").replace("\r", " ").split(" ") if p]
    b = bytes(int(p, 0) & 0xFF for p in parts)
    if len(b) != 1024:
        raise TJZIPError(f"ASCII CRC table must decode to 1024 bytes, got {len(b)}")
    return list(struct.unpack("<256I", b))


def crc_update(crc: int, byte_val: int, table: List[int]) -> int:
    idx = (crc ^ byte_val) & 0xFF
    return ((crc >> 8) ^ table[idx]) & 0xFFFFFFFF


def tjzip_parse_raw(inbuf: bytes, inpos: int, out: bytearray, outpos: int,
                    *, crc: int, crc_table: Optional[List[int]]) -> Tuple[int, int, int]:
    """ParseRawDataBlock: copies a literal block from input to output."""
    if inpos >= len(inbuf):
        raise TJZIPError("Raw block: input underrun")
    b0 = inbuf[inpos]
    inpos += 1
    if b0 != 0:
        run_len = b0 + 2
    else:
        if inpos + 2 > len(inbuf):
            raise TJZIPError("Raw block: input underrun on u16")
        run_len = inbuf[inpos] | (inbuf[inpos + 1] << 8)
        inpos += 2

    if outpos + run_len > len(out):
        raise TJZIPError("Raw block: output overrun")
    if inpos + run_len > len(inbuf):
        raise TJZIPError("Raw block: input underrun on payload")

    if crc_table is None:
        out[outpos:outpos + run_len] = inbuf[inpos:inpos + run_len]
        return inpos + run_len, outpos + run_len, crc

    # Update CRC per-byte
    for i in range(run_len):
        v = inbuf[inpos + i]
        out[outpos + i] = v
        crc = crc_update(crc, v, crc_table)
    return inpos + run_len, outpos + run_len, crc


def tjzip_parse_dict(inbuf: bytes, inpos: int, out: bytearray, outpos: int,
                     *, crc: int, crc_table: Optional[List[int]]) -> Tuple[int, int, int, int]:
    """ParseDictionaryCode: decodes one backreference and copies it, returning (inpos,outpos,crc,post)."""
    if inpos + 2 > len(inbuf):
        raise TJZIPError("Dict: input underrun")
    b1 = inbuf[inpos]
    b2 = inbuf[inpos + 1]
    inpos += 2

    top = b1 & 0xE0
    if top < 0xC0:
        length = (b1 >> 5) + 4
        dist = ((b1 << 6) & 0x300) | b2
        post = b1 & 0x03
    elif top == 0xC0:
        if inpos >= len(inbuf):
            raise TJZIPError("Dict(C0): input underrun")
        b3 = inbuf[inpos]
        inpos += 1
        length = (b1 & 0x1F) + 4
        dist = ((b2 << 6) & 0x3F00) | b3
        post = b2 & 0x03
    else:
        # 0xE0
        if inpos >= len(inbuf):
            raise TJZIPError("Dict(E0): input underrun")
        b3 = inbuf[inpos]
        inpos += 1
        small_len = (b1 & 0x0F) + 3
        if small_len >= 4:
            length = small_len
            dist = ((b1 & 0x10) << 10) | ((b2 & 0xFC) << 6) | b3
            post = b2 & 0x03
        else:
            # extended length
            if inpos >= len(inbuf):
                raise TJZIPError("Dict(E0/ext): input underrun on b4")
            b4 = inbuf[inpos]
            inpos += 1
            length2 = b2 + 0x12
            if length2 >= 0x13:
                length = length2
                dist = ((b1 & 0x10) << 10) | ((b3 & 0xFC) << 6) | b4
                post = b3 & 0x03
            else:
                # very-extended length uses b3:b4 as length, and reads b5,b6 for distance
                if inpos + 2 > len(inbuf):
                    raise TJZIPError("Dict(E0/veryext): input underrun")
                b5 = inbuf[inpos]
                b6 = inbuf[inpos + 1]
                inpos += 2
                length = (b3 << 8) | b4
                dist = ((b1 & 0x10) << 10) | ((b5 & 0xFC) << 6) | b6
                post = b5 & 0x03

    if dist == 0:
        raise TJZIPError("Dict: zero distance")
    if dist > outpos:
        raise TJZIPError(f"Dict: backref distance {dist} beyond output pos {outpos}")
    if outpos + length > len(out):
        raise TJZIPError("Dict: output overrun")

    src = outpos - dist
    if crc_table is None:
        # bytewise copy to support overlap
        for i in range(length):
            out[outpos + i] = out[src + i]
        return inpos, outpos + length, crc, post

    for i in range(length):
        v = out[src + i]
        out[outpos + i] = v
        crc = crc_update(crc, v, crc_table)
    return inpos, outpos + length, crc, post


def tjzip_decompress(comp: bytes, decomp_size: int,
                     *, crc_table: Optional[List[int]] = None,
                     limit_out: Optional[int] = None,
                     history_size: int = 0) -> Tuple[bytes, int]:
    """Decompress TJZIP stream.

    Returns (output_bytes, final_crc) where final_crc is ~crc if crc_table provided, else 0.
    """
    # The original routine allows dictionary distances to reference memory *before*
    # the output start pointer (a classic LZ sliding-window history buffer).
    # Provide an optional zero-initialized history prefix to support those streams.
    out = bytearray(history_size + decomp_size)
    inpos = 0
    outpos = history_size
    crc = 0

    # Initial raw block
    inpos, outpos, crc = tjzip_parse_raw(comp, inpos, out, outpos, crc=crc, crc_table=crc_table)
    if limit_out is not None and outpos >= limit_out:
        return bytes(out[history_size:history_size + limit_out]), (~crc) & 0xFFFFFFFF if crc_table else 0

    # Main loop: parse dict, then optional literal/raw
    comp_len = len(comp)
    while inpos < comp_len:
        inpos, outpos, crc, post = tjzip_parse_dict(comp, inpos, out, outpos, crc=crc, crc_table=crc_table)

        if limit_out is not None and outpos >= limit_out:
            return bytes(out[history_size:history_size + limit_out]), (~crc) & 0xFFFFFFFF if crc_table else 0

        # IMPORTANT: per TJZIP_Decompress, post==3 means "no trailing bytes" (neither raw nor literal).
        if post == 0:
            inpos, outpos, crc = tjzip_parse_raw(comp, inpos, out, outpos, crc=crc, crc_table=crc_table)
        elif post in (1, 2):
            # copy 'post' literal bytes
            if inpos + post > comp_len:
                raise TJZIPError("Post-literal: input underrun")
            if outpos + post > len(out):
                raise TJZIPError("Post-literal: output overrun")
            if crc_table is None:
                out[outpos:outpos + post] = comp[inpos:inpos + post]
                inpos += post
                outpos += post
            else:
                for i in range(post):
                    v = comp[inpos + i]
                    out[outpos + i] = v
                    crc = crc_update(crc, v, crc_table)
                inpos += post
                outpos += post
        elif post == 3:
            pass
        else:
            raise TJZIPError(f"Unexpected post value {post}")

        if limit_out is not None and (outpos - history_size) >= limit_out:
            return bytes(out[history_size:history_size + limit_out]), (~crc) & 0xFFFFFFFF if crc_table else 0

    # Finished input. Final CRC is bitwise NOT.
    final_crc = (~crc) & 0xFFFFFFFF if crc_table else 0
    return bytes(out[history_size:history_size + decomp_size]), final_crc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wad", type=Path, help="Input HIG! WAD file")
    ap.add_argument("-o", "--out", type=Path, required=True, help="Output decompressed blob")
    ap.add_argument("--crc-table", type=Path, default=None, help="CRC table dump (optional)")
    ap.add_argument("--verify", type=Path, default=None, help="Known-good decompressed blob to compare")
    ap.add_argument("--history", type=lambda x: int(x, 0), default=0x10000,
                    help="Zero-initialized history prefix size (hex allowed). Default 0x10000")
    ap.add_argument("--include-history", action="store_true",
                    help="Write the history prefix + decompressed payload (useful for matching in-memory dumps)")
    ap.add_argument("--limit-out", type=lambda x: int(x, 0), default=None,
                    help="Stop after producing N output bytes (hex allowed)")
    args = ap.parse_args()

    blob = args.wad.read_bytes()
    header_size, comp_off, decomp_size = parse_hig_wad(blob)
    comp = blob[comp_off:]

    table = load_crc_table(args.crc_table) if args.crc_table else None
    out_bytes, final_crc = tjzip_decompress(
        comp,
        decomp_size,
        crc_table=table,
        limit_out=args.limit_out,
        history_size=args.history,
    )

    if args.include_history and args.history:
        args.out.write_bytes(b"\x00" * args.history + out_bytes)
    else:
        args.out.write_bytes(out_bytes)

    if args.verify:
        ref = args.verify.read_bytes()
        n = min(len(ref), len(out_bytes))
        if ref[:n] != out_bytes[:n] or len(ref) != len(out_bytes):
            # find first mismatch
            mm = None
            for i in range(n):
                if ref[i] != out_bytes[i]:
                    mm = i
                    break
            if mm is None and len(ref) != len(out_bytes):
                mm = n
            raise SystemExit(f"VERIFY FAILED: first mismatch at 0x{mm:x} (ref_len={len(ref)}, out_len={len(out_bytes)})")
        print("VERIFY OK")

    if table:
        print(f"Final CRC: 0x{final_crc:08x}")
    print(f"Wrote {len(out_bytes)} bytes (decomp_size=0x{decomp_size:x}, header_size=0x{header_size:x}, comp_size=0x{len(comp):x})")


if __name__ == "__main__":
    main()
