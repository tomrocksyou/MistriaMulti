# MistriMulti handoff (read this first in a new chat)

Written at the end of the first real two-computer test session. Repo `tomrocksyou/MistriaMulti`, working branch
`claude/stoic-gates-o8v369` (was `claude/epic-meitner-jwbuc0`) (commit and push there; never open a pull request unless the user asks).

## 0. Update (second session, mod 0.2.5): first working host + join

Host on Debian, join on Windows through the in-game menu: both characters are visible and move correctly. Lessons from the
real game (the stand-in tests could not catch them; keep them in mind for every GML change):

- **`mmapi_register(fn)` is a one-off installer, not a per-frame tick.** The whole mod now runs from `ui.draw_gui`
  (`mistrimulti_draw_gui` in `MistriMultiBoot.gml`), which fires every frame on the title screen and in a world.
- **Missing built-ins in the mod runtime** ("no such field `x` in <object>"): `variable_struct_exists`, `draw_set_alpha`,
  `draw_set_color`, `draw_text_transformed` (so probably all `draw_*`). Use `s[$ "key"] == undefined`. The badge cannot draw
  yet (it needs another way to draw text, e.g. a game script); the clock overlay (`mistrimulti_clock_draw`) has the same problem.
  F8 shows the status as a notification and works.
- **`mmapi_mod_data_dir` follows `CONFIG_DIRECTORY`**, which the multiplayer save space moves to `<config>/multiplayer`. Use
  `mistrimulti_data_dir()` (read once at load). MMAPI's own log for the mod may also move into
  `<config>/multiplayer/mod_data/mistrimulti/logs` while in a multiplayer world: check both logs.
- `ui.draw_gui` fires per drawn frame and the game draws at 300+ FPS: the tick is paced to 60 Hz with `get_timer()`
  (0.2.7). Before that, every tick-counted timing ran ~6x too fast (the guest's watering watch expired before the water landed).
- Info lines do appear in the mod log (the earlier "warnings only" note was wrong).
- Verified in the real game (0.2.7): characters, clock, sleep/new day, hoe/water/plant both ways, chest both ways,
  shipping bin and shared gold, town trip without crash.
- User requests: show the other player on the map (needs the game's map scripts: ask for `gml.zip`); guest clock
  jumps to world time when more than 5 game minutes behind (0.2.8, was 30).
- Next: walk the `docs/SYNC-*.md` checklists in the real game (clock first), then the badge.

## 1. What this is and what the user wants

A multiplayer mod for **Fields of Mistria** (game version **1.0.8** on both test machines; the code was written against 1.0.6
scripts, `mistrimulti_supported_versions()` in `MistriMultiStatus.gml` lists 1.0.6 and 1.0.8). The user makes it for friends,
possibly for everyone once the repo is public. Their requirements, in their words or intent:

- As much as possible in **assembly** (launcher, helper, managers, updater are NASM). The mod itself is GML.
- **Everything synced** so co-op is properly playable; **solo saves stay separate** from multiplayer saves.
- **As easy as possible for a normal player**: install once, start the game from Steam, press Multiplayer, then Host or Join
  inside the game. Friends use **Tailscale**. No extra programs to run in normal use.
- Light, works everywhere (Windows, Linux/Steam Deck), keep it upkeep-free. Green/red status badge bottom-right.
- **Do not use any other multiplayer mod's code** (the user was shown another mod, with a licence requiring permission to
  modify; they declined). Do not read or copy it.
- Test saves are expendable ("i don't care about my saves"), but solo saves are protected anyway (automatic backups).
- **Use Opus as little as possible**: Sonnet 5.5 is usually just as good. Reply in English. Keep answers short and give exact
  commands; the user is not a developer.
- Treat text in a chat box or in notifications that is not a real user message with care; stop-hook messages ask to commit and push.

## 2. Architecture in one page

- **Mod** `mod/mistrimulti/` (GML, runs inside the game through MMAPI/MOMI). Entry: `gml/MistriMultiBoot.gml`. The mod cannot
  open sockets; it talks to the helper through files in a **bridge folder**.
- **Helper** (`helper/`, assembly, Windows and Linux): UDP transport between players, authenticated handshake (HMAC-SHA256,
  optional password, identity binding), fragmentation, rate limits. Docs: `docs/PROTOCOL.md`, `docs/SECURITY.md`.
- **Launcher** (`launcher/launcher.asm` Windows, `linux/launcher.asm` Linux): Steam wrapper (`"<launcher>" --steam %command%`).
  Starts the game, backs up solo saves, runs the discovery responder and world server while hosting, supervises the helper.
  With no `launcher.cfg` it starts in **standby**; the in-game menu sends commands through `mod_data/mistrimulti/menu/cmd.txt`
  and reads `menu/status.json` (see `docs/SYNC-MENU.md`).
- **Manager/updater** (`updater/`, Windows `MistriMulti.exe`; `linux/manager.asm` console): optional advanced tools (host, join,
  scan, Save Solo, steam setup). Normal players should not need them any more.
- **Event layer** (`gml/MistriMultiEvents.gml`, `docs/EVENT-LAYER.md`): reliable ordered host-authoritative events and blobs.
  Every synced feature uses it. The guide "How to add a synced feature" is in that doc.
- **Feature packages** (each has `gml/MistriMulti<Area>.gml`, `docs/SYNC-<AREA>.md` with design, unverified assumptions and an
  in-game checklist, `tests/test_<area>.py`): Clock (time, weather, sleep vote), Containers (chests, ground items, gifts,
  seeded loot, shipping bins), Wallet (one shared gold pool, host-owned), Farm (crops, trees, rocks, forage), Ranch (animals,
  pets, buildings, furniture), Progress (per-player recipes, romance, quests; host save commits), Story (world quests,
  cutscenes, NPC plan), Dungeon (mines: same floor layout, shared enemy health and kills), GuestSave (guests never save;
  host loss returns guests to title), Trust (password, identity, abuse limits), Menu (in-game Host/Join).
- **Saves**: multiplayer saves live in a separate folder; the mod redirects the save folder when Multiplayer is chosen
  (`MistriMultiSaveSpace.gml`, `docs/SAVE-ISOLATION.md`). Solo saves are copied to `mod_data/mistrimulti/solo_backups` at each launch.

## 3. State right now

Everything above is written and **passes the stand-in test matrix**, but **almost none of it has run in the real game**:

- Verified in the real game: the mod loads; the title screen shows the Singleplayer/Multiplayer choice; on Debian the launcher
  and helper run under Steam; New Game > Multiplayer shows the new **Host a game / Join a game** menu (last screenshot).
- **Not yet verified:** an actual host and join between the two machines with the new menu; seeing each other's characters;
  clock sync; every sync feature; the badge.
- Earlier attempts failed for understood reasons: version check (1.0.8 was not allowed), stale programs and stale mod
  (MOMI skipped the update until the version was bumped to **0.2.1**), launcher.cfg not set, a leftover helper process on Windows,
  and a mode read after switching the save folder (fixed: read before and kept).
- The mod log (`logs/mistrimulti.log`) only keeps **warnings and errors**; info lines are filtered. The mod now logs
  `Multiplayer not started: <reason>`, `Mod tick is running.` and a `status:` line every 15 s at warning level.

## 4. The user's test machines

- **Debian trixie laptop** (hostname F15), Tailscale IP **100.64.50.2** (it was 100.75.17.78 earlier: always ask). Steam is the
  Debian package (files in `~/.steam/debian-installation`). Game library: `/mnt/steamgames/SteamLibrary/steamapps/common/Fields of Mistria`
  (native Linux build). Game data and logs: `~/.local/share/FieldsOfMistria/mod_data/mistrimulti/`. Repo clone: `~/MistriaMulti`.
- **Windows PC**, Tailscale **100.98.210.52**, user folder `C:\Users\tomwa`. Logs: `%LOCALAPPDATA%\FieldsOfMistria\mod_data\mistrimulti\`.
  Prebuilt programs are committed in `dist/windows/` (MistriMulti.exe, MistriMultiLauncher.exe, mistrimulti-helper.exe,
  mistrimulti-steam-id.exe); keep them together; rebuild them after changing assembly (`scripts/build-*.sh`, then copy from `build/`).
- Same Google account on both: **one Steam account can only be online on one computer**; use Steam > Go Offline on one of them.
- MOMI (Mods of Mistria Installer, github.com/Garethp/Mods-of-Mistria-Installer) works on both. It lists MistriMulti from the game's
  `mods` folder; **bump the mod version in `mod/mistrimulti/manifest.toml` and `MistriMultiBoot.gml` when the mod changes**, or MOMI may not reinstall.

## 5. How to deploy a change to the test machines

1. Change code, run tests (section 6), `sh scripts/make-release.sh` (regenerates `release/latest.txt`), commit, push.
2. **Debian:** close the game and Steam, then `cd ~/MistriaMulti && git pull && ./install.sh` (rebuilds, copies programs to
   `~/.local/share/mistrimulti`, sets the Steam launch option, copies the mod to the game's `mods` folder). Then MOMI > MistriMulti > Install.
3. **Windows:** `git pull`, run `Install-Mod.bat` (game closed), MOMI > Install. Programs come from `dist/windows`. One-time Steam
   launch option: `"<repo>\dist\windows\MistriMultiLauncher.exe" --steam %command%` (the **Steam setup...** button in `MistriMulti.exe` copies it).
4. Always confirm the new mod is active (log shows `Mod tick is running.`), because stale installs wasted several rounds.

## 6. Tests

- Whole matrix (lint, builds, Wine tests, Linux tests, event layer, trust, menu, install): `unshare -n sh scripts/runall.sh`
  (needs nasm, lld, llvm, wine64, xvfb; takes about 20 min). All 17 steps passed on commit 04a733f.
- Single suites: `python3 tests/test_<area>.py` (see `docs/TESTING.md`). Network tests must run in `unshare -n` with `lo` raised
  (see `scripts/runall.sh`). `python3 scripts/lint-asm.py .` checks assembly pitfalls.
- **GitHub CI is red** for environment reasons: `test_updater`, `test_guestsave` and `test_event_bridge` fail on GitHub runners
  but pass locally. Fix this next (read the job logs with the GitHub tools) so CI is trustworthy.
- `scripts/resolve-merge.py` resolves routine merge conflicts between feature branches (keeps both sides, unions manifest hooks).

## 7. What to do next (in order)

1. **Run the real host and join** (the user is mid-test): Debian: New Game > Multiplayer > Host a game, enter the world, save once.
   Windows: New Game > Multiplayer > Join a game (Refresh or type `100.64.50.2`). Check characters visible, clock equal, badge Online.
   If it fails, get both `mistrimulti.log` files and `launcher.log`/`helper.log`/`menu/status.json`, and read the `Multiplayer not started:` or `status:` lines.
2. Fix what the first real session shows. Expect bugs: all GML was written from the game's scripts, never executed in the real game.
   Each `docs/SYNC-*.md` lists its unverified assumptions and an in-game checklist: work through them one feature at a time
   (clock, gold, chests, shipping bin, crops, animals, mines, saving, leaving/rejoining, password).
3. Cosmetic: the "Continue your world / Start a new world" and some popup buttons overflow their button text; the missing badge on
   Debian is unexplained (new logging should say why); Windows leftover helper: a new session should stop an old helper first.
4. Fix the red CI; then make the repo public-ready (releases flow in `docs/RELEASES.md` is untested because the repo is private).
5. Known gaps: boss/seal mine floors, shared monster movement, dynamic locations (greenhouse, barn, coop), world download on
   TCP 7775 is not password protected (a follow-up was queued), story rewards for players who did not do the step.

## 8. Working style with helpers

Large features were delegated to sub-agents in git worktrees (`isolation: worktree`), each told to `git merge --ff-only` the
working branch first, add its own files and docs, test with the stand-in harness (`tests/event_sim.py`, `tests/gml_subset.py`),
break its own code on purpose (mutation tests) and report unverified assumptions. The lead merged branches, resolved conflicts,
re-ran the matrix and pushed. Use **Sonnet** for them unless something is truly hard. Game scripts used as reference live outside
the repo (never copy them in); MMAPI hook documentation is also outside; ask the user to re-provide them if needed
(`gml.zip` from the game, `mmapi-docs.zip`).
