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

function mistrimulti_character_profile() {
    var r = __mistrimulti_runtime();
    var path = r.character_path;
    var profile = file_exists(path) ? try_read_json_file(path) : undefined;
    if (mistrimulti_valid_character(profile) && profile[$ "uid"] == r.uid) return profile;
    profile = file_exists(path + ".bak") ? try_read_json_file(path + ".bak") : undefined;
    if (mistrimulti_valid_character(profile) && profile[$ "uid"] == r.uid) return profile;
    // Claim a legacy device profile for one identity only.
    var root = mistrimulti_data_dir();
    var owner_path = root + "/legacy_character_owner.json";
    var owner = file_exists(owner_path) ? try_read_json_file(owner_path) : undefined;
    if (is_struct(owner) && owner[$ "uid"] != r.uid) return undefined;
    var legacy = root + "/character.json";
    profile = file_exists(legacy) ? try_read_json_file(legacy) : undefined;
    if (!mistrimulti_valid_character(profile)) return undefined;
    if (owner == undefined) save_text_file(owner_path, json_stringify({ uid: r.uid }));
    return profile;
}

function mistrimulti_character_tick() {
    var r = __mistrimulti_runtime();
    if (r.mode != "join" || !r.player_ready || ARI == undefined || GRID == undefined || !instance_exists(obj_ari)) return;
    if (r.character_owner != ARI) {
        r.character_owner = ARI;
        r.character_pending = true;
        r.character_ready_ticks = 0;
        r.character_loaded = false;
        r.character_menu = undefined;
    }
    if (!r.character_pending) return;
    // A guest who is never offered the character editor must be able to say why: log what is holding it back, rarely.
    var hold = "";
    try {
        if (MIST.is_running()) hold = "a cutscene is running";
        else if (ARI.end_of_day_status != undefined) hold = "the end of day is running";
        else if (ANCHOR.get_menu(Menu.Customization) != undefined && r.character_menu == undefined) hold = "a customization menu is already open";
        else if (ANCHOR.popup_is_open()) hold = "a popup is open";
        else {
            for (var h = 0; h < ANCHOR.open_menus.count(); h++) {
                if (ANCHOR.open_menus.get(h).data.pause != PauseStatus.EMPTY) { hold = "a paused menu is open (menu type " + string(ANCHOR.open_menus.get(h).type) + ")"; break; }
            }
        }
        r.character_hold_ticks = hold == "" ? 0 : (r[$ "character_hold_ticks"] ?? 0) + 1;
        if (hold != "" && r.character_hold_ticks mod 1200 == 600) mmapi_log_warn("mistrimulti", "The character editor is waiting: " + hold + ".");
    } catch (e) {}
    if (r.character_menu != undefined) {
        // A world/menu shutdown must not leave a guest permanently hidden.
        if (ANCHOR.get_menu(Menu.Customization) != r.character_menu) {
            r.character_menu = undefined;
            r.character_ready_ticks = 0;
        }
        return;
    }
    if (MIST.is_running() || ARI.end_of_day_status != undefined) { r.character_ready_ticks = 0; return; }
    for (var i = 0; i < ANCHOR.open_menus.count(); i++) {
        if (ANCHOR.open_menus.get(i).data.pause != PauseStatus.EMPTY) { r.character_ready_ticks = 0; return; }
    }
    if (ANCHOR.get_menu(Menu.Customization) != undefined || ANCHOR.popup_is_open()) return;
    r.character_ready_ticks++;
    if (r.character_ready_ticks < 30) return;
    var preset = ARI.animation_assets().clone();
    if (!r.character_loaded) {
        var saved = mistrimulti_character_profile();
        if (saved != undefined) {
            preset = player_animation_assets_deserialize(saved.look);
            ARI.name = saved.name;
            ARI.deserialize_pronouns(clone_value(saved.pronouns));
            local_set_pronouns(ARI.pronouns);
            ARI.birthday = int64(saved.birthday);
        }
        r.character_loaded = true;
    }
    r.character_preset = preset;
    mmapi_log_warn("mistrimulti", "Opening the character editor for this guest.");
    var menu = start_character_creation(preset, mistrimulti_character_complete, true);
    r.character_menu = menu;
    menu.listen_for_exit_flag = false;
    menu.continue_button.text_label.set_key("misc_local/continue");
    // Keep the host's farm name locked.
    menu.farm_field.set_unlocked(false);
}

function mistrimulti_character_complete() {
    var r = __mistrimulti_runtime();
    var preset = r.character_preset;
    if (preset == undefined) return;
    // Build from the old equipped outfit before replacing the selected preset.
    build_obj_ari_par_from(preset);
    ARI.presets.set(ARI.preset_index_selected, preset);
    var profile = { v: 1, uid: r.uid, name: string(ARI.name), pronouns: clone_value(ARI.pronouns),
        birthday: ARI.birthday, look: preset.serialize() };
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
    r.character_preset = undefined;
    r.character_menu = undefined;
    r.look_signature = "";
    mistrimulti_update_look();
    mistrimulti_player_checkpoint();
}

function mistrimulti_debug_character() {
    var r = __mistrimulti_runtime();
    var menu = r.character_menu;
    return { pending: r.character_pending, open: menu != undefined,
        uid: r.uid, profile_path: r.character_path,
        name: ARI.name, birthday: ARI.birthday,
        look: ARI.animation_assets().serialize(),
        edited_look: r.character_preset == undefined ? undefined : r.character_preset.serialize() };
}
