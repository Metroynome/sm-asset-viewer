"""Extract VAGS.WAD table entries and index embedded developer paths in HIG payloads."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import struct
from extract_sm import write_new


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('root', type=Path, help='Extraction output directory')
    args = ap.parse_args()
    root = args.root
    path = root / 'disc/VAGS.WAD'
    entries = []
    with path.open('rb') as f:
        count = struct.unpack('<I', f.read(4))[0]
        if 4+count*12 > path.stat().st_size:
            raise ValueError('VAGS table exceeds archive')
        table = [struct.unpack('<III', f.read(12)) for _ in range(count)]
        previous_end = 4+count*12
        for index, (key, size, offset) in enumerate(table):
            if offset < previous_end or offset+size > path.stat().st_size:
                raise ValueError('VAGS entry overlaps or exceeds archive')
            f.seek(offset)
            data = f.read(size)
            if len(data) != size:
                raise ValueError('Truncated audio entry')
            ext = 'vag' if data[:4] == b'VAGp' else 'bin'
            name = f'{index:04d}_{key:08x}.{ext}'
            write_new(root / 'audio' / name, data)
            entries.append({'file': name, 'id': f'{key:08x}', 'offset': offset, 'size': size, 'magic': data[:4].hex(), 'sha256': hashlib.sha256(data).hexdigest()})
            previous_end = offset+size
    write_new(root / 'audio/manifest.json', json.dumps(entries, indent=2).encode())
    paths = []
    pattern = re.compile(rb'[A-Za-z]:\\[ -~]{5,}')
    for payload in sorted((root / 'unpacked').rglob('payload.bin')):
        data = payload.read_bytes()
        for match in pattern.finditer(data):
            paths.append({'archive': payload.parent.relative_to(root / 'unpacked').as_posix(), 'payload_offset': match.start(), 'reconstructed_offset': match.start()+0xc0, 'source_path': match.group().decode('ascii')})
    write_new(root / 'embedded_paths.json', json.dumps(paths, indent=2).encode())
    print(f'Extracted {len(entries)} audio entries ({sum(e["magic"] == "56414770" for e in entries)} VAGp); indexed {len(paths)} embedded paths.')


if __name__ == '__main__':
    main()
