"""Reference items decode identically from a legacy install and a retail one.

Runs against whichever installs are configured:

* ``FFXI_LEGACY_DIR`` — a client from before the 10 September 2026 update
  (0xC00 records). Falls back to ``FFXI_DIR`` when that install is legacy.
* ``FFXI_RETAIL_DIR`` — a current retail client (0x1400 records).

Either may be missing; the tests for it skip. When both are present the
cross-install test asserts the two decode to the same names, stats and icons
for well-known items (Scorpion Harness, Kraken Club, Byakko's Haidate, …).
"""
from pathlib import Path

import pytest

from xi.ui.items import xi_layout as L
from xi.ui.items.xi_parser import ITEM_DATS, ItemDat, _parse_record

# (name, id, item_type, expected fields)
REFERENCE = [
    ("Scorpion Harness", 12579, 3, {"level": 57, "slots": 0x20, "races": 0x1FE, "jobs": 0x004B77E6}),
    ("Byakko's Haidate", 12818, 3, {"level": 75, "slots": 0x80, "races": 0x1FE, "jobs": 0x3E06}),
    ("Kraken Club", 17440, 4, {"level": 63, "slots": 0x03, "jobs": 0xFFFE, "dmg": 11, "delay": 264, "dps": 250, "skill": 11}),
    ("Excalibur", 18276, 4, {"level": 75, "slots": 0x03, "jobs": 0xA0, "dmg": 49, "delay": 233, "skill": 3}),
    ("Chocobo Bedding", 1, 0, {"flags": 0x6054, "stack": 1}),
]
DESCRIPTIONS = {
    "Kraken Club": "Occasionally attacks 2 to 8 times",
    "Scorpion Harness": "Accuracy+10 Evasion+10",
    "Byakko's Haidate": "Haste+5%",
    "Chocobo Bedding": "Furnishing:",
}

DAT_FOR_TYPE = {cat[2]: cat for cat in ITEM_DATS if cat[0] in ("Items_1", "Armor_1", "Weapons")}


def _install(env_name: str, want_fmt: str):
    import os
    d = os.environ.get(env_name)
    if not d and env_name == "FFXI_LEGACY_DIR":
        d = os.environ.get("FFXI_DIR")
    if not d or not Path(d).is_dir():
        pytest.skip(f"{env_name} not configured")
    probe = Path(d) / "ROM" / "118" / "108.DAT"
    if not probe.is_file():
        pytest.skip(f"{env_name} has no item DATs")
    fmt = L.detect_format_path(probe)
    if fmt != want_fmt:
        pytest.skip(f"{env_name} is a {fmt} install, test wants {want_fmt}")
    return Path(d)


@pytest.fixture(scope="session")
def legacy_root():
    return _install("FFXI_LEGACY_DIR", "legacy")


@pytest.fixture(scope="session")
def retail_root():
    return _install("FFXI_RETAIL_DIR", "retail")


def _load_item(root: Path, item_id: int, item_type: int):
    cat_name, base_id, _, en_rom, jp_rom = DAT_FOR_TYPE[item_type]
    en = ItemDat.load(root / en_rom)
    jp_path = root / jp_rom
    jp = ItemDat.load(jp_path) if jp_path.is_file() else None
    idx = item_id - base_id
    rec_jp = jp.record(idx) if jp is not None else None
    return en, _parse_record(item_id, en.record(idx), rec_jp, item_type, str(root / en_rom),
                             dat_ui=en_rom, fmt=en.format, record_index=idx)


def _check_reference(root: Path, fmt: str):
    for name, item_id, item_type, expect in REFERENCE:
        dat, item = _load_item(root, item_id, item_type)
        assert dat.format == fmt, f"{dat.path} detected as {dat.format}"
        assert item is not None, name
        assert item.name == name
        assert item.format == fmt
        for k, v in expect.items():
            assert getattr(item, k) == v, f"{name}.{k}: {getattr(item, k)} != {v}"
        if name in DESCRIPTIONS:
            assert DESCRIPTIONS[name] in item.description, (name, item.description)
        assert item.icon_size > 0x40 and item.icon_data[:1] == b"\x91", name  # 8-bit paletted icon
        assert item.name_jp, f"{name}: JP name missing"


def test_legacy_reference_items(legacy_root):
    _check_reference(legacy_root, "legacy")


def test_retail_reference_items(retail_root):
    _check_reference(retail_root, "retail")


def test_retail_has_colibri_scythe(retail_root):
    _, item = _load_item(retail_root, 18567, 4)
    assert item is not None and item.name == "Colibri Scythe"
    assert item.dmg == 1 and item.delay == 528 and item.skill == 7  # scythe skill
    assert item.level == 1


def test_retail_items7_table_present(retail_root):
    p = retail_root / "ROM" / "387" / "14.DAT"
    assert p.is_file()
    dat = ItemDat.load(p)
    assert dat.format == "retail" and dat.count == 1024


def test_all_item_dats_detect_one_format(legacy_root):
    """Every item DAT in an install must be readable with one stride."""
    fmts = set()
    for cat_name, base_id, item_type, en_rom, jp_rom in ITEM_DATS:
        p = legacy_root / en_rom
        if p.is_file():
            fmts.add(L.detect_format_path(p))
    assert fmts == {"legacy"}


def test_legacy_and_retail_agree(legacy_root, retail_root):
    """Same item, two installs: the decoded record must be identical apart
    from the format tag and source path (name, plural, stats, icon bytes)."""
    skip = {"format", "dat", "dat_ui", "record_index", "description", "description_jp"}
    for name, item_id, item_type, _ in REFERENCE:
        _, a = _load_item(legacy_root, item_id, item_type)
        _, b = _load_item(retail_root, item_id, item_type)
        for k, v in vars(a).items():
            if k in skip:
                continue
            assert getattr(b, k) == v, f"{name}.{k} differs: legacy={v!r} retail={getattr(b, k)!r}"
        # descriptions were re-spaced by the retail patch ("damage taken -3%" -> "Damage taken-3%")
        norm = lambda s: "".join(s.lower().split())
        assert norm(a.description) == norm(b.description), name
