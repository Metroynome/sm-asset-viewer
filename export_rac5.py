"""Export regional RAC5 boot sections and lossless SNR2 container blocks.
Existing binary files are reused only after an exact byte comparison.
"""
from pathlib import Path
import argparse
import hashlib
import json

from paths import ROOT, RAC

REGIONS = ('ntscu', 'pal', 'ntscj')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def hx(value):
    return f'0x{value:08x}'


def save_json(path, value):
    data = json.dumps(value, indent=2, ensure_ascii=False) + '\n'
    temp = path.with_name(path.name + '.tmp')
    with temp.open('x', encoding='utf-8', newline='\n') as f:
        f.write(data)
    temp.replace(path)


def regional_export(destination, defs, metadata, region):
    meta = metadata if region == 'ntscu' else metadata['regions'][region]
    disc = ROOT / ('extracted/disc' if region == 'ntscu' else region + '/extracted/disc')
    files = []

    def write(path, data, **fields):
        dest = destination / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if dest.read_bytes() != data:
                raise ValueError(f'Refusing to replace different binary: {dest}')
        else:
            with dest.open('xb') as f:
                f.write(data)
        row = {'file': path, 'size': len(data), 'sha256': sha(data), **fields}
        files.append(row)
        return row

    elf = meta['bootElf']
    boot = (disc / elf['file']).read_bytes()
    assert sha(boot) == elf['sha256']
    write(f'boot/elf/rac5.boot.{region}.v100.retail.elf', boot,
          kind='original_elf', source=elf['file'])
    profile = defs['rac']['5']['boot']['region'][region]['version']['1.00']
    core = {}
    for index, desc in profile['core'].items():
        matches = [s for s in elf['sections'] if s['name'] == desc['name']
                   and s['virtualAddress'] == desc['offset'] and s['size'] == desc['size']]
        assert len(matches) == 1
        section = matches[0]
        offset = None if section['zeroInitialized'] else int(section['fileOffset'], 16)
        data = bytes(section['size']) if offset is None else boot[offset:offset + section['size']]
        assert len(data) == section['size']
        core[index] = write(f'boot/core{index}/rac5.boot.{region}.v100.retail.core.{int(index):04d}.bin',
                            data, kind='boot_section', name=desc['name'], virtualAddress=desc['offset'],
                            source=elf['file'], sourceFileOffset=section['fileOffset'],
                            zeroInitialized=section['zeroInitialized'])
    modules = {}
    for filename, module in meta['modules'].items():
        data = (disc / filename).read_bytes()
        assert sha(data) == module['sha256']
        level = -1 if filename.endswith('FRONTEND.REL') else int(Path(filename).stem.split('_')[1])
        prefix = f'rac5.level{level}.{region}.v100.retail'
        full = write(f'modules/{prefix}.rel', data, kind='original_rel', source=filename)
        layout = module['layout']
        reloc = int(layout['relocations']['fileOffset'], 16)
        symbols = int(layout['symbols']['fileOffset'], 16)
        end = symbols + layout['symbols']['size']
        assert reloc + layout['relocations']['size'] == symbols
        bounds = [0, reloc, symbols, end, len(data)]
        assert bounds == sorted(bounds)
        blocks = []
        names = ['module_payload_and_header', 'relocations', 'symbols', 'trailing_data']
        for i, name in enumerate(names):
            start, stop = bounds[i:i+2]
            blocks.append(write(f'code{i}/{prefix}.code.{i:04d}.bin', data[start:stop],
                                kind='rel_block', name=name, source=filename,
                                sourceFileOffset=hx(start), moduleOffset=hx(start), runtimeAddress=None))
        assert b''.join((destination / b['file']).read_bytes() for b in blocks) == data
        modules[filename] = {'level': level, 'original': full['file'], 'size': len(data),
                             'sha256': sha(data), 'libMainOffset': module['libMainOffset'],
                             'loadCallbackOffset': layout['loadCallbackOffset'],
                             'unloadCallbackOffset': layout['unloadCallbackOffset'],
                             'code': {str(i): b for i, b in enumerate(blocks)}, 'reconstructionVerified': True}
    rows = meta['inventory']['rac']['5']['levels'] if region == 'ntscu' else meta['levels']
    levels = []
    for row in rows:
        source = row['region'][region]['version']['1.00'] if region == 'ntscu' else row
        filename = source['module']['file']
        module = modules[filename]
        levels.append({**{k: row[k] for k in ('level', 'gameMode', 'shortName', 'longName')},
                       'sourceModule': filename, 'original': module['original'],
                       'code': {i: b['file'] for i, b in module['code'].items()},
                       'sourceAssets': source.get('assets')})
    return {'game': 'Ratchet & Clank: Size Matters', 'abbreviation': 'rac5',
            'serial': meta['serial'], 'region': region, 'version': '1.00', 'buildType': 'retail',
            'entryPoint': elf['entryPoint'], 'sourceExtraction': str(disc),
            'boot': {'core': core}, 'modules': modules, 'levels': levels, 'files': files,
            'addressConvention': 'Boot virtualAddress values are EE addresses; level offsets are module-relative, not runtime addresses.',
            'codeBlockConvention': {'0': 'REL prefix before relocations, including header and mixed code/data/names.',
                                    '1': '12-byte relocation records.', '2': '12-byte symbol records.',
                                    '3': 'Trailing bytes after the symbol table; format unknown.'}}


def export(destination, append=False):
    definitions = {name: (RAC / name).read_bytes() for name in
                   ('rac-defs.json', 'rac-defs-sm.json', 'rac-defs-sm-metadata.json')}
    defs = json.loads(definitions['rac-defs-sm.json'])
    metadata = json.loads(definitions['rac-defs-sm-metadata.json'])
    if destination.exists() and not append:
        raise FileExistsError('Existing destination requires --append; differing binaries are never overwritten')
    destination.mkdir(parents=True, exist_ok=True)
    manifests = {}
    for region in REGIONS:
        if region not in defs['rac']['5']['boot']['region']:
            continue
        manifests[region] = regional_export(destination, defs, metadata, region)
    files = [f for m in manifests.values() for f in m['files']]
    assert len({f['file'] for f in files}) == len(files)
    for row in files:
        data = (destination / row['file']).read_bytes()
        assert len(data) == row['size'] and sha(data) == row['sha256']
    for region, manifest in manifests.items():
        save_json(destination / f'manifest.{region}.json', manifest)
    save_json(destination / 'manifest.json', {'game': 'Ratchet & Clank: Size Matters',
              'abbreviation': 'rac5', 'regions': {r: {'manifest': f'manifest.{r}.json',
              'serial': m['serial'], 'version': m['version'], 'entryPoint': m['entryPoint'],
              'binaryFiles': len(m['files'])} for r, m in manifests.items()}, 'files': files})
    (destination / 'eemem').mkdir(exist_ok=True)
    (destination / 'README.md').write_text(README, encoding='utf-8')
    for name, original in definitions.items():
        assert (RAC / name).read_bytes() == original
    print(f'Verified {len(files)} binaries and {sum(len(m["modules"]) for m in manifests.values())} exact REL reconstructions across {len(manifests)} regions.')


README = """# Size Matters (RAC5) binary exports

NTSC-U (SCUS-97615), PAL (SCES-55019), and NTSC-J (SCPS-15120), retail v1.00.
Files share the existing directory layout and use `.ntscu.`, `.pal.`, or `.ntscj.`
in their names. For example: `code0/rac5.level20.pal.v100.retail.code.0000.bin`.

- `boot/elf`: unchanged original regional boot ELFs.
- `boot/core0` through `boot/core5`: .text, .data, .sndata, .rodata,
  .gcc_except_table, and synthesized zero-filled .bss, matching rac-defs-sm.json.
- `modules`: unchanged RELs for 20 numbered levels plus frontend (level-1).
- `code0`: REL prefix before relocations (header, mixed code/data and names).
- `code1`: relocation records; `code2`: symbol records; `code3`: remaining tail.
- `eemem`: reserved for actual captures; no memory dumps are synthesized.

Concatenating code0 + code1 + code2 + code3 reproduces each original REL exactly.
These are container boundaries, not recovered .text/.data sections. Co-op 16-19
share their parent REL but have distinct WAD/BWD sources. A .bss file describes
initial zero storage, not captured memory.

`manifest.json` indexes all regions and all binary hashes. `manifest.ntscu.json`,
`manifest.pal.json`, and `manifest.ntscj.json` contain boot addresses, REL offsets,
source assets, and 25 level/mode mappings each. Boot addresses are region-specific.
REL offsets are not absolute runtime addresses; level code dictionaries in the
main definitions remain empty and entrypoints null until loaded bases are verified.

Detailed regional ELF/REL metadata is in ../rac-defs-sm-metadata.json. The legacy
top-level metadata fields refer to NTSC-U; additional regions live under regions.

Repeat with `python test/sm/tools/export_rac5.py --output NEW_DIRECTORY` from
Metroynome. To add/update verified regional exports in an existing directory,
pass --append; differing existing binaries are rejected, and manifests refreshed.
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=RAC / 'rac5')
    ap.add_argument('--append', action='store_true')
    args = ap.parse_args()
    export(args.output.resolve(), args.append)


if __name__ == '__main__':
    main()
