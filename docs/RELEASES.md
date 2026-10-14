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
| `MistriaMulti-<version>-Linux.tar.gz` | For players: the four Linux programs, `install.sh`, the mod and `HOW-TO-PLAY.txt` in one `MistriaMulti/` folder. |

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

## MOMI: what is known and what is not

The manager's **Open MOMI** button opens MOMI and shows the steps (close the game, select MistriaMulti, click Install). It
does not run MOMI's command line. Reasons, from the files provided (the MOMI repository listing and the MMAPI docs):

- Known: MOMI has a command-line project, `ModsOfMistriaCommandLine` (`Program.cs`); the README of this project calls its
  built program `ModsOfMistriaInstaller-cli.exe`. The MMAPI docs say "run the installer (GUI or command line)" to install a
  mod, and that removing a mod and running the installer again is repair.
- Documented command-line flags are only for checks that write nothing: `--lint <mod folder> [pristine zip] [--strict-lints]
  [--compile-check on|off|require]` (exit 0 would install, 1 would be skipped, 2 could not run, always with an **absolute**
  mod path), `--seam-check`, `--reseed-check`, `--seam-diff`, and `--fail-on-skip`.
- Not documented, so not guessed: the command (or flags) that performs an install, whether it needs the game folder, whether
  an install without arguments installs every mod in `mods/`, its exit codes, where MOMI is installed, and the file name of
  the window program.

So the button needs the player to choose the MOMI program once (a file dialog); the choice is stored in
`%LOCALAPPDATA%\FieldsOfMistria\mod_data\mistrimulti\momi.cfg` (UTF-16, one path). A program whose name ends in `-cli.exe` is
refused. `MISTRIMULTI_MOMI_EXE` overrides the stored path (used by the tests). MOMI is started with no arguments.
Once the install command is confirmed on a real machine (`ModsOfMistriaInstaller-cli.exe --help`, or the MOMI source), the
fallback in `updater/momi.inc` (`momi_open`) is the single place to replace.

## Not verified

- Real GitHub: the repository is private, so the download from `github.com` / `raw.githubusercontent.com` has not been run.
  Redirects (a release download redirects to GitHub's CDN) rely on WinHTTP following them, which is its default.
- The release workflow has not run on GitHub; its steps are the commands used locally.
- The real MOMI, and the file dialog (the tests use the environment override and the stored path).
- Managers older than this scheme cannot update themselves; download `MistriMulti.exe` once from a release.
