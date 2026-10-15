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
  that did not choose to host (the world server, TCP 7775, has no password: `docs/PROTOCOL.md`). Both open when Host starts and
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

The launcher **deletes the file as soon as it has read it** (a password must not stay on disk; the only copy is the helper's
`auth.cfg`, mode 0600 on Linux, as before). Every value is validated (same checks as `launcher.cfg`); an invalid command is
answered with state `error`, err 3, and starts nothing. Not a regular file (directory, FIFO, link to nowhere) is ignored.

### `<mod data>/menu/status.json` (launcher -> mod)

Rewritten after every change and at least once a second:

```json
{"v":1,"hb":1789596,"seq":3,"state":"hosting","err":0,"session":"host","helper":1,"scan":2,"port":7777,
 "addrs":["100.64.0.7","192.168.1.20"],
 "hosts":[{"ip":"100.101.102.103","port":7777,"flags":2,"name":"DECK"}]}
```

- `hb` moves while the launcher lives (monotonic milliseconds, Windows: 31 bits of `GetTickCount64`). The mod calls the launcher
  dead when it stops moving for 4 s (40 s while `scanning` / `downloading`, which block the launcher's loop for a while).
- `seq` is the last command applied: the mod waits for `seq == its own` before it trusts the state.
- `state`: `idle`, `hosting`, `joining`, `downloading`, `ready` (joined and world downloaded), `error`, `scanning`, `stopped`.
- `session`: `none`, `host`, `join`. `helper`: 1 when the helper program exists. `scan` counts finished scans (a scan that
  ended in error 7 counts too).
- `addrs` (host): this computer's addresses, Tailscale first. `hosts`: at most 12 found by the last scan, `flags` as in the
  discovery reply (bit 0 custom room code, bit 1 needs a password), `name` cleaned (printable ASCII, `"` and `\` replaced by `_`).
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
| 41..46 | world download: 41 cannot connect (port 7775), 42 the host has no saved world yet, 43 invalid reply, 44 checksum mismatch, 45 cannot write, 46 out of memory |

(21..26 are `20 +` the helper's reject reason in its `status.json`; 40.. are `40 +` the `world_fetch` result.)

## What a command does

- **host** (`password`, `port`, `room` optional): stop whatever runs; `cfg_mode = host`, player 0; fresh epoch; prepare
  `bridge_0`; write `auth.cfg`; write `control.json` (`enabled:true, mode:host`); start the helper
  (`host <port> 0 <room> <bridge>`); open UDP 7776 and TCP 7775; collect this computer's addresses (adapters, then the
  Tailscale self address first); state `hosting`.
- **join** (`host`, `port`, `password`, `room`): stop whatever runs; pick a player number 1..7 different from the last try;
  write `auth.cfg` and `control.json` (`mode:join`); start the helper (`join <port+player> <player> <room> <bridge> <ip> <port>`);
  state `joining`. The launcher then watches the helper's own `status.json`: `auth == 2` (the host's authenticated WELCOME) ->
  state `downloading`, download the world into `multiplayer/saves` (the existing TCP client: size and SHA-256 checked, `.part` file
  renamed), state `ready`. A reject reason or 12 s without a WELCOME ends the session with an error. **The password is
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
  Menus and popups draw above the `Hud` layer, so they cover the badge while open.
- **Never throws.** Every ANCHOR call is inside try/catch; a failure is logged (rate limited) and the slot is dropped and
  rebuilt on the next tick. No `ANCHOR` / screen canvas yet (very early frames): nothing happens, the next tick retries.
- It logs every change of its text with the reason ("Badge: Multiplayer: Offline - launcher not running ... [the launcher's
  status file does not exist (<path>) ...]") and logs once when the node is first built (`trace hudtext: created the 'badge'
  text node`) and once when it is first on screen. If the `ui.draw_gui` hook never fires, `mistrimulti_badge_watchdog` logs that
  after 900 frames. **F8** is unchanged: it shows the badge text and the reason as a notification (it works outside a session).

## Security notes

- Standby opens nothing. Hosting opens UDP 7776 (answers 64-byte queries with 64 bytes), TCP 7775 (world, unauthenticated: use a
  private network) and the helper's UDP game port, only while hosting.
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
| `python3 tests/test_menu.py` | the GML menu and badge against a scripted fake launcher: every screen, validation, error words, cancel/Escape, silent launcher, hostile status file, badge states and fallbacks (14 tests) |
| `unshare -n ... python3 tests/test_menu.py <launcher> <helper> <fakegame>` | plus an end-to-end test: GML menu <-> real Linux launcher + helper <-> a real host: host with password, scan, wrong password, right password, world download, leave, badge Online |
| `tests/test_launcher_linux.py` (`test_menu_*`) | standby, nothing listening, host/stop, helper arguments, scan and join with a real host, failures, command validation, helper missing, `launcher.cfg` compatibility |
| `tests/test_launcher.py` (`test_menu_*`, Wine) | the same for the Windows launcher; `--addrs` and `--scan` of `MistriMulti.exe`; a real Windows host helper with a password |

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

## Known limitations

- The host's world is the last saved copy (unchanged): the host should sleep once before friends join. The menu says so on the
  hosting screen, and "The host has no saved world yet" explains the empty case.
- A scan or a download blocks the launcher for a few seconds; the game is not affected (separate process), the menu shows
  "Looking for hosts..." / "Downloading...".
- The host password is optional and set from the menu; a custom room code can only come from an older `launcher.cfg` host or by hand.
- Windows needs the one-time Steam launch option (the manager's **Steam setup...** copies the line). An installer that sets it
  automatically is not part of this package.
- Only one host/join session at a time; a second game on the same computer would clash on the fixed ports (unchanged).
