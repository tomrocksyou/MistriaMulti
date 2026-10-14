# MistriaMulti

A Fields of Mistria multiplayer mod. One person hosts their farm, friends join in, and you play it together.

Made for fun to play with friends, so expect the odd bug.

## Setup

You need:
- Fields of Mistria on Steam
- [MOMI](https://github.com/Garethp/Mods-of-Mistria-Installer) (the mod installer)
- [Tailscale](https://tailscale.com/download), so you and your friends can reach each other (not needed on the same home network)

Then grab the latest download from **Releases** (on the right).

**Windows**
1. Unzip `MistriaMulti-<version>-Windows.zip` somewhere you'll keep it, like Documents.
2. With the game closed, run `Install-Mod.bat`.
3. In MOMI, tick MistriaMulti and click Install.
4. Open `MistriMulti.exe`, click **Steam setup...**, and paste the line into the game's Launch Options in Steam
   (right-click the game > Properties).

**Linux / Steam Deck**
1. Unpack `MistriaMulti-<version>-Linux.tar.gz` (Steam Deck: in Desktop Mode).
2. Close Steam and run `./install.sh` in that folder.
3. In MOMI, tick MistriaMulti and click Install.

## Playing

Start the game from Steam like normal, then New Game (or Load Game) > **Multiplayer**:
- **Host a game**: share the address that starts with `100.` with your friends. Sleep once first, so they get your latest save.
- **Join a game**: pick the host from the list or type their address.

Your singleplayer saves stay separate. Press F8 to see if you're connected.

More help: [docs/HOW-TO-PLAY.md](docs/HOW-TO-PLAY.md). Technical stuff: [docs/DEVELOPERS.md](docs/DEVELOPERS.md).

## License

Free to use, mod and share, just not commercially without asking first (see `LICENSE` and `CONTACT.md`).
