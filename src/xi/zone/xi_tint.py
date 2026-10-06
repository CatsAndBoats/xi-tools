#!/usr/bin/env python3
"""Colour-tint zone meshes by scaling their baked vertex colours.

The editor's per-model "Colour" panel (brightness / R / G / B, or Match Colour) records
a multiplier per mesh name in the change-set:

    "meshTints": {"xi_ar_3bx4": {"rgb": [1.04, 0.97, 0.92], "fp0": "…", "pub": [1, 1, 1]}}

At publish every 0x2E section with that name gets each vertex's BGRA colour scaled by
``rgb`` in place: same topology, same vertex format, alpha untouched. The vertex colour
is the baked lighting, stored half-scale (0x80 = 1.0, doubled by the client), so a byte
tops out at about 2x. Brightening clips where retail colours already sit near 255;
darkening and hue shifts are exact.

The tint is per MESH, not per placement: every placement of that mesh shares the one
0x2E section, so all copies change together. Textures are left alone; they are shared
across many meshes, so recolouring one would leak onto every other mesh that uses it.

``rgb`` is relative to the pristine mesh. A "Reset DAT before Publish" run re-applies it
to fresh bytes, so it never compounds. Without a reset the DAT still holds the tint from
the last publish (``pub``, tracked by the editor), so ``tint_factors`` applies only the
difference rgb / pub.
"""

from __future__ import annotations

import click

from xi.entity.anim.xi_export import parse_sections
from xi.zone.xi_decrypt import decrypt_zone_mesh, reencrypt_zone_mesh
from xi.zone.xi_export import SECTION_TYPE_ZONE_MESH, parse_zone_mesh_section

_EPS = 1e-4


def _rgb(v) -> tuple[float, float, float] | None:
    """A change-set tint value as an (r, g, b) multiplier: a bare [r, g, b] list or a
    {"rgb": [...]} record. None when malformed."""
    if isinstance(v, dict):
        v = v.get("rgb")
    if not isinstance(v, (list, tuple)) or len(v) < 3:
        return None
    try:
        r, g, b = (float(v[0]), float(v[1]), float(v[2]))
    except (TypeError, ValueError):
        return None
    if min(r, g, b) < 0:
        return None
    return r, g, b


def _is_identity(rgb) -> bool:
    return all(abs(c - 1.0) < _EPS for c in rgb)


def tint_factors(mesh_tints: dict | None, relative: bool = False) -> dict[str, list[float]]:
    """Resolve the editor's ``meshTints`` records to the multipliers to apply now.

    ``relative`` = publishing onto the current DAT (no reset): divide out the tint the
    last publish already baked in (``pub``), so the result lands on ``rgb`` instead of
    stacking. Identity factors are dropped."""
    out: dict[str, list[float]] = {}
    for name, rec in (mesh_tints or {}).items():
        rgb = _rgb(rec)
        if not name or rgb is None:
            continue
        if relative and isinstance(rec, dict):
            pub = _rgb(rec.get("pub")) or (1.0, 1.0, 1.0)
            rgb = tuple(c / p if p > _EPS else c for c, p in zip(rgb, pub))
        if not _is_identity(rgb):
            out[str(name)] = [round(c, 4) for c in rgb]
    return out


def tint_zone_meshes(data: bytearray, mesh_tints: dict, table1: bytes, table2: bytes) -> dict:
    """Scale the vertex colours of every named 0x2E mesh in ``data`` (in place).

    ``mesh_tints`` maps mesh name -> [r, g, b] (or a {"rgb": …} record). Returns
    {"tinted": n_meshes, "vertices": n, "clipped": n_channels, "missing": [names]}."""
    wanted = {}
    for name, rec in (mesh_tints or {}).items():
        rgb = _rgb(rec)
        if name and rgb is not None and not _is_identity(rgb):
            wanted[str(name)] = rgb
    stats = {"tinted": 0, "vertices": 0, "clipped": 0, "missing": []}
    if not wanted:
        return stats
    found: set[str] = set()
    for s in parse_sections(data):
        if s.type_code != SECTION_TYPE_ZONE_MESH:
            continue
        decrypt_zone_mesh(data, s.data_start, table1, table2)
        try:
            name = data[s.data_start + 0x10:s.data_start + 0x20].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
            rgb = wanted.get(name)
            if rgb is None:
                continue
            offsets: list[int] = []
            parse_zone_mesh_section(data, s, color_offsets=offsets)
            fr, fg, fb = rgb
            clipped = 0
            for off in offsets:
                # BGRA: scale B, G, R; leave alpha (transparency) alone.
                for i, f in ((0, fb), (1, fg), (2, fr)):
                    v = round(data[off + i] * f)
                    if v > 255:
                        v = 255
                        clipped += 1
                    data[off + i] = v
            found.add(name)
            stats["tinted"] += 1
            stats["vertices"] += len(offsets)
            stats["clipped"] += clipped
            click.echo(f"[tint] {name}: {len(offsets)} vertices x ({fr:.2f}, {fg:.2f}, {fb:.2f})"
                       + (f" — {clipped} channel(s) clipped at max brightness" if clipped else ""))
        finally:
            reencrypt_zone_mesh(data, s.data_start, table1, table2)
    stats["missing"] = sorted(set(wanted) - found)
    for name in stats["missing"]:
        click.echo(f"[tint] mesh '{name}' not in this DAT — skipped", err=True)
    return stats
