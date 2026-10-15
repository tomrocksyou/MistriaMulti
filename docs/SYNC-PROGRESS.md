# Per-player progress

What a player has earned (recipes, mail, quests, romance, ...) belongs to that player; the world belongs to the host. This page
audits everything the game saves, decides which side owns each part and why, and describes how the personal part is stored,
restored, committed with the host's save and kept consistent with the shared world.

Code: `mod/mistrimulti/gml/MistriMultiProgress.gml` (progress records, save commit, one partner per NPC), with small hooks in
`MistriMultiPlayerData.gml` (record schema), `MistriMultiPlayerSync.gml` (handshake and checkpoints) and `MistriMultiBoot.gml`.
It runs on the event layer (`docs/EVENT-LAYER.md`). The core character record is described in `docs/PLAYER-DATA.md`.

## Principles

- **The host owns the world.** Terrain, objects, containers, NPCs in the world, the museum, the house, the clock, the weather and
  the story are the host's save. Guests ask; they never write them.
- **Each player owns their character.** Inventory, money, skills, recipes, mail, relationships, personal quests, counters, seen
  flags are kept by the game that plays them and mirrored to the host's per-player record (a checkpoint about every five seconds).
  The host's copy is what comes back when the player returns, in any slot.
- **A new guest is a new character**, not a copy of the host: the game's new-game values for every personal field (default
  recipes, default cosmetics, starter inventory, an empty inbox with the first letters, no quests, no relationships). The
  only exception is the *seen cutscene history*, which starts as the host's: a story scene the host already played has had its
  effects on the world, and replaying it for a guest would apply them twice.
- **Fail soft and never overwrite what cannot be read.** Every network field is validated; a section the game cannot restore
  is not uploaded afterwards; a damaged host record is refused and recovered from its backup instead of being replaced.

## Audit

The game writes six files into a save: `header`, `gamedata`, `player`, `npcs`, `quests`, `game_stats` (plus `date_photos`, `info`
and one file per location grid). A guest starts from a copy of the host's save, so **every field below that is personal and not
carried yet is, for the guest, a copy of the host's value** (see [Known gaps](#known-gaps)). "Core" is the record of
`docs/PLAYER-DATA.md`; "progress" is the record of this page, in sections.

### `player` (`ARI`, saved by `SaveGame.gml`)

| Field | Owner | Carried by | Why |
| --- | --- | --- | --- |
| name, birthday, pronouns, selected preset (appearance) | personal | core `character` | identity |
| other saved presets (`presets`) | personal | not yet | outfit loadouts; the guest sees the host's list |
| farm_name | world | host save | the farm has one name; character creation keeps it locked |
| gold, essence, renown, health, stamina, mana, free_baths | personal | core `stats` | |
| inventory, armor | personal | core | a tool upgrade replaces the tool by a different item, so upgrades travel with the inventory |
| skill_xp, perks, spells_learned | personal | core | |
| status_effects, invulnerable_hits, ancient_inspiration_time, end_of_day_status | personal, transient | not carried | timed buffs and sleep-flow state; they end with the session |
| perks_active (perk toggles) | personal | progress `misc.perks_off` | |
| ate_perpetual_soup_today | personal, daily | progress `daily.soup` | |
| pinned_spell | personal | progress `misc.pinned` | |
| inbox (mail) | personal | progress `inbox` | each player has a mailbox |
| items_acquired (almanac) | personal | progress `almanac.acquired` | |
| items_sold, monsters_killed | personal | progress `almanac.sold/killed` | quest requirements compare against them |
| legendary_fish_caught, annual_item_purchase_bans | personal | progress `almanac` | |
| tutorials_seen | personal | progress `seen.tutorials` | a new player should see the tutorials |
| recipe_unlocks, recipes_created | personal | progress `recipes` | crafting and cooking unlocks |
| morning_recipe_unlocks | derived | recomputed on restore | the game recomputes it every morning |
| seen_cosmetics, cosmetic_unlocks | personal | progress `cosmetics.outfits/seen` | |
| animal_variant_unlocks, animal_cosmetic_unlocks, pet_cosmetic_sets_unlocked, pet_skin_unlocks | personal | progress `cosmetics` | what the player may adopt or place; the animals themselves are world |
| song_unlocks, song_overrides, dyn_song_overrides, bell_sound | personal | progress `cosmetics` | jukebox and bell settings |
| renown_reward_inventory, pending_renown_entries | personal | progress `misc.renown_rewards/renown` | renown is personal |
| quest_artifacts, crown_cooldown | personal | progress `misc` | per-player quest scores |
| date_history, date_unlocks, festival_date_partner | personal | progress `romance` | |
| wedding_date, proposal_date, disable_break_ups(_letters), pending_child, children | personal | progress `romance` | see [Relationships](#relationships-and-romance) |
| mount | personal | progress `misc.mount` | |
| has_seen_treasure/ritual/arena_level_today, has_gossiped_today, used_object_today, has_left_house_today | personal, daily | progress `daily` | restored only for the day they were saved on |
| world_fountains, used_wishing_well, ate_soup | world | host save | discoveries of the shared world (the game only reads them when saving and loading) |
| lost_and_found | world | host save | a shared container |
| floorings, wallpapers, size_upgrade, upper_floor, home_variant | world | host save | one shared house |
| secret_narrows, secret_beach, secret_tower | world | host save | opened secret areas are changes to the shared map |
| last_bed_used, save_position | personal, not carried | not yet | they point into the shared house and need the sleep/position features |
| give_magic_key_seed | constant | none | always saved as `false` |

### `gamedata` (world file, with a few personal fields)

| Field | Owner | Carried by | Why |
| --- | --- | --- | --- |
| random_seed, dir, playtime, date, clock, weather, day_time_speed, pending_day_time_speed_change | world | host save | the shared clock and weather |
| all_unlocks, story_enabled | world | host save | game-mode switches |
| dynamic_grid_count, lost_items, props, farm_expanded, seals, pet, daycare, saturday_market_vendors, fish_trap_* | world | host save | objects, animals and containers of the farm |
| **museum_progress** | **world** | host save | **Decision: the museum is shared.** There is one building; its displays and set rewards belong to the farm. A guest's donation must become a host request (the `museum.donate_item` hook exists); the donor's renown stays personal (`pending_renown_entries`). Until that feature exists a guest's local donation is not saved |
| t2_world_facts, t2_expirator | mixed | see [World facts](#world-facts-t2) | |
| scene_history | personal | progress `seen.scenes` | includes romance scenes |
| scenes_played_today | personal, daily | progress `daily.scenes` | |
| maximum_mines_level | personal | progress `misc.mines_level` | each explorer unlocks their own elevator floors |
| active_mist_sight | personal, not carried | not yet | a vision setting |

### `npcs` (one entry per villager)

| Field | Owner | Carried by | Why |
| --- | --- | --- | --- |
| heart_points, gifts_given, known_gift_preferences, gift_flag, talk_flag, times_spoken_today | personal | core `relations` | friendship is between one player and one villager; the daily flags reset by day |
| relationship status (`<npc>_status`) | personal | core `relations.status` | see [Relationships](#relationships-and-romance) |
| `<npc>_has_met`, `<npc>_is_ex` | personal | progress `romance.met/ex` | |
| animation, cardinality, outfit, current_activity, current_routine, location_position, schedule_name, had_arrived, simulated_distance_traveled, swap_schedule_request | world | host save | the villager's simulation (a future NPC feature) |

### `quests`

| Field | Owner | Carried by | Why |
| --- | --- | --- | --- |
| active and completed quests of category **crown, Tali, Stillwell, heart, fetch** (+ completion times, task blackboards) | personal | progress `quests` | personal errands and challenges |
| active and completed **story** quests | world | host save | the story is the world's: its rewards and effects change the shared map. Guests see the host's story state |
| manual_quest_unlocks, request_board_read_entries | personal | progress `quests` | |
| request_board | world | host save | the notice board is a shared object |
| `blackboard` of the quest log | unused | none | no gameplay script reads it |

### `game_stats` and the rest

| Field | Owner | Carried by | Why |
| --- | --- | --- | --- |
| enemies_killed, gross_essence, deaths, faints, bathhouse_uses, bugs_missed, fish_missed, cutscenes_skipped, npcs_spoken_to | personal | progress `counters` | read by achievements |
| the logs (items cooked/forged/eaten, fish and bugs caught, harvests, purchases, income, bedtimes, ...) | personal, not carried | not yet | unbounded lists; only their length matters to achievements |
| date_photos | personal, not carried | not yet | compressed images (large) |
| header, info | derived | none | rebuilt by the game |
| every location grid, the farm buffer, dynamic grids | world | host save | |

### World facts (T2)

The game keeps a store of named *world facts* that the dialogue and schedule data read. Most are derived from a field above and
rewritten by the game every morning (`T2R.update_daily`): quest facts, `had_item_*`, `cutscene_seen_*`, relationship facts,
children facts, skill levels. The mod restores the field and then **clears the facts the daily update would only ever set**
(for quests and cutscenes), writes `<npc>_has_met` / `<npc>_is_ex` / `<npc>_status` itself, and runs `T2R.update_daily()` once.
Facts that cannot be derived from a field and that the data files write (date counters such as `da_<npc>_<date>`, dialogue
progress) are personal in nature and are **not carried**: a guest starts with the host's values.

## Relationships and romance

**Personal.** Friendship points, gift/talk flags, known preferences and the relationship status (best friend, dating, fiancé,
spouse) are the player's. Marriage and engagement dates, the date history, children, "met" and "ex" are the player's too. Each
player's game uses its own values for dialogue and prompts, so two players can have different hearts with the same villager.

**World.** The villager's body (where they walk, their schedule, outfit, animation, whether they are asleep) is simulated in every
game and steered by the host's plan (`docs/SYNC-STORY.md`). Each game's own relationship facts choose a villager's schedule, which
has two consequences that are by design:

- A villager lives in the farm house in the game of the player whose spouse they are. **Since the story sync every game also moves
  in the spouses of the other players** (the host's registry below says who is married to whom, a player who is away included), so
  a guest's spouse lives at the farm in every game, like the host's would; the spouse is still the guest's partner in dialogue and
  only in the guest's game. Details, the bed and the unverified assumptions: `docs/SYNC-STORY.md`, "Spouses of other players live
  at the farm".
- A guest's friendship, status and daily availability (`talk_flag`, `gift_flag`) are the guest's: talking to a villager once a day
  is per player; a villager is not "used up" for everybody.

**Coherence.** The host keeps one **claim registry**: villager → the player who is dating, engaged to or married to them. It is
derived from the records (the host's own relationships and every stored core record), so the personal data and the world
fact can only differ for the moment between a change and the next checkpoint.

**Shared hearts (world option, 0.3.1).** When the host starts a new world they choose *Hearts with villagers*: each
player's own (the default, recommended) or shared by everyone. With shared hearts the host's villagers hold the one value
per villager; a guest's gain (the game's `npc.heart_points` filter) is sent to the host (`heart_add`), added once and
broadcast (`hearts`), and a guest's own record no longer restores hearts. Relationship status, dates, marriage and heart
events stay per player, and the exclusivity below still applies. Options are stored in `worlds/<world>/options.json` on the
host and sent in the host's frame (`o`). Code: `MistriMultiHearts.gml`; tests: `test_event_features.py`
(`test_shared_hearts`, `test_own_hearts`). A heart level set directly by a cutscene in a guest's game is not shared.

**Exclusivity (decided).** A villager can be romantically involved with **one player at a time**; friendship and "best friend"
stay open to everyone.

1. The first claim wins. Claims last as long as the status stays dating, fiancé or spouse, even while the player is offline.
2. While a villager is claimed by someone else, their *pink* romance prompts are greyed out for every other player
   (`dialogue.romance_prompt_guard`; the claims are broadcast within a second and sent to every game that joins).
3. If two players get past the prompt at nearly the same time, the host keeps the first claim, **downgrades the later player's
   record to "best friend"** before saving it, and tells that player's game, which sets the status back to "best friend"
   (only "dating" can be revoked this way; engagement needs a "dating" status, so it cannot race).
4. A break-up (the status leaving the romantic states) releases the claim. Players are never removed from a claim by absence.
5. The host's own partner is protected the same way: a guest cannot start dating the host's spouse, and the host cannot take a
   guest's partner (the host's game is set back to "best friend" the same way).

**Spouses (registry).** Next to the claims the host keeps `romance_spouse` (villager -> player), derived from the same records at the
same moments, for the status "spouse" only: a player has **one** spouse (the first the records name; the game has one
`ARI.spouse()`), and only a villager the player also holds in the claims. The host's own spouse is included. The `romance_claims`
event carries it (`{ claims, spouses }`, sent to a game that joins and whenever it changes); a guest keeps only the entries that its
claims list confirms (`mistrimulti_romance_spouse_view`, at most 256 names). `MistriMultiStory.gml` reads it to move the spouses of
other players into the farm house in every game. The entry stays while the player is away and ends only when the record says the
marriage ended. Debug: `mistrimulti.progress` lists `spouses`.

## Records

### Layout

The host stores, per world and player (`mod_data/mistrimulti/worlds/<world-key>/`):

```text
players/<identity>.json            core record (docs/PLAYER-DATA.md)
players/<identity>.progress.json   progress record, with .bak and .tmp
members.json                       the identities that have records (the host cannot list a folder)
commits/<save name>.json           records committed with a host save, with .bak (two generations)
commits/discarded.json             the records the last rollback replaced
```

A progress file is `{ "v": 1, "revision": n, "data": { "v": 1, "uid", "world", "sections": { ... } } }`.

### Sections (schema version 1)

| Section | Content |
| --- | --- |
| `recipes` | `unlocks`, `created`: item names |
| `almanac` | `acquired` (item names), `sold` and `killed` (name → count), `legendary` (seasons), `bans` (item names) |
| `seen` | `tutorials` (names), `scenes` (cutscene names, romance scenes included) |
| `cosmetics` | `outfits`, `seen`, `animal_variants`, `animal_cosmetics` (kind → names), `pet_sets`, `pet_skins`, `songs`, `song_overrides`, `dyn_song_overrides`, `bell_sound` |
| `romance` | `dates`, `history`, `wedding_date`, `proposal_date`, `no_break_ups`, `no_break_up_letters`, `festival_partner`, `pending_child`, `children`, `met`, `ex` |
| `inbox` | `letters`: `{ path, read, items_taken }` |
| `quests` | `active` (`name`, `task`, `board`), `done`, `times`, `manual`, `board_read` (non-story quests only) |
| `counters` | `stats` (name → number), `spoken` (villager → number) |
| `misc` | `crown_cooldown`, `artifacts`, `pinned`, `perks_off`, `renown`, `renown_rewards`, `mount`, `mines_level` |
| `daily` | `day` plus today's flags; restored only when `day` is the current in-game day |
| `story_rewards` | `init` (the ledger was seeded) and `paid` (story quest -> level whose rewards this player has been given, 1 to 1000000, at most 2048 quests); see below |

**`story_rewards`** is not a field of the game's save: it is the player's ledger of story-step rewards (`docs/SYNC-STORY.md`, "Rewards
of a shared step"), kept in the world facts `mm_paid_<quest>` and `mm_paid_init`. Capture reads those facts for every story quest;
restore writes them (and clears the ones the record lacks, because a guest's world copy contains the host's), so a returning player
keeps their ledger in any slot, and it rides the host's save commit like the other sections. A record from before this section, and a
new character, restore `init: false`: the story sync seeds the ledger at the first pass, marking everything that exists then as
paid. The host's own ledger needs no section: the facts are saved with its world.

Everything is stored **by name**, written by the game's own `*_to_string` functions (and the game's own `serialize_array_bool`,
`Inbox.serialize`, `serialize_renown_entry`, `Inventory.serialize`), and restored through the inverse mapping, so a name this
game version does not know is dropped instead of crashing, and formats follow the game when it changes. Values whose inner format
belongs to the game (quest blackboards, quest artifacts, the mount) are accepted as plain JSON with bounded depth, size and numbers.

### Versioning and migration

- A section is added by adding it to `mistrimulti_progress_sections()`. An older record that lacks it restores that section as a new
  character's and uploads it at the first checkpoint, so adding sections needs no version change.
- A change that is not additive increments `MISTRIMULTI_PROGRESS_VERSION` and adds a conversion step to
  `mistrimulti_progress_migrate` (older envelope → current). A record written by a *newer* version is refused (never overwritten);
  sections this version does not know are dropped when a record is read.
- **From the old format** (a core record and no progress): the core record is restored exactly as before (no new character), the
  host answers "no progress yet", and the guest starts with a new character's progress, uploads it, and from then on the player has
  both records. Nothing of the core file is touched.

### Limits

| | |
| --- | --- |
| One section | 96 KiB of JSON |
| A whole progress record | 240 KiB (the blob limit of the event layer is 256 KiB) |
| Names | 1-96 characters; lists and maps are bounded per field (for example 8192 item names) |
| Writes | the host writes a player's progress at most once a second and pauses 2 s after a failed write |

An oversized section is never sent; the guest reports it and stops sending that section (the host keeps its copy).

## Synchronisation

| Kind | Direction | Meaning |
| --- | --- | --- |
| `progress_request` | guest → host | the core record is in; send my progress |
| `progress_start` | host → guest | no progress record yet: start as a new character |
| `progress_record` (blob) | host → guest | the stored record, delivered whole or not at all |
| `progress_update` (blob) | guest → host | the sections that changed since the last acknowledged upload, with revision n+1 |
| `progress_saved` | host → guest | revision n is stored |
| `progress_error` | host → guest | refused or needs recovery; names the offending section |
| `progress_flush` | host → guests | send your state now (a day ended, the host is about to save) |
| `romance_claims`, `romance_revoke` | host → guests | the claim registry; a status to set back to "best friend" |

1. The guest's core handshake is unchanged. After the core record (or "start") is applied, the guest sends `progress_request`.
   The host answers only for the identity its core handshake admitted (so duplicates and the host's own identity are refused once).
2. The guest becomes **playable only when both records are applied** (`player_ready`), so it never shows or uploads a half-loaded
   character. The restore validates the whole record first and then applies it section by section; a section that fails in the
   game is locked for the session so a half-restored state never overwrites the host's copy.
3. About every five seconds, together with the core checkpoint (and one at a time, so blobs never queue behind each other), the
   guest captures every section, compares it with what the host last acknowledged and uploads only the changed ones. The host
   merges them into the stored record, validates, writes `.tmp` then renames over the file (keeping the previous file as `.bak`),
   and answers `progress_saved`. Updates must arrive with revision n+1; a repeated one is only acknowledged again.
4. A refused section (the host answers `progress_error` with its name) is not sent again in this session; the others continue.

## Host save commit

The world is written only when the game saves, but player records are written every few seconds. A record newer than the save
that is reloaded later would give a player items that the reloaded world never handed out, so the two are committed together:

1. **Saving.** At `save.game_saving` (after every guard allowed the save, before the game writes anything) the host writes
   `commits/<save name>.json`: the current core and progress records of every known player, the in-game day and the world key.
   The previous commit of that save is kept as `.bak`. The write is a temporary file and a rename. Just before, `game.new_day`
   and `game.save_guard` ask guests to flush, so the commit holds the state of the last second or two rather than of the last
   checkpoint.
2. **Loading.** At `save.game_loaded` the host notes which save is coming in. When its world session starts (before any guest is
   admitted) the host looks for the commit of that save whose in-game day equals the loaded day (newest first, then the previous
   generation, which covers a crash between writing the commit and writing the save). If it finds one it first copies the
   records it is about to replace to `commits/discarded.json`, then writes the committed records over the working ones.
   Players who joined after that save have nothing to restore and keep their records. A new world, or a save without a
   matching commit, restores nothing (F8 shows "Player records may be newer than this save" when commits exist but none match).
3. The host's *own* character is inside its save file and needs no commit.

Result: reloading a host save, from the same slot or after a crash, brings the world and every player back to the same moment.

## Reconnect and identity

- Records are keyed by identity (Steam ID, or the persistent local identity), never by slot. A returning guest in any slot gets the
  same core and progress records back and does **not** create a character again (restoring clears the creation state).
- A different identity in the same slot gets its own records (a new character); it cannot see or touch another player's files.
- The same identity cannot be connected twice, and a guest cannot claim the host's identity (core handshake).
- Messages carry the sender's session; a blob for another session, identity or world is ignored.
- The UDP transport still does not authenticate a claimed Steam ID (docs/PLAYER-DATA.md).

## When something goes wrong

| Situation | Result |
| --- | --- |
| Guest crashes between checkpoints | The player returns to the last acknowledged checkpoint (at most about 5-10 s of progress is lost) |
| Network cut during an upload | Nothing is stored (blobs are all-or-nothing); the next checkpoint repeats it |
| Host disk fails between `.tmp` and the rename | The old record stays whole; the upload is retried after 2 s |
| Primary progress file damaged | The `.bak` copy is used; the next upload repairs the primary |
| Both copies unreadable, for another identity or world, or from a newer MistriaMulti | The guest waits with "The host progress record needs recovery"; nothing is overwritten. Restore the file from a backup or from `commits/` |
| Host crashes and the save is reloaded | Rollback to the save's commit; the newer records are kept in `commits/discarded.json` |
| The game rejects part of a record | That section is skipped (and not uploaded); F8 shows a message; the other sections work |
| An update fails validation on the host | `progress_error`; that section is not sent again this session |

## Known gaps

These are personal in nature and still **copied from the host's save** into a new guest's game (not carried):

- Villager dialogue counters and date counters that data files write as world facts (`da_<npc>_<date>`, ...).
- Other saved appearance presets, `last_bed_used`, `save_position`, `active_mist_sight`, transient buffs and `status_effects`.
- The statistics logs (cooked, caught, harvests, purchases, ...), so log-based achievements start from the host's totals.
- Date photos.
- Personal quests that need a world object (a turn-in box) are restored without that object: a guest's copy of the world does
  not get the box, so such a quest cannot be handed in until the quest feature exists.
- A museum donation by a guest is not saved (the museum is shared and needs a host request).
- Records of players seen only by a version without this feature are not part of the commit until they rejoin once (the host cannot
  list the folder).
- Loading a save made before this feature has no commit: the working records are used as they are, once.
- Two saves of the same slot on the same in-game day, where the second is interrupted, restore the newer commit (same day, tiny
  difference).

## Assumptions about the game that could not be verified here

The mod runs only inside the game, and this work was written against the game's scripts and the MMAPI documentation without
being able to run either. Each of these must be confirmed in the game (the checklist below covers them):

1. `save.game_saving` and `save.game_loaded` fire as documented for the host's autosave and manual saves, and the loaded save's
   path gives the commit name (`game-<id>-autosave.sav` → `game-<id>-autosave_sav`).
2. `dialogue.romance_prompt_guard` greys out every pink prompt (dating, confession, proposal) of the NPC in the textbox.
3. `json_stringify` writes a struct member holding `undefined` as `null` and `json_parse` returns `undefined`/`pointer_null` for it
   (the code accepts both and an absent key).
4. `file_rename` replaces an existing file (the core record already relies on it), and `try_read_json_file` returns `undefined` for a
   missing or broken file.
5. The engine functions and names the code calls exist as in the scripts: `item_id_to_string`, `monster_id_to_string`,
   `season_to_string`, `tutorial_to_string`, `date_to_string`, `animal_kind_to_string`, `child_id_to_string`,
   `child_skin_tone_to_string`, `child_stage_to_string`, `child_location_to_string`, `utero_to_string`, `object_id_to_string`,
   `location_id_to_string`, `npc_id_to_string`, `perk_to_string`, `spell_to_string`, `sex_to_string`, `try_string_to_npc_id`, `serialize_array_bool`,
   `HashSetFromArray`, `MapWrap`, `List`, `Inventory`, `clone_value`, `opt_and_then`, `is_nullish`, `array_create_ext`,
   `default_cosmetic_unlocks`, `create_default_mount`, `report_children_facts`, `serialize_renown_entry`, `deserialize_renown_entry`,
   `ari_has_recipe_anywhere`, `Child`, `ActiveQuest`, `QUESTS`, `QUEST_LOG`, `LETTERS`, `MANUAL_QUEST_UNLOCKS`,
   `REQUEST_BOARD_READ_ENTRIES`, `GAME_STATS`, `RENOWN_REWARD_INVENTORY`, `MAXIMUM_REACHED_DUNGEON_LEVEL`, the `Utero`, `Sex`,
   `Tutorial`, `Date`, `ChildId`, `ChildStage`, `ChildSkinTone`, `ChildLocation`, `QuestCategory` enums (each with `LEN`).
6. Building an `ActiveQuest` directly (instead of `QUEST_LOG.start`) is enough for the quest log and menu to show and complete
   the quest; `Inbox.contents.clear()` followed by `deserialize` replaces the mailbox; `T2R.update_daily()` is safe to call while
   no cutscene runs; replacing `ARI.*` arrays and sets by new objects is safe (nothing caches the old ones).
7. A struct key is a valid name for `[$ name]` lookups with the names above; the `Date`/`Tutorial`/... names are unique.
8. The Rust-backed saver ignores nothing we rely on: this feature adds nothing to the game's own save files.

## Tests

`python3 tests/test_progress.py` (about 3 minutes) runs the real GML of the progress, player-sync, player-data (storage) and
identity files over the event layer and its simulated network, with only the game faked: every section round trip, defaults,
validation of 43 malformed sections and records, migration, readiness gating, a new guest, delta uploads, returning guests in
other slots and accounts, a core-only record, crash between checkpoints, damaged/foreign/newer records, an interrupted host write,
refused and oversized sections, protocol abuse and replays, the flush, the save commit and rollback (including restarts, missing,
damaged and foreign commits, two generations), one partner per NPC (race, break-up, host partner, restart, late joiner), the spouse
registry (only marriages, one spouse per player and per villager, break-ups, restarts, a player who is away, a late joiner, a hostile
list), the story-rewards ledger section (round trip, 12 malformed variants, empty for a new character, replacing the host's), a 134 KB
record in multi-chunk blobs, and a section that fails to restore. It also needs `python3 tests/test_event_features.py` and
`python3 tests/test_event_layer.py` to keep passing. None of this runs the real game.

## In-game checklist

Use two game installs (or one plus the `tests/test_live_game.py` peer), a host world on an autosave, `mistrimulti.progress` and
`mistrimulti.player_data` in the MMAPI debug console when it is enabled. Tick each item.

1. Startup: the log shows no error; the manifest hooks `save.game_saving`, `save.game_loaded`, `dialogue.romance_prompt_guard` are
   accepted by MOMI.
2. **New guest.** Join; create the character. Check: default recipes only, empty quest log (story quests as the host), a welcome
   letter, tutorials appear, host-only unlocks (cosmetics, recipes) are absent. The guest becomes visible to the host only after the
   record loads.
3. **Checkpoint.** Craft with a new recipe, read a letter, sell items, kill a monster. Within ~10 s `mistrimulti.progress` on the guest
   shows `saved_revision == revision` and the host's `players/<id>.progress.json` changes (only those sections).
4. **Leave and rejoin** (same slot, another slot, game restart): the character, recipes, mail (read state), quests, almanac and
   counters come back without the character creator.
5. **Another account** in the same slot: new character, nothing of the first player.
6. **Quests.** Start and finish a fetch/heart quest on the guest: it is personal (the host's quest log is unchanged); a story
   quest advanced by the host shows as the host's on the guest after rejoining. Look at the quest menu for odd entries.
7. **Cutscenes.** A cutscene the host saw is not replayed for a new guest; a romance scene the guest plays is saved and not
   replayed after rejoining.
8. **Romance.** Guest A starts dating a villager; guest B's pink prompts for that villager are greyed within seconds, other villagers
   stay open. A breaks up: B can start. Try both at once (race): the second is told and set back to "best friend". Check the host's
   own partner is protected. Check that proposals/weddings for the guest work (children, wedding date). The guest's spouse lives at
   the farm in the host's game too: `mistrimulti.progress` on the host lists them under `spouses`; the full check is in
   `docs/SYNC-STORY.md`, checklist 23 to 30. Dating or engaged is not a spouse (`spouses` stays empty).
9. **Children / pending child** of a guest survive a rejoin; `report_children_facts` shows the right facts.
10. **Host save commit.** Guests play; the host sleeps (autosave). Check `commits/game-<id>-autosave_sav.json` exists and holds the
    guests' records. Let a guest gain items, then kill the host game without saving and load that autosave: the guest returns to the
    committed state, and `commits/discarded.json` holds the newer one. Repeat with a manual slot.
11. **Damage.** With the host closed, damage the primary progress file: the guest still joins (from `.bak`). Damage both: the guest
    waits with the recovery message and nothing is overwritten.
12. **Size.** After a long session `mistrimulti.progress` sizes stay well under 96 KiB per section.
13. F8 shows a readable message for each failure above; the game never crashes; the debug console is not needed in normal play.
