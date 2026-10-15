# Shared town rank (renown)

The town rank belongs to the farm: everyone in a hosted world has **one renown total**, owned by the host like the gold pool
(`docs/SYNC-WALLET.md`). A gain by any player raises it for all of them, and **every player gets the rank-up** (the level-up popup,
the reward of each level crossed and the rank quests) from their own game, once. Code: `mod/mistrimulti/gml/MistriMultiRenown.gml`
(plus `mistrimulti_progress_capture_renown` in `MistriMultiProgress.gml`). Tests: `tests/test_renown.py`, `tests/mutate_renown.py`.

Field report that started this: in a hosted world the shipping-bin payout gave the host a rank-up and the guest none, because renown
was personal and the guest's own sale of its (drained) copy of the bins was worth nothing.

## How the game does renown (read from the game's scripts)

- Gains are **queued** in `ARI.pending_renown_entries` during the day: `RenownEntry.Gold(gold_earned)` by `sell_shipping_bin_items`
  (end-of-day menu), `RenownEntry.Quest(name)` by `QuestLog.complete` (quests with a `Renown` reward) and by this mod's story reward
  mirror, `RenownEntry.MuseumDonation(item)` by `donate_item_to_museum`. Values: gold `ceil(0.01 * gold)`, museum `item.value.renown ?? 5`,
  quest the quest's `Renown` reward.
- The **end-of-day menu** shows the sum of the pending entries, and if it is not 0 (and the level is below 100) plays
  `RenownSequenceMenu`: the bar climbs from `ARI.renown` by the sum, with the level-up popup and the rank sprite for every level
  crossed. Nothing is applied yet.
- The entries are applied at the **day rollover** (`Ari.on_new_day`): `pending_renown_entries.drain(...)` calls
  `modify_renown(renown_entry_value(e))` per entry. `modify_renown` runs the MMAPI filter `player.renown_delta`, then
  `set_renown(renown + delta)`, which floors and clamps to `[0, renown_level_total_cost(100)]` and, for each level crossed, gives the
  level's reward (`RENOWN.rewards`: items; furniture items become a crafting scroll if the recipe is unknown) into
  `RENOWN_REWARD_INVENTORY` (the town renown chest, or the town's lost-items list when it is full), and starts the rank quest
  `reach_<metal>_star_town_rank` every 10 levels (completing the one ten levels earlier). The MMAPI events `renown.level_gained` and
  `renown.rank_gained` fire in there. The rank is `level div levels_per_rank`.
- There is nothing else that gives renown during play (`NewGame`'s cheat and the debug console set it absolutely).

## Decisions

| Question | Decision |
| --- | --- |
| Who owns the total? | The host: `pool`. Every game's `ARI.renown` is brought up to it. |
| What counts, and where is it counted? | Every renown gain of any player counts **once**. The host's drains all count (its own shipping sale, quests, donations, and the story quests every game pays). A guest's drains count only for what is that player's own: **non-story quests and museum donations**. A guest's copy of the **shipping sale** and of a **story quest** is dropped, because the host sold the shared bins (`docs/SYNC-WALLET.md`) and the host's game pays the mirrored story quest too (`docs/SYNC-STORY.md`). |
| How does a guest's gain reach the host? | The `player.renown_delta` filter sees each drained entry. A guest's own gain becomes a signed delta, sent as an exactly-once `renown_tx` request. The host adds it to the pool and answers with the pool, broadcast to everyone. Unsent deltas of one rollover travel as one request. |
| How does every game reach the pool? | **Carriers.** What a game has not applied (`pool - (renown + carriers)`) is put into its pending list as one gold entry worth exactly that renown, marked `mm_carrier` (`Gold(100 * k - 50)` is worth `ceil(0.01 * gold) = k`). The game's own end-of-day menu plays the climb and the level-up popups for it, and the day rollover drains it through `modify_renown`/`set_renown`: the rewards, the rank quests and the MMAPI events all come from the game itself, exactly as for a gain of the player's own. The filter recognises a carrier and applies it as it is, never counting it again. |
| Rank-up rewards | **Given to each player, once, from their own game** (items go to that player's own renown chest, `RENOWN_REWARD_INVENTORY`, which stays per player). Reason from the data: `set_renown` only ever produces items (`consume_reward`; a `RewardType.Quest` reward yields nothing), the chest is a per-player inventory (the progress record carries it), and the game gives them as the player's level crosses a threshold. There is no reward in this data that is a world unlock; the rank quests are quests, which this mod already handles per player or as shared story quests. Nothing is given to the host on behalf of the others. |
| Popups | Each player sees their own level-up popups, at **their own** end of day (the carrier is part of their pending sum). If the host's rollover comes after a guest's rollover, the guest's popup comes the following day. |
| Why not set the guests' renown directly? | That would give the rewards and the rank at once but silently: no popup, and the rank-up would happen in the middle of play. Carriers reuse the game's whole path and need no knowledge of the reward code. |
| Can the pool go down? | Only by a negative delta from another mod (clamped at 0). A game is **never taken back**: if a guest is ahead of the pool (see Migration, or a host reload) it keeps its level; its rewards are not given twice. |
| Where is it saved? | With the host's world: the host's own `ARI.renown` is saved with the game; `commits/<save name>.renown.json` (two generations, next to the player-record commit) holds the pool for that save. |

## Protocol

| Kind | Direction | Data |
| --- | --- | --- |
| `renown_tx` (request) | guest -> host | `{ d }`: signed whole number, `|d| <= 10,000,000`. Result `{ ok, p: pool }`, broadcast to everyone (every guest takes `p`). |
| `renown_state` (event) | host -> everyone, or one joining guest | `{ p }`: sent when the host's own drains change the pool (at the next 20 Hz tick) and as a snapshot from `on_peer`. |

Every field is validated (`is_real`, whole, range) on both sides; a refused request returns `{ ok: false }`. The pool is capped at what
the game can hold, `renown_level_total_cost(MAX_RENOWN_LEVEL)`. A guest's expected total is `pool + its own deltas the host has not
answered yet`, so its own gain is never delivered back to it as a carrier.

### Guarantees

| Situation | What happens |
| --- | --- |
| Packet loss, duplication, reordering | The event layer retransmits and de-duplicates; each delta is applied once and answered once. |
| Guest away longer than the 10 s expiry, then back | Its queued and in-flight requests are resent in order; anything already applied is re-answered from the host's cache, never applied twice; `on_gap`/`on_peer` ask for the total again, and the game gets the carrier for what it missed. |
| Host restarts | A request in flight is reported `lost` and **dropped** (at most once across a host restart). The pool is restored from the save's commit, or the host's own renown. A guest that had applied a lost gain stays ahead. |
| Guest re-enters the world | New session: unanswered deltas are dropped with it; it takes the pool from the host's snapshot (see Migration for its own old renown). |
| Hostile request or state (type, fraction, range) | Refused; the pool is unchanged; a state event from a guest is ignored. |
| Host alone | Behaves exactly like the game's own renown. |
| Day rollover repeated, ticks repeated | A carrier is made only for the gap and is grown, not duplicated; levels are rewarded once. |

## Persistence and migration

- **Carriers are derived state.** They are removed from the pending list in `save.game_saving` (both host and guest): the game would
  load them back as ordinary shipping gold and count them twice. The next tick makes them again from the pool. The progress record
  (`mistrimulti_progress_capture_renown`) never stores one either; it keeps the player's own queued gains.
- **Saving** (`save.game_saving`, host): `commits/<save name>.renown.json` = `{ v, world, day, renown }` (temporary file + rename,
  previous generation as `.bak`, the helper `mistrimulti_commit_write` of the player-record commit). The save itself holds the host's
  applied renown, which lags the pool by the carriers; that gap is what the commit makes up.
- **Loading** (`save.game_loaded`, then the world session opens): the pool is `max(host's renown in the save, commit of that save whose
  in-game day equals the loaded day (newest, then .bak))`. Without a valid commit it is the host's own renown. Reloading an older
  save therefore rolls the pool back with the world, and the host gets a carrier for the levels its save had not applied.
- **Old per-player renown** (worlds from before this feature): the pool starts from the **host's own renown**; a guest's personal
  renown is **never added** to it (adding it would let a hand-edited record mint renown and would change an existing world silently).
  What happens to that guest in its own game, by the first `renown_state` after it is ready:
  - no renown of its own (a new character, `mistrimulti_player_fresh`): its renown is set to the pool **silently, without back
    rewards**, like the story ledger (nobody is owed the past). This is a decision; the alternative (paying every past level) would
    drop a lot of items into a small chest in one night;
  - behind the pool (a returning player, or an old personal total below the world's): it gets a carrier for the difference, so it gets
    the popups and the rewards of the levels it was missing, once;
  - ahead of the pool (an old personal total above the world's): it keeps its renown and level, receives nothing, and gets carriers
    only for what the pool gains beyond its level. Its rank shows higher than the others until the pool passes it.
  - its old pending entries (`misc.renown` of the progress record) are drained like any: shipping gold and story entries are dropped,
    quests and donations count once.
  Its renown chest (`misc.renown_rewards`) is kept as it is.

## Assumptions to verify in the game

1. `player.renown_delta` fires once per drained entry, from `Ari.on_new_day`, with `ctx.player == ARI`, and returning `undefined`
   leaves the game's own value (the seam is `amount_to_add = mmapi_apply_filters(...)`; a filter that returns `0` makes the call a
   no-op, which is how a guest drops the shipping copy).
2. While the filter runs for entry `i`, that entry is still `ARI.pending_renown_entries.get(0)` (`List.drain` removes it after the
   callback returns, and the earlier ones are gone). The filter identifies carrier/gold/story from it, and checks
   `renown_entry_value(entry) == value`; if it does not match (another mod changed the value, or the call is not a drain) the gain is
   treated as the player's own and counted.
3. A struct entry accepts an extra field (`mm_carrier`) and `List.push` / `List.remove(index)` / `List.get` / `List.count` behave as in
   the scripts. `RenownEntry.Gold(gold)` / `renown_entry_value` are as read (`ceil(gold * 0.01)`); `100 * k - 50` gold is worth `k`.
4. `QuestCategory.Story` is the category of story quests, and **the host's game pays the renown of a story quest a guest handed in**
   (the story reward mirror pushes `RenownEntry.Quest` into every game that skipped the step, the host included;
   `docs/SYNC-STORY.md`). If it does not, a guest's story-quest renown is lost: watch for a quest that gives renown.
5. The museum is not synced yet: each player's donations are their own entries and each counts. When the museum becomes shared, its
   sync must push the donation entry in only one game (or this file must drop the others).
6. The rank quests `reach_..._star_town_rank` started and completed inside `set_renown` are harmless in every game. If they are story
   quests, the story sync treats the local start as the player's own step. The game starts `renown_level_to_quest(level)` without
   checking whether it is already active or done.
7. `ARI.renown` can be written directly (the silent start of a new character), as the player-record restore already does.
8. `save.game_saving` runs before the game serialises the player (so a carrier is gone from the save), and `save.game_loaded` before
   the host's world session starts. `mistrimulti_commit_key`/`mistrimulti_commit_write` (MistriMultiProgress.gml) are loaded.
9. The game's end-of-day menu reads the pending entries after `sell_shipping_bin_items`, so a carrier made earlier is part of the
   animation; a carrier made later is still drained at the rollover and rewarded without popup.
10. `renown_level_total_cost`, `MAX_RENOWN_LEVEL`, `RenownEntryType.Gold/Quest`, `QUESTS.get`, `QuestCategory.Story` exist as read.
11. MMAPI hook `player.renown_delta` is in the catalog and was added to `requires_hooks`.

## Known limitations

- **Trust.** A guest's `d` is validated for type and range, not for plausibility: a modified guest can claim renown (same as gold and
  the records).
- **Timing.** A guest sees the popups and gets the rewards at its own end of day, after the news reached it. Gains that arrive after
  its rollover come the next day. The rewards of a level are given when the player's game applies it, not when the pool reached it.
- **The guest's own shipping copy still adds to its end-of-day summary and animation** (the game files a gold entry for it): the
  popup may show a climb that the host's sale will be counted for instead, and the real rank-up comes with the carrier. The entry is
  dropped at the rollover. The summary of the receipt shows the carrier as renown from gold.
- **A request lost with a host restart is dropped**: the guest keeps what it applied and is ahead of the pool until it passes.
- **Negative deltas** (another mod) lower the pool and the player who got them; others are not taken back.
- The pool of a guest that joins a world before `renown_state` arrives (about a second) is unknown: nothing is done until then.
- Rank rewards are per player (the chest is theirs): a late joiner starts at the rank without the earlier levels' items.
- The shared renown applies to hosted worlds only; a host alone is the game's own renown.

## In-game checklist

1. Host and guest. Fill the shipping bins with enough to cross a level. The host sleeps: the host's popup, reward and (if the rank
   changes) the rank sprite play. The guest sleeps afterwards (or had slept before): the guest's end-of-day menu climbs by the same
   amount with its own popup; its renown chest has the same level rewards; `mistrimulti.renown` (debug) shows `pool == renown`.
2. The guest sleeps **first** with items in the bins: no renown is added from the guest's copy; the host's sale counts once.
3. A guest hands in a story quest that gives renown: the pool rises once (host's mirrored entry), both players get it.
4. A guest hands in a non-story quest and donates to the museum: the host and the other guest receive the gain at their next end of day.
5. Both players gain on the same day: the total is the sum, no level reward twice (look in each renown chest).
6. Reach a rank boundary with one player: both players get the rank-up popup and the rank quest's start once.
7. Kill the guest's game after its sleep, rejoin: nothing duplicated, nothing missing. Kill the host's game after a sleep, reload the
   autosave: the pool is the committed one (`commits/*.renown.json`); delete the file: the pool is the host's own renown.
8. A new character joins a world at rank 3: it shows rank 3 at once, without the earlier levels' items.
9. Save during the day while a carrier is waiting (`mistrimulti.renown`: `carried` > 0): the carrier is back within a second.
10. `mistrimulti.renown` (debug agent): `pool`, `known`, `queued`, `pending`, `renown`, `carried`.

## Tests

```sh
python3 tests/test_renown.py          # about 45 s: 15 scenarios, see below
python3 tests/mutate_renown.py        # breaks the code on purpose in 26 places; each must be caught
```

`test_renown.py` runs the real GML on the event layer over the lossy network simulation, with the player, entries and
`modify_renown` stubbed (the filter wrapped exactly where the MMAPI seam sits, `List.drain` keeping the entry in the list while the
callback runs, `set_renown` giving one reward per level and a rank every 10 levels): the field report (host shipping rank-up reaches
both guests with popups, rewards and the rank-up once); a guest's gains; three players gaining in the same moment under loss and
duplication; a rank reached by one player; each entry kind counted once; 120 random gains and rollovers under 12-20% loss and
duplication (one total, rewards once); a guest away beyond the expiry; joining and re-entering (new, behind, ahead, old queued
entries); host restart with commit, stale commit, damaged commit and `.bak`; a request lost with a host restart; the guest's own
unanswered gain; hostile requests and state; the filter's guards; carriers as derived state (one per gap, never saved, never in the
record); a host alone.
