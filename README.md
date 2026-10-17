# MistriaMulti

A Fields of Mistria multiplayer mod. One person hosts their farm, friends join in, and you play it together.

Made for fun to play with friends, so expect the odd bug.

**Early test version.** Two people have played it over Tailscale: movement, clock and sleep, farming, chests, the shipping bin, shared
gold and town rank, story cutscenes, the mines, characters per world, and leaving and rejoining all worked. Animals and the building
interiors have not been tried in the real game yet. Bug reports are welcome. Your solo saves are kept separate and backed up before every launch.

Works with Fields of Mistria **1.0.6 and 1.0.8**. Everybody in a game needs the same MistriaMulti version (and the same other mods).

## Setup

You need:
- Fields of Mistria on Steam
- [MOMI](https://github.com/Garethp/Mods-of-Mistria-Installer/releases) (the mod installer)
- [Tailscale](https://tailscale.com/download), or Radmin VPN, or Hamachi so you and your friends can reach each other (not needed on the same home network)

Then grab the latest download from **Releases** (on the right).

**Windows**
1. Unzip `MistriaMulti-<version>-Windows.zip` somewhere you'll keep it, like Documents or your desktop.
2. With the game closed, run `Install-Mod.bat`.
3. In MOMI, tick MistriaMulti and click Install.
4. Open `MistriMulti.exe`, click **Steam setup...**, and paste the line into the game's Launch Options in Steam
   (right-click the game > Properties).

**Linux / Steam Deck**
1. Unpack `MistriaMulti-<version>-Linux.tar.gz` (Steam Deck: in Desktop Mode).
2. Close Steam and run `./install.sh` in that folder.
3. In MOMI, tick MistriaMulti and click Install. (If MOMI's game picker pre-fills a `.exe` path, clear it and choose the game's normal
   program instead.)

**Updating:** close the game, then 
Windows: open `MistriMulti.exe` and press **Update MistriMulti**; 
Linux / Steam Deck:
`./install.sh --update` (or `mistrimulti-manager update`). It downloads the newest release, verifies it and replaces the mod files
and programs; then press Install in MOMI once more (or let it run MOMI's command-line installer for you after you agreed once).
Details: [docs/HOW-TO-PLAY.md](docs/HOW-TO-PLAY.md#update), [docs/RELEASES.md](docs/RELEASES.md).

## Playing

Start the game from Steam like normal, then New Game (or Load Game) > **Multiplayer**:
- **Host a game**: share the address that starts with `100.` with your friends. A new world saves itself once you can move at home, so
  friends can join straight away. For an older world, friends get your last save.
- **Join a game**: pick the host from the list or type their address. On **New Game** you make a new character for that world; on
  **Load Game** you carry on with the character you already have there.

Your singleplayer saves stay separate: a guest never brings a solo character in, and multiplayer never touches your solo saves.
The badge at the bottom right shows whether you're connected.

The title screen shows your MistriaMulti version bottom left; when a newer release exists an **Update** button appears next to it (the daily check can be switched off, see [docs/HOW-TO-PLAY.md](docs/HOW-TO-PLAY.md)).

More help: [docs/HOW-TO-PLAY.md](docs/HOW-TO-PLAY.md). Technical stuff: [docs/DEVELOPERS.md](docs/DEVELOPERS.md).

## License

GNU GPL version 3 (see `LICENSE`): free to use, change and share. Anything you distribute that is based on it must stay open under the same licence.
