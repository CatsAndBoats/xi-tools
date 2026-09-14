"""The manifest is the publish step: it must refuse a list that does not parse."""

import json
from pathlib import Path

import pytest

from xi.mv import update_lists as ul


def test_manifest_indexes_every_parsable_list(tmp_path: Path):
    (tmp_path / "a.json").write_text('{"x": 1}\n', encoding="utf-8")
    (tmp_path / "b.json").write_text("[1, 2]\n", encoding="utf-8")
    rep = ul.write_manifest(tmp_path)
    assert rep["wrote"] and not rep.get("error")
    m = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert set(m["files"]) == {"a.json", "b.json"}
    assert m["files"]["a.json"]["bytes"] == (tmp_path / "a.json").stat().st_size


def test_manifest_refuses_a_broken_list(tmp_path: Path):
    (tmp_path / "good.json").write_text("[]\n", encoding="utf-8")
    ul.write_manifest(tmp_path)
    before = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    (tmp_path / "bad.json").write_text('{"x": 1}\n{"y": 2}\n', encoding="utf-8")
    rep = ul.write_manifest(tmp_path)
    assert not rep["wrote"]
    assert "bad.json" in rep["error"] and "not published" in rep["error"]
    assert (tmp_path / "manifest.json").read_text(encoding="utf-8") == before


def test_write_json_reads_back_what_it_wrote(tmp_path: Path):
    out = tmp_path / "list.json"
    ul._write_json(out, {"rows": [1, 2, 3]}, dry_run=False, indent=1)
    assert json.loads(out.read_text(encoding="utf-8")) == {"rows": [1, 2, 3]}


def test_write_json_rejects_unserialisable_data(tmp_path: Path):
    out = tmp_path / "list.json"
    with pytest.raises((TypeError, RuntimeError)):
        ul._write_json(out, {"when": object()}, dry_run=False, indent=1)
