"""Folder names for ``xi anim export --categories``.

A motion DAT lands under ``<race>/<category>/<action>/`` — ``hume_male/sword/fast_blade``,
``galka/emote/emote``, ``mithra/battle/battle_club_staff`` — instead of its ROM path.
Names come from two places, in order:

1. The viewer's character list (``mv/lists/characters.json``): per race, every action
   row's DATs with the row's group and label. This is where the human names live
   (weapon-skill names, "Battle: Sword", "Fishing").
2. The FFXiMain.dll motion tables (:mod:`xi_motion_tables`): race + category + slot
   for any PC motion DAT the list doesn't name.

Anything else (a monster, an NPC, a DAT outside FFXI_DIR) goes under ``other/``.
"""

import json
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from xi.xi_config import FFXI_DIR, XI_TOOLS_DIR

CHARACTERS_LIST = Path(XI_TOOLS_DIR) / 'mv' / 'lists' / 'characters.json'

# Viewer race id -> xi race name (the base skeleton an animation-only DAT rigs
# onto). Tarutaru share one skeleton; mounts and child NPCs carry their own.
_LIST_RACE_TO_XI = {
    'HumeM': 'HumeMale', 'HumeF': 'HumeFemale', 'ElvaanM': 'ElvaanMale',
    'ElvaanF': 'ElvaanFemale', 'Tarutaru': 'TaruMale', 'Mithra': 'Mithra', 'Galka': 'Galka',
}


def snake(label: str) -> str:
    """``'Battle: Club / Staff'`` → ``battle_club_staff``; ``'weaponSkillExt'`` →
    ``weapon_skill_ext``; ``"Rudra's Storm"`` → ``rudras_storm``."""
    s = str(label or '').replace("'", '').replace('’', '')
    s = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', s)
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_').lower()
    return s or 'unnamed'


def rom_key(spec) -> str:
    """Canonical key for a DAT spec: ``ROM/27/82`` (upper, forward slashes, no .DAT)."""
    s = str(spec).replace('\\', '/').strip('/')
    s = re.sub(r'\.DAT$', '', s, flags=re.I)
    return s.upper()


def rom_key_for_path(dat_path: Path) -> Optional[str]:
    """``rom_key`` of a DAT under FFXI_DIR, else None."""
    try:
        rel = Path(dat_path).resolve().relative_to(Path(FFXI_DIR).resolve())
    except (ValueError, OSError):
        return None
    return rom_key(rel.as_posix())


class MotionCategories:
    """Resolves a DAT to its ``race/category/action`` folder. Built lazily: the
    character list is read on first use, the DLL tables only if a DAT falls
    through it."""

    def __init__(self, lists_path: Optional[Path] = None):
        self._lists_path = Path(lists_path) if lists_path else CHARACTERS_LIST
        self._named: Optional[Dict[str, Tuple[str, str, str]]] = None
        self._tables: Optional[Dict[str, Tuple[str, str, str]]] = None
        self._race: Dict[str, Optional[str]] = {}   # key -> xi race name

    # -- character list ---------------------------------------------------------

    def _load_named(self) -> Dict[str, Tuple[str, str, str]]:
        if self._named is not None:
            return self._named
        named: Dict[str, Tuple[str, str, str]] = {}
        companions: Dict[str, Tuple[str, str, Optional[str]]] = {}
        try:
            data = json.loads(self._lists_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        for race in data.get('races') or []:
            race_name = snake(race.get('label') or race.get('id') or '')
            xi_race = _LIST_RACE_TO_XI.get(str(race.get('id') or ''))
            for action in race.get('actions') or []:
                group = snake(action.get('group') or 'other')
                label = snake(action.get('label') or '')
                # A row's own DATs take its name. A DAT that is only ever a
                # companion (the shared waist block of a dozen weapon skills)
                # belongs to no one row, so it keeps its ROM id as the action.
                for p in action.get('paths') or []:
                    if named.setdefault(rom_key(p), (race_name, group, label))[0] == race_name:
                        self._race.setdefault(rom_key(p), xi_race)
                for p in action.get('motionPaths') or []:
                    companions.setdefault(rom_key(p), (race_name, group, xi_race))
        for key, (race_name, group, xi_race) in companions.items():
            if key not in named:
                named[key] = (race_name, group, 'rom_' + '_'.join(key.split('/')[1:]).lower())
                self._race.setdefault(key, xi_race)
        self._named = named
        return named

    # -- DLL motion tables ------------------------------------------------------

    def _load_tables(self) -> Dict[str, Tuple[str, str, str]]:
        if self._tables is not None:
            return self._tables
        tables: Dict[str, Tuple[str, str, str]] = {}
        try:
            from xi.entity.anim.xi_motion_tables import (
                RACE_NAMES, WS_EXTENDED_FIRST, WS_EXTENDED_SLOTS, WS_PRIMARY_SLOTS,
                _FileIdResolver, _window_sizes, category_bases, load_maindll,
            )
            cat_bases = category_bases(load_maindll())
            windows = _window_sizes(cat_bases)
            resolver = _FileIdResolver()
        except Exception:
            self._tables = tables
            return tables
        for ri, race in enumerate(RACE_NAMES):
            for cat, bases in cat_bases.items():
                for off in range(windows[cat]):
                    spec = resolver.rom_spec(bases[ri] + off)
                    if not spec:
                        continue
                    # Weapon-skill windows are body + two companion blocks of the
                    # same slots; name all three by the animation number so a
                    # skill's body and waist clips share a folder.
                    if cat == 'weaponSkill':
                        action = f'ws{off % WS_PRIMARY_SLOTS:03d}'
                    elif cat == 'weaponSkillExt':
                        action = f'ws{WS_EXTENDED_FIRST + off % WS_EXTENDED_SLOTS:03d}'
                    else:
                        action = f'slot{off:02d}'
                    if rom_key(spec) not in tables:
                        tables[rom_key(spec)] = (snake(race), snake(cat), action)
                        self._race.setdefault(rom_key(spec), race)
        self._tables = tables
        return tables

    # -- lookup -----------------------------------------------------------------

    def lookup(self, key: str) -> Optional[Tuple[str, str, str]]:
        """``(race, category, action)`` for a ``rom_key``, or None if nothing
        names it."""
        hit = self._load_named().get(key)
        if hit is None:
            hit = self._load_tables().get(key)
        return hit

    def race_for(self, dat_path: Path) -> Optional[str]:
        """The PC race (xi name, e.g. ``HumeMale``) whose motion set a DAT belongs
        to, or None. A base skeleton for animation-only DATs the ROM-id heuristic
        in :func:`xi_export.detect_race_from_dat` doesn't know (weapon skills,
        job emotes, ...)."""
        key = rom_key_for_path(dat_path)
        if key is None or self.lookup(key) is None:
            return None
        return self._race.get(key)

    def dir_for(self, dat_path: Path,
                fallback: Optional[Tuple[str, str]] = None) -> Path:
        """Relative output folder for a DAT: ``race/category/action``. A DAT
        nothing names goes under ``<race>/<category>/rom_<dir>_<file>`` when the
        caller knows those (bulk export), else ``other/rom/<dir>/<file>``; a DAT
        outside FFXI_DIR under ``other/<stem>``."""
        key = rom_key_for_path(dat_path)
        if key is None:
            return Path('other') / Path(dat_path).stem
        hit = self.lookup(key)
        if hit is not None:
            return Path(*hit)
        parts = key.lower().split('/')
        if fallback is not None:
            return Path(snake(fallback[0])) / snake(fallback[1]) / ('rom_' + '_'.join(parts[1:]))
        return Path('other', *parts)
