function mistrimulti_valid_look(look) {
    if (!is_struct(look) || !is_array(look[$ "assets"]) || array_length(look.assets) > 24) return false;
    if (!is_real(look[$ "skin_tone"]) || !is_real(look[$ "eyes"])) return false;
    if (look.skin_tone < 0 || look.skin_tone != floor(look.skin_tone) || look.skin_tone >= sprite_get_width(spr_player_base_lut)) return false;
    if (look.eyes < 0 || look.eyes != floor(look.eyes) || look.eyes > 255) return false;
    for (var i = 0; i < array_length(look.assets); i++) {
        var part = look.assets[i];
        if (!is_struct(part) || !is_string(part[$ "name"]) || !is_real(part[$ "lut_index"])) return false;
        var asset = PLAYER_ANIMATION_DATABASE.player_assets.get(part.name);
        if (asset == undefined || part.lut_index < 0 || part.lut_index != floor(part.lut_index) || part.lut_index > 1024) return false;
        if (asset.lut_sprite != undefined && part.lut_index >= sprite_get_width(asset.lut_sprite)) return false;
    }
    return true;
}

function mistrimulti_valid_character(profile) {
    if (!is_struct(profile) || profile[$ "v"] != 1 || !mistrimulti_valid_look(profile[$ "look"])) return false;
    if (!is_string(profile[$ "name"]) || string_length(profile.name) > 64) return false;
    if (!is_struct(profile[$ "pronouns"]) || !is_real(profile[$ "birthday"])) return false;
    return profile.birthday >= 0 && profile.birthday < years(1);
}

// A guest makes a new character whenever the world is new to it (the host has no record of this identity in this world, or the
// player chose "New character" for it). A guest who comes back to a world it has a record in continues with that record and
// never sees the editor. Where the record lives and how the host answers: MistriMultiPlayerSync.gml, docs/PLAYER-DATA.md.
// Everything that happens to the editor is logged at warn level ("Character editor: ...") so a guest who never sees it can say why.

function mistrimulti_character_log(text) {
    try { mmapi_log_warn("mistrimulti", "Character editor: " + text); mmapi_log_flush("mistrimulti"); } catch (e) {}
}

function mistrimulti_character_default_name() {
    return "Guest";
}

// Why the editor (or its question) cannot be shown right now, or "".
function mistrimulti_character_hold(r) {
    if (MIST.is_running()) return "a cutscene is running";
    if (ARI.end_of_day_status != undefined) return "the end of day is running";
    if (ANCHOR.get_menu(Menu.Customization) != undefined && r.character_menu == undefined) return "a customization menu is already open";
    if (ANCHOR.popup_is_open()) return "a popup is open";
    for (var i = 0; i < ANCHOR.open_menus.count(); i++) {
        if (ANCHOR.open_menus.get(i).data.pause != PauseStatus.EMPTY) return "a paused menu is open (menu type " + string(ANCHOR.open_menus.get(i).type) + ")";
    }
    return "";
}

// What the editor looks like to the game, for the log.
function mistrimulti_character_state(menu) {
    var text = "";
    try { text += "alpha=" + string(menu.canvas.get_alpha()); } catch (e) { text += "alpha=?"; }
    try { text += " hide_requests=" + string(menu.hide_requests) + " closing=" + string(menu.close_requested) + " fading=" + string(menu.internal_chain != undefined); } catch (e) {}
    try { text += " pause_status=" + string(PAUSE_STATUS); } catch (e) {}
    try { text += " load_sequence=" + string(LOAD_SEQUENCE.is_active()); } catch (e) {}
    return text;
}

function mistrimulti_character_tick() {
    var r = __mistrimulti_runtime();
    if (r.mode != "join" || ARI == undefined || GRID == undefined || !instance_exists(obj_ari)) return;
    try { mistrimulti_character_step(r); }
    catch (e) { mmapi_warn_rate_limited("mistrimulti_character_step", "mistrimulti", "Character editor: the step failed (" + string(e) + ")."); }
}

function mistrimulti_character_step(r) {
    if (r.character_owner != ARI) {
        r.character_owner = ARI;
        r.character_pending = true;
        r.character_ready_ticks = 0;
        r.character_loaded = false;
        // An editor that is still open belongs to this guest: keep following it instead of waiting for a second one.
        if (r.character_menu != undefined && ANCHOR.get_menu(Menu.Customization) != r.character_menu) r.character_menu = undefined;
    }
    if (!r.character_pending) return;
    // The host has a character of this identity in this world and the guest entered through New Game: ask what to do.
    mistrimulti_character_send_choice(r);
    if (r.character_phase == "ask") { mistrimulti_character_ask(r); return; }
    if (r.character_phase == "keep" || !r.player_ready) return;
    if (r.character_menu != undefined) { mistrimulti_character_watch(r); return; }
    // The editor opens once nothing else is going on for half a second.
    var hold = mistrimulti_character_hold(r);
    r.character_hold_ticks = hold == "" ? 0 : (r[$ "character_hold_ticks"] ?? 0) + 1;
    if (hold != "" && r.character_hold_ticks mod 1200 == 600) mistrimulti_character_log("waiting: " + hold + ".");
    if (hold != "") { r.character_ready_ticks = 0; return; }
    r.character_ready_ticks++;
    if (r.character_ready_ticks < 30) return;
    mistrimulti_character_open(r);
}

function mistrimulti_character_open(r) {
    var preset = r.character_preset;
    if (!r.character_loaded) {
        // A new character starts from the game's defaults: not the host's character that this game loaded, and not a character
        // this player made in another world.
        preset = create_default_player_animation_assets();
        ARI.name = mistrimulti_character_default_name();
        ARI.deserialize_pronouns(default_pronouns());
        local_set_pronouns(ARI.pronouns);
        ARI.birthday = DEFAULT_ARI_BIRTHDAY;
        r.character_loaded = true;
    }
    if (preset == undefined) preset = ARI.animation_assets().clone();
    r.character_preset = preset;
    r.character_opens = (r[$ "character_opens"] ?? 0) + 1;
    r.character_open_ticks = 0;
    r.character_shown = false;
    r.character_forced = false;
    mistrimulti_character_log("opening for this guest (attempt " + string(r.character_opens) + ", entry " + string(r[$ "character_entry"]) + ").");
    var menu = undefined;
    try { menu = start_character_creation(preset, mistrimulti_character_complete, true); }
    catch (e) { mistrimulti_character_log("could not be opened (" + string(e) + "); trying again in 5 seconds."); }
    if (menu == undefined) {
        // Half a menu may exist: a stray editor would block the next attempt.
        try { var stray = ANCHOR.get_menu(Menu.Customization); if (stray != undefined) stray.close(); } catch (e) {}
        r.character_ready_ticks = -300;
        return;
    }
    r.character_menu = menu;
    menu.listen_for_exit_flag = false;
    try { menu.continue_button.text_label.set_key("misc_local/continue"); }
    catch (e) { mistrimulti_character_log("the Continue label could not be set (" + string(e) + ")."); }
    // Keep the host's farm name locked.
    try { menu.farm_field.set_unlocked(false); }
    catch (e) { mistrimulti_character_log("the farm name could not be locked (" + string(e) + ")."); }
    mistrimulti_character_log("opened (" + mistrimulti_character_state(menu) + ").");
}

// While the editor is open: log when it is visible, show it if it never became visible, notice when it was closed without Continue.
function mistrimulti_character_watch(r) {
    var menu = r.character_menu;
    if (ANCHOR.get_menu(Menu.Customization) != menu) {
        // A world/menu shutdown must not leave a guest permanently hidden: the editor opens again.
        mistrimulti_character_log("closed without Continue after " + string(r.character_open_ticks) + " ticks (shown=" + string(r.character_shown) + "); it opens again.");
        r.character_menu = undefined;
        r.character_ready_ticks = 0;
        return;
    }
    r.character_open_ticks++;
    var alpha = 0;
    try { alpha = menu.canvas.get_alpha(); } catch (e) { alpha = 0; }
    if (!r.character_shown && alpha >= 0.99) {
        r.character_shown = true;
        mistrimulti_character_log("shown after " + string(r.character_open_ticks) + " ticks (" + mistrimulti_character_state(menu) + ").");
    } else if (!r.character_shown && !r.character_forced && r.character_open_ticks >= 180) {
        // Open for 3 seconds and still not visible (the fade-in never ran?): show it at once.
        r.character_forced = true;
        mistrimulti_character_log("still not visible after 3 seconds (" + mistrimulti_character_state(menu) + "); showing it now.");
        try { menu.request_show(0); } catch (e) { mistrimulti_character_log("showing it failed (" + string(e) + ")."); }
    } else if (r.character_open_ticks mod 3600 == 0) {
        mistrimulti_character_log("still open (" + mistrimulti_character_state(menu) + ").");
    }
}

// The answer reaches the host as an event; it is sent again until the event layer accepts it.
function mistrimulti_character_send_choice(r) {
    var ask = r.character_ask;
    if (ask == undefined || ask.choice < 0 || ask.sent || !mistrimulti_event_can_emit(1)) return;
    ask.sent = mistrimulti_event_emit("profile_choice", { world: r.world_key, uid: r.uid, keep: ask.choice, gen: ask.gen }, 0);
}

function mistrimulti_character_ask(r) {
    var ask = r.character_ask;
    if (ask == undefined) {
        ask = { epoch: r.epoch, popup: undefined, choice: -1, sent: false, gone: 0, stage: "first", gen: 0 };
        r.character_ask = ask;
    }
    if (ask.popup != undefined) {
        if (ANCHOR.popup_is_open()) { ask.gone = 0; return; }
        ask.gone++;
        if (ask.gone < 60) return;
        mistrimulti_character_log("the question was closed without an answer; asking again.");
        ask.popup = undefined;
    }
    if (mistrimulti_character_hold(r) != "") return;
    // After "Keep mine" a player with earlier characters in this world chooses between them (MistriMultiCharPicker.gml).
    if (ask.stage == "pick") { mistrimulti_charpicker_ask(r, ask); return; }
    var mcp = new MultipleChoicePopup(mistrimulti_menu_t("You have a character here"));
    mcp.option(mistrimulti_menu_t("Keep mine"), mistrimulti_charpicker_keep, [ask.epoch]);
    mcp.option(mistrimulti_menu_t("New character"), mistrimulti_character_chosen, [0, ask.epoch]);
    ask.popup = mcp;
    ask.gone = 0;
    mistrimulti_character_log("this world already has a character of yours; asked whether to keep it or make a new one.");
}

// keep: 1 the current character, 2 an earlier one (gen = its number), 0 a new character.
function mistrimulti_character_chosen(keep, epoch, gen = 0) {
    var r = __mistrimulti_runtime();
    var ask = r.character_ask;
    if (!is_struct(ask) || ask.epoch != epoch || epoch != r.epoch) {
        mistrimulti_character_log("an answer to an old question was ignored.");
        return;
    }
    ask.choice = keep;
    ask.gen = gen;
    r.character_phase = keep >= 1 ? "keep" : "edit";
    mistrimulti_character_log(keep == 2 ? "answer: continue with earlier character " + string(gen) + "." : keep == 1 ? "answer: keep the existing character." : "answer: make a new character (the old one stays on the host until the new one is saved).");
}

// The game calls this when the guest taps Continue (after the editor has faded out).
function mistrimulti_character_complete() {
    var r = __mistrimulti_runtime();
    mistrimulti_character_log("Continue tapped after " + string(r[$ "character_open_ticks"] ?? -1) + " ticks (shown=" + string(r[$ "character_shown"]) + ").");
    try {
        var preset = r.character_preset;
        if (preset == undefined) { mistrimulti_character_log("there is no character being made; the editor opens again."); return; }
        var name = string(ARI.name);
        if (name == "") name = mistrimulti_character_default_name();
        ARI.name = string_copy(name, 1, 64);
        // Build from the old equipped outfit before replacing the selected preset.
        build_obj_ari_par_from(preset);
        ARI.presets.set(ARI.preset_index_selected, preset);
        var profile = { v: 1, uid: r.uid, name: string(ARI.name), pronouns: clone_value(ARI.pronouns),
            birthday: ARI.birthday, look: preset.serialize() };
        // The last character this install made. A convenience copy only: it is never applied to a world (the host's record is).
        var path = r.character_path;
        try {
            if (file_exists(path)) {
                var old = try_read_json_file(path);
                if (mistrimulti_valid_character(old)) save_text_file(path + ".bak", json_stringify(old));
            }
            save_text_file(path + ".tmp", json_stringify(profile));
            file_rename(path + ".tmp", path);
        } catch (e) {
            r.warning = "Character could not be saved; your current appearance is still active.";
            mmapi_log_warn("mistrimulti", r.warning + " " + string(e));
        }
        r.character_pending = false;
        r.character_phase = "done";
        r.character_preset = undefined;
        r.character_menu = undefined;
        r.look_signature = "";
        mistrimulti_update_look();
        mistrimulti_player_checkpoint();
        mistrimulti_charcache_remember();
        mistrimulti_character_log("complete: " + string(ARI.name) + " is now in the world.");
    } catch (e) {
        mistrimulti_character_log("completing failed (" + string(e) + "); the editor opens again.");
    }
}

function mistrimulti_debug_character() {
    var r = __mistrimulti_runtime();
    var menu = r.character_menu;
    return { pending: r.character_pending, open: menu != undefined, phase: r.character_phase, entry: r[$ "character_entry"],
        uid: r.uid, profile_path: r.character_path,
        name: ARI.name, birthday: ARI.birthday,
        look: ARI.animation_assets().serialize(),
        edited_look: r.character_preset == undefined ? undefined : r.character_preset.serialize() };
}
