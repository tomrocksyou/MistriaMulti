# MistriMulti

Co-op for **Fields of Mistria**! One person hosts their farm and friends join in (up to 8 players). You farm, water,
plant, fill chests, ship stuff and sleep through the night together, and everyone sees everyone else running around.

Made for fun to play with friends. It's experimental, so expect the odd bug.

## How it works

- There's a mod that runs inside the game, plus a small helper program that does the networking (the game itself can't
  talk over the internet, so the helper does it for it). It's written in assembly, just for fun.
- You start the game from Steam like normal. A launcher sits in front of the game and waits in the background.
- In the game you pick **New Game** (or **Load Game**) > **Multiplayer** > **Host a game** or **Join a game**. That's it.
- The host's world is the real one. Friends download it when they join, and their own character, inventory and progress
  are kept on the host's side, so they come back to it next time.
- Your singleplayer saves stay separate and nothing in multiplayer touches them.
- To connect over the internet, everyone uses **Tailscale** (free). On the same home network you don't need it.

## Setup

You need Fields of Mistria on Steam, **MOMI** (the mod installer: https://github.com/Garethp/Mods-of-Mistria-Installer)
and **Tailscale** (https://tailscale.com/download) on everyone's computer, all on the same Tailscale network.

Grab the latest download from **Releases** (right side of this page).

### Windows

1. Download `MistriMulti-<version>-Windows.zip` and unzip it somewhere you'll keep it (like Documents). Don't move the
   folder later, Steam uses it.
2. Close the game and double-click `Install-Mod.bat`.
3. Open MOMI, tick MistriMulti, click **Install**.
4. Open `MistriMulti.exe`, press **Steam setup...**, then in Steam: right-click Fields of Mistria > Properties >
   Launch Options and paste.

### Linux / Steam Deck

1. Download `MistriMulti-<version>-Linux.tar.gz` and unpack it (on the Deck, do this in Desktop Mode).
2. Close Steam, open a terminal in that folder and run `./install.sh`. It sets up Steam for you.
3. Open MOMI, tick MistriMulti, click **Install**.

### Playing

- **Hosting:** Multiplayer > Host a game > Start hosting. Give your friends the address that starts with `100.`
  Sleep once before they join, they get your world as of your last save.
- **Joining:** Multiplayer > Join a game, pick the host (or type their `100.` address).
- **F8** shows if you're connected.

### Updating

Download the new version, unpack it over the old folder, run `Install-Mod.bat` (or `./install.sh`) again, then MOMI >
Install. Everyone has to be on the same version.

More detail and troubleshooting: [docs/HOW-TO-PLAY.md](docs/HOW-TO-PLAY.md)

## What works so far

Tried in the real game and working: seeing each other, shared time and weather, sleeping together, hoeing, watering,
planting, chests, the shipping bin and shared gold, going to town, leaving and coming back.

Not tried for real yet: the mines, animals, buildings, quests and cutscenes. Villagers can be a few steps apart on
different screens.

If something breaks, the log is in `%LOCALAPPDATA%\FieldsOfMistria\multiplayer\mod_data\mistrimulti\logs` (Windows) or
`~/.local/share/FieldsOfMistria/multiplayer/mod_data/mistrimulti/logs` (Linux). Grab it before restarting the game.

## For developers

All the technical stuff (building, tests, how it all fits together) is in [docs/DEVELOPERS.md](docs/DEVELOPERS.md).

## License

Free for noncommercial use, modding and sharing. Selling it or using it in something commercial needs permission first,
see `LICENSE` and `CONTACT.md`.
