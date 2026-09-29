"""Add verified PAL/NTSC-J profiles without changing NTSC-U or rac-defs.json."""
from pathlib import Path
import copy
import hashlib
import json
from build_level_defs import module_info
from sm_layout import elf_layout, rel_layout
from export_rac5 import ROOT, RAC, save_json, export


def main():
    original = (RAC / 'rac-defs.json').read_bytes()
    for name in ('rac-defs-sm.json', 'rac-defs-sm-metadata.json'):
        if (ROOT / name).read_bytes() != (RAC / name).read_bytes():
            raise ValueError(f'Workspace and RAC Levels copies differ: {name}')
    defs = json.loads((RAC / 'rac-defs-sm.json').read_text())
    meta = json.loads((RAC / 'rac-defs-sm-metadata.json').read_text())
    before = copy.deepcopy(defs)
    game = defs['rac']['5']
    reference_levels = meta['inventory']['rac']['5']['levels']
    for region, serial in (('pal', 'SCES_550.19'), ('ntscj', 'SCPS_151.20')):
        disc = ROOT / region / 'extracted/disc'
        config = (disc / 'SYSTEM.CNF').read_text()
        assert serial in config and 'VER = 1.00' in config
        elf, core = elf_layout(disc / serial)
        game['boot']['region'][region] = {'defaultVersion': '1.00', 'version': {'1.00': {
            'buildType': 'retail', 'entryPoint': elf['entryPoint'], 'core': core}}}
        modules = {}
        for path in sorted((disc / 'LVL').glob('*.REL')):
            filename = path.relative_to(disc).as_posix()
            modules[filename] = {**module_info(filename, disc), 'layout': rel_layout(path)}
            assert modules[filename]['sourceElf'] == meta['modules'][filename]['sourceElf']
        assert set(modules) == set(meta['modules']) and len(modules) == 21
        rows = []
        for row, ref in zip(game['levels'], reference_levels):
            assert (row['level'], row['gameMode']) == (ref['level'], ref['gameMode'])
            ref_profile = ref['region']['ntscu']['version']['1.00']
            filename = ref_profile['module']['file']
            profile = {'buildType': 'retail', 'entryPoint': None, 'code': {}}
            row['region'][region] = {'defaultVersion': '1.00', 'version': {'1.00': profile}}
            inventory_row = {k: row[k] for k in ('level', 'gameMode', 'shortName', 'longName')}
            inventory_row['module'] = modules[filename]
            if 'assets' in ref_profile:
                assets = copy.deepcopy(ref_profile['assets'])
                for key in ('wad', 'soundBank'):
                    assert (disc / assets[key]).is_file()
                archive = ROOT / region / 'extracted/unpacked' / assets['wad'] / 'manifest.json'
                assets['sourceConfig'] = json.loads(archive.read_text())['source_name']
                # Display names inherited from the existing mapping; matching source
                # REL and WAD config prove the same level, not localization text.
                assert assets['sourceConfig'].casefold() == ref_profile['assets']['sourceConfig'].casefold()
                inventory_row['assets'] = assets
            rows.append(inventory_row)
        meta.setdefault('regions', {})[region] = {
            'region': region, 'serial': serial.replace('_', '-').replace('.', ''),
            'buildType': 'retail', 'version': '1.00', 'versionSource': 'SYSTEM.CNF',
            'bootElf': elf, 'modules': modules, 'levels': rows,
            'mappingEvidence': 'Level REL source ELF names and WAD config paths match NTSC-U; display names reuse the existing English mapping.',
            'addressConventions': copy.deepcopy(meta['addressConventions'])}
    # Preserve schema shape and every pre-existing NTSC-U profile.
    assert set(defs) == set(before)
    assert set(game) == set(before['rac']['5'])
    assert game['boot']['region']['ntscu'] == before['rac']['5']['boot']['region']['ntscu']
    assert len(game['levels']) == len(before['rac']['5']['levels']) == 25
    for row, old in zip(game['levels'], before['rac']['5']['levels']):
        assert set(row) == set(old)
        assert row['region']['ntscu'] == old['region']['ntscu']
        assert set(row['region']) == {'ntscu', 'pal', 'ntscj'}
        for region in row['region'].values():
            assert set(region['version']['1.00']) == {'buildType', 'entryPoint', 'code'}
    for folder in (ROOT, RAC):
        save_json(folder / 'rac-defs-sm.json', defs)
        save_json(folder / 'rac-defs-sm-metadata.json', meta)
    export(RAC / 'rac5', append=True)
    assert (RAC / 'rac-defs.json').read_bytes() == original
    for name in ('rac-defs-sm.json', 'rac-defs-sm-metadata.json'):
        assert (ROOT / name).read_bytes() == (RAC / name).read_bytes()
    print('Updated both copies: 25 level/mode records and boot profiles for all three regions.')
    print('Original rac-defs.json unchanged: ' + hashlib.sha256(original).hexdigest())


if __name__ == '__main__':
    main()
