"""Export a searchable, explicitly partial type/symbol reference for an EE dump."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from paths import ROOT, RAC


def cstring(data, address):
    if not 0 < address < len(data):
        raise ValueError('Invalid string pointer')
    end = data.find(b'\0', address, min(address + 4096, len(data)))
    if end < 0:
        raise ValueError('Unterminated symbol name')
    return data[address:end].decode('ascii')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('dump', type=Path)
    ap.add_argument('--symbols', type=Path, default=ROOT / 'symbols/symbols.json')
    ap.add_argument('--plan', type=Path, help='Optional earlier Ghidra import plan with opaque_types')
    ap.add_argument('--output', type=Path, default=ROOT / 'smtypes.txt')
    args = ap.parse_args()
    data = args.dump.read_bytes()
    if len(data) != 32 * 1024 * 1024:
        raise ValueError('Expected a full 32 MiB EE dump, file offset = RAM address')
    symbols = json.loads(args.symbols.read_text())['symbols']
    plan = json.loads(args.plan.read_text()) if args.plan else {'opaque_types': []}
    known = {r['name']: r for r in symbols}
    modules = []
    for match in re.finditer(b'SNR2', data):
        base = match.start()
        table, count, source = struct.unpack_from('<III', data, base + 12)
        if not 0 < count <= 100000 or table + count * 12 > len(data):
            continue
        rows = []
        try:
            for i in range(count):
                ptr, value, _, _, kind, processed = struct.unpack_from('<IIBBBB', data, table + i * 12)
                if ptr and value:
                    name = cstring(data, ptr)
                    if name:
                        rows.append((name, value, kind))
            origin = cstring(data, source) if source else 'boot .sndata'
        except (ValueError, UnicodeDecodeError):
            continue
        modules.append((base, origin, count, rows))
    boot = next((m for m in modules if m[0] == 0x01f0ad00), None)
    if not boot or {(n, v) for n, v, k in boot[3]} != {(r['name'], r['address']) for r in symbols}:
        raise ValueError('Dump boot symbols do not match this release; refusing mixed-build output')
    lines = [
        'SIZE MATTERS - PARTIAL TYPE AND SYMBOL REFERENCE',
        'Build: NTSC-U retail SCUS_976.15',
        f'Dump: {args.dump.resolve()}',
        f'SHA256: {hashlib.sha256(data).hexdigest()}',
        '',
        'LIMITATIONS',
        'This is not a complete debug-type dump or a compilable C header.',
        'SNR2 records provide linkage names and addresses, not C structure layouts.',
        'Decoded C++ names can preserve parameter types and class/namespace names.',
        'No structure members, offsets, sizes, enum values, or general return types are recovered here.',
        'Opaque names below are pointer targets selected by the earlier conservative import plan.',
        'They are NOT an exhaustive list of game types, and their struct/class/typedef identity is unknown.',
        'Ghidra undefined1 placeholders do NOT establish a one-byte object size.',
        'The source boot ELF has no .stab, .stabstr, .mdebug, or .debug_* sections.',
        'Addresses below are resolved RAM addresses; do not add a module base again.',
        'A resident table alone does not prove a module is currently executing.',
        '',
        f'OPAQUE TYPE NAMES ({len(plan["opaque_types"])})',
    ]
    for name in sorted(plan['opaque_types'], key=str.lower):
        lines.extend(['', f'TYPE: {name}', 'Layout: UNKNOWN; size: UNKNOWN'])
        uses = [r for r in symbols if re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', r.get('demangled', ''))]
        lines.extend(f'  0x{r["address"]:08X}  {r["demangled"]}' for r in uses)
    decoded = [r for r in symbols if r.get('demangled', r['name']) != r['name']]
    lines.extend(['', f'ALL DECODED BOOT NAMES ({len(decoded)})',
                  'Includes additional class/type references not in the opaque-name list.',
                  'These are decoded names, not verified complete function prototypes.'])
    for row in sorted(decoded, key=lambda r: r['demangled'].lower()):
        lines.extend([f'0x{row["address"]:08X} [{row["kind"]}] {row["demangled"]}', f'  Linkage: {row["name"]}'])
    lines.extend(['', 'RESIDENT SYMBOL TABLES - ALL NAMED NONZERO RECORDS'])
    for base, origin, count, rows in modules:
        lines.extend(['', f'TABLE 0x{base:08X}: {origin}', f'{count} records; {len(rows)} named nonzero records'])
        for name, value, kind in rows:
            decoded_name = known.get(name, {}).get('demangled', name)
            lines.append(f'0x{value:08X} linkage_kind={kind} {name}')
            if decoded_name != name:
                lines.append(f'  Decoded: {decoded_name}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'opaque_names': len(plan['opaque_types']),
                      'decoded_boot_names': len(decoded), 'tables': [
                          {'address': hex(m[0]), 'source': m[1], 'named_records': len(m[3])} for m in modules]}, indent=2))


if __name__ == '__main__':
    main()
