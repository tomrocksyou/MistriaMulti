# Testing MistriMulti

## Validation coverage

Windows and Ubuntu/WSL native ASM transport tests pass:

- Three-player host forwarding and Unicode bridge paths.
- Exact reassembly of 15 KB snapshots.
- Packet loss, reordering, duplicates, corruption and replay rejection.
- Wrong-source and oversized-payload rejection.
- Sequence recovery after a helper restart.
- Approximately one snapshot per second when idle.
- A local heartbeat that advances even when player state is unchanged.
- Graceful helper shutdown.

MOMI 0.16.5 strict compilation checks pass for the mod on game 1.0.6.
The actual Windows game also passes `tests/test_live_game.py` using a second,
real ASM helper on loopback and a simulated game client:

- Creates the remote character and executes its real draw callback.
- Interpolates position and changes walking animation and facing.
- Removes the character when rooms differ and recreates it on re-entry.
- Streams acknowledged farm snapshots.
- Accepts soil/water requests on the host's farm.
- Corrects conflicting client predictions to the host's state.
- Rejects a guest's host-only terrain commit and out-of-reach requests.
- Blocks the guest save guard after replicated terrain changes; permits the host guard.
- Removes the character after its helper disconnects and expires.
- Restores the empty test tile afterward.

These checks do not replace testing two actual game clients, real local hoe
and watering-can actions in both directions, WAN/VPN conditions, or a native
Steam Deck game session. The save test invokes the real registered guard;
it does not force a save or advance the day. Unsynchronized gameplay listed
in `README.md` remains outside the current prototype.

## Updater checks

`tests/test_updater.py` runs the assembly updater against a local HTTP server (under Wine with xvfb on Linux, directly on
Windows): update detection, verified download and install, rejection of a file with a bad checksum (nothing installed,
no staged files left), "up to date" afterwards, and the Save Solo backup into Documents. Build with
`sh scripts/build-updater.sh`. Regenerate the published file list with `sh scripts/make-release.sh` whenever the mod
changes; CI fails when `release/latest.txt` is stale.

## Launcher checks

`tests/test_launcher.py` runs `MistriMultiLauncher.exe` against a fake game under Wine (or directly on Windows):
helper start and cleanup, `control.json` lifecycle, exit code and argument pass-through, stable identity, the rolling
solo-save backup (newest 10 kept, foreign folders untouched), every invalid-configuration fallback (the game must always
start), `--mistrimulti-direct`, wrong executables, the `--configure` prompts, 24 fuzzed configuration files and the helper
being stopped when the launcher is killed, the host's discovery responder (valid 64-byte queries only) and the manager's scan
(`MistriMulti.exe --scan <file>`, with `MISTRIMULTI_SCAN_EXTRA=<ip>` adding a target) against both a fake host and the real
launcher. Build with `sh scripts/build-launcher.sh` and `sh scripts/build-updater.sh`. `python3 scripts/lint-asm.py .`
rejects `[label+register]` addresses, which crash 64-bit Windows programs.

## Linux launcher and manager checks

`tests/test_launcher_linux.py` runs the native Linux `mistrimulti-launcher` and `mistrimulti-manager` against a fake game
(`tests/fakegame/fakegame_linux.asm`, an ELF written in assembly) with no Wine and no display. It needs only the build from
`sh scripts/build-linux.sh`:

```sh
python3 tests/test_launcher_linux.py build/mistrimulti-launcher build/mistrimulti-helper-linux build/fakegame-linux build/mistrimulti-manager
python3 tests/test_world_linux.py build/mistrimulti-manager
```

It ports every case of the Windows suite: helper start and cleanup, `control.json` lifecycle, the helper's exact command line,
exit-code pass-through (including a game killed by a signal and SIGTERM/SIGINT sent to the launcher), the stable identity (plus a
fake Steam identity probe that prints rubbish, hangs or fails), the rolling backup (newest 10 kept, foreign folders untouched),
every invalid-configuration fallback including a missing, non-executable or instantly exiting helper and an unknown game folder,
`--mistrimulti-direct`, other programs, Proton style and `PATH` game commands, the `--configure` prompts, 40 fuzzed
configuration files, the helper dying with the launcher (`PR_SET_PDEATHSIG`), the discovery responder (valid 64-byte queries
only), the world server (newest valid save, SHA-256, junk requests, a client that resets the connection, a silent client) and the
download client against it (seven sizes up to 5 MB), the backup folder date arithmetic against Python's `gmtime`, a guest refreshing the world at start, the manager's scan with a fake host and a
fake `tailscale`, `host`, `join` (by IP, interactive, every bad input), `steam-setup` and `save-solo`, and how the game folder
is found (`~/.config`, `XDG_CONFIG_HOME`, Steam `compatdata`, `STEAM_COMPAT_DATA_PATH`) including the Proton `C:/...` bridge path.
`tests/test_world_linux.py` is the native twin of `tests/test_world.py` (the same cases against the manager's `--fetch`).
The tests use fixed ports 7775/7776 (the protocol's discovery and world ports), so run one suite at a time; inside a private
network namespace (`unshare -n`, loopback up) several can run side by side. `ONLY=test_host,test_fuzz python3 tests/test_launcher_linux.py ...` runs just those tests.

Not covered: the real game on a real Steam Deck, the real Linux or Proton game's save folder, a real Steam identity probe,
and the real Tailscale output. Those need a device.

## World transfer checks

`tests/test_world.py` runs the download client (`MistriMulti.exe --fetch <ip> <folder> <result file>`) against a fake host:
an intact 300 KB transfer, a wrong checksum (nothing replaced, no partial file), unsafe file names, "no world", truncated,
oversized, empty and junk replies, an absent host and a host that stalls. `tests/test_launcher.py` additionally checks the
real host: it sends the newest valid save with a correct checksum, ignores look-alike files, drops malformed requests and
answers "no world" when there is nothing; and a joining launcher downloads the world as the game starts without being
delayed by an unreachable host.

## Transport checks

From the project folder on Windows:

```powershell
python tests/test_transport.py build/mistrimulti-helper.exe
python tests/test_packet_faults.py build/mistrimulti-helper.exe
```

On Linux use the same Python test scripts with `build/mistrimulti-helper-linux`.
Python is only a developer test dependency. Players run the native helpers.

## Opt-in live game checks

Use an expendable test world. Disconnect other players before running this
test; it occupies player slot 1 and temporarily changes one empty farm tile.
It restores that tile in cleanup and never saves the game. Keep the game open
until the test has finished.

1. Close the game. Enable the MMAPI debug agent by adding `"debug_enabled": true`
   to `%LOCALAPPDATA%/FieldsOfMistria/mod_data/mmapi/mmapi.json`. Preserve any
   other existing settings. A new file can contain `{ "debug_enabled": true }`.
2. Run `Play.bat` and choose host, note its room code, set the Steam launch option, click Play in Steam and enter a test world on the farm.
3. Run:

```powershell
python tests/test_live_game.py --room-code YOUR_EIGHT_HEX_DIGIT_CODE
```

For a different host port add `--port 7777`; for another game data folder use
`--data-dir`. Read the PASS output. A passing test leaves the original terrain
restored and the fake player disconnected.

After testing, close the game and set `"debug_enabled": false` for normal play.
Debug functions are registered only when the agent is enabled during mod
initialization. No debugger is needed to play. The F8 status hotkey overlaps
with MMAPI's snapshot toggle while its developer agent is enabled.

## Player record checks

Host a disposable test world with the MMAPI debug agent enabled and other players
disconnected, then run:

```powershell
python tests/test_player_data.py --room-code YOUR_EIGHT_HEX_DIGIT_CODE
```

The live test checks native host checkpoints, interrupted uploads, exact multipart
records, invalid-input rejection, reconnects in another slot, separate player/world
records, backup recovery and native character restoration. It disables achievements
during temporary character changes, restores the character and settings, and removes
its temporary player records.

The Windows guest flow has also been tested against a simulated host: first creation
publishes a record, changes wait for host save confirmation, and a host restart
handshake restores the saved guest without reopening creation. A two-computer playtest
with actual game clients remains necessary.

## Guest character checks

With the debug agent enabled, start a guest test world, finish the character
creator and connect a host in the same room. Run:

```powershell
python tests/test_guest_character.py
```

This compares the active character with its identity-specific saved profile
and checks that the remote character stays opaque. Add `--reopen` to check
the creator's saved appearance and its Continue action interactively.

## Assembly debugging

Build with `Build.bat` for Windows debug symbols. Use x64dbg on the helper;
`mistria_main`, `read_local_frame`, `receive_fragment`, and `send_record` are
useful breakpoints. `docs/ASM-TOUR.md` explains the source and calling convention.

The helper working set observed during this test was about 5 MB on Windows,
including operating-system libraries. That is one observation, not a memory
or CPU guarantee. The protocol stores bounded per-player buffers and avoids
resending unchanged state at the full game frame rate.
