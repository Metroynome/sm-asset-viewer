"""Keep rac-defs-sm schema-compatible; store raw ELF/REL layout in a companion."""
import copy,hashlib,json,struct
from pathlib import Path
from paths import ROOT, RAC
DISC=ROOT/'extracted/disc'
def hx(n):return f'0x{n:08x}'
def u32(b,o):return struct.unpack_from('<I',b,o)[0]

def elf_layout(path):
 b=path.read_bytes();assert b[:6]==b'\x7fELF\x01\x01'
 et,machine,version,entry,phoff,shoff,flags,ehsize,phsize,phnum,shsize,shnum,shstr=struct.unpack_from('<HHIIIIIHHHHHH',b,16)
 assert phoff+phsize*phnum<=len(b) and shoff+shsize*shnum<=len(b)
 sections_raw=[struct.unpack_from('<10I',b,shoff+i*shsize) for i in range(shnum)]
 strings=b[sections_raw[shstr][4]:sections_raw[shstr][4]+sections_raw[shstr][5]]
 segments=[]
 for i in range(phnum):
  typ,off,va,pa,fs,ms,fl,align=struct.unpack_from('<8I',b,phoff+i*phsize)
  assert off+fs<=len(b) and fs<=ms
  segments.append({'index':i,'type':'PT_LOAD' if typ==1 else hx(typ),'fileOffset':hx(off),'virtualAddress':hx(va),'physicalAddress':hx(pa),'fileSize':fs,'memorySize':ms,'zeroFillSize':ms-fs,'virtualEndExclusive':hx(va+ms),'flags':hx(fl),'readable':bool(fl&4),'writable':bool(fl&2),'executable':bool(fl&1),'alignment':align})
 types={0:'SHT_NULL',1:'SHT_PROGBITS',2:'SHT_SYMTAB',3:'SHT_STRTAB',8:'SHT_NOBITS',9:'SHT_REL'}
 sections=[]
 core={}
 for i,s in enumerate(sections_raw):
  nm,typ,fl,addr,off,sz,link,info,align,entsize=s
  name=strings[nm:strings.index(b'\0',nm)].decode('ascii')
  if typ!=8:assert off+sz<=len(b)
  record={'index':i,'name':name,'type':types.get(typ,hx(typ)),'typeValue':hx(typ),'flags':hx(fl),'allocated':bool(fl&2),'writable':bool(fl&1),'executable':bool(fl&4),'virtualAddress':hx(addr),'fileOffset':None if typ==8 else hx(off),'headerFileOffset':hx(off),'size':sz,'alignment':align,'entrySize':entsize,'link':link,'info':info,'zeroInitialized':typ==8}
  sections.append(record)
  if fl&2 and sz and addr:
   core[str(len(core))]={'name':name,'offset':hx(addr),'size':sz}
   assert any(int(p['virtualAddress'],16)<=addr and addr+sz<=int(p['virtualEndExclusive'],16) for p in segments if p['type']=='PT_LOAD')
 entryfile=next(int(s['fileOffset'],16)+entry-int(s['virtualAddress'],16) for s in segments if s['type']=='PT_LOAD' and int(s['virtualAddress'],16)<=entry<int(s['virtualAddress'],16)+s['fileSize'])
 return {'file':path.name,'size':len(b),'sha256':hashlib.sha256(b).hexdigest(),'format':'ELF32 little-endian','machine':machine,'elfType':et,'elfVersion':version,'entryPoint':hx(entry),'entryPointFileOffset':hx(entryfile),'flags':hx(flags),'headerSize':ehsize,'programHeaderTable':{'fileOffset':hx(phoff),'entrySize':phsize,'count':phnum},'sectionHeaderTable':{'fileOffset':hx(shoff),'entrySize':shsize,'count':shnum,'stringTableIndex':shstr},'segments':segments,'sections':sections},core

def rel_layout(path):
 b=path.read_bytes();assert b[:4]==b'SNR2'
 reloc,count,symbols,symcount,source,load,unload=struct.unpack_from('<7I',b,4)
 assert reloc+count*12<=len(b) and symbols+symcount*12<=len(b)
 assert u32(b,44)==len(b)
 for off in (source,load,unload):assert off<len(b)
 return {'format':'SNDLL/SNR2, not ELF','elfProgramHeaders':None,'elfSectionHeaders':None,'offsetBasis':'start of REL file / loaded module','fileSize':len(b),'loadCallbackOffset':hx(load),'unloadCallbackOffset':hx(unload),'relocations':{'fileOffset':hx(reloc),'count':count,'entrySize':12,'size':count*12},'symbols':{'fileOffset':hx(symbols),'count':symcount,'entrySize':12,'size':symcount*12},'sourceElfPathOffset':hx(source),'rawHeaderWords':{hx(i):hx(u32(b,i)) for i in range(0,0x3c,4)},'notes':'The header fields at 0x20, 0x24, 0x28, 0x30, 0x34, and 0x38 are retained raw; their section semantics have not been established. The original named source ELF is not present on the disc.'}

def normalize(inventory):
 old=copy.deepcopy(inventory);g=old['rac']['5'];layout,core=elf_layout(DISC/'SCUS_976.15')
 result={'games':old['games'],'gameMoodes':old['gameMoodes'],'rac':{'5':{'abbreviation':g['abbreviation'],'altAbbreviation':g['altAbbreviation'],'levels':[]}}}
 result['rac']['5']['boot']={'region':{'ntscu':{'defaultVersion':'1.00','version':{'1.00':{'buildType':'retail','entryPoint':layout['entryPoint'],'core':core}}}}}
 details={'schemaNote':'rac-defs-sm.json uses exactly the existing rac-defs.json key shapes. All extra extraction/layout fields are kept here.','region':'ntscu','buildType':'retail','serial':'SCUS-97615','version':'1.00','versionSource':'SYSTEM.CNF VER = 1.00','addressConventions':{'mainFileOffsets':'Virtual EE addresses, matching rac-defs.json; never raw file offsets.','elfSegments':'Program headers, separate from named ELF sections used by boot.core.','relOffsets':'Module-relative; add a verified load address for that particular memory image.','levelEntryPoints':'Null until a stable/appropriate runtime mapping is verified. libMainOffset identifies an exported function, not an original ELF e_entry.'},'bootElf':layout,'modules':{},'inventory':old}
 for row in g['levels']:
  clean={k:row[k] for k in ('level','gameMode','shortName','longName')}
  clean['region']={'ntscu':{'defaultVersion':'1.00','version':{'1.00':{'buildType':'retail','entryPoint':None,'code':{}}}}}
  result['rac']['5']['levels'].append(clean)
  module=row['region']['ntscu']['version']['1.00']['module'];filename=module['file']
  if filename not in details['modules']:
   details['modules'][filename]={**module,'layout':rel_layout(DISC/filename)}
 return result,details

def validate(main,reference):
 assert set(main)==set(reference)=={'games','gameMoodes','rac'}
 g=main['rac']['5'];example=reference['rac']['4']
 assert set(g)==set(example)
 assert len(g['levels'])==25
 for r in g['levels']:
  assert set(r)==set(example['levels'][0])
  assert set(r['region'])=={'ntscu'}
  p=r['region']['ntscu']['version']['1.00'];assert set(p)=={'buildType','entryPoint','code'} and p['buildType']=='retail'
 p=g['boot']['region']['ntscu']['version']['1.00'];assert set(p)=={'buildType','entryPoint','core'}
 assert p['entryPoint']=='0x01e62508'
 for row in p['core'].values():assert set(row)=={'name','offset','size'}
 assert any(r['name']=='.text' and r['offset']=='0x01e62500' for r in p['core'].values())

def main():
 target=RAC/'rac-defs-sm.json';reference=target.with_name('rac-defs.json')
 untouched=reference.read_bytes();previous=target.read_bytes();inventory=json.loads(previous)
 if 'rac' in inventory and set(inventory['rac']['5']['boot']['region']) != {'ntscu'}:raise RuntimeError('Multi-region definitions detected; use update_rac5_regions.py to preserve all regions')
 if '_metadata' not in inventory:inventory=json.loads(target.with_name('rac-defs-sm-metadata.json').read_text())['inventory']
 result,details=normalize(inventory);validate(result,json.loads(untouched))
 if (ROOT/'rac-defs-sm.json').read_bytes()!=previous:raise RuntimeError('The two existing copies differ; reconcile before updating')
 docs={ 'rac-defs-sm.json':result,'rac-defs-sm-metadata.json':details }
 for folder in (target.parent,ROOT):
  for name,data in docs.items():
   dest=folder/name;temp=dest.with_suffix('.json.tmp');temp.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');temp.replace(dest)
 assert reference.read_bytes()==untouched
 assert target.read_bytes()==(ROOT/target.name).read_bytes()
 print('Updated',target)
 print('Verified original schema shapes: 25 level records; 6 boot core sections; entrypoint 0x01e62508.')
 print('Companion metadata:',len(details['bootElf']['segments']),'ELF segment,',len(details['bootElf']['sections']),'ELF sections,',len(details['modules']),'REL module headers.')
 print('Original rac-defs.json unchanged:',hashlib.sha256(untouched).hexdigest())

if __name__=='__main__':main()
