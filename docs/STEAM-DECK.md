# MistriMulti on the Steam Deck (and other Linux PCs)

Status: the Linux launcher and manager are tested natively with a fake game (see `docs/TESTING.md`). They have **not**
been run against the real game on a real Steam Deck yet, so treat the first session as a test and read "If something
goes wrong" at the end. Everything below also applies to a desktop Linux PC.

You need three programs from this project, kept together in one folder:

- `mistrimulti-launcher` (starts the helper and the game from Steam)
- `mistrimulti-manager` (host, join, Steam setup, backups)
- `mistrimulti-helper-linux` (the network helper)

Every player needs the mod installed and these three programs. Only Steam's launch option has to be set once.

## One-time setup in Desktop Mode

1. **Switch to Desktop Mode.** Press the Steam button, choose Power, then Switch to Desktop.
2. **Get the programs.** The Deck's system is read-only by default, so the easiest way is a prebuilt copy: download the
   `mistrimulti-linux-x64` build from the project's CI page (or copy the files from the PC where you built them with
   `sh scripts/build-linux.sh`). Put them in a folder such as `/home/deck/mistrimulti`. Then open **Konsole**
   (the terminal) and run:

   ```sh
   cd ~/mistrimulti
   chmod +x mistrimulti-launcher mistrimulti-manager mistrimulti-helper-linux
   ```

   (Building on the Deck itself needs `nasm` and `binutils`, which means `sudo steamos-readonly disable` and a package
   install, and SteamOS updates can undo that. Building elsewhere is simpler.)
3. **Install the mod.** Use the Linux build of MOMI to install **MistriMulti** into Fields of Mistria (MOMI 0.16.5, game
   1.0.6), exactly as on Windows. Close the game while installing.
4. **Set up hosting or joining** (see the next two sections), still in Konsole.
5. **Add the Steam launch option, once.** In Konsole run:

   ```sh
   ~/mistrimulti/mistrimulti-manager steam-setup
   ```

   It prints a line like `"/home/deck/mistrimulti/mistrimulti-launcher" --steam %command%`. Select it with the touchpad or
   mouse and copy it (Ctrl+Shift+C in Konsole). Then in Steam: right-click **Fields of Mistria**, Properties, Launch Options,
   paste (Ctrl+V), and close the window. It works the same whether the game runs natively or through Proton, because
   `%command%` is replaced by whatever Steam would have run.
6. **Go back to Gaming Mode** (the "Return to Gaming Mode" icon on the desktop) and press Play as usual.

## Hosting

```sh
~/mistrimulti/mistrimulti-manager host
```

This saves the host setup and prints the addresses to give your friends: your **Tailscale** address (starts with `100.`) and
your **local-network** address. Start the game from Steam, choose **New Game** or **Load Game**, then **Multiplayer**.
Save (sleep in the game) before friends join: they receive the world as of your last save. While you play, the launcher
answers friends who scan for hosts (UDP 7776) and gives them your newest multiplayer save (TCP 7775).

## Joining

```sh
~/mistrimulti/mistrimulti-manager join
```

The manager looks for hosts on your local network and on your Tailscale network, numbers them, and asks which one to join.
Type the number, `R` to look again, or type an IP address. If the host uses a room code you are asked for it (the list marks
those hosts). To skip the list: `mistrimulti-manager join 100.101.102.103`, optionally with `--player 3`, `--room a1b2c3d4`
or `--port 7777`. Your player number (1-7) is picked for you and kept; two friends must not share one, so pass `--player` if
you end up with the same number as someone else. Joining also downloads the host's latest world; start the game from Steam,
choose **New Game**, then **Multiplayer**, and you enter the host's world.

The host can be found automatically only on the same local network or through Tailscale. Over the Internet, use Tailscale (or
another private VPN) and type the host's Tailscale address. Do not expose the ports to the open Internet: the room code is not
a password and the protocol has no encryption.

## Safety net for your solo saves

The launcher copies your solo saves into `mod_data/mistrimulti/solo_backups/<UTC time>/` inside the game's folder before every
launch (the newest 10 are kept), and never changes the originals. For an extra copy that is easy to find, run

```sh
~/mistrimulti/mistrimulti-manager save-solo
```

which copies them to `~/Documents/MistriMulti Backups/<UTC time>/`.

## Controls

The in-game connection badge is at the bottom right. The F8 key shows the connection status; use Steam Input to map a Deck
button to F8 if you want it in Gaming Mode.

## If something goes wrong

- **The game starts but there is no multiplayer.** The reason is written to
  `<game folder>/mod_data/mistrimulti/launcher.log`, and the helper's own messages are in `helper.log` next to it. The game
  always starts normally even when the multiplayer setup is broken.
- **"Could not find the folder where the game keeps its files."** The Linux tools look for the game's `saves` folder in the
  places listed in `README.md` (`~/.config/FieldsOfMistria`, `~/.local/share/FieldsOfMistria`, and the Proton prefix under
  `~/.local/share/Steam/steamapps/compatdata/*/pfx/drive_c/users/steamuser/AppData/Local/FieldsOfMistria`). Start the game once
  so it creates its folder, or tell the tools where it is: `export MISTRIMULTI_DATA_DIR=/the/folder/with/saves` before running
  the manager, and use the Steam launch option
  `MISTRIMULTI_DATA_DIR=/the/folder/with/saves "/home/deck/mistrimulti/mistrimulti-launcher" --steam %command%`.
  (If you find the folder, please report where it was so the list can be corrected.)
- **Proton and the bridge folder.** When the game folder is inside a Proton prefix, the launcher writes the helper bridge path
  into `control.json` the way the Windows game sees it (`C:/users/steamuser/AppData/Local/...`). This is the least tested
  part: if the in-game badge stays red while `status.json` in the bridge folder keeps updating, `control.json`'s `bridge`
  value is what the game rejects. Please include `control.json` and `launcher.log` in a bug report.
- **No hosts found.** Make sure the host started the game from Steam with the launch option set, that you are on the same
  network (or both on Tailscale, and the `tailscale` command exists on your side), and that nothing blocks UDP 7776. Join by
  typing the IP as a fallback. SteamOS has no firewall by default; other distributions may need UDP 7776, TCP 7775 and the
  game port (UDP 7777 and up) opened for the private network.
- **Wrong game executable.** Multiplayer only starts when one of the arguments Steam passes has a file name beginning with
  `FieldsOfMistria` (`FieldsOfMistria.exe` under Proton). Other programs are launched untouched. To bypass multiplayer for one
  launch, add `--mistrimulti-direct` after `%command%`.
- **Stopping.** Closing the game, or stopping it from Steam (the launcher passes SIGTERM/SIGINT on), stops the helper and turns
  `control.json` off. If the launcher itself is killed, the helper is terminated by the kernel as well.
