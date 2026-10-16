# MOMI notes: can the command-line build install mods headlessly?

MOMI = Mods of Mistria Installer, <https://github.com/Garethp/Mods-of-Mistria-Installer> (C# / .NET, GPL-3.0). Research
date: 2026-10-16, from the public `main` branch. Nothing from MOMI is copied into this repository; this page is facts and
links only.

How it was read: the raw files were fetched with a web-fetch tool that returns a summary written by a small model, not the
verbatim source. The statements below are therefore **reported by that summary and not byte-checked** against the C# files.
Nothing was run (no .NET, no MOMI binary in the test machine). Treat every row as "to confirm on a real machine".

## Sources

| What | Link |
| --- | --- |
| README (install steps, "-cli" mention) | <https://github.com/Garethp/Mods-of-Mistria-Installer> |
| CLI entry point | `ModsOfMistriaCommandLine/Program.cs` |
| CLI project file | `ModsOfMistriaCommandLine/ModsOfMistriaCommandLine.csproj` |
| Install logic used by both programs | `ModsOfMistriaInstallerLib/Standalone.cs`, `ModInstaller.cs` |
| Where the game / mods folder are looked for | `ModsOfMistriaInstallerLib/MistriaLocator.cs` |
| What the GUI Install button does | `ModsOfMistriaGUI/ViewModels/ModlistPageViewModel.cs` (`InstallMods`, `BackgroundInstall`) |

## The command-line program

- Built from `ModsOfMistriaCommandLine` (net10.0, self-contained, single file). Assembly names per the csproj:
  `ModsOfMistriaInstaller-cli` (default), `ModsOfMistriaInstaller-cli-win-x86`, `ModsOfMistriaInstaller-cli-linux`,
  `ModsOfMistriaInstaller-cli-osx`. The README only says to try "the `-cli` version" when something goes wrong (it "doesn't look as
  nice, but should provide more information"). It documents no flags.
- **With no arguments it installs.** `Program.cs` checks the diagnostic flags first (`--version`, `--compile-check`, `--seam-check`,
  `--seam-diff`, `--reseed-check`, `--lint`, `--uninstall`); with none of them it runs `Standalone.Run(options, gateMode)`:
  find the game, find the mods folder, discover the mods in it, drop the invalid ones (logged), install the rest.
- Optional install flags: `--strict-lints`, `--fail-on-skip` (stop instead of skipping GML mods whose seams do not match),
  `--compile-check on|off|require`. A bad `--compile-check` value exits 2.
- `--uninstall` restores the game's original archive.
- **Exit codes** (install path): 0 on completion, 1 when an exception escaped. `Standalone.Run` returns `void` and returns
  quietly (so the program exits **0**) when the game folder is not found or the mods folder is missing: it only logs a
  message. So exit 0 does NOT prove that mods were installed.
- **It waits for a key press at the end** unless the environment variable `EXIT_ON_COMPLETE` equals `true`. A headless caller must set
  it (and should give the child no console input).
- Output is plain log lines on the console (progress, summary of installed and skipped mods with reasons). Their wording comes from
  resource strings we have not seen.

## How it finds the game and the mods folder (`MistriaLocator`)

- Game: the first existing `<steam library>/common/Fields of Mistria` that contains `Maybe.toml`. Candidates: the two default
  Windows Steam folders, every drive root plus a few suffixes (`SteamLibrary/steamapps/`, `Program Files (x86)/Steam/steamapps/`...),
  and on Linux `~/.local/share/Steam/steamapps/`, the Snap path, `~/.steam/debian-installation/steamapps/` and a CrossOver path.
  Fallback: the **current working directory** if it contains `Maybe.toml`. No registry, no environment variable, **no argument** to
  choose the game folder. (It does not read Steam's `libraryfolders.vdf` in the parts we saw, so a library on another Linux
  mount may not be found unless the working directory trick is used.)
- Mods folder: `<game>/mods`, then `<game>/Mods`, then `~/mistria-mods`, then `~/Mistria-Mods`; the first one that exists. On Linux a
  folder that is a symbolic link is skipped. Not configurable.
- Saves (used for the extension ledger): `%LOCALAPPDATA%\FieldsOfMistria\saves`, or the Proton prefix `compatdata/2142790`.
- `MOMI_GAME_CONFIG_DIR` (environment) only redirects config directories.
- Linux/Proton: the README gives no extra requirement beyond the mods folder; the Linux CLI is a native self-contained build, so
  it edits the game's files directly (no Wine needed to run it). Whether it needs anything else on a Steam Deck was not verified.

## What the GUI's Install button does

`InstallMods` saves the profile (enabled mods and load order), then in the background builds a `ModInstaller(game, mods folder,
saves folder)` and calls `InstallMods` for **only the mods ticked as enabled in the window**; results become a status line and a
tick or cross per mod. The library call is the same one the command line makes. Differences that matter to us:

1. The GUI installs the enabled set from its profile; the CLI installs **every valid mod in the mods folder**.
2. The GUI lets the player pick a game folder; the CLI can only use what the locator finds (or the working directory).

`ModInstaller.InstallMods` makes a backup of the original game archive first (`EnsureBackup`), then rebuilds the archive from that
backup plus all selected mods (a full rebuild each time, written only at commit), so running it again is a reinstall, not an
increment. The code reviewed shows no prompts and no check that the game is running (close the game first; this is not enforced
by us either, we say it in the window).

## What we do with this

- Windows manager and `install.sh --update` run the CLI **only if the player chose its path** and **agrees each time**; they set
  `EXIT_ON_COMPLETE=true`, start it in the game folder, and tell the player that exit code 0 does not prove an install. Any problem
  (missing program, non-zero exit, timeout) falls back to: open MOMI, select MistriaMulti, press Install.
- The path is never searched for or guessed; a program that is not named `*-cli*` is never run by that step.

## Not verified (needs a real machine)

- That the CLI really installs with no arguments and what it prints (read through a summary, not run).
- That the release assets exist under the names above and that the Linux build runs on the Steam Deck.
- The wording of messages; the behaviour when the game is running; whether `~/mistria-mods` or the game's `mods` folder is used when both exist.
- That a mod skipped by validation is reported with a non-zero exit code (the summary says it is only logged).

## Ready-to-post feature request for the MOMI maintainer

**Title:** A documented non-interactive "install all mods" command with exit codes and folder arguments

**Body:**

Hi, and thanks for MOMI. I maintain a mod (MistriaMulti, <https://github.com/tomrocksyou/MistriaMulti>) that ships updates through
GitHub releases. Our own updater can download the new mod files into `mods/`, but the player then has to open MOMI and press Install,
which is the step people forget. From reading `ModsOfMistriaCommandLine/Program.cs` the `-cli` build already seems to install
everything when run without arguments, but it is only mentioned as a diagnostic build, so we cannot rely on it.

What we need (small, documented, stable):

1. A documented command, for example `ModsOfMistriaInstaller-cli install`, that installs (reinstalls) all enabled mods without any
   prompt and without waiting for a key (today that needs `EXIT_ON_COMPLETE=true`).
2. Documented exit codes: 0 only when the archive was rebuilt, a different non-zero code for "game not found", "mods folder not
   found", "some mods were skipped" and "failed". Today `Standalone.Run` returns quietly when the game or the mods folder is missing,
   so the program exits 0.
3. Arguments to pass the game folder and the mods folder (`--game <dir> --mods <dir>`), so a launcher can target the right copy
   (Steam libraries on other mounts, Flatpak Steam, Proton).
4. An option to install only the mods enabled in the GUI profile, or to name mods (`--only mistrimulti`).
5. Optionally a machine-readable summary (`--json`) so a tool can show "installed 1, skipped 0" in its own words.

Why: every mod author who publishes updates has the same "now press Install in MOMI" step; a stable command lets updaters finish the
job for the player. I am happy to contribute a pull request for the argument parsing, the exit codes and the README section if you
tell me which shape you prefer.
