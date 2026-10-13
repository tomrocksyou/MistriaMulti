// Stable identities are strings: a 64-bit Steam ID must never pass through a float.
function mistrimulti_valid_uid(uid) {
    if (!is_string(uid)) return false;
    var steam = string_copy(uid, 1, 6) == "steam:";
    var local = string_copy(uid, 1, 6) == "local:";
    if ((!steam && !local) || string_length(uid) != (steam ? 23 : 38)) return false;
    for (var i = 7; i <= string_length(uid); i++) {
        var c = ord(string_char_at(uid, i));
        if (c >= ord("0") && c <= ord("9")) continue;
        if (local && c >= ord("a") && c <= ord("f")) continue;
        return false;
    }
    return true;
}

function mistrimulti_identity_initialize(cfg) {
    var r = __mistrimulti_runtime();
    r.uid = cfg[$ "uid"];
    if (!mistrimulti_valid_uid(r.uid)) {
        var path = mmapi_mod_data_dir("mistrimulti") + "/local_identity.json";
        var saved = file_exists(path) ? try_read_json_file(path) : undefined;
        if (is_struct(saved) && mistrimulti_valid_uid(saved[$ "uid"])) r.uid = saved.uid;
        else {
            r.uid = "local:" + cfg.epoch;
            if (!mistrimulti_valid_uid(r.uid)) throw "Launcher identity is missing or invalid.";
            save_text_file(path, json_stringify({ uid: r.uid }));
        }
    }
    var folder = mmapi_mod_data_dir("mistrimulti") + "/characters";
    directory_create(folder);
    r.character_path = folder + "/" + string_replace_all(r.uid, ":", "_") + ".json";
    r.roster = {};
    r.roster_dirty = false;
    if (r.mode == "host") {
        var path = mmapi_mod_data_dir("mistrimulti") + "/players.json";
        var saved = file_exists(path) ? try_read_json_file(path) : undefined;
        if (is_struct(saved) && saved[$ "v"] == 1 && is_struct(saved[$ "players"])) r.roster = saved.players;
    }
}

function mistrimulti_remember_peer(player) {
    var r = __mistrimulti_runtime();
    var p = r.peers[player];
    if (r.mode != "host" || !mistrimulti_valid_uid(p[$ "uid"]) || !mistrimulti_valid_look(p[$ "look"])) return;
    if (!is_string(p[$ "name"]) || string_length(p.name) > 64) return;
    var entry = r.roster[$ p.uid];
    if (entry == undefined && array_length(struct_get_names(r.roster)) >= 256) return;
    r.roster[$ p.uid] = { name: p.name, look: p.look };
    r.roster_dirty = true;
}

function mistrimulti_flush_roster() {
    var r = __mistrimulti_runtime();
    if (!r.roster_dirty || r.mode != "host") return;
    var path = mmapi_mod_data_dir("mistrimulti") + "/players.json";
    try {
        save_text_file(path + ".tmp", json_stringify({ v: 1, players: r.roster }));
        file_rename(path + ".tmp", path);
        r.roster_dirty = false;
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_roster", "mistrimulti", "Player records will retry.");
    }
}
