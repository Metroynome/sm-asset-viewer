"""Extract a PS2 Size Matters ISO and checksum-verify HIG/TJZIP archives.
Uses electrogecko's reviewed TJZIP token decoder (tools/upstream/tjzip_dump.py).
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import sys
import zlib

sys.path.insert(0, str(Path(__file__).parent / 'upstream'))
import tjzip_dump as tj


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def iso_files(stream, iso_size):
    stream.seek(16 * 2048)
    pvd = stream.read(2048)
    if pvd[:7] != b'\x01CD001\x01':
        raise ValueError('Expected ISO9660 primary volume descriptor')
    seen = set()
    def walk(record, parent):
        offset, size = u32(record, 2) * 2048, u32(record, 10)
        if offset + size > iso_size or offset in seen:
            raise ValueError('Invalid/cyclic ISO directory')
        seen.add(offset)
        stream.seek(offset)
        data = stream.read(size)
        pos = 0
        while pos < len(data):
            n = data[pos]
            if not n:
                pos = (pos // 2048 + 1) * 2048
                continue
            record = data[pos:pos+n]
            pos += n
            if len(record) < 34:
                raise ValueError('Truncated directory record')
            raw = record[33:33+record[32]]
            if raw in (b'\0', b'\1'):
                continue
            name = raw.decode('ascii').split(';')[0]
            if name in ('', '.', '..') or any(c in name for c in '/\\:'):
                raise ValueError('Unsafe ISO filename')
            path = parent / name
            if record[25] & 2:
                yield from walk(record, path)
            else:
                off, length = u32(record, 2) * 2048, u32(record, 10)
                if off + length > iso_size or record[25] & 0x80:
                    raise ValueError('Out of bounds or multi-extent file')
                yield path, off, length
    return list(walk(pvd[156:156+pvd[156]], Path()))


def decompress(blob):
    if len(blob) < 0xc0 or blob[:4] != b'HIG!':
        raise ValueError('Not a HIG archive')
    expected, packed = u32(blob, 0x3c), u32(blob, 0x40)
    if packed != len(blob)-0xc0 or expected > 512*1024*1024:
        raise ValueError('Invalid archive sizes')
    comp = blob[0xc0:]
    out = bytearray(expected)
    ip, op, crc = tj.tjzip_parse_raw(comp, 0, out, 0, crc=0, crc_table=None)
    while ip < len(comp):
        ip, op, crc, post = tj.tjzip_parse_dict(comp, ip, out, op, crc=0, crc_table=None)
        if ip == len(comp) and op == expected:
            break
        if post == 0:
            ip, op, crc = tj.tjzip_parse_raw(comp, ip, out, op, crc=0, crc_table=None)
        elif post in (1, 2):
            if ip+post > len(comp) or op+post > expected:
                raise ValueError('Literal overrun')
            out[op:op+post] = comp[ip:ip+post]
            ip += post
            op += post
    if ip != len(comp) or op != expected:
        raise ValueError(f'Length mismatch: input {ip}/{len(comp)}, output {op}/{expected}')
    actual = zlib.crc32(out, 0xffffffff)
    if actual != u32(blob, 0x34):
        raise ValueError(f'CRC mismatch: {actual:08x} != {u32(blob, 0x34):08x}')
    return bytes(out), actual


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == data:
            return
        raise FileExistsError(f'Refusing to replace different file: {path}')
    with path.open('xb') as f:
        f.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('iso', type=Path)
    ap.add_argument('--output', type=Path, required=True, help='New output directory (must not exist)')
    ap.add_argument('--resume', action='store_true', help='Reuse existing disc files after byte comparison against ISO')
    args = ap.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=args.resume)
    report = {'iso': str(args.iso.resolve()), 'files': [], 'archives': [], 'errors': []}
    with args.iso.open('rb') as iso:
        entries = iso_files(iso, args.iso.stat().st_size)
        for rel, off, length in entries:
            dest = root / 'disc' / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            iso.seek(off)
            digest = hashlib.sha256()
            reuse = args.resume and dest.exists()
            if reuse and dest.stat().st_size != length:
                raise ValueError(f'Existing file size mismatch: {dest}')
            with dest.open('rb' if reuse else 'xb') as output:
                remaining = length
                while remaining:
                    block = iso.read(min(1024*1024, remaining))
                    if not block:
                        raise ValueError('Unexpected ISO EOF')
                    if reuse:
                        if output.read(len(block)) != block:
                            raise ValueError(f'Existing file differs from ISO: {dest}')
                    else:
                        output.write(block)
                    digest.update(block)
                    remaining -= len(block)
            report['files'].append({'path': rel.as_posix(), 'iso_offset': off, 'size': length, 'sha256': digest.hexdigest()})
            with dest.open('rb') as f:
                magic = f.read(4)
            if magic != b'HIG!':
                continue
            try:
                blob = dest.read_bytes()
                payload, crc = decompress(blob)
                archive_dir = root / 'unpacked' / rel
                write_new(archive_dir / 'payload.bin', payload)
                # Retain the original header for investigation; its compression fields
                # still describe the on-disc stream. This is not a repackable archive.
                full = blob[:0xc0] + payload
                write_new(archive_dir / 'header.bin', blob[:0xc0])
                pointers = [(slot, u32(blob, slot)) for slot in range(4, 0x34, 4) if u32(blob, slot)]
                bounds = sorted(set(value for _, value in pointers))
                if any(value < 0xc0 or value >= len(full) for value in bounds):
                    raise ValueError('Section offset outside reconstructed header + payload')
                sections = []
                for index, start in enumerate(bounds):
                    end = bounds[index+1] if index+1 < len(bounds) else len(full)
                    slots = [slot for slot, value in pointers if value == start]
                    filename = f'sections/{start:08x}_slot_{slots[0]:02x}.bin'
                    write_new(archive_dir / filename, full[start:end])
                    sections.append({'file': filename, 'header_slots': slots, 'offset': start, 'size': end-start, 'prefix_hex': full[start:start+16].hex()})
                info = {'path': rel.as_posix(), 'compressed_size': len(blob)-0xc0, 'payload_size': len(payload), 'crc32': f'{crc:08x}', 'crc_verified': True, 'payload_sha256': hashlib.sha256(payload).hexdigest(), 'source_name': blob[0x44:0xc0].split(b'\0')[0].decode('ascii', errors='replace'), 'sections': sections}
                write_new(archive_dir / 'manifest.json', json.dumps(info, indent=2).encode())
                report['archives'].append(info)
                print(f'OK {rel}: {len(payload):,} bytes, CRC {crc:08x}, {len(sections)} sections', flush=True)
            except Exception as exc:
                report['errors'].append({'path': rel.as_posix(), 'error': str(exc)})
                print(f'ERROR {rel}: {exc}', flush=True)
    manifest = root / 'manifest.json'
    if manifest.exists():
        previous = root / 'manifest.previous.json'
        if previous.exists():
            raise FileExistsError('Previous manifest backup already exists')
        manifest.rename(previous)
    write_new(manifest, json.dumps(report, indent=2).encode())
    print(f"Extracted {len(report['files'])} disc files; verified {len(report['archives'])} HIG archives; {len(report['errors'])} errors.", flush=True)
    return bool(report['errors'])


if __name__ == '__main__':
    sys.exit(main())
