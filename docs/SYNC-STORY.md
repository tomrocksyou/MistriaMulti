# Story, villagers, cutscenes and festivals

The world's story (story quests, the cutscenes that change the map, the facts that open bridges and secret places), the villagers'
whereabouts, and what happens around a cutscene or a festival when several people play. Code:
`mod/mistrimulti/gml/MistriMultiStory.gml` (about 800 lines, no new MMAPI hook), small additions in `MistriMultiBoot.gml`. It
runs on the event layer (`docs/EVENT-LAYER.md`) and builds on the clock (`docs/SYNC-CLOCK.md`: one date and time of day for
everybody) and on the personal records (`docs/SYNC-PROGRESS.md`: friendship, romance, personal quests, mail, seen scenes).

Nothing here has run in the real game. The GML ran against a stand-in game (see [Tests](#tests)). [What to check in the
game](#assumptions-about-the-game-that-could-not-be-verified) and the [checklist](#in-game-checklist) list everything the stand-in
cannot show, and [Known limitations](#known-limitations) is the honest list of what this does not do.

## Decisions

| Question | Decision |
| --- | --- |
| Who owns the story? | The host. A guest's own game applies a step first (the game has no way to ask permission), then tells the host; the host merges it with "max" and tells everybody. The host's game applies guests' steps to its own quest log, so they are in the host's save. |
| What is world and what is personal? | See [the audit](#audit). Story-category quests, the cutscenes that change the shared map or open a gate, the facts those gates read and the secret-chest counters are the world's. Everything the player earns, says, gets or feels is personal. |
| Villagers: host simulation or per-game simulation? | **Per-game simulation, steered by the host.** Every game keeps simulating its villagers (the game cannot be told to stop), the host decides *which schedule each villager follows today* and samples *room and activity* every 3 seconds, and a guest swaps its villagers' schedules to match, only ever out of its player's sight. Reasons below. |
| What does a cutscene do to the others? | Nothing. It is a **private viewing**. It never pauses, moves, waits for or waits on anybody else; only the lasting world effects of the scenes that have any are shared, once, when the scene is over. |
| Festivals? | A festival is a function of the date, and the date is the clock package's. Nobody is held out and nobody has to enter together; there is no start to miss. See [Festivals](#festivals-and-calendar-events). |
| Heart events? | Personal. The game plays them with throw-away actors and respawns the real villagers afterwards; nothing about a villager travels from a guest to the host, so a heart event cannot move a villager for anybody else. |
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
| Quest rewards and renown | the player who hands in | a mirrored quest gives **nothing** to the mirroring player; see [limitations](#known-limitations) |

### Cutscenes (`Mist.gml`, `MistRuntime.gml`, `Std.gml`)

What `Mist.clean_up_scene` does when any scene ends, and what is shared:

| Effect | Shared? |
| --- | --- |
| `scene_history`, `scenes_played_today`, the `cutscene_seen_<name>` fact | personal for most scenes (`docs/SYNC-PROGRESS.md`); **world** for the scenes below, which every game adds to its own history |
| `object_removals` (objects erased from a location's grid), `nuke` (a rectangle of the town cleared), the plaza upgrade | world: applied once in every game when the scene is done by anybody |
| `quest_to_start`, `quest_to_progress` | the quest effect is shared as *quest state* (a story quest is mirrored), never as "progress one step" |
| `spell_to_unlock`, `mana_to_set` | the player's, **and** granted to a player who did not watch a world scene (they would otherwise miss it) |
| `given_items`, `drop_items`, `status_effects`, `baths`, `set_health_to`, cosmetics, heart/relationship changes, `heart_level_changes`, `romantic_choice_warning` | personal; never granted to a player who did not watch |
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

## Cutscenes: the safe rule

**A cutscene is a private viewing. The mod does nothing in a game while its cutscene runs, and nobody is held for it.**

| Question | Answer |
| --- | --- |
| Do others stop? | No. The clock package keeps the world time running while at least one other player's clock runs (a player in a cutscene has a stopped clock, as in the game). |
| Do others see anything of it? | They see the player's figure in the room as usual. The scene's throw-away actors are local; the real villagers are untouched in every other game. |
| Can a scene soft-lock anybody else? | Nothing waits for it. The one coupling is the end of the day (all asleep), and the clock package already ends the day 60 seconds after 2 am for a player stuck in a scene. |
| What changes in other games, and when? | Only the lasting effects of the *world* scenes, once the scene is over (the end, or the skip): objects removed, an area cleared, a story quest started or advanced, a spell. These are the same effects the game applies at the end of every scene; the viewer's game already applied them, the others get them from the mirror. |
| What happens to the host's save? | The host applies the viewer's world effects to its own game, so they are saved with it. |
| What if the viewer's game dies in the scene? | Nothing was claimed (the pass is paused during the scene); the others never saw a half-done effect. The viewer replays it. |
| Same scene triggered in two games at once? | Both play it; the effects are idempotent (see above). |
| Heart events and romance scenes | Private from start to end. They are not claimed, not mirrored, and the villagers they use are throw-away actors. Nothing in them reaches a villager of another game. |
| A world scene a player never watched | They get its lasting effects but not the scene (the same rule `docs/SYNC-PROGRESS.md` gives a new guest). Their personal gains from it (items, heart changes) are not granted; spell and mana are. |
| Late join while somebody is in a scene | The snapshot is only data and goes out at once, also while the host is in a scene. |

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

All sizes are bounded (names 96 characters, schedule names 160, lists 20 or 4096 in a snapshot, counters 0-1000). A malformed
claim or an event from the wrong sender is dropped without effect; nothing in this file can throw into the game (the tick is wrapped,
and each change the game is asked to make is wrapped on its own).

## Interaction with other areas

* **Clock** (`docs/SYNC-CLOCK.md`): the date and the time of day are the host's. This package relies on it for the plan's day and for
  festivals, and does not touch the clock.
* **Progress** (`docs/SYNC-PROGRESS.md`): a guest's `seen.scenes` is the player's whole history; world scenes mirrored here enter it
  like any scene and are stored with the player, so a returning guest keeps them. Story quests are excluded from the personal
  quest section and handled here. The romance claim registry is unchanged.
* **Farm, ranch, containers**: objects the farm package synchronises (the farm) are theirs; turn-in boxes that quests place in other
  rooms are placed by the game's own function in each game, their contents are not synchronised by this package.

## Tests

`python3 tests/test_story.py` (about a minute): the real GML over the simulated helpers and a lossy network (5-15% loss,
duplication, jitter), with a stand-in game (`tests/story_fake.py`: quests with turn-in boxes, cutscenes of every kind, world gates,
six villagers with schedules, rooms and activities, a hundred chapter quests). 25 scenarios:

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

`python3 tests/mutate_story.py` breaks the GML in 20 ways (personal quests accepted, the story lowered, a stage that does not exist,
no broadcast, no completion, boxes left, acting during a scene, no snapshot, heart events as world, the festival quest mirrored, a
villager moved in sight, a plan on the wrong day, a claim repeated, a refusal repeated, a spoofed delta, an unknown schedule, an old
mirror kept for a new host, merging before knowing it fits, activities steered in sight, guests that cannot tell the host they are
ahead) and fails if any test still passes. All 20 are caught.

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
   rooms). Check `swaps` / `steers` in `mistrimulti.story` and that nobody ever pops in or out in front of a player. Look at the
   guest's spouse/fiance(e): it follows the host's schedule (does it behave? see limitations).
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

## Known limitations

* **Rewards of a story quest go to the player who hands it in.** A mirrored quest gives the others nothing (items, recipes, cosmetics,
  renown), and a mirrored world scene gives them its spell and mana but not its items. The rewards table of a quest is in the game's
  data; sharing them is a product decision, not a protocol one.
* **Edits made by a scene's own script** (`__erase_node`, `nuke_tut`, `handle_farm_chores`, house repairs) are local to the viewer's copy
  of the room they happen in. Only `object_removals`, `nuke` and the plaza upgrade are replayed for the others; other rooms'
  objects are not synchronised by any package.
* **Facts that data files write** and the code never mentions are not classified; only the dragon-story facts and the facts world
  gates read are shared. A story that depends on another fact needs it added to `mistrimulti_story_fixed_facts()` (or a gate that reads it).
* **Villagers: seats, paths and animation variants differ** between games; positions agree at the level of room and activity. The
  host's own simulation is the reference, which means a villager is exactly where the host's player would see it only when the host's
  player is in the room; elsewhere it is the host's *simulated* position.
* **A guest's own spouse/roommate** follows the host's plan, not the guest's roommate schedule (unverified in the game, see assumption 7).
* **A guest's conversation cannot change the world's villagers**: a schedule swap it causes is overwritten by the host's plan. A swap
  that is the world's (a story step) happens through the mirrored story state on the host's next day.
* **Two players opening one secret chest** within a second can both be paid; the chest contents are not host-arbitrated here.
* **After a host crash and an older autosave**, connected guests re-assert the story they made after it. If that is not wanted (a
  deliberate rollback) the guests have to rejoin so that they load the host's world again.
* **No notification** tells a player that the story moved because of somebody else.
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
