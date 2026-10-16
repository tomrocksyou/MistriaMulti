# Guest saving, leaving and returning

What happens to a guest's game when the guest saves, quits, loses the host or comes back. Code:
`mod/mistrimulti/gml/MistriMultiGuestSave.gml`, with small hooks in `MistriMultiBoot.gml` (the save guard, the tick, the
registrations). No new network event: it uses the player records of `docs/PLAYER-DATA.md` and `docs/SYNC-PROGRESS.md`, the save
spaces of `docs/SAVE-ISOLATION.md` and the event layer (`docs/EVENT-LAYER.md`).

## Decisions

| Question | Decision |
| --- | --- |
| Does a guest's game save anything? | **No.** Every save in a joined game is vetoed (`game.save_guard`), whether the game or the mod runtime is healthy or not. |
| Is the guest's world kept offline (a "guest copy")? | **No.** The guest's character lives in the host's per-player records; the world is the host's. Nothing is written into any save folder. |
| What does the player see on a save attempt? | ONE line: "Guests do not save: the host keeps your progress." It replaces the game's own "Save complete" text (`local.get` filter on `misc_local/save_complete`, guests only); the mod adds no second notice. The attempt also **sends the character to the host at once**. |
| Is the guest's character kept locally? | Yes, as a **character export** file (a backup of what the host acknowledged, see below). It is not a save and the game cannot load it. |
| What happens when the host is gone? | The guest sees a message and returns to the title screen (same path as the settings menu's "Return to main menu"). |
| Can a multiplayer game write into the solo save folder? | **Never**, for either role: a save whose path is inside the solo `saves` folder is vetoed (a belt-and-braces check on top of the separate save folder). |

### Why no "guest copy" of the world

The save hook can only veto (`game.save_guard` allows or blocks, it cannot change the path). A redirect would mean the mod
calling `save_game` itself with another path from inside the guard. That would write the host's world, as the guest's game holds
it (only partly synchronised, with the guest's own character mixed in), into `multiplayer/saves`. That folder is where the
downloaded host world lives: `mistrimulti_savespace_newest_world` picks the newest file there, and the launcher serves the newest
file to joiners when this player hosts. A guest copy would therefore be loaded by mistake as "the host's world" and
could be handed out as a world. Blocking costs the guest nothing it can use: the character is on the host, the world is the
host's.

## What the game saves, and when (from the game's scripts)

| Path | Saves? |
| --- | --- |
| Journal save (`Interact.gml`, "Save your progress?") | yes, `save_game(exact_save_path(..., manual))` |
| End of day (`EodMenu.end_sequence`) | yes, `save_game(autosave path)` |
| Settings > "Return to main menu" | **no**: fade, then `Game.exit_to_menu()` |
| Settings > "Exit to desktop" | **no**: `game_end()` |
| Alt-F4, a crash, power loss | no |

The game never saves on quit, so "the guest quits" has nothing to protect locally. What matters is that the **last checkpoint
reached the host**. Both save paths call `save_game`, which is where the guard sits. The game's end-of-day code shows its own
"saved" notice after the vetoed save (`create_save_notification` is unconditional). The mod cannot stop it, but it rewords it:
the `local.get` filter `mistrimulti_guestsave_local_get` answers the lookup of `misc_local/save_complete` on a guest with the
guest line, so the player reads one true sentence. **Could not be suppressed:** the game's save sound
(`SoundEffects/UI/SuccessfulSave`), the save icon next to the text, the "Saving..." text of the load sequence and the short
fade of the HUD pins: they run in `create_save_notification` / `LoadSequence`, which have no hook. If the game's notice never
appears (the filter did not run), `mistrimulti_guestsave_notice_tick` shows the same line itself after 1 s (`create_notification`),
at most once every 5 s.

## Saving

`mistrimulti_save_guard` (Boot) asks `mistrimulti_guestsave_blocks(ctx)` first:

1. **Guest** (`enabled && mode == "join"`, or the multiplayer save space is active and `control.json` says `join`, which also
   covers a runtime that failed to start): veto, arm the 1 s fallback line (at most once every 5 s) and flush the character (below).
2. **Anybody in multiplayer** (runtime enabled or multiplayer space active) with a `save_path` inside the solo `saves` folder
   (`<original CONFIG_DIRECTORY>/saves/`, compared case-insensitively with `/` and `\` unified): veto and log an error.
3. Otherwise the existing host behaviour (flush the guests, checkpoint, `progress_flush`) runs and the save is allowed.
   Singleplayer is never touched: outside multiplayer nothing here runs.

The guard fails closed for a guest: with no ctx (the debug console calls it that way) it still blocks.

### Flush

`mistrimulti_guestsave_flush` makes the guest checkpoint now instead of at the next 5 s tick: it zeroes both checkpoint timers
and calls the core and progress checkpoints. They send one record at a time, so if the previous upload is not acknowledged yet
the flush is repeated by the tick as soon as it is (`flush_pending`). Nothing happens while the character is not loaded
(`player_ready`) or a cutscene runs (the existing rule of the checkpoint).

## Leaving cleanly

The game gives the mod no hook on "Return to main menu" or "Exit to desktop", and nothing after them runs for a guest that is
being torn down. So:

- **Final flush: opening the Settings tab.** In the world, Settings is a tab of the journal and is spawned with
  `ANCHOR.spawn_menu(Menu.Settings)`, which fires `ui.menu_opened` with `kind == Menu.Settings`. A joined game flushes then.
  Every quit option is reached from that screen, and the character cannot change while it is open, so the host holds the final
  state a moment later (about a round trip plus the host's once-a-second record write).
- **Goodbye frame (`game.title_entered`).** When a world session ends (menu quit), the game writes one last bridge frame
  `{v: 2, ..., active: false, world: ""}`. Without it the helper would keep resending the last frame of a game that is no longer
  in a world: the host would keep a frozen ghost and refuse the same player from another slot as "already connected"; guests
  would never learn that the host had left. The host reacts to a guest's goodbye by forgetting that slot's record session, so
  the player can come back through any slot at once.
- **Returning.** The guest asks the host for its records as usual (`docs/PLAYER-DATA.md`), restores them and does not see the
  character creator again (entering through Load Game; through New Game the guest is first asked "Keep mine" or "New character",
  see "A character per world" there). If the old slot is still counted (the game vanished without a goodbye: alt-F4, network drop, crash;
  the helper expires a silent peer after 10 s) the host refuses with "This player identity is already connected". That
  refusal used to be final for the session; the guest now asks again every 3 s, at most 10 times, so it is let in as soon as
  the old slot expires.
- **Exit to desktop / alt-F4 / crash / network drop.** Settings flush, if the player opened Settings first; otherwise nothing
  runs. The host keeps the last acknowledged checkpoint (see the loss window below).

## The host is gone

`mistrimulti_guestsave_watch_host` runs four times a second in a joined game, once the guest has seen the host in this session.
(A guest that starts before the host simply waits; it is never sent away for a host it has not met.)

| State | How it is seen | Grace | What happens |
| --- | --- | --- | --- |
| ok | host peer present, same epoch and world as when first seen | | nothing |
| lost | no host frames: the host's game or helper died, the network is down, or this guest's own helper stopped. The helper expires a silent peer after 10 s | 20 s (so about 30 s after the host's last frame); a notice "Connection to the host lost. Waiting..." after 4 s | message, then title |
| closed | the host's goodbye frame: it went back to its title screen | 3 s | message, then title |
| restarted | the host's world epoch or world key changed: it reloaded or started another world | 2 s | message, then title |

A return of the host inside its grace period (a short outage) cancels the state; nothing happens. A guest cannot tell "the host
died" from "my own connection died"; both show as `lost`.

**The message** is the game's popup (`popup_creator`): "Disconnected from the host", with a body that says the character was
saved on the host's computer a few seconds ago, that nothing was saved here, and to join again from MistriaMulti. Its single
button is the game's own "Return to main menu"; it fades out and calls `Game.exit_to_menu()` exactly like the settings menu. It
appears once. If the popup cannot be built the guest still goes to the title.

**No corrupted save is possible on the guest**: the guest wrote nothing (every save is vetoed) except bridge frames, the export file
and the settings (which the save space already redirects to the multiplayer folder). On the host, records are written as
`.tmp` then rename, with a `.bak`, and a damaged record is refused and recovered, never replaced (`docs/SYNC-PROGRESS.md`).

### What is lost

| Event | Loss window |
| --- | --- |
| Guest game closes (any way) after Settings was opened | nothing: the settings flush has been acknowledged |
| Guest crashes, alt-F4, network drop, exit to desktop without Settings | the guest's changes since the last **acknowledged** checkpoint: normally 5 s, up to 10 s (a checkpoint is every 5 s and waits for the previous upload's acknowledgement; the host writes a player's progress at most once a second) |
| Host crashes or closes | The guests' records on the host are the latest checkpoint (5-10 s old at most). The **host's own world** is only what its last save wrote (autosave at the end of a day, or a manual journal save), exactly as in singleplayer. If the host later loads that save, each guest's records are rolled back to the **commit that was written with that save** (`docs/SYNC-PROGRESS.md`, "Host save commit"), so a guest's progress since the host's last save is not kept: the newer records are saved as `commits/discarded.json`, not deleted. Progress is kept on the host only; the guest has no copy of the world |

Practical advice for hosts: sleep (autosave) before long sessions end; for guests: open the settings menu before quitting.

## Character export (backup, and a way to host your own copy)

A guest does not keep the world, but keeps its **character** as the host acknowledged it:
`mod_data/mistrimulti/exports/<world key>__<identity>.json`, written by the guest with `.tmp` then rename.

```json
{ "v": 1, "kind": "character_export", "uid": "...", "world": "...",
  "core": { "v": 1, "revision": 12, "data": { ... } },
  "progress": { "v": 1, "revision": 9, "data": { "v": 1, "uid": "...", "world": "...", "sections": { ... } } } }
```

`core` and `progress` are exactly the two envelopes the host stores in `players/<identity>.json` and
`players/<identity>.progress.json`, built from what the host acknowledged (never a state still in flight). It is written
at the first full acknowledgement, at most once a minute afterwards, and at once after the Settings tab opened. It holds
account identifiers and character data and does not belong in a repository. A section the host refused (locked) is missing.

**Becoming the host of your own copy.** The export is the input of `mistrimulti_guestsave_import(file name)`, available as the
MMAPI debug function `mistrimulti.import_character` (needs `debug_enabled` in the MMAPI config). On a host with the same
identity, in a loaded hosted world, it validates the export (identity, file shape, then the same validators as a record, with the
world key replaced by this world's), restores the character and progress like a record restore and checkpoints. The player
then saves the world normally to keep it. It only replaces the host's own character, does not move the world and refuses
folders in the file name. It is experimental and has not been run in the game. Moving a character between two worlds as a *guest*
is the same file copied into `players/` of the other world with `data.world` rewritten, and is not automated.

## Constants

| | |
| --- | --- |
| lost / closed / restarted grace | 20 s / 3 s / 2 s |
| "connection lost" notice | after 4 s of `lost` |
| Save notice gap | 5 s |
| "already connected" retries | every 3 s, 10 times |
| Export gap / size limit | 60 s / 512 KB |

## Assumptions about the game that could not be verified here

1. `game.save_guard` vetoes both the journal save and the end-of-day autosave, and a vetoed end-of-day sequence continues
   normally (the game then shows its own "saved" notice, `create_save_notification`, unconditionally; for a guest its text is the guest line).
2. `ui.menu_opened` fires with `kind == Menu.Settings` when the journal's Settings tab is opened (`JournalMenu.set_active_sub_menu`
   calls `ANCHOR.spawn_menu(menu)`; the hook's seam is in `spawn_menu`). If the tab were not spawned with that id, the final flush
   would not fire and the 5 s checkpoint would be the only protection.
3. `game.title_entered` fires on "Return to main menu" in a joined game after the world is gone, and the bridge folder is still
   writable. It cannot fire on alt-F4 or "Exit to desktop".
4. The helper publishes a changed `tx.frame` of a game that is at its title screen (it republishes the file it reads), and the
   goodbye frame (`v: 2`, no `ev` member) is accepted by `mistrimulti_read_peers` and `mistrimulti_events_receive`, as the plain frames
   that games send outside a world already are.
5. `Game.exit_to_menu()` after `SCREEN_FADER.fade_out(FADE_SPEED_TRANSITION, fn)` is what "Return to main menu" does for a guest
   in the middle of anything (cutscene, dungeon, a menu); the popup is spawned on top of whatever is open. A cutscene runs on
   until the player taps the button.
6. `misc_local/return_to_main_menu` is a valid localization key for a popup button label (the settings menu uses it for a menu
   element); the three `mistrimulti/guest_*` keys come from the `local.missing` filter like the save-space texts.
7. `string_lower`, `string_pos`, `string_replace_all`, `directory_create` behave as in GameMaker; the original `CONFIG_DIRECTORY` has no
   trailing slash (the game formats `"{}/saves/..."`), so the solo-folder prefix is `<dir>/saves/`.
8. A helper epoch/world change of the host means the host started a different world session (host `r.epoch` only changes in
   `mistrimulti_player_reset_session`, which runs when the host's player object is replaced).
9. The helper expires a silent peer after 10 s and the guest's mask is refreshed once a second (`docs/PROTOCOL.md`).

## Known limitations

- Alt-F4, "Exit to desktop" and crashes cannot flush: up to 5-10 s of progress can be lost unless the Settings tab was opened.
- A guest cannot tell a dead host from its own network loss; both return it to the title after about 30 s. A guest on a bad
  link that recovers within the grace period is kept.
- A host that reloads its save while guests are connected now sends them to the title (their world copy is stale). This ends the
  "guest stays through a host restart" case that `docs/SYNC-CLOCK.md` simulates; the clock logic itself is unchanged.
- The game's own "saved" icon still appears after a vetoed end-of-day save.
- The guest's settings changes are written into the multiplayer folder (`docs/SAVE-ISOLATION.md`), not the solo one.
- The export is a backup and an import input; the game cannot load it as a save, and the import is a debug-console function.
- A host quitting through alt-F4 leaves no goodbye: guests see `lost` and wait out the 10 s expiry plus the 20 s grace.

## Tests

`python3 tests/test_guestsave.py` (about 35 s) runs the real `MistriMultiGuestSave.gml` with the real player-sync, player-data
storage, progress and identity files over the simulated helpers and network, with the game faked as in `tests/test_progress.py`.
It checks: the save guard (guest, host, solo path with other slashes and letter case, runtime failure, singleplayer, missing
ctx); that a save attempt and the Settings tab flush the character to the host at once (and again after an in-flight upload); that
other menus do not; quit and return without a new character; the goodbye frame; rejoining through another slot after a goodbye and
after a vanished game (retry); host crash (about 30 s), host quitting to the title, host restart, a short outage, a guest
that never saw the host; the single message and the fade-then-exit path; export content equals the host's stored records and
never an unacknowledged state; import for the same identity in a new world, with every refusal; and the real `mistrimulti_save_guard`
and registrations of `MistriMultiBoot.gml` against the manifest. `python3 tests/mutate_guestsave.py` breaks the GML in 27 ways and
checks that a test fails each time. None of this runs the real game.

## In-game checklist

Use two installs (host and guest), a host world on an autosave, and the MMAPI debug console for `mistrimulti.guestsave`
(`blocked`, `state`, `exported`) when it is enabled.

1. Startup: no error in the MistriaMulti log; MOMI accepts the manifest (new hook: `local.get`). Unverified: that the lookup
   of `misc_local/save_complete` reaches `local.get` with the key string as `ctx`, as the hook page says; the log line "The game's
   save notice was reworded for the guest." proves it, "showing the guest line instead" means the fallback ran.
2. **Save attempt.** As a guest, save at the journal. The notice reads "Guests do not save: the host keeps your progress." (once, not "Save complete" and not a second line), no file appears in `saves/` or `multiplayer/saves/`
   (check modification times), and the host's `players/<id>.json` updates within a couple of seconds.
3. **End of day.** As a guest, sleep through the host's day end: the game continues normally (the save sound and icon are expected, the text is
   the guest line); no autosave file is touched on the guest.
4. **Solo untouched.** Choose Singleplayer: saving works as always, no notice, no export.
5. **Settings flush.** As a guest, earn gold, open journal > Settings immediately, check the host's record; then "Return to main
   menu". Join again through Load Game > Multiplayer, even through another slot: the character is as it was, no creator.
    (Through New Game > Multiplayer > Join the question "Keep mine / New character" appears first.)
6. **Goodbye.** On the host, a guest that returned to its title disappears (no frozen ghost) and can rejoin at once.
7. **Alt-F4 / "Exit to desktop"** as a guest after opening Settings: the character is current; without Settings, the last 5-10 s
   are missing. Rejoining within 10 s through a different slot works after a short wait (retry).
8. **Host quits** to its title: the guest gets the message within ~5 s, taps the button, fades to the title. Repeat with the host
   process killed (about 30 s) and with the host reloading its save (a few seconds).
9. **Short outage.** Unplug the guest's network for 15 s: the "Connection lost" notice shows, nothing else; plug back in and play on.
10. **Export.** After a session, `mod_data/mistrimulti/exports/` holds one file for the world; its `core.data.stats.gold` equals the
    host's file. As host of a new world, `mistrimulti.import_character "<file>"` restores the character; the F8 line shows no error.
11. Nothing crashes and the debug console is not needed in normal play.
