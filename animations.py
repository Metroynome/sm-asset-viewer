"""ANIM v15 tracks, verified against Pokitaru 00e772a8 and 00dd5420."""
import math
import struct
from models import bounds,u32,f32


def decode(b):
    bounds(b,0,12)
    if f32(b,4)!=15:raise ValueError('Unsupported animation version')
    table,count=u32(b,0),b[8]
    bounds(b,table,count*64)
    clips=[]
    for i in range(count):
        p=table+i*64
        name=b[p:p+8].split(b'\0')[0].decode('ascii','replace')
        duration=f32(b,p+40)
        if not math.isfinite(duration) or not 0<=duration<10000:raise ValueError('Invalid animation duration')
        # LOD 0 uses the full skeleton, matching the full model preview.
        off,n=u32(b,p+12),b[p+47]
        bounds(b,off,n*16)
        tracks=[]
        for j in range(n):
            q=off+j*16;bone,flags=b[q+4:q+6];keys,ptr=struct.unpack_from('<II',b,q+8)
            if flags&~7 or keys>100000:raise ValueError('Unsupported animation track')
            stride=2+(5 if flags&1 else 0)+(6 if flags&2 else 0)+(4 if flags&4 else 0)
            bounds(b,ptr,keys*stride);frames=[]
            for k in range(keys):
                r=ptr+k*stride;t=struct.unpack_from('<h',b,r)[0]/256;r+=2
                frame=dict(time=t)
                if flags&1:
                    packed=int.from_bytes(b[r:r+5],'big');r+=5
                    frame['rotation']=[((packed>>shift)&1023)/511-1 for shift in (30,20,10,0)]
                if flags&2:
                    frame['translation']=[v/8000 for v in struct.unpack_from('<3h',b,r)];r+=6
                if flags&4:
                    packed=u32(b,r)
                    frame['scale']=[((packed>>shift)&1023)/64 for shift in (20,10,0)]
                if frames and t<frames[-1]['time']:raise ValueError('Nonmonotonic animation keys')
                frames.append(frame)
            tracks.append(dict(bone=bone,frames=frames))
        clips.append(dict(name=name or f'Clip {i}',duration=duration,tracks=tracks))
    return dict(format='ANIM v15',clips=clips,maxBone=max((t['bone'] for c in clips for t in c['tracks']),default=-1))
