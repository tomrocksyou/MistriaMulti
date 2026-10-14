# Shared wallet and shipping bins

Money is collective: everyone in a hosted world spends from, and earns into, **one pool of gold**. The host owns the pool; every
player's HUD shows it. The shipping bins are shared with it: any player can put items in, the host sells them once at the end of
its day and the proceeds go to the pool. Code: `mod/mistrimulti/gml/MistriMultiWallet.gml` (plus the bin changes in
`MistriMultiContainers.gml`). Tests: `tests/test_wallet.py`, `tests/mutate_wallet.py`.

## Decisions

| Question | Decision |
| --- | --- |
| Who owns the gold? | The host: `pool` (and `debt`, below). A guest's gold is a mirror. |
| How do changes reach the host? | Every gold change goes through `Ari.modify_gold`, which the MMAPI hook `player.gold_delta` filters. The filter turns each change into a signed delta: applied directly on the host, sent as an exactly-once `wallet_tx` request from a guest. |
| What does a guest show? | `balance + its own deltas the host has not answered yet`, so the HUD moves at once and never double counts. The game's own `set_gold` (absolute, does not re-enter the filter) is used to keep the HUD equal to that value. |
| Can the pool go negative? | Never. The host validates every spend against the pool. |
| Two players spend the same gold at the same moment | The first is applied, the second takes the pool to 0 and the rest is a **debt**. Income pays the debt before it adds to the pool. No gold is created from nothing; pool - debt always equals the start plus all changes. |
| Where is it saved? | With the host's world: the host's own gold in its save is the pool, and `commits/<save>.wallet.json` (two generations, next to the player-record commit) holds pool and debt for that save. |
| Guests' old personal gold | **Not added to the pool** and discarded (see Migration). |
| Shipping bins | Host-owned, synced like chests. The **host** sells them once at its end of day; the proceeds go to the pool. The **host's perks** apply (the seller's `bin_value`). |

### Why this mechanism

- *A hook on every change (chosen).* `modify_gold` is the only way the game changes gold during play. Every shop, quest, sale,
  fee and the end-of-day payout already goes through it, so one filter covers all of them, including features added by other
  packages (the ranch pays with `ARI.modify_gold`). The alternative, patching each shop and menu, would miss some and cannot be
  verified without the game.
- *Deltas, not absolute values.* Sending "my gold is now X" would lose a concurrent change by another player. A signed delta
  composes: the host applies each exactly once (the event layer's request ids), in the order it receives them.
- *The host's answer carries the balance, not "+5"*, so applying it is idempotent and corrects any local drift. The host's stream
  is ordered, so the balance in any host message includes exactly the answered deltas; the guest adds the ones still unanswered.
- *Why not block the purchase until the host agrees?* The game decides, spends and hands over goods inside one frame
  (`StoreMenu`: `store.purchase` "nothing can abort", then `modify_gold`); a filter cannot refuse a purchase that the game already
  completed. The debt makes an overdraw harmless to the pool instead.

## Protocol

| Kind | Direction | Data |
| --- | --- | --- |
| `wallet_tx` (request) | guest -> host | `{ d }`: signed whole number, `|d| <= 100,000,000`. Result `{ ok, g: pool, s: debt }`, broadcast to everyone (every guest takes `g`). |
| `wallet_state` (event) | host -> everyone, or one joining guest | `{ g, s }`: sent when the host's own gold changes (`dirty`, at the next 20 Hz tick) and as a snapshot from `on_peer`. |

Every field is validated (`is_real`, whole, range) on both sides; a refused request returns `{ ok: false }` and the guest's
expected value falls back to the host's balance. The pool is capped at 999,999,999 (the limit the player records already
validate). A guest's `d` is what the game really applied: `max(floor(gold + delta), 0) - gold`, i.e. exactly what `set_gold`
does with it, so a spend can never take a guest below 0 locally or ask the host for more than the guest saw.

### Guarantees

| Situation | What happens |
| --- | --- |
| Packet loss, duplication, reordering | The event layer retransmits and de-duplicates; each delta is applied once and answered once. |
| Guest away longer than the 10 s expiry, then back | Its queued and in-flight requests are resent in order; anything already applied is re-answered from the host's cache, never applied twice; `on_gap` / `on_peer` ask for the balance again. |
| Host restarts | A request in flight is reported `lost` and **dropped** (at most once across a host restart: the new host cannot know whether the old one applied it). The guest follows the new host's snapshot. The pool is restored from the save's commit (below). |
| Guest re-enters the world / restarts | New session: its unanswered deltas are dropped with it; it receives the pool from the host. |
| Hostile request (type, fraction, range) | Refused; the pool is unchanged. |
| Host alone | Behaves exactly like the game's own gold. |

## Persistence and migration

- **Saving** (`save.game_saving`, host): the host's gold is set to the pool, then `commits/<save name>.wallet.json` is written
  (`{ v, world, day, gold, debt }`, temporary file + rename, previous generation kept as `.bak`, the helper
  `mistrimulti_commit_write` of the player-record commit). The save file itself therefore also holds the pool as the host's gold.
- **Loading** (`save.game_loaded`, then the world session opens): the pool is the commit of that save whose in-game day equals the
  loaded day (newest, then `.bak`); without a valid commit it is the host's own gold in the save. Reloading an older save
  therefore rolls the pool back with the world, like every other host-owned state.
- **Migration of guests' personal gold.** Before this feature each player had their own gold, kept in their player record
  (`stats.gold`). That value is **not** added to the pool: it is overwritten by the pool as soon as the host's balance arrives
  (and the record is then re-uploaded with the pool). Rule: *the world's gold is the host's gold*; a guest who joins a world
  starts with the pool, and the gold a guest earned in another world or in single player stays in that save. Adding it would
  let any guest mint gold by editing a record, and would change the economy of an existing world silently. The host can still
  give gold to the pool by hand (a debug `set_gold` before the first guest joins).

## Shipping bins

The game's end-of-day menu sets `ARI.end_of_day_sequence = true`, then `sell_shipping_bin_items()` drains every bin on **that
game's** copy of the world and pays `ARI.modify_gold(total)` (always called, even with 0). With synced bins:

- All bins are host-owned and replicated like chests (`MistriMultiContainers.gml`, `docs/SYNC-CONTAINERS.md`): any player puts
  items in and takes them back; the host's bins hold everything.
- The host's sale is the real one: its payment passes the filter like any gain and goes into the pool. The seller's perks apply
  (`LiveItem.bin_value()` uses `ARI.perk_active`), i.e. **the host's**: Back in Vogue and similar perks of a guest do not
  raise the proceeds of the items that guest put in. (Alternative for later: send the guest's perk multiplier with the items.)
- A guest's end of day sells the guest's copy as well. The filter drops that payment: the **first** gold change of an
  end-of-day sequence on a guest is the shipping payout, and returns 0. The guest's summary screen may therefore show a number
  that the host did not pay. After its end of day the guest asks the host for each bin again and shows the host's contents.
- Proceeds are credited once however the days interleave (host first, guest first, packet loss): tested.

## Where gold changes (covered and not covered)

Everything that calls `ARI.modify_gold` is covered by the `player.gold_delta` hook (found by grep in the game's scripts):
the shop basket (`StoreMenu`, one negative delta), Ryis' store (upgrades, purchases, expansion), the bathhouse, the pumpkin
patch, the wishing well, crafting costs and gold ingredients (`Recipe`), quest costs and rewards (`QuestLog`), story rewards
(`StoryExecutor`, `T2r` actions), animal adoption and selling (`AdoptionMenu`, `SellAnimalsMenu`, the ranch package's own
charge, refund and clawback), purses and coins that give gold (`use_item`, `AriFsm` auto-use items), and the end-of-day shipping payout.

**Not covered** (absolute sets; the hook does not see them): `Ari.deserialize` (loading a save: handled as pool initialisation on
the host), `NewGame` (`set_gold` at world creation: same), the debug console and `BuggerInitialize` (`set_gold` / `modify_gold`
cheats on a guest are corrected by the next pool update), the player-record restore and `mistrimulti_player_fresh`
(`ARI.gold = ...`, overwritten by the pool), and anything that writes `ARI.gold` directly. `T2r` only reads gold.
The wallet **mirror** is set with `ARI.set_gold`, so the achievement refresh `refresh_achievements([Requirement.EarnedGold])` also
runs when gold is corrected, which the game does on every change anyway.

## Assumptions to verify in the game

1. `player.gold_delta` fires for the purchases, quests and sales above with `ctx.player` equal to `ARI`, and returning the clamped
   delta leaves the game's `set_gold(floor(gold + delta))` at the expected value.
2. `Ari.get_gold()`, `Ari.set_gold()` and `ARI.end_of_day_sequence` exist and behave as in the scripts. `set_gold` does not call
   `modify_gold` (it does not, by the script) and its HUD animator tolerates being called by the mod.
3. **The first `modify_gold` of the end-of-day sequence is the shipping payout** (the sale runs right after the flag is set,
   in the same menu callback; nothing else pays in between). If a mod or an update gives gold earlier in the sequence, a guest
   would lose it; watch the F8/debug output.
4. Inventory removal (`drain` -> `remove`) increments `slot.updates`, so the host's sale is seen by the container scan and
   broadcast (true in the scripts).
5. `save.game_saving` runs before the game writes the save (so the host's gold in the file is the pool), and
   `save.game_loaded` runs before the host's world session starts.
6. `r.player_ready` is true on the host before the first purchase; a gold change before that is left to the game.
7. Wine/Windows file rename over an existing file for the commit (the same helper as the player-record commit).
8. The mod's `mistrimulti_commit_key` / `mistrimulti_commit_write` (MistriMultiProgress.gml) are loaded in the game; the wallet
   depends on them.

## Known limitations

- **Trust.** A guest's `d` is validated for type and range, not for plausibility: a modified guest can claim income. The host
  cannot verify a sale or reward it did not see (same as the records and chests).
- **Overdraw becomes a debt**, not a refusal: the guest already got the goods. The debt shows up as the pool staying at 0 until
  later income covers it (`mistrimulti.wallet` debug function shows `debt`).
- **A request lost with a host restart is dropped**: the guest may have spent or earned once without the pool knowing. The host
  also reloaded an older save at that moment, so the rollback is consistent with the rest of the world.
- Before the first `wallet_state` arrives (about a second after joining) a guest still shows its old personal gold; a spend in
  that window is validated by the host and, if needed, becomes debt.
- The summary of a guest's end-of-day screen does not equal what the host paid (see Shipping bins).
- The guest's drained copy of the bins is refilled from the host after its end of day; until then it shows empty bins.
- Only the host's perks apply to shipping proceeds.
- Gold the guests' records still carry (`stats.gold`) mirrors the pool and is not used for anything.

## In-game checklist

1. Host and guest: both HUDs show the same gold. A guest that joins with its own saved gold shows the host's gold after a second.
2. Guest buys from a shop: its HUD drops at once; the host's HUD drops within a second. Host sells something: the guest's HUD rises.
3. Both players buy at the same moment with just enough for one: the pool ends at 0, not negative, and the next income is
   partly absorbed (`mistrimulti.wallet`: `debt`).
4. Quest reward, animal adoption and sale, crafting with a gold ingredient and the bathhouse as a guest: pool changes once.
5. Throttle the guest's link while it spends: no double charge, no lost charge after the link returns.
6. Kill the guest's game right after a purchase, rejoin: the pool is the host's, nothing is duplicated.
7. Host sleeps (autosave), spends, then reloads that autosave: the pool is the committed value. Delete `commits/*.wallet.json`:
   the pool is the host's gold in the save.
8. Shipping bins: three bins, items put in by the host and the guest; the host sleeps: the whole content sells once, every HUD
   changes by the same amount. The guest sleeps afterwards: no additional gold, no items reappear in the bins. Repeat with the
   guest sleeping first.
9. `mistrimulti.wallet` (debug agent): `pool`, `debt`, `known`, `queued`, `pending`, `gold`.

## Tests

```sh
python3 tests/test_wallet.py          # about 20 s: 15 scenarios, see below
python3 tests/mutate_wallet.py        # breaks the code on purpose in 17 places; each must be caught
```

`test_wallet.py` runs the real GML on the event layer over the lossy network simulation: the mirror and ordering; concurrent
spending (never negative, debt, repayment); 250 random changes under 12-20% loss and duplication (exactly once); an overdraw fuzz
(conservation: pool - debt = start + applied changes); a guest away beyond the expiry; joining and re-entering guests; host
restart with commit, stale commit and damaged commit; hostile requests; the filter's guards; bins shared; the day end with three
bins, host first, guest first, under loss and over two days.
