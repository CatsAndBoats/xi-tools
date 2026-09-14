"""``xi ability publish`` — put a composed ability into the custom ROM10 namespace.

    xi ability publish recipe.json [--target pivot|dir] [--animation N] [--subdir S] [--dry-run]

Steps: compose the recipe (one DAT, or one per race for a race-bound recipe), pick the
animation number the server will send, place the DAT(s) under ``ROM10/<subdir>/<n>.DAT``
in the target root, register the file id(s) in that root's FTABLE/VTABLE + ROM10 overlay
tables (``xi dats`` placement, ``.base`` backups), save the recipe beside the output, and
print the server row to add.

Kinds and where the client looks (docs/ability/inspect.md, docs/anim/weapon-skills.md):

    ja     file_id = 4412 + animation      retail band 4412..4750 is full; custom = 339+
    spell  file_id = 0xAF0 + animation     retail animations reach 1011; custom = 1012+,
                                           only unregistered ids (others live in between)
    ws     per-race extended bank slots    256..271; 264..271 are dummies on retail
           (body + companion A at +16 + companion B at +32, all per race)

The client has no spell table of its own: ``spell_list.animation`` rides in the action
packet (category 4, magic finish) and the client opens file id 0xAF0 + that number — the
same file-table lookup a job ability uses, so a new spell is a new registered id.

A recipe whose motion lane is a weapon skill (``ws:N``) carries per-race clips and must be
published as ``ws``; a spell motion (``spell:N``) publishes as ``spell``; everything else is
a job ability. ``target.kind`` in the recipe overrides the inference.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import click

from xi.ability.xi_compose import Composed, _lanes, compose, load_recipe, output_name
from xi.ability.xi_inspect import ABILITY_FILE_OFFSET
from xi.entity.anim.xi_motion_tables import RACE_NAMES, race_index, resolve_weapon_skill
from xi.ftable.xi_core import resolve_dat

JA_CUSTOM_FIRST = 339           # first animation number past the retail band
JA_CUSTOM_LAST = 499            # 4412 + 499 = 4911, just below the weapon-skill VFX band
WS_CUSTOM_FIRST, WS_CUSTOM_LAST = 264, 271
# Spells: file_id = 0xAF0 + animation (xi.spell FILE_TABLE_OFFSET). Retail animations run
# 0..1011; the ids above are shared with other content, so only unregistered ones are
# taken (92 free up to 1611, where the job-ability band starts at 4412).
SPELL_FILE_OFFSET = 0xAF0
SPELL_CUSTOM_FIRST = 1012
SPELL_CUSTOM_LAST = 1611

# (file-id offset, first custom number, last, what the server column is called)
_SINGLE_DAT_KINDS = {
    "ja": (ABILITY_FILE_OFFSET, JA_CUSTOM_FIRST, JA_CUSTOM_LAST, "abilities.animation"),
    "spell": (SPELL_FILE_OFFSET, SPELL_CUSTOM_FIRST, SPELL_CUSTOM_LAST, "spell_list.animation"),
}
DEFAULT_SUBDIR = 20


def _root(target: str) -> Path:
    from xi.dats.xi_dats import _target_root
    return _target_root(target)


def _placement(root: Path, file_id: int) -> Optional[str]:
    ft, vt = root / "FTABLE.DAT", root / "VTABLE.DAT"
    if not ft.exists() or not vt.exists():
        raise click.ClickException(f"{root} has no FTABLE.DAT/VTABLE.DAT — not a DAT root")
    dat, _ = resolve_dat(ft.read_bytes(), vt.read_bytes(), file_id)
    return dat


def _is_dummy(root: Path, rel: Optional[str]) -> bool:
    """A retail placeholder slot: the DAT exists and carries a ``dumm`` directory."""
    if not rel:
        return True
    from xi.xi_config import FFXI_DIR
    for base in (root, Path(FFXI_DIR)):
        p = base / rel
        if p.exists():
            return b"dumm" in p.read_bytes()[:4096]
    return True


def _kind(recipe: dict) -> str:
    kind = (recipe.get("target") or {}).get("kind")
    race_bound = any(l.race_bound for l in _lanes(recipe).values())
    motion_spec = str(((recipe.get("sources") or {}).get("motion") or {}).get("spec") or "")
    if kind is None:
        kind = "ws" if race_bound else ("spell" if motion_spec.startswith("spell:") else "ja")
    if race_bound and kind != "ws":
        raise click.ClickException(
            "this recipe carries per-race motion clips (a ws: lane), so it must be published "
            "as kind 'ws' — a job-ability or spell slot is one DAT for every skeleton")
    if kind not in ("ja", "spell", "ws"):
        raise click.ClickException(f"unsupported target kind {kind!r} (ja, spell or ws)")
    return kind


def _pick_animation(root: Path, kind: str, wanted: Optional[int], force: bool) -> int:
    if kind in _SINGLE_DAT_KINDS:
        offset, first, last, _col = _SINGLE_DAT_KINDS[kind]
        cands = [wanted] if wanted is not None else range(first, last + 1)
        for n in cands:
            fid = offset + n
            if _placement(root, fid) is None or force:
                return n
        if wanted is not None:
            raise click.ClickException(
                f"{kind} animation {wanted} (file id {offset + wanted}) is already "
                f"registered to {_placement(root, offset + wanted)}; pass --force to repoint it")
        raise click.ClickException(f"no free {kind} animation number between {first} and {last}")
    cands = [wanted] if wanted is not None else range(WS_CUSTOM_FIRST, WS_CUSTOM_LAST + 1)
    for n in cands:
        slots = resolve_weapon_skill(n)
        if force or all(_is_dummy(root, _placement(root, s.file_id)) for s in slots):
            return n
    raise click.ClickException(
        "no weapon-skill extended slot is free (a slot is free when every race's body DAT is "
        "a retail dummy); pass --animation N --force to overwrite one")


def _free_files(root: Path, subdir: int, count: int) -> List[int]:
    used = set()
    d = root / "ROM10" / str(subdir)
    if d.exists():
        used = {int(p.stem) for p in d.glob("*.DAT") if p.stem.isdigit()}
    free = [i for i in range(128) if i not in used]
    if len(free) < count:
        raise click.ClickException(f"ROM10/{subdir} has only {len(free)} free file numbers, need {count}")
    return free[:count]


def _ws_file_ids(animation: int, race: str) -> Dict[str, int]:
    s = resolve_weapon_skill(animation, race)[0]
    return {"body": s.file_id, "companion_a": s.companion_a, "companion_b": s.companion_b}


def _source_ws_animation(recipe: dict) -> Optional[int]:
    for lane in _lanes(recipe).values():
        if lane.race_bound:
            return int(lane.spec.split(":")[1])
    return None


def plan(recipe: dict, target: str, animation: Optional[int], subdir: int, force: bool) -> dict:
    root = _root(target)
    kind = _kind(recipe)
    composed = compose(recipe)
    if kind in _SINGLE_DAT_KINDS and any(s.endswith("(0x2B)") for c in composed for s in c.sections):
        raise click.ClickException(
            "this recipe carries skeleton clips, which are one race's; a job-ability or spell "
            "slot is one DAT for every race. Use a ws: lane (published per race) or motion the "
            "actor already has (cm0?, ma2?...)")
    anim = _pick_animation(root, kind, animation, force)
    files: List[dict] = []
    if kind in _SINGLE_DAT_KINDS:
        offset = _SINGLE_DAT_KINDS[kind][0]
        (c,) = composed
        (n,) = _free_files(root, subdir, 1)
        files.append({"race": None, "role": "body", "file_id": offset + anim,
                      "place": f"ROM10/{subdir}/{n}.DAT", "composed": c})
    else:
        src_anim = _source_ws_animation(recipe)
        from xi.xi_config import FFXI_DIR
        from xi.ftable.xi_core import scan_file_ids
        nums = _free_files(root, subdir, 3 * len(composed))
        seen_ids: set = set()
        for c in composed:
            ids = _ws_file_ids(anim, c.race)
            if ids["body"] in seen_ids:          # Taru male/female share one bank row
                continue
            seen_ids.add(ids["body"])
            n_body, n_a, n_b = nums[:3]
            nums = nums[3:]
            files.append({"race": c.race, "role": "body", "file_id": ids["body"],
                          "place": f"ROM10/{subdir}/{n_body}.DAT", "composed": c})
            # Companion (waist) DATs come from the motion source's slot for the same race.
            src_ids = _ws_file_ids(src_anim, c.race)
            for role, n in (("companion_a", n_a), ("companion_b", n_b)):
                hits = scan_file_ids([src_ids[role]])
                if not hits:
                    raise click.ClickException(f"cannot resolve source companion {role} for {c.race}")
                files.append({"race": c.race, "role": role, "file_id": ids[role],
                              "place": f"ROM10/{subdir}/{n}.DAT",
                              "copy_from": Path(FFXI_DIR) / hits[0]["dat"]})
    return {"root": root, "kind": kind, "animation": anim, "subdir": subdir, "files": files}


def apply(recipe: dict, p: dict, force: bool) -> List[dict]:
    from xi.dats.xi_dats import _place_raw_dat_in_build, _set_target_root
    out_dir = Path("exports") / "ability" / recipe["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    _set_target_root(p["root"])
    try:
        for f in p["files"]:
            if "composed" in f:
                c: Composed = f["composed"]
                src = out_dir / output_name(recipe, c)
                src.write_bytes(c.data)
            else:
                src = out_dir / f"{recipe['name']}.{f['race']}.{f['role']}.DAT"
                shutil.copy2(f["copy_from"], src)
            # plan() already applied the slot policy (free job-ability ids; weapon-skill
            # slots only where every race's DAT is a retail dummy, or --force), so the
            # placement's own collision guard — which would refuse to repoint a dummy —
            # is bypassed here.
            r = _place_raw_dat_in_build(src, f["place"], f["file_id"], force=True,
                                        action_id=f"ability:{recipe['name']}")
            r.update({"race": f["race"], "role": f["role"]})
            results.append(r)
    finally:
        _set_target_root(None)
    recipe_out = dict(recipe)
    recipe_out["target"] = {"kind": p["kind"], "animation": p["animation"]}
    (out_dir / f"{recipe['name']}.recipe.json").write_text(json.dumps(recipe_out, indent=2), encoding="utf-8")
    (out_dir / f"{recipe['name']}.published.json").write_text(
        json.dumps({"kind": p["kind"], "animation": p["animation"], "root": str(p["root"]),
                    "files": results}, indent=2), encoding="utf-8")
    return results


def server_snippet(recipe: dict, kind: str, animation: int) -> str:
    name = recipe["name"]
    if kind == "spell":
        return (f"-- in-game check, no DB change: target a mob or NPC and   !injectaction 4 {animation}\n"
                f"-- spell: point a spell_list row at the new animation (the client opens file id 0xAF0 + {animation})\n"
                f"UPDATE spell_list SET animation = {animation}, animationTime = 2000 WHERE name = '{name}';\n"
                f"-- or a new row (spellid, name, jobs, group, family, element, zonemisc, validTargets, skill, mpCost,\n"
                f"--   castTime, recastTime, message, magicBurstMessage, animation, animationTime, AOE, base, multiplier,\n"
                f"--   CE, VE, requirements, spell_range, radius, content_tag):\n"
                f"-- INSERT INTO spell_list VALUES (<spellid>,'{name}',<jobs>,<group>,<family>,<element>,0,<validTargets>,<skill>,\n"
                f"--   <mpCost>,<castTime>,<recastTime>,<msg>,<burstMsg>,{animation},2000,0,0,1.00,0,0,0,<range>,0,NULL);")
    if kind == "ja":
        return (f"-- in-game check, no DB change: target a mob or NPC and   !injectaction 6 {animation}\n"
                f"-- job ability: point an abilities row at the new animation\n"
                f"UPDATE abilities SET animation = {animation}, animationTime = 2000 WHERE name = '{name}';\n"
                f"-- or a new row: INSERT INTO abilities VALUES (<abilityId>,'{name}',<job>,<level>,<validTarget>,"
                f"<recast>,<recastId>,<msg1>,<msg2>,{animation},2000,0,0,0,0,0,1,0,0,0,NULL);")
    return (f"-- in-game check, no DB change: target a mob or NPC and   !injectaction 3 {animation}\n"
            f"-- humanoid mob skill (mob_anim_id is 16-bit, works today):\n"
            f"--   INSERT INTO mob_skills VALUES (<id below 256>,{animation},'{name}',0,0.0,5.0,2000,0,4,0,0,0,8,0,0);\n"
            f"-- player weapon skill: weapon_skills.animation is tinyint and the loader reads it as uint8\n"
            f"--   (src/map/utils/battleutils.cpp get<uint8>(\"animation\")), so {animation} needs the column\n"
            f"--   widened (ALTER TABLE weapon_skills MODIFY animation smallint unsigned NOT NULL DEFAULT 0)\n"
            f"--   and a one-line cpp-patch to get<uint16> — then:\n"
            f"--   UPDATE weapon_skills SET animation = {animation} WHERE name = '{name}';")


@click.command("publish")
@click.argument("recipe_path", type=click.Path(exists=True, path_type=Path))
@click.option("--target", type=click.Choice(["pivot", "dir"]), default="pivot", show_default=True,
              help="pivot = FFXI_PIVOT_DIR overlay (custom content), dir = the game folder itself.")
@click.option("--animation", type=int, default=None, help="Animation number to use (default: next free).")
@click.option("--subdir", type=int, default=DEFAULT_SUBDIR, show_default=True, help="ROM10 folder to place DATs in.")
@click.option("--force", is_flag=True, help="Repoint a file id that is already registered.")
@click.option("--dry-run", is_flag=True, help="Show the plan; write nothing.")
def publish_cmd(recipe_path: Path, target: str, animation: Optional[int], subdir: int,
                force: bool, dry_run: bool):
    """Compose RECIPE_PATH and install it into ROM10 with a new animation number."""
    recipe = load_recipe(recipe_path)
    p = plan(recipe, target, animation, subdir, force)
    click.echo(f"target root : {p['root']}")
    click.echo(f"kind        : {p['kind']}   animation {p['animation']}")
    for f in p["files"]:
        who = f"{f['race'] or 'all races'} {f['role']}"
        cur = _placement(p["root"], f["file_id"])
        click.echo(f"  file_id {f['file_id']:>6}  {who:<26} -> {f['place']}"
                   + (f"   (was {cur})" if cur else ""))
    if dry_run:
        click.echo("\n[DRY RUN] nothing written.")
        click.echo(server_snippet(recipe, p["kind"], p["animation"]))
        return
    try:
        results = apply(recipe, p, force)
    except PermissionError as e:
        raise click.ClickException(
            f"cannot write {e.filename}: the target's file tables are owned by another account "
            "(a launcher or updater that ran elevated). Either run this command from an "
            "elevated terminal, or grant yourself modify rights on the overlay once:\n"
            f'  icacls "{p["root"]}" /grant "%USERNAME%":(OI)(CI)M /T\n'
            "Nothing was registered; any DAT already copied is unreferenced and harmless.")
    click.echo(f"\nwrote {len(results)} DAT(s) and registered them; recipe + report under exports/ability/{recipe['name']}/")
    click.echo("restart the client (it caches the file tables at startup), then:")
    click.echo(server_snippet(recipe, p["kind"], p["animation"]))
