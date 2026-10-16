# In-game Multiplayer menu (Host a game / Join a game)

Status: written against the game's scripts and tested against stand-ins and the real launcher / helper binaries. **Not yet run
in the real game.** `tests/test_menu.py` drives the GML menu code against a scripted fake launcher and, end to end, against the
real Linux launcher, helper and a real host; `tests/test_launcher_linux.py` and `tests/test_launcher.py` (Windows launcher under
Wine) test the launcher side. The popup, text-box and localisation calls are the one thing no test can prove: see
"Unverified assumptions" and the "In-game checklist" at the end.

## The goal

After the installer, a player only starts the game from Steam. Everything about hosting and joining is chosen in the game:

1. **New Game** or **Load Game**, then **Multiplayer** (the existing "Singleplayer or Multiplayer?" popup).
2. **Host a game** or **Join a game**.
3. Host: **Start hosting** (optionally **Set a password**), then the game shows the addresses to give to friends (Tailscale
   and this network), then **Start playing**.
   Join: the game looks for hosts, lists them (with `[password]` when the host set one), or you **Type an address**; a password
   (and, for hosts that use one, a room code) is asked for; the host's world is downloaded; the world opens.

No `host` / `join` / `--configure` / `steam-setup` step is needed for normal use. Those tools stay as optional advanced tools.
The one setup that remains is the Steam launch option (`install.sh` sets it on Linux; on Windows the manager's **Steam setup...**
button copies the line, once), because a mod can neither start programs nor open sockets, so something must be started
by Steam: the launcher.

## Who does what

```
game (GML mod)                         launcher (assembly, started by Steam)               helper (assembly)
MistriMultiMenu.gml                    linux/menu.inc  or  launcher/menu.inc               host / join transport
  shows popups, validates input          supervisor: reads commands, runs sessions            (unchanged protocol)
  writes menu/cmd.txt            ----->  scan (net.inc / MistriMulti.exe --scan)
  reads  menu/status.json        <-----  world download (net.inc / world.inc)
                                         discovery answer UDP 7776 + world server TCP 7775 (host only)
                                         starts / stops the helper, writes control.json
```

**Deviation from the first idea, on purpose.** The brief said the helper should idle and accept live commands. The supervisor is
the launcher instead: it is the one process that already (a) lives exactly as long as the game, (b) owns the scan, the world
download, the discovery answer and the world server, and (c) starts the helper with the arguments the transport needs
(role, player number and host address are command-line arguments of the helper and its UDP socket is bound at start). A helper
that idles would need a second copy of all of that or a live-reconfiguration path in a security-sensitive loop. So the
transport helper is started on demand for each host or join session and ended when the session ends. The player-visible
effect is the same ("the helper is always there and waits for the menu"), with a smaller attack surface: **in standby nothing
listens**.

## Standby (what the launcher does when Steam starts the game)

`mistrimulti-launcher --steam %command%` (Linux) / `MistriMultiLauncher.exe --steam ...` (Windows) used to need a valid
`launcher.cfg`; without it, nothing multiplayer started (the log on the Debian machine: "no multiplayer started because setup
had not been run"). Now:

- **No valid `launcher.cfg` (missing, empty, damaged): standby.** The launcher creates `mod_data/mistrimulti/menu/`, writes
  `control.json` as `{"enabled":false,"mode":"idle",...}`, checks that the helper program exists, publishes
  `menu/status.json` (state `idle`, or `error` with code 1 when the helper is missing), backs up the solo saves as before, and
  starts the game. `launcher.log` says "Waiting for Host or Join in the in-game Multiplayer menu".
- **Nothing is hosted or joined, no helper runs, no port is open.** The discovery answer (UDP 7776) is needed only by a host, so
  it is **not** opened in standby: a player who only joins never answers scans, and nobody can download a world from a computer
  that did not choose to host (the world server, TCP 7775, answers only a player whose join the helper authenticated: `docs/PROTOCOL.md`). Both open when Host starts and
  close when it stops or the game ends.
- **A valid `launcher.cfg` still works** (older setups, `mistrimulti-manager host|join`, `--configure`): that role starts by
  itself as before, and the menu shows it as running. Menu commands replace it for the session, ignoring `launcher.cfg`
  (default port 7777 and room code; port, room and password may be sent by the menu). Delete `launcher.cfg` to get plain standby.
- The game **always** starts, whatever fails (unchanged rule). If the game's data folder cannot be found (Linux) the launcher
  cannot write anything: the game starts plain, and the in-game badge says the launcher is not running.
- When the game closes the launcher publishes state `stopped` (so the badge does not keep saying Idle), stops the helper and
  closes the sockets.

## The bridge files (no new network ports)

Same mechanism as `tx.frame` / `status.json`: plain files in the mod's data folder, replaced atomically.
`<mod data>` is `mod_data/mistrimulti` inside the game's data folder.

### `<mod data>/menu/cmd.txt` (mod -> launcher)

Written by the mod as `cmd.tmp`, then renamed. `key=value` lines, LF or CRLF, at most 1000 bytes are read:

| key | meaning |
| --- | --- |
| `seq` | 1..999999; the launcher applies a command only when `seq` differs from the last one it applied. The mod starts from a clock-based number so a restart of the mod cannot reuse one |
| `cmd` | `host`, `join`, `scan` or `stop`; anything else only moves `seq` |
| `host` | join: the host's IPv4 address (`a.b.c.d`) |
| `port` | optional, 1..65535, default 7777 (the game port of the host: the scan reports it) |
| `password` | optional, 1..64 printable ASCII characters, no spaces |
| `room` | optional, 8 hex digits (hosts with a custom room code; default `4d495354`) |

### `<mod data>/menu/world.txt` (host mod -> launcher)

`id=<Game.unique_identifier>` (one line), written by a host's mod as `world.tmp` and renamed, once per world, as soon as the world is
loaded. It tells the launcher which world is being played now, so the world server sends THAT world's newest save and says whether one
exists (`docs/PROTOCOL.md`, "World info"). The launcher never trusts it: the id must parse as 1..2147483647, anything else is "no note". It belongs to a
session: the launcher deletes it when it starts, on every `host` / `join` / `stop` command and at the end of the game. The mod forgets
what it published when the title screen returns.

The launcher **deletes the file as soon as it has read it** (a password must not stay on disk; the only copy is the helper's
`auth.cfg`, mode 0600 on Linux, as before). Every value is validated (same checks as `launcher.cfg`); an invalid command is
answered with state `error`, err 3, and starts nothing. Not a regular file (directory, FIFO, link to nowhere) is ignored.

### `<mod data>/menu/status.json` (launcher -> mod)

Rewritten after every change and at least once a second:

```json
{"v":1,"hb":1789596,"seq":3,"state":"hosting","err":0,"session":"host","helper":1,"scan":2,"port":7777,"hw":0,"hf":0,"dw":0,
 "addrs":["100.64.0.7","192.168.1.20"],
 "hosts":[{"ip":"100.101.102.103","port":7777,"flags":2,"name":"DECK"}]}
```

- `hb` moves while the launcher lives (monotonic milliseconds, Windows: 31 bits of `GetTickCount64`). The mod calls the launcher
  dead when it stops moving for 4 s (40 s while `scanning` / `downloading`, which block the launcher's loop for a while).
- `seq` is the last command applied: the mod waits for `seq == its own` before it trusts the state.
- `state`: `idle`, `hosting`, `joining`, `downloading`, `ready` (joined and world downloaded), `error`, `scanning`, `stopped`.
- `session`: `none`, `host`, `join`. `helper`: 1 when the helper program exists. `scan` counts finished scans (a scan that
  ended in error 7 counts too).
- `hw`, `hf`, `dw` (guest, after the world download; zero otherwise and cleared by `host`, `join` and `stop`): the id of the world the host
  plays now (0 = not told), its flags (bit 0 named, bit 1 saved) and the id of the world file that arrived. Added after 0.4.5; the mod treats a
  missing field as 0.
- `addrs` (host): this computer's addresses, Tailscale first. `hosts`: at most 12 found by the last scan, `flags` as in the
  discovery reply (bit 0 custom room code, bit 1 needs a password, bit 2 the host named the world it plays, bit 3 that world is saved), `name` cleaned (printable ASCII, `"` and `\` replaced by `_`).
- The mod validates every field (`mistrimulti_menu_clean`); a damaged file is ignored, the last good one is kept.

### Error codes (`err`; the words are in `mistrimulti_menu_error_text`)

| err | meaning |
| --- | --- |
| 1 | the helper program is missing |
| 2 | the helper could not start (port busy; see `helper.log`) |
| 3 | an address, port, room or password in the command is not valid |
| 4 | the host did not answer the handshake within 12 s (wrong address, host not hosting, a room code is needed) |
| 5 | the password cannot be written to the helper's configuration |
| 6 | `control.json` could not be written |
| 7 | (Windows) scanning is not available: `MistriMulti.exe` is not next to the launcher |
| 21 | wrong password |
| 22 | the host blocked this computer |
| 23 | the player number is already used on the host (the launcher picks another one on the next try) |
| 24 | the host's game is full |
| 26 | the host needs a password and none was sent |
| 41..47 | world download: 41 cannot connect (port 7775), 42 the host has no saved world yet, 43 invalid reply, 44 checksum mismatch, 45 cannot write, 46 out of memory, 47 refused (no joined session, wrong proof, or a host from an older release) |
| 48 | world download: the host plays a world it has not saved yet (nothing downloadable is that world) |
| 49 | (mod only) the world that arrived is not the world the host plays now (`hw != dw`) |

(21..26 are `20 +` the helper's reject reason in its `status.json`; 40.. are `40 +` the `world_fetch` result; 49 is made by the mod.)

## What a command does

- **host** (`password`, `port`, `room` optional): stop whatever runs; `cfg_mode = host`, player 0; fresh epoch; prepare
  `bridge_0`; write `auth.cfg`; write `control.json` (`enabled:true, mode:host`); start the helper
  (`host <port> 0 <room> <bridge>`); open UDP 7776 and TCP 7775; collect this computer's addresses (adapters, then the
  Tailscale self address first); state `hosting`.
- **join** (`host`, `port`, `password`, `room`): stop whatever runs; pick a player number 1..7 different from the last try;
  write `auth.cfg` and `control.json` (`mode:join`); start the helper (`join <port+player> <player> <room> <bridge> <ip> <port>`);
  state `joining`. The launcher then watches the helper's own `status.json`: `auth == 2` (the host's authenticated WELCOME) ->
  state `downloading`, download the world into `multiplayer/saves` (the existing TCP client: size and SHA-256 checked, `.part` file
  renamed; the download first proves the helper's session key, `docs/PROTOCOL.md`), state `ready`. A reject reason or 12 s without a WELCOME ends the session with an error. **The password is
  therefore checked before anything is downloaded.**
- **scan**: state `scanning`; the host scan of the manager (broadcast on every local network plus the Tailscale peer list).
  Linux runs `mp_scan` in the launcher; Windows runs `MistriMulti.exe --scan <file>` as a child process (the same code as the manager window). `scan += 1`, hosts published.
- **stop**: close everything, `control.json` disabled, state `idle`.

The scan and the download block the launcher's loop (about 1.5 to 6 s for a scan, up to 15 s plus connect time for the world).
That is why `status.json` shows `scanning` / `downloading` first, and why the mod gives those states a longer heartbeat grace.

## The mod (GML)

`MistriMultiMenu.gml` (new), small edits in `MistriMultiSaveSpace.gml`, `MistriMultiStatus.gml`, `MistriMultiBoot.gml`.

- `mistrimulti_savespace_chosen(kind, true, arg)` (after "Multiplayer") now calls `mistrimulti_menu_begin(kind, arg)`. If the
  launcher is not running, stopped, or has no helper, a popup says so in plain words and nothing else happens.
- The flow is a state machine in `__mistrimulti_menu().flow`: `choose`, `host`, `wait_host`, `hosting`, `wait_scan`, `list`,
  `input`, `wait_join`, `error`. `mistrimulti_menu_tick()` runs every frame from `mistrimulti_tick` (title screen too), polls
  `status.json` every 10 frames while a flow is active and every 60 otherwise, and moves the flow.
- Screens use only what the game's own scripts use: `MultipleChoicePopup(title)` + `.option(label, callback, args)` for the
  choices (the pattern the existing "Singleplayer or Multiplayer?" popup uses), `popup_creator(title, body)` +
  `.create_button(label, callback, args)` + `.spawn()` for messages (at most two buttons: the game warns about more), and
  `text_input_popup(title, "", 110, callback, [kind])` (the game's own text box, as used for naming a farm) for the address,
  password and room code. No keypad was needed.
- Dynamic text (addresses, host names, error words) is given to the game as local keys `mistrimulti/t/<n>` answered by the
  mod's existing `local.missing` filter; every text gets a new key, so a popup already on screen can never change.
- After a popup is closed or replaced, the next one is shown 12 frames later (the game checks that only the top popup closes).
- **Start playing** (host) and the end of a successful join call `mistrimulti_savespace_enter(kind, arg)`: switch to the
  multiplayer saves (`mistrimulti_savespace_try_set(true)`), then the existing `enter_multiplayer` (host: continue the
  multiplayer world or start a new one; guest: load the downloaded world). `control.json` already says host or join, because the
  launcher wrote it when the session started, so the existing initialisation (`mistrimulti_initialize`) is unchanged.
- Returning to the title screen (`game.title_entered`) closes the flow and sends `stop` if a session is running, so nobody stays
  connected as a ghost.
- Everything is guarded: a popup or file error is logged (`mmapi_log_error`), the flow resets (and sends `stop`), the game goes on.
  Singleplayer is never touched.

## Leaving the flow: every way out resets everything

Real-game finding (0.4.5): New Game > Multiplayer > Host a game > Cancel left **New Game dead until the game was restarted**.
Cause: the game closes any popup by itself on Escape or on a click outside it **without calling a button**, so a state that only a
button callback cleared (the `choosing` flag in `__mistrimulti_savespace()`, the menu `flow`, a session on the launcher) stayed set,
and the New Game wrapper (`mistrimulti_title_enter_game`) ignores the button while `choosing` is set. Now:

- **One exit.** Cancel, Close, Back to the title, Escape and a click outside all end in `mistrimulti_menu_cancel` -> `mistrimulti_menu_reset(stop)`:
  popups and text box closed, the flow dropped, `choosing` cleared, and `stop` sent whenever the launcher has (or is starting) a session. The
  decision is `mistrimulti_menu_session_running`: the screen says so (waiting for the host / scan / join, hosting, the error that follows a session)
  **or** the launcher's status shows a session.
- **Escape is seen.** The tick compares the flow's popup with `close_requested` (the game sets it when it closes a popup by itself) and treats
  a closed popup as Cancel. A closed text box returns to the screen before it (as before).
- **A flag is never trusted alone.** `mistrimulti_savespace_choosing_live()` clears `choosing` unless the Singleplayer / Multiplayer popup
  (`choose_popup`) or the flow is really on screen. It runs in the tick and again when New Game / Load Game is pressed, so even if
  something else leaves the flag behind, the button works at once. A flow with nothing on screen and nothing coming is reset after 3 s.
- Beginning the flow again closes any old flow and stops its session. A failing popup constructor clears the flag and lets the game's own
  New Game go on.
- `tests/test_menu.py::test_every_cancel_path_resets_and_can_restart` walks every screen (question, choose, host, waiting for the host,
  hosting, host list, looking for hosts, connecting, downloading, the error screens, world-not-saved, world-changed, the four text boxes)
  and every exit of it (button, Escape, closed text box), checks that nothing is left and that the session was stopped where one had been started, then
  presses New Game and Load Game again. Not covered: the "Continue world / New world" popup the game shows AFTER Start playing (a host
  who presses Escape there is in the multiplayer save space with a running host session; New Game still works, and the title screen stops the session).

## Which world does a guest get? (finding 2 of the 0.4.5 real-game test)

The host started a NEW world (New Game > Multiplayer > Host a game > Start a new world) without saving. The guest joined and downloaded the host's
**last saved** world (day 3) while the host was in the new world (day 1): wrong day ("Your day is ahead of the host's world"), the guest's
character carried the old world's progress. The identity of a world is the game's `Game.unique_identifier` (the mod's world key is
`<host identity>_<id>`, and the id is the number in the save file's name). Now:

1. **The host publishes the world it plays** (`menu/world.txt`, above). The launcher serves only that world's newest save, signs the id and a
   "saved" flag into the world header, answers a world that was never saved with status 4, and repeats the facts in the discovery answer (`docs/PROTOCOL.md`, "World info").
2. **The guest compares before it enters.** After the download the launcher reports `hw`, `hf`, `dw`. The mod enters when the world that arrived
   is the world the host plays (`hw == dw`) or when nothing was said (`0`: an older host or launcher). Otherwise:
   - the host's world is not saved: error 48 "The host has started a new world but has not saved it yet. Ask them to sleep or save once, then press Join again." (**Try again** joins the same host again);
   - the host changed world while the guest was downloading (`hw != dw`): error 49, the session is stopped, **Try again** downloads again;
   - the host list marks hosts whose current world is not saved ("[new world, not saved]", from the discovery flags).
3. **Safety net inside the world.** `mistrimulti_menu_guest_world_check` (every tick, guests) compares the suffix of the host's world key (from its
   frames) with this game's `Game.unique_identifier`. A difference sets `r.world_mismatch`: `MistriMultiPlayerSync.gml` then never hands the guest's character
   to the host (so nothing of the old world is written into the new world's records), and `MistriMultiGuestSave.gml` shows "The host is playing a
   different world than the one you downloaded ..." and returns the guest to the title screen after 2 s (state `wrongworld`, like `restarted`). The same path
   already handled a host that starts another world during the session (`restarted`). Guests' solo saves are never touched (a guest saves nothing).
4. **The host's side is easier: a new world is saved early.** `mistrimulti_world_options_hearts` (the last question of New world) marks the
   session `new_world`. `mistrimulti_menu_early_save` waits until the world is loaded and published, the player is in control (`PlayerState.Default`),
   at home, no scene (`MIST.is_running()`), no popup, no loading screen, then does what the journal's "Save your progress?" does: hold the player
   (`PlayerState.Dummy`), `LOAD_SEQUENCE.start("misc_local/saving", ...)`, inside it `ARI.save_position = ...` and
   `save_game(exact_save_path(Game.unique_identifier, false))` (the autosave name, so the host's own end-of-day autosave replaces it later), then back to `Default`.
   `save_game` runs `game.save_guard`, so `mistrimulti_save_guard` (flush guests, checkpoint, drops) and `save.game_saving` (wallet, renown, progress commit) run exactly as for any
   save; nothing is bypassed. The host reads "MistriaMulti: your new world is saved. Friends can join now." (the game's own "Save complete" shows too). One attempt;
   a failing save still finishes the loading sequence and says "could not be saved". If the conditions are not met within two minutes the host reads
   "your new world is not saved yet, so friends cannot join it. Sleep or save at the journal once." (once).
   **Not possible / not done:** the world cannot be saved before the player is in control (the intro scene and the first moments run inside MIST scenes the mod must not interrupt);
   there is no hook for "world finished loading", so the mod polls; the save uses the autosave file name, not a manual one. A host who continues an existing world needs nothing.
5. **Old releases.** A new guest against an old host gets zero world info (nothing changes). An old guest against a new host that has a note: status 4 is "invalid
   reply" (code 43) for it; a world with a save is sent as before (an old guest ignores the new header fields). Both sides need the release after 0.4.5 for the new behaviour.

## The badge ("Multiplayer: Offline / Idle / Online")

The real-game test showed no badge at all: the mod runtime has no `draw_*` functions (`draw_set_color`, `draw_text_transformed`
...: "no such field"), so the old drawing code threw on every frame. The badge is now made of the game's own UI system instead
(`MistriMultiHudText.gml`, shared with the sleep counter of `docs/SYNC-CLOCK.md`):

- **How it is shown.** Two ANCHOR text nodes on `ANCHOR.screen_canvas`, layer `Hud`, aligned `RightIn` / `BottomIn` with a
  small inward offset: the text in the level's colour (`node.set_color`, red / amber / green) and a black copy one pixel to the
  lower right, behind it (lower `z` is nearer in ANCHOR), as an outline. The text is `Multiplayer: Offline - <reason>`,
  `Multiplayer: Idle - choose Multiplayer in New Game` or `Multiplayer: Online (hosting|joined)`. `node.set_text` only changes
  the node when the text differs, so a steady badge costs nothing.
- **When it updates.** `mistrimulti_badge_tick` runs in the mod tick (60 Hz, `MistriMultiBoot.gml`): it re-reads the launcher /
  helper status about once a second and sets the node. The `ui.draw_gui` hook now only counts draws for the watchdog.
- **Title screen, worlds, menus, room changes.** It shows on the title screen and in multiplayer worlds (the old rule) and is
  hidden (alpha 0) elsewhere, e.g. in a singleplayer world. The game shuts ANCHOR down and builds a new one at some state
  changes, which frees every node: each tick the slot checks that its ANCHOR is still the live one and its nodes are not
  freed, and builds new nodes if not. Nodes are not created while a world's room change is unsettled (`room_settled`, Boot).
  The badge sits on the `Popup` layer (the layer of the game's toolbar), so it is no longer drawn behind other UI; its z (900)
  is behind popup contents of the same layer. On the title screen it sits 16 px above the bottom edge, over the game's
  "(c) 2024-2026 NPC Studio" line (bottom right, `TitleMenu.setup_main_screen`); in a world it sits in the corner (4 px).
  `mistrimulti_hudtext_set` moves an existing node when the offset changes. Texts are short (about 40 characters at most).
- **The states, true in a world.** In a multiplayer world (`runtime.enabled`, mode host or join) the badge reads the signals the
  event layer uses (`MistriMultiBoot.gml` tick, `__mistrimulti_world_link`): the helper's `status.json` heartbeat seen within
  3 s, and the peer mask. `Online (hosting)`: heartbeat moving. `Online (joined)`: heartbeat moving and the host's bit in the mask.
  A guest with a heartbeat but no host bit says `Joining the host...`; before the first status read `Connecting...`; a heartbeat
  that stopped says `Offline - connection lost`. The old "helper not running" text (control.json said a session exists but the
  separate once-a-second read had not seen a heartbeat) was stale in worlds and is gone: on the title screen a just-started
  session says `Starting...` for up to 10 s, then `Offline - helper stopped`. The log line carries the reason (`heartbeat N, mask M`).
- **Never throws.** Every ANCHOR call is inside try/catch; a failure is logged (rate limited) and the slot is dropped and
  rebuilt on the next tick. No `ANCHOR` / screen canvas yet (very early frames): nothing happens, the next tick retries.
- It logs every change of its text with the reason ("Badge: Multiplayer: Offline - launcher not running ... [the launcher's
  status file does not exist (<path>) ...]") and logs once when the node is first built (`trace hudtext: created the 'badge'
  text node`) and once when it is first on screen. If the `ui.draw_gui` hook never fires, `mistrimulti_badge_watchdog` logs that
  after 900 frames. **F8** is unchanged: it shows the badge text and the reason as a notification (it works outside a session).

## Security notes

- Standby opens nothing. Hosting opens UDP 7776 (answers 64-byte queries with 64 bytes), TCP 7775 (world, released only to an authenticated
  join session; not encrypted) and the helper's UDP game port, only while hosting.
- The mod only sends validated values; the launcher validates again. A newline in a password cannot add a key (rejected by the
  mod; the launcher's `v_pass` rejects control characters and spaces).
- The command file is deleted after reading; a password lives only in the helper's `auth.cfg` (0600 on Linux, per-user data
  folder on Windows).
- The status file is local and untrusted by the mod anyway (types and ranges are checked, host names cleaned).
- Anyone who can write the user's mod data folder can already change `launcher.cfg` and the mod itself; the menu adds no new
  privilege.

## Tests

| Command | What it covers |
| --- | --- |
| `python3 tests/test_menu.py` | the GML menu and badge against a scripted fake launcher: every screen, validation, error words, cancel/Escape, silent launcher, hostile status file, badge states and fallbacks, the badge in a world, short popup labels; **every cancel path of the host / join flow followed by New Game again, stuck flags healing, the world check before entering, the host's world note, the guest's wrong-world detection, the early save of a new world (25 tests)**; `python3 tests/mutate_polish.py` and `python3 tests/mutate_joinflow.py [--asm]` break things on purpose |
| `unshare -n ... python3 tests/test_menu.py <launcher> <helper> <fakegame>` | plus an end-to-end test: GML menu <-> real Linux launcher + helper <-> a real host: host with password, scan, wrong password, right password, world download, leave, badge Online |
| `tests/test_launcher_linux.py` (`test_menu_*`, `test_world_info`) | standby, nothing listening, host/stop, helper arguments, scan and join with a real host, failures, command validation, helper missing, `launcher.cfg` compatibility; **the world note: which save is served, signed world info, status 4, discovery flags 4/8, junk notes, hw/hf/dw in the guest's status, the note's lifetime** |
| `tests/test_launcher.py` (`test_menu_*`, `test_world_info`, Wine) | the same for the Windows launcher; `--addrs` and `--scan` of `MistriMulti.exe`; a real Windows host helper with a password; the same world-info cases (shared in `tests/worldserver_cases.py`) and the Windows guest reading the signed world info |

Sandbox note: tests that open ports run in a private network namespace (`unshare -n`, `lo` up), as `scripts`/`runall.sh` do.

## Unverified assumptions (the real game was not available)

1. `MultipleChoicePopup`, `popup_creator`, `text_input_popup` and `ANCHOR.wrap_for_local` behave as in the game's scripts that
   use them (`anchor_utils.gml`, `PopupMenu.gml`, `obj_farm_plate.gml`, `CustomizationMenu.gml`). Read from source, never executed.
2. That `local_get` calls `local.missing` for keys like `mistrimulti/t/12` each time (documented in the MMAPI hook), also for
   button labels created by `create_button`, `option` and `add_title`.
3. That a popup can be closed from code with `popup.close()` (the game's own `MultipleChoicePopup` does it), that closing several
   frames before opening the next is enough, and that Escape on a message popup sets `close_requested` (treated as Cancel).
4. That "\n" in a popup description starts a new line. If not, the address list is on one line.
5. That a MultipleChoicePopup with up to seven options fits the screen (the host list is capped at four hosts).
6. That `save_text_file` + `file_rename` over an existing file replaces it on Windows and Linux (the `tx.frame` code relies on it).
7. That `text_input_popup` works on the Steam Deck (it has its own Steam keyboard branch in the game's code).
8. That the badge hook (`ui.draw_gui`) fires on the title screen on Linux/Proton; the log says if it does not. And, new, the
   ANCHOR assumptions of the badge (the stand-in only fakes ANCHOR): `ANCHOR.text(parent, z, layer)`, `set_align`, `set_xy`,
   `set_color`, `set_text`, `set_alpha` are callable on the mod runtime (the chain returns the node, as in `InfoHudMenu.gml`);
   the enums `Align` and `AnchorLayer` and `ANCHOR.screen_canvas` are visible to the mod; a text node's `color` tints the whole
   text (the game's `draw_text_with_color`); a node created in the mod tick renders from the next frame; `node.freed` becomes
   true when the game frees it, and `ANCHOR` is a new struct after the game rebuilds it; the `Hud` layer is shown on the title
   screen; the 480x270-based offsets land the text in the corner without clipping; long reasons fit the screen width.
9. Proton: the launcher writes the bridge path the way the Windows game sees it (existing behaviour, `docs/STEAM-DECK.md`).
10. Windows: not run on a real Windows machine; Wine only.

11. `Game.unique_identifier` is a whole number 1..2147483647 equal to the digits in the save's file name (read from `SaveManager.gml`,
    `LoadState.gml`), on host and guest. A guest's `Game.unique_identifier` after `LoadState.Load` is the file name's id.
12. A popup that the game closes by itself (Escape, click outside) has `close_requested == true` and runs no button callback (read from
    `PopupMenu.gml`, `AnchorMenu.run_exit_listening`).
13. The early save: `LOAD_SEQUENCE.start(key, fn, args, fade)` calls `fn` and finishes when it returns true; `LocationPosition`, `Vec2`, `PlayerState.Default` / `Dummy`,
    `exact_save_path`, `save_game`, `MIST.is_running()`, `ANCHOR.popup_is_open()`, `is_home_location` and `obj_ari.fsm.current_state_id()` are callable from the mod
    (all are used by the game's own journal-save code, `Interact.gml`; never executed by the mod). That a new game's first controllable moment is at home with
    `PlayerState.Default`. That saving at that moment does not disturb the intro.

## In-game checklist (please walk through it once and report)

1. Start the game from Steam with **no** `launcher.cfg`. The badge (bottom right, title screen) says `Multiplayer: Idle ...`
   in amber, with a dark outline, readable, not cut off at the screen edge. If it is missing or red, press **F8** and send
   `launcher.log`, `menu/status.json` and the game's MMAPI log (look for `trace hudtext` and `On-screen text 'badge' failed`).
   Also check: it stays when you open Settings or a popup closes, it is still there after you load a world and after you
   return to the title screen, and it turns green `Online (hosting)` while hosting and red with a reason if you close the helper.
2. New Game -> **Multiplayer** -> the popup "Multiplayer" with Host a game / Join a game / Cancel. Cancel closes it cleanly.
3. **Host a game** -> Set a password (type one, confirm) -> Start hosting -> "Starting your game for friends..." ->
   "You are hosting" with your Tailscale / network addresses (check the line breaks) -> Start playing -> your world opens, the
   badge turns green `Online (hosting)`.
4. On a second computer: Multiplayer -> **Join a game** -> "Looking for hosts..." -> the host is listed with `[password]` ->
   pick it -> type the password -> "Connecting..." -> "Downloading the host's world..." -> the world opens, the badge says
   `Online (joined)`. Repeat with a wrong password (message "Wrong password", Try again asks again) and with **Type an
   address**.
5. Quit to the title screen on the guest: the host no longer sees the guest after a few seconds; the badge goes back to Idle.
6. Press **Escape** on "Looking for hosts" and on the text box: no stuck popup, no crash.
7. Stop the launcher (kill it) while on the title screen: the badge says `Offline - launcher stopped` within a few seconds;
   Multiplayer shows the plain-words popup.
8. **Cancel paths.** On the title screen: New Game > Multiplayer > Host a game > Start hosting > Cancel (on "Starting your game..."); then New Game
   again: the Singleplayer / Multiplayer question must appear. Repeat with Escape (and a click outside the popup) on: the question, "Multiplayer", the
   host screen, "Starting your game...", "You are hosting", "Join a game", "Looking for hosts", the password / address / room text boxes, "Connecting...",
   "Downloading ...", and an error. After each, New Game and Load Game must work, and on the host machine `launcher.log` / the badge must show that
   hosting stopped (the guest can no longer find the host). `Menu:` lines in the MMAPI log say "a popup was dismissed on screen <name>".
9. **New world.** Host: New Game > Multiplayer > Host a game > Start hosting > Start playing > New world (hearts choice). In the new world, once you can move at
   home, the game briefly shows "Saving..." and "MistriaMulti: your new world is saved. Friends can join now." (log: `saving the new world so friends can join it`;
   `<game folder>/multiplayer/saves/game-<id>-autosave.sav` exists; `menu/world.txt` says `id=<id>`). The guest joins at once and arrives in the SAME world
   (same day, no old character). If you walk away before the save (or a scene runs), after two minutes you read the "not saved yet" notice.
10. **Old save vs new world.** Host loads an old world, then returns to the title screen and starts a NEW one but dismisses the early save (cannot be forced;
    for the test, pull the plug on the save by quitting the game right after "Start playing"): a guest who joins reads "The host has started a new world but has not
    saved it yet. Ask them to sleep or save once, then press Join again." and is NOT put in a world. After the host sleeps once, "Try again" enters. The host
    list shows "[new world, not saved]" for that host.
11. A guest who is already in the host's world when the host starts another one is told and returned to the title screen within a few seconds.

## Known limitations

- The host's world is the last saved copy of THE WORLD THE HOST PLAYS (after 0.4.5; a new world is saved early by the mod): changes since the last save are not
  in it. The menu says so on the hosting screen, and "The host has no saved world yet" explains the empty case. A host whose launcher or mod is older than this change
  still gets the old behaviour (the newest save in the folder).
- The early save needs the player to be at home and in control; a host who leaves home first is told after two minutes. It uses the game's loading
  sequence, whose behaviour in the first minutes of a new game could not be tested (see the assumptions).
- A scan or a download blocks the launcher for a few seconds; the game is not affected (separate process), the menu shows
  "Looking for hosts..." / "Downloading...".
- The host password is optional and set from the menu; a custom room code can only come from an older `launcher.cfg` host or by hand.
- Windows needs the one-time Steam launch option (the manager's **Steam setup...** copies the line). An installer that sets it
  automatically is not part of this package.
- Only one host/join session at a time; a second game on the same computer would clash on the fixed ports (unchanged).
