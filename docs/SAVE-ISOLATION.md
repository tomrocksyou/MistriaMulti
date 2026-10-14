# Solo-save isolation design

Grounded in the game's own scripts (read-only reference, not stored in this repo) and probe results.

## What the game does
- A save is one checksummed "vault" file: `<CONFIG_DIRECTORY>/saves/game-<id>-<slot|autosave>.sav`.
  `CONFIG_DIRECTORY` is a single global (`global.__config_directory`, assigned from GameMaker's `game_save_id` in
  `SerdeUtils.gml`): `%LOCALAPPDATA%\FieldsOfMistria` on Windows. On Linux the scripts do not say where the runtime puts it;
  the Linux tools search the usual places and `MISTRIMULTI_DATA_DIR` overrides (see `README.md`, "Where the game keeps its files").
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
4. **Safety net (done).** The launcher copies the solo saves to `mod_data/mistrimulti/solo_backups/<timestamp>` before
   every launch (newest 10 kept). It never restores or changes saves: multiplayer uses its own folder, so a rollback
   would only destroy legitimate solo progress.

## Verified
`probes/mmprobe_saves` on the real game (title screen, `game.title_entered`): `CONFIG_DIRECTORY` is readable and
assignable, `Setup.save_manager = new SaveManager()` rebuilds the list from the new folder (1 save -> 0 saves) and
restores cleanly.

## Implemented
`mod/mistrimulti/gml/MistriMultiSaveSpace.gml`. Every title entry starts in the solo space. The title menu's `enter_game`
and `transition_to` are wrapped (via `ui.menu_opened`): New Game and Load Game first ask "Singleplayer or Multiplayer?"
(the game's own `MultipleChoicePopup`, text supplied through `local.missing`). The choice points `CONFIG_DIRECTORY` at
`<config>/saves` or `<config>/multiplayer/saves` and rebuilds the save list. The multiplayer runtime only starts inside the
multiplayer space; choosing Multiplayer without the helper running shows an explanatory popup.
Any failure restores the solo folder. Quitting to the title tears the session down.

## World transfer (implemented, untested in the real game)
The host's launcher serves the newest multiplayer save over TCP 7775 (see PROTOCOL.md). **Join selected** in the manager
downloads it into the guest's `multiplayer/saves` folder, and the guest's launcher refreshes it as the game starts. On a guest,
**New Game -> Multiplayer** then loads that world (`LoadState.Load`) instead of creating a new one. A host with an earlier
multiplayer world is asked whether to continue it or start a new one. The world is a copy as of the host's last save, so the
host should save (sleep) before friends join; live state beyond terrain and players is not synchronised yet.

## Known side effects / still to do
- `settings.json` is also resolved through `CONFIG_DIRECTORY`, so settings changed during a multiplayer session are written
  to the multiplayer folder (solo settings are untouched).
- A guest's game never saves: every save is vetoed and the attempt sends the character to the host instead, a lost host returns the
  guest to the title, and no multiplayer save may land in the solo folder (`docs/SYNC-GUESTSAVE.md`).
- A mod cannot launch programs, so the helper is started by `MistriMultiLauncher.exe --steam` (the Steam launch option),
  or by `mistrimulti-launcher --steam` on Linux (same behaviour; backup folder names are UTC there).
- If there are no solo saves the title screen has no Load Game button, so existing multiplayer worlds are unreachable until one solo save exists.
- Untested: wrapping the title menu's methods, popup text injection, and teardown on quit-to-title.
- Host-world transfer to guests (helper file transfer) is not built.
