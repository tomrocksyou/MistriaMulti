// Multiplayer save space. When a multiplayer session is armed (control.json), the game's save
// folder is redirected to <config>/multiplayer. The game's own title screen, Load menu and
// save/delete code then only ever see multiplayer worlds; solo saves are never listed or written.
// The redirect is applied from game.title_entered, before the title menu's start chain decides
// whether Continue/Load Game exist. It is idempotent: quit-to-title re-enters with the same folder.
function __mistrimulti_savespace() {
    if (global[$ "__mistrimulti_savespace"] == undefined) {
        global.__mistrimulti_savespace = { solo_dir: undefined, active: false, error: "" };
    }
    return global.__mistrimulti_savespace;
}

function mistrimulti_savespace_armed() {
    var control = mmapi_mod_data_dir("mistrimulti") + "/control.json";
    if (!file_exists(control)) return false;
    var cfg = try_read_json_file(control);
    return is_struct(cfg) && cfg[$ "enabled"] == true && (cfg[$ "mode"] == "host" || cfg[$ "mode"] == "join");
}

// Rebuilds Setup.load_menu_data from the current save manager. Mirrors the list Setup's create
// builds for the Load menu, because the game built it from the solo folder before this hook ran.
function mistrimulti_savespace_rebuild_menu() {
    Setup.load_menu_data = List();
    var saves = Setup.save_manager.get_saves_ordered();
    for (var i = 0; i < array_length(saves); i++) {
        var path = saves[i];
        var load_bundle = Setup.save_manager.manifest.get(path);
        var loader = load_bundle.loader;
        var fail = false;
        var header = loader.load_file("header");
        if (header == undefined) {
            fail = true;
        } else {
            try {
                var info = loader.load_file("info");
                if (version_is_ahead(string_to_version("0.11.6"), info.version)) zero_eleven_six_hair_patch(header.preset);
                header.preset = player_animation_assets_deserialize(header.preset);
                header.load_bundle = load_bundle;
                header.path = path;
                Setup.load_menu_data.push(header);
            } catch (e) { fail = true; }
        }
        if (fail) {
            loader.mark_invalid();
            Setup.save_manager.manifest.remove(path);
        }
    }
}

function mistrimulti_title_entered(ctx) {
    var s = __mistrimulti_savespace();
    try {
        if (!mistrimulti_savespace_armed()) { s.active = false; return; }
        if (s.solo_dir == undefined) s.solo_dir = CONFIG_DIRECTORY;
        vault_close_all_vaults();
        CONFIG_DIRECTORY = s.solo_dir + "/multiplayer";
        Setup.save_manager = new SaveManager();
        mistrimulti_savespace_rebuild_menu();
        s.active = true;
        s.error = "";
        mmapi_log_info("mistrimulti", "Multiplayer save space active: " + CONFIG_DIRECTORY);
    } catch (e) {
        // Fail safe: put the solo folder back so a failed redirect can never expose solo saves to a session.
        s.error = string(e);
        mmapi_log_error("mistrimulti", "Save space redirect failed: " + s.error);
        try {
            if (s.solo_dir != undefined) {
                CONFIG_DIRECTORY = s.solo_dir;
                vault_close_all_vaults();
                Setup.save_manager = new SaveManager();
                mistrimulti_savespace_rebuild_menu();
            }
        } catch (e2) { mmapi_log_error("mistrimulti", "Save space restore failed: " + string(e2)); }
        s.active = false;
    }
    mmapi_log_flush("mistrimulti");
}
