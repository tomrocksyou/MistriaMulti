# Solo-save isolation design

Grounded in the game's own scripts (read-only reference, not stored in this repo) and probe results.

## What the game does
- A save is one checksummed "vault" file: `<CONFIG_DIRECTORY>/saves/game-<id>-<slot|autosave>.sav`.
  `CONFIG_DIRECTORY` is a single global (`global.__config_directory`), `%LOCALAPPDATA%\FieldsOfMistria`.
- `SaveManager()` scans `<CONFIG_DIRECTORY>/saves`, opens each vault and builds `Setup.save_manager.manifest`.
  The title menu's Continue / Load Game read that manifest and call `title_menu.enter_game(LoadState.Load(bundle))`.
- `load_game(loader)` validates the vault checksum and rebuilds the world. `save_game(path)` writes a vault.
- The save holds world state (clock, calendar, weather, props, all location grids, farm, museum, daycare...)
  and the player (inventory, stats, skills, perks, inbox...).
- Steam Cloud syncs the `saves` folder (`steam_autocloud.vdf`).

## Constraints found
- Mod runtime has no sockets, no native calls, no scanning functions (see probes). Files + the ASM helper stay.
- Mods write text only (`save_text_file`); vault files are binary. Binary transfer belongs to the helper.

## Design
1. **Separate folder, not separate logic.** Multiplayer mode points `CONFIG_DIRECTORY` at
   `mod_data/mistrimulti/mp/` (its own `saves/`), rebuilds `Setup.save_manager`, and the game's normal
   load/save/delete UI then operates on multiplayer worlds only. Solo saves are never listed or written.
   On leaving multiplayer (or any failure) the original value is restored. Settings are written through
   the same variable, so the swap is held only while a multiplayer world is open.
2. **Host.** "Host multiplayer" copies a chosen solo save into `mp/saves/` (helper or launcher copies the
   binary file), then loads it from there. The solo original is untouched.
3. **Guest.** The host's helper sends its `.sav` to the guest's helper (chunked, checksummed, over the
   existing UDP link); the guest's helper writes it into the guest's `mp/saves/`; the guest loads that.
   Guests therefore start from the actual host world instead of a local one. Per-player records
   (inventory, appearance...) keep using the existing host-side player store.
4. **Safety net (done).** `scripts/SaveGuard.ps1` backs up solo saves before every launch and restores
   guest changes afterwards, so a bug in 1-3 cannot lose solo progress.

## Verified
`probes/mmprobe_saves` on the real game (title screen, `game.title_entered`): `CONFIG_DIRECTORY` is readable and
assignable, `Setup.save_manager = new SaveManager()` rebuilds the list from the new folder (1 save -> 0 saves) and
restores cleanly.

## Implemented
`mod/mistrimulti/gml/MistriMultiSaveSpace.gml`: when `control.json` arms a host/join session, the title-entry hook points
`CONFIG_DIRECTORY` at `<config>/multiplayer`, rebuilds the save manager and the Load-menu list. Any failure restores the
solo folder. Solo and multiplayer worlds therefore never share a save list.

## Known side effects / still to do
- `settings.json` is also resolved through `CONFIG_DIRECTORY`, so settings changed during a multiplayer session are written
  to the multiplayer folder (solo settings are untouched).
- Guest saves are still vetoed (`game.save_guard`) until the host-world transfer exists.
- No Multiplayer button yet: multiplayer is chosen by launching with Host.bat / Join.bat.
- Host-world transfer to guests (helper file transfer) is not built.
