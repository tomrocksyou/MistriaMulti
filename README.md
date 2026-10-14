# MistriMulti

A Fields of Mistria multiplayer mod with a native x86-64 NASM networking helper.
The Windows helper calls Win32/Winsock; the Linux helper, launcher and manager use Linux syscalls. None of
them needs Python, .NET, Rust, a paid server, or a third-party multiplayer relay at runtime.
GML and MOMI/MMAPI provide the supported connection to the game.

## Current version: 0.2.5 experimental

0.2.0 replaces the one-at-a-time event queue with the event layer (`docs/EVENT-LAYER.md`). Every player
must run the same version; 0.1.0 and 0.2.0 games do not see each other's updates.

With 0.1.0, the Windows game bridge was tested with a simulated remote player.
The live test covers movement, drawing, room changes,
farm requests, conflict/authority checks, save guards and disconnect expiry.
The 0.2.0 event layer is tested against the real helpers and file bridge, but not yet in the game.
See `docs/TESTING.md` for what these checks prove and what remains untested.

Implemented:

- Host and join over reachable IPv4/UDP, with one host and up to seven joining slots.
- Remote characters in the same location, with interpolated movement, facing, outfits,
  base animations, action animations, and tool attachments.
- Host-authoritative farm soil and watering updates, conflict correction, and bounded
  terrain snapshots for joining players, room transitions, and host day changes.
- Host-authoritative farm objects (crops, trees, rocks, forageables, dig sites, weeds, fences, sprinklers): harvests,
  chops and digs are decided by the host and yield to the player who acted; growth and spawns follow the host
  (`docs/SYNC-FARM.md`, untested in the game).
- An event layer for synced features: batched, ordered, acknowledged events per player, blobs up to
  256 KB delivered whole, and host-authoritative requests applied exactly once (`docs/EVENT-LAYER.md`,
  which includes the guide for adding a synced feature). Appearance, farm terrain and player records use it.
- Ranch sync (written against the game's scripts, not yet run in the game): animals, the farm pet, barn products, furniture,
  blueprints, new buildings, floors/wallpapers, apiaries and terrariums, farm expansion and house upgrades are host-owned;
  guests pay only when the host agrees (`docs/SYNC-RANCH.md`).
- Atomic game/helper file publication; bounded fragmentation and reassembly; replay rejection;
  one-second idle heartbeats; automatic helper shutdown from the Windows launcher.
- Guest character creation uses the game's customization menu and saves an independent profile.
- Profiles use a Steam ID when available, with a persistent local identity as fallback. Joining is authenticated: an optional host
  password, per-install keys, tagged packets, identity binding with host approval (F7), a ban list and per-player rate limits
  (`docs/SECURITY.md`; the room code is not a password).
- Each hosted world stores separate player records for appearance, inventory, equipment,
  money, skill XP, perks, spells, friendship points and relationship status.
- Guests load their hosted-world record on reconnect. New guests start with the game's
  starter inventory and customize their character before publishing progress.
- Host-owned chests, items on the ground and F9 gifts that never duplicate or lose items
  (`docs/SYNC-CONTAINERS.md`, experimental and not yet run in the game).
- One shared gold pool for the whole world, owned by the host, and shared shipping bins sold once by the host
  (`docs/SYNC-WALLET.md`, not yet run in the game).
- Per-player progress (recipes, almanac, mail, personal quests, romance and children, cosmetics, counters) is stored on the host
  beside each player's record, committed with the host's save, and one villager can be romanced by one player at a time
  (`docs/SYNC-PROGRESS.md`).
- A guest's game never saves (its character lives on the host); a save attempt or opening the settings menu sends the character
  to the host, a lost or closed host returns the guest to the title screen with a message (`docs/SYNC-GUESTSAVE.md`).
- **Everything is chosen in the game**: after the install you only start the game from Steam. New Game or Load Game, then
  Multiplayer, then **Host a game** (shows the addresses to give friends) or **Join a game** (finds hosts, asks for a password,
  downloads the host's world). No host/join step to run first (`docs/SYNC-MENU.md`; not yet run in the real game).
- F8 displays connection status in game.
- Host-owned time, date and weather; the day ends once every player is asleep (`docs/SYNC-CLOCK.md`, not yet tried in the game).
- Mines: one shared run (same itinerary and floors for everyone), host-owned monster health with one kill and one drop set, and shared rocks, chests and ladders (`docs/SYNC-DUNGEON.md`, not yet run in the game).
- World story (story quests, the cutscenes and facts that open the map), villager schedules steered by the host, cutscenes as private
  viewings, festivals as a function of the shared date (`docs/SYNC-STORY.md`, not yet tried in the game).

This is not feature-complete co-op. Not shared: monster movement in the mines (each player sees their own copy; health and
kills are shared), the seal and boss rooms, villagers' exact paths and seats (room and activity agree), and story rewards
for players who did not do the step. Everything listed above was written against the game's scripts and tested only against
a stand-in game; none of it has been confirmed in the real game yet.

Guests retain their local world's objects while the synchronized systems operate.
Their core character progress is checkpointed on the host about every five seconds;
the host confirms a complete record before it is considered saved. Guest local saves
are blocked during multiplayer. The host can save its farm normally. See
`docs/PLAYER-DATA.md` for storage, backup and recovery details.

## Windows: first setup

1. Install the supported game version and MOMI **0.16.5** (validated against game **1.0.6**).
2. Keep this project outside the game folder. `Build.bat` builds the ASM helper; a built
   Windows executable is also included under `build/` in the supplied project.
3. Get the mod into the game's `mods/` folder with the manager (`MistriMulti.exe`: **Check for updates**, then **Update**), or, when
   building from source, with `Install-Mod.bat`. Both copy **only this project's own mod**.
4. Open MOMI, select **MistriMulti**, and click **Install** (the manager's **Open MOMI** button opens MOMI and lists these
   steps; it asks you once where MOMI is). Close the game during installation. MistriMulti cannot press MOMI's Install for
   you: see `docs/RELEASES.md` for why.
5. **Once**, in Steam: right-click the game, Properties, Launch Options, and paste the launch line
   (`"<folder>\MistriMultiLauncher.exe" --steam %command%`; the manager's **Steam setup...** button copies it to the clipboard).
   That is the only setup. Nobody has to choose "host" or "join" outside the game any more.
6. **Click Play in Steam.** Steam runs the launcher, which waits quietly (no helper, no open port) and starts the game. If
   anything is wrong the game still starts normally; the reason is written to
   `%LOCALAPPDATA%\FieldsOfMistria\mod_data\mistrimulti\launcher.log`.
7. In the game choose **New Game** or **Load Game**, then **Multiplayer**, then:
   - **Host a game**: **Start hosting** (optionally **Set a password** first). The game shows the addresses to give your friends
     (your Tailscale IP, which starts with `100.`, and your local-network IP), then **Start playing**. Hosts answer scans only
     while they host.
   - **Join a game**: the game scans your local network (broadcast) and your Tailscale peers (if installed) and lists the hosts
     found (`[password]` marks hosts that need one); pick one, type the password if asked, and the game downloads the host's
     latest saved world and opens it. **Refresh** scans again; **Type an address** joins an IP that is not listed. The player
     number is chosen for you.
   The host should save (sleep) before friends join, because friends get the world as of the host's last save.
8. A badge at the bottom right shows **Multiplayer: Online** (green), **Idle** (amber: ready, nothing hosted or joined) or
   **Offline** (red, with the reason: the game was updated past the versions this mod was tested on, the launcher is not
   running because the game was not started through the Steam launch option, the helper program is missing...). F8 shows the
   same text with the reason.
   (`MistriMulti.exe`'s **Host a game** / **Join a game...** buttons, `Play.bat` and `MistriMultiLauncher.exe --configure` still
   exist as optional advanced tools: they pre-set a role in `launcher.cfg` that then starts by itself. The in-game menu replaces
   them for normal use.)
9. Choosing **Singleplayer** or **Multiplayer** in the game keeps the saves apart: they are labelled
   `[Single]` or `[Multi]` and are kept in separate folders. After a game update, add the new version to
   `mistrimulti_supported_versions()` in `MistriMultiStatus.gml` once you have tested the mod with it.

**Updates.** The manager's **Check for updates** / **Update** buttons update everything: the mod files under the game's
`mods/mistrimulti/` and the programs that sit next to `MistriMulti.exe` (`MistriMulti.exe` itself, `MistriMultiLauncher.exe`,
`mistrimulti-helper.exe`, `mistrimulti-steam-id.exe`). Only files that differ are downloaded. Every file is checked against
the SHA-256 in the release list before anything is installed; nothing is installed unless all of them pass, and a failed
replacement puts every file back. The manager replaces itself by renaming the running copy to `MistriMulti.exe.old` (removed
at the next start): close it and open it again afterwards. A newer installed version than the published one is never
"updated". After a mod update, open MOMI and click Install. The first copy of a manager older than this feature cannot update
itself: download `MistriMulti.exe` from the latest release once. How releases are published: `docs/RELEASES.md`.

`MistriMultiLauncher.exe` and the helper must sit in the same folder. The mod installer (`Install-Mod.bat`) searches
Steam libraries for the game; pass `-GameDirectory` to `scripts\Install-Mod.ps1` to choose an installation explicitly.

Use a LAN or a private VPN such as Tailscale. Windows Firewall may ask once whether `mistrimulti-helper.exe` may use the network: allow it for the private network (and for Tailscale's adapter if it is listed as public). The default room code is not a password, so do not expose the host's port to the open Internet. Direct Internet connections need the host's
UDP port reachable; CGNAT can prevent direct hosting. The room code separates sessions,
and the checksum detects corruption; this protocol does **not** provide encryption or
cryptographic authentication. No firewall or router settings are changed automatically.

## Linux / Steam Deck

**Quick start: close Steam, then run `./install.sh`** from the project folder (Debian/Ubuntu/Steam Deck desktop mode). It builds or
finds the programs, copies them to `~/.local/share/mistrimulti`, sets Steam's launch option for Fields of Mistria (with a backup),
copies the mod into the game's `mods` folder and prints the remaining MOMI step. `--dry-run` previews, `--uninstall` undoes it,
`--yes` lets it run the one `sudo apt-get install -y nasm binutils` it may need. The manual steps below are what it automates.

Linux has the same one-click-in-Steam flow as Windows, built from three native assembly programs (raw Linux system
calls, no C runtime, no Python). Keep them together in one folder, for example `~/mistrimulti`:

| Program | What it does |
| --- | --- |
| `mistrimulti-launcher` | The Steam launch wrapper (`--steam %command%`). It always starts in standby (nothing hosted or joined, no port open) and does what the in-game Multiplayer menu asks: hosts (starts the helper, answers host discovery on UDP 7776, serves the world on TCP 7775), scans, joins and downloads the host's world. It also backs up your solo saves and runs the game; the game always starts, whatever fails. A saved `launcher.cfg` (optional) still starts its role by itself. `--configure` asks the optional pre-set questions. |
| `mistrimulti-manager` | Optional console tools: `host`, `join [IP]`, `scan`, `steam-setup`, `save-solo`. |
| `mistrimulti-helper-linux` | The network helper (unchanged). The launcher starts it and ties its life to its own. |

1. Install the GML mod through the Linux MOMI build (MOMI **0.16.5**, game **1.0.6**, same as Windows).
2. Build with `sh scripts/build-linux.sh` (needs `nasm` and `binutils`; the output is in `build/`), or take the
   `mistrimulti-linux-x64` artifact from CI. `chmod +x` the three programs.
3. **Once**, in Steam (`./install.sh` does this for you): right-click the game, Properties, Launch Options, and paste the line
   printed by `./mistrimulti-manager steam-setup`, which looks like
   `"/home/deck/mistrimulti/mistrimulti-launcher" --steam %command%`. It also works for the Proton (Windows build) version of
   the game, because `%command%` simply expands to Proton's command line.
4. **Click Play in Steam.** There is nothing to run before the game. In the game choose New Game or Load Game, then
   **Multiplayer**, then **Host a game** (shows the Tailscale and local-network addresses to give your friends) or
   **Join a game** (scans the local network and your Tailscale peers, lists the hosts, asks for a password if the host set one,
   downloads the host's world and opens it; you can also type an address). See `docs/SYNC-MENU.md`.
   (Optional and advanced: `./mistrimulti-manager host` / `join [IP]` and `./mistrimulti-launcher --configure` pre-set a role
   in `launcher.cfg` that then starts without the menu. Delete `launcher.cfg` to get back to the menu.)
5. The badge, the **New Game -> Multiplayer** menu, world download and save separation work exactly as in the Windows steps above.
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
The event layer has its own tests (`tests/test_event_layer.py`, `tests/test_event_features.py`,
`tests/test_event_bridge.py <helper>`); see `docs/TESTING.md`.
Python is only used for developer tests. Both release binaries are native NASM code.
Open `build/mistrimulti-helper.exe` in x64dbg; break on `mistria_main`, `read_local_frame`,
`receive_fragment`, or `send_record`. Start with `docs/ASM-TOUR.md`.

Game bridge data lives under the game's configuration folder:
`mod_data/mistrimulti/control.json`, `mod_data/mistrimulti/bridge_<id>/` and, for the in-game menu,
`mod_data/mistrimulti/menu/cmd.txt` + `status.json` (`docs/SYNC-MENU.md`).
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
