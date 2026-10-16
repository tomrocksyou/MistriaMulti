// A guest's characters in one world (docs/PLAYER-DATA.md, "Choosing between your characters").
//
// Host: the character a guest replaces with "New character" is kept as a generation next to the current record, up to five per
// identity per world, in fixed slot files (players/<identity>.h1.json .. .h5.json). A full history reuses the slot of the oldest
// generation, so nothing has to be deleted. Choosing an earlier character swaps it with the current one; nothing is lost on the way.
// Guest: the question after "Keep mine", and a small per-world cache of the guest's own character that the Load Game list shows
// instead of the host's character (the list reads the downloaded world's save header, which holds the host's character).

function mistrimulti_history_limit() {
    return 5;
}

function mistrimulti_history_base(uid) {
    var path = mistrimulti_player_path(uid);
    return string_copy(path, 1, string_length(path) - 5);
}

function mistrimulti_history_path(uid, slot) {
    return mistrimulti_history_base(uid) + ".h" + string(slot) + ".json";
}

function mistrimulti_history_write(path, value) {
    save_text_file(path + ".tmp", json_stringify(value));
    file_rename(path + ".tmp", path);
}

// What a list needs to show a character without opening its records.
function mistrimulti_history_meta(core) {
    var c = core.data;
    return { name: string(c.character.name), day: string(c.day), gold: c.stats.gold };
}

// Two copies of one character have the same signature; the character changes whenever it uploads.
function mistrimulti_history_sig(core, progress) {
    return string(core.revision) + ":" + string(progress == undefined ? -1 : progress.revision) + ":" + string(core.data.day) + ":" + string(core.data.character.name);
}

// A slot file that holds a complete, valid character of this identity in this world, or undefined.
function mistrimulti_history_check(file, uid, world) {
    if (!is_struct(file) || file[$ "v"] != 1 || !is_real(file[$ "seq"]) || !is_struct(file[$ "core"])) return undefined;
    var core = file.core;
    if (!is_real(core[$ "revision"]) || core.revision < 0 || core.revision != floor(core.revision)) return undefined;
    if (!mistrimulti_player_valid(core[$ "data"], uid, world)) return undefined;
    var progress = undefined;
    if (is_struct(file[$ "progress"])) {
        progress = mistrimulti_progress_migrate(file.progress);
        if (progress == undefined || !mistrimulti_progress_valid(progress.data, uid, world)) return undefined;
    }
    return { slot: 0, seq: file.seq, core: core, progress: progress, meta: mistrimulti_history_meta(core), sig: mistrimulti_history_sig(core, progress) };
}

// The valid generations of an identity, newest first.
function mistrimulti_history_read(uid) {
    var r = __mistrimulti_runtime();
    var items = [];
    for (var slot = 1; slot <= mistrimulti_history_limit(); slot++) {
        var path = mistrimulti_history_path(uid, slot);
        if (!file_exists(path)) continue;
        var item = mistrimulti_history_check(try_read_json_file(path), uid, r.world_key);
        if (item == undefined) continue;
        item.slot = slot;
        array_push(items, item);
    }
    for (var i = 1; i < array_length(items); i++) {
        for (var j = i; j > 0 && items[j].seq > items[j - 1].seq; j--) {
            var held = items[j];
            items[j] = items[j - 1];
            items[j - 1] = held;
        }
    }
    return items;
}

// Puts a character into the history: into `slot`, or (slot < 0) into a free slot, else over the oldest generation.
// A character that is already in the history (same signature) is not stored twice.
function mistrimulti_history_park(uid, core, progress, slot) {
    var items = mistrimulti_history_read(uid);
    var sig = mistrimulti_history_sig(core, progress);
    var seq = 1;
    for (var i = 0; i < array_length(items); i++) {
        if (slot < 0 && items[i].sig == sig) return true;
        seq = max(seq, items[i].seq + 1);
    }
    if (slot < 0) {
        for (var s = mistrimulti_history_limit(); s >= 1; s--) {
            var taken = false;
            for (var i = 0; i < array_length(items); i++) if (items[i].slot == s) taken = true;
            if (!taken) slot = s;
        }
        if (slot < 0) slot = items[array_length(items) - 1].slot;
    }
    mistrimulti_history_write(mistrimulti_history_path(uid, slot), { v: 1, seq: seq, core: core, progress: progress });
    return true;
}

// 0.4.5 kept one replaced character as players/<identity>.replaced.json (+ .progress.replaced.json): it becomes a generation.
function mistrimulti_history_import_legacy(uid) {
    var r = __mistrimulti_runtime();
    var base = mistrimulti_history_base(uid);
    var core_path = base + ".replaced.json";
    var progress_path = base + ".progress.replaced.json";
    if (!file_exists(core_path)) return;
    var core = try_read_json_file(core_path);
    if (!is_struct(core) || !is_real(core[$ "revision"]) || !mistrimulti_player_valid(core[$ "data"], uid, r.world_key)) return;
    var progress = undefined;
    if (file_exists(progress_path)) {
        progress = mistrimulti_progress_migrate(try_read_json_file(progress_path));
        if (progress != undefined && !mistrimulti_progress_valid(progress.data, uid, r.world_key)) progress = undefined;
    }
    if (!mistrimulti_history_park(uid, core, progress, -1)) return;
    file_rename(core_path, core_path + ".imported");
    if (file_exists(progress_path)) file_rename(progress_path, progress_path + ".imported");
}

// The guest chose "New character": the current character is kept in the history. The current records stay where they are.
function mistrimulti_history_demote(uid) {
    try {
        mistrimulti_history_import_legacy(uid);
        var core = mistrimulti_player_load(uid);
        if (core == undefined) return true;
        return mistrimulti_history_park(uid, core, mistrimulti_progress_load(uid), -1);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_history", "mistrimulti", "The replaced character could not be kept: " + string(e));
        return false;
    }
}

// What the guest is shown: the current character first (id 0), then the earlier ones newest first (id = slot).
function mistrimulti_history_summary(uid, current) {
    var list = [];
    try {
        mistrimulti_history_import_legacy(uid);
        var sig = mistrimulti_history_sig(current, mistrimulti_progress_load(uid));
        var meta = mistrimulti_history_meta(current);
        array_push(list, { id: 0, name: meta.name, day: meta.day, gold: meta.gold });
        var items = mistrimulti_history_read(uid);
        for (var i = 0; i < array_length(items); i++) {
            // The copy of a character that is still the current one (the guest left the editor unfinished) is not offered twice.
            if (items[i].sig == sig) continue;
            array_push(list, { id: items[i].slot, name: items[i].meta.name, day: items[i].meta.day, gold: items[i].meta.gold });
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_history", "mistrimulti", "The earlier characters could not be listed: " + string(e));
    }
    return list;
}

// Makes the character in `slot` the current one and puts the current one in its place. Returns false when nothing changed.
// Order: a copy of the current character in players/<identity>.swap.json, the chosen records over the current ones (each write is
// a temporary file and a rename, the old record stays as .bak), then the former current character into the chosen slot.
function mistrimulti_history_swap(uid, slot) {
    var r = __mistrimulti_runtime();
    try {
        var item = undefined;
        var items = mistrimulti_history_read(uid);
        for (var i = 0; i < array_length(items); i++) if (items[i].slot == slot) item = items[i];
        var core = mistrimulti_player_load(uid);
        if (item == undefined || core == undefined) return false;
        var progress = mistrimulti_progress_load(uid);
        mistrimulti_history_write(mistrimulti_history_base(uid) + ".swap.json", { v: 1, core: core, progress: progress });
        // The one-partner rule applies to a character that comes back like to any record the host stores.
        mistrimulti_romance_arbitrate(uid, item.core.data);
        if (!mistrimulti_player_store(uid, item.core.revision, item.core.data)) return false;
        var chosen = item.progress != undefined ? item.progress
            : { revision: 0, data: { v: MISTRIMULTI_PROGRESS_VERSION, uid: uid, world: r.world_key, sections: {} } };
        if (!mistrimulti_progress_store(uid, chosen.revision, chosen.data)) {
            mistrimulti_player_store(uid, core.revision, core.data);
            return false;
        }
        // The chosen slot could not be written: any other slot will do (the chosen character's copy there is the current one now).
        var parked = false;
        try { parked = mistrimulti_history_park(uid, core, progress, slot); } catch (e) {}
        if (!parked) {
            try { parked = mistrimulti_history_park(uid, core, progress, -1); } catch (e) {}
        }
        if (!parked) mmapi_warn_rate_limited("mistrimulti_history", "mistrimulti", "The former character is in players/<identity>.swap.json only.");
        return true;
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_history", "mistrimulti", "Choosing an earlier character failed: " + string(e));
        return false;
    }
}

// ---- guest: the question ------------------------------------------------------------------------------------------------------

// The host's list, checked: at most six entries, a name, a day and a gold amount each. Never trusted further than that.
function mistrimulti_charpicker_clean(list) {
    var out = [];
    if (!is_array(list)) return out;
    for (var i = 0; i < array_length(list) && i < mistrimulti_history_limit() + 1; i++) {
        var c = list[i];
        if (!is_struct(c) || !is_real(c[$ "id"]) || c.id != floor(c.id) || c.id < 0 || c.id > mistrimulti_history_limit()) continue;
        if (!is_string(c[$ "name"]) || !is_string(c[$ "day"]) || !is_real(c[$ "gold"]) || c.gold < 0) continue;
        if (string_digits(c.day) != c.day || c.day == "" || string_length(c.day) > 12) continue;
        array_push(out, { id: c.id, name: string_copy(c.name, 1, 64), day: c.day, gold: floor(c.gold) });
    }
    return out;
}

// "Spring 5, Y2" from a calendar time, with the game's own calendar functions.
function mistrimulti_charpicker_when(day) {
    try {
        var time = real(day);
        var season = season_to_string(get_seasons(time));
        return string_upper(string_copy(season, 1, 1)) + string_copy(season, 2, string_length(season)) + " " + string(get_days(time) + 1) + ", Y" + string(get_years(time) + 1);
    } catch (e) {
        return "day " + string(day);
    }
}

// One row of the question: name (the names are cut so that a row stays short), when it was last played, gold.
function mistrimulti_charpicker_label(c) {
    var name = string_copy(c.name, 1, 12);
    return name + (c.id == 0 ? " (now)" : "") + ", " + mistrimulti_charpicker_when(c.day) + ", " + string(c.gold) + "g";
}

// "Keep mine": a guest with earlier characters in this world chooses one of them; with none, the answer is final.
function mistrimulti_charpicker_keep(epoch) {
    var r = __mistrimulti_runtime();
    var ask = r.character_ask;
    var list = r[$ "character_chars"] ?? [];
    if (array_length(list) < 2 || !is_struct(ask) || ask.epoch != epoch || epoch != r.epoch) { mistrimulti_character_chosen(1, epoch); return; }
    ask.stage = "pick";
    ask.popup = undefined;
    ask.gone = 0;
    mistrimulti_character_log("keep: choosing between " + string(array_length(list)) + " characters of this world.");
}

// The characters of this player in this world and "New character" last. At most 1 + 5 + 1 = 7 options: the same as the join
// menu's list of hosts (4 hosts + 3), which the game shows in the same popup.
function mistrimulti_charpicker_ask(r, ask) {
    var list = r[$ "character_chars"] ?? [];
    var mcp = new MultipleChoicePopup(mistrimulti_menu_t("Your characters here"));
    for (var i = 0; i < array_length(list); i++) {
        mcp.option(mistrimulti_menu_t(mistrimulti_charpicker_label(list[i])), mistrimulti_character_chosen, [list[i].id == 0 ? 1 : 2, ask.epoch, list[i].id]);
    }
    mcp.option(mistrimulti_menu_t("New character"), mistrimulti_character_chosen, [0, ask.epoch, 0]);
    mistrimulti_widen_choices(mcp);
    ask.popup = mcp;
    ask.gone = 0;
    mistrimulti_character_log("asked which of the " + string(array_length(list)) + " characters to continue with, or a new one.");
}

// The host could not load the character that was chosen: the guest is asked again from the start.
function mistrimulti_charpicker_failed(r) {
    var ask = r[$ "character_ask"];
    if (!is_struct(ask) || ask.choice != 2 || r.character_phase != "keep") return;
    r.character_ask = undefined;
    r.character_phase = "ask";
    mistrimulti_character_log("the host could not load that character; asking again.");
}

// ---- guest: the Load Game list -------------------------------------------------------------------------------------------------

function mistrimulti_charcache_dir() {
    return mistrimulti_data_dir() + "/characters";
}

// Remembers this guest's character in this world for the Load Game list: characters/<world>.json, and the map from the game's
// world number (the one in the save's file name) to the world: characters/worlds.json. Written only when something changed.
function mistrimulti_charcache_remember() {
    var r = __mistrimulti_runtime();
    try {
        if (r.mode != "join" || ARI == undefined || !is_string(r.world_key) || r.world_key == "" || r.character_pending) return;
        var entry = { v: 1, world: r.world_key, game: string(Game.unique_identifier), name: string(ARI.name),
            look: ARI.animation_assets().serialize(), used: date_current_datetime() };
        var signature = json_stringify({ w: entry.world, n: entry.name, l: entry.look });
        if (r[$ "charcache_sig"] == signature) return;
        directory_create(mistrimulti_charcache_dir());
        mistrimulti_history_write(mistrimulti_charcache_dir() + "/" + r.world_key + ".json", entry);
        var path = mistrimulti_charcache_dir() + "/worlds.json";
        var index = file_exists(path) ? try_read_json_file(path) : undefined;
        var worlds = is_struct(index) && is_struct(index[$ "worlds"]) ? index.worlds : {};
        worlds[$ entry.game] = r.world_key;
        mistrimulti_history_write(path, { v: 1, worlds: worlds });
        r.charcache_sig = signature;
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_charcache", "mistrimulti", "The character could not be remembered for the Load Game list: " + string(e));
    }
}

// Called while the Load Game list is built, for a guest: puts this guest's own character into the header of the world's entry.
// Never throws (the caller would take a failure for a damaged save). The name is set first and alone, so a look the game cannot
// build still leaves the right name.
function mistrimulti_charcache_apply(header, game_ident) {
    try {
        var index_path = mistrimulti_charcache_dir() + "/worlds.json";
        if (!file_exists(index_path)) return;
        var index = try_read_json_file(index_path);
        var world = is_struct(index) && is_struct(index[$ "worlds"]) ? index.worlds[$ string(game_ident)] : undefined;
        if (!is_string(world) || world == "") return;
        var path = mistrimulti_charcache_dir() + "/" + world + ".json";
        if (!file_exists(path)) return;
        var entry = try_read_json_file(path);
        if (!is_struct(entry) || entry[$ "v"] != 1 || entry[$ "world"] != world || !is_string(entry[$ "name"]) || string_length(entry.name) > 64) return;
        header.name = entry.name;
        try {
            if (mistrimulti_valid_look(entry[$ "look"])) header.preset = player_animation_assets_deserialize(entry.look);
        } catch (e) {
            mmapi_warn_rate_limited("mistrimulti_charcache_look", "mistrimulti", "The Load Game portrait stays the host's: " + string(e));
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_charcache", "mistrimulti", "The Load Game list keeps the host's character: " + string(e));
    }
}
