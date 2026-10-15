# Live map markers and remote hit shake

Status: written against the game's scripts and tested against stand-ins (`tests/test_maplive.py`, `test_hit_shake` in
`tests/test_farm_sync.py`). **Not yet run in the real game.**

## 1. Other players on the map, live

Code: `mod/mistrimulti/gml/MistriMultiMapLive.gml` (the marker code moved here from `MistriMultiPeers.gml`), one call in
`mistrimulti_tick`, `ui.menu_opened` as before.

Finding: the markers appeared only when the map was opened. `MapMenu.select_location` (game script `MapMenu.gml`) builds every
icon of a page once (villagers, the player, the pet, children, and our players) and the game never calls it again until a tab is
tapped. The game's own icons do not move while the map is open either. There is no minimap in the game's scripts (nothing but
`MapMenu` uses `MAP_HUBS`), so the map menu is the only place.

Design:

- `ui.menu_opened` (kind `Menu.Map`) still wraps `select_location`: after the game's icons, `mistrimulti_map_add_peers` puts the
  player icon (alpha 0.8) on the hub the game itself would pick for each other active player (`menu.find_hub_for`, the function
  the game uses for Ari). The menu is remembered in `r.map_menu`; the picture is remembered as a text signature
  (`r.map_sig`: shown page + hub of every marker).
- The mod tick (driven by `ui.draw_gui`, which keeps firing while the map is open and the game is paused) calls
  `mistrimulti_map_tick` every tick. It returns at once unless a map is open, and then acts every 30 ticks (0.5 s): it
  recomputes the hubs of the players (at most seven `find_hub_for` calls on small arrays) and compares the signature. Only when
  a player crossed into another hub, appeared, left, or changed location does it call the menu's own `select_location(page)` again;
  the wrapper then re-places the markers (and the game refreshes its own icons as a side effect). A player walking inside one hub
  costs no rebuild.
- The tick forgets the menu when it is gone: `free_requested`, or no longer in `ANCHOR.open_menus` (the same list the game's
  `Anchor.gml` removes freed menus from). A failure (an exception in the rebuild) logs once (rate limited) and stops following
  that menu, so a broken page can never repeat an error.
- Players in another location: `find_hub_for` returns nothing for a page that has no hub for the player's location (a
  `MapHub.Position` hub matches only when the player's location is the shown page, a `MapHub.Locations` hub only its listed
  locations). So a player who walks into the town disappears from the farm page and shows on the town page (or when the
  player taps that tab); the dungeon has no page and shows nowhere; a player whose slot is not in the session mask or inactive
  is not drawn. Players inside a building count as the building's location (the game's own rule for Ari).
- Small fix on the way: two players on different hubs used a shared slot counter and the second marker was offset; the offset is
  now per hub.

## 2. Hit shake when another player hits a tree, rock or stump

Code: `mistrimulti_farm_hit_shake` and its two callers in `MistriMultiFarm.gml`.

What the game does: `chop_node` / `pick_node` (`Chop.gml`, `Pick.gml`) on a hit that does not destroy the node call
`rot_traumatize(node.renderer, tool_fx/chop.damaged.tree[stage].node_trauma)` (tree), `traumatize(renderer,
tool_fx/chop.damaged.node_trauma)` (stump) or `traumatize(renderer, tool_fx/pick.damaged.node_trauma)` (rock) from
`NodeRendererUtils.gml`. These two calls only set a number on the renderer and register it in a list that the game animates: no
drops, no sound, no item, no state. That is the whole visual hit, so the mod calls exactly them and nothing else.

When: (a) on a guest, when the host's change message (`mistrimulti_farm_apply_change`) lowers a tree / stump / rock's hitpoints
and the node still stands (`shake` argument of `mistrimulti_farm_apply`; snapshots, digests and repairs do not shake); (b) on
the host, in `mistrimulti_farm_op_tool`, which applies a guest's swing to the state only and so left the host's copy motionless.
The swinger's own game does it in the real `chop_node`; the shake is skipped when the viewer is in another room (no renderer).

Not done, on purpose: the killing blow. The game's destroy branch spawns a falling tree (`obj_falling_tree`), debris and
`drop_item` / `tree_attempt_drop_fruit` / `try_gather_item_spawn` together, and splitting the visual from the drops there is not
safe to do from outside (a duplicate drop would break the shared economy). So a felled tree or broken rock still disappears
without an animation on the other players' screens; only the non-lethal hits shake.

## Unverified assumptions (cannot be run here)

1. `ANCHOR.open_menus.contains(menu)` exists (the game's `Anchor.gml` line 1956 uses it on the same list) and the map menu
   stays in the list while the Journal is open; `menu.free_requested` is the game's flag (Anchor.gml).
2. Calling `select_location(selected_location_id)` again on an open map is safe and cheap enough twice a second only on change
   (it frees the map's children and rebuilds the hub nodes; the game itself does this on every tab tap). A hidden Journal tab
   with the map still open is rebuilt too, harmlessly.
3. `ui.draw_gui` keeps firing (and the mod tick keeps running) while the Journal is open and the game paused. The existing mod
   already relies on this for everything else (status badge, bridge), but it was not observed with the map open.
4. `fiddle_get("tool_fx/chop").damaged.tree[stage].node_trauma` and `tool_fx/pick.damaged.node_trauma` have the shape used in
   `Chop.gml` / `Pick.gml`; any error is caught and logged (rate limited).
5. A renderer replaced by `mistrimulti_farm_redraw` just before the shake is the one `traumatize` should be applied to.

## In-game checklist

1. Two players, map open on one: the other's icon moves between hubs while it stays open (within about a second) and on the
   right page.
2. The other player enters a house, the town, the dungeon: the icon leaves this page; the town page shows it.
3. Close and reopen the map, tap through tabs, leave the game paused for a minute: no errors in the MMAPI log.
4. Hit a tree, a stump and a rock from player 2 while player 1 watches (host and guest in both roles): non-lethal hits shake,
   nothing drops twice, the lethal hit removes the node as before.
