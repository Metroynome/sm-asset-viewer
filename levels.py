"""Size Matters PS2 saved level assembly (BOG v60 and GDE assets)."""
import array
import collections
import hashlib
import itertools
import json
import math
import re
import struct
from pathlib import Path
from models import bounds, u32

IDENTITY=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]


def catalog(assets):
    rows=[]
    for archive in sorted({a['archive'] for a in assets if re.fullmatch(r'WAD/\d{2}C?\.WAD',a['archive'],re.I)}):
        source=next(a for a in assets if a['archive']==archive)
        rows.append(dict(id=hashlib.sha256(('level:'+archive).encode()).hexdigest()[:20],name=('12 - Template' if archive.upper()=='WAD/12.WAD' else source['group']),category='Levels',group=source['group'],archive=archive,source=source['source'],offset=0,size=0,status='Fly-through preview',levelPreview=True))
    return rows


def read_asset(root,row):
    with (root/row['source']).open('rb') as f:
        f.seek(row['offset']);b=f.read(row['size'])
    if len(b)!=row['size']:raise ValueError('Truncated level asset')
    return b


def placement_matrix(b,p):
    bounds(b,p,64);m=list(struct.unpack_from('<16f',b,p))
    if not all(math.isfinite(v) for v in m):raise ValueError('Nonfinite placement matrix')
    if any(abs(m[i])>1e-5 for i in (3,7,11)) or abs(m[15]-1)>1e-5:raise ValueError('Invalid affine placement matrix')
    return m


def gameplay(b):
    bounds(b,0,128)
    if b[:4]!=b'BOG ' or u32(b,4)!=60 or u32(b,8)!=len(b):raise ValueError('Unsupported BOG header/version (expected 60)')
    nodes=[];report=dict(mobyRecords=0,pooled=0,logicOnly=0,ties=0,shrubs=0)
    types,nt,start,count=struct.unpack_from('<4I',b,44)
    bounds(b,types,nt*68);bounds(b,start,count*128)
    forms,nforms=struct.unpack_from('<II',b,36);bounds(b,forms,nforms*52)
    report['mobyRecords']=count
    for i in range(count):
        p=start+i*128;t=u32(b,p+64)
        if not u32(b,p+92):report['pooled']+=1;continue
        if not types<=t<types+nt*68 or (t-types)%68:raise ValueError('Invalid moby type pointer')
        form=b[p+68];num=b[t+60]
        if not num:report['logicOnly']+=1;continue
        fp=u32(b,t+4)+form*52
        if form>=num or not forms<=fp<forms+nforms*52 or (fp-forms)%52:raise ValueError('Invalid moby form pointer')
        nodes.append(dict(signature=f'{u32(b,fp+4):08x}',name=f'Moby #{i}',matrix=placement_matrix(b,p),source='BOG moby',group='Mobys',flags=u32(b,p+100)))
    # LEVEL_01.REL 0x12b090 / 0x12b130: class +4 geometry signature,
    # +16 placement pointer, +20 count. Each record has variable light pairs.
    for header,base,lights,group,key in ((84,100,98,'Ties / props','ties'),(100,84,81,'Shrubs / foliage','shrubs')):
        table,n=struct.unpack_from('<II',b,header);bounds(b,table,n*24)
        total=0
        for i in range(n):
            t=table+i*24;p=u32(b,t+16);count=u32(b,t+20)
            if count>len(b)//base:raise ValueError('Invalid scenery count')
            for j in range(count):
                bounds(b,p,base);stride=base+b[p+lights]*8;bounds(b,p,stride)
                nodes.append(dict(signature=f'{u32(b,t+4):08x}',name=f'{group} {i}:{j}',matrix=placement_matrix(b,p),source='BOG '+key,group=group))
                total+=1;p+=stride
        if total!=u32(b,header+12):raise ValueError('Scenery count does not match BOG header')
        report[key]=total
    return nodes,report


def assemble(root,row,assets,model_loader):
    local=[a for a in assets if a['archive']==row['archive']]
    shared_names={'GLOBAL.WAD','MP.WAD' if re.search(r'/(16|17|18|19|20)',row['archive']) else 'SP.WAD'}
    by_signature={}
    for a in sorted(assets,key=lambda a:a['archive']==row['archive']):
        if a.get('modelPreview') and (a['archive']==row['archive'] or a['archive'] in shared_names):by_signature[a['signature']]=a
    draw=[];warnings=[];report={};nodes=[]
    for a in local:
        if a.get('modelPreview') and a.get('assetType') in (0,1):
            draw.append(dict(name=a['name'],modelId=a['id'],matrix=list(IDENTITY),source='GDE scene',group='Skybox' if a['assetType']==1 else 'Terrain / scenery'))
    for a in local:
        if a['category']=='Gameplay':
            placed,stats=gameplay(read_asset(root,a));nodes.extend(placed);report.update(stats)
    for n in nodes:
        signature=n.pop('signature');a=by_signature.get(signature)
        if not a:warnings.append(f'Missing geometry {signature}: '+n['name']);continue
        n['modelId']=a['id'];n['name']=a['name']+' - '+n['name'];draw.append(n)
    binary=bytearray();geometry={};materials=[];materialids={}
    for key in dict.fromkeys(n['modelId'] for n in draw):
        model=model_loader(key);parts=[]
        for mesh in model['meshes']:
            if mesh['lod']!=model.get('defaultLod',0):continue
            mat=model['materials'][mesh['material']];tex=mat.get('textureUrl');mk=json.dumps(mat,sort_keys=True,separators=(',',':'))
            if mk not in materialids:materialids[mk]=len(materials);materials.append(dict(mat))
            pos=mesh['positions'];normals=mesh.get('normals');indices=mesh['indices']
            if not normals:
                normals=[[0.,0.,0.] for _ in pos]
                for i in range(0,len(indices),3):
                    ids=indices[i:i+3];a,b,c=[pos[j] for j in ids];u=[b[k]-a[k] for k in range(3)];v=[c[k]-a[k] for k in range(3)];normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
                    for j in ids:
                        for k in range(3):normals[j][k]+=normal[k]
                normals=[[v/(math.sqrt(sum(x*x for x in n)) or 1) for v in n] for n in normals]
            alphas=mesh.get('alphas') or [1]*len(pos)
            data=array.array('f',(v for i,p in enumerate(pos) for v in (*p,*normals[i],*(mesh['uvs'][i] if mesh['uvs'] else [0,0]),*(mesh['colors'][i] if mesh['colors'] else [1,1,1]),alphas[i])))
            vo=len(binary);binary.extend(data.tobytes());io=len(binary);binary.extend(array.array('I',indices).tobytes())
            parts.append(dict(vertexOffset=vo,indexOffset=io,count=len(indices),material=materialids[mk],bakedLighting=mesh.get('bakedLighting',False),sceneLighting=bool(mesh.get('normals')) and not mesh.get('bakedLighting',False)))
        geometry[key]=dict(parts=parts,bounds=model['bounds'],name=next(n['name'] for n in draw if n['modelId']==key))
    low=[math.inf]*3;high=[-math.inf]*3
    for n in draw:
        if n['group'] in ('Skybox','Inactive / templates'):continue
        bounds=geometry[n['modelId']]['bounds'];m=n['matrix']
        for p in itertools.product(*zip(*bounds)):
            v=[sum(m[j*4+k]*p[j] for j in range(3))+m[12+k] for k in range(3)]
            for k in range(3):low[k]=min(low[k],v[k]);high[k]=max(high[k],v[k])
    if not all(math.isfinite(v) for v in low+high):low=[-10,-10,-10];high=[10,10,10]
    report.update(placedMobys=sum(n['source']=='BOG moby' for n in draw),drawInstances=len(draw),uniqueModels=len(geometry),binaryBytes=len(binary))
    return dict(version=2,vertexStride=48,name=row['name'],nodes=draw,geometry=geometry,materials=materials,lights=[],bounds=[low,high],groups=dict(collections.Counter(n['group'] for n in draw)),report=report,warnings=warnings),binary
