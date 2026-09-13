# Retail update — 10 September 2026

Official notes: <https://forum.square-enix.com/ffxi/threads/64686>

What the retail client's data files changed in this version update, worked out
by diffing the patched install against a **legacy install** (a client last
patched in June 2026) file by file. 135 files were touched; 107 are ROM DATs,
the rest patcher bookkeeping (`patch.cfg`, `patch.txt`, `FTABLE`/`VTABLE`),
three DLLs (`FFXiMain.dll`, `FFXi.dll`, `FFXiResource.dll`) and PlayOnline
runtime noise.

The one change that matters for tooling is the **item record format**: every
item DAT grew its per-item block from `0xC00` to `0x1400` bytes and widened the
header. Anything that hard-codes `0xC00` reads garbage from a patched client.
xi-tools now detects the format per file (`xi ui items info`), and the
`xi_layout` module is the single place both layouts are described.

> Terminology used below: **legacy** = the pre-update record format
> (`0xC00`-byte records); **retail** = the format from this update on
> (`0x1400`-byte records).

---

## 1. Item DAT format change

### Stride

| | Legacy | Retail |
|---|---|---|
| Record size | `0xC00` (3072) | `0x1400` (5120) |
| Cipher | rotate-right-5 (`(b >> 5) \| (b << 3)` to decode) | unchanged |
| Records per file | unchanged — every file grew by exactly 5/3 | |
| Record terminator `0xFF` | at `0xBFF` | at `0x13FF` |
| Icon (`u32 size` + 8-bit BMP) | `0x280` | `0x280`, byte-identical |
| Bytes `0xC00`–`0x13FF` | – | zero (reserved) |

A modder's summary on release day put it as "each item entry grew by 2048
bytes with new fields mixed into the structs at different spots" — that matches
what the diff shows: +2048 bytes per record, of which 4 bytes are header growth
and the remainder is zero padding after the icon.

### Header

Two mechanical edits, applied per layout:

1. `flags` at `0x04` became a **u32** (was u16), so every field after it moves
   **+2**.
2. The equipment layouts (armor, armor 2, weapons, Monstrosity instincts) gained
   a **2-byte pad after `races`**, so every field after `races` moves **+4**.

Consequences per layout (offsets are into the decoded record):

| Layout (DATs) | Legacy string block | Retail string block | Notes |
|---|---|---|---|
| General (`118/106`, `301/115`, new `387/14`) | `0x18` | `0x1C` | +2 through `0x18`, then a pad |
| Usable (`118/107`) | `0x1C` | `0x1C` | +2 for every field; the old trailing pad at `0x1A` absorbed it |
| Puppet (`118/110`) | `0x18` | `0x1C` | `puppetSlot` `0x0E→0x10`, `elementCharge` `0x10→0x14`; `stack` now reads 0 |
| Armor (`118/109`, `286/73`) | `0x2C` | `0x30` | `level 0x10`, `slots 0x12`, `races 0x14`, `jobs 0x18`, `superior 0x1C`, `shieldSize 0x1E` … `itemLevel 0x2A` |
| Weapon (`118/108`) | `0x38` | `0x3C` | `dmg 0x20`, `delay 0x22`, `dps 0x24`, `skill 0x26`, `jugSize 0x27`, `maxCharges 0x2C` … `baseItemId 0x34`, `itemLevel 0x36` |
| Maze Mongers (`217/21`) | `0x54` | `0x54` | +2 for the common fields only; everything from `0x14` unchanged |
| Instincts (`288/80`) | `0x28` | `0x2C` | `level 0x10`, `races 0x14`, `instinctCost 0x1C` |
| RoE objectives (`307/16`) | `0x20` | `0x20` | **header unchanged**, only the stride grew |

Full field tables (both formats, every layout) live in
[`src/xi/ui/items/xi_layout.py`](../../src/xi/ui/items/xi_layout.py) and are
mirrored in the model viewer's `ui/js/database.js` (`HEADER_OFFSETS`). They were
derived by matching every legacy field value against the retail record for
30,000+ named items and are exercised by `tests/test_items_reference.py`.

### Detecting the format

File size settles it for every table but two (`ROM/320/26` and `ROM/332/48`
have sizes both strides divide). Rule used by `xi_layout.detect_stride`:

1. Only one of `0xC00` / `0x1400` divides the file size → that stride.
2. Both divide → count records ending in `0xFF` under each stride; the higher
   ratio wins.
3. Still tied (a file with no terminators, e.g. the gil table) → the stride under
   which decoded record ids count up by one.

`XI_ITEM_FORMAT=legacy|retail` forces the answer for debugging.

### Affected files

All JP/EN pairs (JP first): `ROM/0/4–9` & `ROM/118/106–110` + `ROM/174/48`,
`ROM/217/20–21`, `ROM/286/72–73`, `ROM/288/66–67`, `ROM/288/79–80`,
`ROM/301/114–115`, `ROM/307/15–16`, `ROM/307/23–24`, `ROM/314/89`,
`ROM/320/26`, `ROM/332/46–49`, and the new pair `ROM/387/13–14`.

---

## 2. New files and table entries

| File | File id | What |
|---|---|---|
| `ROM/387/13.DAT` / `ROM/387/14.DAT` | 55555 / 55675 | **New item table** (JP / EN), 1024 slots, item ids **30720–31743** (`0x7800–0x7BFF`), general layout. Every slot is still a `.` placeholder. On a legacy install these two ids pointed at `ROM/327/123–124` (emote help text) as a stand-in. |
| `ROM/387/15–21.DAT` | 107374, 107674, 107974, 108274, 108574, 108874, 109174 | **Main-hand gear model 969**, one DAT per race (hm, hf, em, ef, tr, mt, gl — section tags `70hm` … `70gl`, mesh `scyk`). This is the **Colibri Scythe** (item 18567). |
| `ROM/384/118.DAT` | 97 | New 512-byte lookup table (eight u32 indices, then `xx 00 01 3c` records). Sits next to the emote tables (id 96 = `ROM/327/122`, id 98 = `ROM/384/119`). Purpose not yet identified. |

`FTABLE.DAT`/`VTABLE.DAT` changed for exactly these ids (one brand-new id, 97,
and nine ids remapped to `ROM/387`). Everything else that differs from a legacy
install's tables is older retail growth the legacy install never received
(`ROM/384–386` ranges) or that install's own customisations.

> **Gear model 969 and custom gear.** Any private-server gear injected at
> main-hand model id 969 (the first free retail slot before this update) now
> collides with retail's Colibri Scythe file ids. `xi ftable expand` reserves
> custom gear from model 3000 up for exactly this reason; re-check anything
> placed below that.

---

## 3. Zone tables — file id formulas (verified)

Derived from the tables themselves and confirmed against the actor ids inside
the event files (`zone = (actor_id >> 12) & 0xFFF`):

| Table | zones < 256 | zones ≥ 256 |
|---|---|---|
| Event DAT (NPC bytecode) | `5820 + zone` | `84735 + (zone − 256)` |
| Dialog, JP | `6120 + zone` | – |
| Dialog, EN | `6420 + zone` | `85335 + (zone − 256)` |
| Entity names | `6720 + zone` | `86235 + (zone − 256)` |

Formats: event = `u32 count, u32 sizes[count], blocks` (each block begins with
the actor id; `0x7FFFFFF0` is the zone actor); dialog = offset table XOR
`0x80808080`, strings XOR `0x80`; entity names = `none` header then 32-byte
records `char[28] name, u32 id`.

---

## 4. Every updated DAT and what it is

### Item tables (see §1) — 34 files
`ROM/0/4–9`, `ROM/118/106–110`, `ROM/174/48`, `ROM/217/20–21`, `ROM/286/72–73`,
`ROM/288/66–67`, `ROM/288/79–80`, `ROM/301/114–115`, `ROM/307/15–16`,
`ROM/307/23–24`, `ROM/314/89`, `ROM/320/26`, `ROM/332/46–49`, `ROM/387/13–14`.

### Zone event DATs (`5820 + zone`) — 27 files

| DAT | Zone |
|---|---|
| `ROM3/0/92` | 26 Tavnazian Safehold |
| `ROM4/0/55`, `ROM4/0/58` | 50 Aht Urhgan Whitegate, 53 Nashmau |
| `ROM/20/17`, `ROM/20/24`, `ROM/20/31` | 80 Southern San d'Oria [S], 87 Bastok Markets [S], 94 Windurst Waters [S] |
| `ROM/20/120` | 183 Maquette Abdhaljs-Legion (Ambuscade) |
| `ROM/21/19` | 210 developer test zone (Fame / Conquest Debug / Item-Test NPCs) |
| `ROM/21/40, 41, 42, 44, 45, 46, 49, 51, 54, 57, 58` | 231 Northern San d'Oria, 232 Port San d'Oria, 233 Chateau d'Oraguille, 235 Bastok Markets, 236 Port Bastok, 237 Metalworks, 240 Port Windurst, 242 Heavens Tower, 245 Lower Jeuno, 248 Selbina, 249 Mhaura |
| `ROM2/13/46`, `ROM2/13/47`, `ROM2/13/49` | 247 Rabao, 250 Kazham, 252 Norg |
| `ROM9/5/53` | 256 Western Adoulin |
| `ROM/303/28` | 280 Mog Garden |
| `ROM/362/20` | 287 Maquette Abdhaljs-Legion (second instance) |
| `ROM/364/108`, `ROM/364/109` | client zone ids `0x401` / `0x402` — two four-actor zones, almost certainly the Mog House interiors (they carry the same shared script every town has) |

### Zone dialog DATs — 18 files
- EN (`6420 + zone`): `ROM2/17/63` (130 Ru'Aun Gardens), `ROM/24/76` (139 Horlais Peak), `ROM/24/81` (144 Waughroon Shrine), `ROM/24/83` (146 Balga's Dais), `ROM2/17/87` (154 Dragon's Aery), `ROM2/17/92` (159 Temple of Uggalepih), `ROM/24/102` (165 Throne Room), `ROM/25/39–50` (230–241, the nine nation city zones).
- JP (`6120 + zone`): `ROM/22/76` (139), `ROM/23/39–50` (230–241).

### Entity-name DATs — 2 files
`ROM/26/120` (zone 183) and `ROM/362/25` (zone 287): the Ambuscade rotation.

### Strings and misc — 7 files

| DAT | Id | What |
|---|---|---|
| `ROM/27/79`, `ROM/27/80` | 7034, 7035 | Monster ability names, JP / EN (dialog-format tables, 5120 / 4864 entries) |
| `ROM/97/8` | 30 | `XISTRING`: PlayOnline lobby / connection messages (JP). Text unchanged, only index tag bytes |
| `ROM/97/20` | 32 | `XISTRING`: client UI format strings (JP). One new string |
| `ROM/384/118` | 97 | New lookup table (see §2) |
| `ROM/387/15–21` | see §2 | Gear model 969 |

### Non-DAT
`FFXiMain.dll`, `FFXi.dll`, `FFXiResource.dll`, `FTABLE.DAT`, `VTABLE.DAT`,
`patch.cfg`, `patch2.cfg`, `patch.txt`, `patch.sin`, `patch.rst`, `patch.ver`,
`file.txt`. The DLLs have not been diffed yet.

---

## 5. What changed inside them

### Items (EN, against the legacy install)

**New items** (slots that were `.` placeholders):

- *General:* Orvail Box Key (1065), Sachertorte — a furnishing (3756).
- *Usable:* Ulthalam's Chronicles, Trust Primer, Trust Tome, Marjory's Thesis,
  Regine's Fifth Eye, Sack of Beads, L. Sack of Beads (6714–6721).
- *Weapons (104):* a full **Skia → Arctus → Telognophos → Auge → Daduchos →
  Telopanos** progression across every weapon type (grips, knuckles, knives,
  axes, choppers, scythes, halberds, shinobi-gatana, katana, bows, swords,
  sabers, mauls, staves, claymores), plus Prophetic Knife / Axe / Sword / Club,
  **Colibri Scythe** (18567, DMG:1 Delay:528 — the model 969 above), Ja Ja Sword,
  Ja Ja Mace, Ryofu Uchiwa, Abyssbringer, Sh. Moogle Rod (+1), Bud Rod,
  Travesty, Prophetica.
- *Armor:* Abyssal Mask (10863).
- *Armor 2 (63):* the CS / MG / WN / SV / EL race-look **+1 sets**
  (24276–24303), Subu Houou Kabuto, Amin / Ischkur / Azimuth Turban, Reciente
  Coselete, Mirce Wardecors, Noble Redingote, and four new sets — **Ruwa**,
  **Olorun**, **Nzame**, **Egbesu** — plus Cactuar Shield, the Skia…Telopanos
  shields and Jubilee Ring (Experience point bonus +50%).
- *General 2 (13):* Kupon I-Amb, Auge Scintistone, Fafnir's Scale, Kirin's
  Mane, Iron Giant Shard, Kupon A-sAF+3 / A-sRel+3 / A-sEmp / A-sEmp+3,
  Temenos Code, Apollyon Code, Alabaster Material, Murky Material.
- *Records of Eminence:* 38 new objectives ("Deeds are the Best!", the
  Reforging Relics / Ambuscade / Artifact / Empyrean progression chain,
  "Joining a Sortie", the "Entering Dynamis - …" set, several (VBD) rows), 24
  removed and 9 renamed ("Pioneer (VBD)" → "Coalition Assignments (VBD)" …).
  21 objectives changed the same two header bytes (a category flag).

**Renames:** "Greatsword" / "Greataxe" → "Great Sword" / "Great Axe" (10
weapons); "Def." / "Ap." → "Defeat" / "Apathy" (4 armor); Basket-burdened Crab
→ Hermitage Crab (Monstrosity species).

**Description text:** 330 armor and 888 armor-2 descriptions changed only in
formatting ("Physical damage taken -3%" → "Physical Damage taken-3%",
"Critical hit rate +5%" → "…rate+5%"). Substantive edits: Worn Sack
singular/plural strings, Beryllium Tachi "Katana skill" → "Great Katana skill",
Miracle Cheer and Seraphic Ampulla stat text, the Trust / Prestige / Sworn crown
and platemail line order, typo fixes (Rolandienne, nondescript, Bonanza),
Storage Slip wording.

**Stats:** one real weapon header change (Dark Amood). No armor stat changed.

### Dialog (EN)

Lines inserted in **every** updated zone: "The Deeds of Heroism Bonus Campaign
is underway!", "We've prepared a special present in celebration of the
collaboration with Wizardry Variants Daphne!", two recycle-bin-full messages,
"It won't open.", "Your wing skill improved to …".

- **Nation cities:** the **Mandragora Mania** minigame — rules, setup prompts
  and results (Southern San d'Oria, Bastok Markets, Windurst Woods, +40 lines
  each); **Tales' Beginning** — start / postpone prompts for every expansion
  storyline; a **chocobo digging "wing skill"** tutorial; a guild-rank renounce
  prompt; a rewritten new-player tutorial (Records of Eminence, gil, the
  auction house, Trust instructors Gondebaud / Clarion Star / Wetata, Weakness);
  phantom gem selection; a "one-time free Warp for the objective" travel option.
- **Battlefield zones** (130, 139, 144, 146, 154, 159, 165): only the shared
  campaign lines and minor wording fixes ("impossible to gauge" →
  "impossible-to-gauge", "battle machine" → "siege machine").
- JP tables received the same insert counts.

### Events

Most byte changes are dialog-index renumbering after the insertions above.
Real changes:

- A **shared unnamed NPC script present in every town, Adoulin, Mog Garden and
  the two `0x401`/`0x402` zones grew by 160 bytes** (29648 → 29808) and now
  references the 28 new race-look +1 items, Sachertorte and Bud Rod.
- Survival Guide scripts grew +196 bytes everywhere; Dealer Moogle 10812 →
  15024; Curator Moogle 468 → 676.
- Bastok Markets lost 78 actor blocks and gained 22 (the Mandragora Mania NPCs
  "Moogle", "Mumor", "Brian", "Sludge", "Horro"; many "???" / Agent Moogle test
  blocks removed). Northern San d'Oria +Excenmille, +Tales' Beginning; Port
  Bastok +Clarion Star, +A.M.A.N. Liaison; Port Windurst +Skipper Moogle,
  +A.M.A.N. Liaison, +Tales' Beginning. "Unity Master" blocks were removed in
  several cities. Western Adoulin gained one unnamed actor.
- The developer zone (210) swapped four test NPCs (Limbus Operator, Mog garden,
  SCitem-Chair, Wep-test → Unity Master, Item-Test, Galka, Previous Race).

### Ambuscade

Both Maquette Abdhaljs-Legion zones renamed their entities to **Bozzetto
Bigwig, Bozzetto Tormenter ×3, Bozzetto Astrologer ×2, Alluttu**, replacing
Freyja / Frigg / Skathi / Archytas / Sturdy Decanter / Overseeing Eye — the
monthly rotation.

### Monster ability names (`ROM/27/79–80`)

~40 names filled into slots 3712–3727, 3776–3793 and 4152–4162: Spinal
Cleave, Mangle, Leaping Cleave, Hex Palm, Animating Wail, Fortifying Wail,
Unblest Jambiya, Gen'ei Ryodan, Phantom Whorl, Turn the Tables, Spin the
Tables, Triple Reversal, Pyric / Polar Blast and Bulwark, Barofield, Trembling,
Serpentine Tail, Nerve Gas, Bad Breath, Leeching Current, Scream, Subterfuge,
Submission, Beckon, Nihility Genesis. (A legacy install that has filled those
slots with its own names will see them overwritten if it takes these files.)

### UI strings

`ROM/97/20` gained one JP string — "Spend N Face Points to raise 「X」's ability
value?" — a **Face Points** (Trust) spend prompt that matches the new Trust
Primer / Trust Tome items and the Trust tutorial dialog.

---

## 6. Effect on the tooling

- **`xi ui items`** (search / export / json / import / inject / icon):
  format-aware. `xi ui items info` prints the detected format per DAT.
  Import and inject write records in the DAT's own format, so a legacy install
  stays legacy and a retail install stays retail.
- **`xi mv database`**: bakes both formats; the JSON now carries `stride`,
  `strides` (per part) and `format` so the model viewer can find a row's block
  for its icon.
- **Model viewer** (`ui/js/database.js`): detects the stride per file and uses
  the matching header offsets; the DAT browser badges item tables, string
  tables and the new lookup tables; the new `items7` table is registered but
  hidden from the Database tree until it holds a real item; characters.json
  lists the Colibri Scythe (model 969) for every race.
- **Legacy-only tooling** (FFXiMain patches, gear-table expansion) is untouched
  by the item-format change — item ids, gear model ids and file ids are three
  different number spaces and none of the ranges moved. The retail
  `FFXiMain.dll` did change in this update, so those patches would need
  re-porting before they could be applied to a retail-current DLL.

---

## 7. Not yet analysed

The three DLLs (binary diff), the exact meaning of the two new header words,
the `ROM/384/118` table, and the `ROM/307/24` / `ROM/320/26` numeric tables.
