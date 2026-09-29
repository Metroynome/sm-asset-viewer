"""Bounded GIM and mono VAG decoders; standard library only."""
import array
import struct
import sys
import zlib


def u16(data, offset): return struct.unpack_from('<H', data, offset)[0]
def u32(data, offset): return struct.unpack_from('<I', data, offset)[0]


def colors(data, fmt, count):
    if fmt == 3:
        if len(data) < count * 4: raise ValueError('Truncated RGBA palette')
        return [data[i:i+4] for i in range(0, count*4, 4)]
    if fmt not in (0, 1, 2) or len(data) < count*2: raise ValueError('Unsupported color format')
    out = []
    for i in range(count):
        v = u16(data, i*2)
        if fmt == 0: c = ((v&31)*255//31, ((v>>5)&63)*255//63, ((v>>11)&31)*255//31, 255)
        elif fmt == 1: c = ((v&31)*255//31, ((v>>5)&31)*255//31, ((v>>10)&31)*255//31, (v>>15)*255)
        else: c = tuple(((v>>s)&15)*17 for s in (0,4,8,12))
        out.append(bytes(c))
    return out


def gim(data):
    if data[:12] != b'MIG.00.1PSP\0': raise ValueError('Not a little-endian PSP GIM')
    blocks = {}
    pos = 16
    while pos+16 <= len(data):
        kind, size, step, header = struct.unpack_from('<4I', data, pos)
        if not size and not step: break
        if size < 16 or pos+size > len(data) or step < 16 or step > size:
            raise ValueError('Invalid GIM block')
        if kind in (4,5):
            if kind in blocks: raise ValueError('Multiple GIM pictures are not yet supported')
            blocks[kind] = data[pos:pos+size]
        pos += step
    block = blocks.get(4)
    if block is None or len(block) < 80: raise ValueError('Missing image block')
    fmt, order, width, height, bpp = struct.unpack_from('<5H',block,20)
    if not 0 < width <= 4096 or not 0 < height <= 4096: raise ValueError('Invalid image dimensions')
    if fmt not in range(8) or order not in (0,1): raise ValueError('Unsupported GIM encoding')
    expected = (16,16,16,32,4,8,16,32)[fmt]
    if bpp != expected: raise ValueError('GIM pixel depth mismatch')
    start = 16 + u32(block,44)
    stride = (width*bpp+7)//8
    stored_stride = (stride+15)&~15 if order else stride
    stored_height = (height+7)&~7 if order else height
    raw = block[start:start+stored_stride*stored_height]
    if start < 64 or len(raw) != stored_stride*stored_height: raise ValueError('Truncated GIM pixels')
    if order:
        pixels = bytearray(stride*height)
        for y in range(height):
            for x in range(stride):
                off = ((y//8)*(stored_stride//16)+x//16)*128+(y%8)*16+x%16
                pixels[y*stride+x] = raw[off]
        raw = pixels
    if fmt < 4:
        rgba = b''.join(colors(raw,fmt,width*height))
    else:
        pal = blocks.get(5)
        if pal is None or len(pal)<80: raise ValueError('Missing palette')
        pf, _, entries = struct.unpack_from('<3H',pal,20)
        po = 16+u32(pal,44)
        if not 0<entries<=65536 or po<64: raise ValueError('Invalid palette')
        entries = min(entries, 1 << bpp)
        palette = colors(pal[po:],pf,entries)
        rgba = bytearray()
        for y in range(height):
            for x in range(width):
                bit = y*stride*8+x*bpp
                if bpp==4: index=(raw[bit//8]>>(bit%8))&15
                elif bpp==8: index=raw[bit//8]
                elif bpp==16: index=u16(raw,bit//8)
                else: index=u32(raw,bit//8)
                if index>=entries: raise ValueError('Palette index outside table')
                rgba.extend(palette[index])
    return width,height,bytes(rgba)


def png(width,height,rgba):
    def chunk(kind,body):
        return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)&0xffffffff)
    scan = b''.join(b'\0'+rgba[y*width*4:(y+1)*width*4] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(scan))+chunk(b'IEND',b'')


def vag_info(data):
    if len(data)<48 or data[:4]!=b'VAGp': raise ValueError('Not a VAGp stream')
    version,size,rate = struct.unpack_from('>I',data,4)[0],struct.unpack_from('>I',data,12)[0],struct.unpack_from('>I',data,16)[0]
    if version not in (0,2,3,0x20) or not 4000<=rate<=96000 or size%16 or 48+size>len(data):
        raise ValueError('Unsupported or truncated VAG stream')
    return size,rate


def vag_wav(data):
    size,rate = vag_info(data)
    coefficients = ((0,0),(60,0),(115,-52),(98,-55),(122,-60))
    pcm = array.array('h')
    h1=h2=0
    for pos in range(48,48+size,16):
        param,flag = data[pos:pos+2]
        shift,filt=param&15,param>>4
        if filt>=5 or shift>12: raise ValueError('Invalid ADPCM frame')
        if flag==7: break
        a,b=coefficients[filt]
        for byte in data[pos+2:pos+16]:
            for nibble in (byte&15,byte>>4):
                sample=((nibble if nibble<8 else nibble-16)<<12)>>shift
                sample += (h1*a+h2*b+32)>>6
                sample=max(-32768,min(32767,sample))
                pcm.append(sample);h2,h1=h1,sample
        if flag&1: break
    if sys.byteorder!='little': pcm.byteswap()
    body=pcm.tobytes()
    return b'RIFF'+struct.pack('<I',36+len(body))+b'WAVEfmt '+struct.pack('<IHHIIHH',16,1,1,rate,rate*2,2,16)+b'data'+struct.pack('<I',len(body))+body
