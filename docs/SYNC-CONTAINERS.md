# Containers, world items and gifts

Files: `mod/mistrimulti/gml/MistriMultiContainers.gml` (chests), `MistriMultiDrops.gml` (items on the ground, gifts, loot
seeds). Built on the event layer (`docs/EVENT-LAYER.md`). Tests: `tests/test_containers.py`.

The rule for everything here: **items are never created or destroyed by the network code.** Every movement is a transfer
between two places (a chest slot, a player's inventory, an entry in the world item table), and a transfer is applied by the
host exactly once or refused as a whole.

## What is shared, what is not

| Thing | Decision |
| --- | --- |
| Chests, fridges, turn-in boxes (any furniture node with `interaction_chest`) | Host-owned. Replicated to every guest. |
| **Shipping bins** | **Per player, never synced.** See below. |
| Items on the ground (`obj_item`) | Host-owned table with ids, published 2 s after they appear. |
| Gifts between players | An entry in the same table that only the recipient can claim (F9). |
| Loot rolls (treasure chests, rocks) | Seeded from the host's seed, so the roll depends only on (host seed, source). |
| Shop stock and prices | Per player and local. See [Shops](#shops). |
| Player inventories | Stay local to each game; mirrored into the host's record (see [Crash safety](#crash-safety)). |
| Not covered | Factories, auto feeders, seal tablets, the museum, Lost and Found, the player's own bed/closet menus (all other `Menu.Storage` users). |

### Shipping bins (decision)

The game's end-of-day sequence calls `sell_shipping_bin_items()` in every game that runs it, and pays the local player. If a
bin were shared, every game would sell the same items and every player would be paid for all of them. So bins are **per
player**:

- `MistriMultiContainers.gml` skips every node whose `interaction_chest.shipping_bin` is true: nothing about it is sent or
  received, and its menu is the game's own, untouched.
- Each game sells its own bin at its own end of day, and the proceeds go to its own player. A bin can therefore never be sold
  twice.
- A guest's copy of the world comes from the host's save and may contain the **host's** items in the bin. On its first sight
  of each bin in a session, a guest empties its copy (without giving anything to the player) so that it does not sell the
  host's items too. The host keeps and sells them.
- Limitation: what a guest has put in its bin when it leaves before sleeping is lost with its game (guests do not save the
  world). Players should sleep before leaving, or use a chest for items to keep.

## Chests: protocol

Every chest has a **key** (`<root location>:<x>,<y>`, nested grids add `<parent x>,<parent y>/`) and a **revision** that only
the host increases. A **slot state** is `{ it: item as LiveItem.serialize(), n: count }`. On the wire items travel in a
**pack**: `t` = the distinct items (only their set fields), `s` = `[[slot, index into t or -1, count], ...]`.

The host's inventory is the truth. A guest's `node.inventory` is a **replica** that the game's own menus edit freely
(the menus are not intercepted). Every bridge tick the code compares each slot's `updates` counter with what it saw; a slot
whose content differs from the last authoritative state ("base") is **dirty**.

| Kind | Direction | Content |
| --- | --- | --- |
| `chest_tx` (request) | guest -> host | `{ x: [ { k, t, o } ] }`: for one or more chests, ops `[slot, remove item index, remove n, add item index, add n]`. The change of every dirty slot since the last request, in ONE request. |
| result of `chest_tx` | host -> everyone | `{ ok, x: [ { k, v, t, s } ] }`: per chest the new revision and the authoritative state of every slot the request named. On refusal `ok:false` with the current states. |
| `chest_state` (event) | host -> everyone | `{ k, v, t, s }`: slots the host (or the game's own code) changed. |
| `chest_open` (request) | guest -> host | `{ k }`. The host streams the whole chest as `chest_snap` events to that guest, then answers. |
| `chest_snap` (event) | host -> one guest | `{ k, v, n, t, s, e }`: a slice (<= 5.5 KB) of the chest as of now; `e` marks the last slice. |

**Host, applying `chest_tx`** (once per request id, by the event layer): validates shape and ranges (`≤ 8` chests, `≤ 128` ops each,
`≤ 64` distinct items, counts `1..9999`, no slot twice, known item ids, no self-using items, `≤ 6500` bytes), that the guest is
in the chest's location, then applies every op in order. An op is: remove `rn` of item A from the slot (the slot must hold at
least that many of an equal item), then add `an` of item B (`slot.room_for_item(B) ≥ an`: stack limit, tags, soulbound).
If any op fails, every touched slot is restored and the request is refused. Because ops are **deltas, not absolute states**, two
guests taking different amounts from one stack both succeed; the second fails only when not enough is left.

**Guest, applying any authoritative state** (`__mistrimulti_ct_reconcile`): the slot has no unsent edit -> it becomes the
host's state. The slot has an unsent edit of the same item -> counts merge (`local + auth - base`); if the merge is
impossible (the host has less than the menu already took) the difference is taken back from the player; if it overflows the
stack, the excess is given back. An unsent edit of a different item is undone. The menus refresh by themselves because the
slot's `updates` counter changes.

**Guest, refused or lost request**: for every slot of the request the menu's movement is undone on the player (items the
player received are removed from the hand/inventory, items the player put in are given back), then the slot takes the host's
state. All undo movements of a request are netted per item and applied gives-first, so nothing is "taken" that is still on its
way back. If the player already moved the items on inside the menus, they are pulled out of the puts that have not been sent yet.

**One request at a time per guest, all dirty chests together.** A later move may depend on an earlier one (take from chest A,
put into chest B). One request in flight, and everything dirty in one request, means a later put can never reach the host
before the take it depends on is settled; a refusal undoes both. Requests over the size limits (for example a sort of 54 very
different stacks) are not sent: the change is undone and a warning is logged.

### Revisions, joining, gaps

- Each host change batch increases the chest's revision by 1; every event and result carries it. A synced guest accepts
  revision `r+1`, ignores `<= r`, and on a jump marks the chest unsynced and asks `chest_open`.
- **Snapshot on join** (`on_peer`): the host streams every chest to the new guest in slices, the chests of the guest's own
  location first, two events per bridge tick, only while the host's backlog is below 16 events (back-pressure). A guest that
  was away (`on_peer` again, or `on_gap`) gets the same.
- **Lazy refresh on open**: `object.interact` (an override that always defers) makes a guest ask `chest_open` when it opens
  a chest. The menu opens immediately on what the guest has; edits made on stale contents are checked by the host.
- Alone, the host stops watching chests; the first guest gets a full snapshot.

## Chests: crash safety

Player inventories are checkpointed to the host about every 5 s. A chest transfer changes two places (the chest and the player
inventory) that are saved separately, so a crash between them would duplicate or lose items. Therefore, when the host applies a
transfer for a guest it **also edits that guest's stored player record** (`mistrimulti_ct_record_apply`): takes are added to
the record's inventory, puts are removed from it. The guest's next checkpoint replaces the record with its live inventory,
which says the same. The guest also asks for an immediate checkpoint after a pickup grant. A guest crash before its checkpoint
therefore reloads a record that already agrees with the chest. The same is done for world item claims, gifts and drops that
come out of an inventory. Remaining windows (unverified, see below): a checkpoint that was captured just before the guest
applied a reply and reaches the host afterwards overwrites the host's edit until the next checkpoint (sub-second plus the
checkpoint interval); an item the player consumes, trashes or drops from the hand between the take and a refusal cannot be
taken back (a warning is logged and the difference remains); a **host** crash rolls the chests back to its last save while
guests keep what they took (the usual rule of the event layer).

## World items

State per game: `table[id] = { id, loc, x, y, g: [[item, n]], by, f }`; the host's table is the truth; every other game mirrors
it. Every `obj_item` instance is a puppet of an entry, or a private item that nobody else knows.

1. **Appear**: any `obj_item` this game did not create from the table is polled each bridge tick. It is private for 2 s
   (`PUBLISH_TICKS`), during which the dropper's own pickup works as in the game and costs no traffic.
2. **Publish**: after 2 s (and only in a shared location, not in a per-player dungeon floor) `item_drop` (request) asks the host
   to create the entry; the answer is broadcast; the dropper's instance becomes bound to the entry and every other game spawns
   a puppet if it is in that room (and when it enters the room later).
3. **Pickup is a claim.** `obj_item` starts its own pickup by setting `kill_timer`/`kill_target = obj_ari`. Every frame the mod
   cancels this for bound instances the same way the game refuses a full inventory (`kill_timer = -1; lerping_to_player = false`)
   and sends `item_claim`. The host removes the entry and broadcasts; **every** game deletes its instance; the claimant (and
   only the claimant) receives the items (`give_item`, or `use_item_fast` for auto-use items). A second claimant gets
   `gone` and its instance disappears.
4. **Day change** (`game.new_day`, host): every entry is pushed into the host's `GRIDS[loc].lost_items` (the game's own place for
   items left behind, saved with the world), the table is cleared, every game destroys its puppets and the dropper's bound
   instances. A new loot seed is chosen.
5. **Save**: `game.save_guard` on the host removes the puppets for the moment of the save (the game would store them as lost
   items too) and respawns them half a second later.
6. **Host restart**: the table is gone with the host. Droppers' instances turn private again and are published again; puppets
   disappear; nothing is duplicated because no instance is ever granted without a claim.
7. **Back-pressure/limits**: 256 entries, 6 groups of one item id per entry, 999 units, 8 unconfirmed publications per game.
   A refused publication leaves the item private.
8. **Join**: the host streams the table (`item_snap`, 2 entries per event, 2 events per tick) with a `reset` flag first.

### Gifts (F9)

The game has no player-to-player transfer (gifts go to villagers). F9 takes the stack in hand and gives it to the nearest player in the room as
an entry with `f = recipient uid`, placed at their feet. The stack leaves the giver's inventory at once and the stored record
is edited; if the host refuses it, it is given back. Only the recipient can claim it (`locked` for everyone else, the instance
is shown but never picked up). Unclaimed gifts follow the day-change rule and become ordinary lost items of the host.

### Loot

A loot roll that matters is made from a seed the host chooses (per world session and per day, sent at join and in `item_day`):
`random_set_seed(FNV(seed + source))` runs from `dungeon.treasure_chest` (source = location + chest position) and from
`resource.node_picked` for a rock that breaks (source = location + rock position), and `randomize()` restores the game's own
randomness a few frames later. The outcome is a pure function of (host seed, source): no reroll, the same on every game. Nothing
else is rolled twice because each drop is published once (above). Tree chops and other drops are not seeded.

## Shops

Decision: **stock and prices are per player and local.** The game's shelves are unlimited (`constant_stock`) or a daily rotation
seeded from `Game.unique_identifier` and the day (`random_set_seed(Game.unique_identifier + days)` in `Stores.gml`), which is
identical on every game that loaded the host's save. Whether an entry is offered at all depends on the player's own progress
(`purchasable()`: recipes, cosmetics, one-time unlocks), and a purchase is paid from the buyer's own gold. Nothing needs to be
agreed between games, so nothing is synced; a purchase only changes the buyer's inventory and gold, which reach the host
through the player record. `store.purchase`, `store.stock` and `items.give` are therefore not used.

## Assumptions about the game that could not be verified here

1. `STORAGE_NODES` lists every node that has `inventory`; `node.parent_grid`, `grid.parent_node`, `grid.location_id`,
   `grid.dyn_index` exist as read in the scripts; the same chest has the same key and position in a guest's copy of the world.
2. The game's storage menu changes slots only through `slot.add/remove/swap/drain` and direct assignment, all of which
   increase `slot.updates` (the menus rely on it). `Inventory.sort()` and the stack button change slots the same way.
3. `ARI.give_item(item, count, ...)` and `ANCHOR.get_menu(Menu.Storage).left_menu.hand` behave as read in the scripts.
4. `object.interact` is called for chests (`Interact.gml`) with the node; the override returns `undefined` and so never claims it.
5. `obj_item` cancel: after `kill_timer = -1; lerping_to_player = false; v = 0` the item keeps lying there and chases again
   (the game's own full-inventory branch does exactly this). The mod's tick runs at least once between the start of the pickup
   (`kill_timer = 5`) and its completion (about 5 frames).
6. `with (obj_item) array_push(list, id)` yields instance ids usable with dot access and `string()`. `instance_create_layer` plus
   `setup(List)` plus `final_x/final_y/v_counter` spawns a resting item (the pattern of `restore_lost_items`).
7. `instance_destroy` inside `game.save_guard` is honoured before the game runs `store_loose_items_as_lost()` in the same call.
8. `random_set_seed` followed by `randomize()` leaves no lasting effect; the hooks `dungeon.treasure_chest` and
   `resource.node_picked` fire before the respective rolls (as the hook documentation states).
9. `end_of_day_status` is set while the end-of-day sequence changes containers (used to ignore the game's own bin changes
   on guests; bins are skipped anyway).
10. JSON `null` in a parsed item may arrive as `undefined` or `pointer_null`; `is_nullish` is used everywhere.
11. `mistrimulti_player_load/store` and `r.player_sessions[slot]` keep their meaning, and storing a record with the same revision
    is accepted by the guest's next upload.

## Known limitations

- Hostile guests: structure, ranges and capacity are validated; **provenance is not** (the host cannot check that a guest owned
  what it puts into a chest or claims to have dropped). Same as the rest of the player data.
- A refusal that must take items back from a player who has already put them into a request that is still in flight (only
  possible when the host changes the same slot at the very moment, with lag) records a **debt**: what the refusal of that
  other request gives back is cancelled against it. If that other request is accepted instead, the debt stays and one
  stack is duplicated; a warning is logged. The randomised tests with host edits at 20-200 ms intervals under 15-25% loss
  hit this about once in fifty runs; real menu use is far slower.
- Crafting from nearby storage on a guest consumes from its replica and is sent as a take; if it is refused the crafting
  result cannot be undone.
- Moving items between players through the same chest at the same instant is correct but can look jumpy (a refused move
  returns the items a moment later).
- Entries in a location other than the host's are only spawned when someone enters it.
- Furniture placement/removal is not synced here; removing a chest on a guest drops its replica contents as private items.
- Shipping-bin contents are lost if the guest leaves without sleeping.

## In-game checklist

1. Host + guest: put an item into a chest on the host, open it on the guest: contents match (also after the guest joins late).
2. Guest takes half a stack; the host's chest and a second guest's open menu update without reopening.
3. Both guests take more than half of one stack at the same time: exactly one succeeds, the other's menu corrects itself and its
   inventory has no extra items.
4. Take from chest A and put into chest B within a second while the network is lagging (use a throttled link): totals stay equal.
5. Kill the guest's game right after a transfer, restart it and rejoin: no duplicate and no missing item.
6. Sort and stack buttons in a shared chest; a chest with 54 different items.
7. Drop an item on the farm as the guest; the host sees it after about 2 s; both walk to it: only one receives it.
8. F9 with a stack in hand next to the other player; only they can pick it up; walk away from a refused give.
9. Sleep with unclaimed items on the ground: they are in the host's lost items next day, nothing is left on guests.
10. Shipping bins: put items in the host's and the guest's bins, sleep: each is paid for their own items only, nobody for the other's.
11. Break a rock and open a dungeon treasure chest on both players' games (same node, same day): same loot; random drops
    elsewhere still vary.
12. `mistrimulti.containers` and `mistrimulti.drops` (debug agent) show chests/synced/transactions and table/tracked/pending.
