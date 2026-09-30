"""PS2 GDE mesh decoder. Offsets verified against LOADER_LoadGdeFile / SKIN_DrawMesh."""
import math
import struct


def u32(b, p): return struct.unpack_from('<I', b, p)[0]
def f32(b, p): return struct.unpack_from('<f', b, p)[0]
def bounds(b, p, size):
    if size == 0:return
    if p < 0 or size < 0 or p + size > len(b): raise ValueError('Model offset outside asset')


def vif(b, start, size):
    """Read bounded VIF commands; return each UNPACK stream grouped by MSCNT."""
    bounds(b, start, size)
    p, end, group = start, start + size, []
    while p < end:
        bounds(b, p, 4)
        code = u32(b, p); p += 4
        cmd, n, imm = (code >> 24) & 127, (code >> 16) & 255, code & 65535
        if cmd & 0x60 == 0x60:
            n = n or 256
            components, bits = ((cmd >> 2) & 3) + 1, (32,16,8,5)[cmd & 3]
            if bits == 5: raise ValueError('Unsupported packed VIF vector')
            length = n * components * bits // 8
            if p + length > end: raise ValueError('Truncated VIF UNPACK')
            fmt = {32:'I',16:'H' if imm & 0x4000 else 'h',8:'B' if imm & 0x4000 else 'b'}[bits]
            values = list(struct.iter_unpack('<' + fmt * components, b[p:p+length]))
            group.append(dict(address=imm & 0x3ff, bits=bits, components=components, values=values))
            p += (length + 3) & ~3
        elif cmd in (0x14,0x15,0x17):
            if group: yield group
            group = []
        elif cmd in (0x20,0x30,0x31,0x4a,0x50,0x51):
            length = 4 if cmd==0x20 else 16 if cmd in (0x30,0x31) else (n or 256)*8 if cmd==0x4a else imm*16
            p += length
        elif cmd not in (0,1,2,3,4,5,6,7,0x10,0x11,0x13):
            raise ValueError(f'Unsupported VIF command {cmd:02x}')
        if p > end: raise ValueError('Truncated VIF command')
    if group: yield group


def material_list(b):
    count, off, tc, to = struct.unpack_from('<4I', b, 8)
    bounds(b, off, count*248); bounds(b, to, tc*20)
    result=[]
    for i in range(count):
        p=off+i*248
        name=b[p:p+96].split(b'\0')[0].decode('ascii','replace')
        layers=u32(b,p+108); signature=None
        if layers and struct.unpack_from('<H',b,p+112)[0]:
            ti=struct.unpack_from('<H',b,p+116)[0]
            if ti<tc: signature=f'{u32(b,to+ti*20):08x}'
        # MATERIAL_Activate: GS ALPHA 0x44 / 0x48 / 0x42; alpha test >0 / >64.
        flags=u32(b,p+104);blend=b[p+164] if layers else 0;test=b[p+165] if layers else 2
        result.append(dict(name=name,textureSignature=signature,materialFlags=flags,
            transparent=bool(flags&1),blendEquation=('alpha','add','subtract')[blend] if blend<3 else 'alpha',
            alphaCutoff=0.5 if test==1 else 0 if test==0 else -1,layerCount=layers))
    return result


def packet_mesh(b, off, size, scale, material, skin=False, bones=None, scene=False):
    meshes=[]
    for streams in vif(b, off, size):
        pos=next((x for x in streams if x['components']==(4 if scene else 3) and x['bits']==16),None)
        if pos is None: continue
        positions=[[(v-16384)*scale if skin else v*scale for v in xyz[:3]] for xyz in pos['values']]
        n=len(positions)
        uv=next((x for x in streams if x['address']==(3 if skin else 1) and x['bits']==16),None)
        color=next((x for x in streams if x['address']==(2 if scene else 3) and x['bits']==8),None) if not skin else None
        if uv and len(uv['values'])!=n: raise ValueError('UV count mismatch')
        indices=[]
        for i in range(2,n):
            tri=[i-2,i-1,i] if i%2==0 else [i-1,i-2,i]
            a,c,d=[positions[t] for t in tri]
            if a==c or c==d or a==d: continue
            indices.extend(tri)
        if not indices: continue
        mesh=dict(positions=positions,indices=indices,material=material,
            uvs=[[v[0]/1024,v[1]/1024] for v in uv['values']] if uv else [],
            colors=[[(v&255)/128 for v in c[:3]] for c in color['values']] if color else [],
            alphas=[min(1,(c[3]&255)/128) for c in color['values']] if color else [],bakedLighting=bool(color))
        normal=next((x for x in streams if not scene and x['address']==2 and x['bits']==8),None)
        if normal:
            if len(normal['values'])!=n:raise ValueError('Normal count mismatch')
            mesh['normals']=[[(v if v<128 else v-256)/127 for v in xyz[:3]] for xyz in normal['values']]
        if skin:
            weights=next((x for x in streams if x['address']==1 and x['bits']==8),None)
            if weights is None or len(weights['values'])!=n: raise ValueError('Missing skin weights')
            mesh['joints']=list(bones)
            mesh['weights']=[[(v & 255)/127 for v in w]+[v/127 for v in uv['values'][i][2:4]] for i,w in enumerate(weights['values'])]
            if any(abs(sum(w)-1)>0.025 for w in mesh['weights']): raise ValueError('Unsupported skin weight encoding')
        meshes.append(mesh)
    return meshes


def deferred_meshes(b, table, count, lod, part):
    # ALPHASORT renderer: 32-byte batches, triangle list with 48-byte float vertices.
    bounds(b,table,count*32);result=[]
    for i in range(count):
        p=table+i*32;n=struct.unpack_from('<H',b,p+16)[0];material=u32(b,p+20);off=u32(b,p+28)
        bounds(b,off,n*144)
        if not n:continue
        positions=[];uvs=[];colors=[];alphas=[]
        for j in range(n*3):
            q=off+j*48
            positions.append([v*0.01 for v in struct.unpack_from('<3f',b,q+32)])
            uvs.append(list(struct.unpack_from('<2f',b,q)))
            colors.append([max(0,v/128) for v in struct.unpack_from('<3f',b,q+16)])
            alphas.append(min(1,max(0,f32(b,q+28)/128)))
        result.append(dict(lod=lod,part=part,positions=positions,uvs=uvs,colors=colors,alphas=alphas,indices=list(range(n*3)),material=material,transparent=True,bakedLighting=True))
    return result


def decode(b):
    bounds(b,0,4)
    if u32(b,0)!=0x10001: raise ValueError('This asset is metadata, not a PS2 GDE mesh')
    bounds(b,0,60)
    typ=u32(b,4); p=u32(b,28);bounds(b,p,48)
    materials=material_list(b); meshes=[]; lods=[]; skeleton=None; skeleton_scale=1.0
    if typ==0x10000004:
        if u32(b,p)!=3: raise ValueError('Unsupported static mesh version')
        count=u32(b,p+4)
        if not 0<count<=7: raise ValueError('Invalid static LOD count')
        for lod in range(count):
            q=p+8+lod*36;bounds(b,q,36)
            scale=f32(b,q+4)/32768*0.01
            if not math.isfinite(scale) or scale<=0: raise ValueError('Invalid vertex scale')
            n,table=struct.unpack_from('<II',b,q+12);
            if n: bounds(b,table,n*12)
            start=len(meshes)
            for i in range(n):
                r=table+i*12; size,off=struct.unpack_from('<II',b,r+4)
                parts=packet_mesh(b,off,size,scale,b[r+2])
                for part in parts: part.update(lod=lod,part=b[r+3])
                meshes.extend(parts)
            meshes.extend(deferred_meshes(b,u32(b,q+24),struct.unpack_from('<H',b,q+20)[0],lod,0))
            lods.append(dict(level=lod,meshStart=start,meshCount=len(meshes)-start))
    elif typ==0x10000003:
        if u32(b,p)!=2: raise ValueError('Unsupported shrub version')
        scale=f32(b,p+8)/32768*0.01
        size,off=struct.unpack_from('<II',b,p+36)
        meshes=packet_mesh(b,off,size,scale,0)
        for part in meshes: part.update(lod=0,part=0)
        lods=[dict(level=0,meshStart=0,meshCount=len(meshes))]
    elif typ==0x10000000:
        if u32(b,p)!=3:raise ValueError('Unsupported scene mesh version')
        scale=f32(b,p+4)*0.01
        count,table=struct.unpack_from('<II',b,p+16);bounds(b,table,count*8)
        for i in range(count):
            q=table+i*8;mat,n,part_table=struct.unpack_from('<HHI',b,q);bounds(b,part_table,n*16)
            for j in range(n):
                q=part_table+j*16;part,packets,pt=struct.unpack_from('<HHI',b,q);bounds(b,pt,packets*24)
                for k in range(packets):
                    r=pt+k*24;size=struct.unpack_from('<H',b,r+2)[0]
                    if not size:continue
                    decoded=packet_mesh(b,u32(b,r+4),size,scale,mat,scene=True)
                    for m in decoded:m.update(lod=0,part=part)
                    meshes.extend(decoded)
                q=part_table+j*16
                meshes.extend(deferred_meshes(b,u32(b,q+12),struct.unpack_from('<H',b,q+8)[0],0,part))
        lods=[dict(level=0,meshStart=0,meshCount=len(meshes))]
    elif typ==0x10000001:
        if u32(b,p)!=2: raise ValueError('Unsupported skinned mesh version')
        scale=f32(b,p+16)/16384
        # Joint matrices use normalized skin units; vertices include this scale.
        skeleton_scale=f32(b,p+16)
        skeleton=read_skeleton(b,u32(b,32),skeleton_scale)
        for lod in range(6):
            cmd=u32(b,p+24+lod*4)
            if not cmd: continue
            start=len(meshes); material=0; slots=[0]*6; part=0
            for _ in range(100000):
                bounds(b,cmd,4);word=u32(b,cmd);cmd+=4;op=word>>24
                if op==0xfe:break
                if op==0xfc:material=word&15
                elif op==0xf9:part=word&15
                elif op in (0xfa,0xfb):
                    slot=(word>>16)&15;bone=word&65535
                    if slot>=6 or bone>=len(skeleton):raise ValueError('Invalid skin bone slot')
                    slots[slot]=bone
                elif op==1:
                    q=word&0xffffff;bounds(b,q,16)
                    parts=packet_mesh(b,u32(b,q+12),u32(b,q+8),scale,material,skin=True,bones=slots)
                    for m in parts:
                        m.update(lod=lod,part=part)
                        m['uvs']=[[(u-1)*f32(b,p+8),v*-f32(b,p+12)] for u,v in m['uvs']]
                    meshes.extend(parts)
                # SKIN_DrawMesh ignores all other command words.
            else: raise ValueError('Unterminated skin command stream')
            lods.append(dict(level=lod,meshStart=start,meshCount=len(meshes)-start))
    else:
        raise ValueError(f'Model variant 0x{typ:08x} is not decoded yet')
    if not meshes: raise ValueError('No drawable triangles')
    default_lod=max(lods,key=lambda l:sum(len(m['indices']) for m in meshes if m['lod']==l['level']))['level']
    vertices=[v for m in meshes if m['lod']==default_lod for v in m['positions']]
    if not vertices: raise ValueError('Empty first LOD')
    if not all(math.isfinite(c) and abs(c)<1e7 for v in vertices for c in v): raise ValueError('Invalid vertex coordinates')
    return dict(format='PS2 GDE',variant=f'0x{typ:08x}',materials=materials,meshes=meshes,lods=lods,
        skeleton=skeleton,skeletonScale=skeleton_scale,defaultLod=default_lod,bounds=[list(map(min,zip(*vertices))),list(map(max,zip(*vertices)))],
        vertexCount=sum(len(m['positions']) for m in meshes),triangleCount=sum(len(m['indices'])//3 for m in meshes))


def read_skeleton(b, p, scale=1.0):
    bounds(b,p,24)
    if u32(b,p)!=0x44444444:raise ValueError('Unknown skeleton header')
    count,table,defaults=struct.unpack_from('<III',b,p+4)
    if not 0<count<=128:raise ValueError('Invalid bone count')
    bounds(b,table,count*80);bounds(b,defaults,count*48)
    result=[]
    for i in range(count):
        q=table+i*80;d=defaults+i*48
        parent=b[q+68]
        if parent!=255 and parent>=i:raise ValueError('Invalid skeleton hierarchy')
        values=struct.unpack_from('<12f',b,d)
        matrix=list(struct.unpack_from('<16f',b,q))
        matrix[12:15]=[v*scale for v in matrix[12:15]]
        if not all(math.isfinite(v) for v in (*values,*matrix)):raise ValueError('Invalid bone transform')
        result.append(dict(parent=-1 if parent==255 else parent,inverseBind=matrix,
            rotation=list(values[:4]),scale=list(values[4:7]),translation=[v/800*scale for v in values[8:11]]))
    return result
