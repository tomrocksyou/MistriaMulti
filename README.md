# MistriMulti

A Fields of Mistria multiplayer mod with a native x86-64 NASM networking helper.
The Windows helper calls Win32/Winsock; the Linux helper uses Linux syscalls. Neither
helper needs Python, .NET, Rust, a paid server, or a third-party multiplayer relay at runtime.
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
5. Everyone double-clicks `MistriMultiLauncher.exe` (or `Play.bat`) once. It asks whether you want to host (H) or join
   a friend (J). **Joining only needs the host's IP address**: with Tailscale, that is the host's Tailscale address
   (it starts with `100.`). Port, room code and player number all have defaults; press Enter. Each friend gets a
   player number from 1 to 7 automatically, so if two friends end up with the same one, run the setup again and
   type a different number. A room code is optional (only useful if you want to keep strangers' packets out of a
   session on a public IP; the host and friends must then type the same one).
   The line to paste into Steam is copied to your clipboard when setup finishes.
6. **Click Play in Steam from now on.** One time only: in Steam, right-click the game, Properties, Launch Options,
   and paste the line `Play.bat` prints (`"<folder>\MistriMultiLauncher.exe" --steam %command%`). Steam then runs the
   launcher, which starts the network helper from your saved details and launches the game. If anything is wrong
   with the multiplayer setup the game still starts normally; the reason is written to
   `%LOCALAPPDATA%\FieldsOfMistria\mod_data\mistrimulti\launcher.log`.
7. A badge at the bottom right shows **Multiplayer Online** (green) or **Multiplayer Offline** (red: the game was
   updated past the versions this mod was tested on, the helper is not running, or setup was not done).
8. In the game choose **New Game** or **Load Game**, then **Singleplayer** or **Multiplayer**. Saves are labelled
   `[Single]` or `[Multi]` and are kept in separate folders. After a game update, add the new version to
   `mistrimulti_supported_versions()` in `MistriMultiStatus.gml` once you have tested the mod with it.

`MistriMultiLauncher.exe` and the helper must sit in the same folder. The mod installer (`Install-Mod.bat`) searches
Steam libraries for the game; pass `-GameDirectory` to `scripts\Install-Mod.ps1` to choose an installation explicitly.

Use a LAN or a private VPN such as Tailscale. Windows Firewall may ask once whether `mistrimulti-helper.exe` may use the network: allow it for the private network (and for Tailscale's adapter if it is listed as public). The default room code is not a password, so do not expose the host's port to the open Internet. Direct Internet connections need the host's
UDP port reachable; CGNAT can prevent direct hosting. The room code separates sessions,
and the checksum detects corruption; this protocol does **not** provide encryption or
cryptographic authentication. No firewall or router settings are changed automatically.

## Linux / Steam Deck

The native Linux helper passes transport tests in Ubuntu under WSL. Actual native
game integration on a Steam Deck still requires device testing.

Install the GML mod through the Linux MOMI build. Build with `sh scripts/build-linux.sh`
(NASM and binutils), or use the supplied `build/mistrimulti-helper-linux` executable.
Launch in Desktop Mode:

```sh
sh scripts/play-linux.sh host a1b2c3d4
sh scripts/play-linux.sh join 192.168.1.10 1 a1b2c3d4
```

If automatic data-directory detection fails, set `MISTRIMULTI_DATA_DIR` to the actual
game configuration directory that contains `saves`. The Linux launcher leaves Steam
launching to you and exits the helper when you press Enter after closing the game.
Steam input can map a controller button to F8 for the status notification.

## Build, test, learn

Windows needs NASM and Microsoft C++ Build Tools with MSVC x64/x86 and a Windows SDK:

```powershell
./scripts/Build.ps1                  # debug symbols for x64dbg
./scripts/Build.ps1 -Release         # compact executable
./scripts/Build.ps1 -Target Both     # Windows + WSL Ubuntu Linux linker
python tests/test_transport.py build/mistrimulti-helper.exe
python tests/test_packet_faults.py build/mistrimulti-helper.exe
```

For Linux, run the same Python tests with `build/mistrimulti-helper-linux` on Linux.
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
