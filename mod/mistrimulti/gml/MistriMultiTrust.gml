// Host authority, identity binding and abuse limits. Design, threat model and checklist: docs/SECURITY.md.
//
// The native helper authenticates every guest (password, per-install key) and publishes the verified install
// fingerprint of each slot as <bridge>/auth_<slot>.json. Nothing a guest sends in a snapshot or an event is trusted
// to say who it is: a record (inventory, progress) is keyed by an identity (the uid, a Steam ID or a local id, only a
// claim) that is bound to ONE install fingerprint the first time it is used. A different install claiming it is
// refused until the host approves the re-bind (F7), or refuses it for good (Shift+F7, which also bans that install).
//
// Everything here is optional for the event layer and the record handshake: the runtime slots r.trust_gate and
// r.trust_admit are only set when mistrimulti_trust_initialize runs, and the callers check for them.
#macro MISTRIMULTI_TRUST_PENDING_MAX 8
#macro MISTRIMULTI_TRUST_BOUND_MAX 256
#macro MISTRIMULTI_TRUST_PER_INSTALL 4
#macro MISTRIMULTI_TRUST_DENIED_MAX 64
// Per guest: sustained events/s, requests/s and blob bytes/s (each with a burst of twice that); new event streams.
#macro MISTRIMULTI_TRUST_EVENT_RATE 300
#macro MISTRIMULTI_TRUST_REQUEST_RATE 40
#macro MISTRIMULTI_TRUST_BLOB_RATE 524288
#macro MISTRIMULTI_TRUST_STREAM_BURST 6

// ---- validation ---------------------------------------------------------------------------------------

function mistrimulti_trust_valid_fp(fp) {
    if (!is_string(fp) || string_length(fp) != 32) return false;
    for (var i = 1; i <= 32; i++) {
        var c = ord(string_char_at(fp, i));
        if ((c >= ord("0") && c <= ord("9")) || (c >= ord("a") && c <= ord("f"))) continue;
        return false;
    }
    return true;
}

function __mistrimulti_trust_path() {
    return mistrimulti_data_dir() + "/trust.json";
}

function __mistrimulti_trust_notify(text) {
    mmapi_log_info("mistrimulti", text);
    try { create_notification(ANCHOR.wrap_for_local(text)); } catch (e) { }
}

// ---- lifecycle ----------------------------------------------------------------------------------------

function mistrimulti_trust_initialize() {
    var r = __mistrimulti_runtime();
    r.trust = { bound: {}, pending: [], denied: [], limits: array_create(8, undefined), host_pin: "", warning: "",
        failures: 0, host_verified: false };
    r.trust_admit = undefined;
    r.trust_bound = undefined;
    r.trust_gate = undefined;
    r.trust_host_ok = undefined;
    if (r.mode == "join") r.trust_host_ok = mistrimulti_trust_host_ok;
    if (r.mode != "host") return;
    r.trust_admit = mistrimulti_trust_admit;
    r.trust_bound = mistrimulti_trust_still_bound;
    r.trust_gate = mistrimulti_trust_gate;
    mistrimulti_trust_load();
}

// trust.json: { v: 1, bound: { uid: { fp, name } }, denied: [ { fp, name } ] }. A damaged file is kept aside and
// treated as empty: identities that already have a record then need the host's approval (safe, never open).
function mistrimulti_trust_load() {
    var r = __mistrimulti_runtime();
    var path = __mistrimulti_trust_path();
    if (!file_exists(path)) return;
    var saved = try_read_json_file(path);
    if (!is_struct(saved) || saved[$ "v"] != 1 || !is_struct(saved[$ "bound"])) {
        try { file_rename(path, path + ".bad"); } catch (e) { }
        r.trust.warning = "trust.json was damaged; identities need the host's approval again.";
        mmapi_warn_rate_limited("mistrimulti_trust", "mistrimulti", r.trust.warning);
        return;
    }
    var uids = struct_get_names(saved.bound);
    for (var i = 0; i < array_length(uids) && i < MISTRIMULTI_TRUST_BOUND_MAX; i++) {
        var entry = saved.bound[$ uids[i]];
        if (!mistrimulti_valid_uid(uids[i]) || !is_struct(entry) || !mistrimulti_trust_valid_fp(entry[$ "fp"])) continue;
        r.trust.bound[$ uids[i]] = { fp: entry.fp, name: is_string(entry[$ "name"]) ? string_copy(entry.name, 1, 64) : "" };
    }
    var denied = saved[$ "denied"];
    if (is_array(denied)) {
        for (var j = 0; j < array_length(denied) && j < MISTRIMULTI_TRUST_DENIED_MAX; j++) {
            if (is_struct(denied[j]) && mistrimulti_trust_valid_fp(denied[j][$ "fp"])) {
                array_push(r.trust.denied, { fp: denied[j].fp, name: is_string(denied[j][$ "name"]) ? string_copy(denied[j].name, 1, 64) : "" });
            }
        }
    }
}

function mistrimulti_trust_save() {
    var r = __mistrimulti_runtime();
    var path = __mistrimulti_trust_path();
    try {
        save_text_file(path + ".tmp", json_stringify({ v: 1, bound: r.trust.bound, denied: r.trust.denied }));
        file_rename(path + ".tmp", path);
        return true;
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_trust", "mistrimulti", "Trust records could not be saved.");
        return false;
    }
}

// ---- verified install fingerprints (written by the helper) ------------------------------------------

// The helper's verdict for a slot: { fp, gen, state, reject } or undefined. state 1 means authenticated.
function mistrimulti_trust_slot(slot) {
    var r = __mistrimulti_runtime();
    var path = r.bridge + "/auth_" + string(slot) + ".json";
    if (!file_exists(path)) return undefined;
    var auth = try_read_json_file(path);
    if (!is_struct(auth) || !is_real(auth[$ "state"]) || !is_real(auth[$ "gen"])) return undefined;
    if (auth.state == 1 && !mistrimulti_trust_valid_fp(auth[$ "fp"])) return undefined;
    return auth;
}

// ---- identity binding (host) ----------------------------------------------------------------------------

function __mistrimulti_trust_refuse(message) {
    return { ok: false, message: message };
}

function __mistrimulti_trust_installs_of(fp) {
    var r = __mistrimulti_runtime();
    var uids = struct_get_names(r.trust.bound);
    var count = 0;
    for (var i = 0; i < array_length(uids); i++) if (r.trust.bound[$ uids[i]].fp == fp) count++;
    return count;
}

// Called by the host before it hands out or accepts a player record. `request` is the guest's profile_request.
// Returns { ok: true } or { ok: false, message } (the message goes back to the guest).
function mistrimulti_trust_admit(player, uid, name, request) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host") return { ok: true };
    var auth = mistrimulti_trust_slot(player);
    if (auth == undefined || auth.state != 1) return __mistrimulti_trust_refuse("The host has not verified this install.");
    var fp = auth.fp;
    var bound = r.trust.bound[$ uid];
    if (is_struct(bound)) {
        if (bound.fp == fp) return { ok: true };
        return __mistrimulti_trust_pending(player, uid, name, request, fp, "bound");
    }
    // A record that exists without a binding (made before bindings existed, or a lost trust.json) is claimed only
    // with the host's approval; a brand new identity is bound on first use.
    var path = mistrimulti_player_path(uid);
    if (file_exists(path) || file_exists(path + ".bak")) return __mistrimulti_trust_pending(player, uid, name, request, fp, "unbound");
    if (array_length(struct_get_names(r.trust.bound)) >= MISTRIMULTI_TRUST_BOUND_MAX
        || __mistrimulti_trust_installs_of(fp) >= MISTRIMULTI_TRUST_PER_INSTALL) {
        return __mistrimulti_trust_refuse("This host has no room for another identity from this install.");
    }
    r.trust.bound[$ uid] = { fp: fp, name: is_string(name) ? string_copy(name, 1, 64) : "" };
    mistrimulti_trust_save();
    return { ok: true };
}

function __mistrimulti_trust_pending(player, uid, name, request, fp, why) {
    var r = __mistrimulti_runtime();
    var code = string_copy(fp, 1, 8);
    var list = r.trust.pending;
    for (var i = 0; i < array_length(list); i++) {
        if (list[i].uid == uid && list[i].fp == fp) {
            list[i].slot = player;
            list[i].epoch = r.peers[player][$ "epoch"];
            list[i].request = request;
            return __mistrimulti_trust_refuse("Waiting for the host to approve this install (code " + code + ").");
        }
    }
    if (array_length(list) >= MISTRIMULTI_TRUST_PENDING_MAX) {
        return __mistrimulti_trust_refuse("The host has too many open approvals; try again later.");
    }
    array_push(list, { uid: uid, fp: fp, name: is_string(name) ? string_copy(name, 1, 64) : "", slot: player,
        epoch: r.peers[player][$ "epoch"], request: request, why: why });
    __mistrimulti_trust_notify((is_string(name) && name != "" ? name : "A player") + " wants to use "
        + (why == "bound" ? "an identity bound to another install" : "a saved identity")
        + " (code " + code + "). F7 approves, Shift+F7 refuses.");
    return __mistrimulti_trust_refuse("This player identity needs the host's approval (code " + code + ").");
}

// F7: approve the oldest open request and let that guest continue.
function mistrimulti_trust_approve() {
    var r = __mistrimulti_runtime();
    if (!r.enabled) return false;
    if (r.mode != "host") return mistrimulti_trust_accept_host();
    var list = r.trust.pending;
    if (array_length(list) == 0) {
        __mistrimulti_trust_notify("Nothing is waiting for approval.");
        return false;
    }
    var item = list[0];
    array_delete(list, 0, 1);
    var auth = mistrimulti_trust_slot(item.slot);
    var live = auth != undefined && auth.state == 1 && auth.fp == item.fp
        && (r.mask & (1 << item.slot)) != 0 && is_struct(r.peers[item.slot]) && r.peers[item.slot][$ "epoch"] == item.epoch;
    if (!live) {
        __mistrimulti_trust_notify("That request is no longer current; the player must reconnect.");
        return false;
    }
    r.trust.bound[$ item.uid] = { fp: item.fp, name: item.name };
    mistrimulti_trust_save();
    __mistrimulti_trust_notify("Approved " + (item.name != "" ? item.name : item.uid) + " (code " + string_copy(item.fp, 1, 8) + ").");
    // Run the guest's request again: it now passes and the record is handed over as for any returning player.
    if (is_struct(item.request) && r.player_sessions[item.slot] == undefined) mistrimulti_player_request(item.slot, item.request);
    return true;
}

// Shift+F7: refuse the oldest open request and ban that install.
function mistrimulti_trust_refuse() {
    var r = __mistrimulti_runtime();
    if (!r.enabled || r.mode != "host") return false;
    var list = r.trust.pending;
    if (array_length(list) == 0) return false;
    var item = list[0];
    array_delete(list, 0, 1);
    mistrimulti_trust_deny(item.fp, item.name);
    __mistrimulti_trust_notify("Refused and banned " + (item.name != "" ? item.name : item.uid) + " (code " + string_copy(item.fp, 1, 8) + ").");
    return true;
}

// Remove a binding (a friend who lost their install and Steam account recovers on a new install).
function mistrimulti_trust_unbind(uid) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || !is_struct(r.trust.bound[$ uid])) return false;
    struct_remove(r.trust.bound, uid);
    return mistrimulti_trust_save();
}

// Is this slot still the install that was admitted for its record? Checked before an upload is stored.
function mistrimulti_trust_still_bound(player, uid) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host") return true;
    var auth = mistrimulti_trust_slot(player);
    var bound = r.trust.bound[$ uid];
    return auth != undefined && auth.state == 1 && is_struct(bound) && bound.fp == auth.fp;
}

// ---- deny list (the helper re-reads deny.txt every second and removes listed players) -------------------

function mistrimulti_trust_deny(fp, name) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || !mistrimulti_trust_valid_fp(fp)) return false;
    for (var i = 0; i < array_length(r.trust.denied); i++) if (r.trust.denied[i].fp == fp) return true;
    if (array_length(r.trust.denied) >= MISTRIMULTI_TRUST_DENIED_MAX) return false;
    array_push(r.trust.denied, { fp: fp, name: is_string(name) ? string_copy(name, 1, 64) : "" });
    mistrimulti_trust_save();
    // deny.txt keeps whatever the host wrote by hand; the fingerprint is appended on its own line.
    var path = mistrimulti_data_dir() + "/deny.txt";
    var text = "";
    if (file_exists(path)) {
        try { text = read_text_file(path); } catch (e) { text = ""; }
    }
    if (text != "" && string_char_at(text, string_length(text)) != "\n") text += "\n";
    var label = "";
    if (is_string(name)) {
        for (var k = 1; k <= string_length(name) && k <= 32; k++) {
            var ch = string_char_at(name, k);
            if (ord(ch) >= 32 && ord(ch) < 127 && ch != "#") label += ch;
        }
    }
    save_text_file(path + ".tmp", text + fp + (label != "" ? "  # " + label : "") + "\n");
    file_rename(path + ".tmp", path);
    return true;
}

// ---- abuse limits (host side of the event layer) -----------------------------------------------------

function __mistrimulti_trust_bucket(rate, cap) {
    return { tokens: cap, at: get_timer(), rate: rate, cap: cap };
}

function __mistrimulti_trust_fill(b, now) {
    b.tokens = min(b.cap, b.tokens + (now - b.at) / 1000000 * b.rate);
    b.at = now;
}

function __mistrimulti_trust_limits(slot) {
    var r = __mistrimulti_runtime();
    var s = r.trust.limits[slot];
    if (!is_struct(s)) {
        s = { events: __mistrimulti_trust_bucket(MISTRIMULTI_TRUST_EVENT_RATE, MISTRIMULTI_TRUST_EVENT_RATE * 2),
            requests: __mistrimulti_trust_bucket(MISTRIMULTI_TRUST_REQUEST_RATE, MISTRIMULTI_TRUST_REQUEST_RATE * 2),
            blobs: __mistrimulti_trust_bucket(MISTRIMULTI_TRUST_BLOB_RATE, MISTRIMULTI_TRUST_BLOB_RATE * 2),
            streams: __mistrimulti_trust_bucket(0.1, MISTRIMULTI_TRUST_STREAM_BURST) };
        r.trust.limits[slot] = s;
    }
    return s;
}

// The event layer asks before it hands a guest's event to a handler (item undefined: the guest announces a new event
// stream). false makes the layer wait: the event stays unacknowledged, the guest keeps its queue and retries, so
// nothing is lost and one flooding guest cannot starve the others.
function mistrimulti_trust_gate(slot, item) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || slot == r.id || slot < 0 || slot > 7) return true;
    var s = __mistrimulti_trust_limits(slot);
    var now = get_timer();
    if (item == undefined) {
        __mistrimulti_trust_fill(s.streams, now);
        if (s.streams.tokens < 1) { r.trust.failures++; return false; }
        s.streams.tokens -= 1;
        return true;
    }
    __mistrimulti_trust_fill(s.events, now);
    __mistrimulti_trust_fill(s.requests, now);
    __mistrimulti_trust_fill(s.blobs, now);
    var kind = is_struct(item) ? item[$ "k"] : undefined;
    var bytes = 0;
    if (kind == "~b") {
        var chunk = is_struct(item[$ "d"]) ? item.d[$ "x"] : undefined;
        bytes = is_string(chunk) ? string_byte_length(chunk) : 0;
    }
    if (s.events.tokens < 1 || (kind == "~q" && s.requests.tokens < 1) || (bytes > 0 && s.blobs.tokens < bytes)) {
        r.trust.failures++;
        return false;
    }
    s.events.tokens -= 1;
    if (kind == "~q") s.requests.tokens -= 1;
    if (bytes > 0) s.blobs.tokens -= bytes;
    return true;
}

// ---- the guest's view of the host --------------------------------------------------------------------

// A guest remembers which host identity belongs to a hosted world. A host that suddenly proves a different identity
// (a reinstall, or someone else at the same address) is not trusted with the player record until the guest accepts
// it (F7). Returns true when the record handshake may go ahead.
function mistrimulti_trust_host_ok() {
    var r = __mistrimulti_runtime();
    if (r.mode != "join") return true;
    var auth = mistrimulti_trust_slot(0);
    if (auth == undefined || auth.state != 2 || !mistrimulti_trust_valid_fp(auth[$ "fp"]) || r.world_key == "") return false;
    if (r.trust.host_pin == auth.fp) return true;
    var path = mistrimulti_data_dir() + "/known_hosts.json";
    var known = file_exists(path) ? try_read_json_file(path) : undefined;
    if (!is_struct(known) || !is_struct(known[$ "hosts"])) known = { v: 1, hosts: {} };
    var pinned = known.hosts[$ r.world_key];
    if (!mistrimulti_trust_valid_fp(pinned)) {
        known.hosts[$ r.world_key] = auth.fp;
        __mistrimulti_trust_write_known(path, known);
        r.trust.host_pin = auth.fp;
        return true;
    }
    if (pinned == auth.fp) {
        r.trust.host_pin = auth.fp;
        return true;
    }
    r.trust.warning = "The host's identity changed (was " + string_copy(pinned, 1, 8) + ", now " + string_copy(auth.fp, 1, 8)
        + "). Press F7 only if the host reinstalled the game.";
    return false;
}

function __mistrimulti_trust_write_known(path, known) {
    var names = struct_get_names(known.hosts);
    if (array_length(names) > 64) struct_remove(known.hosts, names[0]);
    try {
        save_text_file(path + ".tmp", json_stringify(known));
        file_rename(path + ".tmp", path);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_trust", "mistrimulti", "Known hosts could not be saved.");
    }
}

// Guest F7: accept the host's new identity for this world.
function mistrimulti_trust_accept_host() {
    var r = __mistrimulti_runtime();
    var auth = mistrimulti_trust_slot(0);
    if (r.mode != "join" || auth == undefined || auth.state != 2 || r.world_key == "") return false;
    var path = mistrimulti_data_dir() + "/known_hosts.json";
    var known = file_exists(path) ? try_read_json_file(path) : undefined;
    if (!is_struct(known) || !is_struct(known[$ "hosts"])) known = { v: 1, hosts: {} };
    known.hosts[$ r.world_key] = auth.fp;
    __mistrimulti_trust_write_known(path, known);
    r.trust.host_pin = auth.fp;
    r.trust.host_verified = true;
    r.trust.warning = "";
    __mistrimulti_trust_notify("Host identity accepted.");
    return true;
}

// ---- status text ---------------------------------------------------------------------------------------

function mistrimulti_trust_status_text() {
    var r = __mistrimulti_runtime();
    if (!is_struct(r[$ "trust"])) return "";
    if (r.mode == "host") {
        // Each connected guest with the first eight characters of its install fingerprint: the code to put in deny.txt
        // (the whole fingerprint is in <bridge>/auth_<slot>.json) and the code shown to a guest who needs approval.
        var text = "";
        for (var i = 1; i < 8; i++) {
            var peer = r.peers[i];
            var auth = (r.mask & (1 << i)) != 0 ? mistrimulti_trust_slot(i) : undefined;
            if (auth == undefined || auth.state != 1) continue;
            var who = is_struct(peer) && is_string(peer[$ "name"]) ? string_copy(peer.name, 1, 16) : "player";
            text += (text == "" ? "" : ", ") + who + " " + string_copy(auth.fp, 1, 8);
        }
        var waiting = array_length(r.trust.pending);
        if (waiting > 0) text += (text == "" ? "" : " | ") + string(waiting) + " waiting for approval (F7)";
        return text;
    }
    var auth = mistrimulti_trust_slot(0);
    if (r.trust.warning != "") return r.trust.warning;
    if (auth == undefined) return "";
    var why = auth[$ "reject"];
    if (auth.state == 2 || !is_real(why) || why == 0) return "";
    if (why == 1) return "The host refused the join: wrong or missing password.";
    if (why == 2) return "The host has banned this install.";
    if (why == 3) return "That player slot is in use by someone else.";
    if (why == 4) return "The host cannot take another identity.";
    if (why == 6) return "The host needs a password. Set it in the launcher configuration.";
    return "The host refused the join.";
}

function mistrimulti_trust_hotkey_approve() {
    try { mistrimulti_trust_approve(); }
    catch (e) { mmapi_warn_rate_limited("mistrimulti_trust", "mistrimulti", "Approval failed: " + string(e)); }
}

function mistrimulti_trust_hotkey_refuse() {
    try { mistrimulti_trust_refuse(); }
    catch (e) { mmapi_warn_rate_limited("mistrimulti_trust", "mistrimulti", "Refusal failed: " + string(e)); }
}

function mistrimulti_trust_debug() {
    var r = __mistrimulti_runtime();
    var t = r[$ "trust"];
    if (!is_struct(t)) return { enabled: false };
    return { bound: t.bound, pending: array_length(t.pending), denied: array_length(t.denied), limited: t.failures,
        warning: t.warning, auth: mistrimulti_trust_slot(r.mode == "host" ? 1 : 0) };
}
