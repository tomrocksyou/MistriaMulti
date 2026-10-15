# Story, villagers, cutscenes and festivals

The world's story (story quests, the cutscenes that change the map, the facts that open bridges and secret places), the villagers'
whereabouts, and what happens around a cutscene or a festival when several people play. Code:
`mod/mistrimulti/gml/MistriMultiStory.gml` (about 800 lines, no new MMAPI hook), small additions in `MistriMultiBoot.gml`. It
runs on the event layer (`docs/EVENT-LAYER.md`) and builds on the clock (`docs/SYNC-CLOCK.md`: one date and time of day for
everybody) and on the personal records (`docs/SYNC-PROGRESS.md`: friendship, romance, personal quests, mail, seen scenes).

Two things sit on top of that and are described in their own sections: [every player gets the personal rewards of a shared story
step](#rewards-of-a-shared-step-for-the-players-who-did-not-do-it) (exactly once, also a player who was away), and [the spouse of
any player lives at the farm](#spouses-of-other-players-live-at-the-farm) (in every game, also while that player is away).

Nothing here has run in the real game. The GML ran against a stand-in game (see [Tests](#tests)). [What to check in the
game](#assumptions-about-the-game-that-could-not-be-verified) and the [checklist](#in-game-checklist) list everything the stand-in
cannot show, and [Known limitations](#known-limitations) is the honest list of what this does not do.

## Decisions

| Question | Decision |
| --- | --- |
| Who owns the story? | The host. A guest's own game applies a step first (the game has no way to ask permission), then tells the host; the host merges it with "max" and tells everybody. The host's game applies guests' steps to its own quest log, so they are in the host's save. |
| What is world and what is personal? | See [the audit](#audit). Story-category quests, the cutscenes that change the shared map or open a gate, the facts those gates read and the secret-chest counters are the world's. Everything the player earns, says, gets or feels is personal. |
| Villagers: host simulation or per-game simulation? | **Per-game simulation, steered by the host.** Every game keeps simulating its villagers (the game cannot be told to stop), the host decides *which schedule each villager follows today* and samples *room and activity* every 3 seconds, and a guest swaps its villagers' schedules to match, only ever out of its player's sight. Reasons below. |
| What does a cutscene do to the others? | It never pauses, moves, waits for or waits on anybody else. Its lasting world effects are shared once, when the scene is over, so gates and unlocks agree. **A world story scene is then played by every player themselves** (each can skip it with the game's own skip), see [Cutscenes that every player watches](#cutscenes-that-every-player-watches); a scene that cannot be shown safely is applied silently, as before. |
| Festivals? | A festival is a function of the date, and the date is the clock package's. Nobody is held out and nobody has to enter together; there is no start to miss. See [Festivals](#festivals-and-calendar-events). |
| Heart events? | Personal. The game plays them with throw-away actors and respawns the real villagers afterwards; nothing about a villager travels from a guest to the host, so a heart event cannot move a villager for anybody else. Their items and hearts are the watcher's alone. |
| Who gets the rewards of a shared story step? | **Everybody, once.** The player who hands a step in is paid by the game as always; every other game, when it is brought up to the mirror, pays the rewards of the stages it skipped, and a per-player ledger says how far each player has been paid. See [Rewards](#rewards-of-a-shared-step-for-the-players-who-did-not-do-it). |
| Whose spouse lives at the farm? | **Every player's.** Each game moves in the spouses of the other players itself, with the game's own functions, from the host's registry of who is married to whom. See [Spouses](#spouses-of-other-players-live-at-the-farm). |
| One flag raised by two players at once? | Every shared fact is an absolute, monotone value (a stage number, "seen", a counter), merged with max on the host. Twice is the same as once. |

## Audit

What the game saves and does, and who owns each part. "Mirrored" means: every game keeps a copy that the host's merge keeps
equal. The tables name the game's scripts that were read.

### Quests (`QuestLog.gml`, `QuestUtils.gml`, `Festivals.gml`)

| Part | Owner | Why |
| --- | --- | --- |
| Quests of category **Story** (`QuestCategory.Story`) | world, mirrored | their rewards and effects change the shared map: turn-in boxes are placed in the world grid (`initialize_requirements_on_task`), quests start follow-up quests, scenes and world gates read them (`CompletedQuest`). |
| The quest a festival starts and ends by itself (`FESTIVALS[i].prototype.associated_quest`) | every game, not mirrored | `Festival.new_day` starts it and `Festival.end_day` finishes it in every game on the same date; mirroring it would only fight that. Found at run time from the festival data, not by name. |
| Crown, Tali, Stillwell, Heart, Fetch quests, `manual_quest_unlocks`, the board's read marks | personal | `docs/SYNC-PROGRESS.md` |
| `request_board` | world object | not synchronised yet (another area) |
| Quest rewards and renown | every player, once | the player who hands in is paid by the game; every other game pays the stages it skipped from the mirror ([Rewards](#rewards-of-a-shared-step-for-the-players-who-did-not-do-it)) |

### Cutscenes (`Mist.gml`, `MistRuntime.gml`, `Std.gml`)

What `Mist.clean_up_scene` does when any scene ends, and what is shared:

| Effect | Shared? |
| --- | --- |
| `scene_history`, `scenes_played_today`, the `cutscene_seen_<name>` fact | personal for most scenes (`docs/SYNC-PROGRESS.md`); **world** for the scenes below, which every game adds to its own history (a scene the game can show again is also offered again there, see [Cutscenes that every player watches](#cutscenes-that-every-player-watches)) |
| `object_removals` (objects erased from a location's grid), `nuke` (a rectangle of the town cleared), the plaza upgrade | world: applied once in every game when the scene is done by anybody |
| `quest_to_start`, `quest_to_progress` | the quest effect is shared as *quest state* (a story quest is mirrored), never as "progress one step" |
| `spell_to_unlock`, `mana_to_set` | the player's, **and** granted to a player who did not watch a world scene (they would otherwise miss it) |
| `given_items`, `baths` | the player's, **and** granted once to a player who did not watch a *world* scene: at once (when the scene enters their history) if the scene is applied silently, after the viewing if it is offered to them; a heart event or romance scene is never a world scene, so its items stay with the watcher |
| `drop_items`, `status_effects`, `set_health_to`, cosmetics, heart/relationship changes, `heart_level_changes`, `romantic_choice_warning` | personal; never granted to a player who did not watch (`drop_items` are objects dropped into one game's copy of a room) |
| `ends_day`, `end_time_jump`, `when_sleeping` | the player's own clock and day (`docs/SYNC-CLOCK.md`) |
| `end_position`, camera, music, fades, throw-away actors (`MistNpcBrain`), the held animal | local presentation |
| Edits that the scene's own script makes to the *current* grid (`__erase_node`, `nuke_tut`, `handle_farm_chores`) | local to that player's copy of that room; the farm package covers the farm, nothing covers other rooms |

A cutscene counts as **the world's** (`__mistrimulti_story_scene_world`) when the game's own data says so, and is not personal:

* its `test_target` is `MainStory` or `DragonStory`, or
* it has `object_removals` or a `nuke`, or
* it starts or advances a Story quest, or
* a world gate reads it: the requirements of every `WORLD_MODS` entry (bridges, the inn interior, the secret narrows and beach,
  the plaza, ...) and of the aliases `BrokeFireSeal`, `SeridiaTransformed`, `SaturdayMarketUnlocked` are walked, aliases and
  `or` groups included, and every `SeenCutscene` found is a world scene.

It is **personal** when it has a `romantic_choice_warning`, any `heart_level_changes`, or `test_target == MarriageAndChildren`
(this wins over everything above), and also when it is none of the things above (the default: a scene nobody can prove to be
the world's stays private).

### World facts (T2) and world gates

The T2 store mixes the two. World *gates* (`WorldMod`, `npc_is_unlocked`, `NpcUtils` wedding party, the Saturday market) are
pure functions of three things: the story quests, the seen scenes and a few facts (`requirements_pass`, `WorldFactIs`,
`SeenCutscene`, `CompletedQuest`). Mirroring those three therefore makes every world gate agree in every game without sending
the gate: all players see the same bridge, the same secret door, the same villagers unlocked.

World facts are exactly:

* `caldarus_seridia_town`, `seridia_is_human`, `caldarus_is_human`, `caldarus_home` (the dragon story; read in
  `NpcUtils.gml`, written together by the game's own story test), and
* every `WorldFactIs` fact found in the requirements of the world gates above (found at run time).

Only a fact becoming `true` is shared, only upwards. Every other fact stays where it is: relationship and heart facts, `quest_*`
(derived from the quest log), `cutscene_seen_*` (derived from the history), `had_item_*`, `*_zone`, `*_activity`, `*_animation`,
`*_routine`, `weather` (clock package), `museum_*` (derived), counters written by dialogue data (`da_<npc>_<date>`), ... Facts that
data files write and the code never mentions cannot be classified from the scripts; see [limitations](#known-limitations) and the
debug function `mistrimulti.story`, which lists what was found, for finishing the audit in the game.

### Other world state found

| Item | Decision |
| --- | --- |
| `SECRET_NARROWS`, `SECRET_BEACH`, `SECRET_TOWER` (how many items of a secret chest were taken) | world counters, mirrored upwards (max). Two players opening the same secret chest in the same second can both get the loot. |
| `STORY_ENABLED` (the game's story mode) | the host's; copied to a guest in the snapshot |
| `CANCEL_FESTIVALS` | the host's; follows the day plan |
| `ATE_SOUP`, `USED_WISHING_WELL`, `WORLD_FOUNTAINS` (once a day each) | **decided: per player.** `docs/SYNC-PROGRESS.md` calls them "world" because they are not in the player record, but a daily perk shared by everybody would be first come, first served for no gain. Each game keeps its own, reset by its own new day. |
| Tutorials (`tutorials_seen`), mail, gifts, `gift_flag`, `talk_flag`, `times_spoken_today`, hearts, dates | personal (`docs/SYNC-PROGRESS.md`); one talk and one gift per villager per player per day |
| Shop hours, the calendar and birthdays | derived from the clock and the date, so already shared; vendors are villagers, so the plan places them |
| Shop stock, the request board | another area |

## Villagers

### Why this design

The options and why two were rejected:

| Option | Verdict |
| --- | --- |
| **Host simulates, positions streamed at low rate** | Rejected. `npcs_on_step` runs in every game and cannot be switched off: a streamed position would be fought by the local simulation (rubber-banding), and a villager walks with real pathfinding only in the room its player is in. Streaming 34 villagers at a usable rate through the 16 KB bridge frame is out of proportion with what is gained. |
| **Per game, seeded by the host's time and day** | Not enough. The schedule a villager follows today comes from `T2R.request_schedule`, which reads facts that are personal (hearts, relationship status, quests in progress): two players get different days for the same villager. Activities (`ActivityHandler`) use unseeded `irandom`. |
| **Per game, steered by host-owned logical state** (chosen) | The deterministic part of a villager's day is the schedule (data) plus the clock (shared). Sharing *which schedule* closes the first gap; sharing *room and activity* every few seconds closes drift and the random part, at the price of a few hundred bytes. The game's own deferred mechanism does the moving. |

### What is shared

Host to guests, change-only:

* `npc_plan` `{ d, s[], cf }`: the day number, the name of the schedule each villager follows (`T2R.schedule_name`), and
  `CANCEL_FESTIVALS`. Sent when it changes (a new day, or any swap the host's game made) and to every joining game.
* `npc_pos` `{ d, l[], a[] }`: the room (`location_id`) and the activity id of each villager, at most every 3 seconds and only
  when something changed.

Each guest (every 3 seconds, only after it holds the host's snapshot, only when the plan is for the guest's own day, and not during
a cutscene or the end of the day):

1. If a villager's schedule differs from the plan: set the game's own `NPCS[i].swap_schedule_request = { schedule_name, finish: false }`.
   `npcs_on_step` performs it (`perform_schedule_swap`, which also fast-forwards the new schedule to the time now) as soon as the
   villager is not in the room the player is in. **The mod never writes a villager's position.** A plan with an unknown schedule name
   (not in `T2R.schedule_names()`), a wrong length or a wrong type is dropped.
2. Same schedule but another room than the host's for 3 passes (about 9 s, the walk between rooms): the same swap, which re-aligns the
   villager to the time now. Never while the villager, or the host's villager, is in the player's room.
3. Same room but another activity for 3 passes, out of sight and not travelling: `request_activity(host's activity)`, a request
   the game's own handler accepts or fails.

A guest never sends anything about villagers. There is no event kind for it.

### What agrees and what does not

| | Agrees for all players |
| --- | --- |
| Which schedule a villager follows today | yes (the plan) |
| Which room, and where the schedule says to be at this time | yes, within one clock-package error (about 25 game seconds) and 3-9 s of correction |
| What the villager does (sit, eat, read, ...) | yes in kind, after a few seconds |
| The exact seat or wander point, the path taken, the animation variant | no (chosen per game by the game's own random choice) |
| A villager in the room you are standing in | never moved or changed before your eyes; corrected after you leave |
| Dialogue, gifts, hearts, "talked today" | per player |

Because a swap waits until the villager is out of sight, two players standing in one room always see the same villagers do the same
things only as far as the schedule goes; a correction can take until somebody looks away.

## The world story: how it works

Every game keeps a **mirror**: `q` (quest name -> stage, or 1000000 for done), `sc` (world scenes seen), `f` (world facts true),
`k` (three secret-chest counters). A pass runs once a second in every game, not during a cutscene or the end of the day:

```text
local  = what this game's quest log / history / facts / counters say (world items only)
up     = local entries above the mirror         down = mirror entries above local
host:   merge(up) into the mirror -> broadcast the part that advanced it; apply down to its own game
guest:  claim(up)  -> host -> merge (max) -> result to every guest      apply down to its own game
```

* **Claims are absolute** ("quest `bridge` is at stage 1"), merged with max on the host after validation against the game's
  own data (is it a story quest, does the stage exist, is the scene world-level, is the fact a world fact, is the counter in
  range). Level 1000000 means done and is final.
* **Applying "down"** brings a game up to the mirror: a quest is started at the mirror's stage with the game's own
  `QUEST_LOG.start(name, stage)` (which places turn-in boxes), advanced by setting the stage, or marked done by hand
  (completed set, timestamp, facts) **without rewards or renown**; the turn-in boxes of finished stages are removed as the game
  removes them for the player who hands in. A world scene is added to the history, its `cutscene_seen_*` fact written, its object
  removals and area clear applied, and its spell and mana granted. At most 16 changes per pass; one the game refuses is not tried
  again this session.
* **Join and rejoin.** The host sends a snapshot blob (the whole mirror plus `STORY_ENABLED`) followed by the plan and sample, when a
  guest appears (new session, or back after more than 10 seconds), on request (`story_sync`, which a guest sends if it has
  nothing after 10 seconds) and once per host session. A guest claims nothing before it holds the snapshot, and a guest that sees a
  *new host session* (it may have restarted from an older save) throws its mirror away and waits for that host's snapshot.
* **Host restart.** The host's mirror is rebuilt from its own game (its save), without announcing it. Guests that are ahead of the
  restored save claim the difference again, so the story the guests made after the host's last save returns. Progress made after a
  host crash is therefore not lost; the cost is that a rollback of the host's save does not roll the story back for guests who
  stay connected (they should rejoin).
* **Back-pressure.** The host merges and broadcasts only when the send queue has room for it (12 events). What does not fit stays
  "ahead" of the mirror and goes out in a later pass: a full queue delays, it cannot lose. Lists are cut to 20 entries per event.
* **In flight.** A claim is not repeated while it waits (an entry is "pending" with its request id). A claim the host answered but
  did not take (it refused it) is not made again this session. A lost or expired answer clears the pending mark so the next pass
  claims again.

### Two players, one flag

| Situation | Result |
| --- | --- |
| Both hand in the same quest step at the same time | both games advanced locally (and each player was paid once); the host merges stage k+1 once; everybody ends at k+1 |
| Both watch the same world scene | both apply its effects locally; the host takes it once; nobody applies it twice (the history is checked first) |
| A scene advances a quest *relatively* (`quest_to_progress`) and two players watch it | each game advanced the quest once locally; the claims are absolute, so the world advances one step |
| A scene finished by A reaches B while B is already in it | B's pass is paused until its scene is over; its history then already holds it |
| Two guests open the same secret chest | both may get the loot (the chest is not a host-arbitrated object) |

## Rewards of a shared step for the players who did not do it

A story step gives its rewards when a player hands it in: the game's `ActiveQuest.progress` grants the *task's* rewards
(`grant_quest_rewards`: items, gold, recipe and crafting scrolls, cosmetics, animal cosmetics, a quest to start), and when the last task
is in, `QuestLog.complete` files a renown entry (`pending_renown_entries`, when the quest has a `Renown` reward) and the quest-complete
popup grants the *quest's* own rewards. Mirroring a step (`mistrimulti_story_apply_quest`) changes the quest log only. Since this feature
a game that brings its quest log up to the mirror then pays what the step would have paid, with the game's own functions.

**The ledger.** For every story quest, a number: the level up to which this player has been paid. Level `L` of an active quest means
the rewards of its tasks `0..L-1` have been given; the level "done" adds the quest's own rewards and renown. It lives in the player's
**world facts** (`mm_paid_<quest>`, and `mm_paid_init`), which is the one place that is saved with the right thing on both sides:

| Player | Where the ledger is saved | Why it stays consistent |
| --- | --- | --- |
| The host | the host's save (`t2_world_facts`) | it is saved and restored together with the host's inventory, gold and quest log: loading an older save rolls all of them back together, and the host is then paid again for the steps its older inventory never received |
| A guest | the progress section `story_rewards` (`{ init, paid: { quest: level } }`), which restores into the facts | it is uploaded, stored by the host, committed with the host's save and restored in any slot like every other section ([docs/SYNC-PROGRESS.md](SYNC-PROGRESS.md)); restoring it replaces the facts the guest's copy of the host's world contained |

**One pass** (every second, after the game was brought up to the mirror; the same code on the host and on a guest):

1. *Own steps first.* Before anything is changed, a quest level that rose since the end of the last pass (a quest that was not there
   counts as rising from nothing) is the player's own doing: the game has paid it, so the ledger moves up to it. A rise this file
   made is recorded in `seen` at the end of its pass and never counts as the player's. Nothing counts in the first pass of a
   session (the game was just loaded).
2. *Seeding.* The first time (`mm_paid_init` is not true: a new character, or a record from before the ledger) every quest that
   exists, in the game or in the mirror, is marked as paid up to the highest level either has. **A new player is not owed the story so
   far**, only what happens from then on. (Their scene history starts as the host's for the same reason.)
3. *Paying.* For each quest where `min(what this game has, what the mirror holds)` is above the ledger, at most 6 quests a pass: the
   ledger moves up **first**, then the rewards of the stages in between are given by `grant_quest_rewards`, one task at a time; for
   "done" also the quest's own rewards and the renown entry. A reward that fails is logged and **not** repeated (it might have been half
   given): losing one reward is better than giving it twice.

What is filtered: a reward that **starts a quest** starts it only if the quest is not a story quest (those come through the mirror,
and a second start would restart it) and the player has it neither active nor finished, so a step that opens a personal errand
opens it for everybody once. A message ("Story reward: ...") is shown once per pass in which something was paid.

**World scenes** need no ledger: the scene history *is* one (it is saved in the progress record, `seen.scenes`). When a world scene
reaches a game that did not play it, `mistrimulti_story_apply_scene` adds it to the history and, in the same call, gives its
`given_items` (through the game's `mist_give_items_after_scene`, to the bed if the pockets are full) and its `baths`. A scene watched
in two games at once gives each viewer its items once from their own end of the scene, and the mirror finds it already in both
histories. Heart events and romance scenes are never world scenes (see the classification above) and keep their items.

| Situation | Result |
| --- | --- |
| A player hands a step in | the game pays them; the ledger follows in the next pass; nobody else's game pays them twice |
| Another player hands it in, this one is online | paid when the mirror reaches them (a second or two), once |
| ... and this one is away (more than ten seconds), or the game is closed | paid when they next join and the mirror reaches them, once (the ledger is in their record) |
| Two players hand in the same step at once | each is paid by the game for their own hand-in; the host merges one step; nobody is paid again |
| A new character joins a story that is half done | nothing for the past; the next step is paid |
| A guest's world copy is older than the ledger says | the ledger wins: nothing is paid again |
| The host loads an older save | its ledger and inventory are older together; the guests' steps made after that save pay the host again, once |
| The pass cannot read the game's data | the story sync is off, so nothing is paid |

The only gap is a crash between a reward being given and the record (the ledger is in the same record as the quest section, but the
**inventory is in the core record**, a separate upload every five seconds): a guest that dies in those seconds can lose or, rarely,
repeat one reward. The ledger moves before the reward is given, so the usual outcome is the loss.

## Spouses of other players live at the farm

**The game's rule.** A villager lives in the farm house only if the game's own relationship fact `<npc>_status` says "spouse"
(`Npc.is_spouse`, `is_roommate`, which also makes Dozy and Henrietta roommates of Juniper and Hayden). That fact is the player's own,
so the host's game moves only the host's spouse in, and a guest's game only the guest's. What "moving in" means, from the scripts: at
a new day `npcs_on_new_day` gives a roommate the schedule `Schedules/roommate_schedule` (`_friday`, `_festival`) instead of
`T2R.request_schedule`, then `roommate_to_sleep` puts a spouse in the bed (`spouse_wake_position`, animation sleep) and a pet on the
floor; `perform_schedule_swap` puts a roommate whose schedule is "away/at home" at home with the routine `<npc>_roommate`; and
`process_t2_action` ignores the schedule's animation, outfit, activity and routine actions for a roommate at the farm.

**The registry.** The host's claim registry (`docs/SYNC-PROGRESS.md`) already derives, from every stored record and from the host's own
relationships, who is dating, engaged to or married to whom. It now also keeps `romance_spouse` (villager -> player) for the status
"spouse" only, **one spouse per player** (the first the records name; the game has one `ARI.spouse()`), only for a villager the player
holds in the claims. It is part of the `romance_claims` event (`spouses`), sent to every game that joins and when it changes; a guest
accepts an entry only if the same player also holds the villager in the claims, and the list is bounded. Because the registry comes
from the stored records, **a married guest's spouse stays at the farm while the guest is offline**, like the host's would; the
marriage ends when the record says it ended.

**What each game does** (`__mistrimulti_story_house_pass`, from the `game.new_day` hook and every 3 seconds, not during a cutscene or
the end of the day). For each villager the registry lists for *another* player (and, for Juniper and Hayden, the pet), that is not a
roommate in this game already, and that the game says can be married:

* *At the start of a day* (the hook runs right after the game's `new_day`, so every villager is at the start of the day's schedule):
  if the villager is not in the room the player is in, the game's `perform_schedule_swap` makes the roommate schedule at once and the
  villager wakes up in the house: a spouse in the bed (the game's `roommate_to_sleep`, which asks the villager's status, so the
  status fact reads "spouse" for that one call and is put back at once), a pet on the floor. **One bed:** if the player already has a
  spouse here, or another spouse was just put to bed, the villager starts the day standing on a free spot of the house instead
  (`roommate_home_position`); the villagers keep their order, so with two spouses the player's own has the bed, and with none the
  lower villager number does.
* *In the middle of a day* (a marriage, a player joining, a villager in the room the player is in): the game's deferred
  `swap_schedule_request`, which the game performs when the villager is out of the player's sight, up to three tries a day each.
* From then on the villager follows the roommate schedule the game's clock gives (the same in every game), and the host's day plan
  (`npc_plan`) carries that schedule name like any other. A guest does not steer a villager it moved in today (the plan from the host
  may still say "village" for a moment while the host's own swap is pending, and the swap would only send the villager out again).
* *When the marriage ends* the villager is sent back to the schedule `T2R.request_schedule` gives, by the same deferred swap.

| What | Result |
| --- | --- |
| Host married, guest not | the host's game moves its spouse in as always; the guest's game moves the same villager in |
| Guest married, host not | the guest's game as always; the host's and any other guest's games move the spouse in |
| Both married | both spouses live at the farm in every game, one in the bed and one on the floor (a second bed is not used, see limitations) |
| The guest is offline, or never joins this session | their spouse lives at the farm all the same, as long as the host has their record |
| The marriage ends or the record is lost | the villager goes back to the village schedule (the next day at the latest) |
| Dating or engaged | not a spouse: the villager stays in the village (the game's rule) |
| Two players | cannot be married to the same villager (the one-partner rule is unchanged) |

Hearts, dialogue, gifts, "talked today" and the wedding itself stay per player: only the villager's body is shared. The player's own
game still treats the villager as it always did (the guest's spouse is the guest's `ARI.spouse()`, the others are only housed).

## Cutscenes: the safe rule

**A cutscene is a private viewing. The mod does nothing in a game while its cutscene runs, and nobody is held for it.**

| Question | Answer |
| --- | --- |
| Do others stop? | No. The clock package keeps the world time running while at least one other player's clock runs (a player in a cutscene has a stopped clock, as in the game). |
| Do others see anything of it? | They see the player's figure in the room as usual. The scene's throw-away actors are local; the real villagers are untouched in every other game. |
| Can a scene soft-lock anybody else? | Nothing waits for it. The one coupling is the end of the day (all asleep), and the clock package already ends the day 60 seconds after 2 am for a player stuck in a scene. |
| What changes in other games, and when? | Only the lasting effects of the *world* scenes, once the scene is over (the end, or the skip): objects removed, an area cleared, a story quest started or advanced, a spell. These are the same effects the game applies at the end of every scene; the viewer's game already applied them, the others get them from the mirror, **and play the scene themselves** (see [Cutscenes that every player watches](#cutscenes-that-every-player-watches)). |
| What happens to the host's save? | The host applies the viewer's world effects to its own game, so they are saved with it. |
| What if the viewer's game dies in the scene? | Nothing was claimed (the pass is paused during the scene); the others never saw a half-done effect. The viewer replays it. |
| Same scene triggered in two games at once? | Both play it; the effects are idempotent (see above). |
| Heart events and romance scenes | Private from start to end. They are not claimed, not mirrored, and the villagers they use are throw-away actors. Nothing in them reaches a villager of another game. |
| A world scene a player never watched | They get its lasting effects and, if the scene can be shown safely, the scene itself when their own conditions start it. A scene that cannot be shown safely, and any scene older than a new character, is applied without the scene (the rule `docs/SYNC-PROGRESS.md` gives a new guest); items and baths are paid, heart changes are not; spell and mana are given. |
| Late join while somebody is in a scene | The snapshot is only data and goes out at once, also while the host is in a scene. |

## Cutscenes that every player watches

**Why.** A world story scene used to be a private viewing whose effects were also written into every other game's history, so the
other players never saw it (real game 1.0.8: the guest watched the day-2 dragon cutscene, the host never did). The decision now is:
every player *sees* the important story scenes themselves and may skip them with the game's own skip; what the scene changes in the
world, and what it pays, still happens once per world and once per player.

**What the game does (from its scripts).** A scene starts by itself in three ways, all of which test the scene's data in the
player's own game: an area of a room (`trigger`, spawned by `Mist.on_room_start` when `check_cutscene_eligible` holds), a quest task
that waits for it (`QuestQueryType.Cutscene`, started by the player object when the quest is at that task and the player is in its
area; afterwards `MIST.arbitrary_quest_to_progress` advances the quest) and the night (`when_sleeping`, `Mist.on_end_day`).
`check_cutscene_eligible` needs: the scene's `requirements`, not in `scene_history` (unless `can_repeat`), the story mode if the scene
needs it, not played today. `clean_up_scene` (end *and* skip) then marks the scene played, removes its objects
(`trigger_scene_object_removals`, unless the scene's script already did and set `removed_scene_objects`), advances or starts its
quests, gives spell and mana, **always** adds the scene's baths, and gives its items unless the scene gives them once and it was
already in the history. Gates (`SeenCutscene`) read `scene_history`, which is why the mirror used to insert the scene there.

**Design: a world scene is applied to the other games as a *held scene*** (`mistrimulti_story_apply_scene_view`):

1. The *world effects* land at once, as before (history and the `cutscene_seen_` fact, so every gate that reads the scene agrees;
   removed objects, cleared area, plaza, spell, mana), once, because it happens when the scene is new to the game.
2. The scene stays in the history, but the game's data for it is switched to `can_repeat = true`, so the trigger the game itself arms
   (area, quest task, night) still offers it. The held scenes are listed in the world fact `mm_view` (scene -> game day; for a guest
   also in the `view` field of the progress section `story_rewards`, [SYNC-PROGRESS.md](SYNC-PROGRESS.md)), so a restart of the
   game or a rejoin in another slot does not lose them.
3. **Quests are held** (`__mistrimulti_story_cap`). The quests a held scene belongs to are brought by the mirror only as far as the
   scene allows, in that game only: a quest it *starts* is not started (nor completed behind its back: the scene would restart a
   finished quest, `if !active.contains_key`), a quest that waits for it in a task (query target) or that its `requirements` read at a
   stage (`QuestIsAtStage`) stays at that stage, a quest it must find *active* is not completed. So the scene can start and the quest
   advances **once** (the scene's own `quest_to_progress` / `arbitrary_quest_to_progress`), after which the mirror brings the game
   up to the rest. The levels come from the game's data; the mirror itself is unchanged (claims, max, snapshot).
4. **Viewing** is noticed while the scene runs (every tick: `MIST.active_cutscene` is a held scene): the repeat switch goes off at
   once (it is never offered a third time) and the game is told its objects were removed (`MIST.blackboard.set(
   "removed_scene_objects", true)`), so the end of the scene does not remove them again. Skipping ends the same way. When the scene
   is over the next pass: if the scene gives its items only once, they are given now (the game does not, the scene was in the
   history); baths and everything else were given by the game. Rewards of the scene's quest step are the game's, and the ledger
   (below) records them as the player's own step. The viewer's claim finds nothing new: the scene and the level are in the mirror.
5. **Applied silently instead** (today's behaviour, items and baths paid at once, the reason logged by `mmapi_log_info` and listed by
   `mistrimulti.story` as `why`) when the scene cannot be shown safely:

   | Reason | Why |
   | --- | --- |
   | no area, no quest task and not at night (`manually_activated`, started by a dialogue or an object) | nothing the mod can verify starts it; the player might never see it |
   | it advances a story quest at a stage nobody can tell (no `QuestIsAtStage`, no task waits for it) | the replay would advance a mirrored quest a second time |
   | a quest condition inside an `or`, an alias or an inversion in its requirements; a world fact it needs to be false, or a world scene or finished story quest it needs *not* to be seen / done | no cap can be derived, or the mirror itself would make the scene unreachable |
   | the game repeats it anyway (`can_repeat` in its data), or it builds objects (`upgrade_the_saturday_market_plaza`) | a second application is not harmless |
   | the player is already past the quest step it belongs to, or has finished the quest it starts | the scene would advance the quest again |
   | the scene needs the story mode and it is off | it will never be offered |
   | eight scenes are already waiting | no crowd of held quests |
   | a *new character* (its rewards ledger is not yet seeded) and the scene was over when it arrived | nobody is owed the story so far, scenes included |
   | **the scene is not watched within seven game days** (`MISTRIMULTI_STORY_PATIENCE`) | the way out of every other case: nothing waits for ever (a requirement that can never be met, a task the player cannot do, a player who stops playing) |

   A held scene is also given up this way when the player goes past the quest step by another path, or when the game stops knowing
   the scene. A record that no longer holds the scene in its history (an older save) pays nothing for it.
6. Order: the host sends a scene before the quest levels that belong to it, and a pass applies scenes before quests, so a game never
   learns the level before it knows what holds it.

**What is idempotent.** The world effects are applied once per game (a game applies a scene only when it is in neither its history
nor in the mirror's): the objects the scene removes, the cleared area, spell and mana are not repeated at the viewing (spell and mana
are guarded by the game itself; the objects by the blackboard flag; the cleared area is a no-op on a second pass). Nothing the
player earns (gold of a quest step, items, baths, renown) is paid by the mirror before the viewing, and the ledger moves with the
player's own step, so every reward is paid once per player.

| Situation | Result |
| --- | --- |
| A watches, then B | B received the effects (gates open, objects gone) and sees the scene when its own conditions start it; one removal, one spell, one set of rewards in each game |
| B watches first, or both at once | whoever finishes first tells the mirror; a game that has not played the scene holds it; a game that played it at the same moment finds it already in its history and holds nothing |
| B is in the scene when A's news arrives | nothing is applied during a scene; at its end the scene is in B's history and the mirror's news changes nothing |
| B joins late, or was away | held like any new scene (if B's ledger is seeded); a brand-new character gets the scene silently |
| B or the host restarts while waiting | `mm_view` is in the save (host: the world facts; guest: the progress record), the switch is set again at the first pass |
| Packets lost, duplicated, reordered | the event layer delivers the scene and the levels once and in order; the claim and the mirror are max-merges |
| B never watches | after seven game days the scene is applied silently and the quest is released |
| Heart events, romance, weddings | as before: private, never held, never claimed |
| Skip | the game's own skip goes through the same clean-up, so it counts as a viewing; whether a scene can be skipped is the game's `can_skip` |

A gate that reads a quest a held scene holds (`CompletedQuest`) opens in that game when the scene has been watched (or after seven
days); gates that read the scene itself open at once.

## Festivals and calendar events

A festival, a birthday, a market day or a shop's opening hours are functions of the date and the time, which the clock package
makes the same for everybody (the host's date; the day ends when everybody sleeps). `Festival.is_today()` reads the date and
`CANCEL_FESTIVALS`, so no festival state needs to travel except the cancel flag, which follows the host's plan.

* **Entering together or being held out.** There is nothing to hold: a festival has no start the game waits for. The decoration is
  built when a room is built, and the associated quest runs in every game. A player who arrives at 3 pm sees the same festival day
  as one who was there at 9 am. A festival cutscene is triggered by walking into its area (`Festival.room_start` ->
  `MIST.spawn_trigger`), per player, and is private like every cutscene.
* **Late join.** A guest that joins mid-festival takes the host's date from the clock package; it builds the festival when it enters
  the room. If its own date differs from the host's world (it rejoined a day behind or ahead) the clock package tells it to rejoin
  and this package does not use a plan that is not for its own day.
* **Festival dates, partners, challenges and prizes** (`festival_date_partner`, `quest_artifacts`, stocks) are personal and in the
  progress record.
* **The festival's associated quest** is excluded from the story mirror on purpose.

## Event kinds

| Kind | Direction | Payload | Handlers |
| --- | --- | --- | --- |
| `story_claim` | guest -> host (request), result to every guest | `{ q:[[name,level]], sc:[name], f:[name], k:{n,b,t} }`, at most 20 entries a list | host `on_request` merges (validated); `on_result` merges; `on_reply` clears "pending", remembers a refusal |
| `story_delta` | host -> guests | same shape | `on_event` (sender must be the host) |
| `story_snapshot` | host -> one game (blob) | mirror + `se` (story mode) | `on_blob` (sender must be the host); starts or follows a host session |
| `story_sync` | guest -> host | `{}` | `on_event` queues a snapshot; also carries `on_peer` (the host queues a snapshot for a joining game) and `on_gap` |
| `npc_plan` | host -> guests | `{ d, s[], cf }` | `on_event` (host only, validated: length, types, day) |
| `npc_pos` | host -> guests | `{ d, l[], a[] }` | `on_event` (host only, validated) |

No event kind was added for the rewards or the spouses. The rewards use no network at all (each game pays itself from the mirror it
already has); the registry of married players rides on `romance_claims` of the progress package (`{ claims, spouses }`), and the ledger
on its `story_rewards` section.

All sizes are bounded (names 96 characters, schedule names 160, lists 20 or 4096 in a snapshot, counters 0-1000). A malformed
claim or an event from the wrong sender is dropped without effect; nothing in this file can throw into the game (the tick is wrapped,
and each change the game is asked to make is wrapped on its own).

## Interaction with other areas

* **Clock** (`docs/SYNC-CLOCK.md`): the date and the time of day are the host's. This package relies on it for the plan's day and for
  festivals, and does not touch the clock.
* **Progress** (`docs/SYNC-PROGRESS.md`): a guest's `seen.scenes` is the player's whole history; world scenes mirrored here enter it
  like any scene and are stored with the player, so a returning guest keeps them. Story quests are excluded from the personal
  quest section and handled here. The romance claim registry keeps its rules and gains the list of spouses ([Spouses](#spouses-of-other-players-live-at-the-farm));
  the section `story_rewards` carries the rewards ledger of a guest ([Rewards](#rewards-of-a-shared-step-for-the-players-who-did-not-do-it)).
* **Farm, ranch, containers**: objects the farm package synchronises (the farm) are theirs; turn-in boxes that quests place in other
  rooms are placed by the game's own function in each game, their contents are not synchronised by this package.

## Tests

`python3 tests/test_story.py` (about two minutes): the real GML over the simulated helpers and a lossy network (5-15% loss,
duplication, jitter), with a stand-in game (`tests/story_fake.py`: quests with turn-in boxes, cutscenes of every kind, world gates,
six villagers with schedules, rooms and activities, a hundred chapter quests, task and quest rewards with gold, items, renown and quests
to start, scenes with items and baths, a roommate model that fails for a villager who is neither a spouse nor a pet, as the
game's `roommate_to_sleep` does, and the game's scene eligibility and `clean_up_scene` (repeat switch, history, `give_items_once`,
baths, a second removal that erases another object, `quest_to_start` for a quest that is not active, the blackboard flag). 52 scenarios:

| Scenario | What it shows |
| --- | --- |
| start, host progress, guest progress | steps mirrored by both sides, each game's quest log changed once, rewards personal, personal and festival quests never cross |
| same step race | three players take the same step, the same scene, fact, counter, relative scene effect: one step in the world |
| world scenes | objects, area, spell, quest and gate scenes reach every game once; heart events, wedding, dates stay private |
| facts and counters | only gate facts, only upwards, survive an older host save |
| late join, away and back, guest restart | arrival after everything, a guest silent for more than 10 s, a restarted guest with an older and with a *newer* save |
| host restart | guests' progress returns once; a claim in flight during the restart is not lost or doubled |
| cutscene hold | a guest in a scene claims and applies nothing, others carry on; the same for the end of the day; a host in a scene still serves a joining game |
| many changes | 100 steps at once, a full send queue (delayed, not lost), a late joiner served from the snapshot |
| refused claim, claim in flight, quiet | a refused claim is asked once; a waiting claim is not repeated; a converged world sends nothing |
| merge rules, hostile input | max, idempotent, bounded, validated; about forty malformed, oversized, personal or spoofed claims, deltas, snapshots and plans change nothing |
| villagers | every game follows the host's day plan for 15 game hours with different local choices; a villager in sight is never touched, a drifted one is brought back out of sight; the mod never writes a position; a guest's heart event moves nobody else's villagers; the festival flag and day check |
| data unreadable | if the game's data cannot be read the story sync switches itself off and the villagers keep working |
| rewards: offline and restart | a guest away for more than ten seconds, and one restarted from an older world copy with its old ledger, are paid once for what they missed; a restart from an even older copy but the newer ledger gets nothing again |
| rewards: new character | nobody is owed the story so far (guests and a host without a ledger are seeded); the next step is paid to all |
| rewards under loss | three players, two taking the same step at the same moment, 15% loss and duplication: every reward of every game exactly once, renown once |
| rewards: scenes | a world scene's items and baths reach the players who did not watch it (also one who was away), once; two watchers are each paid once; a heart event's item stays with the watcher |
| rewards: a failure | a reward that raises is logged and not repeated; the next step is paid |
| spouses: a guest's | the guest's spouse and pet live at the farm in all three games for 14 game hours (roommate schedule, bed or floor, same place and activity in every game), on every day, with the mod never writing a position |
| spouses: two | the host's and a guest's spouse both live there in every game; one bed, the player's own spouse has it |
| spouses: a guest who is away | the spouse lives there with the guest not connected, and with nobody connected at all |
| spouses: a marriage in the middle of a day, a divorce | out-of-sight deferred swap, the guest's own game follows the plan, a divorce sends the villager back |
| spouses: in sight, Fridays, festivals | a villager in the player's room waits; the game's Friday and festival roommate schedules are used |
| spouses: a bad registry | unknown names, wrong types, the player's own spouse, a pet listed as a spouse: nobody moves |
| held scene: watched by everybody | the guest watches the dragon scene, then the host and the other guest play it themselves (one skips): effects, spell, items, baths, gold, quest step once each; gates open at once |
| held scene: any order, all at once, loss | five orders, three players at the same moment, 15% loss and duplication: every game plays it once, nothing twice |
| held scene: late join, new character, restarts | a returning player is shown it, a new character gets it silently; host and guest restarts keep the waiting scenes; a corrupt list in a save is dropped |
| held scene: gates, quest tasks, quests it starts, night | the gate opens everywhere at once; a quest task that waits for the scene stays there; a quest the scene starts is neither started nor finished early; the night scene |
| held scene: safe fall-backs | hand-made trigger, unknown quest step, `or` over a stage, a fact that must be false, a scene that must be unseen, repeatable, plaza, story mode off, player already ahead, more than eight scenes, seven days without watching: applied silently, reason logged |
| held scene: in the scene when the news comes, record replaced, leaving the world | no double effect, nothing paid for a scene that is not in the history, nothing left switched on |

`python3 tests/test_progress.py` adds: the section `story_rewards` (round trip including the waiting scenes, 21 malformed variants, new character's empty ledger,
the host's ledger replaced by the player's) and the spouse registry (only marriages, one per player and per villager, told to every
game, break-ups, restarts, a player who is away, a late joiner, a hostile `spouses` list).

`python3 tests/mutate_story.py` breaks the GML in 44 ways and fails if any test still passes: the 20 rules of the story and the
villagers (personal quests accepted, the story lowered, a stage that does not exist, no broadcast, no completion, boxes left, acting
during a scene, no snapshot, heart events as world, the festival quest mirrored, a villager moved in sight, a plan on the wrong day, a
claim repeated, a refusal repeated, a spoofed delta, an unknown schedule, an old mirror kept for a new host, merging before knowing it
fits, activities steered in sight, guests that cannot tell the host they are ahead), nine for the rewards (a player's own step paid
again, a story quest started by a reward, the ledger not moved, the past owed to a new character, scene items or baths missing, the
quest's own rewards or the renown missing, payment from the start of the quest every time), nine for the spouses (no status for the
game's bed function, a player's own spouse moved in twice, everybody gets the bed, a divorce leaves the villager, a villager in sight
moved at once, the plan swaps a housed villager out, the pet left in the village, a villager nobody can marry, Fridays) and six in the
progress package (a dating partner as spouse, several spouses a player, spouses the claims do not hold, a marriage that stays after it
ended, the host's ledger kept after a restore, a ledger level of zero). All are caught.

`python3 tests/mutate_story_views.py` breaks the shared-scenes part in 25 ways (a scene applied silently, the game not told to offer
it, quests not held, objects removed twice, items never or twice paid, waiting scenes forgotten by a restart, nobody gives up, a player
who is ahead made to wait, the switch left on, hand-made triggers, new characters shown the past, quests a scene starts, unknown quest
steps, `or` conditions, facts and inversions the mirror breaks, query targets, no limit, no sorting at the start of a pass, a record that pays for a missing scene, a world that
is left with scenes on, repeatable scenes, corrupt saves, late noticing of the viewing) and four in the progress record. All are caught.

Also required to keep passing: `tests/test_event_features.py`, `tests/test_event_layer.py` (syntax of every GML file) and
`scripts/lint-asm.py`.

## Assumptions about the game that could not be verified

Each of these must be confirmed in the game (the checklist covers them). None could be checked here: the scripts were read, the
game was not run.

1. `QuestCategory.Story` is the world's story and nothing else; every festival quest is reached through
   `FESTIVALS[i].prototype.associated_quest`.
2. `QUEST_LOG.start(name, stage)` is safe to call outside a normal flow in a game that did not play the step (turn-in boxes are
   written to `GRIDS[...]` and assert if another object is there: then that quest is refused and left to the player), `ActiveQuest.current_stage` may be assigned,
   and `QUEST_LOG.active.remove`, `completed.insert`, `completion_timestamps.insert` are enough to complete a quest without its rewards.
   `refresh_achievements` is not called (achievements follow at their next refresh).
3. `CUTSCENES.get(name)` has the fields read in `load_cutscenes` (`test_target`, `object_removals`, `nuke`, `quest_to_start`,
   `quest_to_progress`, `spell_to_unlock`, `mana_to_set`, `romantic_choice_warning`, `heart_level_changes`), `SceneTestTarget` has
   `MainStory`, `DragonStory`, `MarriageAndChildren`, and "main/dragon story" targets really are the world's story.
4. `trigger_scene_object_removals(name)` is idempotent, the clear-area loop and the plaza upgrade reproduce what `clean_up_scene`
   does, `ARI.learn_spell`, `ARI.mana_max`, `ARI.set_mana` exist as read.
5. `WORLD_MODS[i].requirements`, `REQUIREMENT_ALIASES`, `requirement_is_alias`, `Requirement.Or/SeenCutscene/WorldFactIs/BrokeFireSeal/
   SeridiaTransformed/SaturdayMarketUnlocked/SuppliedItems`, `WorldMod.LEN`, `FestivalId.LEN` exist, and the parsed shapes are as in
   `parse_requirements` (`SeenCutscene`: array of names; `WorldFactIs`: array of `[name, value]`).
6. `T2R.read(name) == true` for a fact written `true`; `T2R.write(name, true)` is enough to set a gate fact.
7. `NPCS[i].swap_schedule_request = { schedule_name, finish }` is honoured by `npcs_on_step` exactly as read, including for a villager
   that is a roommate or the player's spouse (the guest's own spouse follows the host's plan; the code paths for roommates
   (`BANNED_ROOMMATE_ACTIONS`, `schedule_roommate_jump`, the Aldaria branch of `perform_schedule_swap`) were not run in that
   situation); `T2R.schedule_name(i)` returns the name that `T2R.schedule_names()` lists; `NPCS[i].location_position.location_id`,
   `activity_handler.activity.id/state/request/request_activity`, `ACTIVITIES.get`, `Activity.LEN`, `ActivityState.Traveling` exist.
8. `CANCEL_FESTIVALS`, `STORY_ENABLED`, `SECRET_NARROWS/BEACH/TOWER` are macros over globals that mod code may assign.
9. `MIST.is_running()` is true from the moment a scene is requested to the end of its clean-up (including the skip), and
   `ARI.end_of_day_status` is set for the whole end-of-day sequence.
10. `string_char_at`, `string_copy`, `struct_remove`, `array_delete`, `typeof` behave as GameMaker documents; a request's `on_reply`
    context carries `lost` and `expired` as `docs/EVENT-LAYER.md` says.
11. Clocks stay within about 25 game seconds of each other (the clock package), so that "same room after 3 passes" does not correct
    villagers that are merely mid-walk.

*Rewards:*

12. `grant_quest_rewards(list)` takes a `List()` built in the mod (`List()`, `.push`, `.count`, `.get`, as the game's own code uses
    them), and gives the rewards of that list when it is called outside the hand-in flow (in particular it needs no open popup).
    `QuestRewardType.Quest/Renown`, `reward.quest_name`, `reward.type`, `task.reward_list`, `quest.reward_list` are as read in
    `QuestDatabase.gml`; `RenownEntry.Quest(name)` pushed to `ARI.pending_renown_entries` is what `QuestLog.complete` does, and the
    renown sequence of the next day pays it.
13. `T2R.write(name, <number>)` and `T2R.read(name)` round-trip a number under a name the game never uses (`mm_paid_<quest>`), such
    facts are saved in `t2_world_facts` with the host's world (`T2R.read_world`) and loaded back by `LoadGame`, and nothing deletes
    unknown facts (the daily update only writes the facts it knows).
14. `QUESTS.keys()` lists every quest and `QUESTS.get(name).category`, `.tasks.count()` exist (the ledger section reads them).
15. `mist_give_items_after_scene(items, location_position)` and `player_wake_position()` can be called from the mod, outside a scene,
    with the `given_items` of `CUTSCENES.get(name)`; `ARI.free_baths` is a number.
16. A scene's `give_items_once` is ignored by the silent route on purpose: the item is given when the scene first enters a player's history. A
    held scene honours it: the game gives the items of a scene that does not give them once, and this file gives those of a scene that does,
    after the viewing (the scene was in the history, so the game would not).

*Shared scenes (the held scene is only as good as the first two; the in-game checklist 31 to 38 comes first):*

23. `CUTSCENES.get(name)` returns the one struct the game also reads, and `can_repeat` on it is read by `check_cutscene_eligible` each time
    (not copied at load). `scene_history` is what `SeenCutscene` and the eligibility test read; `MIST.scenes_played_today` is a set with
    `contains`; `MIST.active_cutscene.id` is the running scene's name for the whole scene, skip included; `MIST.blackboard.set(
    "removed_scene_objects", true)` before the end of the scene is what `clean_up_scene` reads (`try_take`), and the blackboard is cleared
    at the end only.
24. The shapes read from quest and requirement data: `QUESTS.keys()`, `quest.tasks.get(t).query_targets` is a list with `count()`/`get(i)`
    of structs with `type` (`QuestQueryType.Cutscene`) and `cutscene`; `QuestIsAtStage` is an array of `{ quest, stage }`, `QuestIsActive` an
    array of quest names; a scene's `trigger` is undefined or a struct with `manually_activated`; `when_sleeping`, `give_items_once`,
    `requires_story_mode`, `can_repeat` exist on the scene. If the quest data cannot be read every scene is applied silently.
25. A quest task that waits for a cutscene is started only while the quest is at that task (so holding the quest there keeps the scene
    reachable), and the task's own `requirements` do not ask for something that only the player who watched first has. If they do the
    player waits until the seven days are over.
26. A second `trigger_scene_object_removals` for a scene whose objects are gone removes nothing or another object of the same kind: the
    blackboard flag prevents it at the end, but a scene whose script calls the removal itself in the middle (`std` function) still
    calls it a second time; this is harmless if the objects are unique in the grid (as `object_removals` identifies them by id only).
27. A scene replay in a game that has the scene's effects: `ARI.learn_spell` and the mana guard are idempotent, the area clear and the
    scene's own script do not fail on objects that are already gone.
28. The player's progress record is restored before the first story pass of the session (the held list is read once at that pass).
29. `T2R.write("mm_view", <text>)` stores text in the world facts like the status facts, and `json_stringify` / `json_parse` round-trip a
    struct of numbers.

*Spouses:*

17. `Npc.is_roommate()`, `is_spouse()` (reads the T2 fact `<npc>_status`), `prototype.dateable`, `NPCS[i].swap_schedule_request`,
    `brain_dead`, `talk_flag`, `location_position` behave as read; `perform_schedule_swap(i, name, false, CALENDAR.unified_time())`
    is safe to call from the `game.new_day` hook (the game calls it from its step), for a villager that is not in the player's room,
    and for a villager who is not a roommate in this game; its Aldaria branch puts the villager at home with the routine
    `<npc>_roommate` and touches `ARI.children` the way it does for the game's own spouse.
18. `roommate_to_sleep(npc)` works for a villager whose status fact reads "spouse" for the duration of the call and does nothing
    else with the status (it calls `spouse_wake_position()`, which needs a bed: the game warns and uses a safe position when there is
    none); writing the status fact does not trigger any other code (only `report_relationship` and the daily update copy it to the
    `<npc>_is_spouse` family of facts, and they are not called).
19. `Schedules/roommate_schedule`, `_friday` and `_festival` exist and are listed by `T2R.schedule_names()`; `CALENDAR.day_type()`,
    `Day.Friday` and `todays_festival()` exist.
20. A roommate schedule works for a villager who is not a roommate by `is_roommate()`: `process_t2_action` then does **not** drop the
    schedule's animation, outfit, activity and routine actions at the farm (`BANNED_ROOMMATE_ACTIONS`). If the schedule contains such
    actions for the hours the villager is at home they take effect instead of the villager's own `<npc>_roommate` routine; watch for
    a spouse who stands still, sits in odd places or leaves the house (checklist 23).
21. The T2 data accepts `Schedules/roommate_schedule*` for any villager (the schedule is named for roommates but it is data per
    villager: the T2 script for the villager must have one; a villager without one, such as a non-dateable one, never gets here).
22. `T2R.request_schedule(i)` returns the schedule the game would give villager `i` today (used to send a former spouse back).

## In-game checklist

Two game installs (or one plus `tests/test_live_game.py`), a host world on an autosave. `mistrimulti.story` in the MMAPI debug console
prints the mirror, the claims in flight, refusals, statistics and what was found in the game's data (`gate_scenes`, `gate_facts`).

1. **Start-up.** No error in the log; `mistrimulti.story` on both shows `ready: true` within a few seconds of joining, and
   `gate_scenes` / `gate_facts` list the bridge, secret and market gates (an empty list means the data could not be read: report
   `error`).
2. **Story step by the guest.** Hand in a story quest task on the guest. Within about 2 seconds the host's quest log shows the same
   stage (and the host's gold, items and renown are unchanged); then the other guest's. Check the turn-in box of the first stage
   appears in the host's copy and is gone when the stage is over.
3. **Story step by the host**, the same the other way. Save and reload the host: the story the guest made is still there.
4. **Same step at once.** Both players hand in the same task at the same moment: one stage in the end, each player paid once.
5. **A world cutscene** (for example a main-story one, or the one that opens the narrows secret): the host watches it. The guest's
   map changes (removed objects, the secret entrance) without the guest seeing the scene, and a spell the scene unlocks is learned.
   Then the other way round. Rejoin a guest that was away during one.
6. **Heart event, wedding, date** on a guest: nobody else's game changes, no claim is made (`stats.claims` does not move), no
   villager moves for the others.
7. **A cutscene on one player** while the other plays: the other is not paused, time continues, the day can end once both sleep.
   Skip the scene half way: its lasting effects still arrive.
8. **Villagers.** Start a new day. Compare where five villagers are at 9, 12, 15 and 20 o'clock on both screens (use two
   rooms). Check `swaps` / `steers` in `mistrimulti.story` and that nobody ever pops in or out in front of a player. The spouses are
   the subject of items 16 to 20.
9. **A conversation on the guest that swaps a villager's schedule** (a quest step, a date invitation): the host's plan wins within a
   few seconds; the villager is never moved in sight.
10. **Festival day.** Both players on a festival day: decoration, the festival quest, the shops, the associated cutscene (private).
    A guest that joins in the middle. `CANCEL_FESTIVALS` if you can set it.
11. **Facts.** Open a bridge or a secret place on one player: it is open for the other after the claim. Check that no unrelated T2 fact
    (`just my mood`) travels.
12. **Counters.** Open the same secret chest on two players: note whether both get the loot (documented limitation).
13. **Host crash.** Kill the host after a guest's story step, load the autosave: the guest's step returns within seconds
    (`mistrimulti.story` on the host) and nothing is applied twice (no second reward on the host).
14. **Version skew.** A guest with a mod build that does not know a quest: `refused` lists it, it is asked once.
15. Look in the log for "Story" warnings; there should be none in normal play. The F8 status line does not mention the story.

*Rewards* (steps 2 to 5 above also show them; here is the full check). Use a world where the guest and the host both have the same
items counted before: note gold, inventory, the mail and the quest log of both.

16. **A step by the host with a reward.** Hand in a story task that gives gold or an item (the quest menu lists the rewards of a
    task). The guest's gold or inventory rises by the same within a few seconds, once, and a message "Story reward: ..." appears.
    Repeat the other way round. Look at `mistrimulti.story` (`stats.paid`).
17. **The end of a quest.** Finish a story quest on one player: the other gets the last task's rewards, the quest's own rewards (the
    list in the quest-complete popup) and, if the quest gives renown, the renown at the next morning's renown screen.
18. **A guest that was away.** Close the guest's game, hand in two steps on the host, open the guest again: it gets the rewards of
    both steps once after joining, not on a second join.
19. **A new character.** A second guest who joins a story that is well on its way gets nothing for what was done before it; the next
    step is paid.
20. **A world cutscene with items.** The host watches a main-story cutscene that gives an item: the guest receives the item without
    seeing the scene (a free-baths scene: the baths too). A heart event on the guest: the item (if any) is the guest's alone.
21. **A step that starts another errand** (a task whose reward starts a non-story quest): the other player has that errand once.
22. **Crash.** Kill the guest within two seconds of a reward: it may be lost or repeated, but never more than that one reward.

*Spouses at the farm* (needs a character who can be married; the debug function `mistrimulti.progress` lists `spouses`, and
`mistrimulti.story` lists `housed`):

23. **A guest's spouse.** Marry a villager on the guest. After the wedding, sleep until the next morning (all players). On the
    **host**: the guest's spouse is in the farm house at the start of the day, asleep next to the bed (or on the floor if the host also
    has a spouse), and during the day follows the same routine as the host's would (goes out, comes back, sleeps). The pet of
    Juniper or Hayden comes along.
24. **Both married.** The host's and the guest's spouse are both in the house on both screens; look at the bed for overlap.
25. **The guest is offline.** Close the guest's game, restart the host's world: the guest's spouse is in the house next morning.
26. **A marriage that ends.** Break up (or divorce, if the game allows it): the villager is back in the village the same day or the
    next, and nobody else can start dating her/him until the host's registry shows it free.
27. **A marriage in the middle of the day** (the wedding is a cutscene): the other games move the spouse in out of sight, within
    seconds; never in front of a player.
28. **Friday and a festival day.** The spouses use the game's Friday / festival roommate schedule in every game.
29. **Dialogue and hearts** with the other player's spouse are the player's own: the host sees the guest's spouse as a friend, not as
    its own spouse (no "spouse" dialogue, no "kiss" prompt other than the greyed romance ones).
30. **Log.** No "A villager could not be moved into the farm house" warnings; if there are, `mistrimulti.story` `error` says why.

*Shared scenes* (the day-2 dragon scene is the first thing to try; `mistrimulti.story` lists `views` (waiting scenes), `why` (scenes
applied silently, with the reason) and `stats.shown / viewed / silent`):

31. **The reported case.** Guest watches the day-2 dragon scene. The host's game: the gate it opens is open, the objects it removes are
    gone, the dragon quest has not moved (`levels`), `views` lists the scene. The host then walks into the scene's area (or goes to
    bed, if it is a night scene) and sees it. Afterwards: no second removal, the spell once, the quest at the guest's step, the item
    once, `views` empty. Try the other way round, and both at once.
32. **Skip.** Skip the scene on the second player (hold the skip button): same result as watching it.
33. **Gold and items.** Note gold, inventory and baths of both before: each gets the step's reward and the scene's items once; the
    mirror pays nothing for the held step until the scene has been watched.
34. **A quest that waits for a scene** (a quest task whose area starts a cutscene): the second player's quest stays at that task until
    the scene was watched; it is not marked done. A quest the scene starts is not in the second player's quest log until then.
35. **Restart.** While the scene is waiting restart the second player's game (and then the host): `views` still lists it and it plays.
36. **Seven days.** Leave a scene unwatched and sleep seven times: it is applied silently (items and baths arrive), the quest is
    released, the log says why.
37. **A scene that is applied silently** (`why`): one that a dialogue or an object starts shows there with the reason and behaves as it
    did before this feature (no scene, effects at once). Check that none of the scenes of the main story you meet is in `why` for a
    reason you did not expect.
38. **Joining late.** A returning character that joins after the scene sees it; a new character does not, and is not blocked.

## Known limitations

* **A reward is paid when the mirror reaches the game, not when the step is taken,** and a reward that fails is lost rather than
  repeated. A guest that dies within about five seconds of a reward may lose or repeat that one reward (the core and the progress
  record are separate uploads). A new character is deliberately not owed the story so far. Rewards that depend on the player's
  own state at the hand-in (a tier reward computed from an animal or a gathered score) use whatever the artifact says in the game
  that pays; the animal festival is not a story quest, so none of them is affected today.
* **Spouses: with one bed, the second spouse starts the day on their feet** (the game's `roommate_to_sleep` always uses the one bed
  spot; the mod does not look for a second bed). Later the villager follows the roommate schedule like any roommate.
* **Spouses: a housed villager is not a "roommate" to the game in a game that is not their player's.** Besides the banned schedule
  actions (assumption 20), `Interact`, the end-of-day "can talk" flag and the pet placement on loading a save (`par_NPC`, `LoadGame`)
  only know the player's own spouse: after the world is loaded again the housed villager is put where the schedule says (the
  mod's next pass moves them in again), and a housed villager does not wake up "ready to talk" the way the player's own does.
* **Spouses: a hostile record can marry one villager per player** (and only one who is dateable and unclaimed); the village loses
  that villager's schedule in every game. The UDP transport does not authenticate players (see the last limitation).
* **Spouses: the wedding, children and the spouse's gifts and dialogue stay with the player** whose spouse it is: the host's
  game shows a guest's spouse as a friend. Children (`ARI.children`) are per player and are not moved.
* **Edits made by a scene's own script** (`__erase_node`, `nuke_tut`, `handle_farm_chores`, house repairs) are local to the viewer's copy
  of the room they happen in. Only `object_removals`, `nuke` and the plaza upgrade are replayed for the others; other rooms'
  objects are not synchronised by any package.
* **Facts that data files write** and the code never mentions are not classified; only the dragon-story facts and the facts world
  gates read are shared. A story that depends on another fact needs it added to `mistrimulti_story_fixed_facts()` (or a gate that reads it).
* **Villagers: seats, paths and animation variants differ** between games; positions agree at the level of room and activity. The
  host's own simulation is the reference, which means a villager is exactly where the host's player would see it only when the host's
  player is in the room; elsewhere it is the host's *simulated* position.
* **A guest's own spouse/roommate** is moved in by the guest's own game, and the host's plan (which carries the roommate schedule the
  host's game gave the same villager) agrees with it. If the host's game fails to house the villager the plan says "village" and the
  guest's game follows it (assumptions 7 and 17).
* **A guest's conversation cannot change the world's villagers**: a schedule swap it causes is overwritten by the host's plan. A swap
  that is the world's (a story step) happens through the mirrored story state on the host's next day.
* **Two players opening one secret chest** within a second can both be paid; the chest contents are not host-arbitrated here.
* **After a host crash and an older autosave**, connected guests re-assert the story they made after it. If that is not wanted (a
  deliberate rollback) the guests have to rejoin so that they load the host's world again.
* **No notification** tells a player that the story moved because of somebody else.
* **A held scene is only offered by the triggers the mod can read** (an area, a quest task, the night). A scene that a dialogue or an
  object starts is applied silently (the second player misses the scene itself). A scene that needs something only the first
  viewer had (an item, a time window) is applied silently after seven days.
* **A quest held for a scene holds its gates**: a gate that reads the quest (`CompletedQuest`) stays closed in that game until the
  scene has been watched, and the quests that follow it wait too (a few days at most). A player cannot jump ahead in a chain of
  held scenes: they are watched in the story's order.
* **A scene can be watched twice only by accident**: a scene whose script calls the object removal itself in the middle removes the
  object again in a game that already has the effects (harmless if the object is unique; see assumption 26).
* **A scene older than a new character is never shown** to it, and a character that comes back with a record older than the scene
  sees it again (that is correct: they have not seen it).
* **Timing.** A step takes about a second to leave the player's game and another to reach the others; a world scene's effects land
  a second after the viewer's scene is over.
* **A plan that does not fit in one event** (more than about 45 villagers with 160-character names) is not sent; the game has 34.
* **The UDP transport does not authenticate players** (`docs/PLAYER-DATA.md`): a claim is checked against the game's data, not against
  who the sender really is, so a hostile friend can advance the story, though only by what the data allows.

## Extending

* A new world fact: add the name to `mistrimulti_story_fixed_facts()` (or make a gate read it in the game's data) and extend
  `tests/story_fake.py` and the facts test.
* A new kind of world state follows the pattern: put it in the mirror (`st`), `__mistrimulti_story_local` (what this game has),
  `__mistrimulti_story_up` (ahead), `mistrimulti_story_merge` (validate and max), `__mistrimulti_story_down` (apply), the snapshot.
