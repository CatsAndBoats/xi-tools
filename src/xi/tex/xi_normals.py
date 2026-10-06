#!/usr/bin/env python3
"""`xi tex normals` — normal maps for a DAT's textures, named for VanaCore's texture packs.

VanaCore replaces a texture by the FNV-1a hash of the first level the game *uploads*,
not by any DAT name, and the game converts what it reads (paletted art goes up as DXT3,
the HD pack's art is not the vanilla DAT's). So the hash can't be computed from the DAT.
Instead VanaCore's `[graphics] tex_debug=<folder>` writes every upload as `<hash>.bin` plus
an `index.txt` (`hash WxH format`); this command decodes those, matches each to a texture
of the DAT by its pixels (measured: identical art correlates at 1.000, anything else under
0.5), and writes `<hash>_<W>x<H>.n.dds` (BC5 / ATI2, X in red and Y in green, with mips)
from the normal PNG that has the texture's name.

The normal PNGs come from `xi tex export` -> an upscaler/normal model (chaiNNer) -> the
same file names in `--normals`. `--placeholder` writes a flat normal for textures with none.
"""

import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click
import numpy as np

from xi.tex.xi_core import (parse_sections, parse_texture, resolve_dat_path,
                           SECTION_TYPE_TEXTURE, sanitize, rom_rel)
from xi.xi_config import read_path_for

FMT_ARGB = 0x15          # D3DFMT_A8R8G8B8
FMT_DXT1 = 0x31545844    # 'DXT1'
FMT_DXT3 = 0x33545844    # 'DXT3'
MATCH_MIN = 0.98         # luminance correlation of a match
MATCH_GAP = 0.02         # ... and by how much it beats the next texture


# --- decoding what the game uploaded -----------------------------------------------------------

def _rgb565(v: np.ndarray) -> np.ndarray:
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1).astype(np.int32)


def decode_dxt(data: bytes, w: int, h: int, dxt3: bool) -> np.ndarray:
    """DXT1 / DXT3 -> (h, w, 4) uint8."""
    bw, bh = (w + 3) // 4, (h + 3) // 4
    blk = 16 if dxt3 else 8
    raw = np.frombuffer(data, np.uint8)[: bw * bh * blk].reshape(bh * bw, blk)
    c = raw[:, blk - 8:]
    c0 = c[:, 0].astype(np.uint16) | (c[:, 1].astype(np.uint16) << 8)
    c1 = c[:, 2].astype(np.uint16) | (c[:, 3].astype(np.uint16) << 8)
    bits = c[:, 4:8].astype(np.uint32)
    bits = bits[:, 0] | (bits[:, 1] << 8) | (bits[:, 2] << 16) | (bits[:, 3] << 24)
    p0, p1 = _rgb565(c0), _rgb565(c1)
    four = (c0 > c1) | dxt3                      # DXT3 always uses the four-colour palette
    pal = np.zeros((len(raw), 4, 4), np.int32)
    pal[:, 0, :3], pal[:, 1, :3] = p0, p1
    pal[:, 2, :3] = np.where(four[:, None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[:, 3, :3] = np.where(four[:, None], (p0 + 2 * p1) // 3, 0)
    pal[:, :, 3] = 255
    pal[~four, 3, 3] = 0
    sel = (bits[:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3
    px = pal[np.arange(len(raw))[:, None], sel]  # (blocks, 16, 4)
    if dxt3:
        a = raw[:, :8].astype(np.uint64)
        a = sum(a[:, i] << np.uint64(8 * i) for i in range(8))
        px[:, :, 3] = (((a[:, None] >> (4 * np.arange(16, dtype=np.uint64))) & np.uint64(15)) * 17).astype(np.int32)
    img = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return img[:h, :w].astype(np.uint8)


def decode_upload(data: bytes, w: int, h: int, fmt: int) -> Optional[np.ndarray]:
    if fmt == FMT_ARGB:
        return np.frombuffer(data, np.uint8)[: w * h * 4].reshape(h, w, 4)[..., [2, 1, 0, 3]]
    if fmt in (FMT_DXT1, FMT_DXT3):
        return decode_dxt(data, w, h, fmt == FMT_DXT3)
    return None


def read_dump(folder: Path) -> List[Tuple[str, int, int, int]]:
    """`index.txt` rows of a tex_debug dump: (hash, width, height, format)."""
    rows = []
    for line in (folder / "index.txt").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 3 and (folder / f"{parts[0]}.bin").exists():
            w, h = parts[1].split("x")
            rows.append((parts[0], int(w), int(h), int(parts[2], 16)))
    return rows


# --- matching ----------------------------------------------------------------------------------

def _lum(a: np.ndarray) -> np.ndarray:
    return a[..., :3].astype(np.float32).mean(-1).ravel()


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.std() < 1e-6 or b.std() < 1e-6:
        return 0.0
    return float(((a - a.mean()) * (b - b.mean())).mean() / (a.std() * b.std()))


def dat_textures(dat_path: Path) -> List[Tuple[str, np.ndarray]]:
    """(file stem, RGBA) of each texture; a repeated name gets `__2`, `__3` ... so no two share a stem."""
    data = bytes(read_path_for(dat_path).read_bytes())
    seen: Dict[str, int] = {}
    out = []
    for s in parse_sections(bytearray(data)):
        if s.type_code != SECTION_TYPE_TEXTURE:
            continue
        img = parse_texture(data, s)
        if img is None:
            continue
        stem = sanitize(img.name)
        seen[stem] = seen.get(stem, 0) + 1
        if seen[stem] > 1:
            stem = f"{stem}__{seen[stem]}"
        out.append((stem, np.frombuffer(img.rgba, np.uint8).reshape(img.height, img.width, 4)))
    return out


def match_dump(dump: Path, textures: List[Tuple[str, np.ndarray]], min_side: int = 64) -> Dict:
    """Each upload of at least `min_side` on its short side -> the DAT texture it is.
    {'matched': [(hash, w, h, stem)], 'unmatched': [(hash, w, h)], 'ambiguous': [...]}"""
    by_size: Dict[Tuple[int, int], List] = {}
    for stem, rgba in textures:
        by_size.setdefault((rgba.shape[1], rgba.shape[0]), []).append((stem, _lum(rgba)))
    res: Dict[str, list] = {"matched": [], "unmatched": [], "ambiguous": []}
    for h_, w, h, fmt in read_dump(dump):
        if min(w, h) < min_side:
            continue
        up = decode_upload((dump / f"{h_}.bin").read_bytes(), w, h, fmt)
        cands = by_size.get((w, h))
        if up is None or not cands:
            res["unmatched"].append((h_, w, h))
            continue
        lum = _lum(up)
        scored = [(_corr(lum, c), stem) for stem, c in cands]
        top = max(sc for sc, _ in scored)
        if top < MATCH_MIN:
            res["unmatched"].append((h_, w, h))
            continue
        # textures of identical art (a name repeated in a DAT) tie: the first in the DAT stands for them
        first = next(stem for sc, stem in scored if sc >= top - 1e-4)
        rivals = [stem for sc, stem in scored if stem != first and top - sc < MATCH_GAP and sc < top - 1e-4]
        if rivals:
            res["ambiguous"].append((h_, w, h, first, rivals[0]))
        else:
            res["matched"].append((h_, w, h, first))
    return res


# --- BC5 ---------------------------------------------------------------------------------------

def _bc4(ch: np.ndarray) -> np.ndarray:
    """(blocks, 16) uint8 -> (blocks, 8) uint8: the 8-value mode, endpoints at the block's extremes."""
    hi, lo = ch.max(1).astype(np.int32), ch.min(1).astype(np.int32)
    a0, a1 = hi, lo                                   # a0 > a1 selects the 8-value palette
    pal = np.stack([a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)], 1)
    idx = np.abs(ch[:, :, None].astype(np.int32) - pal[:, None, :]).argmin(2).astype(np.uint64)
    bits = np.zeros(len(ch), np.uint64)
    for i in range(16):
        bits |= idx[:, i] << np.uint64(3 * i)
    out = np.zeros((len(ch), 8), np.uint8)
    out[:, 0], out[:, 1] = a0, a1
    for i in range(6):
        out[:, 2 + i] = ((bits >> np.uint64(8 * i)) & np.uint64(255)).astype(np.uint8)
    return out


def encode_bc5(rg: np.ndarray) -> bytes:
    """(h, w, 2) uint8 -> BC5 blocks (red block then green block per 4x4)."""
    h, w = rg.shape[:2]
    ph, pw = (h + 3) // 4 * 4, (w + 3) // 4 * 4
    pad = np.pad(rg, ((0, ph - h), (0, pw - w), (0, 0)), mode="edge")
    blocks = pad.reshape(ph // 4, 4, pw // 4, 4, 2).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 2)
    return np.concatenate([_bc4(blocks[:, :, 0]), _bc4(blocks[:, :, 1])], 1).tobytes()


def normal_chain(rgb: np.ndarray) -> List[np.ndarray]:
    """Tangent-space normal PNG pixels -> every mip as (h, w, 2) uint8 X/Y, the vectors renormalised."""
    v = rgb[..., :3].astype(np.float32) / 127.5 - 1.0
    v /= np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-6)
    chain = []
    while True:
        chain.append(np.clip((v[..., :2] * 0.5 + 0.5) * 255.0 + 0.5, 0, 255).astype(np.uint8))
        h, w = v.shape[:2]
        if h == 1 and w == 1:
            return chain
        nh, nw = max(h // 2, 1), max(w // 2, 1)
        v = v[: nh * (2 if h > 1 else 1), : nw * (2 if w > 1 else 1)]
        v = v.reshape(nh, h // nh, nw, w // nw, 3).mean((1, 3))
        v /= np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-6)


def dds_bc5(rgb: np.ndarray) -> bytes:
    """A DDS file (FourCC ATI2 = BC5) of a normal map, with its full mip chain."""
    chain = normal_chain(rgb)
    h, w = rgb.shape[:2]
    top = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
    hdr = struct.pack("<4sIIIIIII", b"DDS ", 124, 0x000A1007, h, w, top, 0, len(chain)) + bytes(44)
    hdr += struct.pack("<II4sIIIII", 32, 4, b"ATI2", 0, 0, 0, 0, 0)
    hdr += struct.pack("<IIIII", 0x401008, 0, 0, 0, 0)
    return hdr + b"".join(encode_bc5(m) for m in chain)


def flat_normal(w: int, h: int) -> np.ndarray:
    return np.broadcast_to(np.array([128, 128, 255], np.uint8), (h, w, 3))


# --- the command -------------------------------------------------------------------------------

def make_normals(dat_path: Path, dump: Path, normals: Optional[Path], out_dir: Path,
                 placeholder: bool = False, min_side: int = 64, dry_run: bool = False) -> Dict:
    """Match, then write one `<hash>_<W>x<H>.n.dds` per upload that has a normal PNG (or a placeholder)."""
    from PIL import Image
    res = match_dump(dump, dat_textures(dat_path), min_side)
    written, missing = [], []
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    for h_, w, h, stem in res["matched"]:
        png = next((q for q in (normals / f"{stem}.png", normals / f"{stem}_normal.png") if q.exists()), None) if normals else None
        if png is not None:
            rgb = np.asarray(Image.open(png).convert("RGB"))
            if rgb.shape[:2] != (h, w):               # a model that upscaled it: the pack wants the upload's size
                rgb = np.asarray(Image.fromarray(rgb).resize((w, h), Image.LANCZOS))
        elif placeholder:
            rgb = flat_normal(w, h)
        else:
            missing.append(stem)
            continue
        name = f"{h_}_{w}x{h}.n.dds"
        if not dry_run:
            (out_dir / name).write_bytes(dds_bc5(rgb))
        written.append(name)
    return {**res, "written": written, "missing": sorted(set(missing))}


@click.command()
@click.argument("dat_path")
@click.option("--dump", "dump", required=True, type=click.Path(exists=True, file_okay=False),
              help="VanaCore [graphics] tex_debug folder (index.txt + <hash>.bin).")
@click.option("--normals", type=click.Path(file_okay=False), default=None,
              help="Normal PNGs named like `xi tex export`'s: <texture>.png or <texture>_normal.png.")
@click.option("--output-dir", "out_dir", type=click.Path(), default=None,
              help="Where the .n.dds files go (default: exports/tex/normals/<rom>/).")
@click.option("--placeholder", is_flag=True, help="A flat normal for each texture with no PNG in --normals.")
@click.option("--min-side", default=64, show_default=True, help="Skip uploads smaller than this on their short side.")
@click.option("--dry-run", is_flag=True, help="Match and report, write nothing.")
def normals_cmd(dat_path, dump, normals, out_dir, placeholder, min_side, dry_run):
    """Name normal maps for VanaCore's texture packs by matching a tex_debug dump to a DAT's textures."""
    try:
        resolved = resolve_dat_path(dat_path)
    except FileNotFoundError as e:
        raise click.ClickException(str(e))
    out = Path(out_dir) if out_dir else Path("exports") / "tex" / "normals" / rom_rel(Path(resolved))
    r = make_normals(Path(resolved), Path(dump), Path(normals) if normals else None, out,
                     placeholder, min_side, dry_run)
    click.echo(f"{len(r['matched'])} upload(s) matched, {len(r['unmatched'])} not in this DAT, "
               f"{len(r['ambiguous'])} ambiguous")
    click.echo(f"{'Would write' if dry_run else 'Wrote'} {len(r['written'])} file(s) -> {out}")
    if r["missing"]:
        click.echo(f"No normal PNG (use --placeholder for a flat one): {', '.join(r['missing'][:20])}"
                   + (" ..." if len(r["missing"]) > 20 else ""))
    for h_, w, h, a, b in r["ambiguous"][:10]:
        click.echo(f"  ambiguous {h_} {w}x{h}: {a} or {b}")
