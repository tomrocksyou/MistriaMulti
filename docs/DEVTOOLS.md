# Developer tools (for testing only)

Commands for the person who hosts a world and wants to test multiplayer without playing through the story first. They are
**not part of normal play**, they are host only, and they change the saved world. Code:
`mod/mistrimulti/gml/MistriMultiDevTools.gml`. Tests: `tests/test_devtools.py`, `tests/mutate_devtools.py`.

## Unlock the mines

At the start of a new game the mines are closed: opening them is a story step (the letters and scenes
`unlocking_the_mines_pt_1` and `unlocking_the_mines_pt_2` in the game's own story test, which needs about five days and
renown level 10). This command does that step for you, for **everybody in the world**, at once.

| | |
| --- | --- |
| Hotkey | **Ctrl+F6**, in a world, as the host. (F6 alone does nothing. The other keys in use are F7, Shift+F7, F8 and F9; the MMAPI debug agent, if enabled, takes F8 to F10.) |
| Debug function | `mistrimulti.unlock_mines`, registered only when the MMAPI debug agent is enabled (`debug_enabled` in `mmapi.json`). Returns `{ ok, changed, open, skipped, text }`. |
| Who | The host only. A guest gets "Only the host can use this developer command." and nothing happens: the check is the host's own mode and player id 0, and the command has no network entry point, so a guest cannot ask the host to run it. |
| When | In a world, not during a cutscene or the end of the day, and once the story sync holds the world (a second or two after loading). Otherwise it says why it did not run. |
| What it says | A notification (and a line in the MMAPI log): "Mines unlocked (N story steps). The other players get it within seconds.", "The mines are already unlocked.", or the reason it refused or failed. |
| Safe to press twice | Yes. Whatever is already done is skipped, and a second press changes nothing. |

### What it does

The game has one named requirement for this, the alias `Requirement.OpenedMines`. Its own automated test fulfills it with
the game's own `fulfill_requirement(Requirement.OpenedMines)` before the stone refinery quest. The command does the same,
step by step instead of in one call, so that it can leave out anything that would pay out:

1. It walks the alias (nested aliases included) and collects the cutscenes it needs seen, the world facts it needs, and the
   quests it needs completed.
2. Each cutscene not seen yet goes through `fulfill_requirement(SeenCutscene, ...)`: it is recorded as seen **and its
   object removals are applied**, which is how a blocker in the world disappears. Each fact not set yet goes through
   `fulfill_requirement(WorldFactIs, ...)`. Each quest not finished is finished with the story sync's own
   `mistrimulti_story_apply_quest` (no rewards, no renown).
3. Anything else in the alias (items, gold, "or" groups, dates ...) is **not touched**. It is listed in the log
   ("devtools: not handled: ...") and counted in `skipped`. The command never hands out items or gold.
4. It asks the game whether `OpenedMines` now passes and tells you. If something unhandled still keeps the mines shut, it says
   "The mines still report as locked" instead of claiming success.
5. It refreshes the current room with the game's own `setup_room()` (what the game's debug console does after a world
   change), unless you are inside the mines.

### How everybody gets it

Nothing new travels on the network. The host's game now holds the scenes, fact and quest, and the story sync
(`docs/SYNC-STORY.md`) notices within a second, merges them into the world story and tells every guest. Each guest's game
applies them exactly as it applies any other story step another player took: the scene is added to its history and its
object removals are applied, the fact is written, the quest is finished. For this the story sync reads the
`OpenedMines` alias the way it reads the other world gates (one guarded line in `__mistrimulti_story_data`), so the scenes and
facts it needs count as the world's and are shared. A guest that is away, or joins later, gets it from the host's snapshot.

**Rewards.** Nobody is paid twice, and the host's step is free:

* The host is paid nothing (it is a test command).
* Every guest that is in the game gets what the story sync gives for any step another player took, once: the scene's own
  gift items and free baths (once, when the scene enters their history), and the gold and items of the quest's tasks, through
  the per-player ledger of `docs/SYNC-STORY.md`. A guest that joins afterwards is not owed the past, as for every story step.
* Pressing again, or restarting, pays nothing again.

### What it does not do

* **Dungeon floor lifts (the elevator).** Not included. Which floors the elevator offers is the per-player number
  `MAXIMUM_REACHED_DUNGEON_LEVEL`, not a story requirement or fact; it lives in each player's own record
  (`docs/SYNC-PROGRESS.md`) and would need its own, per-player command. It is not one more line of this mechanism.
* The real content of `OpenedMines` lives in the game's data files, not in its scripts, so what exactly it contains could
  not be read here (see the assumptions below). The command works from whatever the alias holds at run time.

### Assumptions that could not be checked without the game

* `Requirement.OpenedMines` exists and is an alias requirement (the game's own test in `TestSuite.gml` calls
  `fulfill_requirement(Requirement.OpenedMines)`), and its content is scenes, facts and quests. If it holds other things, they
  are listed as not handled and the command says the mines are still locked.
* Setting the scenes, fact and quest this way opens the mines in the game as it does in the game's own test. The physical
  blocker is data-driven (a grid object removed by a scene's `object_removals`, or a world mod gated on the same
  requirement); `setup_room` re-evaluates both.
* Guests' rooms pick up an object removal when their grid changes; a guest standing in the room may need to leave and
  come back to see the blocker gone.
* `create_notification` shows on the host in a world; on the title screen only the log line appears.

### Testing it

```sh
python3 tests/test_devtools.py       # the real GML on the story sync, stand-in game, lossy network, three to four players
python3 tests/mutate_devtools.py     # breaks the code on purpose in 19 places; every one must be caught
```

The tests cover: the host unlocks and every guest follows; nothing is paid to the host and each guest is paid once; a second
press changes nothing; a guest (or a guest runtime that claims to be the host) cannot run it; refusals before the sync is
ready, in a cutscene, at the end of the day and with multiplayer off; unknown parts of the alias are reported and never
handed out; late joiners, a guest restarting from an old save, a lossy network; an engine failure is contained; the debug
function and the hotkey are registered and not on a key that is already used.
