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

MOMI 0.16.5 strict compilation checks passed for mod version 0.1.0 on game 1.0.6.
With version 0.1.0 (the stop-and-wait event queue), the actual Windows game also passed
`tests/test_live_game.py` using a second, real ASM helper on loopback and a simulated game
client. Version 0.2.0 replaces that queue with the event layer; the live tests were ported to
it but **have not yet been run against the game, and the MOMI compilation check has not been
repeated**:

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

## Event layer checks

The event layer (`docs/EVENT-LAYER.md`) is checked three ways, all on Linux (and Windows) without the game:

```sh
python3 tests/test_event_layer.py            # about 4 minutes; --quick runs the Python model only
python3 tests/test_event_features.py
python3 tests/test_event_bridge.py build/mistrimulti-helper-linux    # --guests 7 for eight players
python3 tests/test_event_bridge.py build/mistrimulti-helper.exe      # Windows helper (under Wine on Linux)
```

- `test_event_layer.py` runs the reference model (`tests/event_model.py`) and
  `mod/mistrimulti/gml/MistriMultiEvents.gml` itself, executed by a small GML interpreter
  (`tests/gml_subset.py`), separately and mixed in one session. They run over a simulated helper
  and network (`tests/event_sim.py`) with loss, duplication, reordering, 10 s expiry, reconnects,
  host restart, world re-entry, slot reuse, back-pressure, stalled handlers and 256 KB blobs, for
  up to eight players. Every run checks ordered exactly-once delivery, requests applied and
  answered exactly once, exact blobs, drained queues and 16 KB frames. A lockstep test requires the
  model and the GML to publish byte-identical frames on every tick. The interpreter also parses
  every mod file, and it is stricter than GameMaker about unset fields, string arithmetic and
  undeclared variables.
- `test_event_features.py` runs the real terrain and player-sync GML on the event layer with the
  engine stubbed: requests applied once, conflicts corrected, invalid and out-of-reach requests
  rejected, snapshots on rejoin, exact record upload, restore after re-entry, duplicate identities
  refused.
- `test_event_bridge.py` drives the real native helpers through the real file bridge, with the
  model as each player's game, one guest behind a proxy that drops, duplicates and reorders
  datagrams. It covers steady traffic with 100 KB blobs, a guest helper killed long enough to
  expire, and a host restart.

What these do not prove: that GameMaker executes the GML exactly as the interpreter does (for
example `json_parse` number types, `json_stringify` key order, or array copy-on-write), game frame
time with a full window, and anything about the real hooks, menus or saves. `test_live_game.py` and
`test_player_data.py` (below) speak the new protocol through the same model but need the real game.

## Updater checks

`tests/test_updater.py` runs the assembly manager against a local HTTP server (under Wine with xvfb on Linux, directly on
Windows). It always runs a COPY of the exe from a temporary folder, because the manager installs the tools next to itself.
Build with `sh scripts/build-updater.sh` (and `sh scripts/build-launcher.sh` for `fakegame.exe`, which stands in for MOMI):

```sh
python3 tests/test_updater.py build/MistriMulti.exe build/fakegame.exe
```

- Mod: update detection, verified download and install, "up to date" afterwards, only changed files downloaded,
  fresh install, bad checksum (nothing installed, no staged files), Save Solo into Documents.
- Tools (launcher, helper, probe) and self-update: a stale tool is reported even when the mod version is equal; the running
  `MistriMulti.exe` is renamed to `.old`, the new build is verified, runs, and removes the `.old` at its next start;
  leftover `.old`/`.new` files of our tools are deleted at start and foreign files are not.
- Failure paths: a blocked staging file (nothing changes); a replacement that fails after the manager and the launcher were
  already replaced (everything is put back and the original exe still works); a mod replacement that fails (files and
  `manifest.toml` version unchanged, because the manifest is installed last).
- Versions: numeric comparison (`0.10.0` is newer than `0.9.0`, `0.2` equals `0.2.0`), an unreadable installed version is
  updated, and a newer installed version than the published one is reported as such and never touched.
- Hostile lists (about 65 cases, all rejected whole, with the list as the only request made): `..`, absolute and drive paths,
  backslashes, streams, other roots, tool names outside the whitelist, hidden names, trailing dots, Windows device names,
  8.3 names, non-ASCII, bad or upper-case hashes, duplicates, a missing/wrong footer, lists cut at a line or in a line,
  content after the footer, bad versions, a missing `manifest.toml`, too many files, an oversized list; comments, blank
  lines and CRLF are accepted.
- Hostile downloads: wrong content for a tool, the manager or a mod file, a truncated download, a 2 MB and a 1 MiB + 1 file,
  a 404, an empty body: nothing is installed and no `.new` file remains.
- `MistriMulti.exe --urls <version> <file>` prints the production server and URL path for the list, a mod file and a tool
  (no network), so the GitHub URLs are checked exactly.
- Open MOMI: not found, the command-line program refused, started with no arguments, the saved choice, a vanished saved path.

Regenerate the committed mod list with `sh scripts/make-release.sh` whenever the mod changes; CI fails when
`release/latest.txt` is stale. The complete list with the tools (`make-release.sh --bin <dir> <file>`) is built by the
release workflow, see `docs/RELEASES.md`. The suite takes a few minutes (one Wine start per case). Not tested: the real
GitHub servers (the repository is private, and redirects from `github.com` release downloads go through GitHub's CDN) and
the real MOMI.

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

## Container and item checks

`python3 tests/test_containers.py` (about 40 s, no ports) runs the real chest/drop GML on the event layer with the engine
stubbed: simultaneous takes, stale replicas, 21 hostile requests, a guest cut off mid-transaction, host restart with a
request in flight (never applied twice), snapshots, drop/claim races under loss, day change, gifts, per-player shipping
bins, seeded loot and randomised item-conservation runs.

## Ranch checks

`python3 tests/test_ranch.py` runs the real animal, pet, building and home GML on the event layer (19 scenarios: paid
adopt/sell/buy requests answered once, refunds, pooled barn products, snapshots, host restart, hostile data).
`python3 tests/mutate_ranch.py` breaks the GML in 12 ways and fails if any test still passes.

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

The live test checks native host checkpoints, interrupted uploads (every blob chunk but
the last), exact records, invalid-input rejection, reconnects in another slot, separate player/world
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
