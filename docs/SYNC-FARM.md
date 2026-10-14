# Farm world sync: crops, trees, rocks, forageables, weeds, fences and sprinklers

`mod/mistrimulti/gml/MistriMultiFarm.gml`, on the event layer (`docs/EVENT-LAYER.md`). Soil and watering stay in
`MistriMultiTerrain.gml` and are not duplicated here. Nothing in this document has run in the real game yet; the
logic and wiring are tested with the engine stubbed (`python3 tests/test_farm_sync.py`), and
[Assumptions about the game](#assumptions-about-the-game-to-verify) lists everything that still needs checking there.

## What is synchronised

The farm, plus every other static location whose `LOCATIONS[i].forageables` or `.dig_sites` is above zero
(forageable and dig-site nodes grow there too). Dynamic grids (the greenhouse, barn and coop interiors) are not covered.

| Object (category) | Host's own play | A guest's action |
| --- | --- | --- |
| Crops and forageables (`Crop`) | Seen by the scanner and published | **Harvest**: asked of the host, then the engine's own harvest runs for the guest. **Planting**: predicted, reported, validated. **Removal** (shovel): reported |
| Fruit trees and bushes (`Tree`, `Bush`) | Same | **Shake / pick**: like a harvest |
| Trees, stumps (`Tree`, `Stump`) | Same | **Chop**: asked of the host, then the engine's chop runs for the guest. **Sapling**: predicted, reported |
| Rocks and ore (`Rock`) | Same | **Pick**: like a chop |
| Dig sites (`DigSite`) | Same | **Shovel or pickaxe**: like a chop |
| Weeds and grass (`Grass`) | Same | **Cut** (sword, scythe): predicted, reported. **Planting grass**: reported |
| Fences, sprinklers (`Furniture` with `fence` or `sprinkler`) | Same | **Place / remove / charge**: predicted, reported |
| Everything else (buildings, chests, decor, machines, rugs, terrain) | Not touched by this feature | Not touched |

Growth, spawning and respawning (crop stages, tree stages and fruit, regrowing crops, new grass, forageables, rocks, dig
sites, season changes) are the game's daily code. They run in the host and reach the guests as described under
[Day change](#day-change).

## Design

### Nodes, records, signatures

Every synchronised node is identified by its **top-left cell** and described by a record
`[object name, x, y, state...]` of whole numbers (booleans are 0/1, an unset timer is -1, `variant_idx` is stored
multiplied by 100). The state per category:

| Category | State values |
| --- | --- |
| Crop | `ctx` (the crop flags), `stage`, `day_count`, `regrow_cycle`, `managed_timer` |
| Tree | `stage`, `day_count`, `hitpoints`, `fruiting_days`, `has_fruit`, `variant_idx` |
| Stump, Rock | `hitpoints`, `variant_idx` |
| Grass | `variant_idx`, `offset_x`, `offset_y`, `stunt_growth`, `day_count` (not part of the signature) |
| Bush | `day_count` |
| DigSite | `day_count` (not part of the signature) |
| Furniture | `cardinal_index`, `essence_supply` |

A node is *known* by one cell: its top-left cell, except a tree, whose top-left corner the engine leaves empty (the 6x6
square has four free 2x2 corners), so a tree is known by the cell two to the right. Each game keeps, per location,
`sig[cell]` (a number computed from the object and its state, 0 for nothing), `kind[cell]` and a digest per 8x8-cell
**chunk** (the sum of the signatures of the nodes known in it). A **scanner** compares the grid with `sig` a few
hundred to a few thousand cells per bridge tick (1500 for the player's location, 300 for each of the others; 4000 during a
first or post-day pass; never more than one pass of a location at a time), in slices of at most 256 cells. A pass of the
farm takes about a second. No node gets an added field: the game serialises every field of a node into the save.

### Who changes what

* **The host's own changes** (its harvest, its axe, the day's growth) are found by the scanner and published as
  `farm_delta` events: at most 40 records per event, the latest state of a node replacing an older queued one, nothing
  sent while `mistrimulti_event_backlog()` is 24 or more, and the scanner pauses if 6000 changes are waiting.
* **A guest's action with a yield is never performed locally first.** The yield is the point of the action, so the host
  decides it:
  * `object.interact` (override): on a guest, pressing harvest on a crop, bush or tree that `can_interact` is
    *claimed* and becomes the request `harvest`.
  * `tool.targets` (filter): on a guest, the cells of an axe, pickaxe or shovel swing that would hit a tree trunk, a stump,
    a rock or a dig site are taken out of the list, and each becomes a request `chop`, `pick` or `dig` once the swing is
    final: at once for a tool that cannot charge, when the button is released for one that can. The hook runs every frame of a swing;
    a gap of more than three frames between calls means a new swing, which may ask again.
  * The host checks the request (below), applies the **state change only**, and answers with the new state of every node
    involved plus the node as it was before. It drops no items and plays no effects for somebody else's action.
  * When the answer arrives, the requester (`on_reply`) first brings the node to the pre-state, then runs **the game's
    own function** (`interact`, `chop_node`, `pick_node`, `shovel_node`, with the swing's charge modifier) and the stamina,
    essence and xp bookkeeping the Tool state does, with the game's hooks bypassed. Drops, perks, xp and effects are therefore the
    requester's own, and the items go into the requester's own inventory exactly once: the event layer answers a request once,
    also after retransmissions, duplicates and reconnects. Finally the host's state is applied over the result. Every other
    guest simply applies the broadcast result.
  * If the player has left the room before the answer comes, a harvest gives the plain yield (`prototype.harvest` times
    `prototype.count`, which the answer carries) with `ARI.give_item`; a swing is lost.
* **A guest's action with no yield** (planting, cutting grass, placing or removing a fence, charging a sprinkler) is
  predicted: it happens locally, the guest's scanner notices it, and it is reported to the host as an `edit` request (up
  to 16 entries): `["a", record]` add, `["c", x, y]` cut, `["r", x, y]` remove, `["s", x, y, supply]` charge. The scanner
  reports only these transitions and only outside a silent pass. Everything else it sees in a guest's own grid (growth,
  spawns, a rock a bomb broke) is the host's to say; see the digests.
  The host validates every entry: the record, the reach, a free tile, soil for crops, grass for grass, `Placeable` tiles for
  saplings, a charge that only goes up, and removes only plain crops and removable fences and sprinklers. The answer lists
  the host's state of each cell, which corrects a refused prediction; a refused planting also comes back as the item to give
  back (`rf`), given once by the requester's `on_reply`.

### Host validation

A request must come from an `active` peer; the location must be synchronised; the peer's last frame must be in that
location (`room` equals the location id and `:undefined`) and within 128 pixels of the cell; coordinates and records are
checked for type, whole numbers, range and length; a tool must be an item of the right type (`ToolType`) and pass the quality
gate of `chop_node` / `pick_node`; the node must exist and be of a category the action works on (`can_interact` for
harvests; trunk cells for trees). The request payload is never trusted for counts, items or state.
Not checked: that the player really holds the tool or seed (the host's mirrored record of the guest's inventory is only
as fresh as its last checkpoint).

### Digests and chunks: join, rejoin, day change, repair

The host sends `farm_digest` events: the digest of every chunk, 128 per event, location by location. It does so
for a guest when the guest joins or re-enters (`on_peer`), when a guest says `farm_hello` (after its own day change,
after a gap, after a lost reply), for everyone after the day's pass, and for everyone once a minute. It never sends
one while changes are waiting to be published, so a digest describes the stream position it is sent at.

A guest compares each digest with its own once its first pass is complete (digests that arrive earlier are kept),
and sends `farm_want` for the chunks that differ (at most 24 per event, and it does not ask for a chunk again within a
minute). The host answers each wanted chunk with `farm_chunk` events of at most 40 records (a chunk has at most 64
cells), at most 4 chunks per tick and never with 24 or more events backlogged. The guest writes the records and, on the
last slice, **removes the synchronised nodes the chunk does not list**; a slice with any invalid record is dropped
whole, so a damaged chunk never deletes anything. Because only differing chunks travel, a stale save costs little, and
the same mechanism repairs anything missed: a lost event, a gap, the guest's own local growth, a rock a bomb broke.
A node that cannot be written in the guest (blocked by something this feature does not own) is asked for again
at most every minute.

### Day change

The game's `new_day()` runs wherever the sleep sequence runs it (`game.new_day` fires inside it). The host then
runs a **fast pass** over every synchronised location, publishing each changed node as a delta (a day can change
thousands of nodes: about 70 bytes each, 40 per event), and when the passes are complete sends the digests to everybody.
A guest that ran its own `new_day()` (it does not know whether it should) throws away what its scanner has seen,
re-reads its grid silently (so its own growth and random spawns are never reported as actions), and asks for digests;
whatever differs from the host's world is replaced by the host's chunks. Guests therefore never contribute growth or
spawns: the host's randomness and perks decide them. A guest that never ran the day simply receives the deltas.
The host does not scan while nobody is connected; when somebody arrives it reads its grids silently and then sends digests.

### Conflicts

| Situation | Outcome |
| --- | --- |
| Two guests harvest the same crop | The host handles the requests in arrival order: the first harvest changes the node, the second finds `can_interact` false and is refused with the current state. One yield, to the first. |
| A guest acts on a tile that has changed (felled tree, harvested crop) | Refused; the answer carries the host's state, which the guest applies (the swing played out nothing locally). |
| Guest and host chop at once | Both change the host's node in order; hitpoints never go below zero; a node already gone refuses the second. |
| A planting the host refuses (blocked, not soil, out of reach) | The guest's node is removed by the answer and the seed or sapling is given back. |
| Two guests plant the same spot | The first request wins; the second is undone and refunded. A guest's own change that its scanner has not reached yet is reported just before the host's state is written over it, so the loser is still refunded. |
| A guest cut or removed something the host does not allow | The answer restores it. |
| Host changed something while a guest's prediction was in flight | The ordered host stream and the answer's state both reach the guest; the later one wins. A stale queued publication of an anchor is replaced when a request touches it. |
| A guest's local world differs for any other reason (bomb, animals, a missed event, its own day) | Found by the next digest (at most a minute, or at once after a day change, join or gap) and replaced. |
| A host restart | The guests' outstanding requests are reported lost (`on_reply` with `lost`); the guest asks for digests. Whether the old host applied them is unknowable, so the layer never replays them. |

### Failing soft

Handlers and hooks catch exceptions and count them; after 40 the feature switches itself off for the session (the hooks
stand aside, events are ignored) and the game plays on. All incoming fields are validated (`is_struct`, whole numbers up
to a million, array lengths, known object names, even cells for the objects the engine writes on even cells).
`tests/test_farm_sync.py` feeds forged and malformed requests, results, deltas, digests, chunks and wants to hosts and guests.

## Hooks

| Hook | Use |
| --- | --- |
| `tool.targets` (filter) | Guest only. Takes tool cells that hit a synchronised yield node out of the swing and asks the host. |
| `object.interact` (override) | Guest only. Claims harvests of crops, bushes and trees and asks the host. Added to `requires_hooks`. |
| `game.new_day` (event) | Starts the day pass on the host; resets the scanner on a guest. |

Considered and not used: `resource.node_chopped` and `resource.node_picked` (they fire after the local effects, drops
included, so they cannot gate; the scanner already finds the host's own results), `resource.node_modifier` (it can
only change the modifier: a very negative value would heal a rock under a top-tier pickaxe, and dig sites and furniture
ignore it), `items.dig_artifact` (the digging player's own game rolls the artifact), `combat.tarball_grid` (bombs, fire
and monsters; they are left to the digests), `furniture.place_guard` (fires before the placement, which the scanner sees anyway).

## Assumptions about the game, to verify

Everything was read from the game's scripts (`Grid.gml`, `Chop.gml`, `Pick.gml`, `Shovel.gml`, `Interact.gml`, `Crops.gml`,
`Trees.gml`, `Stumps.gml`, `Rocks.gml`, `Grass.gml`, `Bushes.gml`, `Digsite.gml`, `AriFsm.gml`, `NewDay.gml`, ...) and the MMAPI
hook pages. None of it ran. In order of risk:

1. `object.interact` returning `true` claims the harvest and the game does nothing more (no animation, stamina or sound it
   would add after a `true` return). Crops, bushes and trees reach `interact(node)` through their `renderer.interact(...)`
   prompt. The node passed has `object_id`, `top_left_x`, `top_left_y`, `renderer`.
2. `tool.targets`: a list with cells removed is honoured (no callback for the removed cells, no stamina), an empty list is
   harmless, the hook runs on every step of the Tool state, `ctx.item.prototype.tool_type` is `undefined` for seeds, and
   `INPUT.check(InputId.UseToolCharged)` is true while the charge button is held. A tool that cannot charge
   (`quality_to_range_pattern(quality) == RangePattern.One`) swings at once.
3. Calling `interact`, `chop_node`, `pick_node` and `shovel_node` from a mod tick, outside the Tool state, with
   `new TangoDoppel()` and `doppel.resolve()` (as `Mist/Std.gml` does), behaves like the Tool state's call, and the node
   still has its renderer. `GRID` is the grid of the player's location. `ARI.gain_essence`, `modify_stamina` and `gain_xp`
   are called as the Tool state calls them.
4. Writing nodes: `grid.write_node_without_initializing(x, y, object_id, ctx)` (`ctx` is the crop flags for a crop and the
   rotation index for furniture) followed by setting the fields, `erase_object_node_by_parent`, and re-creating a renderer with
   `erase_object_renderer(node)` and `grid.initialize_node_renderer(node)` on a node that already has one (as
   `remake_room_renderers()` does for all nodes). `set_collision_on_node` as `tree_node_new_day` calls it.
5. A tree is known by the cell two to the right of its top-left (the corners of its 6x6 square are free:
   `write_tree_to_location` skips cells where both offsets are in {0,1,4,5}), and a stump left by a felled tree is
   written at `(top_left_x + 2, top_left_y + 3)` with the tree's `variant_idx`.
6. The node fields in the table above exist under those names, are the whole state that matters, and are restored
   by assigning them (the same assumption `load_objects` makes). `variant_idx` has two decimals.
7. `NODE_PROTOTYPES[id]` has `category_id`, `size` (not for trees: 6x6), `fence`, `sprinkler`, `cardinals`, `destructable`,
   `minimum_quality`, `stump_id`, `harvest`, `count`, `post_harvest_day_to_stage` (a list with `.get(0)`), `managed_regrow_days`.
   `try_string_to_object_id`/`try_string_to_item_id` return `undefined` for an unknown name instead of failing.
8. `LOCATIONS[i].forageables` is a number and `.dig_sites` a number when set; `GRIDS[i]` exists for every location of a
   loaded world; `grid.dyn_index` is `undefined` for static ones; the Grid struct accepts a new field (`mm_farm`).
9. The peer frame's `room` has the form `"<location id string>:undefined"` for a static location (as `mistrimulti_room_key()`
   produces); `location_id_to_string` and `point_distance` behave as in `MistriMultiTerrain.gml`.
10. Replaying the damage rules on the host (`hitpoints -= min(item.damage + modifier, hitpoints)`, the quality gates, the
    `-1` modifier of a charged swing, stump creation, `DigSiteDestroyed`) gives the same result as the engine run on the guest. The
    guest applies the host's state after its own run, so a difference shows as a corrected node, not a divergence.
11. Crop harvest state (`process_crop_harvest`, `MANAGED`, regrow cycle, forageables destroyed) is replayed from the script text.
12. Adding furniture with `write_node_without_initializing` works for fences and sprinklers (the fence autotile runs inside
    `write_furniture_to_location`), and `find_item_prototype(object_id)` finds the item that places an object.
13. The cost: the scanner reads up to about 4200 cells per bridge tick (6000 at most) and computes a signature for each
    node it passes; the farm has about 27 000 cells. Measure the frame time.
14. A guest that runs `new_day()` itself calls `game.new_day` once per day in the same way as the host.
15. JSON numbers survive `json_stringify` / `json_parse` as whole numbers.

## Known limitations

* Dynamic grids (greenhouse, barn and coop interiors) are not synchronised; `NpcFarm` tiles and the greenhouse's
  watered positions are not special-cased.
* Harvests, chops, picks and digs by a guest take one round trip (typically 0.1 to 0.4 s) before anything happens, and a
  swing taken out of the list shows no effect until then. The request goes out when the swing is final, up to a few frames
  before the blow lands (`tool.targets` is dispatched until the use acts), so a swing cancelled in those frames (the player
  is hurt) has already been asked for. If the host is not reachable the hooks stand aside and the guest's world drifts until
  the digests repair it.
* Bombs, fire, monsters and animals change a game's own grid without the host's say. The change is reverted by the next
  digest, but the items such an action dropped stay in that player's world (the same for the player's own predictions that
  the host refused: only the placed objects come back as items).
* Two players cutting the same weed or removing the same fence at once each receive the item (no yield is gated for these).
* Tool, seed and fence ownership is not verified by the host.
* Shoveling grass or dirt (terrain) is not synchronised, here or in `MistriMultiTerrain.gml`; a shovel on a crop is a removal.
* Other furniture (decor, chests, machines, rugs, house stairs) is not synchronised here; a sprinkler's essence stone is
  not drawn on remote games, only its charge counts.
* The tree shake's bug and shake-item rolls (`renderer.has_bug`, `has_shake_item`) are per game.
* The host's perks decide crop and tree growth for everyone (the growth code reads `ARI.perk_*` where it runs).
* The scanner reports at most 256 pending edits per location; further ones are left to the digests.

## Tests

`python3 tests/test_farm_sync.py` (several minutes: the GML is interpreted) runs the real `MistriMultiFarm.gml` on the real
`MistriMultiEvents.gml` over the simulated helpers and lossy network, with the engine stubbed (`Engine` in the test models
the grid, nodes, tools, inventory and the rules of the game's scripts):

| Test | What it checks |
| --- | --- |
| join | Stale saves (changed, missing, extra nodes, two locations) converge through digests and chunks; objects the sync does not own survive |
| host changes | The host's harvest, removal, planting and a day of growth and spawns reach all; the guests' own, different growth is overwritten |
| guest harvest | Two guests race for one crop (one yield, in the right inventory, with 10% loss and 20% duplication), regrowing crop, bush, fruit tree, out of reach |
| guest tools | Axe, pickaxe and shovel are decided by the host; the swinger gets the yield; wrong tool, reach and unreleased charge ask for nothing |
| guest edits | Planting, weeds, fences, sprinkler charge; racing, unsound and sapling plantings undone and refunded |
| conflicts | Stale tile, leaving the room before the answer, a second location, repair of a disagreeing guest, a lost reply |
| rejoin and gap | A guest that re-enters its world, or was cut off beyond the 10 s expiry, is brought up to date |
| hostile input | Forged and malformed requests, results, deltas, digests, chunks and wants; no errors, nothing changes |
| bulk | Hundreds of changes at once stay within the event budgets and the 16 KB frame |

It cannot show that GameMaker runs the GML like the interpreter (array copy-on-write, `json_parse` number types), that the hooks
behave as assumed above, or the frame time.

## Checklist in the game

Two game instances (host and guest), the same save, both on the farm unless stated.

1. Join: the guest's farm matches the host's (trees, rocks, crops, weeds, fences). Join again after the host has felled a tree
   or cut weeds in between: the guest ends up identical within seconds.
2. Host: till and plant a seed, water; the guest sees the seed. Harvest a ripe crop: it disappears on the guest. Chop a tree
   down: trunk, then stump on the guest. Break a rock; cut weeds with the sword.
3. Guest: harvest a ripe crop. Nothing happens for a moment, then the harvest plays and the item arrives in the guest's own
   inventory, not the host's. The crop is gone or regrowing on the host. Repeat with a regrowing crop, a bush, a fruit tree.
4. Guest: chop a tree with a basic axe (several hits), then a charged swing over several cells. Wood arrives for the guest only.
   Check the stump, then chop it. Pick a rock and an ore with a pickaxe too weak for it (the host refuses, the rock stays).
5. Guest: dig an archaeology spot with the shovel and with the pickaxe. The artifact is the guest's.
6. Both press harvest on the same crop within a second: only one gets the yield, the other's game stays quiet.
7. Guest: plant a seed and a sapling (host sees them), cut weeds with a sword sweep, place and pick up a fence, charge a
   sprinkler with an essence stone. Plant on a tile the host has changed in the meantime: the plant disappears and the seed returns.
8. Stand at the far edge of the farm and harvest something near the host: refused, nothing changes.
9. Sleep (host, or both). Next morning: both farms show the same growth, new weeds, forageables and dig sites; nothing the guest
   grew locally survives. Watch the F8 status and `mistrimulti.events` (backlog returns to 0). With the debug agent,
   `mistrimulti.farm` shows `errors`, queued work and a `digest` per location: the digests of host and guest are equal when the worlds agree.
10. Guest leaves to the town and harvests a forageable there; the host sees it gone.
11. Third player joining mid-day: gets the farm in seconds without freezing the others.
12. Kill the guest's network for 15 s, change things on the host, restore: the guest catches up.
13. Frame time: with a full farm of weeds, the game stays smooth during the first pass and during a day change.
14. Fail-soft: with the debug agent, break a call on purpose (for example rename the node field `stage` in the GML) and check that the
    game keeps running and the feature switches itself off after 40 errors, without crashing.
