# Mines sync: shared run and floors, monsters, rocks, chests and ladders

`mod/mistrimulti/gml/MistriMultiDungeon.gml`, on the event layer (`docs/EVENT-LAYER.md`). Tests: `tests/test_dungeon.py`
(about 20 s, no ports) and `tests/mutate_dungeon.py`. Nothing in this document has run in the real game yet; the logic and
wiring are tested with the engine stubbed, and [Assumptions](#assumptions-about-the-game-to-verify) lists everything that
still has to be checked there. The Farm package leaves the mines out on purpose (its location list skips
`LocationId.Dungeon`); this file is the mines' counterpart. Containers already seeds treasure-chest and rock loot per
(host seed, source) (`docs/SYNC-CONTAINERS.md`); that stays as it is.

## What the game does (read from its scripts)

- `enter_dungeon()` makes an **itinerary** (a list with one `{ impl, gm_room, biome }` per floor, from `create_dungeon_itinerary`,
  which uses the game's unseeded random numbers and the player's own `has_seen_arena_level_today`) and a `DungeonRunner` that
  holds it. Every floor is a **premade GameMaker room**; `build_dungeon_room()` fills it with rocks, ore, chests, forageables, dig
  sites, fish, bugs and monsters by rolling `chance_percent()` and `get_candidate()` on every "chance" tile (some chances and
  candidates depend on the player's perks). Nothing is seeded, and nothing is saved: leaving the mines throws all of it away.
- A floor's **ladder** appears when the destroyed pieces add up (`DungeonRunner.ladder_score`: monsters and
  `ladder_candidate` rocks and breakables) to a needed score drawn at the room start (`random_range`).
- A monster is a per-game `par_monster` instance with its own state machine; its AI targets `obj_ari`, the local player. Each
  species takes damage in its own `step_end` (`hit_points -= tarball.damage`), starts its Dying state when the health is gone,
  and pays **drops, essence and combat xp to the local player** from the death poof (`create_drops_and_essence`).
- The elevator menu and the best depth reached (`MAXIMUM_REACHED_DUNGEON_LEVEL`) are per player; the Progress package already
  stores it in the player's record (`docs/SYNC-PROGRESS.md`: "each explorer unlocks their own elevator floors").

## Decisions

| Question | Decision |
| --- | --- |
| Same layout for everyone on a floor | **Both.** A host-chosen run seed feeds the game's own generator (`random_set_seed` in `dungeon.room_build_begin`, per (run, floor)); the first game on a floor then reports what was actually built, the host keeps it as the **floor record**, and every later arrival reconciles with the record. The seed makes the reconciliation small; the record makes it correct when the generator is not deterministic (perks and the player's collection change what it rolls). |
| Where the floor record lives | In the **host's memory** (not in the host's room): it works while the host is on another floor or at home. A guest may found a floor; the host stores and arbitrates. |
| Movement of monsters | **Each game simulates the copy that chases its own player.** The AI cannot be shared (it reads `obj_ari`, and the host is often elsewhere); streaming one host-simulated copy would need all eleven species' state machines puppeted. Other players are not seen by the AI (limitation below). |
| Health, death | **Host-owned.** Every hit is reported, the host adds them up, and a game's copy never dies by itself. |
| Who is credited for a kill, drops, xp | **The killer: the player whose report takes the host's health to zero or below** (last hit, decided by the host in arrival order). That game's copy dies the normal way, so the drops, the essence, the combat xp, the kill count and the `monsters_killed` quest counters are that player's own, once. Every other game removes its copy without drops (`skip_destroy_logic`), but counts its share of the ladder score. Not pooled: the drops are physical items created in one game's room, and xp is a local stat. |
| Rocks, ore, chests, forageables, dig sites | **Host-owned, like the Farm package's nodes.** A swing or press that would yield something is asked of the host first; one game gets the yield. Hit points are pooled. Anything else that disappears (a bomb, a sword on a pot) is reported afterwards and removed everywhere. |
| Ladder | One per floor, in the place the first game that earned it put it (the host's record). |
| Elevator, depth record | Personal. Taking the elevator starts at any floor of the run that is going on; the best depth stays in each player's own record. |
| How long a run lives | Until nobody has been in the mines for 5 s, or the day changes. Floors keep their state meanwhile (leave and come back, other players arrive later). The next entry gets a new seed, a new itinerary and untouched floors, as in the game. |
| Different floors | Independent: a record per (run, floor). Players on different floors never see each other (the mines' room key carries the run and floor, `mistrimulti_room_key()`). |
| Not shared | Side rooms (treasure, ritual), the arena floor, the seal and boss rooms, fish and bugs, wave spawns and anything spawned after the floor was built. The game's own rules apply there. |

## The run

The host picks a **run** (a random id and seed) when its mines code first runs and sends `dg_run` to everybody (to a game that
joins, from `on_peer`). Both are known to every game **before** anyone enters, because a floor is built within a few frames of
the transition and no round trip fits in between.

`dungeon.runner_created` (event; the runner is already built and the first `goto_gm_room` has not run): the game's own,
unseeded itinerary is replaced by `create_dungeon_itinerary(count)` run again under `random_set_seed(hash(run seed, "itinerary"))`
(with `has_seen_arena_level_today` forced to false for the call and restored). The runner's side rooms stay as they were
(they depend on the player's perks and are the player's own).

`dungeon.room_build_begin` (event): if the floor is shareable (no side room, not the arena, not a special room, the run is
known and the host is reachable), `random_set_seed(hash(run seed, "floor:" + floor))`. `dungeon.floor_built` calls `randomize()`,
so the game's own randomness resumes before anything else rolls.

The host ends the run when `at[]` (who is on which floor) has been empty for 300 frames (5 s), or at `game.new_day`.

## The floor record

A game that has built a shareable floor asks `dg_act` / `here` one tick after `dungeon.floor_built` (the runner has finished its
room start by then). The host answers:

| Answer | Meaning |
| --- | --- |
| `found` | No record yet. This game is the **founder**: it captures its room and sends it. |
| `wait` | Another game is founding it right now. Ask again in half a second. |
| `snap` | A record exists. The host streams it (`dg_snap` events, targeted, 50 entries per slice, two events a tick, never with 24 or more events backlogged); the host's own game reads it directly. |
| `stale` / `off` | The run is over or unknown, or this game built another GameMaker room for that floor number (its itinerary disagreed): the floor is **not shared**. |

**Capture.** Every `obj_node_renderer` node that is a rock, ore, breakable (pot, chest), forageable or live dig site becomes
`[object name, x, y, hit points, open]`, every `par_monster` becomes `[monster name, spawn x, spawn y, health]` (a monster is known
by the pixel position it was spawned at, `original_spawn_pos`), plus the header `{ need (ladder score needed), lad (ladder tile),
rv (record revision) }`. Up to 800 nodes and 200 monsters. A founding host stores it directly; a founding guest sends it in
ordered slices as requests (exactly once, in order). A founder that stalls for 10 s loses the claim.

**Reconcile** (a game that is not the founder, and a founder after a host restart): the game's `ladder_score_needed` becomes the
record's; every shared node the record does not hold is erased with the game's own `erase_object_node_by_parent` (which also adds
its ladder score, as in the game); every record node the room lacks is built (`GRID.write_node`; forageables with
`CropFlag.FORAGEABLE | SPAWN_GROWN`); hit points and open chests are copied; every monster the record does not hold is removed
without drops, every missing one is spawned (`spawn_monster`), and health is copied. The natural ladder spawn is held back while
this runs (`dungeon.ladder_spawn` guard) and the record's ladder is built, if there is one.

**Results that arrive meanwhile.** Every mutation the host makes bumps the record's revision `v` and carries it. A game that is
waiting for the record keeps the results it receives (at most 300) and, after reconciling, replays those newer than the record's
revision. Nothing is lost between the snapshot and "live".

Until a game is live on its floor, its monsters and rocks behave as in the game (nothing is capped or reported); that window
is the round trip plus the stream, normally well under a second, and during it the player is still in the fade-in.

## Monsters

```text
tool/spell hit --> combat.damage (filter): note the full damage, deal at most hp - 1       (so no copy dies by itself)
species step_end takes what it takes (a shell or an invulnerable phase takes nothing)
next frame, monster.step_end: health below what was expected = damage taken
        --> dg_act / hit { floor, monster key, max(health lost, noted damage) }
host:   hp -= d. If hp <= 0 the monster is removed from the record and the reporter is the killer: { dead, k: slot }
result to everybody: { hp } or { dead, k }
        every copy: hit_points = hp (at least 1)
        dead, killer's copy: hit_points = 0 -> the game's own Dying state: drops, essence, xp, kill count, ladder score
        dead, other copies: skip_destroy_logic, instance_destroy, a death poof effect, ladder score
```

- **Simultaneous kills.** Two lethal reports reach the host one after the other; the first is the killer, the second finds the
  monster gone (`dead`, no killer) and its sender's copy is removed with no drops. Tested with three games striking at the same
  moment, under 8-25 % loss and duplication.
- **Damage over time** (venom) is reported by the same step hook; the tick that kills makes its reporter the killer.
- **Hits the species ignores** (the mushroom's shell, aerial phases) are not reported, because the health did not change. The
  hook reports what the copy actually lost, not what was thrown at it.
- **Health shown elsewhere.** Every copy follows the host's health: when another player wounds the monster your copy's health
  drops (no flinch, no damage number), and it dies when the host says so.
- Monsters spawned after the floor was captured (the arena's waves, summons) are not in the record and are not shared.

## Nodes

| Thing | Local effect first? | Rule |
| --- | --- | --- |
| Rock, ore (pickaxe) | No. `tool.targets` takes the cell out of the swing; the request goes out when the swing is final (charged tools: when released) | The host replays `pick_node`'s damage rules on the record (quality gate, `hp -= min(damage, hp)`). The requester then brings its node to the pre-state and runs the **game's own `pick_node`** with the swing's modifier, so drops, perks, xp and stamina are its own. Other games get the new hit points or the removal. |
| Dig site (shovel or pickaxe) | No | One game digs; the others lose the site. |
| Chest (press) | No. `object.interact` claims it | The first press opens it; the game's own `interact` runs for that player; the others see it open. |
| Forageable (press) | No | One game gathers it. |
| Breakables (pots), rocks broken by bombs, anything else | Yes | The game acts; the scan (every 10 frames) sees the node gone and reports it; the host removes it from the record; the others erase it. If two games break it in the same instant both get the drops: the one case that is not exactly once. |

The host keeps the record's node state per node (hit points, open). Two games chipping one rock add up: three hit points, two
swings of two, the second swing breaks it, one yield.

## Ladders

`dungeon.ladder_spawn` is a guard: while a room is being reconciled it vetoes the natural spawn; once the floor's ladder is known
(from the record or from a result) it vetoes every other spawn; and when a live game earns the ladder it reports the place
(`lad`), the first report wins, and the other games spawn theirs at that place (`spawn_ladder(x, y)` with the same inputs).
Because every game counts the same removals (its own kills, the others' kills silently, nodes erased by `erase_object_node_data`),
the scores agree and usually every game spawns at the same place anyway. When two games earn it in the same instant the loser
keeps a ladder at its own place (rare; the record says where the others go).

## Leaving, rejoining, passing out, the host

| Situation | What happens |
| --- | --- |
| A player leaves the mines (ladder up, pass-out at 2 AM, death, teleport) | The tick sees the location is no longer `LocationId.Dungeon` and sends `here` with floor -1; the host forgets where the player is. The floor records stay. |
| The same player comes back in the same run | Joins the run that is going on (the seed is the same, so the itinerary is the same); reconciles with the record: broken rocks stay broken, dead monsters stay dead, hurt monsters stay hurt. |
| Everybody has left | After 5 s the run ends and the host sends a new one; the next entry gets other floors. |
| The host leaves the mines, or goes to bed | Nothing changes: the record is in memory, and the host's own game is just another player. |
| A guest cut off from the host | The grace period is 5 s; then the floor is unshared in that game (monsters become killable by themselves again). A short loss only delays results. On return (`on_gap`) the game asks for the record again. |
| The host game restarts | It knows nothing. Guests inside the mines see the new host (`on_peer`) and ask again with `rj`: a host nobody has used yet **adopts the run** the guests are in, the first of them founds each floor from what its room holds *now* (the dead stay dead), and the others reconcile. Requests in flight are reported lost by the event layer and are not replayed. |
| A guest game restarts | A new event stream; it is a new player (a late arrival). |
| The day changes | The host starts a new run. |
| Player in a side room or the arena | That floor is the game's own; the player is not "on" a shared floor. |

## Events

| Kind | Direction | Content |
| --- | --- | --- |
| `dg_run` | host -> everyone, or one game from `on_peer` | `{ run, seed }` |
| `dg_act` (request) | any game -> host | `o`: `here`, `man`, `hit`, `pick`, `dig`, `use`, `gone`, `lad` plus `run`, `f` (floor) and the fields of the operation. The host's own game uses the same path. |
| result of `dg_act` | host -> everyone | Small: `{ ok, o, run, f, v, ... }` (monster key and health or death and killer; node cell and hit points or removal; ladder place). Applied by every game that is live on that floor; kept by games that are waiting for their record. The requester's own part (the engine action) runs from its reply. |
| `dg_snap` | host -> one game | A slice of the floor record: `{ run, f, i, n, nd, mo, h? }` |

Every field is checked by type, whole numbers and range before use: run and seed 1 to 2^31, floor 0 to 1000, cells 0 to 4000,
health 1 to 100000, damage 1 to 5000 per report, 50 entries per slice, known object and monster names only. The host answers
requests only from an `active` peer that the host has placed on that floor of that run. It does **not** verify reach, the player's
tool, or that a hit was really struck (a hostile guest can kill monsters and take rocks anywhere on a floor it is on; the same
trust level as the rest of the player data).

## Hooks

| Hook | Use |
| --- | --- |
| `dungeon.runner_created` (event) | Replace the itinerary with the run's. |
| `dungeon.room_build_begin`, `dungeon.floor_built` (events) | Seed the generator for the floor, then restore the game's randomness; start asking the host. |
| `dungeon.ladder_spawn` (guard) | One ladder, in the record's place. |
| `combat.damage` (filter) | Note the hit and cap what a copy can lose. |
| `monster.step_end` (event) | Report the health a copy lost. Hot path: the first checks are a struct lookup and a comparison. |
| `tool.targets` (filter) | Take pickaxe and shovel swings at shared rocks and dig sites out of the swing and ask the host. |
| `object.interact` (override) | Claim chest and forageable presses. |
| `game.new_day` (event) | The host starts a new run. |

All are in `requires_hooks`. Considered and not used: `monster.spawn` (it could cancel or move spawns, but the spawn set is
reconciled after the build, which also covers the record's own state), `monster.death` (fires after the drops are paid, so it
cannot gate them), `combat.damage_resolved` (fires before the species decides whether to take the damage; the health delta is
the better signal), `dungeon.side_room_range` and `interact.ladder_down_action` / `interact.elevator_action` (nothing to block),
`dungeon.treasure_chest` and `items.treasure_distribution` (Containers' loot seeds already make chest loot a function of the host
seed and the chest's place).

A small edit in the Containers package follows from this one: `__mistrimulti_dr_room()` (MistriMultiDrops.gml) returned the
location for the mines (a dungeon grid has no `dyn_index`), so items dropped in the mines were published to the host and shown on
**every** floor of every player. It now returns -1 for `LocationId.Dungeon`: items in the mines stay with the player who dropped
them. Sharing them per floor would need the floor in the entry's key.

## Assumptions about the game, to verify

Everything was read from the game's scripts (`enter_dungeon.gml`, `DungeonRunner.gml`, `build_dungeon_room.gml`, `par_monster.gml`,
the species, `obj_damage_receiver.gml`, `MonsterUtils.gml`, `GridUtils.gml`, `Pick.gml`, `Interact.gml`, `Breakables.gml`) and the
MMAPI hook pages. In order of risk:

1. **`create_dungeon_itinerary` is deterministic under `random_set_seed`.** It uses `List.shuffle`, `choose_random` and
   `HistoricalVotes.get_candidate`; if any of them draws from something other than GameMaker's `random` (or caches state between
   runs, like the vote dampening), two games get different itineraries. The room-name check then keeps their floors **apart**
   (unshared, with a log of nothing) instead of corrupting them, and the whole mines are simply unshared. Fallback if this
   fails: the host sends its first itinerary's `gm_room` names in `dg_run` and `runner_created` rebuilds the runner's list from
   them (it needs a name -> room lookup the scripts do not obviously have).
2. **`build_dungeon_room` is close to deterministic under `random_set_seed`.** Perks (`Treasured`, `FantasticFinds`,
   `HasVoidSight`) and collections change what it rolls and so shift the rest of the sequence. This is why the record exists. If
   the stream shifts a lot, many nodes pop in and out on arrival (visible, but correct). Required for full determinism: a seam
   around the per-tile roll so each tile can be seeded on its own (`dungeon.spawn_roll`), which the hook catalog does not have.
3. **`erase_object_node_by_parent` adds ladder score** (`GridUtils.gml` line 402, `DUNGEON_RUNNER.on_object_destroy`) and so
   does `DungeonRunner.on_monster_destroy`, called by hand for remote kills. Reconcile relies on it for the score.
4. **`combat.damage` sees the same tarball instance the species reads afterwards** and `tarball.damage` is what the species
   subtracts (`hit_points -= next_dmg.tarball.damage`, read in the species' `step_end` after `try_take_damage`). A species that
   reads damage some other way keeps dying locally; the verdict of the host would then arrive too late for it.
5. **Every species starts dying when its health is set to 0.** Read for the mite (`if hit_points > 0 { take damage } else if
   state != Dying { change_state(Dying) }`); every other species in `objects/Combat` has the same `hit_points > 0` guard
   (found by search; their dying branches were not all read), and the statue and the tome have their own handling.
   `mon.hit_points = 0` from a result is the only way the killer's copy dies.
6. **`monster.step_end` fires after `process_status` and before the species' damage check in the same `step_end`** (the hook page
   says: end of par_monster's end step; the species call `event_inherit` first). If the order is the other way round, venom could
   kill a copy locally before it is reported.
7. **`skip_destroy_logic = true; instance_destroy(mon)` is a clean silent removal**: the species' `destroy` calls the parent
   `destroy`, which returns before `on_monster_destroy`, the kill stat and `killed_by_ari`. `create_animation_effect(x, y, depth,
   spr_fx_small_monster_death_poof)` is a harmless stand-in for the poof.
8. **`monster.original_spawn_pos`** (a `Vec2` set in `par_monster` create) is the spawn position and unique per monster on a
   floor. Only monsters alive one tick after `dungeon.floor_built` are shared.
9. **`tool.targets`, `object.interact`, `pick_node` / `shovel_node` / `interact` from a mod tick, `TangoDoppel`, `GRID.write_node`**
   behave as the Farm package assumes (`docs/SYNC-FARM.md`, assumptions 1 to 4 and 10). Quality gates and `hp -= min(damage,
   hp)` are replayed from `Pick.gml`; a difference shows as a corrected node.
10. **`obj_node_renderer` instances have a `node`**, one per shared node (rocks, breakables, crops, dig sites), and
    `GRID.node_parent[ni] == node` identifies a live node. Chests have `prototype.chest` and `is_open`, and a renderer with
    `set_sprite` and `image_speed` (as `create_breakable_renderer` uses).
11. **`dungeon.ladder_spawn`'s `ctx.x` / `ctx.y` are the inputs of `spawn_ladder`**, which finds a free position by spiral from
    them; calling it with the same inputs on another game gives the same place if the grids agree around it.
12. **`asset_to_string(room())`** names the GameMaker room (as `DungeonRunner` uses it in an assertion).
13. **`MonsterId.LEN`, `monster_id_to_string`, `spawn_monster(x, y, id)`, `object_id_to_string`, `try_string_to_object_id`,
    `NODE_PROTOTYPES[id].chest / .minimum_quality`** exist as used (the first four are used by the Progress and Farm packages).
14. **`is_special_dungeon_room(room())`** is true for the seal rooms and the priestess and Seridia rooms; those have no
    `build_dungeon_room` pass and static grids.
15. **Cost:** capture and reconcile loop over all `obj_node_renderer` and `par_monster` instances once per arrival; the scan loops
    over at most 800 registered nodes every 10 frames; `monster.step_end` does one string, one struct lookup and one comparison
    per monster per frame. Measure in a big floor.
16. JSON numbers survive `json_stringify` / `json_parse` as whole numbers; `typeof(true)` is `"bool"` after `json_parse`.

## Known limitations

- **Movement is not shared.** Each player sees their own copy of every monster, chasing them. A monster far from you on your
  screen may be next to the other player on theirs. Other players are not targets for the AI. What is shared: health, death,
  loot credit. To share movement the game would need a seam that lets the AI pick any player (a `monster.target` filter, with
  the remote players' ghost positions) and a position stream; neither exists.
- **Hit feedback**: when someone else wounds a monster you see its health change (damage numbers only for your own hits) and
  it does not flinch.
- **The lethal blow lands one round trip late** (0.1 to 0.4 s; up to 50 ms more for the host). The monster stays at 1 health
  until the host decides.
- **The killer must still be on the floor.** If the killer left between its hit and the verdict (a fraction of a second), nobody
  gets the drops; the monster is gone.
- **Credit is last hit.** A player who does 90 % of the damage gets nothing if another lands the last 10 %.
- **Exactly once is guaranteed for monsters and for rocks, ore, dig sites, chests and forageables taken with the tools and
  presses above.** Pots, bombs and anything the hooks do not gate can be taken by two games in the same instant and pay twice.
- **Window before "live"**: during the first round trip on a floor the game plays by its own rules (a monster may die locally
  and then come back from the record; a rock may be mined locally and then reappear).
- **Seal rooms and bosses** (floors 20, 40, 60, 80, 90, 100; `rm_*_seal`, the priestess and Seridia rooms) are static special
  rooms with scripted encounters (`MIST` scenes). They are not covered: each player plays them alone. A shared boss needs the
  same treatment as a monster plus hooks into the scene scripts, which the catalog does not offer.
- **The arena floor** (waves of monsters from a scene) and **side rooms** (treasure and ritual rooms, depending on perks) are
  per player.
- **Fish and bugs** in the mines are per player.
- **Perks that affect combat** (`GenerousInDefeat`, `Treasured`, damage perks) work for the player who owns them, on their own
  copy; the host's accounting uses the damage reported, not the host's perks.
- **Damage taken** from monsters is local: your copy hurts you, not the other player.
- A hostile guest can report any damage up to 5000 per hit and claim any node on its floor. Reach and tool ownership are not
  checked.
- Items dropped in the mines are not shared (they stay in the game that dropped them); see the Drops note above.

## Tests

`python3 tests/test_dungeon.py [name ...]` runs the real `MistriMultiDungeon.gml` on the real `MistriMultiEvents.gml` over the
simulated helpers and lossy network (`Mine` in the test models one game's floor with the rules of the game's scripts; the
generator draws from the same `random_set_seed` the GML sets, so a missing or wrong seed changes the layouts):

| Test | What it checks |
| --- | --- |
| same floor | One run seed gives all three games the same itinerary (their own unseeded ones differ) and the same floor; a game whose perk changes its build is reconciled; a guest can found a floor that the host and another guest then join |
| seed matters | Floors are seeded from (run seed, floor); another floor gives another layout |
| two players, one enemy | Health pooled; three simultaneous lethal blows give exactly one killer, one drop set, one xp award, one kill count; every copy removed; ladder scores equal everywhere; under 8 % loss and 6 % duplication |
| poison and late hit | Venom is reported through the step hook and the lethal tick makes its reporter the killer; a hit the species ignores is not reported |
| nodes | Rocks (chip, then break by two players at once: one yield), ore (refused with the weak pickaxe, taken with the better one), a chest, a herb and a dig site opened or taken by two players at once: one yield; a pot erased without the hooks is removed everywhere |
| ladder | A floor cleared by three players has one ladder, in the same place everywhere; a second claimant is vetoed; a late arrival builds it where the record says |
| floors apart, leave and rejoin | Three floors at once are independent and have distinct room keys; a player who leaves and returns finds the floor as it was; an empty mine ends the run and the next one is new |
| host away, host restart | The host leaving changes nothing for the others; a restarted host adopts the run, guests re-found their floors from what they hold, kills still resolve once |
| big floor, join during changes, results during a join | A floor of several slices founded by one of three simultaneous arrivals under 10 % loss; a game joining while others fight and mine; results received during a join are kept and replayed only when newer |
| unshared floors, different rooms | Side rooms, the arena, an unknown run, a lost host and a different GameMaker room leave the floor to the game |
| hostile input | Two dozen forged and malformed requests, slices and results; no change, no errors; off-floor, absurd and fractional hits refused |
| loss matrix | 15-25 % loss, 10-30 % duplication, a partition: every kill and every drop set exactly once, the same floor everywhere |

`python3 tests/mutate_dungeon.py` breaks the GML in 21 ways (a copy that may die by itself, a remote kill that pays, nobody credited,
no seeding, no reconcile, no replay of results, a run that never ends, unchecked ranges, ...) and fails if any test still passes.

The tests cannot show that GameMaker runs the GML like the interpreter, that the hooks behave as assumed above, or the frame time.

## Checklist in the game

Two instances (host and guest), the same save, both with a few perks different if you can (Treasured, Fantastic Finds).

1. Host and guest enter the mines from the entrance at once. Floor 1 looks the same (rocks, chests, monsters). Take the
   F8 status and `mistrimulti.dungeon` (debug agent): `run` and `my_run` are equal, `st` is `live`, `floors` lists one record.
2. Descend together a few floors by the ladder. Same floors, same rooms. Make one player's perk different: nodes pop in or out
   within a second of arriving, then agree.
3. Both hit the same monster: its health bar and damage numbers follow; one player gets the drops and the combat xp, not both.
   Watch the other player's monster disappear in a puff.
4. Both strike at the same time with a killing blow (use a weak monster): exactly one set of drops. Repeat ten times.
5. Venom or fire on a monster: it takes the damage and dies once.
6. Mushroom monsters (shell): hitting the shell does not hurt it on the other player's screen either.
7. Both pick the same rock with the pickaxe, then an ore with a too-weak pickaxe (refused), then the same chest, a herb and a dig
   site: one yield each, the other player's node disappears or opens.
8. Clear a floor together: one ladder, in one place. Take it separately and together.
9. Different floors: one player goes down, the other stays; neither sees the other's ghost. The second goes down later: the
   floor is as the first left it (rocks broken, monsters dead).
10. One player leaves the mines and comes back: same floor, same state. Both leave, wait 10 s, enter: new floors.
11. Pass out at 2 AM in the mines (or die) and walk back in the next day: a new run.
12. The host walks out of the mines while the guest keeps fighting: kills and drops still work; the host walks back in and finds
    the floor as the guest left it.
13. Restart the host game while the guest is on floor 3, rejoin: the guest's floor stays alive, monsters killed before the
    restart stay dead.
14. Kill the guest's network for 15 s mid-fight; restore: the floor is brought up to date; with the host unreachable for longer
    the monsters become killable again.
15. Floors 20, 40 (seal rooms), the arena floor, a treasure side room (with the perk): each player plays them alone and nothing
    breaks.
16. Frame time in a floor with many nodes during arrival and during a fight with 6 monsters.
17. Fail-soft: break a call on purpose with the debug agent; after 40 errors the feature switches itself off and the mines play
    as in the game.
