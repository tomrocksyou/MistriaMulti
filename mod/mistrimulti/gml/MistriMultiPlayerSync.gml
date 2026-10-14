function mistrimulti_player_reset_session() {
    var r = __mistrimulti_runtime();
    r.player_ready = false;
    r.player_revision = 0;
    r.player_saved_revision = 0;
    r.player_signature = "";
    r.player_last_checkpoint = 0;
    r.player_request = "";
    r.player_incoming = undefined;
    r.player_outgoing = [];
    r.player_sessions = array_create(8, undefined);
    r.player_error = "";
    r.queue = [];
    r.next_event = 1;
    r.epoch += "_" + string(get_timer());
    r.character_owner = undefined;
    r.character_pending = true;
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
            r.world_path = mmapi_mod_data_dir("mistrimulti") + "/worlds/" + r.world_key;
            directory_create(mmapi_mod_data_dir("mistrimulti") + "/worlds");
            directory_create(r.world_path);
            directory_create(r.world_path + "/players");
            save_text_file(r.world_path + "/world.json", json_stringify({ v: 1,
                world: r.world_key, game_id: Game.unique_identifier, host: r.uid }));
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
        if (r.player_request == "" && array_length(r.queue) < 4) {
            if (mistrimulti_emit("profile_request", { world: r.world_key, uid: r.uid })) r.player_request = r.epoch;
            r.player_error = "Loading player progress from the host.";
        }
    }
    if (r.ticks mod 3 != 0) return;
    if (!r.player_ready || r.character_pending || MIST.is_running()) return;
    if (get_timer() - r.player_last_checkpoint >= 5000000 && array_length(r.player_outgoing) == 0) {
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
    return true;
}

function mistrimulti_player_send(kind, target, peer_epoch, revision, data) {
    var r = __mistrimulti_runtime();
    if (array_length(r.player_outgoing) >= 8) return false;
    var text = json_stringify(data);
    if (string_byte_length(text) > 131072) return false;
    var count = ceil(string_length(text) / 1536);
    if (count < 1 || count > 128) return false;
    array_push(r.player_outgoing, { kind: kind, target: target, peer_epoch: peer_epoch,
        uid: data.uid, world: r.world_key, revision: revision,
        transfer: r.epoch + ":" + string(revision) + ":" + string(get_timer()),
        text: text, count: count, next: 0 });
    return true;
}

function mistrimulti_player_send_tick() {
    var r = __mistrimulti_runtime();
    if (array_length(r.player_outgoing) == 0 || array_length(r.queue) >= 4) return;
    var job = r.player_outgoing[0];
    if (job.world != r.world_key || (job.target != r.id && (r.mask & (1 << job.target)) == 0)) {
        array_delete(r.player_outgoing, 0, 1);
        return;
    }
    if (mistrimulti_emit(job.kind, { world: job.world, uid: job.uid, to: job.target,
        peer_epoch: job.peer_epoch, revision: job.revision, transfer: job.transfer,
        total: job.count, index: job.next, text: string_copy(job.text, job.next * 1536 + 1, 1536) })) job.next++;
    if (job.next == job.count) array_delete(r.player_outgoing, 0, 1);
}

function mistrimulti_player_request(player, data) {
    var r = __mistrimulti_runtime();
    var peer = r.peers[player];
    if (r.mode != "host" || !r.player_ready || player == 0) return true;
    if (data[$ "world"] != r.world_key || data[$ "uid"] != peer[$ "uid"] || !mistrimulti_valid_uid(data.uid)) return true;
    if (data.uid == r.uid) return mistrimulti_emit("profile_error", { to: player,
        peer_epoch: peer.epoch, message: "The host is already using this player identity." });
    for (var i = 1; i < 8; i++) {
        var existing = r.player_sessions[i];
        if (i != player && (r.mask & (1 << i)) != 0 && is_struct(existing) && existing.uid == data.uid) {
            return mistrimulti_emit("profile_error", { to: player, peer_epoch: peer.epoch, message: "This player identity is already connected." });
        }
    }
    var session = r.player_sessions[player];
    if (is_struct(session) && session.epoch == peer.epoch && session.uid == data.uid) return true;
    var saved = mistrimulti_player_load(data.uid);
    if (saved == undefined && (file_exists(mistrimulti_player_path(data.uid)) || file_exists(mistrimulti_player_path(data.uid) + ".bak"))) {
        return mistrimulti_emit("profile_error", { to: player, peer_epoch: peer.epoch, message: "The host player record needs recovery." });
    }
    var success = saved == undefined
        ? mistrimulti_emit("profile_start", { to: player, peer_epoch: peer.epoch, uid: data.uid, world: r.world_key })
        : mistrimulti_player_send("profile_record", player, peer.epoch, saved.revision, saved.data);
    if (success) r.player_sessions[player] = { uid: data.uid, epoch: peer.epoch,
        revision: saved == undefined ? 0 : saved.revision, incoming: undefined };
    return success;
}

function mistrimulti_player_receive(player, kind, data) {
    var r = __mistrimulti_runtime();
    if (kind == "profile_request") return mistrimulti_player_request(player, data);
    if (data[$ "to"] != r.id) return true;
    if (kind == "profile_start" && r.mode == "join" && player == 0
        && data[$ "peer_epoch"] == r.epoch && data[$ "uid"] == r.uid && data[$ "world"] == r.world_key) {
        if (!r.player_ready) mistrimulti_player_fresh();
        r.player_error = "";
        return true;
    }
    if (kind == "profile_error" && r.mode == "join" && player == 0 && data[$ "peer_epoch"] == r.epoch) {
        r.player_error = string(data[$ "message"]);
        return true;
    }
    if (kind == "profile_saved" && r.mode == "join" && player == 0
        && data[$ "peer_epoch"] == r.epoch && data[$ "world"] == r.world_key && data[$ "revision"] == r.player_revision) {
        r.player_saved_revision = r.player_revision;
        r.player_error = "";
        return true;
    }
    var upload = kind == "profile_update" && r.mode == "host" && player != 0;
    var download = kind == "profile_record" && r.mode == "join" && player == 0;
    if (!upload && !download) return true;
    var session = upload ? r.player_sessions[player] : undefined;
    var epoch = upload ? r.peers[player].epoch : r.epoch;
    var uid = upload ? r.peers[player][$ "uid"] : r.uid;
    if (data[$ "peer_epoch"] != epoch || data[$ "uid"] != uid || data[$ "world"] != r.world_key) return true;
    if (upload && (!is_struct(session) || session.epoch != epoch || session.uid != uid)) return true;
    if (!is_real(data[$ "revision"]) || data.revision < 0 || data.revision != floor(data.revision)) return true;
    if (upload && data.revision == session.revision) return mistrimulti_emit("profile_saved", { to: player, peer_epoch: epoch, world: r.world_key, revision: session.revision });
    if (upload && data.revision != session.revision + 1) return true;
    if (!is_string(data[$ "transfer"]) || string_length(data.transfer) > 200 || !is_string(data[$ "text"]) || string_length(data.text) > 1536) return true;
    if (!is_real(data[$ "total"]) || data.total < 1 || data.total > 128 || data.total != floor(data.total)) return true;
    if (!is_real(data[$ "index"]) || data.index < 0 || data.index >= data.total || data.index != floor(data.index)) return true;
    var incoming = upload ? session.incoming : r.player_incoming;
    if (data.index == 0 && (!is_struct(incoming) || incoming.transfer != data.transfer)) {
        incoming = { transfer: data.transfer, revision: data.revision, total: data.total, next: 0, text: "" };
        if (upload) session.incoming = incoming; else r.player_incoming = incoming;
    }
    if (!is_struct(incoming) || incoming.transfer != data.transfer || incoming.total != data.total || incoming.revision != data.revision) return true;
    if (data.index > incoming.next) return true;
    if (data.index == incoming.next) { incoming.text += data.text; incoming.next++; }
    if (string_byte_length(incoming.text) > 131072) { incoming.text = ""; return true; }
    if (incoming.next < incoming.total) return true;
    var profile;
    try { profile = json_parse(incoming.text); }
    catch (e) { return true; }
    if (!mistrimulti_player_valid(profile, uid, r.world_key)) {
        if (upload) return mistrimulti_emit("profile_error", { to: player, peer_epoch: epoch, message: "The player update was rejected." });
        r.player_error = "The host sent an invalid player record.";
        return true;
    }
    if (upload) {
        if (!mistrimulti_player_store(uid, data.revision, profile)) return false;
        session.revision = data.revision;
        session.incoming = undefined;
        return mistrimulti_emit("profile_saved", { to: player, peer_epoch: epoch, world: r.world_key, revision: session.revision });
    }
    if (MIST.is_running() || ARI == undefined) return false;
    if (!mistrimulti_player_restore(profile)) return false;
    r.player_revision = data.revision;
    r.player_saved_revision = data.revision;
    r.player_signature = json_stringify(mistrimulti_player_capture());
    r.player_incoming = undefined;
    r.player_error = "";
    return true;
}

function mistrimulti_debug_player_data() {
    var r = __mistrimulti_runtime();
    return { world: r.world_key, world_path: r.world_path, mask: r.mask,
        ready: r.player_ready, revision: r.player_revision,
        saved_revision: r.player_saved_revision, error: r.player_error,
        outgoing: array_length(r.player_outgoing), profile: mistrimulti_player_capture() };
}
