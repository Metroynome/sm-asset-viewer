# Size Matters level placement evidence

NTSC-U `LVL/LEVEL_01.REL` is the reference; addresses are REL file offsets.

- BOG version 60: forms at header +36/+40 (52 bytes each), types +44/+48 (68 bytes), mobys +52/+56 (128 bytes). Moby +64 selects its type, +68 selects its form, +92 distinguishes original placements from empty pool records. The type form count is byte +60. The form geometry signature is +4. Loader 0x12af18 reads these fields; the form loader advances by 52 at 0x12aee4.
- Tie class table is header +84/+88; shrub class table +100/+104. Both class records are 24 bytes, with geometry signature +4, placement pointer +16, count +20.
- Tie loader 0x12b090 advances each placement by `100 + 8 * byte[98]`. Shrub loader 0x12b130 advances by `84 + 8 * byte[81]`. Both start with a 16-float affine transform; trailing light data is retained in the original file but not evaluated.
- Asset types 0 and 1 provide terrain and sky GDE geometry already in scene coordinates. BOG matrices place local GDE geometry directly in the same Y-up coordinate system. References resolve against the level and its GLOBAL/SP/MP banks, never unrelated levels.

The WebGL2 level renderer shares mesh buffers between placements. Its binary response uses version 2, 48-byte position/normal/UV/RGBA vertices and uint32 indices. Sky renders before geometry without depth writes. Preview lighting and material behavior remain approximate; runtime gameplay and skeletal animation are not evaluated in assembled levels.
