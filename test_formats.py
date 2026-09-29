import io
import struct
import unittest
import wave
from formats import gim, png, vag_wav

class FormatsTest(unittest.TestCase):
    def test_vag_silence(self):
        data=bytearray(64);data[:4]=b'VAGp';struct.pack_into('>II',data,12,16,22050)
        with wave.open(io.BytesIO(vag_wav(data))) as sound:
            self.assertEqual((sound.getnchannels(),sound.getframerate(),sound.getnframes()),(1,22050,28))
            self.assertEqual(sound.readframes(28),bytes(56))
        with self.assertRaises(ValueError):vag_wav(data[:-1])
        data[48]=0xf0
        with self.assertRaises(ValueError):vag_wav(data)

    def test_rgba_gim(self):
        data=bytearray(16+80+8);data[:12]=b'MIG.00.1PSP\0'
        struct.pack_into('<4I',data,16,4,88,88,16)
        struct.pack_into('<5H',data,36,3,0,2,1,32)
        struct.pack_into('<I',data,60,64)
        data[96:]=bytes([255,0,0,255,0,255,0,128])
        w,h,rgba=gim(data)
        self.assertEqual((w,h,rgba),(2,1,bytes(data[96:])))
        self.assertTrue(png(w,h,rgba).startswith(b'\x89PNG'))
        with self.assertRaises(ValueError):gim(data[:-1])

if __name__=='__main__':unittest.main()
