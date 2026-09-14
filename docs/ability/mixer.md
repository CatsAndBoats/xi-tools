# Ability Mixer — recipe, compose, publish, catalog

Build a new ability presentation from pieces of retail ones: the motion of one, the
effects of another, the sound of a third. The xi-model-viewer's **Ability Mixer** mode
is the UI; these are the commands it drives, usable on their own.

```bash
uv run xi ability recipe ws:1:HumeMale --out fb.json     # starter recipe from one source
uv run xi ability compose recipe.json [--out DIR] [--race Mithra] [--json]
uv run xi ability publish recipe.json [--target pivot|dir] [--animation N] [--subdir 20] [--dry-run]
uv run xi ability catalog [--out exports/ability/catalog.json] [--kinds ja,spell,ws]
```

## Recipe

```jsonc
{
  "name": "tiger_fury",
  "sources": {
    "motion": { "spec": "ws:1",      "routine": "main" },   // race-bound: one DAT per race
    "vfx":    { "spec": "spell:144", "routine": "main" },
    "sound":  { "spec": "ja:33",     "routine": "main" }
  },
  "events": [
    { "from": "motion", "op": 5,  "ref": "b00?", "start": 10, "dur": 35, "blend": [20, 0], "loops": 1 },
    { "from": "motion", "op": 44, "ref": "b0a?", "start": 55, "dur": 70 },
    { "from": "vfx",    "op": 2,  "ref": "g004", "start": 60, "dur": 100 },
    { "from": "sound",  "op": 2,  "ref": "g0s0", "start": 60 },
    { "from": "motion", "op": 3,  "ref": "mdam", "start": 100 }
  ]
}
```

- **`sources`** — one lane per name; `spec` is anything `xi ability inspect` accepts.
  A `ws:N` spec without a race is *race-bound*: the recipe composes once per race.
- **`events`** — one command each in the new `main` routine. `start` is the absolute
  frame (the writer turns it back into the format's relative delays). `dur`, `blend`
  (`[in, out]`) and `loops` patch the command's fields; anything else in the command is
  the source's own bytes. Give `raw` (hex from `inspect --json`) or `routine` +
  `offset` to pin an exact source command; otherwise the first command in the lane's
  routine with the same `op` and `ref` is used, and a handful of ops have templates.
- Commands with no ref (locks, flinch) are copied verbatim.

## Compose

`compose` gathers, for every event, the sections its command names from that lane's
DAT: generators plus their textures, sprite sheets, meshes, curves and sound pointers
(the `xi fx copy --from` walk); sound pointers; clips and weapon traces matching the
ref (wildcards included); locally linked routines, recursively. Two sources naming the
same section differently get the later one **renamed** (`g003` → `g004`…) and every
reference in that source's copied generators and routines patched; the report lists
the renames. Then it writes one directory holding everything and a fresh `main` routine
laid out like retail (sec1 end marker, sec2 start + commands + end, sec3 end marker,
`totalDelay` = the routine's end: the source's own total when the recipe came from
`xi ability recipe`, else the last event's start + duration; each command's delay is
the gap to the next, and the first start rides on the start marker).

Output: `exports/ability/<name>/<name>[.<Race>].DAT` and a `<name>.report.json` with
sections, renames and the absolute-frame timeline. Round trip is proven in
`tests/test_ability_compose.py`: a recipe made by `xi ability recipe` from Fast Blade
composes back to the same timeline the inspector reads from the retail DAT.

A referenced generator or sound pointer that the lane's DAT does not have is an
error, not a silent drop.

## Publish

Puts the composed DAT(s) into the **ROM10** custom namespace of the target root
(`--target pivot` = `FFXI_PIVOT_DIR`, the DAT override tree the loader layers over the
game; `dir` = the game folder) and registers the file id(s) the client will look up — the same placement and
table patching `xi dats build` uses, with `.base` backups.

| Kind | When | Client lookup | Custom numbers | Server |
|---|---|---|---|---|
| `ja` | no lane is race-bound and no clips are carried | `file_id = 4412 + animation` | first free from **339** (retail band 4412–4750 is full) | `abilities.animation` |
| `spell` | the motion lane is a `spell:N` (or `target.kind` says so); one DAT for every race | `file_id = 0xAF0 + animation` — the client has no spell table, `spell_list.animation` rides in the magic-finish action packet | first **unregistered** id from **1012** (retail reaches 1011; the ids above are shared with other content, 92 free up to 1611) | `spell_list.animation` |
| `ws` | a lane is `ws:N` (per-race clips) | per-race extended bank, slots 256–271 | first slot whose body DAT is a retail dummy on every race (**264–271**) | `weapon_skills.animation`, or a `mob_skills` row with id < 256 |

For `ws`, the three DATs per race (body + companion A/B waist packs) are placed and
registered; the companions are copied from the motion source's own slot for that race.
Tarutaru male and female share one bank row and are registered once.

`--dry-run` prints the plan: target root, kind, animation number, every file id with
its current occupant, and the SQL to add. The mixer shows this plan before it asks to
confirm. **Restart the client** after publishing — it caches the file tables at
startup.

The client accepts custom numbers of all three kinds from the ROM10 overlay: job abilities
past retail's 338, weapon skills in the extended slots, and spell animations past 1011.
The quickest in-game check needs no database change — on a LandSandBoat server the
`!injectaction <category> <animation>` GM command sends the action packet directly
(category 6 job ability, 3 weapon skill, 4 spell). Target a mob or NPC first: the server
takes the client's *face target*, which is not sent for yourself, and ignore the message
line the command prints (it is hardcoded). Publish with the client closed, or restart it
afterwards: a running client holds the overlay's file tables in memory and can write them
back over a registration made while it runs.

## Catalog

`xi ability catalog` writes `exports/ability/catalog.json`: every job ability (band
0–338, named from `abilities.sql`), spell (`xi.spell`) and weapon skill (both banks,
per-race paths, named from `weapon_skills.sql` and humanoid `mob_skills.sql`), each
with its generators (audio ones separately), sound pointers, clips and total frames.
Dummies and DATs without `main` are skipped. The viewer's picker reads this file; the
mixer offers to build it when it is missing. ~1,500 entries, about a minute.

## In the viewer

*Assets → Ability Mixer.* Left: the picker, one lane at a time — hover or arrow through
rows and the stage plays them on the current character (open Actors to pick race or an
NPC). Click or Enter takes a row for the lane. Right: the timeline (drag a block to
move it, drag a lane label to shift the lane, *snap to strike* aligns a lane's first
generator with the motion's hit frame), the selected block's numbers, and the **Parts**
of the previewed source with *solo* (play one generator alone) and *take*. **Play mix**
composes for the actor's race under `exports/ability/mixer/` and plays it; **Publish…**
shows the dry-run plan, then publishes. Recipes save next to the composed DATs.

Weapon-skill motion carries its own clips; the viewer resolves a routine's clip refs
against the loaded character, so picking a `ws:` motion source also sets the
character's Action to that skill (a short reload). Job-ability and spell motion
(`cm0?`, `ma2?`) plays from the character's own pool.

**Stance.** The Category / Action combos above the Actors panel are the Characters
view's own: *Battle → Battle: Sword* (etc.) or equipping a main weapon in Actors loads
that stance's `btl` clip, and in the mixer the character rests in it between the
routine's clips, so the mix is seen from the pose it plays from in game. *Basic* puts
the plain idle back.
