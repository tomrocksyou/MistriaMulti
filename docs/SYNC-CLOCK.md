# Clock, weather and all-player sleep

`mod/mistrimulti/gml/MistriMultiClock.gml` keeps every player's time of day, date and weather on the host's
world, and ends the day only when every player is asleep. It is built on the event layer
(`docs/EVENT-LAYER.md`) and uses MMAPI hooks only. No game file is edited.

Nothing here has run in the real game yet. The tests run the GML against a stubbed engine (see [Tests](#tests)).
[What to check in the game](#what-to-check-in-the-game) lists every assumption about the game, and the
[in-game checklist](#in-game-checklist) lists the steps to try.

## Decisions

| Question | Decision |
| --- | --- |
| Who owns time? | The host. It keeps the **world time** W (time of day and day number). Guests never change it; they report. |
| Does a menu stop time for everyone? | **No.** World time runs while at least one player's own clock is running. A player in a menu, a cutscene or asleep has a stopped clock, as in the game. W stops only when every player's clock is stopped, which is the single-player behaviour when the host plays alone. |
| How does a clock follow W? | Every game, the host's included, steers its own clock through the `clock.time_advance` filter: up to twice as fast when it is behind, slower down to stopped when it is ahead. A clock never goes backwards. More than 30 game minutes behind, it jumps (`CLOCK.jump`, which moves NPCs and the pet as the game does). |
| A clock moved forward by the game (cutscene time jump, oversleeping) | W follows only when **every** awake player is past that time (a cutscene everyone watched). One player's jump stays personal: their clock waits until W catches up. |
| Weather | The host's forecast (`WEATHER.forecast`, the whole season) is sent at join, at every new day and whenever it changes. A guest takes it and sets today's weather from it, unless a rain spell is active locally. |
| What ends the day? | A vote: every in-session player must be asleep. Asleep means in bed (cancellable) or in the end-of-day sequence (bed after the vote, the 2 am pass-out, a day-ending cutscene). |
| Who runs the day transition? | Every game runs its own, once, using the game's own code: sleep scene, `end_day()`, end-of-day menu with its own summary, `new_day()`, wake-up. The mod only delays `EodMenu.end_sequence` (which runs `new_day()` and the save) until the host has ended the day. |
| Who saves? | The host, once, in its own `end_sequence`. Guests' saves are already vetoed by `mistrimulti_save_guard` (`game.save_guard`). |
| Players stuck in a menu or cutscene at 2 am | Once W reaches 2 am and at least one player is asleep, the host ends the day 60 seconds later anyway. The stuck player ends their own day (once) as soon as they are free. |

## World time

The host keeps W in its clock state (`r.clock.w`, game seconds since midnight, 6 am = 21600, 2 am = 93600):

- **Alone** (no guest has entered the world), W simply follows the host's clock and the mod changes nothing.
- **With guests**, W advances by one frame of game time on each host frame while *any* player's clock runs:
  the host's own (not paused, not stopped, awake) or a guest's, from its `clock_report`. W stops at 2 am.
- The host sends a sample `clock {d, t, r, m}` (day, W, rate in game seconds per real second, the host's minutes
  per day) when W starts or stops, every 2 s while it runs, on a new day and to every player who joins.
- A guest extrapolates `t + r * elapsed`. A sample that arrives late (queued behind a loss) never moves the
  estimate back within a day. A guest runs at the host's day speed even if its own setting differs.

Each game's filter (`mistrimulti_clock_time_advance`) returns
`natural * (1 + clamp(error / 120 s, -1, 1))`: with `error = W - local`, a clock behind by 2 game minutes runs at
double speed, one ahead by 2 game minutes stops. When the game itself stops the clock (pause, menu, cutscene,
end of day) the natural value is 0 and the mod leaves it at 0. When the player is free again and more than
30 game minutes behind, the clock jumps; less than that, it catches up at up to double speed (a 10 s menu at the
default 15-minute day costs about 16 game minutes, caught up in about 10 s). Accuracy is the sample delay times
the clock rate: about 25 game seconds at the default speed with 250 ms of delay; the HUD shows 10-minute steps.

After its own new day a guest that wakes before the host waits at 6 am until the host's new day starts W.

## The sleep vote

### States of one player (per day)

```text
             bed: "Sleep" (others connected)               all asleep (host's vote)
  awake ───────────────────────────────────▶ bed ─────────────────────────────▶ eod
    ▲  ◀────── "Get up" / Back ───────────────┘                                   │
    │                                                                              │
    ├── pass out at 2 am, a day-ending cutscene, the end-of-day menu opening ─────▶ eod
    └── the host ended this day while this player was away / busy: when free ─────▶ eod (forced end_day)

  eod: end_day() → end-of-day menu (own summary, Next Day) → calendar → end_sequence
       held until the host has ended the day → new_day() (+ host save) → wake up → awake (next day)
```

- **bed**: the mod replaces the bed's "Go to sleep?" popup (`object.interact` on bed nodes, only while other
  players are connected and only at home, like the game). After "Sleep" it records the bed as the game does
  (`ARI.last_bed_used`, the "slept last minute" fact) and shows a "Sleeping / Get up" popup. The popup pauses
  this game (its clock stops, as when asleep). "Get up" or Back closes it and cancels.
- **eod**: committed. Set by `player.pass_out`, by the end-of-day menu opening (`ui.menu_opened`, `Menu.Eod`), or
  when the mod starts the sleep scene. Cannot be cancelled: the game has already run `end_day()` (the player's clock set to 2 am; the shipping
  bins are sold a moment later by the end-of-day menu, by the host only in effect, see docs/SYNC-WALLET.md).
- States carry the day number (`total_days()`), so a state is never counted for another day.

### The host's decision

Each bridge tick the host counts `need` = the host plus every *member* and `ready` = those in `bed` or `eod` for
the host's current day. A member is a guest whose game session (event stream) is connected and has been in the
world (frame `active`) at least once in this session. Someone still in the character creator does not hold the
others back, while someone walking through a door (briefly not active) does.

When `ready == need`, or 60 s after W reached 2 am with at least one player asleep, the host records
`a` = this day as **ended** and broadcasts the vote `{d: host day, n: ready, m: need, a: last ended day}` (also on
every change, as the result of each guest request, and to joiners). A game has ended day `x` once
`x <= max(a, d - 1)`. Then:

| This game is | It does |
| --- | --- |
| in bed | closes the waiting popup and starts the game's own `sleep` scene (with the spouse blackboard entries the bed sets) → `end_day()` → end-of-day menu; its `end_sequence` runs immediately |
| holding in `end_sequence` | runs the game's `end_sequence` (new day, the host saves, wake up) |
| awake and one day behind | when free (no pause, menu, cutscene, end of day or wake-up): `end_day()` with a notification, then as above |
| two or more days behind, or ahead of the host | nothing automatic; a warning asks the player to rejoin (reload the host's world) |

Exactly one transition per player and day: the held `end_sequence` is released once (the stored original is
cleared before it runs), the forced `end_day()` happens at most once per day and never when this game is
already in bed or ending the day, and a state for a past day is ignored by the host. `new_day()` therefore runs
once per game per day, and only the host's save is allowed.

The counter `n/m sleeping` is drawn under the HUD clock (top right) on every game while at least one player is
asleep; a player held in `end_sequence` sees "Waiting for the other players to sleep" on the black screen.

### Cases

| Case | Behaviour |
| --- | --- |
| Cancel | "Get up" (or Back) in the waiting popup: state back to `awake`, the counter drops. Not possible after `eod`. |
| Disconnect while others sleep | The host stops counting the player when its helper expires it (10 s). If everyone else is asleep the day ends. Back with the same session, the player is one day behind and ends that day when free. |
| A guest's host disappears while the guest is held | After 30 s alone the guest's held day ends locally (no save); the warning then asks to rejoin. |
| Late join during a vote | The newcomer counts as soon as it has entered the world, so the day waits for them. It arrives at the saved time (6 am) and jumps to W. |
| Passing out at 2 am | Counts as asleep (`eod`). Players in bed are already counted. |
| Early and late sleepers | A player can go to bed at any time; the others keep playing and W runs for them. |
| Summary screens | Each game shows its own end-of-day menu with its own gold, renown and calendar, at its own pace. |
| Stuck in a menu or cutscene | Not ready, so the day waits, until W is at 2 am: then 60 s later the host ends the day. The stuck player ends their day when free. |
| Host restarts mid-vote | The new host session starts from its save (that day, 6 am). Guests re-send their state to the new session (`on_peer`, and lost requests), so beds and held ends of day still count. Guest clocks never go back: they wait for W. A guest that already finished the day is ahead and is asked to rejoin. |
| Lost, duplicated, reordered events | The event layer delivers in order exactly once. States and votes are whole snapshots (idempotent); samples are monotonic. |

## Events

| Kind | Direction | Data | Checked |
| --- | --- | --- | --- |
| `clock` | host → all, and to joiners | `{d, t, r, m}` | from the host; `d` integer; `0 <= t <= 93600`; `r`, `m` bounded numbers |
| `clock_report` | guest → host | `{run, a, d, t}` own clock running, awake, day, time | Booleans, integer day, `t` range; stored per guest session |
| `weather` | host → all, and to joiners | `{d, f}` day and forecast | 1–64 entries, each a `Weather` value |
| `sleep` (request) | guest → host | `{d, s}` day and `"awake"`, `"bed"` or `"eod"` | stored per guest session; result = the vote |
| `sleep_vote` | host → all, and to joiners | `{d, n, m, a}` | integers, `n <= m <= 8`, `a <= d` |

On a guest, `sleep` re-sends its state whenever it changes, when the host session changes and when a request is
reported lost. When a guest's `sleep` state reaches the host's day after its own new day, the host sets
`snapshot_pending` so the farm terrain is sent again (MistriMultiTerrain).

## Hooks

`clock.time_advance` (filter), `game.clock_tick` (the per-frame tick, every third frame), `game.new_day`,
`player.pass_out`, `ui.menu_opened` (the end-of-day menu), `object.interact` (beds, claim-scoped), `ui.draw_gui`
(the counter), `local.missing` (popup text). They are registered by `mistrimulti_clock_register_hooks()`
from `mistrimulti_register()` and listed in `manifest.toml`.

## What to check in the game

These come from the game's scripts and the MMAPI documentation and could not be run here:

1. `CLOCK.update()` runs every frame in the world, also while paused, during the end-of-day menu and room
   transitions (so `clock.time_advance` and `game.clock_tick` fire every frame).
2. The natural advance passed to `clock.time_advance` is exactly `GAME_SECONDS_PER_FRAME` when the clock runs and
   0 when paused or stopped, and the filter's return value is what reaches `side_buffer`.
3. One game day runs `MINUTES_PER_DAY` real minutes at 60 frames per second (the rate sent to guests is
   `86400 / (MINUTES_PER_DAY * 60)`).
4. `CLOCK.jump(t)` is safe to call from the clock-tick hook while the player is free (it is how cutscenes move time).
5. The bed is a furniture grid node whose prototype has `bed_kind`, reached through `interact(node)`, so the
   `object.interact` override sees it; skipping the game's handler and setting `ARI.used_object_today`,
   `ARI.last_bed_used`, `T2R "slept_last_minute"`, the spouse blackboard entries and `MIST.request_scene("sleep")`
   later reproduces the game's sleep.
6. `popup_creator`, `create_button`, `spawn`, `close` and `close_callback` (called on any close, including Back)
   behave as in `PopupMenu.gml`; spawning the waiting popup one tick after the confirmation popup closed is fine;
   an open popup pauses the game.
7. `ui.menu_opened` fires for `Menu.Eod` before `init()`, with `ctx.menu.end_sequence` already defined, and the
   menu calls `self.end_sequence()` through the struct member, so the replacement is what runs; calling the stored
   original later runs it on the menu (a bound method).
8. Holding `end_sequence` on the black screen is harmless (the calendar has faded out, the fader stays out) and
   `ui.draw_gui` text is visible over it.
9. Calling `end_day()` from the clock-tick hook for an awake, free player gives a normal end of day (the game
   itself calls it from the pass-out and from cutscenes); `ARI.end_of_day_status` is set to `Normal` first, as
   `Mist.gml` does.
10. `player.pass_out` fires on the 2 am collapse; `ARI.end_of_day_sequence`, `ARI.end_of_day_status`,
    `game_paused()`, `MIST.is_running()`, `ANCHOR.get_menu`, `ANCHOR.popup_is_open` mean what the scripts suggest.
11. Assigning `WEATHER.forecast` and calling `WEATHER.set_weather` on a guest is enough to change its weather
    (rain also waters the farm, as in the game).
12. `json_parse` gives Booleans for `true`/`false` (the terrain code relies on the same).
13. The drawing calls are those of the status badge (`draw_set_color`, `draw_text_transformed`, `string_width`).
    The counter sits at y = 62 GUI pixels, below the HUD's clock and date boxes (y = 6, 23, 41 in `InfoHudMenu`).

## Known limitations

- **Shipping bins**: every game runs the end-of-day sale (`sell_shipping_bin_items`) on its own copy of the bins. Bins are
  synced and sold once by the **host**; a guest's payment is dropped by the shared wallet (docs/SYNC-WALLET.md,
  docs/SYNC-CONTAINERS.md).
- **World simulation**: each game still runs its own `new_day()` (crops, NPCs, forageables). The grid day is
  seeded from the save and the day, so it usually matches, and terrain is re-sent, but other world state that
  differs is not reconciled here.
- **Festivals and long cutscenes** that move or stop time are personal: a player's jumped clock waits for W.
  If everyone takes part, W follows when all are past the jump.
- **Oversleeping** (passing out) jumps that player's clock in the morning; it then waits for W.
- Mixed mod versions: a host without this file never answers the vote and a guest's end of day would wait.
  Players must use the same release.
- The 2 am timeout (60 s) and the jump threshold (30 game minutes) are constants in the file.

## In-game checklist

Use a disposable multiplayer world, the default day speed, one host and one or two guests.

1. Join a guest while the host is at 9 am: the guest's clock jumps from 6 am to about 9 am within a few seconds,
   then shows the same time as the host's (within one 10-minute step) for several minutes.
2. Open the inventory on the guest for 10 s: its clock stops; after closing it catches up within about 10 s
   (faster minutes, no jump). Repeat on the host: the guest's clock keeps running meanwhile.
3. Open a menu on every game: all clocks stop. Close them: all resume together.
4. Rain: on a day the host's forecast says rain, the guest sees rain too; the guest's calendar/forecast
   (weathervane, end-of-day calendar) matches the host's.
5. Guest uses its bed: the popup says the day ends when everyone is asleep. "Sleep" → "Sleeping / Get up"
   popup; the host's HUD shows `1/2 sleeping` under the clock. Press "Get up": the counter disappears.
6. Host goes to bed, then the guest: both play the sleep scene, see their own summary (own gold and renown) and
   press Next Day at their own pace; neither waits on a black screen, because everyone was already asleep. Both
   wake on the next day, same date, same weather. The host has one new autosave; the guest wrote no save.
7. Held end of day: the host opens a menu at 1:55 am and keeps it open; the guest passes out at 2 am, presses
   Next Day and then sees "Waiting for the other players to sleep" on the black screen. The host closes the menu
   within the minute: it passes out too, and both continue to the next day once.
8. Stay awake past 2 am on both: both pass out, the summary shows, the day advances once.
9. One player in bed, the other's game closed (helper stopped): after about 10 s the sleeper's day ends.
10. One player in bed, the other with a menu open at 2 am: about 60 s after 2 am the sleeper's day ends; closing
    the menu then ends the other player's day once (notification), with its own summary.
11. Host quits to the title and reloads while a guest is in bed: the guest stays in bed, its clock does not run
    backwards (it waits), and after the host sleeps both reach the next day once.
12. Read `mod_data/mistrimulti/logs/mistrimulti.log` on every game: no "Clock sync failed", "End-of-day wrap
    failed" or "Sleep counter failed".

## Tests

`python3 tests/test_event_features.py` runs the real `MistriMultiClock.gml` with the event layer for 3–4 games over
the simulated network with 3–5 % loss and duplication and 30–40 ms jitter. The engine is stubbed: a frame-by-frame
`Clock.update` with the filter, pause, `time_stopped`, the 2 am faint, the bed popup, the sleep scene, `end_day`,
the end-of-day menu with a Next Day delay, `new_day` and the host save. Scenarios:

- `test_clock_sync`: a late guest jumps; clocks stay within 150 game seconds (at a 5-minute day, three times the
  default speed) under loss; a guest with another day speed follows; menus on a guest or the host; all paused
  stops W; an ahead clock waits and never goes back; a jump every player made moves W; weather and forecast.
- `test_sleep_vote`: bed, counter, cancel, all asleep, one sleep scene / end of day / `new_day` per player, the
  host saves once; the next night with pass-outs at 2 am plus a bed sleeper.
- `test_sleep_disconnect_and_late_join`: a disconnected player stops counting and catches up once (not while in a
  menu); a late joiner jumps and must sleep too.
- `test_sleep_timeout_and_host_restart`: a player stuck in a menu at 2 am; the 60 s timeout; the host restarts
  mid-vote and the guests' state is kept, guest clocks never go back.
- `test_clock_untrusted_input`: malformed or forged clock, vote, weather, report and sleep data is ignored.

Every scenario checks that no clock ever went backwards within a day, `new_day` ran exactly once per game and
day in order, the host saved once per day, and no handler failed.
