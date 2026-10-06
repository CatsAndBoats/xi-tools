# `xi tex normals`

Names normal maps for VanaCore's texture packs. VanaCore swaps a texture by the FNV-1a hash of the
first level the game *uploads*, which can't be computed from the DAT: the game converts what it reads
(paletted art goes up as DXT3), and a client running the HD pack uploads the HD DAT's art, not the
vanilla DAT's. So the hashes come from the game itself, and this command matches them to the DAT's
textures by their pixels.

```bash
# 1. VanaCore vanacore.ini: [graphics] tex_debug=textures\dump   -> play in the zone, quit, remove the line
# 2. the DAT the game really loads (check for an overlay: FFXI_HD_DIR / FFXI_PIVOT_DIR have their own ROM/1/35.DAT)
xi tex export "<HD dir>\ROM\1\35.DAT"                         # PNGs to feed the normal model (chaiNNer)
# 3. normals named like the export (<texture>.png) in one folder
xi tex normals "<HD dir>\ROM\1\35.DAT" --dump <dump folder> --normals <normal PNGs>
xi tex normals "<HD dir>\ROM\1\35.DAT" --dump <dump folder> --placeholder --dry-run   # flat normals, report only
```

Writes `exports/tex/normals/<rom>/<hash>_<W>x<H>.n.dds`: BC5 (FourCC `ATI2`), X in red, Y in green,
a full mip chain, each mip renormalised. A PNG of another size (an upscaling model) is resized to the
upload's.

| Option | |
|---|---|
| `--dump DIR` | VanaCore's `tex_debug` folder (`index.txt` + `<hash>.bin`). Required. |
| `--normals DIR` | Normal PNGs named like `xi tex export`'s: `<texture>.png` or `<texture>_normal.png`. |
| `--placeholder` | A flat normal for a texture with no PNG. |
| `--output-dir DIR` | Default `exports/tex/normals/<rom>/`. |
| `--min-side N` | Skip uploads smaller than N on their short side (default 64; the game re-uploads small dynamic text). |
| `--dry-run` | Match and report, write nothing. |

## What is measured

Bastok Markets (`ROM/1/35`, the HD pack's): 43 of the dump's uploads matched a texture of the DAT at a
luminance correlation of 1.000 and no flip. The same dump against the *vanilla* DAT matched 1 of them,
which is why the DAT matters. Uploads not in the DAT (characters, UI, login) are reported as such.
A name repeated in a DAT gets `__2`, `__3` ... in `--normals` file names; textures with identical art
share the first one's normal.

## Not done yet

VanaCore does not read `.n.dds` files: `load_dds` takes DXT1/3/5 only and no draw binds a normal map.
The files are ready for that renderer work (`conflux/src/gfx/d3d8.c` `texture_replacement`).
Paletted textures are matched, not recomputed, so a texture the game never uploaded during the dump has no hash.
