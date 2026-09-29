"""One entry point for the Size Matters extraction and export tools."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

TOOLS = {
    'extract-regions': ('extract_regions.py', 'Extract and index NTSC-U, PAL, and NTSC-J ISOs'),
    'extract': ('extract_sm.py', 'ISO / HIG WAD extraction'),
    'audio-index': ('index_assets.py', 'VAGS.WAD extraction and embedded asset paths'),
    'browse': ('browse.py', 'Categorized browser, PNG and WAV previews'),
    'symbols': ('extract_symbols.py', 'Boot ELF symbols to JSON / TSV'),
    'audit-symbols': ('audit_all_symbols.py', 'Scan all disc files and unpacked WADs for symbols'),
    'types': ('export_smtypes.py', 'NTSC-U dump partial type / symbol reference'),
    'level-defs': ('build_level_defs.py', 'Create NTSC-U definitions using an existing rac-defs.json schema'),
    'add-regions': ('update_rac5_regions.py', 'Add PAL / NTSC-J definitions and export split binaries'),
    'split-binaries': ('export_rac5.py', 'Export all regional boot sections and REL blocks'),
}

def main():
    ap = argparse.ArgumentParser(description=__doc__, epilog='\n'.join(f'{k:16} {v[1]}' for k,v in TOOLS.items()), formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--workspace', type=Path, help='Extraction data folder (default: tools/data)')
    ap.add_argument('--rac-levels', type=Path, help='Definitions and split export folder (default: workspace/rac-levels)')
    ap.add_argument('command', choices=TOOLS)
    ap.add_argument('arguments', nargs=argparse.REMAINDER)
    args = ap.parse_args()
    env = os.environ.copy()
    if args.workspace: env['SM_WORKSPACE'] = str(args.workspace.resolve())
    if args.rac_levels: env['SM_RAC_LEVELS'] = str(args.rac_levels.resolve())
    command = [sys.executable, str(Path(__file__).parent / TOOLS[args.command][0]), *args.arguments]
    return subprocess.call(command, env=env)

if __name__ == '__main__':
    sys.exit(main())
