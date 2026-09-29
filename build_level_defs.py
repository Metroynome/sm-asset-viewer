"""Build standalone Size Matters definitions from the extracted SCUS_976.15 disc.
The existing RAC definitions are read for conventions only and never rewritten.
"""
from pathlib import Path
import hashlib,json,struct
from paths import ROOT, RAC
DISC=ROOT/'extracted/disc'
REFERENCE=RAC/'rac-defs.json'
TARGET=REFERENCE.with_name('rac-defs-sm.json')

def u32(b,o):return struct.unpack_from('<I',b,o)[0]
def cstr(b,o):return b[o:b.index(b'\0',o)].decode('ascii') if o else None

def module_info(filename, disc=DISC):
 b=(disc/filename).read_bytes();assert b[:4]==b'SNR2'
 tab,n=struct.unpack_from('<II',b,12);exports=[];imports=[]
 for i in range(n):
  p,v,_,_,t,_=struct.unpack_from('<IIBBBB',b,tab+12*i)
  if not p:continue
  name=cstr(b,p)
  if not name:continue
  item={'name':name,'linkageType':t}
  if v:
   item['offset' if t!=4 else 'absoluteAddress']=f'0x{v:08x}';exports.append(item)
  else:imports.append(name)
 return {'file':filename,'format':'SNDLL/SNR2','size':len(b),'sha256':hashlib.sha256(b).hexdigest(),'sourceElf':cstr(b,u32(b,20)),'loadAddress':None,'libMainOffset':next((e.get('offset') for e in exports if e['name']=='lib_main__FiPPc'),None),'symbolCount':n,'importCount':len(imports),'exports':exports}

NAMES=[
 (1,'Pokitaru','Pokitaru - Jowai Resort','campaign'),
 (2,'Ryllus','Ryllus - Vetega Jungle','campaign'),
 (3,'Kalidon','Kalidon - Mechanoid Factory','campaign'),
 (4,'Metalis','Metalis - Junkyard LXIV','campaign'),
 (5,'Dreamtime','Dreamtime','campaign'),
 (6,'MedicalOutpostOmega','Medical Outpost Omega - Surgical Facility','campaign'),
 (7,'Challax','Challax - Technomite City','campaign'),
 (8,'DayniMoon','Dayni Moon - Farming Cooperative','campaign'),
 (9,'InsideClank','Inside Clank','campaign'),
 (10,'Quodrona','Quodrona - Clone Factory','campaign'),
 (15,'MetalisGiantClank','Metalis - Giant Clank','giantClank'),
 (16,'IslandEscape','Island Escape','multiplayer'),
 (17,'DangerValley','Danger Valley','multiplayer'),
 (18,'MegaCannons','Mega Cannons','multiplayer'),
 (19,'MoonCowDisease','Moon Cow Disease','multiplayer'),
 (20,'MPLobby','Multiplayer Lobby','lobby'),
 (21,'ChallaxGiantClank','Challax - Giant Clank','giantClank'),
 (22,'KalidonSkyboard','Kalidon - Skyboard Race','skyboard'),
 (23,'MedicalOutpostSkyboard','Medical Outpost Omega - Skyboard Race','skyboard'),
 (24,'HIGTreehouse','HIG Treehouse - California','bonus'),
]
PARENTS={15:4,21:7,22:3,23:6}

def region(profile):return {'ntscu':{'defaultVersion':'1.00','version':{'1.00':profile}}}

def main():
 original=REFERENCE.read_bytes();schema=json.loads(original)
 rows=[]
 frontend={'level':-1,'gameMode':0,'shortName':'MainMenu','longName':'Main Menu / Frontend','category':'frontend','levelIdStatus':'Convention: -1 matches rac-defs.json menu entries; not verified as the game runtime ID.','region':region({'buildType':'retail','entryPoint':None,'code':{},'module':module_info('LVL/FRONTEND.REL')})}
 rows.append(frontend)
 for n,short,long,category in NAMES:
  variants=[False,True] if 16<=n<=19 else [False]
  for coop in variants:
   stem=f'{n:02}'+('C' if coop else '')
   m=json.loads((ROOT/f'extracted/unpacked/WAD/{stem}.WAD/manifest.json').read_text())
   profile={'buildType':'retail','entryPoint':None,'code':{},'module':module_info(f'LVL/LEVEL_{n:02}.REL'),'assets':{'wad':f'WAD/{stem}.WAD','soundBank':f'SND/{stem}.BWD','sourceConfig':m['source_name']}}
   row={'level':n,'gameMode':1 if coop else 3 if category in ('multiplayer','lobby') else 0,'shortName':short+('Coop' if coop else ''),'longName':long+(' (Co-op)' if coop else ''),'category':category,'region':region(profile)}
   if n in PARENTS:row['parentLevel']=PARENTS[n]
   if n==23:row['notes']='The skyboard race takes place around the destroyed outpost.'
   if 16<=n<=19:
    row['internalName']=f'levelMP{n-15:02}'+('_Coop' if coop else '')
    row['mappingEvidence']='REL internal name + distinctive WAD assets (rocket, homing beacon, mega cannon, cow crate) + English localized map names and developer description.'
   elif 1<=n<=10:row['mappingEvidence']='Numbered REL/WAD internal paths corroborated by the ordered English campaign destination list in HUD/LOCALDAT.BIN at 0x1e4fc.'
   else:row['mappingEvidence']='Explicit internal REL and WAD source paths; lobby also verified against the PCSX2 memory dump.' if n==20 else 'Explicit internal REL and WAD source paths.'
   rows.append(row)
 b=(DISC/'SCUS_976.15').read_bytes();off=u32(b,32);size,count,si=struct.unpack_from('<HHH',b,46);sections=[struct.unpack_from('<10I',b,off+i*size) for i in range(count)];strings=b[sections[si][4]:sections[si][4]+sections[si][5]]
 core={}
 for s in sections:
  if s[2]&2 and s[5] and s[3]:
   name=cstr(strings,s[0]);core[str(len(core))]={'name':name,'offset':f'0x{s[3]:08x}','size':s[5],'fileOffset':None if s[1]==8 else f'0x{s[4]:08x}','zeroInitialized':s[1]==8}
 data={'games':{'Ratchet and Clank: Size Matters':5},'gameMoodes':schema['gameMoodes'],'rac':{'5':{'abbreviation':'RAC5','altAbbreviation':'SM','platform':'PS2','serial':'SCUS-97615','levels':rows,'boot':{'region':region({'buildType':'retail','file':'SCUS_976.15','entryPoint':f'0x{u32(b,24):08x}','core':core,'sha256':hashlib.sha256(b).hexdigest()})}}},'_metadata':{'status':'Standalone naming and file inventory; not a complete relocation-aware loader definition.','gameIdNote':'5 is a local standalone configuration key, not a verified runtime game identifier.','schemaNote':'Preserves existing games/gameMoodes/rac/levels/region conventions, including the existing gameMoodes spelling. module/assets/category fields extend that schema.','levelNumberBase':10,'versionSource':'SYSTEM.CNF declares VER = 1.00; no other disc revisions or regions were inspected.','absentNumberedLevelFiles':[0,11,12,13,14],'absentFilesNote':'No matching numbered REL/WAD files on this disc; this does not establish that those runtime IDs are unused. FRONTEND.REL is listed separately with conventional level -1.','addressNote':'boot.core.offset values are ELF virtual addresses. REL export offsets/libMainOffset are file/module-relative, not absolute EE addresses. All static REL entryPoint fields remain null and code maps empty until relocation-aware mapping is established. lib_main is not the SNR2 header load callback.','multiplayerModeNote':'PS2 multiplayer is local split screen: base maps use gameMode 3. Explicit _Coop assets use gameMode 1 and share their parent level ID/REL.','originalDefinitionsSha256':hashlib.sha256(original).hexdigest(),'sources':['SCUS_976.15 and SYSTEM.CNF from the user ISO','LVL/*.REL SNR2 source paths and symbol tables','WAD/*.WAD HIG source configuration paths','HUD/LOCALDAT.BIN English display names','https://blog.playstation.com/2008/03/07/ratchet-and-clank-size-matters-ps2-multiplayer-details/']}}
 from sm_layout import normalize,validate
 data,details=normalize(data)
 validate(data,schema)
 encoded=json.dumps(data,indent=2,ensure_ascii=False)+'\n'
 metadata_encoded=json.dumps(details,indent=2,ensure_ascii=False)+'\n'
 # Validate identity pairs and all listed assets against the extracted disc.
 assert len(rows)==25
 assert len({(r['level'],r['gameMode']) for r in rows})==len(rows)
 for row in rows:
  p=row['region']['ntscu']['version']['1.00'];assert (DISC/p['module']['file']).is_file()
  for key in ('wad','soundBank'):
   if 'assets' in p:assert (DISC/p['assets'][key]).is_file()
 assert REFERENCE.read_bytes()==original
 for dest in (ROOT/'rac-defs-sm.json',TARGET,ROOT/'rac-defs-sm-metadata.json',TARGET.with_name('rac-defs-sm-metadata.json')):
  if dest.exists():raise FileExistsError(dest)
 # Write new files only; never open the original for writing.
 for dest in (ROOT/'rac-defs-sm.json',TARGET):
  with dest.open('x',encoding='utf-8',newline='\n') as f:f.write(encoded)
 for dest in (ROOT/'rac-defs-sm-metadata.json',TARGET.with_name('rac-defs-sm-metadata.json')):
  with dest.open('x',encoding='utf-8',newline='\n') as f:f.write(metadata_encoded)
 assert REFERENCE.read_bytes()==original
 assert json.loads(TARGET.read_text())==data
 print('Created',TARGET,'and',ROOT/'rac-defs-sm.json')
 print('Validated',len(rows),'records: 20 numbered levels, 4 additional co-op variants, 1 frontend.')
 print('Original rac-defs.json unchanged; SHA256',hashlib.sha256(original).hexdigest())

if __name__=='__main__':main()
