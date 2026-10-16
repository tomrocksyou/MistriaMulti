# Releases and the manager's update scheme

The manager (`MistriMulti.exe`, assembly, `updater/`) updates everything from one release: the mod files, the three helper
programs and itself. This page describes what a release is, how the manager finds and checks it, and what is not verified.

## What a release is

A release is a GitHub Release tagged `v<version>` (for example `v0.2.0`) whose assets are:

| Asset | Contents |
| --- | --- |
| `latest.txt` | The list (below): version, SHA-256 of every file, a footer. |
| `MistriMulti.exe` | The manager. |
| `MistriMultiLauncher.exe` | The Steam launcher. |
| `mistrimulti-helper.exe` | The network helper. |
| `mistrimulti-steam-id.exe` | The Steam ID probe. |
| `MistriaMulti-<version>-Windows.zip` | For players: the four programs, `Install-Mod.bat`, the mod and `HOW-TO-PLAY.txt` in one `MistriaMulti/` folder. |
| `MistriaMulti-<version>-Linux.tar.gz` | For players: the four Linux programs, `install.sh`, the mod and `HOW-TO-PLAY.txt` in one `MistriaMulti/` folder. `./install.sh --update` downloads it and checks it against the `#linux-tar` line of `latest.txt`. |

The two player downloads are made by `scripts/make-player-packages.sh <windows bin> <linux bin> <out>` (also runnable locally
after the build scripts). The manager ignores them.

The binaries are **not committed to git**. `.github/workflows/release.yml` builds them from the tagged commit with the Linux
cross-build scripts (`build-updater.sh`, `build-launcher.sh`, `build-helper.sh`: NASM + lld, no Windows SDK), runs the test
suites, writes `latest.txt` with `scripts/make-release.sh --bin dist dist/latest.txt`, creates the release as a draft, uploads
the assets and only then publishes it as the latest release. The mod files are not assets: they are read from the tagged
commit.

To cut a release: bump `version` in `mod/mistrimulti/manifest.toml`, run `sh scripts/make-release.sh`, commit, then
`git tag v<version> && git push origin v<version>`. The workflow refuses a tag that differs from the manifest version, and CI
refuses a committed `release/latest.txt` that is stale. A manual run of the workflow (Actions > Release > Run workflow) builds
and tests everything and attaches the files to the run, without publishing.

## The list

```
version 0.2.0
<64 lowercase hex> mod/mistrimulti/manifest.toml
<64 lowercase hex> mod/mistrimulti/gml/MistriMultiBoot.gml
<64 lowercase hex> bin/MistriMulti.exe
<64 lowercase hex> bin/MistriMultiLauncher.exe
<64 lowercase hex> bin/mistrimulti-helper.exe
<64 lowercase hex> bin/mistrimulti-steam-id.exe
end 6
```

Blank lines and lines starting with `#` are ignored; CRLF is accepted. The `version` line comes first and is 1-4 numbers
separated by dots (`0.2`, `0.2.0.1`; no letters, so a version can never alter a URL). `end <n>` must be last and equal the
number of file lines, and the list must end with a newline, so a download that was cut anywhere is rejected. The committed
`release/latest.txt` lists the mod files only (CI checks it); older managers read it from the `main` branch, newer ones
ignore it.

## How the manager finds the downloads

The URLs are built by the manager; the list never supplies one. The `version` in the list selects the tag.

| What | Server | Path |
| --- | --- | --- |
| The list | `github.com` | `/tomrocksyou/MistriaMulti/releases/latest/download/latest.txt` |
| A mod file | `raw.githubusercontent.com` | `/tomrocksyou/MistriaMulti/v<version>/mod/mistrimulti/<file>` |
| A tool | `github.com` | `/tomrocksyou/MistriaMulti/releases/download/v<version>/<name>` |

Everything is HTTPS. Because both the mod files and the tools are addressed by the tag, a release is immutable: the list,
the mod files and the binaries cannot drift apart while someone updates (a CDN cache can never mix two releases). `latest`
only ever points at a published, non-draft, non-pre-release release. `MistriMulti.exe --urls <version> <file>` prints these
three URLs without any network access (the test suite checks them).

For tests the first command-line arguments override the server: `MistriMulti.exe <game folder> <host> <port> <https 0/1>
<path prefix> <steps> <result file>`. With an override everything comes from that one server: the list from
`<prefix>/release/latest.txt` and every file from `<prefix>/<path in the list>`.

## What the manager accepts

Nothing is installed unless the whole list is valid, every file that differs was downloaded and its SHA-256 matched, and
every file was staged. A path is accepted only as:

- `mod/mistrimulti/<components>`: installed under `<game>\mods\mistrimulti\`. Components use `A-Za-z0-9._-` only, none is empty,
  starts or ends with a dot, or is a Windows device name (`CON`, `NUL`, `COM1`...). No `..`, no `\`, no `:`, no drive letter,
  no absolute path, no 8.3 names, at most 160 characters.
- `bin/<name>` where `<name>` is exactly one of `MistriMulti.exe`, `MistriMultiLauncher.exe`, `mistrimulti-helper.exe`,
  `mistrimulti-steam-id.exe` (case sensitive): installed next to `MistriMulti.exe`.

Also rejected: duplicates, more than 200 files, upper-case or non-hex hashes, a list without `mod/mistrimulti/manifest.toml`, a
list or file larger than 1 MiB (lists: 30,000 bytes), a download that fails or is cut off.

Installing: each changed file is written as `<name>.new` next to its destination after its hash matched. Then, for each file,
the old file is renamed to `<name>.old` and the `.new` file renamed into place (a running program can be renamed but not
overwritten; this is how the manager replaces itself). `manifest.toml` is replaced last, so an interrupted update still shows
"update available". If any rename fails, every file already replaced is put back from its `.old`, new files are removed, and
`.new` files are deleted. When everything succeeded the `.old` files are deleted; one that belongs to a program that is still
running cannot be deleted, and is removed at the next start of the manager (together with any `.new` or `.old` of our four
tools left by a crash). A user is therefore never left without a working `MistriMulti.exe`: it is either the old one or the
new, verified one, and the old one is kept until the new one is in place.

An installed mod version that is newer than the published one (compared number by number, so `0.10.0` > `0.9.0` and `0.2` =
`0.2.0`) is reported as "newer" and is never updated. The tools carry no version of their own: they are compared by hash, so
an equal mod version with a stale tool still offers an update.

## The update flow for players

Windows, `MistriMulti.exe`: one button, **Update MistriMulti** = check, then update when something differs, then the MOMI step.
Linux: `./install.sh --update` or `mistrimulti-manager update` (the manager hands over to `mistrimulti-update.sh`, the copy of
`install.sh` that the installer keeps next to the programs). Both use the same rules (list validation, hashes, all or nothing).

Linux specifics (`install.sh`): needs `curl` or `wget` (HTTPS only; `--max-time`, `--max-filesize`); the list and each mod file are
validated like the Windows manager does (path rules, duplicates, footer, 30,000 byte list, 1 MiB files, at most 200 files). The
Linux programs are not in the list as files; the list carries one comment line, which Windows managers ignore:

```
version 0.4.7
#linux-tar <64 lowercase hex> MistriaMulti-0.4.7-Linux.tar.gz
<64 lowercase hex> mod/mistrimulti/manifest.toml
...
```

`scripts/make-release.sh --bin <dir> <out> <tar.gz>` writes that line (the workflow builds the player packages first). The script
downloads `releases/download/v<version>/MistriaMulti-<version>-Linux.tar.gz`, checks its SHA-256, extracts only the four program
names and `install.sh` (never anything else), then replaces the programs (copy to `.new`, rename) and rebuilds the game's
`mods/mistrimulti` folder from verified files (the old folder is kept until the new one is in place; a file that is no longer in
the release is dropped; `LICENSE` and `CONTACT.md` stay). A release without that line updates the mod files only. Nothing is changed
unless everything was downloaded and verified. Mod versions are compared number by number: a newer installed mod is not touched,
and a folder holding another mod is not touched.

For tests `MISTRIMULTI_RELEASE_BASE=<http://host:port>` replaces GitHub: the list is read from `<base>/release/latest.txt`, a mod file
from `<base>/mod/mistrimulti/<file>` and the archive from `<base>/dl/<name>`.

### The MOMI step

Facts about MOMI's command line, with sources and what could not be verified: [MOMI-NOTES.md](MOMI-NOTES.md). In short: the `-cli`
program with no arguments installs every mod in the mods folder (the GUI installs the ticked ones), finds the game itself, waits for
a key unless `EXIT_ON_COMPLETE=true`, and exits 0 even when it found no game.

- The player chooses MOMI's programs once; nothing is searched for or guessed. A program whose name does not contain `-cli` is never
  run as the installer. The installer is started with no arguments, in the game folder, with `EXIT_ON_COMPLETE=true`, no window and no
  input; it is given at most 5 minutes.
- Windows: the **Open MOMI** button remembers the window program in `%LOCALAPPDATA%\FieldsOfMistria\mod_data\mistrimulti\momi.cfg`
  and, if the player picks a `-cli` program in the file dialog, that one in `momi-cli.cfg` (UTF-16, one path each).
  `MISTRIMULTI_MOMI_EXE` / `MISTRIMULTI_MOMI_CLI_EXE` override them (tests). After an update that changed mod files the button asks
  "Run MOMI's installer for you?"; Yes runs it (and asks once whether it may also run without a question: file `momi-cli.auto`),
  No (or no `-cli` chosen) opens the window program, else the status says "press Open MOMI ... Install". Any failure ends in those
  words with the exit code. Hidden test mode: consent only with `MISTRIMULTI_MOMI_CONSENT=yes`.
- Linux: `./install.sh --momi-cli <path>` stores the path in `~/.local/share/mistrimulti/momi-cli.path` (an executable regular file,
  not a link, name with `-cli`); `--update` asks `Run it now? [y/N]` (no terminal or no answer = no), shows the last lines of the output
  (`momi.log` next to the programs) and the exit code. `--always` also creates `momi-cli.auto` (standing permission for runs without
  a terminal, below). `--momi-cli none` forgets both.
- A marker file `momi-pending` (Windows: in the mod data folder, Linux: next to the programs) is left when mod files changed and
  MOMI did not run, so the next update does the MOMI step even though the files are already current.

## Update without a window or a terminal: the result file

For programs that start an update (the in-game Update button): no questions are asked, progress and the result are written to a file.

| Platform | Command |
| --- | --- |
| Windows | `MistriMulti.exe --update <result file>` |
| Linux | `mistrimulti-manager update --result <result file>` (= `sh <programs>/mistrimulti-update.sh --update --result <file>`) |

The file is plain text, replaced atomically (`<file>.tmp`, then rename) at every change; lines `key=value`, UTF-8 / ASCII:

```
state=needs_momi
version=0.4.7
message=Updated. Close the game and press Install in MOMI, then start the game.
error=0
```

| `state` | Meaning |
| --- | --- |
| `checking` | looking for the latest release |
| `downloading` | the release is valid, files are being downloaded (`version` is known from here) |
| `installing` | files are being put in place (or MOMI's installer is running) |
| `done` | finished: up to date, only programs changed, a newer mod was left alone, or MOMI installed the mod (restart the game) |
| `needs_momi` | the mod files changed and MOMI has not installed them: close the game and press Install in MOMI |
| `failed` | nothing was changed; `error` and `message` say why |

`error`: `0`; for `failed` 13 game / mod folder not usable (nothing touched), 20 no network or no release, 21 invalid list, 22 download
or checksum failed, 23 a file could not be written or replaced (everything put back); for `needs_momi` 0 (installer not run), 30 the
installer reported a problem, 31 it was still running after 5 minutes, 32 it could not be started. `message` is one line of plain words
that can be shown as is. Exit status: 0 for `done` and `needs_momi`, otherwise the `error` code (Linux: 1 when a message is shown to a
person without `--result`). The call is bounded: network steps 30 s (Windows) / 120 s (Linux) each, MOMI 5 minutes.

MOMI's installer runs in this mode only if the player allowed it earlier without a question (Windows `momi-cli.auto`, Linux
`./install.sh --momi-cli <path> --always`) and the caller did not set `MISTRIMULTI_NO_MOMI=1`. A caller whose game is running should set
it: MOMI rewrites the game's data file. The mod files themselves are replaced even while the game runs. Assumption, not verified: the running
game does not read `mods/` (MOMI builds the game's data from it); on Windows a locked file makes the swap fail and roll back (`error=23`).

## The daily check (for the in-game "update available" notice)

`MistriMulti.exe --daily <mod data folder>` (Windows) and `mistrimulti-update.sh --daily <mod data folder>` (Linux) read the list at
most once a day (short timeouts: 5 s Windows, 4 s connect / 6 s total Linux; silent; nothing installed) and write
`<mod data folder>/update.json`: `{"v":1,"latest":"x.y.z","checked":<unix seconds>}`, replaced atomically. A line `check=off` in
`<mod data folder>/update.cfg` turns it off. Nothing starts these yet: the launcher is expected to start them detached at game start.

## Not verified

- Real GitHub: the repository is private, so the download from `github.com` / `raw.githubusercontent.com` has not been run.
  Redirects (a release download redirects to GitHub's CDN) rely on WinHTTP following them, which is its default.
- The release workflow has not run on GitHub; its steps are the commands used locally.
- The real MOMI and its command-line program (the tests use a stand-in that checks the arguments, the working folder and `EXIT_ON_COMPLETE`), and the Windows file dialog and message boxes (the tests use the environment overrides).
- Real GitHub for `install.sh --update` (curl / wget against the fake release server only), and the Linux archive hash line from a real workflow run.
- Managers older than this scheme cannot update themselves; download `MistriMulti.exe` once from a release.
