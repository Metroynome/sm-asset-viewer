import struct
import unittest
import levels
from regions import detect_region

class LevelTests(unittest.TestCase):
    def fixture(self):
        b=bytearray(1600)
        b[:4]=b'BOG ';struct.pack_into('<II',b,4,60,len(b))
        struct.pack_into('<4I',b,44,256,1,384,2)
        struct.pack_into('<II',b,36,128,1)
        struct.pack_into('<I',b,260,128);b[316]=1
        struct.pack_into('<I',b,132,0x12345678)
        for p in (384,512):
            struct.pack_into('<16f',b,p,*levels.IDENTITY)
            struct.pack_into('<I',b,p+64,256)
        struct.pack_into('<I',b,384+92,1)
        for header,table,start,base,light,count in ((84,768,800,100,98,1),(100,1040,1080,84,81,2)):
            struct.pack_into('<4I',b,header,table,1,start,2)
            struct.pack_into('<6I',b,table,0,0x87654321,0,0,start,2)
            for i in range(2):
                matrix=list(levels.IDENTITY);matrix[12:15]=[10+i,20,30]
                struct.pack_into('<16f',b,start,*matrix);b[start+light]=count if i==0 else 0
                start+=base+(count*8 if i==0 else 0)
        return b

    def test_variable_light_records_and_pool(self):
        nodes,report=levels.gameplay(self.fixture())
        self.assertEqual(report['pooled'],1)
        self.assertEqual(report['ties'],2)
        self.assertEqual(report['shrubs'],2)
        self.assertEqual(len(nodes),5)
        self.assertEqual(nodes[0]['signature'],'12345678')
        self.assertEqual(nodes[2]['matrix'][12:15],[11,20,30])
        self.assertEqual(nodes[4]['matrix'][12:15],[11,20,30])

    def test_bad_form_pointer_is_rejected(self):
        b=self.fixture();struct.pack_into('<I',b,260,129)
        with self.assertRaisesRegex(ValueError,'form'):levels.gameplay(b)

    def test_non_affine_matrix_is_rejected(self):
        b=self.fixture();struct.pack_into('<f',b,384+60,0)
        with self.assertRaisesRegex(ValueError,'affine'):levels.gameplay(b)

    def test_scenery_count_is_checked(self):
        b=self.fixture();struct.pack_into('<I',b,96,3)
        with self.assertRaisesRegex(ValueError,'count'):levels.gameplay(b)

    def test_regions(self):
        for serial,region in [('SCUS_976.15','ntscu'),('SCES_550.19','pal'),('SCPS_151.20','ntscj')]:
            self.assertEqual(detect_region('BOOT2 = cdrom0:'+serial+';1')['id'],region)
        self.assertEqual(detect_region('SCUS_000.00')['id'],'unknown')

if __name__=='__main__':unittest.main()
