# Ranch sync: animals, pet, products, buildings, furniture, machines, farm and house

`mod/mistrimulti/gml/MistriMultiRanch.gml` on the event layer (`docs/EVENT-LAYER.md`). It was written against the game's
own scripts and the MMAPI hook catalog, and its logic is tested with the engine faked (`tests/test_ranch.py`). **It has
never run in the real game.** The assumptions that only the game can confirm are listed below, with an in-game checklist.

## What is shared

| Area | Owner | How guests take part |
| --- | --- | --- |
| Animals in barns and coops: name, hearts, fed, petted, age, production counter, treat and pairing, babies in the making, birthday, cosmetic | host | host publishes each barn; guests apply it |
| Hand feeding, breeding treats, feed in the mangers, adopting | host | **paid action**: vetoed on the guest, the host decides, the guest pays on the "yes" |
| Petting, renaming, moving between barns, selling | host | **reported action**: the game does it locally, the guest tells the host, a refusal is undone once |
| Animal products | host | pooled in the barn, handed to whoever walks in first, once |
| Daily animal work (hearts, ageing, production, breeding) | host | guests never produce: `animal.production_gate` is false for them |
| The farm pet: name, hearts, fed, petted | host | in the world record; feeding is a paid action, petting a reported one |
| Furniture, blueprints, floors, wallpapers | host | **paid action** |
| New buildings | host | announced to guests when the host finishes one; guests cannot finish them |
| Apiaries and terrariums: the request and its reward | host | the request is in the world record; handing over the item is a paid action |
| Farm expansion, house size, upper floor, house look | host | **reported action** (the carpenter's menu charges at once) |

Not shared: positions and walking of animals (see below), mounts, the daycare, anything inside a barn that is not an animal,
a manger or a pool (auto feeder, ocarina statue, toys), pet jobs, picking furniture up, and the contents of machines and
turn-in boxes (those are containers; see the chest feature). Furniture and machines placed inside a building are shared
(`docs/SYNC-BUILDINGS.md`).

### Why animals are not streamed

Animals walk, path-find and eat from food markers with the game's own state machines, tied to the local grid. Forcing
positions from a stream of 20 packets per second per animal would fight those machines and use the bridge's bandwidth
for nothing a player can use. Each game therefore simulates its own animals and the **host owns their logical state**. The
one state that depends on place, "is it home tonight", is decided by the host's own copy at its day change. A carried or
ridden animal is local to the player doing it.

## The two kinds of action

### Paid actions: the guest pays on the host's yes

Hand feed, breeding treat, manger feed, adopting, furniture, blueprints, floors, wallpapers, handing an item to a machine.

1. The guest's press is vetoed (`input.take_press`, `items.use_guard`, `furniture.place_guard`, or the adoption menu's
   purchase method). Nothing is taken from the player.
2. The guest sends one `ranch_act` request, with what and where, never a price. One paid request at a time
   (`busy`), so the same held item cannot be promised twice.
3. The host validates against its own state and the game's data (the animal exists and is not fed, the tile is free, the
   item matches the object, the price is `buy_price * tier multiplier`, the requester is in that room), applies it as the
   game would, and replies `{ ok, pay: { g, it: [{ i, n }] }, ... }`.
4. The layer calls `on_reply` once per request id. Only there does the guest pay (`pay`), and it receives what the host
   says it earned (`items`, `ret`, `xp`).

| Situation | Result |
| --- | --- |
| Refused (`ok: false`) | nothing was taken; a notice says why |
| Reply lost, host restarted (`lost`) or answer forgotten (`expired`) | nothing was charged; the guest asks for a snapshot. A host that restarted from its save did not keep the action; if it did, the snapshot shows it and the item stays with the player |
| Duplicate or retransmitted request | the layer applies it once; the cached reply is repeated, `on_reply` still runs once |
| Two players, one animal, tile or machine | the host handles them in order; the second gets "already done" / "something is in the way" and pays nothing |
| The player no longer has the item when the yes arrives (thrown away meanwhile) | the action stands, the player pays what is left and gets a notice. This is the one way to get something for less; closing it needs an undo request |
| The host does not answer for 10 s | the guest can try again; a late yes is still honoured |

### Reported actions: the game acts first, the host decides

Selling, renaming, moving, petting, farm expansion, house upgrades. The game gives no seam before these (the menus do the
work inside closures), so they happen locally and the guest's tick notices the difference between its animals or
`FARM_EXPANDED`/`DECOR` and what the host last said, then sends a request (once per key while one is in flight).

| Situation | Result |
| --- | --- |
| Host agrees | nothing more (a sale whose real value differs from the guest's is corrected by the difference) |
| Host refuses (already sold, expecting, already bought) | the sale's gold is taken back, or the purchase (gold and items) is given back, **once**, from the cost the game's data defines |
| Answer lost because the host restarted | a sale waits for the first snapshot of the new host: if the animal is still there the sale did not happen and the gold is taken back; if it is gone, it stands |
| Host state arrives before the guest's tick noticed | the changes are reported first (`watch` runs before every barn and world message is applied), and an animal in a pending sale is not recreated |

## Replication

| Kind | Direction | Content |
| --- | --- | --- |
| `ranch_act` | request/result | the actions above; results of placements go to every guest |
| `ranch_stable` | host to guests | one barn: animals, fetuses, manger contents, product pool. Replaces the guest's barn |
| `ranch_world` | host to guests | farm expanded, house size/floor/look, floors and wallpapers per room, machine requests, the pet |
| `ranch_struct` | host to guests | buildings finished, placements of this session (and their removal) |
| `ranch_resync` | guest to host | send me everything again (after a lost answer, after the guest's own day change) |

* Barns are keyed by the position of the building (`"72:52"`), not by `dyn_index`, which each game assigns itself.
* The host publishes a barn when its record text changes (checked twice a second), the world record when it changes, and
  one barn every 3 s regardless (repair: a guest's own day-change work may have touched its copy). After its own day change
  it sends everything again, and a guest asks for everything after its own.
* A **snapshot** goes to any game that appears (`on_peer`): placements and buildings, every barn, then the world record,
  which carries how many barn messages to expect. The guest is `synced` when all arrived (barn records may be blobs, which
  are not ordered against events). Until then guests' paid actions are held with "Waiting for the host".
* Records are validated field by field (types, ranges, string lengths, known kinds and variants, at most 48 animals).
  Rejections are logged and ignored; messages from anyone but the host are ignored.
* **Host restart.** The first message of a new host stream makes the guest forget what it believed about the old one
  and take back the placements it applied for it (the new host sends the ones that survived). Guests that were away
  longer than 10 s receive a fresh snapshot because the host sees them appear again.

### Products

With players connected, `animal.product_drops` moves the day's products from the (empty) ground drop into the barn's pool.
The pool travels in the barn record. Walking into the barn (a tick check on `GRID.dyn_index`) sends `collect`; the host
hands the whole pool to the first request and the winner receives it through `ARI.give_item`. The pool is written to
`worlds/<world>/ranch.json` whenever the host saves and read back only when the day matches, so it follows the save's
timeline. With nobody connected the game's own drops are untouched.

### Placements

`rc.led` is the host's ledger of furniture and blueprints placed during the session, whether by a guest's request or by
the host's own hands (confirmed on the next tick by the game's placement counter). It is replayed to joiners and checked
every 2 s: an entry whose node is gone is announced as removed. Objects placed before the session are in every game's
copy of the save and are not tracked; picking up furniture is not synchronised (see below).

## Hooks

`animal.production_gate`, `animal.product_drops`, `input.take_press`, `furniture.place_guard`, `items.use_guard`,
`object.interact` (new in `requires_hooks`), plus `ui.menu_opened`, `game.new_day` and `game.save_guard` (already
required). Every handler returns "allow" when multiplayer is off, so the single-player game is untouched.

Shared files changed: `MistriMultiBoot.gml` (register events and hooks, one tick call, one debug function),
`manifest.toml` (hooks), `README.md` (one bullet).

## Assumptions only the game can confirm

1. `input.take_press` gives `local_key` `misc_local/feed` (animal and pet), `misc_local/place_animal_feed` (manger, with
   `subject.left`), `misc_local/give_item` (machine, `subject.node`), and a vetoed press leaves the held item alone.
   Read from the scripts; the veto semantic is from the hook page.
2. The Adoption menu calls `self.adopt_animal_to_building(...)` through the menu struct, so replacing that member on a
   guest (the same trick as the title menu in `MistriMultiSaveSpace.gml`) takes effect. Its first argument is a
   `dyn_index`.
3. `use_item` returning `false` after `items.use_guard` is harmless for the player state machine (`false` equals
   `UseItemSuccess.None`; the game's own "too tired" path returns `false` the same way), and `owner.cell_select` is the
   blueprint's target.
4. `Grid.write_node`, `write_blueprint_to_location`, `erase_object_node`, `remove_blueprint_from_location`,
   `expand_farm()` and `DECOR.apply_house_upgrade(...)` are safe to run when the player is not in that room (the game
   does so for the stairs, but not for the others), and a guest in another room gets the visual result when it enters.
5. `write_node(x, y, building_object, variant)` on a guest reserves a dynamic room of its own, and everything in this
   file refers to buildings by position, not `dyn_index`. Placements, machines and the room checks use the same name for
   the inside of a building (`"b72_52"`, `docs/SYNC-BUILDINGS.md`); crops and soil inside are the farm and terrain features'.
6. `ARI.give_item(id, n)`, `ARI.inventory.remove(id, n)`, `ARI.modify_gold`, `ARI.gain_xp`, `PET.*`, `DECOR.*`,
   `FACTORIES`, `EXPANSION_COST`, `GAME_STATS.furniture_placed[object]` have the shapes read from the scripts.
7. JSON booleans survive `json_parse` as booleans (the terrain feature relies on it too), and `int64` values
   (`birthday`) survive as numbers.
8. A node's `parent_grid`, `top_left_x/y`, `blueprint_id`, `blueprint_top_left_x/y`, `production_request`,
   `production_tier`, `day_count` and `renderer` are as the scripts show.
9. Hearts: the host sets them directly (`add_heart_points` would pay the host's XP), so the host's Ranching skill never
   grows from a guest's pet, and the guest's own XP is paid locally on the host's yes (feed) or by the game (pet).
10. `Stable.on_new_day()` really runs on guests and `game.new_day` fires after it; if guests do not run it the repair
    messages simply find nothing to repair.

## Known limitations

* Picking furniture or a blueprint up with the pickaxe on a guest is **not** intercepted: the guest gets the item and its
  own copy loses the object; the host's copy keeps it. A follow-up could filter `tool.targets` for guests and send a
  `pickup` request that returns the items through the reply.
* Placements before the session, and changes the host made and saved before a guest copied the world, are only as
  synchronised as the guest's copy of the save. A guest should re-download the world when the host restarts.
* Furniture can be placed in the farm, the house rooms and inside the player's buildings (as long as the game lets that
  object stand in that location), and not stacked via the guest's own placement.
* Finishing a building is the host's job (a guest is told to ask); its materials sit in a turn-in box that is a container.
  A finished building's interior (greenhouse crops and water, furniture, chests) is shared by the features in
  `docs/SYNC-BUILDINGS.md`.
* Babies are named in the popup of whoever sleeps; the host's name wins. The daycare is not shared (an animal a guest puts
  there is put back by the next barn record). Animals standing outside at night are judged by the host's copy.
* A guest cannot give a farm expansion's or a house upgrade's follow-up gifts (recipes) to others: those stay personal.
* An item thrown away while a paid request is in flight (see above), and a farm expansion applied while the host stands on
  the farm, are unhandled corners.
* The event queue is shared with every feature; very large barns fall back to blobs, which are slower.

## In-game checklist

Two games (host and guest) with a farm that has a coop, a barn, a chicken, a cow and a pet:

1. Join: the guest's animals, names and hearts equal the host's; F8 shows no warning; `mistrimulti.ranch` (debug agent)
   reports `synced: true`.
2. Host pets, feeds and renames an animal: the guest's journal shows it within a second. The guest pets another animal:
   the host's hearts go up once, even if both pet the same one.
3. Guest hand-feeds a chicken: the press does nothing visible until the answer, then the item leaves the hand once.
   Both feed the same animal: one loses, keeps the item and sees a notice.
4. Guest puts hay in the manger: the host sees it, and the chickens eat it.
5. Guest adopts an animal: gold is taken once, the animal appears for both; adopting into a full barn costs nothing.
6. Guest sells an animal: the host loses it, the guest keeps the gold; both sell the same one: one loses the gold back.
7. Sleep with the guest in the barn and out: the host's products are not on the ground; both walk into the barn and
   exactly one gets them. Save, quit, reload the host the same day: the pool is back.
8. Guest places a chair, a blueprint, a floor, a wallpaper: vetoed, then appears for both, item gone once; two players on
   one tile: one wins. Host places furniture: the guest sees it. A third player joining late sees all of it.
9. Host finishes a building from the blueprint: it appears for the guest and takes animals.
10. Host and guest hand the requested item to an apiary: one gets the reward.
11. Host buys the farm expansion and a house upgrade: a guest not on the farm or at home sees them; a guest standing there
    sees them after leaving. A guest buys the next upgrade at the carpenter: the host has it, no refund.
12. Kill the host mid-session, restart it from its save, reconnect: the guest's placements from the lost session are gone,
    nothing was charged for unanswered actions.

## Tests

```sh
python3 tests/test_ranch.py            # all, about 30 s
python3 tests/test_ranch.py test_feed_pays_once test_furniture
```

`tests/ranch_fake.py` is the stand-in for the game (animals, barns, a farm grid, house decor, a pet, apiaries, an
inventory), one per simulated game; the GML runs unmodified in `tests/gml_subset.py` over the simulated helpers and lossy
network (5 to 20 % loss, duplicates, jitter) with one host and two guests. The tests cover: snapshot and changes,
rejoin, a guest away for 14 s, host restart (an unanswered feed, an unanswered sale, placements of the lost session),
payment exactly once under loss and duplication and under races (feed, adoption, sale, expansion, house upgrade,
placement on one tile, a machine), refusals that cost nothing, products pooled/collected once/kept across a save, pet, treat
and pairing, manger arrays edited in place, floors and wallpapers with the old covering returned, blueprint to building,
room rules, the single-player no-op, and hostile requests and records (about forty malformed requests, bad and forged
state: no change and no exception). `python3 tests/mutate_ranch.py` breaks twelve rules of the GML in turn (charge twice,
no refund, no veto, no price check, no room check, ...) and requires the tests to notice each one.
What the tests cannot show is the real game: everything they run against is the faked part.
