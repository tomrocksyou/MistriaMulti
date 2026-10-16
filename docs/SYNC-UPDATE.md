# Update button and release check (title screen)

Status: written against the game's scripts and tested against stand-ins (a fake update program, a fake release server, a fake
`curl.exe`) with the real Linux launcher and, under Wine, the real Windows launcher. **Not yet run in the real game, and not with the real
update program** (it is built by the EasyUpdate package; the contract is below). See "Unverified assumptions" and the "In-game checklist" below.

## What the player sees

Bottom left of the title screen, right after the game's own `v1.0.8 (modified)` text:

```
v1.0.8 (modified)  MistriMulti 0.4.6  [Update]
```

- `MistriMulti 0.4.6` is always there.
- When the launcher's daily check found a newer release, an **Update** button sits next to it. Clicking it starts the update; the
  text then shows plain words: `Checking for updates...`, `Downloading 0.4.7...`, `Installing 0.4.7...`, then either
  `Installed. Restart the game` or `Updated. Close the game and press Install in MOMI`, or a plain error
  (`Update failed: <the program's words>`, with the button back for another try).
- In a world the badge and the F8 text add ` - update available (0.4.7)`.
- Nothing about this feature can stop the game: every widget call is guarded, and a missing launcher just means no button.

## Who does what

```
game (GML mod)                         launcher (assembly, started by Steam)                update program (A: EasyUpdate)
MistriMultiUpdateUI.gml                linux/menu.inc / launcher/menu.inc                   Linux:   mistrimulti-manager update --result <file>
  label + Update button                 common/updatecore.inc  (shared logic)               Windows: MistriMulti.exe --update <file>
  cmd.txt  cmd=update  ------------>   starts the program (child), never waits for it       writes state=/version=/message=/error=
  status.json  <------------------     reads the result file once a second, publishes it   exit 0 on done / needs_momi
                                        daily release check: curl, in the background
```

### Commands (mod -> launcher, `menu/cmd.txt`, same `seq` / delete-when-read / validation as the others)

| `cmd` | meaning |
| --- | --- |
| `update` | run the update program (one at a time). Ignored while a run is going and after `done` / `needs_momi`. Refused with `ue=61` while hosting or joining. Other fields in the file are ignored |
| `update_cancel` | stop a run that is `checking` or `downloading` (kill the program, state back to `none`). An `installing` run is never cut off half way |

Both are answered like every command: `seq` in `status.json` becomes the command's number. Neither changes `state` / `err` /
`session` of the host / join machinery.

### Fields added to `menu/status.json`

| field | values |
| --- | --- |
| `update` | `"0.4.7"` when the latest release is newer than the installed mod (`<game>/mods/mistrimulti/manifest.toml`), else `"none"` |
| `us` | update run state: `none`, `checking`, `downloading`, `installing`, `done`, `failed`, `needs_momi` |
| `uv` | the version the run works on (`""` if unknown) |
| `um` | the program's message, cleaned (printable ASCII, at most 90 characters, `"` becomes `'`, `\` becomes `/`) |
| `ue` | error code 0..999: the program's own, or ours: 61 busy (hosting / joining), 62 update program missing, 63 it ended without a result, 64 it failed without saying why, 66 it ran too long |
| `ur` | counts started runs (also refusals), so the mod can tell a new run from an old result |

The mod validates all of them again (`mistrimulti_update_fields`) and shows its **own** words for each state; only a failure message
is taken from the program.

### The update program contract (provided by A)

`mistrimulti-manager update --result <file>` (Linux) and `MistriMulti.exe --update <file>` (Windows), non-interactive, next to the
launcher. It writes `key=value` lines atomically to `<file>` (`<mod data>/menu/update.txt`): `state=` (`checking`, `downloading`,
`installing`, `done`, `failed`, `needs_momi`), `version=<x.y.z>`, `message=<plain words>`, `error=<number>` (also accepted: `code=`).
Exit code 0 on `done` / `needs_momi`, nonzero on failure. The launcher uses these rules:

- it reads the file about once a second while the program runs, and once more when it ends;
- an unknown `state` makes the whole file ignored; a bad `version` is dropped; the message is cleaned; the error is clamped;
- the exit code outranks the file: nonzero turns any state into `failed` (64 if the file gave no code); exit 0 without
  `done` / `needs_momi` is `failed` 63;
- a run longer than 5 minutes (15 while `installing`) is killed: `failed` 66. `MISTRIMULTI_UPDATE_TIMEOUT_MS` shortens this for tests;
- stdin, stdout and stderr are `/dev/null` (Linux) / no window (Windows). The program is **not** tied to the launcher's life
  (no death signal, no job object): an update that has begun may finish after the game closed.

## The release check

Once a day at most the launcher asks for `latest.txt` of the latest release (the same list the update program reads, see
`docs/RELEASES.md`): `https://github.com/tomrocksyou/MistriaMulti/releases/latest/download/latest.txt`. Only its first line,
`version <x.y.z>`, is used, and only when it is valid.

- **Where it runs, and why.** In the launcher's serve loop, **after the game was started** (`sv_poll` only runs from there), as a
  child `curl` that polls without blocking (`--max-time 5 --connect-timeout 3 --max-filesize 65536`, https only, redirects only to
  https). The launcher has no TLS of its own; `curl` ships with Windows 10+ and SteamOS / most Linux. A slow or dead network can
  therefore never delay the game, and the launcher never waits for the answer. The launcher kills the child after 8 seconds.
  The alternative (a thread) would need threads in raw-syscall assembly; the child process is simpler and isolated.
- **Silent.** Any failure (no curl, no network, HTTP error, junk, an oversized or invalid answer) is ignored: `update` stays `none`
  (or the remembered answer), nothing is shown, nothing is logged but the check file.
- **Remembered.** `<mod data>/update_check.txt`: `checked=<unix seconds>`, `ok=1|0`, `latest=<version>`. A success is trusted
  for 24 hours; a failed try is retried after 3 hours. A stamp from the future or junk is not trusted. Within the window the
  remembered `latest` is published again at every start, so the button appears without a request.
- **Opt out.** Default on. Create `<mod data>/update.cfg` (next to `launcher.cfg`) with the line `check=off` (also `no`, `0`,
  `false`, any case). Nothing is then requested and no `update` is ever published; the version label stays, the button never
  appears. (Mod data folder: Windows `%LOCALAPPDATA%\FieldsOfMistria\mod_data\mistrimulti`, Linux the game's data folder
  `.../FieldsOfMistria/mod_data/mistrimulti`.)
- **Installed version.** Read from `<game folder>/mods/mistrimulti/manifest.toml` (`version = "x.y.z"`), the game folder being where
  the game program named on the launcher's command line lives. Unknown installed version: no `update` is offered. The mod
  compares again with its own `mistrimulti_mod_version()` (kept equal to the manifest by `tests/test_updateui.py`), and shows the
  button only if the release is newer than the mod that is running.
- **Test hook.** `MISTRIMULTI_RELEASE_URL` replaces the URL (and drops the https-only rule) so tests can use a loopback server.

## The mod (GML)

`MistriMultiUpdateUI.gml` (new), small edits in `MistriMultiMenu.gml` (`mistrimulti_menu_clean` carries `upd`), `MistriMultiStatus.gml`
(the in-world note), `MistriMultiBoot.gml` (the tick and the F8 note).

- **Label.** An ANCHOR text node that is a **child of the game's version text** (`TitleMenu.sha_text`, found through the title menu
  `ui.menu_opened` already gives `MistriMultiSaveSpace.gml`), aligned `RightOut` / `Middle` with a 6 px gap: the pattern the game
  uses for the checkbox next to its own "tools" text. It follows that text whatever its width, so there is no overlap at the
  smallest screen size and no font measuring. The button is a nine-slice node (`spr_ui_button`, 46 x 16) child of the label with
  a text child "Update", and a tap callback (`set_tap_callback`), switched on and off with `set_enabled`.
- **Fallback.** If the game's text node is not found for 5 seconds, a plain text slot (`MistriMultiHudText.gml`) at x = 112 shows
  the label and, if a release is newer, `(update 0.4.7 available)`, without a button. If the nodes cannot be built at all
  (`nine_slice` missing, any exception) the same fallback is used and one error is logged.
- **Clicks.** One command per click; nothing while a run is going, while the previous command is unanswered, without a newer
  release or without a live launcher. If the launcher does not start a run within 10 seconds the label says so
  (`The launcher did not answer...`) and the button comes back.
- **Guards.** The tick wraps everything in `try`; a failure drops the nodes (rebuilt next time), logs once and rate-limits after.
  Nodes are rebuilt when `ANCHOR` is replaced, the game's text node is freed or the title screen returns; ticks never create
  nodes twice.

## Tests

| Command | What it covers |
| --- | --- |
| `python3 tests/test_updateui.py` | versions (parse / compare / equal to the manifest), hostile or missing status fields, label and button states, click -> one command, every state's words, the 10 s give-up, stale results, click guards, title-only visibility, rebuilds, fallback, `nine_slice` failure, hostile status files, the in-world note, layout |
| `python3 tests/mutate_updateui.py` | breaks the GML in 16 places and requires a failing test for each |
| `tests/test_launcher_linux.py` (`test_update_*`, `test_release_check_*`) | the real Linux launcher with a stand-in update program and a fake release server (run in `unshare -n`): run states and their words, failures, silent and crashing programs, hostile result files, one at a time, cancel, no cancel while installing, busy while hosting, timeout, missing program, command fuzz; the daily check: newer / equal / older, remembered for a day, retry rules, opt-out, slow / dead / hostile / oversized servers, no curl, missing manifest, **the game starts at once** |
| `tests/test_launcher.py` (`test_update_*`, `test_release_check_*`, Wine) | the same for the Windows launcher with `build/fakeupdate.exe` (`tests/fakegame/fakeupdate.asm`: writes the result text of `fakeupdate.cfg`, sleeps, exits) and `build/fakecurl.exe` (`fakecurl.asm`, put in the prefix's System32 as `curl.exe`: writes `version 0.4.7` to the `-o` file and records its command line): run states, failures, cancel, timeout, busy, missing program, the remembered answer, opt-out, missing manifest, the exact curl arguments, the URL override |
| `python3 tests/mutate_updatelauncher.py` | breaks the shared launcher logic (`common/updatecore.inc`) and the Linux platform code in 12 places and requires the Linux tests to fail |

## Unverified assumptions (the real game was not available)

1. `TitleMenu.sha_text` is a field of the title menu instance that `ui.menu_opened` hands over, and it is set before the first tick
   that runs on the title screen (it is created in `setup_main_screen`, after the menu opens: the mod waits up to 5 s).
2. `ANCHOR.nine_slice(parent)`, `.set_sprites_from_key("spr_ui_button")`, `.set_size`, `.set_tap_callback(fn)`, `.set_enabled(bool)`,
   `Align.RightOut` are callable from the mod runtime (all appear in the game's own `TitleMenu.gml` / `Node.gml`); that a node
   made in the mod gets taps (the title screen's own input handling may swallow them: the game skips the title animation on
   `LeftMouse`; ours is a different node), and that a button inherits the title layer from its parent.
3. A disabled node (`set_enabled(false)`) is neither drawn nor tappable.
4. `spr_ui_button` nine-slices down to 46 x 16; if it looks wrong, change the size in `mistrimulti_updateui_build`.
5. The update program's result keys are `state`, `version`, `message`, `error` (`code` also accepted); the Linux program is
   `mistrimulti-manager update --result <file>`, the Windows one `MistriMulti.exe --update <file>` (as agreed with A).
6. `curl` exists: `curl` on `PATH` (Linux), `%SystemRoot%\System32\curl.exe` (Windows 10 1803+). Missing means no check, silently.
7. On a real Windows, `CreateProcessW` of a console program with `CREATE_NO_WINDOW` shows no window (under Wine nothing could be seen); the real
   `curl.exe` accepts the arguments the stand-in recorded and follows the GitHub redirect with `--proto-redir =https` (only Linux curl was tried, against a loopback server).
8. Under Proton the game command names a Windows path or the exe under the game folder: the installed version is read from
   the directory of the program named on the command line (`.../Fields of Mistria/FieldsOfMistria.exe`).

## In-game checklist (please walk through it once and report)

1. Title screen: right after `v1.0.8 (modified)` the text `MistriMulti 0.4.6` appears (same row, small gap, readable, not cut off), also at the smallest
   window size (480 x 270), also with the Steam Deck's resolution. Hold Ctrl (the game adds its sha to its text): note if they overlap.
2. Put a newer version in the release check on purpose (a fake `latest.txt` with `MISTRIMULTI_RELEASE_URL`, or delete `update_check.txt` after a release): the **Update**
   button appears next to the label within a few seconds of the title screen; it looks like a game button (hover highlight, pressed look) and is clickable with the mouse.
   Does it also work with the controller / Steam Deck touch screen? (Keyboard / gamepad focus is not wired: the button is not in the title menu's pilot.)
3. Click it: the label shows `Checking for updates...`, `Downloading ...`, then the end text; the button is gone during the run. On a failure the red text and the button come back.
4. Click it twice quickly: only one run. Start hosting and try: refused with `Update: stop hosting or joining first` (only possible from the log / a forced status, the button is on the title screen).
5. Load a world with a newer release known: the badge reads `... - update available (0.4.7)`; F8 says the same.
6. `update.cfg` with `check=off`: no request (check with a proxy log or `update_check.txt` not created), no button, the label stays.
7. Go offline: the game starts at the same speed, no error, no button.
8. After `Installed. Restart the game`: restart; the label shows the new version.

## Known limitations

- The button is not part of the title menu's gamepad navigation; mouse and touch only.
- Wall-clock stamps use UTC seconds from the system clock; a wrong clock only makes the check run more often or less often.
- The label's room is whatever is right of the game's text; if a very long game text (the sha with Ctrl) fills the row, they overlap while Ctrl is held.
- An update program started by the launcher is not killed when the game closes (it may be mid-install).
