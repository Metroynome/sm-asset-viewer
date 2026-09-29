import argparse
import hashlib
import json
import mmap
import re
import struct
import zlib
from pathlib import Path

from paths import ROOT, RAC
OUT = ROOT / "symbols/full_audit"
MAGIC = re.compile(rb"SNR[12]|\x7fELF")
NAMES = re.compile(rb"[A-Za-z_][A-Za-z0-9_:$./() \\-]{4,}")
FOCUS = re.compile(r"hero|player|terrain|shrub|spawn", re.I)


def string(data, pos):
    if not 0 <= pos < len(data): raise ValueError("string address")
    end = data.find(b"\0",pos,min(pos+4096,len(data)))
    if end < 0: raise ValueError("unterminated string")
    return data[pos:end].decode("ascii")


def sndll(data, off, address_base=0):
    table, count, source = struct.unpack_from("<III",data,off+12)
    if not count or count > 65536 or off+table-address_base+count*12>len(data): raise ValueError("symbol bounds")
    rows = []
    for i in range(count):
        np, value, a,b,kind,done = struct.unpack_from("<IIBBBB",data,off+table-address_base+i*12)
        if not np: continue
        name=string(data,off+np-address_base)
        if not name and kind==0: continue
        if kind not in (1,2,3,4): raise ValueError("symbol linkage")
        if not name or any(ord(c)<32 or ord(c)>126 for c in name): raise ValueError("symbol name")
        rows.append(dict(name=name,value=value,linkage=kind,index=i))
    if not rows: raise ValueError("empty table")
    return dict(format="SNDLL",offset=off,source=string(data,off+source-address_base) if source else None,record_count=count,symbols=rows)


def elf(data, off):
    if data[off+4:off+6] != b"\x01\x01":raise ValueError("ELF class")
    sh=struct.unpack_from("<I",data,off+32)[0]
    sz,n,ns=struct.unpack_from("<HHH",data,off+46)
    if sz<40 or n>4096 or ns>=n or off+sh+n*sz>len(data):raise ValueError("ELF sections")
    sections=[struct.unpack_from("<10I",data,off+sh+i*sz) for i in range(n)]
    strings=sections[ns];names=data[off+strings[4]:off+strings[4]+strings[5]]
    result=dict(format="ELF",offset=off,machine=struct.unpack_from("<H",data,off+18)[0],sections=[],symbols=[])
    for s in sections:
        name=string(names,s[0]);result['sections'].append(dict(name=name,type=s[1],address=s[3],size=s[5]))
        if name == '.sndata':
            table=sndll(data[off+s[4]:off+s[4]+s[5]],0,s[3])
            result['sndll']=table
            result['symbols'].extend(table['symbols'])
        if s[1] in (2,11):
            st=sections[s[6]];text=data[off+st[4]:off+st[4]+st[5]]
            if s[9]<16:raise ValueError("ELF symbols")
            for pos in range(off+s[4],off+s[4]+s[5],s[9]):
                np,value,size,info,other,index=struct.unpack_from("<IIIBBH",data,pos)
                if np:result['symbols'].append(dict(name=string(text,np),value=value,size=size,info=info,section=index))
    return result


def scan(path, relative):
    result=dict(file=relative,size=path.stat().st_size,containers=[],rejected_magic=[],focus_names=[])
    if not result['size']:
        result['sha256']=hashlib.sha256(b'').hexdigest();return result
    with path.open('rb') as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
        result['sha256']=hashlib.sha256(data).hexdigest()
        for match in MAGIC.finditer(data):
            off=match.start()
            try:result['containers'].append(elf(data,off) if match.group()==b"\x7fELF" else sndll(data,off))
            except (ValueError,IndexError,struct.error,UnicodeDecodeError) as error:
                result['rejected_magic'].append(dict(offset=off,reason=str(error)))
        # Asset/type names are evidence, not automatically addressable code symbols.
        for m in NAMES.finditer(data):
            text=m.group().decode('ascii')
            if FOCUS.search(text):result['focus_names'].append(dict(offset=m.start(),name=text[:500]))
    return result


def main():
    ap = argparse.ArgumentParser(description='Audit every disc file and unpacked archive for ELF/SNR symbols.')
    ap.add_argument('--regions', nargs='+', choices=('ntscu','pal','ntscj'), default=['ntscu','pal','ntscj'])
    args = ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    for region in args.regions:
        root=ROOT / ('' if region=='ntscu' else region) / 'extracted'
        manifest=json.loads((root/'manifest.json').read_text())
        assert not manifest['errors']
        records=[]
        actual={p.relative_to(root/'disc').as_posix() for p in (root/'disc').rglob('*') if p.is_file()}
        assert actual=={r['path'] for r in manifest['files']}
        for row in manifest['files']:
            record=scan(root/'disc'/row['path'],'disc/'+row['path'])
            assert record['sha256']==row['sha256'] and record['size']==row['size'],row['path']
            records.append(record)
        for archive in manifest['archives']:
            folder=root/'unpacked'/archive['path']
            record=scan(folder/'payload.bin','unpacked/'+archive['path']+'/payload.bin')
            assert record['sha256']==archive['payload_sha256']
            payload=(folder/'payload.bin').read_bytes()
            assert f"{zlib.crc32(payload,0xffffffff)&0xffffffff:08x}"==archive['crc32']
            full=(folder/'header.bin').read_bytes()+payload
            for section in archive['sections']:
                assert (folder/section['file']).read_bytes()==full[section['offset']:section['offset']+section['size']]
            record['verified_sections']=len(archive['sections'])
            records.append(record)
        report=dict(region=region,disc_files=len(manifest['files']),archives=len(manifest['archives']),files=records)
        (OUT/(region+'_inventory.json')).write_text(json.dumps(report,indent=2))
        containers=[dict(file=r['file'],**c) for r in records for c in r['containers']]
        print(region, 'files',len(records),'containers',[(c['file'],c['format'],len(c['symbols'])) for c in containers],flush=True)


if __name__=='__main__':main()
