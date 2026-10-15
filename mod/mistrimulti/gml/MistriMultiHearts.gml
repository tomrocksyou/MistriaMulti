// World options chosen when the host starts a new world, and the "shared hearts" option.
//
// Options live on the host in worlds/<world key>/options.json (written once, when the world is first hosted; a world
// hosted before options existed gets the defaults) and reach the guests in the host's frame ("o"). Defaults: every player
// has their own hearts with each villager.
//
// Shared hearts: one friendship value per villager for the whole world. The host's own villagers hold it. A guest's gain
// (talking, gifts: the game's npc.heart_points filter) is not applied locally; it is asked of the host ("heart_add"),
// which adds it once and sends every villager's points to everybody ("hearts"). Dating, engagement and marriage stay per
// player (MistriMultiProgress.gml keeps one partner per villager). Heart events and romance scenes stay private.
#macro MISTRIMULTI_HEARTS_MAX_ADD 5000

function mistrimulti_world_options_default() {
    return { v: 1, hearts: "own" };
}

function mistrimulti_world_options_clean(o) {
    var out = mistrimulti_world_options_default();
    if (is_struct(o) && (o[$ "hearts"] == "own" || o[$ "hearts"] == "shared")) out.hearts = o.hearts;
    return out;
}

// Host: the options of the world just loaded. A new world takes the choices made in the New world popups.
// The choices made in the New world popups (MistriMultiSaveSpace.gml), until the new world is first hosted.
function mistrimulti_world_options_pending(set = undefined) {
    if (set != undefined) global.__mistrimulti_new_world_options = set;
    return global[$ "__mistrimulti_new_world_options"];
}

function mistrimulti_world_options_load(world_path) {
    var path = world_path + "/options.json";
    var opts;
    if (file_exists(path)) {
        opts = mistrimulti_world_options_clean(try_read_json_file(path));
    } else {
        opts = mistrimulti_world_options_clean(mistrimulti_world_options_pending());
        save_text_file(path, json_stringify(opts));
    }
    global.__mistrimulti_new_world_options = undefined;
    mmapi_log_info("mistrimulti", "World options: " + json_stringify(opts));
    return opts;
}

function mistrimulti_world_options() {
    var r = __mistrimulti_runtime();
    if (r.mode == "host") return is_struct(r[$ "world_opts"]) ? r.world_opts : mistrimulti_world_options_default();
    var host = r.peers[0];
    return mistrimulti_world_options_clean(is_struct(host) ? host[$ "o"] : undefined);
}

function mistrimulti_hearts_shared() {
    return mistrimulti_world_options().hearts == "shared";
}

// ---- events ---------------------------------------------------------------------------------------------------

function mistrimulti_hearts_register_events() {
    mistrimulti_event_register("hearts", { on_event: mistrimulti_hearts_event, on_peer: mistrimulti_hearts_peer });
    mistrimulti_event_register("heart_add", { on_request: mistrimulti_hearts_request });
}

function __mistrimulti_hearts() {
    var r = __mistrimulti_runtime();
    if (!is_struct(r[$ "hearts"])) r.hearts = { sig: "", dirty: true };
    return r.hearts;
}

// npc.heart_points filter (every heart gain of this game's player). A guest in a shared-hearts world asks the host instead.
function mistrimulti_hearts_filter(value, npc) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || r.mode != "join" || (r.mask & 1) == 0 || !is_real(value) || value <= 0) return undefined;
    try {
        if (!mistrimulti_hearts_shared()) return undefined;
        var amount = min(value, MISTRIMULTI_HEARTS_MAX_ADD);
        if (mistrimulti_event_request("heart_add", { n: npc.id, a: amount }) == undefined) return undefined; // queue full: keep it local
        return 0;
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_hearts", "mistrimulti", "Shared hearts failed: " + string(e));
        return undefined;
    }
}

// Host: a guest gained hearts.
function mistrimulti_hearts_request(player, data, ctx) {
    var r = __mistrimulti_runtime();
    var peer = r.peers[player];
    if (player == r.id || !is_struct(peer) || peer[$ "active"] != true || !mistrimulti_hearts_shared() || !is_struct(data)) return { ok: false };
    var n = data[$ "n"];
    var a = data[$ "a"];
    if (!is_real(n) || n != floor(n) || n < 0 || n >= NpcId.LEN || !is_real(a) || a <= 0 || a > MISTRIMULTI_HEARTS_MAX_ADD) return { ok: false };
    var npc = NPCS[n];
    npc.heart_points += a;
    npc.report_hearts();
    __mistrimulti_hearts().dirty = true;
    return { ok: true };
}

function mistrimulti_hearts_peer(slot, joined, stream) {
    if (joined) __mistrimulti_hearts().dirty = true;
}

// Guests: the world's hearts.
function mistrimulti_hearts_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (player != 0 || r.mode != "join" || !is_struct(data) || !mistrimulti_hearts_shared()) return true;
    var p = data[$ "p"];
    if (!is_array(p) || array_length(p) != NpcId.LEN) return true;
    for (var i = 0; i < NpcId.LEN; i++) if (!is_real(p[i]) || p[i] < 0 || p[i] > 100000000) return true;
    for (var i = 0; i < NpcId.LEN; i++) {
        var npc = NPCS[i];
        if (npc.heart_points == p[i]) continue;
        var old = npc.heart_level();
        npc.heart_points = p[i];
        npc.report_hearts();
        if (npc.heart_level() > old) {
            try { ANCHOR.get_menu(Menu.Dingaling).create_heart_dingaling(i, old); } catch (e) {}
        }
    }
    return true;
}

// Host, every bridge tick: send the hearts when they changed (the host's own gifts too) or somebody joined.
function mistrimulti_hearts_tick() {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || r.mask == 0 || !mistrimulti_hearts_shared()) return;
    try {
        var h = __mistrimulti_hearts();
        var p = array_create(NpcId.LEN, 0);
        for (var i = 0; i < NpcId.LEN; i++) p[i] = NPCS[i].heart_points;
        var sig = json_stringify(p);
        if (sig == h.sig && !h.dirty) return;
        if (mistrimulti_event_emit("hearts", { p: p })) { h.sig = sig; h.dirty = false; }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_hearts", "mistrimulti", "Shared hearts failed: " + string(e));
    }
}
