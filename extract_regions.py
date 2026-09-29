"""Extract and index one or more regional Size Matters ISOs into separate folders."""
import argparse
from pathlib import Path
import subprocess
import sys
from extract_sm import iso_files
from regions import detect_region


def identify(iso):
    with iso.open('rb') as f:
        entries=iso_files(f,iso.stat().st_size)
        config=next((r for r in entries if r[0].as_posix().upper()=='SYSTEM.CNF'),None)
        if not config:raise ValueError('Missing SYSTEM.CNF')
        f.seek(config[1]);return detect_region(f.read(config[2]).decode('ascii'))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('ntscu','pal','ntscj'):ap.add_argument('--'+key,type=Path,help=key.upper()+' ISO')
    ap.add_argument('--output',type=Path,default=Path(__file__).parent/'data')
    ap.add_argument('--resume',action='store_true')
    args=ap.parse_args();selected=[(k,getattr(args,k)) for k in ('ntscu','pal','ntscj') if getattr(args,k)]
    if not selected:ap.error('Provide at least one of --ntscu, --pal, --ntscj')
    for key,iso in selected:
        actual=identify(iso)
        if actual['id']!=key:ap.error(f"{iso}: expected {key}, found {actual['label']} ({actual['serial']})")
    here=Path(__file__).parent
    for key,iso in selected:
        output=args.output/('extracted' if key=='ntscu' else key+'/extracted')
        subprocess.run([sys.executable,str(here/'extract_sm.py'),str(iso),'--output',str(output)]+(['--resume'] if args.resume else []),check=True)
        subprocess.run([sys.executable,str(here/'index_assets.py'),str(output)],check=True)
        print(f'{key}: ready to browse at {output}',flush=True)

if __name__=='__main__':main()
