# Testing MistriaMulti

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
python3 tests/test_engine_audit.py           # the game-identifier audit tool (docs/AUDIT-1.0.8.md); MISTRIA_GML=<dir> audits real scripts
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

## Trust checks (join authentication, identity binding, abuse limits)

```sh
python3 tests/test_trust.py build/mistrimulti-helper-linux      # re-runs itself in `unshare -n`; about 3 minutes
python3 tests/test_trust.py build/mistrimulti-helper.exe        # Windows, or Wine on Linux
python3 tests/test_trust_gml.py                                 # real MistriMultiTrust.gml, no ports
```

`tests/mmauth.py` is the reference implementation of the handshake (`docs/PROTOCOL.md`); it is the guest in front of the real host
helper and the host in front of the real guest helper. `test_trust.py` covers: joins with and without a password (and that neither
the password nor its hash crosses the wire); a wrong or missing password; slot hijack, stolen fingerprints and two slots for one
install; datagrams without a handshake and in the old unauthenticated format; replayed PROOFs and old-session packets; a bit flip
in every byte of a packet; identity keys (registration, known identity with garbage in the registration field, stable host
fingerprint, damaged and oversized key stores); the deny list (fingerprints, addresses, comments, junk, removal); rate limits
(snapshot bursts, a packet flood, a HELLO flood, reply sizes); 3 700 hostile datagrams including correctly tagged ones with
impossible headers; the guest side (missing and wrong passwords, a host without the right tag, RESYNC, a silent host);
`auth.cfg` parsing and absurd arguments. `test_trust_gml.py` covers binding, approval, refusal and bans, legacy records, uploads
from a slot that changed hands, bounded identities, a damaged `trust.json`, per-guest event limits (nothing lost, nobody starved),
host pinning on the guest, and 4 000 hostile event frames. `test_launcher*.py` check that `password=` reaches `auth.cfg` and the
real helper, and that an unusable one stops multiplayer.

What these do not prove: the game's real file reading of `auth_<slot>.json`, `trust.json` and `deny.txt`; the F7 / Shift+F7 hotkeys
and notifications; behaviour on a real network (NAT, MTU, packet loss during the handshake beyond the proxy tests). The manual
checklist is in `docs/SECURITY.md`.

## Progress checks

```sh
python3 tests/test_progress.py        # about 3 minutes
```

Runs the real `MistriMultiProgress.gml`, `MistriMultiPlayerSync.gml`, the storage half of `MistriMultiPlayerData.gml` and
`MistriMultiIdentity.gml` on the event layer, over the simulated helpers and network, with a fake game (the data
structures the game's own save code uses) and a fake file system that can fail. It covers: all ten progress sections
(capture, validate, restore, capture again is exact; the host's data is replaced), new-character defaults, 43 malformed
sections and records, migration (unknown sections, newer or damaged envelopes, a core-only record from before the feature),
readiness gating, delta uploads, returning guests in other slots and accounts, a crash between checkpoints, damaged,
foreign and newer records, an interrupted host write, refused and oversized sections, forged and replayed messages, the
flush, the host save commit and rollback (restarts, two generations, missing, damaged and foreign commits), the
one-partner-per-villager rule (race, break-up, host partner, restart, late joiner), a 134 KB record in blobs and a section
that fails to restore. The in-game checklist (what these tests cannot show) is in `docs/SYNC-PROGRESS.md`.

## Guest save checks

```sh
python3 tests/test_guestsave.py        # about 35 s
python3 tests/mutate_guestsave.py      # breaks the GML 27 ways, about 1 minute
```

Runs the real `MistriMultiGuestSave.gml` with the player-sync, progress and identity files (the harness of `tests/test_progress.py`):
the save veto, flush on a save attempt and on the Settings tab, the goodbye frame, rejoining through another slot, a host that
crashes, quits or restarts, short outages, the character export/import and the real save guard of `MistriMultiBoot.gml`
(`docs/SYNC-GUESTSAVE.md`).

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

## In-game menu checks (Host a game / Join a game)

Details and the in-game checklist: `docs/SYNC-MENU.md`.

```sh
python3 tests/test_menu.py                                                # GML menu + badge against a scripted fake launcher
unshare -n sh -c '<bring lo up>; python3 tests/test_menu.py build/mistrimulti-launcher build/mistrimulti-helper-linux build/fakegame-linux'
python3 tests/test_launcher_linux.py ...   # test_menu_*: standby, host/stop, scan and join, failures, command validation
python3 tests/test_launcher.py ...         # test_menu_*: the same for the Windows launcher under Wine
```

What the first one proves: every screen of the flow in order, input validation (addresses, rooms, passwords, injected lines),
plain-words errors for every code, Cancel / Escape / silent launcher / stuck download, a hostile `status.json`, the badge's
states, fallbacks and watchdog, and that popup or file failures reset the flow without an exception reaching the game. The second
adds the real Linux launcher, helper and a real host. What none of them prove: how the game draws and closes the popups, whether
`text_input_popup` and the localiser behave as read from the scripts, and the Windows launcher on real Windows (Wine only).
Run the tests that open ports inside `unshare -n` (private network namespace, `lo` up), as `runall.sh` does.

## Linux installer checks

`tests/test_install_linux.py` runs `install.sh` against a throwaway `HOME` containing a fake Steam tree (a symlinked
`~/.steam/steam`, `libraryfolders.vdf`, an appmanifest, one or two `userdata/<id>/config/localconfig.vdf` files) and dummy
program files, so it needs neither `nasm` nor Steam:

```sh
sh -n install.sh && python3 tests/test_install_linux.py
```

It covers: a fresh install (programs, launch option, backup, mod copy, summary text), an app block with and without an
existing `LaunchOptions`, running twice (nothing changes, the first backup is kept), an existing launch option (declined, no
answer, accepted), Steam "running" (`MISTRIMULTI_STEAM_RUNNING=1`: no edit, line printed), a missing appmanifest, two Steam
users and a second library folder, `--uninstall` (refused while Steam runs; restores the backups; only clears our own line if
Steam changed the file since), `--dry-run` (nothing written), `MISTRIMULTI_DIR` with a space in the path, missing build tools
(exactly one `sudo apt-get install` line) and a foreign mod already in the mods folder. Not covered: a real `localconfig.vdf`
written by a real Steam, the real mods folder, and the real process check for Steam.

## World transfer checks

The world download needs the join session's key (`docs/PROTOCOL.md`, `docs/SECURITY.md`). `tests/test_world.py` (Wine) and
`tests/test_world_linux.py` (native) run the download client (`MistriMulti.exe` / `mistrimulti-manager --fetch <ip> <folder>
<result file> [<bridge folder> <slot>]`) against a fake host that plays the server side with the reference code in
`tests/mmauth.py` (shared cases: `tests/worldclient_cases.py`): an intact 300 KB transfer after the proof, a fresh proof for every
connection, no key / zero key / short key file (code 7 without connecting), a wrong key (the host refuses, nothing is written),
an impostor host (random, missing, replayed or wrong-slot reply tag, an edited status) never believed, old hosts and junk
(code 7, no hang), a wrong checksum (nothing replaced, no partial file), unsafe file names, "no world", truncated, oversized
and empty replies, an absent host and a host that stalls. `tests/test_launcher.py` and `tests/test_launcher_linux.py` check the
real host (shared cases: `tests/worldserver_cases.py`, three hosting sessions because the cases that wait for timeouts are
slow): the newest valid save goes only to a client with a live session key (two players, two keys), wrong, foreign, missing,
zero, short and malformed credentials and slots 0 / 8 / 255 get one refusal and no world, a recorded request and proof is useless
on a new connection, only the challenge is sent before the proof, an old version-1 request is refused at once, junk and truncated
requests get nothing, a rotated or wiped key stops working immediately, "no world" is signed too; and a joining launcher (a
scripted host in front of the real guest helper, `JoinedHost`) downloads the world as the game starts without being delayed by
an unreachable or silent host. `tests/test_trust.py` (`test_world_key`, `test_world_key_wiped`, `test_guest_world_key`) checks
that both helpers publish `world_<slot>.key` = HMAC(session key, "MMWORLD1"), only for authenticated sessions, and wipe it when
the session ends; `tests/test_menu.py` shows the whole chain with the real launcher and helper on both sides.

## Container and item checks

`python3 tests/test_containers.py` (about 40 s, no ports) runs the real chest/drop GML on the event layer with the engine
stubbed: simultaneous takes, stale replicas, 21 hostile requests, a guest cut off mid-transaction, host restart with a
request in flight (never applied twice), snapshots, drop/claim races under loss, day change, gifts, per-player shipping
bins, seeded loot and randomised item-conservation runs.

## Farm checks

`python3 tests/test_farm_sync.py` (about 5 minutes) runs the real farm-object GML on the event layer at 5-10% loss: join,
host changes and day change, guest harvest races (exactly one yield), tool swings, edits, conflicts, rejoin and hostile input.

## Building interior checks

`python3 tests/test_buildings.py` (about 3 minutes) runs the farm, soil and water GML for the inside of a greenhouse and a barn
whose `dyn_index` differs in one guest (identity, join, guest harvest/plant/charge/tool, walking in, an unknown building,
soil and water, hostile input); `test_ranch.py` and `test_containers.py` have the furniture, machine and chest scenarios inside a
barn. `python3 tests/mutate_buildings.py` breaks 16 rules and fails if any test still passes. See `docs/SYNC-BUILDINGS.md`.

## Mines checks

`python3 tests/test_dungeon.py` (about 20 s, no ports) runs the real mines GML on the event layer: one run seed for the
itinerary and floors, the floor record and reconciliation, simultaneous kills (one killer, one drop set), pooled monster
health and venom, rocks, chests and dig sites claimed once, one ladder, floors apart, leave and rejoin, host away and host
restart, joins during fights, 15-25 % loss and a partition, hostile data. `python3 tests/mutate_dungeon.py` breaks the GML in 21
ways and fails if any test still passes.

## Ranch checks

`python3 tests/test_ranch.py` runs the real animal, pet, building and home GML on the event layer (19 scenarios: paid
adopt/sell/buy requests answered once, refunds, pooled barn products, snapshots, host restart, hostile data).
`python3 tests/mutate_ranch.py` breaks the GML in 12 ways and fails if any test still passes.

## Story checks

`python3 tests/test_story.py` (about two minutes) runs the real story, villager and cutscene GML on the event layer (52 scenarios: steps
by host and guest, three players taking one step, world and private cutscenes, late join, rejoin, host restart with claims in
flight, a cutscene holding only its own game, 100 steps through a full send queue, hostile input, the villagers' day plan, and
the story scenes that every player watches themselves: any order, loss, restarts, late join, safe fall-backs).
`python3 tests/mutate_story.py` breaks the GML in 44 ways and `python3 tests/mutate_story_views.py` breaks the shared-scenes part in
29; both fail if any test still passes. See `docs/SYNC-STORY.md`.

`python3 tests/test_maplive.py` (seconds) runs the real map-marker GML against a model of the game's MapMenu: live marker updates, rebuild only on change, other locations, closing, hostile peers. The remote hit shake is `test_hit_shake` in `tests/test_farm_sync.py`. See `docs/SYNC-MAPLIVE.md`.

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
2. Set the Steam launch option once (`docs/SYNC-MENU.md`), click Play in Steam, choose New Game, Multiplayer, Host a game, Start hosting, Start playing, and enter a test world on the farm. The room code is the default `4d495354` unless you started the host from an older `launcher.cfg` with another one.
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

## Feature suites

`scripts/runall.sh` covers the native components. The GML feature suites (the engine is
stubbed, no game and no build are needed) run with:

```sh
sh scripts/run-features.sh
```

The script re-runs itself in a private network namespace (`unshare -n`, loopback brought
up) and runs `test_containers`, `test_ranch`, `test_progress`, `test_farm_sync`,
`test_wallet`, `test_dungeon`, `test_story`, `test_buildings`, `test_guestsave`,
`test_devtools`, `test_maplive`, `test_menu` (GML parts), `test_trust_gml`,
`test_event_features`, `test_event_layer` and `test_engine_audit` (without the real game
scripts), printing PASS or FAIL with the time of each and exiting non-zero on any failure.
