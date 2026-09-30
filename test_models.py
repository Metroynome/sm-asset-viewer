import struct
import unittest
from models import packet_mesh, vif, decode, read_skeleton, material_list, deferred_meshes
from animations import decode as animation


def unpack(cmd, address, values, fmt):
    raw=b''.join(struct.pack('<'+fmt,*v) for v in values)
    return struct.pack('<I',(cmd<<24)|(len(values)<<16)|address)+raw+b'\0'*((-len(raw))%4)


class ModelsTest(unittest.TestCase):
    def test_strip_degenerates_and_scale(self):
        data=unpack(0x65,1,[(0,0)]*5,'2h')+unpack(0x69,4,[(0,0,0),(0,0,0),(2,0,0),(0,2,0),(0,2,0)],'3h')+struct.pack('<I',0x17000000)
        mesh=packet_mesh(data,0,len(data),0.5,0)[0]
        self.assertEqual(mesh['indices'],[2,1,3])
        self.assertEqual(mesh['positions'][2],[1,0,0])
        with self.assertRaises(ValueError):list(vif(data,0,len(data)-8))

    def test_scene_uv_quantization(self):
        b=bytearray(320)
        struct.pack_into('<2I',b,0,0x10001,0x10000000)
        struct.pack_into('<I',b,28,64)
        struct.pack_into('<If',b,64,3,1)
        struct.pack_into('<2I',b,80,1,112)
        struct.pack_into('<HHI',b,112,0,1,128)
        struct.pack_into('<HHI',b,128,0,1,160)
        packet=unpack(0x65,1,[(256,-128)]*3,'2h')+unpack(0x6d,3,[(0,0,0,0),(1,0,0,0),(0,1,0,0)],'4h')
        struct.pack_into('<HI',b,162,len(packet),192)
        b[192:192+len(packet)]=packet
        self.assertEqual(decode(b)['meshes'][0]['uvs'],[[1,-.5]]*3)
        # Other packet paths retain their separate 1/1024 scale.
        self.assertEqual(packet_mesh(packet,0,len(packet),1,0,scene=True)[0]['uvs'],[[.25,-.125]]*3)

    def test_vertex_rgba_and_signed_normals(self):
        data=unpack(0x6e,2,[(0,127,0,0)]*3,'4b')+unpack(0x6e,3,[(255,128,64,32)]*3,'4B')+unpack(0x69,4,[(0,0,0),(1,0,0),(0,1,0)],'3h')
        mesh=packet_mesh(data,0,len(data),1,0)[0]
        self.assertEqual(mesh['colors'][0],[255/128,1,.5])
        self.assertEqual(mesh['alphas'],[.25]*3)
        self.assertEqual(mesh['normals'][0],[0,1,0])
        self.assertTrue(mesh['bakedLighting'])

    def test_ps2_material_and_deferred_alpha(self):
        b=bytearray(600);struct.pack_into('<4I',b,8,1,64,0,0)
        struct.pack_into('<II',b,64+104,1,1);b[64+164]=2;b[64+165]=1
        mat=material_list(b)[0]
        self.assertTrue(mat['transparent']);self.assertEqual(mat['blendEquation'],'subtract');self.assertEqual(mat['alphaCutoff'],.5)
        struct.pack_into('<H',b,336,1);struct.pack_into('<I',b,348,368)
        for i in range(3):struct.pack_into('<4f',b,368+i*48+16,128,128,128,64)
        self.assertEqual(deferred_meshes(b,320,1,0,0)[0]['alphas'],[.5]*3)

    def test_skin_quantization_and_six_weights(self):
        data=unpack(0x6e,1,[(0,0,0,0)]*3,'4b')+unpack(0x6d,3,[(0,0,127,0)]*3,'4h')+unpack(0x69,5,[(16384,16384,16384),(18432,16384,16384),(16384,18432,16384)],'3h')
        m=packet_mesh(data,0,len(data),8/16384,0,skin=True,bones=list(range(6)))[0]
        self.assertEqual(m['positions'][1],[1,0,0])
        self.assertEqual(m['weights'][0],[0,0,0,0,1,0])
        with self.assertRaises(ValueError):decode(b'not a model')

    def test_skin_bind_pivot_uses_mesh_units(self):
        b=bytearray(152)
        struct.pack_into('<4I',b,0,0x44444444,1,24,104)
        inverse=[1,0,0,0,0,1,0,0,0,0,1,0,-0.125,-0.25,0,1]
        struct.pack_into('<16f',b,24,*inverse)
        b[24+68]=255
        struct.pack_into('<12f',b,104,0,0,0,1,1,1,1,0,100,200,0,0)
        bone=read_skeleton(b,0,8)[0]
        self.assertEqual(bone['translation'],[1,2,0])
        self.assertEqual(bone['inverseBind'][12:15],[-1,-2,0])
        # Rotating about this bind joint must leave the joint itself stationary.
        pivot=bone['translation']
        local=[pivot[i]+bone['inverseBind'][12+i] for i in range(3)]
        rotated=[-local[1]+pivot[0],local[0]+pivot[1],local[2]+pivot[2]]
        self.assertEqual(rotated,pivot)

    def test_animation_channels(self):
        b=bytearray(126)
        struct.pack_into('<IfB',b,0,12,15.0,1)
        b[12:20]=b'TESTCLIP'
        struct.pack_into('<I',b,24,76)
        struct.pack_into('<f',b,52,2)
        b[59]=1
        b[80:82]=bytes([2,7])
        struct.pack_into('<II',b,84,2,92)
        quaternion=(511<<30)|(511<<20)|(511<<10)|1022
        for off,t in [(92,64),(109,320)]:
            struct.pack_into('<h',b,off,t)
            b[off+2:off+7]=quaternion.to_bytes(5,'big')
            struct.pack_into('<3hI',b,off+7,8000,-8000,0,(64<<20)|(128<<10)|32)
        track=animation(b)['clips'][0]['tracks'][0]
        self.assertEqual(track['bone'],2)
        self.assertEqual([k['time'] for k in track['frames']],[0.25,1.25])
        self.assertEqual(track['frames'][0]['rotation'],[0,0,0,1])
        self.assertEqual(track['frames'][0]['translation'],[1,-1,0])
        self.assertEqual(track['frames'][0]['scale'],[1,2,0.5])
        with self.assertRaises(ValueError):animation(b[:-1])


if __name__=='__main__':unittest.main()
