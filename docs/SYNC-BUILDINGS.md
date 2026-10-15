# Building interiors: barns, coops, the greenhouse and the mini museum

The inside of a player building is a *dynamic grid* (`DYNAMIC_GRIDS`, `dyn_index`). This page describes how the mod shares what
is inside, by extending the existing features instead of adding a parallel one:

| Feature | File | What changed for interiors |
| --- | --- | --- |
| Crops, sprinklers, fences, (rocks, dig sites, weeds, trees if the game ever puts them there) | `MistriMultiFarm.gml` | Every interior is one more synchronised location: same scanner, deltas, digests, chunks, harvest/tool/edit requests |
| Soil and watering | `MistriMultiTerrain.gml` | Tiles carry the interior's name; snapshot of the greenhouses on join and when a guest walks in |
| Furniture (feeders, troughs, decor, machines such as apiaries and terrariums) | `MistriMultiRanch.gml` | Placement requests, the host ledger, the snapshot for joiners and the machine records name the interior |
| Chests inside | `MistriMultiContainers.gml` | A chest in an interior gets a key built from the building's place |
| The names themselves | `MistriMultiBuildings.gml` (new) | `mistrimulti_grid_ref`, `mistrimulti_grid_by_ref`, room keys |

Animals, mangers and products in barns were already shared by `docs/SYNC-RANCH.md`; this page adds what lies *inside* the walls
besides them. It has **never run in the real game**; the logic is tested with the engine stubbed.

## How an interior is identified

`dyn_index` is `DYNAMIC_GRIDS.count()` at the moment the building is written (`reserve_dynamic_room`), and a save stores the
count and each grid under its number. Two games that load the same save agree. They stop agreeing when a building is written
in a different order in each game (the host finishes one while a guest was away, a guest is told about a new building after
it built a different thing in another session, a guest's save is older or newer than the host's, a removed building leaves a
hole that only one of the games filled). Ranch sync already announces buildings to guests, and each guest's `write_node` then
takes **its own** next number. So the number can differ, and nothing on the wire uses it.

The building stands on the farm at a fixed place, which every game has. An interior is therefore named by the building's
top-left cell: `"b<x>_<y>"` (for example `"b72_52"`, no colon so room keys still split on the first colon). Every message that
says *where* carries `l`, either

* a number: a `LocationId` of a static location (the farm, the town, ...), exactly as before, or
* that string: the inside of the building at that place.

`mistrimulti_grid_ref(grid)` gives the `l` for a grid (`undefined` for a grid that is neither a saved static location nor the
inside of a farm building); `mistrimulti_grid_by_ref(l)` gives the grid back, and `undefined` for anything else (wrong type,
non-whole number, out of range, a name that matches no building, a name longer than 16 characters).
`get_buildings()` is the game's own list of the farm's buildings and is cached by the game; the mod asks it, never scans the farm
itself.

### Room keys

`mistrimulti_room_key()` (the `room` field of every frame) used to end in `string(GRID.dyn_index)`. It now ends in
`mistrimulti_room_part(GRID)`: `"undefined"` for a static grid (unchanged), the building's name for an interior, and the grid
number only for a grid that belongs to no known building. All "is this player in that room" checks (farm, soil, furniture,
machines, chests, ghosts of other players, dropped items) compare room keys, so players standing in the same barn now share a
room key even when their games number it differently (before, they would not have seen each other).
`mistrimulti_room_of_grid(grid)` is the key a player in that grid has.

## What is shared and how

### Farm nodes (crops, sprinklers, fences, ...)

`mistrimulti_farm_loc(l)` accepts both kinds of `l`. For an interior the state (`sig`, `kind`, chunk digests, edits, pending
digests) is kept per building name and rebuilt whenever the game replaces the grid (`mm_farm` token on the grid). The list of
synchronised locations is the static ones plus `mistrimulti_building_refs()`, recomputed every use, so a building finished
during the session is picked up without a restart. Everything in `docs/SYNC-FARM.md` then applies unchanged:

* the host scans, publishes `farm_delta`, sends `farm_digest`/`farm_chunk`; a guest compares digests and asks (`farm_want`);
* a guest's harvest of an interior crop is claimed by `object.interact` and decided by the host; plantings, fences and
  sprinkler charges are predicted and reported (`farm_act` with `a: "edit"`); axe/pickaxe/shovel swings inside are taken out of
  the swing and asked of the host (`tool.targets`);
* host validation: an `active` peer whose **room key equals the interior's room key** (`mistrimulti_room_of_grid`) and who is
  within 128 pixels of the cell; the fields are validated as before.

New for interiors:

* **Walking in.** A guest that enters an interior (its current grid's token changed to a dynamic one) sends `farm_hello`; the
  host answers with the digests of every location, so a stale greenhouse is repaired within a second or two instead of
  at the next minute timer. A guest also says `farm_hello` when the set of buildings it has changed (a new building appeared).
* **A building one side does not have yet.** Digests, deltas, chunks and wants naming an unknown building are ignored (the
  location does not exist there); the guest's next `farm_hello` after the building appears repairs it.
* **Growth.** The game runs `grid.new_day()` for every dynamic grid on every game that runs the day, and the greenhouse's
  sprinklers water in `end_day`. The host's results are the truth: the host scans its interiors after the day like the farm
  (the day pass counts them), and a guest that ran its own day discards what it saw and takes the host's chunks.

### Soil and watering

`terrain` requests, `terrain_commit` and `terrain_snapshot` events carry `l` when the tile is inside a building (no `l`: the
farm, so old messages mean the same thing). The host checks the tile and `before` exactly as for the farm and additionally that
the peer's room key is that interior's. A guest's hoe or watering can inside is noticed by the existing `tool.targets` watch
(it now works wherever soil and water are shared: the farm and any interior). Watches belong to the grid they were made in.

Snapshots: on a join the host streams the farm as before and then the soil and water of every greenhouse (an interior whose
building has `player_building_kind == Greenhouse`); when a guest's room key changes to a greenhouse the host streams that one
greenhouse to that guest alone. That repairs water that a night, a sprinkler or a missed commit changed.

### Furniture and machines

`ranch_act` with `a: "place"` and `ranch_struct` records carry `l` as above. A guest's furniture placement inside a barn or
the greenhouse is vetoed locally (`furniture.place_guard`), sent as a paid request, validated by the host (the object may stand
in that location per the game's `placeable_locations`, the free tile and the item are checked by the game's own `write_node`,
the player is in that room), applied on the host and announced to every guest, who place it in their own copy of that interior.
The host's own placements are confirmed from the game's placement counter and announced the same way. The host's ledger of
placements is replayed to every joiner and to a rejoining guest; a placement that names a building the guest does not know yet
is retried for 600 ticks (10 s). Machines (apiary, terrarium) inside a building appear in the world record under the
interior's name, and "give an item to a machine" is validated against the room.

### Chests inside buildings

A chest's key is `"<LocationId>:<building name>/<x>,<y>"` (for example `"5:b64_52/4,4"`); previously interior chests had no key
and were not shared. The host checks that the player using the chest is in **that** building (a room key comparison), not only
in a location of that kind (two coops share the location). The rest of `docs/SYNC-CONTAINERS.md` is unchanged.

### The mini museum

It is a farm building like the others, so its interior is addressed, scanned and (for furniture and chests) shared by the same
code. The museum's *collection* (donations) is player and world state that has nothing to do with the grid and is not handled
here.

## Not covered

* **Picking furniture up** inside a building (as on the farm): not intercepted; the digests do not restore furniture (the farm
  sync owns only fences and sprinklers; other furniture is the ledger's), so the object stays in the host's copy.
* **Items lying on the ground** inside a building: `MistriMultiDrops.gml` still ignores dynamic grids.
* **Animals' positions**, mangers and products: `docs/SYNC-RANCH.md`.
* `NpcFarm` tiles and the greenhouse's `greenhouse_watered_positions` (a save-time record of which tiles were watered) are
  not special-cased: the water state is the grid's `node_terrain_is_watered`, shared by the terrain feature.
* A building finished or destroyed during the session while a guest is inside it.
* Players with a different save of the farm (a building at another place, a missing building): their interior has another name
  and nothing is exchanged for it.

## Tests (stand-in)

`python3 tests/test_buildings.py` (about 3 minutes) runs the real `MistriMultiBuildings.gml`, `MistriMultiFarm.gml` and
`MistriMultiTerrain.gml` over the lossy simulated network, with a greenhouse and a barn whose `dyn_index` is different in
guest 1:

| Test | What it checks |
| --- | --- |
| identity | Same name and room key in games that number the grids differently; hostile names (wrong types, ranges, lengths, a LocationId of a template grid) are refused; a grid that belongs to no building has no name |
| join and changes | Stale and missing crops/fences/sprinklers converge by digests; objects the sync does not own survive; digests of every location are equal; the host's harvest, planting and a day of growth reach every guest |
| guests act inside | Two guests racing for one crop (one yield, own inventory), a regrowing crop, plantings, sprinkler charge, fence, an unsound planting refunded; a guest outside (named or not) is refused |
| guest tools inside | A pickaxe swing is taken out of the swing, decided by the host, and the yield is the swinger's |
| entering, unknown building | Walking in repairs a drifted greenhouse at once; a building one game lacks is ignored, then converges when it appears |
| terrain | Host commit, host and guest watering, room check, forged places (wrong types, the barn's name, numbers), snapshot on entering and on (re)joining |
| hostile input | Forged and malformed names and contents in every event kind: no errors, nothing changes |

`tests/test_ranch.py` gained `test_furniture_inside_buildings` (veto, host decision, payment once, a race, host placements,
room and name checks, hostile names, late joiner) and `test_machine_inside_a_building`; its fake now gives every game a different
`dyn_index`, so all the older ranch scenarios also prove that nothing depends on the number. `tests/test_containers.py` gained
`test_chest_inside_a_building`. `python3 tests/mutate_buildings.py` breaks 16 rules of the GML (name by number, room key by
number, no room check, no snapshot on join or on walking in, ...) and requires a test to fail for each.

## Assumptions only the real game can confirm

1. `get_buildings()` returns the farm's buildings with `top_left_x/y` and `dyn_index`, and `DYNAMIC_GRIDS.get(dyn_index)` is the
   inside's grid (`undefined` for a removed building). Read from `Buildings.gml`, `BuildingUtils.gml`, `GridUtils.gml`.
2. The interior grid has the fields the farm sync already assumes of the farm grid (`dims`, `node_object_id`, `node_parent`,
   `write_node_without_initializing`, `initialize_node_renderer`, a new field `mm_farm` accepted), and `GRID` is the same
   struct as `DYNAMIC_GRIDS.get(i)` while the player is inside.
3. A player's `x`/`y` inside a building are `cell * 8` in that interior's own coordinates (the reach test uses `cell * 8 + 8`).
4. Nodes written into an interior that is not the room the player is in get their renderers when the player walks in (the same
   assumption the farm sync makes for other static rooms).
5. `grid.new_day()` for the dynamic grids runs on the host like the farm's, and the greenhouse crops grow only on tiles the
   host has watered (sprinklers in `end_day`, water from guests through the terrain feature).
6. Greenhouse soil: `GroundKind.Soil` tiles in the crop area, `RiverBank` elsewhere; the hoe, the watering can and seeds work on
   the soil like on the farm (`can_plant_seed` conditions are the farm's, replayed in `mistrimulti_farm_can_add`).
7. `LocationId` strings (`location_id_to_string`) of interiors are the same in every game, and two interiors of one kind have
   different names (they stand at different places).
8. Placing an object inside a barn or the greenhouse works through `grid.write_node(x, y, object, rotation)` on the interior grid
   without the player being in that room (as it does for the farm and the house in the ranch sync), and `GAME_STATS.furniture_placed`
   counts it (the host confirms its own placements by that counter).
9. A chest in an interior is in `STORAGE_NODES`, with `parent_grid` the interior and no `parent_node`.
10. Walking into a room changes `mistrimulti_room_key()` within the 60 ticks the boot tick needs to call the room settled; the
    host sees the new room in the guest's next frame.

## In-game checklist (two computers, same save, the farm has a greenhouse, a coop and a barn)

Do each step with the guest standing inside, then repeat once with the host inside and the guest outside. Watch `F8` and, with
the MMAPI debug agent, `mistrimulti.farm` (a `locs` entry per interior, `"b72_52"` style, with equal `digest` on both) and
`mistrimulti.events` (`backlog` back to 0).

1. **Naming.** In the debug agent check that `locs` lists the same interior names on both games. If you built or removed a
   building in only one game before, note whether their `dyn_index` differ; everything below must still work.
2. **Greenhouse crops.** Host plants and waters a seed in the greenhouse: the guest sees it when it walks in. Guest plants a
   seed on a soil tile: the host has it, the seed left the guest's bag once. Plant on a non-soil tile: nothing stays and the seed
   returns.
3. **Watering.** Guest waters the greenhouse: the tiles are dark on the host. Host waters: the guest's tiles are dark. Sleep:
   next morning both games show the same crops and the same wet tiles; walk in with the guest and check again.
4. **Harvest.** Both press harvest on the same ripe crop: one yield, the other's game stays quiet. A regrowing crop (strawberry)
   goes back to growing on both.
5. **Sprinkler.** Place a sprinkler in the greenhouse (guest, then host) and charge it: it waters the same tiles on both after
   the night.
6. **Barn and coop.** Place a feeder/trough/decor inside (guest): it is vetoed, appears for both, item gone once; two players on
   one tile: one wins. Host places furniture by hand: the guest sees it. Walk out and in again, restart the guest (rejoin): the
   furniture is still there.
7. **Chests.** Put a chest in the barn and one in the greenhouse; a guest in the barn takes an item: the host's chest changes. A
   guest on the farm cannot take from the barn's chest by any menu.
8. **Machines.** An apiary or terrarium inside a building: hand in the requested item from the guest: one reward.
9. **Mini museum.** Place furniture and a chest inside it; both appear for both players.
10. **Late join.** A third player joins after all of this: inside every building the contents match within seconds (use the
    `digest`).
11. **Different numbers.** If two games number the interiors differently (the debug agent shows it), repeat steps 2 to 7 there:
    this is what the whole page is about.
12. **Fail-soft.** With the debug agent, break a call on purpose (rename the node field `stage` in the farm GML): the game keeps
    running and the farm feature switches itself off after 40 errors, as before.
