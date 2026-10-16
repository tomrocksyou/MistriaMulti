// Singleplayer / multiplayer save spaces.
//
// Solo saves live in <config>/saves. Multiplayer worlds live in <config>/multiplayer/saves.
// The game finds saves through one global (CONFIG_DIRECTORY), so switching spaces = pointing it at
// the other folder and rebuilding Setup's save list. The title screen always starts in the solo space.
// New Game and Load Game ask "Singleplayer or Multiplayer?" first. Multiplayer then shows "Host a game / Join a game"
// (MistriMultiMenu.gml), which asks the launcher (started by Steam) to host or join; nothing has to be set up beforehand.
function __mistrimulti_savespace() {
    if (global[$ "__mistrimulti_savespace"] == undefined) {
        global.__mistrimulti_savespace = {
            solo_dir: undefined, active: false, title_menu: undefined,
            orig_enter_game: undefined, orig_transition_to: undefined, choosing: false, error: "", entry: "",
        };
    }
    return global.__mistrimulti_savespace;
}

function mistrimulti_savespace_armed() {
    var control = mistrimulti_data_dir() + "/control.json";
    if (!file_exists(control)) return false;
    var cfg = try_read_json_file(control);
    return is_struct(cfg) && cfg[$ "enabled"] == true && (cfg[$ "mode"] == "host" || cfg[$ "mode"] == "join");
}

// "host", "join" or "" from control.json (written by the launcher for this session)
function mistrimulti_savespace_mode() {
    var kept = __mistrimulti_savespace();
    if (kept.active && is_string(kept[$ "mode"]) && kept.mode != "") return kept.mode;   // read before the save folder switch
    var control = mistrimulti_data_dir() + "/control.json";
    if (!file_exists(control)) return "";
    var cfg = try_read_json_file(control);
    if (!is_struct(cfg) || cfg[$ "enabled"] != true) return "";
    return is_string(cfg[$ "mode"]) ? cfg.mode : "";
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
                // A guest sees its own character of the world in the list, not the host's that the downloaded save holds.
                if (__mistrimulti_savespace().active && mistrimulti_savespace_mode() == "join") mistrimulti_charcache_apply(header, load_bundle[$ "game_ident"]);
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

// The game's choice buttons are 97 px wide, too narrow for long labels (keep them under about 18 characters): use the popup's width.
function mistrimulti_widen_choices(mcp) {
    try {
        var w = mcp.popup.backplate.get_width() - 16;
        if (!is_real(w) || w <= 97) return;
        for (var i = 0; i < mcp.buttons.count(); i++) mcp.buttons.get(i).set_width(w);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_widen", "mistrimulti", "Could not widen the popup buttons: " + string(e));
    }
}

// Text arguments are local keys; pass literal text through mistrimulti_menu_t().
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
    mistrimulti_widen_choices(mcp);
}

function mistrimulti_savespace_chosen(kind, multiplayer, arg) {
    var s = __mistrimulti_savespace();
    s.choosing = false;
    if (multiplayer && !mistrimulti_game_supported()) { mistrimulti_savespace_popup("mistrimulti/offline_title", "mistrimulti/offline_version_body"); return; }
    if (multiplayer) {
        // Host a game / Join a game; the flow calls mistrimulti_savespace_enter when the player starts playing.
        try { mistrimulti_menu_begin(kind, arg); }
        catch (e) {
            s.choosing = false;
            mmapi_log_error("mistrimulti", "Multiplayer menu failed: " + string(e));
            mistrimulti_savespace_popup("mistrimulti/offline_title", "mistrimulti/menu_failed_body");
        }
        return;
    }
    if (!mistrimulti_savespace_try_set(false)) return;
    if (kind == "new") s.orig_enter_game(arg);
    else s.orig_transition_to(Menu.Load);
}

// The player chose to start playing (the launcher hosts, or the host's world was downloaded): switch to the multiplayer saves.
function mistrimulti_savespace_enter(kind, arg) {
    var s = __mistrimulti_savespace();
    var mode_before = mistrimulti_savespace_mode();   // read before the save folder switch, kept for the session
    if (!mistrimulti_savespace_try_set(true)) {
        mistrimulti_menu_send("stop", undefined);
        mistrimulti_savespace_popup("mistrimulti/offline_title", "mistrimulti/menu_failed_body");
        return;
    }
    s.mode = mode_before;
    s.entry = kind;   // "new" (New Game > Multiplayer) or "load" (Load Game > Multiplayer): the character logic reads it for the session
    if (kind == "new") mistrimulti_savespace_enter_multiplayer(arg);
    else s.orig_transition_to(Menu.Load);
}

// The newest world in the multiplayer folder (the host's downloaded world for a guest), or undefined.
function mistrimulti_savespace_newest_world() {
    var paths = Setup.save_manager.get_saves_ordered();
    if (array_length(paths) == 0) return undefined;
    return Setup.save_manager.manifest.get(paths[0]);
}

// New Game -> Multiplayer. A guest enters the host's world (downloaded by the manager or at game start).
// A host with an earlier multiplayer world chooses between continuing it and starting a new one.
function mistrimulti_savespace_enter_multiplayer(new_state) {
    var s = __mistrimulti_savespace();
    var world = mistrimulti_savespace_newest_world();
    if (mistrimulti_savespace_mode() == "join") {
        if (world == undefined) {
            mistrimulti_savespace_try_set(false);
            mistrimulti_menu_send("stop", undefined);
            mistrimulti_savespace_popup("mistrimulti/no_world_title", "mistrimulti/no_world_body");
            return;
        }
        s.orig_enter_game(LoadState.Load(world));
        return;
    }
    if (world == undefined) { mistrimulti_world_options_ask(new_state); return; }
    var mcp = new MultipleChoicePopup("mistrimulti/host_world");
    mcp.option("mistrimulti/continue_world", mistrimulti_savespace_host_choice, [true, new_state]);
    mcp.option("mistrimulti/new_world", mistrimulti_savespace_host_choice, [false, new_state]);
    mistrimulti_widen_choices(mcp);
}

function mistrimulti_savespace_host_choice(continue_world, new_state) {
    var s = __mistrimulti_savespace();
    var world = mistrimulti_savespace_newest_world();
    if (continue_world && world != undefined) s.orig_enter_game(LoadState.Load(world));
    else mistrimulti_savespace_later(mistrimulti_world_options_ask, new_state);   // after this popup has closed
}

// ---- New world options (MistriMultiHearts.gml stores and applies them) ------------------------------------------

function mistrimulti_world_options_ask(new_state) {
    mistrimulti_world_options_pending(mistrimulti_world_options_default());
    var mcp = new MultipleChoicePopup("mistrimulti/opt_hearts_title");
    mcp.option("mistrimulti/opt_hearts_own", mistrimulti_world_options_hearts, ["own", new_state]);
    mcp.option("mistrimulti/opt_hearts_shared", mistrimulti_world_options_hearts, ["shared", new_state]);
    mistrimulti_widen_choices(mcp);
}

function mistrimulti_world_options_hearts(choice, new_state) {
    var s = __mistrimulti_savespace();
    var opts = mistrimulti_world_options_pending() ?? mistrimulti_world_options_default();
    opts.hearts = choice;
    mistrimulti_world_options_pending(opts);
    mmapi_log_info("mistrimulti", "New world options: " + json_stringify(opts));
    s.orig_enter_game(new_state);
}

// Runs fn(arg) a few frames later, once the popup that asked for it has finished closing.
function mistrimulti_savespace_later(fn, arg) {
    __mistrimulti_savespace().later = { fn: fn, arg: arg, frames: 12 };
}

// Every mod tick (the title screen too).
function mistrimulti_savespace_tick() {
    var s = __mistrimulti_savespace();
    var l = s[$ "later"];
    if (!is_struct(l)) return;
    l.frames--;
    if (l.frames > 0) return;
    s.later = undefined;
    try { l.fn(l.arg); }
    catch (e) { mmapi_log_error("mistrimulti", "New world popup failed: " + string(e)); s.orig_enter_game(l.arg); }
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
    s.mode = "";
    s.entry = "";
    var rt = __mistrimulti_runtime();
    rt.enabled = false;
    rt.initialized = false;
    try { mistrimulti_menu_title_entered(); }      // stops a host / join that is still running, closes menu screens
    catch (e) { mmapi_log_error("mistrimulti", "Menu reset failed: " + string(e)); }
    if (s.active) { mistrimulti_savespace_try_set(false); return; }
    try { mistrimulti_savespace_rebuild_menu(); }   // tag the solo list with [Single]
    catch (e) { mmapi_log_error("mistrimulti", "Could not label the solo save list: " + string(e)); }
}

function mistrimulti_local_missing(value, ctx) {
    switch (ctx.key) {
        case "mistrimulti/choose_mode": return "Singleplayer or Multiplayer?";
        case "mistrimulti/singleplayer": return "Singleplayer";
        case "mistrimulti/multiplayer": return "Multiplayer";
        case "mistrimulti/host_world": return "Multiplayer world";
        case "mistrimulti/continue_world": return "Continue world";
        case "mistrimulti/new_world": return "New world";
        case "mistrimulti/opt_hearts_title": return "Hearts with villagers";
        case "mistrimulti/opt_hearts_own": return "Own (Recommended)";
        case "mistrimulti/opt_hearts_shared": return "Shared";
        case "mistrimulti/no_world_title": return "No world to join yet";
        case "mistrimulti/no_world_body": return "The host's world was not found on this computer. Choose Multiplayer and Join a game again.";
        case "mistrimulti/offline_title": return "Multiplayer is offline";
        case "mistrimulti/offline_version_body": return "The game was updated and MistriaMulti has not been updated for it yet.";
        case "mistrimulti/menu_failed_body": return "The multiplayer menu could not start. Singleplayer is not affected. Details are in the MistriaMulti log.";
    }
    if (is_string(ctx.key) && string_copy(ctx.key, 1, 14) == "mistrimulti/t/") return mistrimulti_menu_text_for_key(ctx.key);   // texts made by MistriMultiMenu.gml
    return undefined;
}
