"""``xi ability compose`` (xi.ability.xi_compose): the routine writer, section transplanting
with dependency walk, collision renaming, and the round trip recipe → DAT → inspect.

Install-backed tests use the ``root`` fixture and skip without FFXI_DIR."""
import struct
from pathlib import Path

import pytest

from xi.ability import xi_compose as ac
from xi.ability import xi_inspect as ai


def test_build_routine_layout_matches_retail():
    gen = bytes.fromhex("02040000000000006730303000000000")
    sec = ac.build_routine("main", [gen, gen], total=42)
    assert sec[:4] == b"main"
    meta = struct.unpack_from("<I", sec, 4)[0]
    assert meta & 0x7F == 0x07 and ((meta >> 7) & 0x7FFFF) * 16 == len(sec)
    s1, s2, s3, total = struct.unpack_from("<4I", sec, 0x20)
    assert (s1, s2, total) == (0x40, 0x50, 42)
    assert sec[s1:s1 + 4] == bytes.fromhex("00010000")
    assert sec[s2:s2 + 8] == ac._ROUTINE_START
    assert sec[s3:s3 + 4] == bytes.fromhex("00010000")
    assert len(sec) % 16 == 0


def test_stamp_patches_delay_dur_ref_and_clip_fields():
    clip = bytes.fromhex(ac._TEMPLATES[0x05].hex())
    out = ac._stamp(clip, delay=7, ev={"dur": 33, "blend": [4, 9], "loops": 2}, ref="ab0?")
    assert struct.unpack_from("<HH", out, 4) == (7, 33)
    assert out[8:12] == b"ab0?"
    assert struct.unpack_from("<H", out, 24)[0] == 4
    assert struct.unpack_from("<H", out, 28)[0] == 9
    assert struct.unpack_from("<H", out, 30)[0] == 2


def test_fresh_name_avoids_used():
    assert ac._fresh_name("g000", {"g000", "g001"}) == "g002"
    assert ac._fresh_name("g000", {"g00" + c for c in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"}).startswith("x00")


def _timeline_key(info):
    return [(e["start"], e["op"], e["ref"], e["dur"]) for e in info["timeline"]]


def test_round_trip_fast_blade(root: Path, tmp_path: Path):
    src = ai.resolve_targets("ws:1:HumeMale")[0]
    original = ai.inspect_target(src)
    recipe = ac.recipe_from("ws:1:HumeMale")
    (composed,) = ac.compose(recipe)
    p = tmp_path / "fb.DAT"
    p.write_bytes(composed.data)
    rebuilt = ai.inspect_target(ai.Target("fb", p, "fb.DAT"))
    assert _timeline_key(rebuilt) == _timeline_key(original)
    assert rebuilt["total"] == original["total"]
    assert set(rebuilt["sounds"]) == set(original["sounds"])
    assert set(rebuilt["generators"]) == set(original["generators"])
    # every referenced clip came along; unreferenced 1-frame stubs did not
    assert set(rebuilt["clips"]) == {"b000", "b001", "b020", "b021"}
    assert composed.renames == {}


def test_mixed_recipe_transplants_and_renames(root: Path):
    recipe = {
        "name": "mixtest",
        "sources": {"motion": {"spec": "ws:1:HumeMale"}, "vfx": {"spec": "spell:144"},
                    "vfx2": {"spec": "spell:145"}},        # Fire II: same g00N names as Fire
        "events": [
            {"from": "motion", "op": 5, "ref": "b00?", "start": 10, "dur": 35},
            {"from": "vfx", "op": 2, "ref": "g003", "start": 60, "dur": 80},
            {"from": "vfx2", "op": 2, "ref": "g003", "start": 60, "dur": 80},
            {"from": "motion", "op": 10, "ref": "8050", "start": 60},
        ],
    }
    (c,) = ac.compose(recipe)
    assert c.race is None
    assert any(k.startswith("vfx2:g003") for k in c.renames), c.renames
    refs = [t["ref"] for t in c.timeline if t["op"] == 2]
    assert "g003" in refs and c.renames["vfx2:g003"] in refs
    names = {s.split("(")[0] for s in c.sections}
    assert {"b000", "b001", "8050", "g003", "main"} <= names
    assert any(s.endswith("(0x20)") for s in c.sections)      # a texture dependency came along


def test_race_bound_recipe_composes_per_race(root: Path):
    recipe = {"name": "rb", "sources": {"motion": {"spec": "ws:1"}},
              "events": [{"from": "motion", "op": 5, "ref": "b00?", "start": 0, "dur": 35}]}
    out = ac.compose(recipe, race="Mithra")
    assert [c.race for c in out] == ["Mithra"]
    assert ac.output_name(recipe, out[0]) == "rb.Mithra.DAT"
