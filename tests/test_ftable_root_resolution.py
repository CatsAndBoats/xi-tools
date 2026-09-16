"""File-id resolution across a DAT root's table pairs.

The client reads the base install's root ``FTABLE``/``VTABLE`` and, for a file_id
registered in a ``ROM{n}`` pair, honours that entry instead. An XIPivot overlay's
copy of the *root* pair has no effect at all, so a ``ROM{n}`` pair is the only way
an overlay can register a file_id — and it wins over the base install's root entry.

Verified in game (``!injectaction``) with a job ability, a spell and a weapon skill:
each played its custom DAT when registered only in the overlay's ``ROM10`` pair,
including over a root entry that still pointed at a retail placeholder; the same
weapon skill registered only in the overlay's root pair played the placeholder.

These tests pin that order, since the animation/model allocators pick free slots by
asking where a file_id currently resolves."""
import struct
from pathlib import Path

import pytest

from xi.ftable.xi_core import resolve_dat, resolve_dat_in_root, root_table_pair

RETAIL_ROM = 1
CUSTOM_ROM = 10


def _write_pair(root: Path, rom_idx: int, entries: dict[int, tuple[int, int]], size: int = 4096):
    """Create a table pair under ``root`` holding ``{file_id: (subdir, file_idx)}``."""
    ft, vt = (Path(p) for p in root_table_pair(root, rom_idx))
    ft.parent.mkdir(parents=True, exist_ok=True)
    fdata = bytearray(size * 2)
    vdata = bytearray(size)
    for fid, (subdir, file_idx) in entries.items():
        struct.pack_into("<H", fdata, fid * 2, (subdir << 7) | file_idx)
        vdata[fid] = rom_idx
    ft.write_bytes(bytes(fdata))
    vt.write_bytes(bytes(vdata))
    return ft, vt


def test_rom_pair_overrides_the_root_pair(tmp_path):
    _write_pair(tmp_path, RETAIL_ROM, {100: (76, 29)})
    _write_pair(tmp_path, CUSTOM_ROM, {100: (20, 65)})
    assert resolve_dat_in_root(tmp_path, 100) == ("ROM10/20/65.DAT", CUSTOM_ROM)


def test_root_pair_answers_when_the_rom_pair_has_no_entry(tmp_path):
    _write_pair(tmp_path, RETAIL_ROM, {100: (76, 29)})
    _write_pair(tmp_path, CUSTOM_ROM, {})
    assert resolve_dat_in_root(tmp_path, 100) == ("ROM/76/29.DAT", RETAIL_ROM)


def test_rom_pair_alone_is_enough(tmp_path):
    """An overlay that carries only ROM{n} tables still registers a file_id."""
    _write_pair(tmp_path, CUSTOM_ROM, {100: (20, 65)})
    assert resolve_dat_in_root(tmp_path, 100) == ("ROM10/20/65.DAT", CUSTOM_ROM)


def test_unregistered_and_missing_tables_resolve_to_nothing(tmp_path):
    assert resolve_dat_in_root(tmp_path, 100) == (None, None)
    _write_pair(tmp_path, CUSTOM_ROM, {})
    assert resolve_dat_in_root(tmp_path, 100) == (None, None)


def test_root_only_read_misses_a_rom_registration(tmp_path):
    """Why this matters: reading the root pair alone reports a live custom slot as
    free (or as its retail placeholder), so an allocator would hand it out twice."""
    _write_pair(tmp_path, RETAIL_ROM, {100: (76, 29)})
    _write_pair(tmp_path, CUSTOM_ROM, {100: (20, 65)})
    ft, vt = (Path(p) for p in root_table_pair(tmp_path, RETAIL_ROM))
    root_only, _ = resolve_dat(ft.read_bytes(), vt.read_bytes(), 100)
    assert root_only == "ROM/76/29.DAT"
    assert resolve_dat_in_root(tmp_path, 100)[0] == "ROM10/20/65.DAT"


def test_a_file_id_past_the_table_end_resolves_to_nothing(tmp_path):
    _write_pair(tmp_path, CUSTOM_ROM, {100: (20, 65)}, size=128)
    assert resolve_dat_in_root(tmp_path, 9999) == (None, None)


@pytest.mark.parametrize("rom_idx,expected", [
    (RETAIL_ROM, ("FTABLE.DAT", "VTABLE.DAT")),
    (CUSTOM_ROM, ("FTABLE10.DAT", "VTABLE10.DAT")),
])
def test_table_pair_paths(tmp_path, rom_idx, expected):
    ft, vt = (Path(p) for p in root_table_pair(tmp_path, rom_idx))
    assert (ft.name, vt.name) == expected
    assert ft.parent == (tmp_path if rom_idx == RETAIL_ROM else tmp_path / f"ROM{rom_idx}")
