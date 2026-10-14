# How to play MistriMulti

Co-op for Fields of Mistria: one player hosts their farm, friends join it. Everyone needs the same MistriMulti version.

## What you need

- Fields of Mistria on Steam.
- **MOMI** (Mods of Mistria Installer): https://github.com/Garethp/Mods-of-Mistria-Installer
- **Tailscale** (free), so your computers can reach each other over the Internet: https://tailscale.com/download
  Install it on every computer, log in, and invite your friends to your Tailscale network (or share your computer with them
  from the Tailscale admin page). Players on the same home network can skip Tailscale.

## Install (once)

### Windows

1. Download `MistriMulti-<version>-Windows.zip` from the latest release on GitHub (Releases, on the right of the repository page).
2. Unzip it into a place you will keep, for example `Documents`. It makes a `MistriMulti` folder. **Do not move that folder
   afterwards**: Steam starts the game through a program in it.
3. Close the game. Double-click `Install-Mod.bat`. It copies the mod into the game's `mods` folder.
4. Open MOMI, tick **MistriMulti**, click **Install**.
5. Double-click `MistriMulti.exe` and press **Steam setup...**. It copies a line. In Steam: right-click Fields of Mistria >
   Properties > General > Launch Options, paste the line, close the window.

### Linux / Steam Deck (Desktop Mode)

1. Download `MistriMulti-<version>-Linux.tar.gz` from the latest release and unpack it (it makes a `MistriMulti` folder).
2. Close Steam. In that folder, open a terminal and run `./install.sh`. It copies the programs, sets Steam's launch option
   and copies the mod into the game's `mods` folder.
3. Open MOMI, tick **MistriMulti**, click **Install**.

## Play

Start the game from Steam as usual.

- **Host:** New Game (or Load Game) > **Multiplayer** > **Host a game** > **Start hosting** (you can set a password first).
  The game shows your addresses: give your friends the one that starts with `100.` (Tailscale). Press **Start playing**.
  Sleep once (save) before friends join: they get your world as of your last save.
- **Join:** New Game > **Multiplayer** > **Join a game**. Pick the host from the list, or choose **Type an address** and type
  the host's `100.` address. Type the password if asked. The host's world downloads and opens.

Singleplayer stays separate: choosing **Singleplayer** uses your normal saves, which multiplayer never touches.
Press **F8** in the game to see the connection status.

## Update

Download the new zip (or tar.gz), unpack it **in the same place** so it replaces the old `MistriMulti` folder's files, close the game, run `Install-Mod.bat` (Linux:
`./install.sh`), then MOMI > **Install** again. Every player must update.

## If something goes wrong

- The game starts normally but Multiplayer says it is offline: the Steam launch option is missing or points to a folder that
  moved. Do the Steam setup step again.
- A friend cannot find or reach the host: check that both are logged in to Tailscale and on the same Tailscale network, and
  type the host's `100.` address by hand. Windows may ask whether `mistrimulti-helper.exe` may use the network: allow it.
- "That player slot is already in use": press **Try again**.
- Logs for bug reports (they are rewritten each time the game starts, so copy them before restarting):
  - Windows: `%LOCALAPPDATA%\FieldsOfMistria\mod_data\mistrimulti\logs\mistrimulti.log` and, from a multiplayer world,
    `%LOCALAPPDATA%\FieldsOfMistria\multiplayer\mod_data\mistrimulti\logs\mistrimulti.log`
  - Linux: the same paths under `~/.local/share/FieldsOfMistria/`

## What is shared

Tested in the real game: both players' characters, time and weather, sleeping and the new day, hoeing, watering and planting,
chests, the shipping bin and one shared gold purse, picking things up in town, leaving and rejoining with your own inventory.
Written but not yet tried in the real game: each other on the map, the mines, animals and buildings, quests and cutscenes.
Villagers walk the same schedule on every screen but can be a few steps apart. This is an experimental mod: back up saves you
care about (the launcher also keeps copies of your singleplayer saves in `mod_data/mistrimulti/solo_backups`).
