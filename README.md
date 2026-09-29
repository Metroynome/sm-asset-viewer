# sm-asset-viewer

Python 3.10+; no third-party packages. A standalone local asset viewer and extraction toolkit for Ratchet & Clank: Size Matters on PS2.

Run `start.cmd` after extracting into `data/extracted`, then open http://127.0.0.1:8765. For another extraction directory, run `start.cmd --root "path/to/extracted"` or use the Python command below.

For an existing extraction:

```
python browse.py --root path/to/extracted
```

The same extractor supports NTSC-U, PAL, and NTSC-J. To extract one ISO into a new folder:

```
python extract_sm.py game.iso --output data/extracted
python index_assets.py data/extracted
python browse.py --root data/extracted
```

Use `--rebuild` after changing the source files, `--out path` to relocate the generated catalog/cache, or `--build-only` to export PNGs without running a server. The browser binds only to 127.0.0.1.

The folder is self-contained. Share the scripts and web folder; generated assets, audio and the ISO are not bundled with the tools. `output/` contains the searchable JSON index, categorized PNG exports and on-demand WAV cache.

Supported previews: little-endian GIM base images and standard mono VAGp streams. Supported PS2 GDE models render directly in the viewer, including scene geometry, static objects, shrubs and skinned characters. Matching ANIM v15 banks play on the model with clip selection, play/pause, scrubbing and playback speed. Collision, sound-bank metadata, videos and ELF/REL binaries remain raw downloads. Audio stream-to-level mapping is unverified. Names truncated in the original WAD remain truncated.

The extraction scripts reuse the existing Metroynome SM pipeline. `upstream/tjzip_dump.py` is the existing electrogecko TJZIP decoder from https://github.com/electrogecko/UYA_pyTools/tree/main/SM; retained unchanged. GIM and VAG format research: https://github.com/vn-tools/arc_unpacker/blob/master/src/dec/playstation/gim_image_decoder.cc and https://github.com/vgmstream/vgmstream/blob/master/src/meta/vag.c. New preview decoders are implemented here without dependencies on those projects.

Horizon Forge reference: its `PackerHelper` invokes `DL.Level`, with Wrench used for asset conversion, before Unity imports the results. Those game-specific converters do not parse Size Matters HIG/SNR2 assets.

## Extraction and code tools

Run `python tools.py --help` for the categorized command list. The original extraction scripts remain directly runnable. No game files or machine-specific data paths are bundled.

| Command | Output |
| --- | --- |
| `extract` | ISO files, decompressed HIG/WAD payloads and sections |
| `audio-index` | VAGS.WAD streams and embedded source paths |
| `browse` | Asset catalog, PNG textures, WAV previews |
| `symbols` | Boot ELF symbol JSON and TSV; optional GNU v2 demangler |
| `audit-symbols` | All disc files and decompressed archives scanned for ELF/SNR tables |
| `types` | Partial NTSC-U dump type/name reference, not recovered struct layouts |
| `level-defs` | Initial NTSC-U definitions and ELF/REL metadata |
| `add-regions` | PAL / NTSC-J definitions and split binaries |
| `split-binaries` | Boot sections and losslessly split REL blocks |

For extraction, use the same scripts for each region. The definition/audit/export tools expect this data layout under `--workspace`:

```
extracted/                 NTSC-U extraction
pal/extracted/             PAL extraction
ntscj/extracted/           NTSC-J extraction
rac-defs-sm.json
rac-defs-sm-metadata.json
symbols/                   generated reports
```

`--rac-levels` selects the definitions/export directory. It must contain the original `rac-defs.json` schema reference; this file is never rewritten. Default folders are `data/` and `data/rac-levels/` inside this toolkit. Direct script invocation accepts the equivalent `SM_WORKSPACE` and `SM_RAC_LEVELS` environment variables.

Examples from this folder:

```
python tools.py symbols path/to/SCUS_976.15 --output output/symbols
python tools.py --workspace data audit-symbols --regions ntscu
python tools.py --workspace data --rac-levels "data/rac-levels" split-binaries --output output/rac5
python tools.py types path/to/eeMemory.bin --symbols output/symbols/symbols.json --output output/smtypes.txt
```

For fresh definitions, run `level-defs` first, then `add-regions` once all three regions have been extracted. These commands write matching SM definitions to both configured directories. `level-defs` refuses existing destination files; `add-regions` requires the two copies to match. `split-binaries` supports NTSC-U-only definitions too. REL offsets are module-relative, not ready-to-import live RAM addresses.

`types` validates the NTSC-U boot symbols against the dump; `--plan` optionally supplies an earlier import plan's opaque type names. Without a demangler, symbol linkage names are preserved as-is. This does not reconstruct missing debug types.

`tool-manifest.json` records included scripts and exclusions. One-off Ghidra session repair/rename scripts and the historical loader memory audit are not extraction dependencies and remain in their original location. Original workspace scripts are unchanged.

## Model and animation previews

Choose **Mobys**, then an asset: its 3D preview opens inside the existing detail panel. Drag to orbit, Shift-drag to pan, and scroll to zoom. Texture, wireframe, LOD and reset controls are above the canvas. Skinned models offer matching animation banks and clips; playback starts automatically unless you have paused it. Previous/Next follows the current filters, and moby thumbnails appear as you browse. The most detailed mesh is selected by default; all available LODs remain selectable. Selecting a matched asset under **Animation** opens its model in the same panel. Animation playback uses full-detail LOD 0.

The NTSC-U extraction currently provides 2,000 decoded GDE model records (including repeated assets across archives). All 314 animation banks parse; 313 have automatic model matches. `ShieldSphere` uses a separate, unsupported model variant. `RatchetStdMaster.mb.anim` has no automatic model match. These files remain downloadable. Names and animation labels truncated in the original files are preserved.

The preview uses the first material texture layer and simple lighting. Game-specific shader effects, transparency sorting, animation event callbacks and gameplay blending are not reproduced. Missing textures render shaded geometry. Animation matching uses asset names and bone-index bounds; the original game is the reference for unusual poses. No separate application, CDN, npm install or Ghidra connection is required to view assets.

Decoder references: NTSC-U Pokitaru `LOADER_LoadGdeFile` / `LOAD_CHARACTER_SkinGdeFile`, `SKIN_DrawMesh`, animation loader at `00e772a8`, keyframe decoder at `00dd5420`, `ANIM_CreateOutputMatrices`, and alpha triangle renderer at `00dda818`. Tests: `python -m unittest discover -s . -p "test_*.py"`.

## Regions and level previews

Extract and index all three regions in one command (omit any region you do not have):

```sh
python tools.py extract-regions --ntscu "usa.iso" --pal "europe.iso" --ntscj "japan.iso" --output data
```

Disc IDs are checked before extraction. Output folders are `data/extracted`, `data/pal/extracted`, and `data/ntscj/extracted`. `--resume` compares existing disc files with the ISO before reusing them. Each region can be viewed separately:

```sh
python browse.py --root data/pal/extracted --out output/pal
python browse.py --root data/ntscj/extracted --out output/ntscj
```

Select **Levels** in the sidebar and open a level. Drag to look, use WASD to fly, Space/Ctrl to rise/descend, Shift for faster movement, and the wheel to change speed. The preview includes terrain, sky, saved moby placements, props, and shrubs. Layers can be toggled independently; object search and Focus object help locate individual placements. Overview, Ground view, fullscreen, and Previous/Next are available.

These are saved level previews: mobys use their bind pose, and gameplay scripts, runtime spawns, animation, lighting, fog, and secondary material effects are not simulated. Missing drawable references are listed in Assembly details. The regional template scene and skyboard scenes may contain little or no saved gameplay geometry.
