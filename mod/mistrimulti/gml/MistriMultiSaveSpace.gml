// Singleplayer / multiplayer save spaces.
//
// Solo saves live in <config>/saves. Multiplayer worlds live in <config>/multiplayer/saves.
// The game finds saves through one global (CONFIG_DIRECTORY), so switching spaces = pointing it at
// the other folder and rebuilding Setup's save list. The title screen always starts in the solo space.
// New Game and Load Game ask "Singleplayer or Multiplayer?" first; Multiplayer needs the helper to be
// running (Play.bat), because a mod cannot start programs.
function __mistrimulti_savespace() {
    if (global[$ "__mistrimulti_savespace"] == undefined) {
        global.__mistrimulti_savespace = {
            solo_dir: undefined, active: false, title_menu: undefined,
            orig_enter_game: undefined, orig_transition_to: undefined, choosing: false, error: "",
        };
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
// builds for the Load menu, because the game built it before this code could redirect the folder.
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
                header.farm_name = string(header.farm_name) + (__mistrimulti_savespace().active ? "  [Multi]" : "  [Single]");
                Setup.load_menu_data.push(header);
            } catch (e) { fail = true; }
        }
        if (fail) {
            loader.mark_invalid();
            Setup.save_manager.manifest.remove(path);
        }
    }
}

// Points the game at the multiplayer or the solo save folder and refreshes its save list.
function mistrimulti_savespace_set(multiplayer) {
    var s = __mistrimulti_savespace();
    if (s.solo_dir == undefined) s.solo_dir = CONFIG_DIRECTORY;
    vault_close_all_vaults();
    CONFIG_DIRECTORY = multiplayer ? s.solo_dir + "/multiplayer" : s.solo_dir;
    Setup.save_manager = new SaveManager();
    s.active = multiplayer;
    mistrimulti_savespace_rebuild_menu();
    mmapi_log_info("mistrimulti", (multiplayer ? "Multiplayer" : "Singleplayer") + " save space: " + CONFIG_DIRECTORY);
    mmapi_log_flush("mistrimulti");
}

// Switches space; on failure puts the solo folder back so solo saves are never exposed to a session.
function mistrimulti_savespace_try_set(multiplayer) {
    var s = __mistrimulti_savespace();
    try { mistrimulti_savespace_set(multiplayer); return true; }
    catch (e) {
        s.error = string(e);
        mmapi_log_error("mistrimulti", "Save space switch failed: " + s.error);
        try { if (s.solo_dir != undefined) { CONFIG_DIRECTORY = s.solo_dir; mistrimulti_savespace_set(false); } }
        catch (e2) { mmapi_log_error("mistrimulti", "Save space restore failed: " + string(e2)); }
        s.active = false;
        return false;
    }
}

function mistrimulti_savespace_popup(title_key, body_key) {
    var popup = popup_creator(title_key, body_key);
    popup.create_button("misc_local/cancel");
    popup.spawn();
}

// kind: "new" continues entering a new game, "load" opens the Load menu.
function mistrimulti_savespace_choose(kind, arg) {
    var s = __mistrimulti_savespace();
    if (s.choosing) return;
    s.choosing = true;
    var mcp = new MultipleChoicePopup("mistrimulti/choose_mode");
    mcp.option("mistrimulti/singleplayer", mistrimulti_savespace_chosen, [kind, false, arg]);
    mcp.option("mistrimulti/multiplayer", mistrimulti_savespace_chosen, [kind, true, arg]);
}

function mistrimulti_savespace_chosen(kind, multiplayer, arg) {
    var s = __mistrimulti_savespace();
    s.choosing = false;
    if (multiplayer && !mistrimulti_game_supported()) { mistrimulti_savespace_popup("mistrimulti/offline_title", "mistrimulti/offline_version_body"); return; }
    if (multiplayer && !mistrimulti_savespace_armed()) { mistrimulti_savespace_popup("mistrimulti/offline_title", "mistrimulti/needs_helper_body"); return; }
    if (!mistrimulti_savespace_try_set(multiplayer)) return;
    if (kind == "new") s.orig_enter_game(arg);
    else s.orig_transition_to(Menu.Load);
}

// Wrapper installed over TitleMenu.enter_game. New Game asks first; Continue / Load keep the current space.
function mistrimulti_title_enter_game(load_state) {
    var s = __mistrimulti_savespace();
    try {
        if (load_state.type == LoadStateId.New) { mistrimulti_savespace_choose("new", load_state); return; }
    } catch (e) { mmapi_log_error("mistrimulti", "enter_game wrapper failed: " + string(e)); }
    s.orig_enter_game(load_state);
}

// Wrapper installed over TitleMenu.transition_to. Opening the Load menu asks which worlds to list.
function mistrimulti_title_transition_to(target) {
    var s = __mistrimulti_savespace();
    try {
        if (target == Menu.Load && !s.choosing) { mistrimulti_savespace_choose("load", undefined); return; }
    } catch (e) { mmapi_log_error("mistrimulti", "transition_to wrapper failed: " + string(e)); }
    s.orig_transition_to(target);
}

// Fires right after the title menu spawns, before its buttons are built.
function mistrimulti_menu_opened(ctx) {
    if (ctx.kind != Menu.Title) return;
    var s = __mistrimulti_savespace();
    try {
        var menu = ctx.menu;
        s.title_menu = menu;
        s.orig_enter_game = menu.enter_game;
        s.orig_transition_to = menu.transition_to;
        menu.enter_game = mistrimulti_title_enter_game;
        menu.transition_to = mistrimulti_title_transition_to;
    } catch (e) {
        s.error = string(e);
        mmapi_log_error("mistrimulti", "Title menu wrap failed (solo behaviour unchanged): " + s.error);
    }
    mmapi_log_flush("mistrimulti");
}

// Every title entry starts in the solo space; a session that just ended is torn down here.
function mistrimulti_title_entered(ctx) {
    var s = __mistrimulti_savespace();
    s.choosing = false;
    var rt = __mistrimulti_runtime();
    rt.enabled = false;
    rt.initialized = false;
    if (s.active) { mistrimulti_savespace_try_set(false); return; }
    try { mistrimulti_savespace_rebuild_menu(); }   // tag the solo list with [Single]
    catch (e) { mmapi_log_error("mistrimulti", "Could not label the solo save list: " + string(e)); }
}

function mistrimulti_local_missing(value, ctx) {
    switch (ctx.key) {
        case "mistrimulti/choose_mode": return "Singleplayer or Multiplayer?";
        case "mistrimulti/singleplayer": return "Singleplayer";
        case "mistrimulti/multiplayer": return "Multiplayer";
        case "mistrimulti/offline_title": return "Multiplayer is offline";
        case "mistrimulti/offline_version_body": return "The game was updated and MistriMulti has not been updated for it yet.";
        case "mistrimulti/needs_helper_body": return "Multiplayer is not set up. Run Play.bat once, then start the game from Steam.";
    }
    return undefined;
}
