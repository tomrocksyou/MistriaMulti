# How to play MistriaMulti

Co-op for Fields of Mistria: one player hosts their farm, friends join it. Everyone needs the same MistriaMulti version.
Supported game versions: 1.0.6 and 1.0.8 (on any other version the badge says the mod needs an update).

## What you need

- Fields of Mistria on Steam.
- **MOMI** (Mods of Mistria Installer): https://github.com/Garethp/Mods-of-Mistria-Installer/releases
- **Tailscale** (free), so your computers can reach each other over the Internet: https://tailscale.com/download
  Install it on every computer, log in, and invite your friends to your Tailscale network (or share your computer with them
  from the Tailscale admin page). Players on the same home network can skip Tailscale.

## Install (once)

### Windows

1. Download `MistriaMulti-<version>-Windows.zip` from the latest release on GitHub (Releases, on the right of the repository page).
2. Unzip it into a place you will keep, for example `Documents`. It makes a `MistriaMulti` folder. **Do not move that folder
   afterwards**: Steam starts the game through a program in it.
3. Close the game. Double-click `Install-Mod.bat`. It copies the mod into the game's `mods` folder.
4. Open MOMI, tick **MistriaMulti**, click **Install**.
5. Double-click `MistriMulti.exe` and press **Steam setup...**. It copies a line. In Steam: right-click Fields of Mistria >
   Properties > General > Launch Options, paste the line, close the window.

### Linux / Steam Deck (Desktop Mode)

1. Download `MistriaMulti-<version>-Linux.tar.gz` from the latest release and unpack it (it makes a `MistriaMulti` folder).
2. Close Steam. In that folder, open a terminal and run `./install.sh`. It copies the programs, sets Steam's launch option
   and copies the mod into the game's `mods` folder.
3. Open MOMI, tick **MistriaMulti**, click **Install**.

## Play

Start the game from Steam as usual.

- **Host:** New Game (or Load Game) > **Multiplayer** > **Host a game** > **Start hosting** (you can set a password first).
  The game shows your addresses: give your friends the one that starts with `100.` (Tailscale). Press **Start playing**.
  A **new** world saves itself as soon as you can move at home ("your new world is saved. Friends can join now"). For an older
  world, friends get your world as of your last save, so sleep once first. If a friend sees "The host has started a new world but has
  not saved it yet", just sleep or save once and have them press **Join again**.
  When you start a **new** world you also choose how hearts with villagers work: each player's own (recommended) or shared.
  Dating and marriage are always per player, and two players can't date or marry the same villager.
- **Join:** New Game > **Multiplayer** > **Join a game**. Pick the host from the list, or choose **Type an address** and type
  the host's `100.` address. Type the password if asked. The host's world downloads and opens.
  **A character per world:** on **New Game** you make a new character for that world in the game's character editor (your solo
  characters are never used or changed). If you already have a character in that world you are asked **Keep mine** or **New
  character**; if you have several, a list lets you pick one. On **Load Game** you carry on with the character you already have
  there, with no editor. A new character gets the same first tools and seeds a new player gets.
- **Hosts only, for testing:** press **Ctrl+F6** in a world to unlock the mines early for everyone (see `docs/DEVTOOLS.md`).

Singleplayer stays separate: choosing **Singleplayer** uses your normal saves, which multiplayer never touches.
The badge at the bottom right shows the connection status (F8 shows it too).

## Update

Every player must have the same version.

**Windows:** close the game, open `MistriMulti.exe` and press **Update MistriMulti**. It downloads the newest release from
GitHub, checks every file against its checksum and replaces the mod files and the programs (all or nothing: if anything fails,
nothing is changed and the window says why). Then the mod has to be installed into the game once more:

- Press **Open MOMI** once and choose your MOMI program (it is remembered). After the next update the window opens MOMI for you:
  select **MistriaMulti** and click **Install**.
- Optional, saves the last click: in that file dialog choose MOMI's **command-line** program instead (its name contains `-cli`,
  from the same MOMI download page). After an update the manager then asks "Run MOMI's installer for you?"; Yes runs it, No
  opens MOMI. It installs every mod in your mods folder. It asks every time, and if MOMI's installer reports a problem you are
  told to press Install in MOMI.

**Linux / Steam Deck:** close the game, then in a terminal run `~/.local/share/mistrimulti/mistrimulti-update.sh --update` (or
`mistrimulti-manager update`, or `./install.sh --update` in the unpacked folder). It does the same: downloads, verifies, updates
the programs in `~/.local/share/mistrimulti` and the mod files in the game's `mods` folder, and tells you to press Install in
MOMI. To let it run MOMI for you, download MOMI's command-line program (`ModsOfMistriaInstaller-cli-linux`), `chmod +x` it and
run `./install.sh --momi-cli /path/to/it` once; `--update` then asks before it runs it.

No network, or no release yet: you are told and nothing is changed. The old way (download the new zip or tar.gz, unpack it over
the old folder, run `Install-Mod.bat` / `./install.sh`, then MOMI > **Install**) still works.

### Update from inside the game

On the title screen, bottom left, next to the game's own version, the game shows **MistriMulti** and your installed version (new in 0.4.7). Once a day the
launcher quietly asks whether a newer release exists (this needs `curl`, which Windows 10 and later and SteamOS have). When there is one, an
**Update** button appears next to the version. Click it: the text shows what happens (`Downloading 0.4.7...`), then either `Installed. Restart the game`
or `Updated. Close the game and press Install in MOMI`, or a plain error with the button back for another try. Every player still has to update. In a
world, the Multiplayer badge (and F8) say `update available (0.4.7)`. You cannot start an update while you host or join; the button only exists on the title screen.

To switch the daily check off, create a text file named `update.cfg` in the MistriaMulti data folder (next to `launcher.cfg`; Windows
`%LOCALAPPDATA%\FieldsOfMistria\mod_data\mistrimulti`) with the single line `check=off`. The version still shows, but nothing is requested and no button
appears. The check never delays the game and stays silent when you are offline.

## If something goes wrong

- The game starts normally but Multiplayer says it is offline: the Steam launch option is missing or points to a folder that
  moved. Do the Steam setup step again.
- A friend cannot find or reach the host: check that both are logged in to Tailscale and on the same Tailscale network, and
  type the host's `100.` address by hand. Windows may ask whether `mistrimulti-helper.exe` may use the network: allow it.
- "That player slot is already in use": press **Try again**.
- You pressed Cancel in a Host or Join screen: just press **New Game** again.
- The character editor did not appear after joining: send the log (below); it says why.
- Reporting a bug: on Windows press **Collect Logs** in `MistriMulti.exe` right after the problem happens (before you restart the
  game, the logs are rewritten at every start). It copies the logs into one folder, `Documents\MistriMulti Backups\Logs-<time>`, and
  opens it. Send that folder with a few words on what you were doing and what you expected.
  On Linux, or by hand, the logs are `mod_data/mistrimulti/logs/mistrimulti.log` and, from a multiplayer world,
  `multiplayer/mod_data/mistrimulti/logs/mistrimulti.log` under `%LOCALAPPDATA%\FieldsOfMistria\` (Windows) or
  `~/.local/share/FieldsOfMistria/` (Linux).

## What is shared

Tested in the real game: both players' characters, time and weather, sleeping and the new day, hoeing, watering and planting,
chests, the shipping bin, one shared gold purse and one shared town rank, picking things up in town, the other player on the map,
story cutscenes, the mines (same floors), a character per world, and leaving and rejoining.
Written but not yet tried in the real game: animals and the insides of barns, coops and the greenhouse.
Villagers walk the same schedule on every screen but can be a few steps apart. Story cutscenes are watched by everybody
themselves (skip them with the game's own skip button if you like): what a scene changes in the world counts once, and
rewards are paid once per player. This is an experimental mod: back up saves you
care about (the launcher also keeps copies of your singleplayer saves in `mod_data/mistrimulti/solo_backups`).
