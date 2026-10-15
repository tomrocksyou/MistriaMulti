# Audit: game 1.0.6 scripts against 1.0.8 scripts

The whole mod was written against the game's 1.0.6 scripts. Both test machines run 1.0.8. This audit compared the two script
sets and checked every game identifier the mod's GML uses. Nothing from the game is stored in the repo; the checks run against
a directory you point them at (`scripts/audit-gml-ids.py`, `tests/test_engine_audit.py`, below).

## Result in one paragraph

**The two script sets are the same game code.** Every one of the 101 differences `diff -rq` reports comes from MMAPI, not from
the game update: the 1.0.8 set is the dump of an installed game (MMAPI patched in, a copy of this mod beside it) and the 1.0.6
set is an unpatched extract. After the MMAPI patches are accounted for, no function, enum, macro, global, object or
signature differs, so there was nothing in the mod to change for the script differences and **no GML code was changed**. What
the audit could not look at is everything that is not a script (see "Could not be verified").

## What the 101 differences are

| Count | What | Meaning for the mod |
|---|---|---|
| 98 files | game scripts and objects with MMAPI's instrumentation (`mmapi_emit`, `mmapi_apply_filters`, `mmapi_check_guards`, `mmapi_run_override`, `mmapi_local_get`, lines marked `// mmapi_...`) | these are the hook sites the mod relies on; each one is present (below) |
| 1 | `gml.meta.toml` (only in the 1.0.8 dump) | packaging metadata |
| 1 | `scripts/mmapi/` (only in the 1.0.8 dump) | the installed MMAPI; every `mmapi_*` function the mod calls is defined there |
| 1 | `scripts/mistriamulti_mistriamulti/` (only in the 1.0.8 dump) | the installed copy of this mod; byte-identical to `mod/mistrimulti/gml` apart from line endings |

How "no other difference" was established (all scripted, nothing eyeballed alone):

1. Every file pair was compared line by line after removing what MMAPI adds (lines containing `mmapi`, `mmapi_local_get` back to
   `local_get`). Every remaining "removed"/"added" line was read; each belongs to an MMAPI feature (custom spells and the mana
   cost rows, recipe ingredient lists and `RecipeComponent.Items`, treasure chest tables, pet cosmetic store entries, the
   `combat.damage` nil guard, `gain_xp` level-up check, `status_particles`, `ConversationDriver` locals, popup layout changes
   for MMAPI popups, ...). Example: `obj_damage_receiver.gml` gains `if tarball == undefined || !instance_exists(tarball)`
   right after the `combat.damage` filter line: that is MMAPI handling a filter that returned `undefined`.
2. All function and method definitions (`function f(...)`, `f = function(...)`), enums with their members, `#macro`s, `global.*`
   names and script/object file lists were compared structurally: identical except definitions created by MMAPI patches
   (`__mmapi_orig_*` wrappers, `RecipeComponent.Items`, the `__mmapi_store_menu` global).
3. The real game's own log (`L/`, `L2/`, `L3/` in the scratchpad) cites `file:line` for its trace lines
   (`LoadGame.gml:47`, `Taxi.gml:252/257/330`, `Game.gml:838`, `SaveGame.gml:25/283`, ...). Those lines match the 1.0.8 dump
   exactly and not the unpatched set (the MMAPI patch lines shift the numbers). So the dump really is what the game ran.
4. `gml/assets/gml` and `gml/x/assets/gml` (the two copies of the old set) are identical.

## Table of changes found

| # | Change found | Affected in the mod | What was changed | Verified how |
|---|---|---|---|---|
| 1 | No renamed or removed function, field, enum member, macro or global between the sets (`audit-gml-ids.py` with both sets: 0 definitions changed) | none | nothing | structural diff, tests/test_engine_audit.py |
| 2 | No signature change for the 91 game functions/macros the mod calls (e.g. `drop_item`, `find_animal`, `chop_node`, `pick_node`, `use_item_fast`, `create_dungeon_itinerary`, `spawn_monster`, `popup_creator`, `text_input_popup`, `read_text_file`, `save_text_file`, `try_read_json_file`, `requirements_pass`, `is_home_location`, `LocationPosition`, `PlayerAnimal`, `Child`, `Inventory`, `HashSetFromArray`) | none | nothing | same |
| 3 | No change to any of the 72 `Enum.Member` uses (37 enums) or the 16 `Enum.LEN` uses (`AnimalKind`, `Sex`, `HomeUpgrade`, `HomeVariant`, `FactoryTier`, `QualityId`, `NpcId`, `Weather`, `Season`, `Utero`, `ChildSkinTone`, `ChildStage`, `ChildLocation`, `ArmorSlot`, `Cardinal`, `AnimationName`) | none | nothing | enum member lists compared, all mod members exist |
| 4 | All 30 hooks in `requires_hooks` exist in the installed hook catalog with the kind the mod registers (event/filter/guard/override); each has its patch site in the 1.0.8 dump | `manifest.toml`, hook registrations | nothing | `scripts/mmapi/mmapi_hook_catalog.gml`, grep of every emit/filter/guard site |
| 5 | Every payload field a hook handler reads exists at the 1.0.8 patch site: `ctx.kind`/`ctx.menu` (`ui.menu_opened`), `ctx.key` (`local.missing`), `ctx.x`/`ctx.y` (`dungeon.treasure_chest`), `ctx.result/destroyed/burn/effect_override/node` (`resource.node_picked`), `ctx.save_path`, `ctx.player`, `ctx.npc_id`, `ctx.item.prototype.tool_type`, ... | handlers in Boot, SaveSpace, Peers, Clock, Drops, Progress, Wallet, Hearts, Terrain | nothing | read each emit site; handlers already read optional fields with `[$ "x"]` where they may be absent |
| 6 | All 18 `mmapi_*` functions the mod calls are defined by the installed MMAPI with the argument lists the mod uses | all files | nothing | `scripts/mmapi/*.gml` |
| 7 | The mod's `mistrimulti_supported_versions()` already lists 1.0.6 and 1.0.8 | `MistriMultiStatus.gml` | nothing (version not bumped, as asked) | read |

## Identifiers used by the mod that exist in neither script set

Searching all game scripts (both sets) and MMAPI for each name the mod uses:

* **Game functions called by the mod: none missing.** Names that look missing at first (`admit`, `bound`, `verify`, `to_string`)
  are local variables or parameters of the mod's own handlers (function-valued fields of the trust object, the `to_string`
  parameter of `mistrimulti_progress_index_map`), not engine calls.
* **GameMaker built-ins** the mod calls (`array_*`, `string_*`, `struct_*`, `instance_*`, `json_parse`, `buffer_*`,
  `ds_priority_*`, `file_*`, `irandom*`, `point_distance`, `get_timer`, ...) are all also called by the game's own scripts or
  by MMAPI, so they exist in the interpreter. `string_digits`, `string_byte_length`, `array_create_ext`, `lerp`, `room`,
  `ceil` are the ones used by only a few scripts; they appear in the game scripts too.
* **Generated helpers** (`*_to_string`, `string_to_*`, `try_string_to_*`, `try_infusion_to_string`, `fiddle_get`) have no
  `function` definition in the scripts (the game generates them from its data); each one is called by game scripts, which is the
  evidence they exist.
* **Assets not defined in scripts:** `spr_nothing`, `spr_npc_shadow`, `spr_player_base_lut`, `spr_fx_small_monster_death_poof`,
  `spr_ui_generic_icon_npc_small_player`, `par_offset` are used by game scripts; they exist as names but a sprite/object is
  data, so see below. `obj_mistrimulti_peer` is created by the mod itself (`object_create`).
* One field is not the game's: `st.heartbeat` is a field of the helper status file read through the bridge.

## Fixes made

None to the mod code: there is nothing to fix. Added instead:

* `scripts/audit-gml-ids.py`: reads the mod's GML and one or two game script directories and reports functions never mentioned
  by the game, missing enum members, `.field` reads that nothing assigns or mentions, MMAPI functions that are not defined,
  hooks missing from or of another kind than the installed catalog, and (with two directories) every changed definition.
  `python3 scripts/audit-gml-ids.py --game <old scripts> --game <new scripts>`; exit status 1 on any finding. Run it again
  whenever the game updates: it needs the unpacked scripts of the new version, nothing else.
* `tests/test_engine_audit.py`: runs the audit on a small made-up game fixture and proves it reports 12 deliberate breakages
  (renamed function, missing enum member, misspelled field, missing MMAPI function, unknown hook, wrong hook kind, changed
  signature, removed function, removed enum member, changed macro; and that the installed copy of the mod and MMAPI-added
  definitions are not counted as evidence or as game changes). `MISTRIA_GML=<dir>[:<dir>]` also audits real script directories.
  Both real sets currently report 0 findings.

## Could not be verified

* **Anything that is not a script.** `fiddle` data (item, NPC, animal, crop, quest, location tables), localisation, sprites and
  their sizes, rooms, tilemaps, sounds, and the engine's own built-in functions are not in the script dumps. A 1.0.8 change to
  data (a renamed item id, a changed `fiddle_get("...")` key, a new field in a prototype) cannot be seen here. The enums that
  are generated from data (`ItemId`, `NpcId`, ...) are defined in scripts that are identical in both sets, but their members
  come from the data at run time. Mitigation: real-game tests of the features (each `docs/SYNC-*.md` page has an in-game checklist, see
  `docs/HANDOFF-2026-10-15.md`).
* **That the old set is really 1.0.6.** The scripts carry no version string (`GAME_VERSION` is set at run time). It is the set the
  mod was written against; it is simply identical to the 1.0.8 dump apart from MMAPI.
* **A pure-script difference hidden inside an MMAPI-patched line.** Lines MMAPI rewrote were compared by reading both sides
  (about 400 lines across 68 files); every one was explained by an MMAPI feature, but a game change to the very
  same expression would look the same. The structural comparison (item 2 above) would still have shown a renamed or
  re-signed function.
* **Behaviour.** The audit shows names and shapes, not that e.g. `GRID.write_node(...)` still behaves the same, or that a field
  exists on the particular object the mod reads it from (a name existing somewhere in the scripts is only evidence).
* **MMAPI version.** The hook documentation used to write the mod (`MMAPI/CATALOG.md`) and the installed
  `mmapi_hook_catalog.gml` agree for all 30 hooks the mod uses; hooks the mod does not use were not compared.
* **Game logs on file** (`L`, `L2`, `L3`) come from MistriMulti 0.1.0 runs (menu and early game only): they contain no mod errors
  but exercise almost none of the features.
