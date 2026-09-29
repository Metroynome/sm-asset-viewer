"""Extract typed symbol records from an ELF32 .sndata section; no code guessing.
SNDLL record layout checked against chaoticgd/ccc src/ccc/sndll.cpp.
"""
import argparse, collections, hashlib, json, struct, subprocess
from pathlib import Path

def extract(path):
 b=path.read_bytes()
 if b[:6]!=b'\x7fELF\x01\x01': raise ValueError('Expected little-endian ELF32')
 off=struct.unpack_from('<I',b,32)[0]; size,count,strings=struct.unpack_from('<HHH',b,46)
 sections=[struct.unpack_from('<10I',b,off+i*size) for i in range(count)]
 names=b[sections[strings][4]:sections[strings][4]+sections[strings][5]]
 secnames=[names[r[0]:].split(b'\0')[0].decode('ascii') for r in sections]
 r=sections[secnames.index('.sndata')]; base=r[3]; data=b[r[4]:r[4]+r[5]]
 if data[:4] not in (b'SNR1',b'SNR2'): raise ValueError('Unknown SNDLL version')
 table,n=struct.unpack_from('<II',data,12); start=table-base
 if start<0 or start+n*12>len(data): raise ValueError('Symbol table out of bounds')
 result=[]
 for i in range(n):
  ptr,addr,a,c,kind,processed=struct.unpack_from('<IIBBBB',data,start+i*12)
  if not ptr or not addr: continue
  p=ptr-base
  if not 0<=p<len(data): raise ValueError('Name pointer out of bounds')
  end=data.find(b'\0',p)
  if end<0: raise ValueError('Unterminated name')
  name=data[p:end].decode('ascii')
  if not name: continue
  hits=[(sn,s) for sn,s in zip(secnames,sections) if s[2]&2 and s[3]<=addr<s[3]+s[5]]
  # Only .text is EE code: .data has executable flags too on this ELF.
  sec=next((sn for sn,s in hits if sn=='.text'),hits[0][0] if hits else None)
  result.append(dict(index=i,address=addr,address_hex=f'{addr:08x}',name=name,sndll_type=kind,section=sec,kind='function' if sec=='.text' else 'data' if sec else 'unmapped'))
 return dict(elf=str(path.resolve()),sha256=hashlib.sha256(b).hexdigest(),record_count=n,symbols=result)

def main():
 ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('elf',type=Path);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--demangler',type=Path,help='Optional GNU v2-compatible c++filt');args=ap.parse_args()
 report=extract(args.elf); rows=report['symbols']
 demangled=[r['name'] for r in rows]
 if args.demangler:
  proc=subprocess.run([str(args.demangler),'-s','gnu'],input='\n'.join(r['name'] for r in rows)+'\n',text=True,capture_output=True,check=True)
  demangled=proc.stdout.splitlines()
  if len(demangled)!=len(rows): raise ValueError('Demangler output count mismatch')
 for row,dem in zip(rows,demangled): row['demangled']=dem
 args.output.mkdir(parents=True,exist_ok=True)
 (args.output/'symbols.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 (args.output/'symbols.tsv').write_text('address\tkind\tsection\tname\tdemangled\n'+''.join(f"{r['address_hex']}\t{r['kind']}\t{r['section']}\t{r['name']}\t{r['demangled']}\n" for r in rows),encoding='utf-8')
 print('records',report['record_count'],'named',len(rows),'kinds',dict(collections.Counter(r['kind'] for r in rows)))
 print('demangled',sum(r['name']!=r['demangled'] for r in rows))
 print('memset',[r for r in rows if r['name']=='memset'])

if __name__=='__main__': main()
