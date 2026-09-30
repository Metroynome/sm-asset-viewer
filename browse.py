"""Size Matters asset indexer and local, read-only browser."""
import argparse
import collections
import hashlib
import http.server
import json
import mimetypes
import re
import struct
import threading
import functools
import models
import animations
import levels
from regions import detect_region
import urllib.parse
from pathlib import Path
from formats import gim, png, vag_info, vag_wav, u32

HERE=Path(__file__).resolve().parent
NAMES={'12':'Template','01':'Pokitaru','02':'Ryllus','03':'Kalidon','04':'Metalis','05':'Dreamtime','06':'Medical Outpost Omega','07':'Challax','08':'Dayni Moon','09':'Inside Clank','10':'Quodrona','15':'Metalis — Giant Clank','16':'Island Escape','17':'Danger Valley','18':'Mega Cannons','19':'Moon Cow Disease','20':'Multiplayer Lobby','21':'Challax — Giant Clank','22':'Kalidon — Skyboard','23':'Medical Outpost — Skyboard','24':'HIG Treehouse'}


def group(archive):
    stem=Path(archive).stem.replace('LEVEL_','')
    key=stem.upper().removesuffix('C')
    if key in NAMES: return stem+' · '+NAMES[key]+(' (Co-op)' if stem.upper().endswith('C') else '')
    return {'GLOBAL':'Shared · Global','SP':'Shared · Single player','MP':'Shared · Multiplayer','TR':'Shared · Transitions','FRONTEND':'Main menu'}.get(stem,'Shared · '+stem)


def safe_name(value): return re.sub(r'[^A-Za-z0-9_.-]+','_',value)[:120] or 'asset'


def elf_info(data):
    if data[:6]!=b'\x7fELF\x01\x01': return {}
    entry,phoff,shoff=struct.unpack_from('<III',data,24)
    phsize,phnum,shsize,shnum,shstr=struct.unpack_from('<5H',data,42)
    result={'entryPoint':f'0x{entry:08x}','segments':[],'sections':[]}
    if phsize<32 or phoff+phsize*phnum>len(data) or shsize<40 or shoff+shsize*shnum>len(data):return result
    for i in range(phnum):
        typ,off,va,pa,fs,ms,flags,align=struct.unpack_from('<8I',data,phoff+i*phsize)
        result['segments'].append(dict(type=typ,address=f'0x{va:08x}',fileOffset=off,fileSize=fs,memorySize=ms))
    sections=[struct.unpack_from('<10I',data,shoff+i*shsize) for i in range(shnum)]
    if shstr>=shnum:return result
    st=sections[shstr];names=data[st[4]:st[4]+st[5]]
    for s in sections:
        name=names[s[0]:].split(b'\0',1)[0].decode('ascii','replace')
        result['sections'].append(dict(name=name,address=f'0x{s[3]:08x}',size=s[5],type=s[1]))
    return result


def build(root,out):
    assets=[];errors=[];counts=collections.Counter()
    def add(source,offset,size,name,category,archive,**extra):
        key=hashlib.sha256(f'{source}:{offset}:{size}'.encode()).hexdigest()[:20]
        row=dict(id=key,source=source,offset=offset,size=size,name=name,category=category,archive=archive,group=group(archive),status='Raw asset',**extra)
        assets.append(row);counts[category]+=1;return row
    manifest=json.loads((root/'manifest.json').read_text())
    for record in manifest['archives']:
        archive=record['path'];file=root/'unpacked'/archive/'payload.bin'
        if not file.exists():errors.append(dict(file=archive,error='Missing decompressed payload'));continue
        data=file.read_bytes();seen=set()
        for hit in re.finditer(rb'[A-Za-z]:\\',data):
            h=hit.start()-4
            if h<0 or h%16 or h+192>len(data) or h in seen:continue
            namebytes=data[h+4:h+100].split(b'\0',1)[0]
            if any(c<32 or c>126 for c in namebytes):continue
            typ,size=struct.unpack_from('<II',data,h+100)
            if not size or typ>100 or h+192+size>len(data):continue
            seen.add(h);source_name=namebytes.decode('ascii');name=source_name.rsplit('\\',1)[-1]
            ext=Path(name).suffix.lower();start=h+192;raw=data[start:start+size]
            category={'.gim':'Textures','.gde':'Geometry','.mgd':'Geometry','.col':'Collision','.pcol':'Collision','.anim':'Animation','.bog':'Gameplay','.sig':'Sound metadata','.bnk':'Sound banks'}.get(ext,'Other')
            if ext.startswith('.gdes'):category='Sound metadata'
            if raw[:12]==b'MIG.00.1PSP\0':category='Textures'
            row=add(file.relative_to(root).as_posix(),start,size,name,category,archive,sourceName=source_name,assetType=typ,signature=f'{u32(data,h):08x}',headerOffset=h,offsetBasis='Decompressed payload; add 0xc0 for reconstructed WAD offsets')
            if category=='Textures':
                try:
                    width,height,rgba=gim(raw)
                    relative=Path('textures')/safe_name(archive)/f'{row["id"]}_{safe_name(name)}.png'
                    dest=out/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(png(width,height,rgba))
                    row.update(width=width,height=height,preview=relative.as_posix(),status='PNG preview')
                except (ValueError,struct.error,IndexError) as exc:
                    row['status']='Preview unavailable';row['error']=str(exc);errors.append(dict(id=row['id'],file=archive,name=name,error=str(exc)))
        print(archive,len(seen),'asset records',flush=True)
    for record in json.loads((root/'audio/manifest.json').read_text()):
        file=root/'audio'/record['file']
        if not file.exists():continue
        row=add(file.relative_to(root).as_posix(),0,file.stat().st_size,record['file'],'Audio','VAGS.WAD',signature=record['id'])
        row['group']='Audio · Unassigned streams'
        try:
            data=file.read_bytes();size,rate=vag_info(data)
            row.update(sampleRate=rate,channels=1,estimatedDuration=(size//16*28)/rate,status='WAV preview')
        except ValueError as exc:row['error']=str(exc);row['status']='Preview unavailable'
    for file in sorted((root/'disc').rglob('*')):
        if not file.is_file():continue
        with file.open('rb') as f:magic=f.read(4)
        if magic not in (b'\x7fELF',b'SNR2') and file.suffix.upper() not in ('.BIK','.PSS'):continue
        code=magic in (b'\x7fELF',b'SNR2')
        row=add(file.relative_to(root).as_posix(),0,file.stat().st_size,file.name,'Code' if code else 'Video',file.relative_to(root/'disc').as_posix())
        if code:
            data=file.read_bytes()
            if magic==b'\x7fELF':row.update(format='ELF32',details=elf_info(data))
            else:
                row['format']='SNR2 REL';row['details']={'loadCallbackOffset':hex(u32(data,24)),'unloadCallbackOffset':hex(u32(data,28)),'symbolCount':u32(data,16),'runtimeAddress':'Relocatable; no fixed load address'}
        row['status']='Raw download'
    out.mkdir(parents=True,exist_ok=True)
    result=dict(version=2,manifestSha256=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),assets=assets,counts=counts,errors=errors,notes=['Original source paths are names, not recoverable source files.','Audio IDs are not assigned to levels without a verified mapping.','Geometry/collision/animation are raw downloads, not rendered models.','ELF/REL metadata is not decompiled C source.','WAV previews decode one pass; loop playback is not reconstructed.'])
    (out/'index.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    print('Indexed',len(assets),'assets;',dict(counts),'preview errors',len(errors),flush=True)
    return result


def upgrade_models(root, out, index):
    counts=collections.Counter()
    for row in index['assets']:
        if row['category'] not in ('Geometry','Models','Other'): continue
        row.pop('animations',None)
        with (root/row['source']).open('rb') as f:
            f.seek(row['offset']);raw=f.read(row['size'])
        if len(raw)>=8 and u32(raw,0)==0x10001:
            row['category']='Models'
            try:
                model=models.decode(raw)
                row.update(status='3D preview',modelPreview=True,vertexCount=model['vertexCount'],triangleCount=model['triangleCount'],boneCount=len(model.get('skeleton') or []))
                row.pop('error',None)
                counts['preview']+=1
            except (ValueError,IndexError,struct.error) as exc:
                row.update(status='Preview unavailable',error=str(exc),modelPreview=False)
                counts['unsupported']+=1
        elif row['category'] in ('Geometry','Models'):
            row.update(category='Other',status='Geometry metadata')
    def stem(row):return row['name'].lower().split('.mb')[0]
    skins=collections.defaultdict(list)
    for row in index['assets']:
        if row.get('modelPreview') and row.get('boneCount'):skins[stem(row)].append(row)
    for row in index['assets']:
        if row['category']!='Animation':continue
        with (root/row['source']).open('rb') as f:f.seek(row['offset']);raw=f.read(row['size'])
        try:
            bank=animations.decode(raw)
            row.update(clipCount=len(bank['clips']),status='Animation bank',animationPreview=False)
            matches=[m for m in skins.get(stem(row),[]) if m['boneCount']>bank['maxBone']]
            for m in matches:
                if m['archive']==row['archive'] or row['archive'] in ('GLOBAL.WAD','SP.WAD','MP.WAD') or m['archive']=='GLOBAL.WAD':
                    m.setdefault('animations',[]).append(dict(id=row['id'],name=row['name'],clipCount=len(bank['clips'])))
            same=[m for m in matches if m['archive']==row['archive']]
            candidates=same or [m for m in matches if m['archive']=='GLOBAL.WAD'] or (matches if row['archive'] in ('GLOBAL.WAD','SP.WAD','MP.WAD') else [])
            if candidates:row.update(modelId=candidates[0]['id'],animationPreview=True,status='Animation preview')
            else:row['error']='Animation tracks decoded, but no matching skinned model was found.'
        except (ValueError,IndexError,struct.error) as exc:row.update(status='Preview unavailable',error=str(exc))
    index['counts']=dict(collections.Counter(a['category'] for a in index['assets']))
    index['version']=5
    index['notes']=[n for n in index['notes'] if 'rendered models' not in n]
    index['notes'].append('Supported PS2 GDE meshes have embedded 3D previews. Unsupported variants remain downloadable.')
    (out/'index.json').write_text(json.dumps(index,ensure_ascii=False),encoding='utf-8')
    print('Models:',dict(counts),flush=True)
    return index


def serve(root,out,index,port):
    index=dict(index,assets=[a for a in index['assets'] if a['category']!='Levels']+levels.catalog(index['assets']))
    index['extractionRoot']=str(root.resolve())
    index['region']=detect_region((root/'disc/SYSTEM.CNF').read_text())
    index['counts']=dict(collections.Counter(a['category'] for a in index['assets']))
    by_id={row['id']:row for row in index['assets']};lock=threading.Lock()
    textures=collections.defaultdict(list)
    for row in index['assets']:
        if row.get('preview'):textures[row.get('signature')].append(row)
    @functools.lru_cache(maxsize=8)
    def model_json(asset_id):
        row=by_id[asset_id]
        source=(root/row['source']).resolve();source.relative_to(root)
        with source.open('rb') as f:f.seek(row['offset']);raw=f.read(row['size'])
        model=models.decode(raw)
        model['animations']=row.get('animations',[])
        model['warnings']=['Preview uses the base material layer and simple lighting; game shader effects and transparency sorting are not reproduced.']
        for mat in model['materials']:
            matches=textures.get(mat['textureSignature'],[])
            same=[x for x in matches if x['archive']==row['archive']]
            shared=[x for x in matches if x['archive']=='GLOBAL.WAD']
            shared+= [x for x in matches if x['archive'] in ('SP.WAD','MP.WAD')]
            choices=same or shared or (matches if len(matches)==1 else [])
            if choices:mat['textureUrl']='/asset/'+choices[0]['id']+'/png'
        return json.dumps(model,allow_nan=False,separators=(',',':')).encode()

    level_lock=threading.Lock()
    @functools.lru_cache(maxsize=1)
    def level_data(key):
        return levels.assemble(root,by_id[key],index['assets'],lambda key:json.loads(model_json(key)))

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,data,kind,status=200,filename=None):
            # Browser audio seeks use HTTP byte ranges.
            start,end=0,len(data)-1
            request=self.headers.get('Range')
            if request and status==200:
                match=re.fullmatch(r'bytes=(\d+)-(\d*)',request)
                if match:
                    start=int(match[1]);end=min(end,int(match[2])) if match[2] else end
                    if start>end:
                        self.send_response(416);self.send_header('Content-Range',f'bytes */{len(data)}');self.end_headers();return
                    status=206
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes');self.send_header('X-Content-Type-Options','nosniff')
            if kind.startswith(('text/html','text/javascript','application/json')):self.send_header('Cache-Control','no-store')
            if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{len(data)}')
            if filename:self.send_header('Content-Disposition',f'attachment; filename="{safe_name(filename)}"')
            self.end_headers()
            try:self.wfile.write(data[start:end+1])
            except (BrokenPipeError,ConnectionResetError):pass
        def do_GET(self):
            path=urllib.parse.urlsplit(self.path).path
            try:
                if path=='/':return self.send((HERE/'web/index.html').read_bytes(),'text/html; charset=utf-8')
                if path in ('/web/model-viewer.js','/web/level-viewer.js'):return self.send((HERE/path.lstrip('/')).read_bytes(),'text/javascript; charset=utf-8')
                if path=='/api/index':return self.send(json.dumps(index,ensure_ascii=False).encode(),'application/json; charset=utf-8')
                match=re.fullmatch(r'/asset/([a-f0-9]{20})/(raw|png|wav|info|model|animation|level|level-bin)',path)
                if not match or match[1] not in by_id:return self.send(b'Not found','text/plain',404)
                row=by_id[match[1]];action=match[2]
                if action in ('level','level-bin'):
                    if row['category']!='Levels':raise ValueError('Not a level')
                    with level_lock:data,binary=level_data(row['id'])
                    return self.send(binary if action=='level-bin' else json.dumps(data,allow_nan=False).encode(),'application/octet-stream' if action=='level-bin' else 'application/json')
                if action=='info' and row['category']=='Levels':return self.send(json.dumps(row).encode(),'application/json')
                source=(root/row['source']).resolve();source.relative_to(root)
                if action=='model':return self.send(model_json(row['id']),'application/json')
                if action=='png':
                    if not row.get('preview'):raise ValueError('No texture preview')
                    preview=(out/row['preview']).resolve();preview.relative_to(out)
                    return self.send(preview.read_bytes(),'image/png')
                with source.open('rb') as f:f.seek(row['offset']);raw=f.read(row['size'])
                if len(raw)!=row['size']:raise ValueError('Source changed; rebuild index')
                if action=='animation':return self.send(json.dumps(animations.decode(raw),allow_nan=False,separators=(',',':')).encode(),'application/json')
                if action=='info':
                    detail=dict(row,hexPreview='\n'.join(f'{i:04x}  '+raw[i:i+16].hex(' ') for i in range(0,min(256,len(raw)),16)))
                    if row['category']=='Animation':detail['clips']=[dict(name=c['name'],duration=c['duration'],tracks=len(c['tracks'])) for c in animations.decode(raw)['clips']]
                    return self.send(json.dumps(detail,ensure_ascii=False).encode(),'application/json; charset=utf-8')
                if action=='raw':return self.send(raw,'application/octet-stream',filename=row['name'])
                if row['category']!='Audio':raise ValueError('Not an audio stream')
                dest=out/'audio'/f'{row["id"]}.wav'
                with lock:
                    if not dest.exists():
                        wave=vag_wav(raw);dest.parent.mkdir(exist_ok=True);dest.write_bytes(wave)
                return self.send(dest.read_bytes(),'audio/wav')
            except (ValueError,KeyError,OSError,struct.error) as exc:self.send(str(exc).encode(),'text/plain; charset=utf-8',422)
    class ViewerServer(http.server.ThreadingHTTPServer):
        allow_reuse_address=False
    server=ViewerServer(('127.0.0.1',port),Handler)
    print(f'Browse http://127.0.0.1:{server.server_port}  (Ctrl+C to stop)',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,required=True,help='Extracted game folder containing disc/, unpacked/, audio/, manifest.json')
    ap.add_argument('--out',type=Path,default=HERE/'output')
    ap.add_argument('--rebuild',action='store_true');ap.add_argument('--build-only',action='store_true');ap.add_argument('--port',type=int,default=8765)
    args=ap.parse_args();root=args.root.resolve();out=args.out.resolve()
    if not (root/'manifest.json').is_file():ap.error('Missing extraction manifest.json')
    index=json.loads((out/'index.json').read_text(encoding='utf-8')) if (out/'index.json').exists() else {}
    fingerprint=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
    if args.rebuild or index.get('version') not in (2,3,4,5) or index.get('manifestSha256')!=fingerprint:
        index=build(root,out)
    if args.rebuild or index.get('version')!=5:index=upgrade_models(root,out,index)
    if not args.build_only:serve(root,out,index,args.port)

if __name__=='__main__':main()
