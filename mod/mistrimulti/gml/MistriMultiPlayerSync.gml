function mistrimulti_player_reset_session() {
    var r = __mistrimulti_runtime();
    r.player_ready = false;
    r.player_revision = 0;
    r.player_saved_revision = 0;
    r.player_signature = "";
    r.player_last_checkpoint = 0;
    r.player_request = "";
    r.player_sessions = array_create(8, undefined);
    r.player_error = "";
    if (is_struct(r[$ "trust"])) r.trust.host_verified = false;
    mistrimulti_progress_reset_session();
    r.epoch += "_" + string(get_timer());
    // A new world session: nothing queued for the previous one may be delivered to it.
    mistrimulti_events_reset();
    r.character_owner = undefined;
    r.character_pending = true;
    r.character_phase = "";
    r.character_ask = undefined;
    r.character_chars = [];
}

// Event kinds. Handshakes are small targeted events; whole player records travel as blobs, so a
// partial upload can never replace the last saved record.
function mistrimulti_player_register_events() {
    var plain = { on_event: mistrimulti_player_event };
    mistrimulti_event_register("profile_request", plain);
    mistrimulti_event_register("profile_start", plain);
    mistrimulti_event_register("profile_error", plain);
    mistrimulti_event_register("profile_exists", plain);
    mistrimulti_event_register("profile_choice", plain);
    mistrimulti_event_register("profile_saved", plain);
    mistrimulti_event_register("profile_update", { on_blob: mistrimulti_player_upload });
    mistrimulti_event_register("profile_record", { on_blob: mistrimulti_player_download });
}

function mistrimulti_player_data_tick() {
    var r = __mistrimulti_runtime();
    if (ARI == undefined || GRID == undefined || !instance_exists(obj_ari)) return;
    if (r.player_owner != ARI) {
        r.player_owner = ARI;
        mistrimulti_player_reset_session();
        r.world_key = "";
        r.world_path = "";
        if (r.mode == "host") {
            r.world_key = string_replace_all(r.uid, ":", "_") + "_" + string(Game.unique_identifier);
            r.world_path = mistrimulti_data_dir() + "/worlds/" + r.world_key;
            directory_create(mistrimulti_data_dir() + "/worlds");
            directory_create(r.world_path);
            directory_create(r.world_path + "/players");
            save_text_file(r.world_path + "/world.json", json_stringify({ v: 1,
                world: r.world_key, game_id: Game.unique_identifier, host: r.uid }));
            r.world_opts = mistrimulti_world_options_load(r.world_path);
            // Restore the loaded save's committed records and rebuild the one-partner registry before anyone is admitted.
            mistrimulti_progress_host_session();
            r.player_ready = true;
            r.character_pending = false;
            r.roster = {};
            r.roster_dirty = false;
        }
    }
    if (r.mode == "join") {
        var host = r.peers[0];
        if ((r.mask & 1) == 0 || !is_struct(host) || !is_string(host[$ "world"]) || host.world == "") {
            r.player_ready = false;
            r.player_host_epoch = "";
            r.player_error = "Waiting for the hosted world.";
            return;
        }
        if (r[$ "world_mismatch"] == true) { r.player_ready = false; r.player_error = "The host plays another world."; return; }   // MistriMultiMenu.gml
        var expected = string_replace_all(host[$ "uid"] ?? "", ":", "_") + "_";
        if (!mistrimulti_valid_uid(host[$ "uid"]) || string_length(host.world) > 80
            || string_copy(host.world, 1, string_length(expected)) != expected) return;
        var suffix = string_delete(host.world, 1, string_length(expected));
        if (suffix == "" || string_digits(suffix) != suffix) return;
        if (r.world_key != host.world || r.player_host_epoch != host.epoch) {
            mistrimulti_player_reset_session();
            r.world_key = host.world;
            r.player_host_epoch = host.epoch;
        }
        // Never hand a character to a host whose identity changed since this guest last joined it (F7 accepts).
        var verify = r[$ "trust_host_ok"];
        if (verify != undefined && r.player_request == "" && r.ticks mod 15 == 0) r.trust.host_verified = verify();
        if (verify != undefined && r.player_request == "" && !r.trust.host_verified) {
            r.player_error = r.trust.warning != "" ? r.trust.warning : "Waiting for the host to prove its identity.";
        } else if (r.player_request == "" && mistrimulti_event_can_emit(1)) {
            if (mistrimulti_event_emit("profile_request", { world: r.world_key, uid: r.uid,
                intent: r[$ "character_entry"] ?? "load" }, 0)) r.player_request = r.epoch;
            r.player_error = "Loading player progress from the host.";
        }
    }
    mistrimulti_progress_tick();
    if (r.ticks mod 3 != 0) return;
    if (!r.player_ready || r.character_pending || MIST.is_running()) return;
    if (get_timer() - r.player_last_checkpoint >= 5000000 && mistrimulti_event_blobs_pending() == 0) {
        r.player_last_checkpoint = get_timer();
        mistrimulti_player_checkpoint();
    }
}

function mistrimulti_player_checkpoint() {
    var r = __mistrimulti_runtime();
    if (!r.player_ready || ARI == undefined || r.character_pending) return false;
    var data = mistrimulti_player_capture();
    var signature = json_stringify(data);
    if (string_byte_length(signature) > 131072) {
        r.player_error = "Player progress exceeds the current save limit.";
        return false;
    }
    if (signature == r.player_signature) return true;
    if (r.mode == "host") {
        if (!mistrimulti_player_store(r.uid, r.player_revision + 1, data)) return false;
        r.player_revision++;
        r.player_saved_revision = r.player_revision;
    } else {
        if (r.player_revision != r.player_saved_revision) return false;
        if (!mistrimulti_player_send("profile_update", 0, r.epoch, r.player_revision + 1, data)) return false;
        r.player_revision++;
    }
    r.player_signature = signature;
    if (r.mode == "join") mistrimulti_charcache_remember();
    return true;
}

function mistrimulti_player_send(kind, target, peer_epoch, revision, data) {
    var r = __mistrimulti_runtime();
    var text = json_stringify(data);
    if (string_byte_length(text) > 131072) return false;
    return mistrimulti_event_send_blob(kind, text, target,
        { world: r.world_key, uid: data.uid, peer_epoch: peer_epoch, revision: revision });
}

function mistrimulti_player_request(player, data) {
    var r = __mistrimulti_runtime();
    var peer = r.peers[player];
    if (r.mode != "host" || !r.player_ready || player == 0) return true;
    if (data[$ "world"] != r.world_key || data[$ "uid"] != peer[$ "uid"] || !mistrimulti_valid_uid(data.uid)) return true;
    if (data.uid == r.uid) return mistrimulti_event_emit("profile_error",
        { peer_epoch: peer.epoch, message: "The host is already using this player identity." }, player);
    // The uid is only a claim: the record belongs to the install the helper verified (MistriMultiTrust.gml).
    var admit = r[$ "trust_admit"];
    if (admit != undefined) {
        var verdict = admit(player, data.uid, peer[$ "name"], data);
        if (!verdict.ok) return mistrimulti_event_emit("profile_error", { peer_epoch: peer.epoch, message: verdict.message }, player);
    }
    for (var i = 1; i < 8; i++) {
        var existing = r.player_sessions[i];
        if (i != player && (r.mask & (1 << i)) != 0 && is_struct(existing) && existing.uid == data.uid) {
            return mistrimulti_event_emit("profile_error", { peer_epoch: peer.epoch, message: "This player identity is already connected." }, player);
        }
    }
    var session = r.player_sessions[player];
    if (is_struct(session) && session.epoch == peer.epoch && session.uid == data.uid) return true;
    var saved = mistrimulti_player_load(data.uid);
    if (saved == undefined && (file_exists(mistrimulti_player_path(data.uid)) || file_exists(mistrimulti_player_path(data.uid) + ".bak"))) {
        return mistrimulti_event_emit("profile_error", { peer_epoch: peer.epoch, message: "The host player record needs recovery." }, player);
    }
    // "New Game > Multiplayer > Join" means a new character. The record of this identity in this world is not replaced
    // silently: the guest is asked first, and nothing on the host changes before it answers (mistrimulti_player_choice).
    var asking = saved != undefined && data[$ "intent"] == "new";
    var success = saved == undefined
        ? mistrimulti_event_emit("profile_start", { peer_epoch: peer.epoch, uid: data.uid, world: r.world_key }, player)
        : (asking ? mistrimulti_event_emit("profile_exists", { peer_epoch: peer.epoch, uid: data.uid, world: r.world_key,
                chars: mistrimulti_history_summary(data.uid, saved) }, player)
            : mistrimulti_player_send("profile_record", player, peer.epoch, saved.revision, saved.data));
    if (success) r.player_sessions[player] = { uid: data.uid, epoch: peer.epoch,
        revision: saved == undefined ? 0 : saved.revision, asking: asking, replaced: false, swapped: false };
    return success;
}

// profile_choice (guest -> host): the guest with a record in this world, joining through New Game, keeps it or starts over.
function mistrimulti_player_choice(player, data) {
    var r = __mistrimulti_runtime();
    var peer = r.peers[player];
    if (r.mode != "host" || !r.player_ready || player == 0 || !is_struct(peer)) return true;
    var session = r.player_sessions[player];
    if (data[$ "world"] != r.world_key || data[$ "uid"] != peer[$ "uid"] || !is_real(data[$ "keep"]) || data.keep < 0 || data.keep > 2) return true;
    if (!is_struct(session) || session.epoch != peer[$ "epoch"] || session.uid != data.uid || session.asking != true) return true;
    var saved = mistrimulti_player_load(data.uid);
    if (data.keep == 2) {
        // An earlier character of this world becomes the current one (once: a send that is retried must not swap back).
        var slot = data[$ "gen"];
        if (!session.swapped) {
            if (!is_real(slot) || slot != floor(slot) || slot < 1 || slot > mistrimulti_history_limit() || !mistrimulti_history_swap(data.uid, slot)) {
                return mistrimulti_event_emit("profile_error", { peer_epoch: peer.epoch, message: "That character could not be loaded." }, player);
            }
            session.swapped = true;
        }
        saved = mistrimulti_player_load(data.uid);
        if (saved == undefined) return mistrimulti_event_emit("profile_error", { peer_epoch: peer.epoch, message: "The host player record needs recovery." }, player);
        session.revision = saved.revision;
        if (!mistrimulti_player_send("profile_record", player, peer.epoch, saved.revision, saved.data)) return false;
    } else if (data.keep == 1 && saved != undefined) {
        if (!mistrimulti_player_send("profile_record", player, peer.epoch, saved.revision, saved.data)) return false;
    } else {
        // Start over. The old records stay where they are (the new ones replace them with the first upload and the old
        // ones then stay as .bak) and are copied aside as well: a crash in the editor loses nothing.
        mistrimulti_player_keep_replaced(data.uid);
        if (!mistrimulti_event_emit("profile_start", { peer_epoch: peer.epoch, uid: data.uid, world: r.world_key }, player)) return false;
        session.revision = 0;
        session.replaced = true;
    }
    session.asking = false;
    return true;
}

// The old character goes into the history of this identity in this world (MistriMultiCharPicker.gml); the current records stay.
function mistrimulti_player_keep_replaced(uid) {
    mistrimulti_history_demote(uid);
}

// profile_request (guest -> host) and the host's answers (targeted at one guest by the event layer).
function mistrimulti_player_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (!is_struct(data)) return true;
    try {
        var kind = ctx.kind;
        if (kind == "profile_request") return mistrimulti_player_request(player, data);
        if (kind == "profile_choice") return mistrimulti_player_choice(player, data);
        if (r.mode != "join" || player != 0 || data[$ "peer_epoch"] != r.epoch) return true;
        if (kind == "profile_start" && data[$ "uid"] == r.uid && data[$ "world"] == r.world_key) {
            if (!r.player_ready) mistrimulti_player_fresh();
            r.player_error = "";
            r.character_phase = "edit";
            mmapi_log_warn("mistrimulti", "The host has no character of yours in this world: you create a new one.");
        } else if (kind == "profile_exists" && data[$ "uid"] == r.uid && data[$ "world"] == r.world_key) {
            if (r.character_phase == "") r.character_phase = "ask";
            r.character_chars = mistrimulti_charpicker_clean(data[$ "chars"]);
            r.player_error = "";
        } else if (kind == "profile_error") {
            r.player_error = string(data[$ "message"]);
            mistrimulti_charpicker_failed(r);
        } else if (kind == "profile_saved" && data[$ "world"] == r.world_key && data[$ "revision"] == r.player_revision) {
            r.player_saved_revision = r.player_revision;
            r.player_error = "";
        }
        return true;
    } catch (e) {
        r.player_error = "A player record could not be processed.";
        mmapi_warn_rate_limited("mistrimulti_player_receive", "mistrimulti", r.player_error + " " + string(e));
        return false;
    }
}

function mistrimulti_player_upload(player, text, meta) {
    return mistrimulti_player_receive_record(player, true, text, meta);
}

function mistrimulti_player_download(player, text, meta) {
    return mistrimulti_player_receive_record(player, false, text, meta);
}

// A complete record (the event layer delivers blobs whole or not at all). Returning false retries later.
function mistrimulti_player_receive_record(player, upload, text, meta) {
    var r = __mistrimulti_runtime();
    try {
        if (upload ? (r.mode != "host" || player == 0) : (r.mode != "join" || player != 0)) return true;
        if (!is_struct(meta)) return true;
        var session = upload ? r.player_sessions[player] : undefined;
        var epoch = upload ? r.peers[player].epoch : r.epoch;
        var uid = upload ? r.peers[player][$ "uid"] : r.uid;
        if (meta[$ "peer_epoch"] != epoch || meta[$ "uid"] != uid || meta[$ "world"] != r.world_key) return true;
        if (upload && (!is_struct(session) || session.epoch != epoch || session.uid != uid)) return true;
        // An upload is stored only while the slot still belongs to the install this record is bound to.
        var bound = r[$ "trust_bound"];
        if (upload && bound != undefined && !bound(player, uid)) return true;
        var revision = meta[$ "revision"];
        if (!is_real(revision) || revision < 0 || revision != floor(revision)) return true;
        if (upload && revision == session.revision) return mistrimulti_event_emit("profile_saved",
            { peer_epoch: epoch, world: r.world_key, revision: session.revision }, player);
        if (upload && revision != session.revision + 1) return true;
        var profile;
        try { profile = json_parse(text); }
        catch (e) { return true; }
        if (!mistrimulti_player_valid(profile, uid, r.world_key)) {
            if (upload) return mistrimulti_event_emit("profile_error", { peer_epoch: epoch, message: "The player update was rejected." }, player);
            r.player_error = "The host sent an invalid player record.";
            return true;
        }
        if (upload) {
            // One partner per NPC: a claim another player holds is downgraded before the record is saved.
            var taken = mistrimulti_romance_arbitrate(uid, profile);
            if (!mistrimulti_player_store(uid, revision, profile)) return false;
            session.revision = revision;
            if (array_length(taken) > 0) mistrimulti_event_emit("romance_revoke", { peer_epoch: epoch, npcs: taken }, player);
            return mistrimulti_event_emit("profile_saved", { peer_epoch: epoch, world: r.world_key, revision: session.revision }, player);
        }
        if (MIST.is_running() || ARI == undefined) return false;
        // A guest who chose a new character (or has none here) is in the editor: a record must not replace it.
        if (r[$ "character_phase"] == "edit") {
            mmapi_log_warn("mistrimulti", "A saved character arrived while the new character is being made; it is ignored.");
            return true;
        }
        if (!mistrimulti_player_restore(profile)) return false;
        r.player_revision = revision;
        r.player_saved_revision = revision;
        r.player_signature = json_stringify(mistrimulti_player_capture());
        r.player_error = "";
        mistrimulti_charcache_remember();
        return true;
    } catch (e) {
        r.player_error = "A player record could not be processed.";
        mmapi_warn_rate_limited("mistrimulti_player_receive", "mistrimulti", r.player_error + " " + string(e));
        return false;
    }
}

function mistrimulti_debug_player_data() {
    var r = __mistrimulti_runtime();
    return { world: r.world_key, world_path: r.world_path, mask: r.mask,
        ready: r.player_ready, revision: r.player_revision,
        saved_revision: r.player_saved_revision, error: r.player_error,
        outgoing: mistrimulti_event_blobs_pending(), profile: mistrimulti_player_capture() };
}
