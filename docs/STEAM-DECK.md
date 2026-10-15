# MistriaMulti on the Steam Deck (and other Linux PCs)

Status: the Linux launcher and manager are tested natively with a fake game (see `docs/TESTING.md`). They have **not**
been run against the real game on a real Steam Deck yet, so treat the first session as a test and read "If something
goes wrong" at the end. Everything below also applies to a desktop Linux PC.

## One-time setup in Desktop Mode

1. **Switch to Desktop Mode.** Press the Steam button, choose Power, then Switch to Desktop.
2. **Get the project.** Download the project (or the `mistrimulti-linux-x64` build from the project's CI page, unpacked into the
   project folder) and open **Konsole** (the terminal) in that folder.
3. **Close Steam** (Steam menu, Exit), because Steam overwrites its own settings while it runs. Then run:

   ```sh
   ./install.sh
   ```

   It copies the programs to `~/.local/share/mistrimulti`, sets the Steam launch option for Fields of Mistria (your old
   `localconfig.vdf` is backed up next to it first), copies the mod into the game's `mods` folder and prints what it did.
   If Steam is still running it does everything else and prints the launch option for you to paste (right-click the game,
   Properties, Launch Options). `./install.sh --dry-run` shows what it would do; `./install.sh --uninstall` undoes it.
   Running it twice is safe.
4. **Finish the mod in MOMI.** Open the Linux build of MOMI (0.16.5, game 1.0.6), select **MistriaMulti** and click Install,
   as on Windows. Close the game while installing.
5. **Go back to Gaming Mode** (the "Return to Gaming Mode" icon on the desktop), press Play, and choose **Multiplayer** on
   New Game or Load Game. That is all: hosting and joining are chosen in the game (see below). There is nothing to type in
   Konsole for normal play.

If the programs are not prebuilt, `install.sh` builds them and needs `nasm` and `binutils`; if they are missing it prints the one
command to run (`sudo apt-get install -y nasm binutils`; `--yes` lets it run that itself). The Deck's system is read-only by
default (`sudo steamos-readonly disable` first, and SteamOS updates can undo it), so a prebuilt copy is simpler there.

The programs live in `~/.local/share/mistrimulti/` (the installer prints the exact paths).

## Hosting and joining (in the game)

Start the game from Steam (Play), choose **New Game** or **Load Game**, then **Multiplayer**:

- **Host a game**: choose **Start hosting** (first **Set a password** if you want one; the game asks you to type it with the
  Steam keyboard). The game then shows the addresses to give your friends: your **Tailscale** address (starts with `100.`) and your
  **local-network** address. Choose **Start playing**. Save (sleep in the game) before friends join: they receive the world as of your
  last save. While you host, the launcher answers friends who scan for hosts (UDP 7776) and gives them your newest multiplayer save
  (TCP 7775). Nothing listens before you choose Host.
- **Join a game**: the game looks for hosts on your local network and on your Tailscale network and lists them (`[password]`
  marks a host that needs one). Pick one, type the password if asked, and wait while it downloads the host's world; the world opens.
  **Refresh** looks again; **Type an address** joins an address that is not listed (for example a Tailscale address). Your player
  number (1-7) is chosen for you. If the host uses a custom room code you are asked for it.

The host can be found automatically only on the same local network or through Tailscale. Over the Internet, use Tailscale (or
another private VPN) and type the host's Tailscale address. Do not expose the ports to the open Internet: the room code is not
a password and the protocol has no encryption.

The badge at the bottom right says **Multiplayer: Idle** (ready), **Online** or **Offline - reason**; F8 shows the same text.

### Optional: pre-set a role from Konsole

`~/.local/share/mistrimulti/mistrimulti-manager host` / `join [IP]` (and `mistrimulti-launcher --configure`) still exist for people
who prefer a console. They write `launcher.cfg`, and the saved role then starts by itself when the game starts. Delete
`<game folder>/mod_data/mistrimulti/launcher.cfg` to go back to choosing in the game.

## Safety net for your solo saves

The launcher copies your solo saves into `mod_data/mistrimulti/solo_backups/<UTC time>/` inside the game's folder before every
launch (the newest 10 are kept), and never changes the originals. For an extra copy that is easy to find, run

```sh
~/.local/share/mistrimulti/mistrimulti-manager save-solo
```

which copies them to `~/Documents/MistriMulti Backups/<UTC time>/`.

## Controls

The in-game connection badge is at the bottom right. The F8 key shows the connection status; use Steam Input to map a Deck
button to F8 if you want it in Gaming Mode.

## If something goes wrong

- **The badge says "Offline - launcher not running".** The game was not started through the MistriaMulti launch option. Run
  `./install.sh` again with Steam closed, or paste the launch line it prints into the game's Launch Options by hand. The
  reason is also in the game's log, and `<game folder>/mod_data/mistrimulti/launcher.log` says what the launcher did.
- **The game starts but Multiplayer says it cannot start.** The reason is written to
  `<game folder>/mod_data/mistrimulti/launcher.log`, and the helper's own messages are in `helper.log` next to it. The game
  always starts normally even when the multiplayer setup is broken.
- **"Could not find the folder where the game keeps its files."** The Linux tools look for the game's `saves` folder in the
  places listed in `README.md` (`~/.config/FieldsOfMistria`, `~/.local/share/FieldsOfMistria`, and the Proton prefix under
  `~/.local/share/Steam/steamapps/compatdata/*/pfx/drive_c/users/steamuser/AppData/Local/FieldsOfMistria`). Start the game once
  so it creates its folder, or tell the tools where it is: `export MISTRIMULTI_DATA_DIR=/the/folder/with/saves` before running
  the manager, and use the Steam launch option
  `MISTRIMULTI_DATA_DIR=/the/folder/with/saves "/home/deck/.local/share/mistrimulti/mistrimulti-launcher" --steam %command%`.
  (If you find the folder, please report where it was so the list can be corrected.)
- **Proton and the bridge folder.** When the game folder is inside a Proton prefix, the launcher writes the helper bridge path
  into `control.json` the way the Windows game sees it (`C:/users/steamuser/AppData/Local/...`). This is the least tested
  part: if the in-game badge stays red while `status.json` in the bridge folder keeps updating, `control.json`'s `bridge`
  value is what the game rejects. Please include `control.json` and `launcher.log` in a bug report.
- **No hosts found.** Make sure the host started the game from Steam with the launch option set and chose Host a game, that you are on the same
  network (or both on Tailscale, and the `tailscale` command exists on your side), and that nothing blocks UDP 7776. Choose
  Type an address as a fallback. SteamOS has no firewall by default; other distributions may need UDP 7776, TCP 7775 and the
  game port (UDP 7777 and up) opened for the private network.
- **Wrong game executable.** Multiplayer only starts when one of the arguments Steam passes has a file name beginning with
  `FieldsOfMistria` (`FieldsOfMistria.exe` under Proton). Other programs are launched untouched. To bypass multiplayer for one
  launch, add `--mistrimulti-direct` after `%command%`.
- **Stopping.** Closing the game, or stopping it from Steam (the launcher passes SIGTERM/SIGINT on), stops the helper and turns
  `control.json` off. If the launcher itself is killed, the helper is terminated by the kernel as well.
