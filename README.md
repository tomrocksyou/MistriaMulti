# MistriMulti

A Fields of Mistria multiplayer mod with a native x86-64 NASM networking helper.
The Windows helper calls Win32/Winsock; the Linux helper, launcher and manager use Linux syscalls. None of
them needs Python, .NET, Rust, a paid server, or a third-party multiplayer relay at runtime.
GML and MOMI/MMAPI provide the supported connection to the game.

## Current version: 0.1.0 experimental

The Windows game bridge has been tested with a simulated remote player.
The live test covers movement, drawing, room changes,
farm requests, conflict/authority checks, save guards and disconnect expiry.
See `docs/TESTING.md` for what these checks prove and what remains untested.

Implemented:

- Host and join over reachable IPv4/UDP, with one host and up to seven joining slots.
- Remote characters in the same location, with interpolated movement, facing, outfits,
  base animations, action animations, and tool attachments.
- Host-authoritative farm soil and watering updates, conflict correction, and bounded
  terrain snapshots for joining players, room transitions, and host day changes.
- Stop-and-wait acknowledged game events, retried by the helper, including appearance updates.
- Atomic game/helper file publication; bounded fragmentation and reassembly; replay rejection;
  one-second idle heartbeats; automatic helper shutdown from the Windows launcher.
- Guest character creation uses the game's customization menu and saves an independent profile.
- Profiles use a Steam ID when available, with a persistent local identity as fallback.
- Each hosted world stores separate player records for appearance, inventory, equipment,
  money, skill XP, perks, spells, friendship points and relationship status.
- Guests load their hosted-world record on reconnect. New guests start with the game's
  starter inventory and customize their character before publishing progress.
- F8 displays connection status in game.

This is not feature-complete co-op. Crops/harvests, shared containers and item transfers,
resource drops, buildings, animals, quests/unlocks, NPC schedules, time/weather, cutscenes,
mines/dungeon generation are **not synchronized** in this version. Personal quests,
recipe/cosmetic unlocks, romance cutscene history, marriage dates and children are not
included in the player records yet. Saving friendship points and relationship status
does not provide a complete multiplayer romance system.

Guests retain their local world's objects while the synchronized systems operate.
Their core character progress is checkpointed on the host about every five seconds;
the host confirms a complete record before it is considered saved. Guest local saves
are blocked during multiplayer. The host can save its farm normally. See
`docs/PLAYER-DATA.md` for storage, backup and recovery details.

## Windows: first setup

1. Install the supported game version and MOMI **0.16.5** (validated against game **1.0.6**).
2. Keep this project outside the game folder. `Build.bat` builds the ASM helper; a built
   Windows executable is also included under `build/` in the supplied project.
3. Run `Install-Mod.bat`. It copies **only this project's own mod** into your game's `mods/` folder.
4. Open MOMI, select **MistriMulti**, and click **Install**. Close the game during installation.
5. Everyone opens `MistriMulti.exe` (the manager window) once:
   - **Host a game**: one click. It shows the addresses to give your friends (your Tailscale IP, which starts with `100.`,
     and your local-network IP).
   - **Join a game...**: opens a list of hosts and **scans for them** when it opens; **Refresh** scans again. Select a host
     and press **Join selected**. The scan uses broadcast on your local network and the peer list of Tailscale (if it is
     installed); it does not sweep IP ranges. If your host is not listed, type its IP in the box and press **Join this IP**.
     Port, room code and player number are filled in for you (each friend needs a different player number, 1-7: change
     it in the box if two friends end up with the same one). A room code is only needed if the host chose one.
   - **Steam setup...**: copies the launch line (see step 6) to the clipboard.
   (Without the manager, double-clicking `MistriMultiLauncher.exe` or `Play.bat` asks the same questions in a console.)
6. **Click Play in Steam from now on.** One time only: in Steam, right-click the game, Properties, Launch Options,
   and paste the launch line (`"<folder>\MistriMultiLauncher.exe" --steam %command%`; the manager's **Steam setup...** button copies it). Steam then runs the
   launcher, which starts the network helper from your saved details and launches the game. If anything is wrong
   with the multiplayer setup the game still starts normally; the reason is written to
   `%LOCALAPPDATA%\FieldsOfMistria\mod_data\mistrimulti\launcher.log`.
7. A badge at the bottom right shows **Multiplayer Online** (green) or **Multiplayer Offline** (red: the game was
   updated past the versions this mod was tested on, the helper is not running, or setup was not done).
8. **Joining a friend downloads their world.** Pressing **Join selected** (and starting the game) copies the host's latest
   saved world to your PC. In the game choose **New Game**, then **Multiplayer**: you enter the host's world. The host should
   save (sleep) before friends join, because friends get the world as of the host's last save.
9. In the game choose **New Game** or **Load Game**, then **Singleplayer** or **Multiplayer**. Saves are labelled
   `[Single]` or `[Multi]` and are kept in separate folders. After a game update, add the new version to
   `mistrimulti_supported_versions()` in `MistriMultiStatus.gml` once you have tested the mod with it.

`MistriMultiLauncher.exe` and the helper must sit in the same folder. The mod installer (`Install-Mod.bat`) searches
Steam libraries for the game; pass `-GameDirectory` to `scripts\Install-Mod.ps1` to choose an installation explicitly.

Use a LAN or a private VPN such as Tailscale. Windows Firewall may ask once whether `mistrimulti-helper.exe` may use the network: allow it for the private network (and for Tailscale's adapter if it is listed as public). The default room code is not a password, so do not expose the host's port to the open Internet. Direct Internet connections need the host's
UDP port reachable; CGNAT can prevent direct hosting. The room code separates sessions,
and the checksum detects corruption; this protocol does **not** provide encryption or
cryptographic authentication. No firewall or router settings are changed automatically.

## Linux / Steam Deck

Linux has the same one-click-in-Steam flow as Windows, built from three native assembly programs (raw Linux system
calls, no C runtime, no Python). Keep them together in one folder, for example `~/mistrimulti`:

| Program | What it does |
| --- | --- |
| `mistrimulti-launcher` | The Steam launch wrapper (`--steam %command%`) and the `--configure` questions. Starts the helper, writes `control.json`, backs up your solo saves, runs the game, answers host discovery (UDP 7776) and serves the world (TCP 7775) while you host, and refreshes the host's world when you join. The game always starts, whatever fails. |
| `mistrimulti-manager` | Console version of the manager window: `host`, `join [IP]`, `scan`, `steam-setup`, `save-solo`. |
| `mistrimulti-helper-linux` | The network helper (unchanged). The launcher starts it and ties its life to its own. |

1. Install the GML mod through the Linux MOMI build (MOMI **0.16.5**, game **1.0.6**, same as Windows).
2. Build with `sh scripts/build-linux.sh` (needs `nasm` and `binutils`; the output is in `build/`), or take the
   `mistrimulti-linux-x64` artifact from CI. `chmod +x` the three programs.
3. **Host**: `./mistrimulti-manager host` shows the addresses (your Tailscale IP, your local-network IP) to give your friends.
   **Join**: `./mistrimulti-manager join` scans the local network (broadcast) and your Tailscale peers (`tailscale status --json`,
   if the `tailscale` command exists), lists the hosts, and joins the one you choose; `./mistrimulti-manager join 100.101.102.103`
   joins an address directly. The port, a player number (1-7, kept between runs) and the default room code are filled in for you;
   add `--player N`, `--room CODE` or `--port N` to change them. Joining also downloads the host's latest saved world.
   (`./mistrimulti-launcher --configure` asks the same questions as the Windows setup and writes the same `launcher.cfg`.)
4. **Once**, in Steam: right-click the game, Properties, Launch Options, and paste the line printed by
   `./mistrimulti-manager steam-setup`, which looks like
   `"/home/deck/mistrimulti/mistrimulti-launcher" --steam %command%`. Then click Play, as on Windows. It also works for the
   Proton (Windows build) version of the game, because `%command%` simply expands to Proton's command line.
5. The badge, the **New Game -> Multiplayer** flow, world download and save separation work exactly as in the Windows steps above.
   Why multiplayer did not start (if the game opened normally) is written to
   `<game folder>/mod_data/mistrimulti/launcher.log`; the helper's own messages are in `helper.log` next to it.
6. `./mistrimulti-manager save-solo` copies your solo saves to `~/Documents/MistriMulti Backups/<UTC time>/`
   (`$XDG_DOCUMENTS_DIR` and `user-dirs.dirs` are honoured). The launcher also keeps the newest 10 pre-launch backups
   in `mod_data/mistrimulti/solo_backups`. Backup folder names use UTC time on Linux.

**Where the game keeps its files.** The game stores everything under GameMaker's `game_save_id`, which the game's scripts do
not spell out for Linux. The Linux tools therefore use `MISTRIMULTI_DATA_DIR` if you set it, and otherwise take the first of
these that already holds a `saves` (or `mod_data`) folder: `$STEAM_COMPAT_DATA_PATH/pfx/drive_c/users/steamuser/AppData/Local/FieldsOfMistria`
(Steam sets this for Proton games), `${XDG_CONFIG_HOME:-~/.config}/FieldsOfMistria`, `${XDG_DATA_HOME:-~/.local/share}/FieldsOfMistria`,
and `steamapps/compatdata/*/pfx/.../AppData/Local/FieldsOfMistria` in the usual Steam libraries (Steam Deck with Proton).
If your game keeps its files elsewhere, set `MISTRIMULTI_DATA_DIR=<that folder>` (for the Steam launch option:
`MISTRIMULTI_DATA_DIR="/path" "/home/deck/mistrimulti/mistrimulti-launcher" --steam %command%`).

Steam Deck users: see [`docs/STEAM-DECK.md`](docs/STEAM-DECK.md) for the Desktop Mode walkthrough. The Linux launcher and
manager are tested natively with a fake game (`tests/test_launcher_linux.py`, `tests/test_world_linux.py`, run in CI);
the real game on a real Steam Deck has **not** been tested yet, see `docs/TESTING.md`.
`scripts/play-linux.sh` is the older manual way to run the helper without Steam; it still works.
Steam Input can map a controller button to F8 for the status notification.

## Build, test, learn

Windows needs NASM and Microsoft C++ Build Tools with MSVC x64/x86 and a Windows SDK:

```powershell
./scripts/Build.ps1                  # debug symbols for x64dbg
./scripts/Build.ps1 -Release         # compact executable
./scripts/Build.ps1 -Target Both     # Windows + WSL Ubuntu Linux linker
python tests/test_transport.py build/mistrimulti-helper.exe
python tests/test_packet_faults.py build/mistrimulti-helper.exe
```

For Linux, run the same Python tests with `build/mistrimulti-helper-linux` on Linux, plus the native launcher and
manager suites:

```sh
sh scripts/build-linux.sh
python3 tests/test_launcher_linux.py build/mistrimulti-launcher build/mistrimulti-helper-linux build/fakegame-linux build/mistrimulti-manager
python3 tests/test_world_linux.py build/mistrimulti-manager
```
Python is only used for developer tests. Both release binaries are native NASM code.
Open `build/mistrimulti-helper.exe` in x64dbg; break on `mistria_main`, `read_local_frame`,
`receive_fragment`, or `send_record`. Start with `docs/ASM-TOUR.md`.

Game bridge data lives under the game's configuration folder:
`mod_data/mistrimulti/control.json` and `mod_data/mistrimulti/bridge_<id>/`.
Each launcher owns its helper process; it never terminates another helper by process name.

MOMI preflight must use an **absolute** mod path. Relative paths can make its collector
report a misleading "no gml/ tree" result:

```powershell
& 'path\to\ModsOfMistriaInstaller-cli.exe' --lint 'C:\absolute\MistriMulti\mod\mistrimulti' 'C:\absolute\Fields of Mistria\assets.bak.zip' --strict-lints --compile-check require
```

Use the pristine game archive for this check: MOMI's `assets.bak.zip` after
installation, or the original unmodified `assets.zip` before installation.
Linting the already patched live archive reports duplicate seam markers.

## License and dependencies

Noncommercial use, modification and redistribution are allowed under `LICENSE`.
Commercial use of any part, including sale or incorporation into a commercial product
or service, requires prior written permission. Requests are considered individually;
see `CONTACT.md`.

Game assets, Steam libraries and MOMI are not bundled. Those dependencies retain their
own licenses. The Steam identity probes load the library from the installed game.

Appearance defaults are stored under `mod_data/mistrimulti/characters/`. Hosted-world
records and rosters live under `mod_data/mistrimulti/worlds/`. Steam IDs remain strings
to preserve all 64 bits.
The current UDP connection does not authenticate a remote Steam ID; authenticated
Steam sessions remain a separate requirement.
