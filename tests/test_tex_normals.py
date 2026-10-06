"""`xi tex normals`: the DXT decode, the dump matching and the BC5 / DDS writer (synthetic bytes)."""

import struct

import numpy as np

from xi.tex import xi_normals as n


def _dxt1_block(c0, c1, idx):
    return struct.pack("<HHI", c0, c1, idx)


def test_decode_dxt1_solid_colour():
    # c0 = pure red in 565, every texel index 0
    img = n.decode_dxt(_dxt1_block(0xF800, 0x0000, 0) * 4, 8, 8, dxt3=False)
    assert img.shape == (8, 8, 4)
    assert tuple(img[0, 0]) == (255, 0, 0, 255) and tuple(img[7, 7]) == (255, 0, 0, 255)


def test_decode_dxt3_alpha_nibbles():
    block = bytes([0xF0] * 8) + _dxt1_block(0xFFFF, 0, 0)  # alpha 0 then 15 per texel pair
    img = n.decode_dxt(block, 4, 4, dxt3=True)
    assert img[0, 0, 3] == 0 and img[0, 1, 3] == 255 and tuple(img[0, 0, :3]) == (255, 255, 255)


def test_match_and_write(tmp_path):
    rng = np.random.default_rng(1)
    tex = rng.integers(0, 255, (64, 64, 4), dtype=np.uint8)
    other = rng.integers(0, 255, (64, 64, 4), dtype=np.uint8)
    dump = tmp_path / "dump"
    dump.mkdir()
    (dump / "00000000000000aa.bin").write_bytes(tex[..., [2, 1, 0, 3]].tobytes())  # D3DFMT_A8R8G8B8
    (dump / "index.txt").write_text(f"00000000000000aa 64x64 {n.FMT_ARGB:08x}\n")
    r = n.match_dump(dump, [("wall", tex), ("floor", other)])
    assert r["matched"] == [("00000000000000aa", 64, 64, "wall")] and not r["unmatched"]
    r = n.match_dump(dump, [("floor", other)])
    assert not r["matched"] and len(r["unmatched"]) == 1


def test_dds_bc5_header_and_size():
    dds = n.dds_bc5(n.flat_normal(64, 32))
    assert dds[:4] == b"DDS " and dds[84:88] == b"ATI2"
    h, w, size, _, mips = struct.unpack_from("<IIIII", dds, 12)
    assert (h, w, mips) == (32, 64, 7) and size == 64 * 32
    assert len(dds) == 128 + sum(max(1, (64 >> i) // 4) * max(1, (32 >> i) // 4) * 16 for i in range(7))


def test_bc5_flat_normal_round_trips():
    blocks = n.encode_bc5(np.full((4, 4, 2), 128, np.uint8))
    assert blocks[0] == 128 and blocks[1] == 128 and blocks[8] == 128
