# MistriaMulti

A Fields of Mistria multiplayer mod. One person hosts their farm, friends join in, and you play it together.

Made for fun to play with friends, so expect the odd bug.

**Early test version.** It has been played by two people over Tailscale (movement, clock and sleep, farming, chests, shipping bin, gold,
leaving and rejoining), but plenty of it, such as the mines, animals and the building interiors, has not been tried in the real game yet.
Issues and bug reports are welcome. Your solo saves are kept separate and backed up before every launch.

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
3. In MOMI, tick MistriaMulti and click Install. (MOMI might try to find a .exe automatically in the selection box, i had that at least, just remove it and you should see the normal executable) 

**Updating:** close the game, then Windows: open `MistriMulti.exe` and press **Update MistriMulti**; Linux / Steam Deck:
`./install.sh --update` (or `mistrimulti-manager update`). It downloads the newest release, verifies it and replaces the mod files
and programs; then press Install in MOMI once more (or let it run MOMI's command-line installer for you after you agreed once).
Details: [docs/HOW-TO-PLAY.md](docs/HOW-TO-PLAY.md#update), [docs/RELEASES.md](docs/RELEASES.md).

## Playing

Start the game from Steam like normal, then New Game (or Load Game) > **Multiplayer**:
- **Host a game**: share the address that starts with `100.` with your friends. Sleep once first, so they get your latest save.
- **Join a game**: pick the host from the list or type their address.

Your singleplayer saves stay separate. Press F8 to see if you're connected.

More help: [docs/HOW-TO-PLAY.md](docs/HOW-TO-PLAY.md). Technical stuff: [docs/DEVELOPERS.md](docs/DEVELOPERS.md).

## License

GNU GPL version 3 (see `LICENSE`): free to use, change and share. Anything you distribute that is based on it must stay open under the same licence.
