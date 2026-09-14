"""`xi anim export --categories` folder naming — no game files needed."""

import json
from pathlib import Path

import pytest

from xi.entity.anim import xi_categories as xc
from xi.entity.anim.xi_categories import MotionCategories, rom_key, snake


@pytest.mark.parametrize('label, expected', [
    ('Battle: Club / Staff', 'battle_club_staff'),
    ("Rudra's Storm", 'rudras_storm'),
    ('G. Sword', 'g_sword'),
    ('Hand-to-hand', 'hand_to_hand'),
    ('WS (Unreleased)', 'ws_unreleased'),
    ('Hume Male', 'hume_male'),
    ('weaponSkillExt', 'weapon_skill_ext'),
    ('TaruMale', 'taru_male'),
    ('', 'unnamed'),
])
def test_snake(label, expected):
    assert snake(label) == expected


def test_rom_key_normalises_separators_case_and_suffix():
    assert rom_key('ROM\\27\\82.DAT') == 'ROM/27/82'
    assert rom_key('rom/27/82') == 'ROM/27/82'
    assert rom_key('ROM2/9/14.dat') == 'ROM2/9/14'


@pytest.fixture
def cats(tmp_path, monkeypatch):
    lists = tmp_path / 'characters.json'
    lists.write_text(json.dumps({'races': [
        {'id': 'HumeM', 'label': 'Hume Male', 'actions': [
            {'group': 'Basic', 'label': 'Basic', 'paths': ['ROM\\27\\82.DAT']},
            {'group': 'General', 'label': '66 Schedules', 'paths': ['ROM\\27\\82.DAT']},
            {'group': 'Battle', 'label': 'Battle: Club / Staff', 'paths': ['ROM\\32\\13.DAT']},
            {'group': 'Sword', 'label': 'Fast Blade', 'paths': ['ROM\\76\\30.DAT']},
            {'group': 'Sword', 'label': 'Swift Blade', 'paths': ['ROM\\100\\18.DAT'],
             'motionPaths': ['ROM\\100\\77.DAT']},
            {'group': 'Sword', 'label': 'Savage Blade', 'paths': ['ROM\\100\\19.DAT'],
             'motionPaths': ['ROM\\100\\77.DAT']},
        ]},
        {'id': 'Galka', 'label': 'Galka', 'actions': [
            {'group': 'Emote', 'label': 'Emote', 'paths': ['ROM\\61\\8.DAT']},
        ]},
    ]}), encoding='utf-8')
    game = tmp_path / 'game'
    game.mkdir()
    monkeypatch.setattr(xc, 'FFXI_DIR', str(game))
    c = MotionCategories(lists)
    # No FFXiMain.dll here: the DLL fallback must stay out of the picture.
    monkeypatch.setattr(c, '_load_tables', lambda: {})
    return c, game


def test_named_rows_win_first_match(cats):
    c, game = cats
    assert c.dir_for(game / 'ROM/27/82.DAT') == Path('hume_male/basic/basic')
    assert c.dir_for(game / 'ROM/32/13.DAT') == Path('hume_male/battle/battle_club_staff')
    assert c.dir_for(game / 'ROM/76/30.DAT') == Path('hume_male/sword/fast_blade')
    assert c.dir_for(game / 'ROM/61/8.DAT') == Path('galka/emote/emote')


def test_companion_only_dat_keeps_its_rom_id(cats):
    c, game = cats
    assert c.dir_for(game / 'ROM/100/77.DAT') == Path('hume_male/sword/rom_100_77')


def test_race_for_maps_viewer_ids_to_xi_names(cats):
    c, game = cats
    assert c.race_for(game / 'ROM/76/30.DAT') == 'HumeMale'
    assert c.race_for(game / 'ROM/61/8.DAT') == 'Galka'
    assert c.race_for(game / 'ROM/5/3.DAT') is None


def test_unknown_dat_goes_under_other(cats):
    c, game = cats
    assert c.dir_for(game / 'ROM/5/3.DAT') == Path('other/rom/5/3')
    assert c.dir_for(game / 'ROM/5/3.DAT', fallback=('HumeMale', 'weaponSkill')) \
        == Path('hume_male/weapon_skill/rom_5_3')
    assert c.dir_for(Path('C:/elsewhere/42.DAT')) == Path('other/42')


def test_missing_list_is_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(xc, 'FFXI_DIR', str(tmp_path))
    c = MotionCategories(tmp_path / 'nope.json')
    monkeypatch.setattr(c, '_load_tables', lambda: {})
    assert c.dir_for(tmp_path / 'ROM/1/2.DAT') == Path('other/rom/1/2')
