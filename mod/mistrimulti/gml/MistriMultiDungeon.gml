// MistriaMulti mines sync: one shared dungeon run, the same floors for everyone, host-owned monster health and
// kills, and host-arbitrated rocks, chests, forageables, dig sites and ladders, on the event layer.
// Design, assumptions and the in-game checklist: docs/SYNC-DUNGEON.md.
//
// A "run" (id + seed) is chosen by the host and sent to everybody before anyone enters. Every game builds its
// itinerary and each floor from that seed, so the layouts agree as far as the game's own generator is
// deterministic. The first game on a floor (its "founder") then reports what was actually built (nodes and
// monsters, and what is left of them); the host keeps that as the floor's record, and every later arrival
// reconciles its build with the record. The record lives in the host's memory, not in the host's room, so
// it does not matter where the host is.
//
// Monsters: every game keeps its copies, but where they are comes from one game per floor, the floor's
// "authority" (the host when it is on the floor, otherwise the lowest slot there). The authority's game runs the
// monsters normally and streams their state in its peer frame (field dm, 10 Hz, latest wins); every other game
// moves its copies to the streamed places (see the monster section). Their health is the host's: every hit is
// reported, a game never lets its own copy die, and the host decides who struck the lethal blow. That game
// kills its copy the normal way (drops, essence and xp are its own, once); every other game removes its copy
// without drops.
//
// The seal rooms, the priestess's rooms and Seridia's chamber have no monsters; they only keep the run alive
// for the players inside them. The arena floor is shared like any other floor.

#macro MISTRIMULTI_DG_ERRORS 40
#macro MISTRIMULTI_DG_SLICE 50
#macro MISTRIMULTI_DG_NODES 800
#macro MISTRIMULTI_DG_MONSTERS 200
// Durations are in r.ticks (game frames, 60 a second); MISTRIMULTI_DG_OFFLINE counts bridge ticks (20 a second).
#macro MISTRIMULTI_DG_RETRY 30
#macro MISTRIMULTI_DG_SNAP_WAIT 1200
#macro MISTRIMULTI_DG_FOUNDING 600
#macro MISTRIMULTI_DG_EMPTY 300
#macro MISTRIMULTI_DG_OFFLINE 100
#macro MISTRIMULTI_DG_SCAN 10
#macro MISTRIMULTI_DG_BACKLOG 24
#macro MISTRIMULTI_DG_DAMAGE 5000
#macro MISTRIMULTI_DG_PENDING 300
#macro MISTRIMULTI_DG_PRESS 20
// Monster stream (peer frame): at most this many monsters per frame, one frame every this many ticks, and
// the ticks after which a silent authority is replaced / a monster not heard of goes back to its own AI.
#macro MISTRIMULTI_DG_STREAM 40
#macro MISTRIMULTI_DG_STREAM_TICKS 6
#macro MISTRIMULTI_DG_SILENT 240
#macro MISTRIMULTI_DG_STALE 120
#macro MISTRIMULTI_DG_SNAP_DIST 96
// The arena floor (DungeonImpl.Enemy) is shared like the others. Set to false to leave it to each game.
#macro MISTRIMULTI_DG_ARENA true

// ---- registration -------------------------------------------------------------------------------------------

// Event kinds: "dg_act" (requests: here, man, hit, pick, dig, use, gone, lad; the result goes to everybody),
// "dg_run" (host to everyone: the run id and seed) and "dg_snap" (host to one game: a floor record in slices).
function mistrimulti_dungeon_register_events() {
    mistrimulti_event_register("dg_act", { on_request: mistrimulti_dg_request, on_result: mistrimulti_dg_result,
        on_reply: mistrimulti_dg_reply });
    mistrimulti_event_register("dg_run", { on_event: mistrimulti_dg_run_event, on_peer: mistrimulti_dg_peer,
        on_gap: mistrimulti_dg_gap });
    mistrimulti_event_register("dg_snap", { on_event: mistrimulti_dg_snap_event });
}

function mistrimulti_dungeon_register_hooks() {
    mmapi_on("game.new_day", mistrimulti_dg_new_day);
    mmapi_on("dungeon.runner_created", mistrimulti_dg_runner_created);
    mmapi_on("dungeon.room_build_begin", mistrimulti_dg_build_begin);
    mmapi_on("dungeon.floor_built", mistrimulti_dg_floor_built);
    mmapi_guard("dungeon.ladder_spawn", mistrimulti_dg_ladder_guard);
    mmapi_filter("combat.damage", mistrimulti_dg_damage);
    mmapi_on("monster.step_end", mistrimulti_dg_monster_step);
    mmapi_filter("tool.targets", mistrimulti_dg_tool_targets);
    mmapi_override("object.interact", mistrimulti_dg_interact);
}

// ---- state --------------------------------------------------------------------------------------------------

// Per world session (it starts over whenever the event stream does).
function mistrimulti_dg_state() {
    var r = __mistrimulti_runtime();
    var d = r[$ "dg"];
    if (!is_struct(d) || d.stream != r.ev.stream) {
        d = { stream: r.ev.stream, errors: 0,
            // host: the run, the floors' records, who is where, snapshots on their way
            run: 0, seed: 0, used: false, empty_at: 0, dirty: false, floors: {}, at: array_create(8, undefined), snaps: [],
            // every game: the run this game's runner belongs to and the floor it is on
            my_run: 0, my_seed: 0, f: -1, st: "off", key: "", rid: "", asked: 0, retry: 0, build_at: 0, rejoin: false,
            offline: 0, up: undefined, rx: undefined, pend: [], gq: [], lad: undefined, reconciling: false, spawning: false,
            mons: {}, ikeys: {}, hp: {}, want: {}, nodes: {}, bypass: 0, swing: {}, swing_at: -100, press: {}, scan_at: 0,
            mnames: undefined, hits: 0, lost: 0,
            // special rooms (seal, priestess, Seridia): the floor number this game is in, or -1
            sp: -1,
            // monster stream: elected authority (-1 none), the monsters being followed, what this game streams
            au: -1, fol: {}, fseq: -1, fau: -1, seen: array_create(8, undefined), out: [], out_at: 0, cnt: 0, cur: 0 };
        r.dg = d;
    }
    return d;
}

function mistrimulti_dg_ok(d) {
    return d.errors < MISTRIMULTI_DG_ERRORS;
}

function mistrimulti_dg_fail(d, e) {
    d.errors++;
    mmapi_warn_rate_limited("mistrimulti_dungeon", "mistrimulti", "A mines update failed: " + string(e));
}

function mistrimulti_dg_online(r) {
    return r.enabled && (r.mode == "host" || (r.mask & 1) != 0);
}

function mistrimulti_dg_int(v, lo, hi) {
    return is_real(v) && v == floor(v) && v >= lo && v <= hi;
}

function mistrimulti_dg_cell_key(x, y) {
    return string(x) + "," + string(y);
}

function mistrimulti_dg_floor_key(run, f) {
    return string(run) + ":" + string(f);
}

// A random seed for the game's generator from the run seed and a purpose.
function mistrimulti_dg_hash(seed, text) {
    return __mistrimulti_ev_hash(MISTRIMULTI_EV_FNV_OFFSET, string(seed) + ":" + text);
}

function mistrimulti_dg_in_dungeon() {
    return ARI != undefined && GRID != undefined && CURRENT_LOCATION_ID == LocationId.Dungeon && DUNGEON_RUNNER != undefined;
}

// What the room key of the mines carries, so that players only see each other on the same floor of the same run
// (MistriMultiBoot.gml appends it to the key). A floor this game does not share is its own room.
function mistrimulti_dg_room_suffix() {
    if (CURRENT_LOCATION_ID != LocationId.Dungeon) return "";
    var r = __mistrimulti_runtime();
    var d = r[$ "dg"];
    if (is_struct(d) && d.f >= 0 && d.my_run != 0) return ":r" + string(d.my_run) + "f" + string(d.f);
    return ":p" + string(r.id);
}

// The nodes of this room that can have a state worth sharing (rocks, ore, breakables and chests, forageables, dig sites).
function mistrimulti_dg_syncable(node) {
    if (node.object_id == ObjectId.DigSiteDestroyed) return false;
    return mistrimulti_dg_category_ok(object_id_to_object_category(node.object_id));
}

function mistrimulti_dg_category_ok(cat) {
    return cat == ObjectCategory.Rock || cat == ObjectCategory.DigSite || cat == ObjectCategory.Breakable || cat == ObjectCategory.Crop;
}

// ---- engine adapters (the only places that enumerate instances) -------------------------------------------------------

function mistrimulti_dg_node_list() {
    var out = [];
    with (obj_node_renderer) {
        array_push(out, self.node);
    }
    return out;
}

function mistrimulti_dg_monster_list() {
    var out = [];
    with (par_monster) {
        array_push(out, id);
    }
    return out;
}

function mistrimulti_dg_monster_key(mon) {
    var p = mon.original_spawn_pos;
    return mistrimulti_dg_cell_key(round(p.x), round(p.y));
}

function mistrimulti_dg_monster_names(d) {
    if (d.mnames == undefined) {
        d.mnames = {};
        for (var i = 0; i < MonsterId.LEN; i++) d.mnames[$ monster_id_to_string(i)] = i;
    }
    return d.mnames;
}

function mistrimulti_dg_node_at(node) {
    var ni = GRID.try_node_index_for_cell(node.top_left_x, node.top_left_y);
    return ni != undefined && GRID.node_parent[ni] == node;
}

// ---- the run: seed, itinerary, floors ---------------------------------------------------------------------------------

function mistrimulti_dg_new_run(d) {
    d.run = irandom_range(1, 2147483000);
    d.seed = irandom_range(1, 2147483000);
    d.used = false;
    d.floors = {};
    d.snaps = [];
    d.at = array_create(8, undefined);
    d.dirty = true;
}

function mistrimulti_dg_run_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    if (r.mode != "join" || player != 0 || !is_struct(data)) return true;
    if (mistrimulti_dg_int(data[$ "run"], 1, 2147483647) && mistrimulti_dg_int(data[$ "seed"], 1, 2147483647)) {
        d.run = data.run;
        d.seed = data.seed;
    }
    return true;
}

// game.new_day: a day's mines are over; the next entry starts a new run.
function mistrimulti_dg_new_day(ctx) {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    if (r.mode == "host") mistrimulti_dg_new_run(d);
}

// The host sends the run to a game that joined, and forgets where a game that left was.
function mistrimulti_dg_peer(slot, joined, stream) {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    if (r.mode == "host") {
        if (slot > 0 && slot < 8) {
            d.at[slot] = undefined;
            for (var i = array_length(d.snaps) - 1; i >= 0; i--) if (d.snaps[i].slot == slot) array_delete(d.snaps, i, 1);
            if (joined && d.run != 0) mistrimulti_event_emit("dg_run", { run: d.run, seed: d.seed }, slot);
        }
    } else if (slot == 0 && joined) {
        // A new host: it knows nothing of this floor. Ask again; it adopts our run if nobody has used its own.
        mistrimulti_dg_rejoin(d, true);
        mistrimulti_dg_special_send(d, true);
    }
}

function mistrimulti_dg_gap(slot, base, expected) {
    if (slot == 0 && __mistrimulti_runtime().mode == "join") mistrimulti_dg_rejoin(mistrimulti_dg_state(), false);
}

function mistrimulti_dg_rejoin(d, restart) {
    if (d.f < 0 || d.st == "off") return;
    d.st = "build";
    d.build_at = -100;
    d.rejoin = restart;
    d.up = undefined;
    d.rx = undefined;
    d.pend = [];
}

// dungeon.runner_created: a new run of this game's runner. When the host's run is known, the itinerary becomes
// the one its seed produces, so everybody walks the same floors.
function mistrimulti_dg_runner_created(ctx) {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    mistrimulti_dg_leave(d);
    mistrimulti_dg_unsync(d);
    d.my_run = 0;
    if (!mistrimulti_dg_ok(d) || !mistrimulti_dg_online(r) || d.run == 0) return;
    var seen = undefined;
    try {
        var runner = ctx[$ "runner"];
        if (runner == undefined) return;
        var count = runner.itinerary.count();
        random_set_seed(mistrimulti_dg_hash(d.seed, "itinerary"));
        seen = ARI.has_seen_arena_level_today;
        ARI.has_seen_arena_level_today = false;
        var itinerary = create_dungeon_itinerary(count);
        ARI.has_seen_arena_level_today = seen;
        seen = undefined;
        randomize();
        runner.itinerary = itinerary;
        d.my_run = d.run;
        d.my_seed = d.seed;
    } catch (e) {
        if (seen != undefined) ARI.has_seen_arena_level_today = seen;
        randomize();
        mistrimulti_dg_fail(d, e);
    }
}

// dungeon.room_build_begin: seed the generator for this floor. Floors that are one player's own (side rooms,
// the arena) and the special rooms are not shared.
function mistrimulti_dg_build_begin(ctx) {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    mistrimulti_dg_leave(d);
    mistrimulti_dg_unsync(d);
    if (!mistrimulti_dg_ok(d) || d.my_run == 0 || !mistrimulti_dg_online(r)) return;
    try {
        var level = ctx[$ "level"];
        var flr = ctx[$ "floor"];
        if (!is_struct(level) || !mistrimulti_dg_int(flr, 0, 1000)) return;
        if (is_special_dungeon_room(room())) {
            mistrimulti_dg_special_enter(d, flr);
            return;
        }
        if (level[$ "is_side_room"] == true || (level[$ "impl"] == DungeonImpl.Enemy && !MISTRIMULTI_DG_ARENA)) return;
        d.f = flr;
        d.st = "build";
        d.key = mistrimulti_dg_floor_key(d.my_run, flr);
        d.build_at = -100;
        random_set_seed(mistrimulti_dg_hash(d.my_seed, "floor:" + string(flr)));
    } catch (e) {
        mistrimulti_dg_fail(d, e);
    }
}

// A seal room, the priestess's quarters or Seridia's chamber: static rooms with no monsters and no record. The host
// is only told that this player is still inside the run, so the run does not end under a player who stays there.
function mistrimulti_dg_special_enter(d, flr) {
    d.sp = flr;
    mistrimulti_dg_special_send(d, false);
}

function mistrimulti_dg_special_send(d, restart) {
    if (d.sp < 0 || d.my_run == 0) return;
    mistrimulti_event_request("dg_act", { o: "here", run: d.my_run, seed: d.my_seed, f: d.sp, sp: true, rj: restart });
}

// dungeon.floor_built: the game's own randomness resumes; the floor is asked about a tick later, when the
// runner has finished its room start (the ladder score it needs is known then).
function mistrimulti_dg_floor_built(ctx) {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    if (d.f < 0 || d.st != "build") return;
    randomize();
    d.build_at = r.ticks;
}

// Tell the host this game is no longer on a shared floor. False when the request could not be queued yet.
function mistrimulti_dg_leave(d) {
    if ((d.f < 0 && d.sp < 0) || d.my_run == 0) return true;
    return mistrimulti_event_request("dg_act", { o: "here", run: d.my_run, f: -1 }) != undefined;
}

// Forget this game's floor (leaving the mines, or a floor that is not shared).
function mistrimulti_dg_unsync(d) {
    d.f = -1;
    d.sp = -1;
    d.au = -1;
    d.fol = {};
    d.fseq = -1;
    d.out = [];
    d.st = "off";
    d.key = "";
    d.up = undefined;
    d.rx = undefined;
    d.pend = [];
    d.gq = [];
    d.lad = undefined;
    d.reconciling = false;
    d.mons = {};
    d.ikeys = {};
    d.hp = {};
    d.want = {};
    d.nodes = {};
    d.swing = {};
    d.rejoin = false;
    d.offline = 0;
    d.retry = 0;
}

// ---- tick ---------------------------------------------------------------------------------------------------------

// Called from the bridge tick while a world is loaded.
function mistrimulti_dungeon_tick() {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    if (!r.enabled || !mistrimulti_dg_ok(d)) return;
    try {
        if (r.mode == "host") mistrimulti_dg_host_tick(r, d);
        mistrimulti_dg_client_tick(r, d);
    } catch (e) {
        mistrimulti_dg_fail(d, e);
    }
}

function mistrimulti_dg_client_tick(r, d) {
    if (d.f < 0) {
        // in a special room only the run's presence is kept; leaving the mines ends it
        if (d.sp >= 0 && (DUNGEON_RUNNER == undefined || ARI == undefined) && mistrimulti_dg_leave(d)) mistrimulti_dg_unsync(d);
        return;
    }
    if (!mistrimulti_dg_in_dungeon()) {
        // left the mines (stairs, pass-out, death, a menu teleport): tell the host
        if (mistrimulti_dg_leave(d)) mistrimulti_dg_unsync(d);
        return;
    }
    // A guest that lost its host for good plays this floor on its own rules (monsters must be killable).
    if (!mistrimulti_dg_online(r)) {
        d.offline++;
        if (d.offline > MISTRIMULTI_DG_OFFLINE) mistrimulti_dg_unsync(d);
        return;
    }
    d.offline = 0;
    if (d.st == "build") {
        if (r.ticks - d.build_at >= 3 && r.ticks >= d.retry) mistrimulti_dg_ask(r, d);
    } else if (d.st == "ask" || d.st == "snap") {
        if (r.ticks - d.asked > MISTRIMULTI_DG_SNAP_WAIT) {
            d.st = "build";
            d.retry = r.ticks;
        }
    } else if (d.st == "wait") {
        if (r.ticks >= d.retry) d.st = "build";
    } else if (d.st == "found") {
        mistrimulti_dg_upload(d);
    } else if (d.st == "live") {
        mistrimulti_dg_report_gone(r, d);
        mistrimulti_dg_stream_tick(r, d);
    }
}

// The name of the GameMaker room this floor was built in. Two games whose itineraries disagree would build different
// rooms for the same floor number; they must not share a record.
function mistrimulti_dg_room_name() {
    var name = asset_to_string(room());
    return is_string(name) && string_length(name) <= 64 ? name : "";
}

function mistrimulti_dg_ask(r, d) {
    var rid = mistrimulti_event_request("dg_act", { o: "here", run: d.my_run, seed: d.my_seed, f: d.f, rj: d.rejoin,
        rm: mistrimulti_dg_room_name() });
    if (rid == undefined) return;
    d.st = "ask";
    d.rid = rid;
    d.asked = r.ticks;
    d.rx = undefined;
    d.pend = [];
}

// ---- host: the run, founding timeouts, snapshots ------------------------------------------------------------------------

function mistrimulti_dg_host_tick(r, d) {
    if (d.run == 0) mistrimulti_dg_new_run(d);
    var anyone = false;
    for (var i = 0; i < 8; i++) if (d.at[i] != undefined) anyone = true;
    if (anyone) d.empty_at = r.ticks;
    else if (d.used && r.ticks - d.empty_at > MISTRIMULTI_DG_EMPTY) mistrimulti_dg_new_run(d);
    if (d.dirty && mistrimulti_event_emit("dg_run", { run: d.run, seed: d.seed })) d.dirty = false;
    var keys = struct_get_names(d.floors);
    for (var k = 0; k < array_length(keys); k++) {
        var fl = d.floors[$ keys[k]];
        if (fl.st == "founding" && r.ticks - fl.since > MISTRIMULTI_DG_FOUNDING) struct_remove(d.floors, keys[k]);
    }
    var sent = 0;
    while (array_length(d.snaps) > 0 && sent < 2 && mistrimulti_event_backlog() < MISTRIMULTI_DG_BACKLOG) {
        var job = d.snaps[0];
        if (!mistrimulti_event_emit("dg_snap", job.slices[job.i], job.slot)) break;
        sent++;
        job.i++;
        if (job.i >= array_length(job.slices)) array_delete(d.snaps, 0, 1);
    }
}

// A copy of a record (a snapshot must not change while it is on its way).
function mistrimulti_dg_copy(rec) {
    var out = [];
    for (var i = 0; i < array_length(rec); i++) array_push(out, rec[i]);
    return out;
}

// A floor record cut into slices of at most MISTRIMULTI_DG_SLICE entries; the first carries the header.
function mistrimulti_dg_slices(d, fl) {
    var all = [];
    var names = struct_get_names(fl.nodes);
    for (var i = 0; i < array_length(names); i++) array_push(all, [0, mistrimulti_dg_copy(fl.nodes[$ names[i]])]);
    var mnames = struct_get_names(fl.mons);
    for (var j = 0; j < array_length(mnames); j++) array_push(all, [1, mistrimulti_dg_copy(fl.mons[$ mnames[j]])]);
    var count = max(1, ceil(array_length(all) / MISTRIMULTI_DG_SLICE));
    var out = [];
    for (var s = 0; s < count; s++) {
        var slice = { run: d.run, f: fl.f, i: s, n: count, nd: [], mo: [] };
        if (s == 0) {
            slice.h = { need: fl.need, rv: fl.rev };
            if (fl.lad != undefined) slice.h.lad = fl.lad;
        }
        for (var e = s * MISTRIMULTI_DG_SLICE; e < min(array_length(all), (s + 1) * MISTRIMULTI_DG_SLICE); e++) {
            if (all[e][0] == 0) array_push(slice.nd, all[e][1]);
            else array_push(slice.mo, all[e][1]);
        }
        array_push(out, slice);
    }
    return out;
}

// ---- record validation (every field comes from the network) ---------------------------------------------------------------

function mistrimulti_dg_node_rec(v) {
    if (!is_array(v) || array_length(v) != 5 || !is_string(v[0]) || string_length(v[0]) > 64) return false;
    if (!mistrimulti_dg_int(v[1], 0, 4000) || !mistrimulti_dg_int(v[2], 0, 4000) || !mistrimulti_dg_int(v[3], 0, 100000)) return false;
    if (!is_real(v[4]) || (v[4] != 0 && v[4] != 1)) return false;
    var oid = try_string_to_object_id(v[0]);
    return oid != undefined && oid != ObjectId.DigSiteDestroyed && mistrimulti_dg_category_ok(object_id_to_object_category(oid));
}

function mistrimulti_dg_mon_rec(d, v) {
    if (!is_array(v) || array_length(v) != 4 || !is_string(v[0]) || string_length(v[0]) > 64) return false;
    if (!mistrimulti_dg_int(v[1], 0, 40000) || !mistrimulti_dg_int(v[2], 0, 40000) || !mistrimulti_dg_int(v[3], 1, 100000)) return false;
    return struct_exists(mistrimulti_dg_monster_names(d), v[0]);
}

function mistrimulti_dg_header_ok(h) {
    if (!is_struct(h) || !mistrimulti_dg_int(h[$ "need"], 0, 1000000) || !mistrimulti_dg_int(h[$ "rv"], 0, 2147483647)) return false;
    var lad = h[$ "lad"];
    return lad == undefined || (is_array(lad) && array_length(lad) == 2 && mistrimulti_dg_int(lad[0], 0, 4000) && mistrimulti_dg_int(lad[1], 0, 4000));
}

// A slice from the network, checked as a whole. Returns whether every entry is valid.
function mistrimulti_dg_slice_ok(d, s) {
    if (!is_struct(s) || !is_array(s[$ "nd"]) || !is_array(s[$ "mo"])) return false;
    if (!mistrimulti_dg_int(s[$ "i"], 0, 100) || !mistrimulti_dg_int(s[$ "n"], 1, 101) || s.i >= s.n) return false;
    if (array_length(s.nd) + array_length(s.mo) > MISTRIMULTI_DG_SLICE) return false;
    if (s.i == 0 && !mistrimulti_dg_header_ok(s[$ "h"])) return false;
    for (var i = 0; i < array_length(s.nd); i++) if (!mistrimulti_dg_node_rec(s.nd[i])) return false;
    for (var j = 0; j < array_length(s.mo); j++) if (!mistrimulti_dg_mon_rec(d, s.mo[j])) return false;
    return true;
}

// Adds a (valid) slice's entries to the maps. Returns false when a limit is exceeded.
function mistrimulti_dg_slice_add(s, nodes, mons) {
    for (var i = 0; i < array_length(s.nd); i++) nodes[$ mistrimulti_dg_cell_key(s.nd[i][1], s.nd[i][2])] = s.nd[i];
    for (var j = 0; j < array_length(s.mo); j++) mons[$ mistrimulti_dg_cell_key(s.mo[j][1], s.mo[j][2])] = s.mo[j];
    return array_length(struct_get_names(nodes)) <= MISTRIMULTI_DG_NODES && array_length(struct_get_names(mons)) <= MISTRIMULTI_DG_MONSTERS;
}

// ---- host: requests ------------------------------------------------------------------------------------------------------

function mistrimulti_dg_request(from, data, ctx) {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    var refuse = { ok: false };
    if (r.mode != "host" || !is_struct(data) || !is_string(data[$ "o"]) || !mistrimulti_dg_ok(d) || !mistrimulti_dg_int(from, 0, 7)) return refuse;
    if (from > 0 && !(is_struct(r.peers[from]) && r.peers[from][$ "active"] == true)) return refuse;
    var res = refuse;
    try {
        var o = data.o;
        if (o == "here") res = mistrimulti_dg_op_here(r, d, from, data);
        else {
            var fl = mistrimulti_dg_floor_of(d, from, data);
            if (fl == undefined) res = { ok: false, o: o, gone: 1 };
            else if (o == "man") res = mistrimulti_dg_op_man(r, d, from, fl, data);
            else if (fl.st != "ready") res = { ok: false, o: o };
            else if (o == "hit") res = mistrimulti_dg_op_hit(d, from, fl, data);
            else if (o == "pick" || o == "dig" || o == "use") res = mistrimulti_dg_op_node(d, from, fl, data);
            else if (o == "gone") res = mistrimulti_dg_op_gone(d, from, fl, data);
            else if (o == "lad") res = mistrimulti_dg_op_lad(d, from, fl, data);
            // The host's own game applies what others did; its own requests are applied by the reply.
            if (from > 0 && res[$ "ok"] == true && o != "man") mistrimulti_dg_apply(d, res);
        }
    } catch (e) {
        mistrimulti_dg_fail(d, e);
        res = refuse;
    }
    return res;
}

// The floor record a request names, when the requester is there and the run is the current one.
function mistrimulti_dg_floor_of(d, from, data) {
    var at = d.at[from];
    if (at == undefined || !mistrimulti_dg_int(data[$ "run"], 1, 2147483647) || !mistrimulti_dg_int(data[$ "f"], 0, 1000)) return undefined;
    if (data.run != d.run || data.f != at.f || at.run != d.run) return undefined;
    return d.floors[$ mistrimulti_dg_floor_key(d.run, at.f)];
}

function mistrimulti_dg_op_here(r, d, from, data) {
    var f = data[$ "f"];
    if (is_real(f) && f == -1) {
        d.at[from] = undefined;
        return { ok: true, o: "here", st: "left" };
    }
    if (!mistrimulti_dg_int(f, 0, 1000) || !mistrimulti_dg_int(data[$ "run"], 1, 2147483647)) return { ok: false, o: "here", st: "off" };
    if (data.run != d.run) {
        // A restarted host that nobody has used yet adopts the run of a game that is already inside it.
        if (typeof(data[$ "rj"]) == "bool" && data.rj && !d.used && mistrimulti_dg_int(data[$ "seed"], 1, 2147483647)) {
            d.run = data.run;
            d.seed = data.seed;
            d.floors = {};
            d.dirty = true;
        } else {
            return { ok: false, o: "here", st: "stale", run: d.run, f: f };
        }
    }
    d.used = true;
    d.empty_at = r.ticks;
    if (typeof(data[$ "sp"]) == "bool" && data.sp) {
        // a special room: present in the run, no record
        d.at[from] = { run: d.run, f: f, sp: true };
        return { ok: true, o: "here", run: d.run, f: f, st: "special" };
    }
    var key = mistrimulti_dg_floor_key(d.run, f);
    var fl = d.floors[$ key];
    var room_name = is_string(data[$ "rm"]) && string_length(data.rm) <= 64 ? data.rm : "";
    if (fl != undefined && fl.rm != room_name) {
        d.at[from] = undefined;
        return { ok: false, o: "here", st: "off", f: f };
    }
    d.at[from] = { run: d.run, f: f };
    var res = { ok: true, o: "here", run: d.run, f: f };
    if (fl == undefined || (fl.st == "founding" && (fl.founder == from || r.ticks - fl.since > MISTRIMULTI_DG_FOUNDING))) {
        d.floors[$ key] = { f: f, rm: room_name, st: "founding", founder: from, since: r.ticks, next: 0, count: 0, nodes: {}, mons: {}, need: 0, lad: undefined, rev: 0 };
        res.st = "found";
    } else if (fl.st == "founding") {
        res.st = "wait";
    } else {
        res.st = "snap";
        res.v = fl.rev;
        if (from > 0) {
            var slices = mistrimulti_dg_slices(d, fl);
            for (var i = array_length(d.snaps) - 1; i >= 0; i--) if (d.snaps[i].slot == from) array_delete(d.snaps, i, 1);
            array_push(d.snaps, { slot: from, slices: slices, i: 0 });
            res.n = array_length(slices);
        }
    }
    return res;
}

// The founder's upload: slices in order, then the floor is ready.
function mistrimulti_dg_op_man(r, d, from, fl, data) {
    var res = { ok: false, o: "man", run: d.run, f: fl.f };
    if (fl.st != "founding" || fl.founder != from || !mistrimulti_dg_slice_ok(d, data) || data.i != fl.next) return res;
    if (data.i == 0) {
        fl.need = data.h.need;
        fl.lad = data.h[$ "lad"];
        fl.count = data.n;
    } else if (data.n != fl.count) {
        return res;
    }
    if (!mistrimulti_dg_slice_add(data, fl.nodes, fl.mons)) {
        struct_remove(d.floors, mistrimulti_dg_floor_key(d.run, fl.f));
        return res;
    }
    fl.next++;
    fl.since = r.ticks;
    res.ok = true;
    if (fl.next >= data.n) {
        fl.st = "ready";
        res.done = true;
    }
    return res;
}

function mistrimulti_dg_op_hit(d, from, fl, data) {
    var res = { ok: false, o: "hit", run: d.run, f: fl.f };
    if (!is_string(data[$ "m"]) || !mistrimulti_dg_int(data[$ "d"], 1, MISTRIMULTI_DG_DAMAGE)) return res;
    res.m = data.m;
    var mon = fl.mons[$ data.m];
    res.ok = true;
    if (mon == undefined) {
        // already dead: the requester's copy goes, with no drops
        res.dead = 1;
        res.k = -1;
        res.v = fl.rev;
        return res;
    }
    mon[3] = mon[3] - data.d;
    fl.rev++;
    res.v = fl.rev;
    if (mon[3] <= 0) {
        struct_remove(fl.mons, data.m);
        res.dead = 1;
        res.k = from;
    } else {
        res.hp = mon[3];
    }
    return res;
}

// pick, dig and use: the damage rules of pick_node, shovel_node and interact, applied to the record only.
function mistrimulti_dg_op_node(d, from, fl, data) {
    var o = data.o;
    var res = { ok: false, o: o, run: d.run, f: fl.f };
    if (!mistrimulti_dg_int(data[$ "x"], 0, 4000) || !mistrimulti_dg_int(data[$ "y"], 0, 4000)) return res;
    res.x = data.x;
    res.y = data.y;
    var key = mistrimulti_dg_cell_key(data.x, data.y);
    var rec = fl.nodes[$ key];
    if (rec == undefined) {
        res.g = 1;
        res.v = fl.rev;
        return res;
    }
    var oid = try_string_to_object_id(rec[0]);
    var cat = object_id_to_object_category(oid);
    res.hp = rec[3];
    res.v = fl.rev;
    if (o == "use") {
        if (cat == ObjectCategory.Crop) {
            struct_remove(fl.nodes, key);
            res.g = 1;
        } else if (cat == ObjectCategory.Breakable && NODE_PROTOTYPES[oid].chest != undefined) {
            res.op = 1;
            if (rec[4] == 1) return res;
            rec[4] = 1;
        } else {
            return res;
        }
    } else {
        var itemid = is_string(data[$ "i"]) ? try_string_to_item_id(data.i) : undefined;
        var proto = itemid == undefined ? undefined : ITEM_PROTOTYPES[itemid];
        var wanted = o == "pick" ? ToolType.PickAxe : ToolType.Shovel;
        if (proto == undefined || proto.tool_type != wanted) return res;
        res.i = data.i;
        res.c = mistrimulti_dg_int(data[$ "c"], 0, 1) && data.c == 1 ? 1 : 0;
        var modifier = res.c == 1 ? -1 : 0;
        if (o == "pick" && cat == ObjectCategory.Rock) {
            if (proto.quality != QualityId.LEN - 1 && proto.quality + modifier < NODE_PROTOTYPES[oid].minimum_quality) return res;
            res.p = rec[3];
            rec[3] = rec[3] - min(proto.damage + modifier, rec[3]);
            res.hp = rec[3];
            if (rec[3] <= 0) {
                struct_remove(fl.nodes, key);
                res.g = 1;
            }
        } else if (oid == ObjectId.DigSite) {
            struct_remove(fl.nodes, key);
            res.g = 1;
        } else {
            return res;
        }
    }
    fl.rev++;
    res.v = fl.rev;
    res.ok = true;
    res.by = from;
    return res;
}

function mistrimulti_dg_op_gone(d, from, fl, data) {
    var res = { ok: true, o: "gone", run: d.run, f: fl.f, g: 1, by: from };
    if (!mistrimulti_dg_int(data[$ "x"], 0, 4000) || !mistrimulti_dg_int(data[$ "y"], 0, 4000)) return { ok: false, o: "gone" };
    res.x = data.x;
    res.y = data.y;
    var key = mistrimulti_dg_cell_key(data.x, data.y);
    if (fl.nodes[$ key] != undefined) {
        struct_remove(fl.nodes, key);
        fl.rev++;
    }
    res.v = fl.rev;
    return res;
}

function mistrimulti_dg_op_lad(d, from, fl, data) {
    var res = { ok: false, o: "lad", run: d.run, f: fl.f };
    if (!mistrimulti_dg_int(data[$ "x"], 0, 4000) || !mistrimulti_dg_int(data[$ "y"], 0, 4000)) return res;
    res.ok = true;
    if (fl.lad == undefined) {
        fl.lad = [data.x, data.y];
        fl.rev++;
    }
    res.x = fl.lad[0];
    res.y = fl.lad[1];
    res.v = fl.rev;
    return res;
}

// ---- guests: results and replies --------------------------------------------------------------------------------------------

function mistrimulti_dg_mutation(o) {
    return o == "hit" || o == "pick" || o == "dig" || o == "use" || o == "gone" || o == "lad";
}

// A result for everybody (the requester gets its reply as well). Mutations of this game's floor are applied;
// while the floor record has not arrived yet they are kept, to be replayed after it.
function mistrimulti_dg_result(from, res, ctx) {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    if (r.mode != "join" || from != 0 || !is_struct(res) || ctx.mine || !mistrimulti_dg_ok(d)) return true;
    if (!mistrimulti_dg_mutation(res[$ "o"]) || res[$ "ok"] != true || d.f < 0 || res[$ "f"] != d.f || res[$ "run"] != d.my_run) return true;
    try {
        if (d.st == "ask" || d.st == "snap") {
            if (array_length(d.pend) < MISTRIMULTI_DG_PENDING) array_push(d.pend, res);
        } else if (d.st == "live") {
            mistrimulti_dg_apply(d, res);
        }
    } catch (e) {
        mistrimulti_dg_fail(d, e);
    }
    return true;
}

// The requester's reply: its own part of the action (the engine's own pick, shovel or interaction), and the
// answers to "here" and the upload. lost/expired (res undefined) means the host restarted or the answer is gone.
function mistrimulti_dg_reply(from, res, ctx) {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    if (!mistrimulti_dg_ok(d)) return;
    try {
        if (!is_struct(res)) {
            d.lost++;
            if (d.f >= 0 && (d.st == "ask" || d.st == "found")) {
                d.st = "build";
                d.retry = r.ticks + MISTRIMULTI_DG_RETRY;
            } else if (d.f >= 0 && d.st == "live") {
                mistrimulti_dg_rejoin(d, false);
            }
            return;
        }
        var o = res[$ "o"];
        if (o == "here") mistrimulti_dg_reply_here(r, d, res);
        else if (o == "man") mistrimulti_dg_reply_man(r, d, res);
        else if (res[$ "run"] == d.my_run && res[$ "f"] == d.f && d.st == "live") {
            if (o == "pick" || o == "dig" || o == "use") mistrimulti_dg_perform(d, res);
            else if (mistrimulti_dg_mutation(o) && res[$ "ok"] == true) mistrimulti_dg_apply(d, res);
        }
        if (res[$ "gone"] == 1 && d.st == "live") {
            // the host knows nothing of this floor (it restarted or rotated): start over
            mistrimulti_dg_rejoin(d, false);
        }
    } catch (e) {
        mistrimulti_dg_fail(d, e);
    }
}

function mistrimulti_dg_reply_here(r, d, res) {
    if (d.st != "ask" || res[$ "f"] != d.f) return;
    var st = res[$ "st"];
    if (st == "found") {
        d.rejoin = false;
        var cap = mistrimulti_dg_capture(d);
        if (cap == undefined) {
            mistrimulti_dg_unsync(d);
        } else if (r.mode == "host") {
            // the host's own record needs no upload
            var fl = d.floors[$ mistrimulti_dg_floor_key(d.run, d.f)];
            if (fl == undefined || fl.st != "founding") {
                d.st = "build";
                return;
            }
            fl.need = cap.need;
            fl.lad = cap.lad;
            for (var i = 0; i < array_length(cap.nd); i++) fl.nodes[$ mistrimulti_dg_cell_key(cap.nd[i][1], cap.nd[i][2])] = cap.nd[i];
            for (var j = 0; j < array_length(cap.mo); j++) fl.mons[$ mistrimulti_dg_cell_key(cap.mo[j][1], cap.mo[j][2])] = cap.mo[j];
            fl.st = "ready";
            d.lad = cap.lad;
            d.st = "live";
        } else {
            d.up = { slices: cap.slices, sent: 0, acked: 0 };
            d.lad = cap.lad;
            d.st = "found";
        }
    } else if (st == "snap") {
        d.rejoin = false;
        if (r.mode == "host") {
            var own = d.floors[$ mistrimulti_dg_floor_key(d.run, d.f)];
            if (own != undefined) mistrimulti_dg_enter_live(d, own.nodes, own.mons, { need: own.need, lad: own.lad, rv: own.rev });
        } else {
            d.st = "snap";
            d.asked = r.ticks;
            d.rx = { next: 0, nodes: {}, mons: {}, h: undefined };
        }
    } else if (st == "wait") {
        d.st = "wait";
        d.retry = r.ticks + MISTRIMULTI_DG_RETRY;
    } else if (st == "stale" || st == "off") {
        mistrimulti_dg_unsync(d);
    } else {
        d.st = "build";
        d.retry = r.ticks + MISTRIMULTI_DG_RETRY;
    }
}

function mistrimulti_dg_reply_man(r, d, res) {
    if (d.st != "found" || res[$ "f"] != d.f) return;
    if (res[$ "ok"] != true) {
        d.st = "build";
        d.retry = r.ticks + MISTRIMULTI_DG_RETRY;
        d.up = undefined;
        return;
    }
    if (res[$ "done"] == true) {
        d.up = undefined;
        d.st = "live";
    }
}

// The founder's upload goes out a few slices per tick, in order.
function mistrimulti_dg_upload(d) {
    var up = d.up;
    if (up == undefined) {
        d.st = "build";
        return;
    }
    var sent = 0;
    while (up.sent < array_length(up.slices) && sent < 4 && mistrimulti_event_backlog() < MISTRIMULTI_DG_BACKLOG) {
        var slice = up.slices[up.sent];
        slice.o = "man";
        slice.run = d.my_run;
        slice.f = d.f;
        if (mistrimulti_event_request("dg_act", slice) == undefined) break;
        up.sent++;
        sent++;
    }
}

// dg_snap (host to this game): a slice of the floor record.
function mistrimulti_dg_snap_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    if (r.mode != "join" || player != 0 || !mistrimulti_dg_ok(d) || d.st != "snap" || d.rx == undefined || !is_struct(data)) return true;
    try {
        if (!mistrimulti_dg_slice_ok(d, data) || !mistrimulti_dg_int(data[$ "run"], 1, 2147483647) || !mistrimulti_dg_int(data[$ "f"], 0, 1000)) return true;
        if (data.run != d.my_run || data.f != d.f || data.i != d.rx.next) return true;
        if (data.i == 0) d.rx.h = data.h;
        if (!mistrimulti_dg_slice_add(data, d.rx.nodes, d.rx.mons)) {
            mistrimulti_dg_unsync(d);
            return true;
        }
        d.rx.next++;
        if (d.rx.next >= data.n) {
            var rx = d.rx;
            d.rx = undefined;
            mistrimulti_dg_enter_live(d, rx.nodes, rx.mons, rx.h);
        }
    } catch (e) {
        mistrimulti_dg_fail(d, e);
    }
    return true;
}

// ---- capturing and reconciling a floor -------------------------------------------------------------------------------------------

// What this game's room holds now: node and monster records, the header, and (for a guest) the upload slices.
function mistrimulti_dg_capture(d) {
    var nd = [];
    var mo = [];
    d.nodes = {};
    d.mons = {};
    d.ikeys = {};
    d.hp = {};
    d.want = {};
    var nodes = mistrimulti_dg_node_list();
    for (var i = 0; i < array_length(nodes); i++) {
        var n = nodes[i];
        if (!mistrimulti_dg_syncable(n)) continue;
        var key = mistrimulti_dg_cell_key(n.top_left_x, n.top_left_y);
        if (struct_exists(d.nodes, key)) continue;
        d.nodes[$ key] = n;
        array_push(nd, [object_id_to_string(n.object_id), n.top_left_x, n.top_left_y, round(n[$ "hitpoints"] ?? 0), n[$ "is_open"] == true ? 1 : 0]);
    }
    var mons = mistrimulti_dg_monster_list();
    for (var j = 0; j < array_length(mons); j++) {
        var m = mons[j];
        if (m.hit_points <= 0) continue;
        var mkey = mistrimulti_dg_monster_key(m);
        if (struct_exists(d.mons, mkey)) continue;
        d.mons[$ mkey] = m;
        d.ikeys[$ string(m)] = mkey;
        d.hp[$ mkey] = m.hit_points;
        array_push(mo, [monster_id_to_string(m.monster_id), round(m.original_spawn_pos.x), round(m.original_spawn_pos.y), max(1, ceil(m.hit_points))]);
    }
    if (array_length(nd) > MISTRIMULTI_DG_NODES || array_length(mo) > MISTRIMULTI_DG_MONSTERS) return undefined;
    var lad = undefined;
    if (instance_exists(obj_dungeon_ladder_down)) lad = [obj_dungeon_ladder_down.x div 8, obj_dungeon_ladder_down.y div 8];
    var cap = { nd: nd, mo: mo, need: max(0, round(DUNGEON_RUNNER.ladder_score_needed)), lad: lad, slices: [] };
    var fake = { f: d.f, nodes: {}, mons: {}, need: cap.need, lad: lad, rev: 0 };
    for (var a = 0; a < array_length(nd); a++) fake.nodes[$ mistrimulti_dg_cell_key(nd[a][1], nd[a][2])] = nd[a];
    for (var b = 0; b < array_length(mo); b++) fake.mons[$ mistrimulti_dg_cell_key(mo[b][1], mo[b][2])] = mo[b];
    cap.slices = mistrimulti_dg_slices({ run: d.my_run }, fake);
    return cap;
}

// The record arrived (or is the host's own): bring this room to it, then replay what happened meanwhile.
function mistrimulti_dg_enter_live(d, nodes, mons, header) {
    d.reconciling = true;
    d.bypass++;
    try {
        mistrimulti_dg_reconcile(d, nodes, mons, header);
    } catch (e) {
        mistrimulti_dg_fail(d, e);
    }
    d.bypass--;
    d.reconciling = false;
    d.st = "live";
    // the natural spawn was held back while the room was brought to the record; if the score is met, it happens now
    if (d.lad == undefined && DUNGEON_RUNNER != undefined && instance_exists(obj_ari)) DUNGEON_RUNNER.check_ladder_score(obj_ari.x div 8, obj_ari.y div 8);
    var pend = d.pend;
    d.pend = [];
    for (var i = 0; i < array_length(pend); i++) {
        if (is_real(pend[i][$ "v"]) && pend[i].v > header.rv) mistrimulti_dg_apply(d, pend[i]);
    }
}

function mistrimulti_dg_reconcile(d, nodes, mons, header) {
    var runner = DUNGEON_RUNNER;
    if (header.need > 0) runner.ladder_score_needed = header.need;
    d.lad = header[$ "lad"];
    // nodes: what the record does not hold goes (that also scores towards the ladder, as in the game), what it
    // holds and this room lacks is built, and shared state is copied
    d.nodes = {};
    var local = mistrimulti_dg_node_list();
    for (var i = 0; i < array_length(local); i++) {
        var n = local[i];
        if (!mistrimulti_dg_syncable(n)) continue;
        var key = mistrimulti_dg_cell_key(n.top_left_x, n.top_left_y);
        var rec = nodes[$ key];
        if (struct_exists(d.nodes, key)) continue;
        if (rec == undefined || rec[0] != object_id_to_string(n.object_id)) {
            if (mistrimulti_dg_node_at(n)) erase_object_node_by_parent(GRID, n);
        } else {
            d.nodes[$ key] = n;
            mistrimulti_dg_node_state(n, rec[3], rec[4]);
        }
    }
    var keys = struct_get_names(nodes);
    for (var k = 0; k < array_length(keys); k++) {
        if (struct_exists(d.nodes, keys[k])) continue;
        var want = nodes[$ keys[k]];
        var oid = try_string_to_object_id(want[0]);
        var built = undefined;
        if (oid != undefined) {
            if (object_id_to_object_category(oid) == ObjectCategory.Crop) built = GRID.write_node(want[1], want[2], oid, CropFlag.FORAGEABLE | CropFlag.SPAWN_GROWN);
            else built = GRID.write_node(want[1], want[2], oid);
        }
        if (built != undefined) {
            d.nodes[$ keys[k]] = built;
            mistrimulti_dg_node_state(built, want[3], want[4]);
        }
    }
    // monsters
    d.mons = {};
    d.ikeys = {};
    d.hp = {};
    d.want = {};
    var names = mistrimulti_dg_monster_names(d);
    var here = mistrimulti_dg_monster_list();
    for (var a = 0; a < array_length(here); a++) {
        var m = here[a];
        var mkey = mistrimulti_dg_monster_key(m);
        var mrec = mons[$ mkey];
        if (mrec == undefined || struct_exists(d.mons, mkey) || names[$ mrec[0]] != m.monster_id) {
            if (instance_exists(m)) mistrimulti_dg_silent_kill(d, m);
        } else {
            mistrimulti_dg_track(d, mkey, m, mrec[3]);
        }
    }
    var mk = struct_get_names(mons);
    for (var b = 0; b < array_length(mk); b++) {
        if (struct_exists(d.mons, mk[b])) continue;
        var mr = mons[$ mk[b]];
        var spawned = spawn_monster(mr[1], mr[2], names[$ mr[0]]);
        if (spawned != undefined) mistrimulti_dg_track(d, mk[b], spawned, mr[3]);
    }
    // the ladder: the record's position wins over a natural spawn
    if (d.lad != undefined && !instance_exists(obj_dungeon_ladder_down)) {
        d.spawning = true;
        runner.spawn_ladder(d.lad[0], d.lad[1]);
        d.spawning = false;
    }
}

function mistrimulti_dg_track(d, key, mon, hp) {
    d.mons[$ key] = mon;
    d.ikeys[$ string(mon)] = key;
    mon.hit_points = max(1, hp);
    d.hp[$ key] = mon.hit_points;
}

// Shared state of a node: rocks have hitpoints, chests are open or not.
function mistrimulti_dg_node_state(n, hp, open) {
    if (n[$ "hitpoints"] != undefined && hp > 0) n.hitpoints = hp;
    if (open == 1) mistrimulti_dg_open_chest(n);
}

function mistrimulti_dg_open_chest(n) {
    if (n[$ "is_open"] == true || n.prototype[$ "chest"] == undefined) return;
    n.is_open = true;
    var rd = n[$ "renderer"];
    if (rd != undefined && instance_exists(rd)) {
        rd.set_sprite(n.prototype.chest.open_sprite);
        rd.image_speed = 0;
    }
}

// A monster that another game killed (or that the record does not hold): gone without drops, xp or kill count,
// but its share of the floor's ladder score is counted.
function mistrimulti_dg_silent_kill(d, mon) {
    var cx = mon.x div 8;
    var cy = mon.y div 8;
    var px = mon.x;
    var py = mon.y;
    var dp = mon.depth;
    mon.skip_destroy_logic = true;
    instance_destroy(mon);
    create_animation_effect(px, py, dp - 1, spr_fx_small_monster_death_poof);
    DUNGEON_RUNNER.on_monster_destroy(cx, cy);
}

// ---- applying a result to this game's room ----------------------------------------------------------------------------------------

function mistrimulti_dg_apply(d, res) {
    if (d.f < 0 || d.st != "live" || res[$ "f"] != d.f || res[$ "run"] != d.my_run) return;
    var o = res[$ "o"];
    if (o == "hit") mistrimulti_dg_apply_hit(d, res);
    else if (o == "pick" || o == "dig" || o == "use" || o == "gone") mistrimulti_dg_apply_node(d, res);
    else if (o == "lad") mistrimulti_dg_apply_ladder(d, res);
}

function mistrimulti_dg_apply_hit(d, res) {
    var r = __mistrimulti_runtime();
    var key = res[$ "m"];
    if (!is_string(key)) return;
    var mon = d.mons[$ key];
    if (mon == undefined) return;
    if (res[$ "dead"] == 1) {
        struct_remove(d.mons, key);
        struct_remove(d.ikeys, string(mon));
        struct_remove(d.hp, key);
        if (!instance_exists(mon)) return;
        // the killer's copy dies the game's own way (drops, essence and xp are its own); the others just disappear
        if (res[$ "k"] == r.id) mon.hit_points = 0;
        else mistrimulti_dg_silent_kill(d, mon);
    } else if (is_real(res[$ "hp"]) && instance_exists(mon)) {
        mon.hit_points = max(1, res.hp);
        d.hp[$ key] = mon.hit_points;
    }
}

function mistrimulti_dg_apply_node(d, res) {
    if (!mistrimulti_dg_int(res[$ "x"], 0, 4000) || !mistrimulti_dg_int(res[$ "y"], 0, 4000)) return;
    var key = mistrimulti_dg_cell_key(res.x, res.y);
    var n = d.nodes[$ key];
    if (n == undefined) return;
    if (res[$ "g"] == 1) {
        struct_remove(d.nodes, key);
        if (mistrimulti_dg_node_at(n)) {
            var was = n.object_id;
            var tx = n.top_left_x;
            var ty = n.top_left_y;
            erase_object_node_by_parent(GRID, n);
            if (was == ObjectId.DigSite) GRID.write_node(tx, ty, ObjectId.DigSiteDestroyed);
        }
    } else {
        if (is_real(res[$ "hp"]) && n[$ "hitpoints"] != undefined && res.hp > 0) n.hitpoints = res.hp;
        if (res[$ "op"] == 1) mistrimulti_dg_open_chest(n);
    }
}

function mistrimulti_dg_apply_ladder(d, res) {
    if (!mistrimulti_dg_int(res[$ "x"], 0, 4000) || !mistrimulti_dg_int(res[$ "y"], 0, 4000)) return;
    d.lad = [res.x, res.y];
    if (!instance_exists(obj_dungeon_ladder_down) && DUNGEON_RUNNER != undefined) {
        d.spawning = true;
        DUNGEON_RUNNER.spawn_ladder(res.x, res.y);
        d.spawning = false;
    }
}

// dungeon.ladder_spawn: one ladder per floor, where the first game that earned it put it.
function mistrimulti_dg_ladder_guard(ctx) {
    var d = mistrimulti_dg_state();
    if (d.f < 0 || d.spawning) return undefined;
    if (d.reconciling) return false;
    if (d.lad != undefined) return false;
    if (d.st == "live") {
        d.lad = [ctx.x, ctx.y];
        mistrimulti_event_request("dg_act", { o: "lad", run: d.my_run, f: d.f, x: ctx.x, y: ctx.y });
    }
    return undefined;
}

// ---- monsters: reporting hits, keeping every copy alive until the host says it died ----------------------------------------------

function mistrimulti_dg_report(d, key, amount) {
    d.hits++;
    if (mistrimulti_event_request("dg_act", { o: "hit", run: d.my_run, f: d.f, m: key, d: min(ceil(amount), MISTRIMULTI_DG_DAMAGE) }) == undefined) d.lost++;
}

// combat.damage: a hit on one of the floor's monsters is noted at its full size, and at most hp - 1 of it can be
// dealt here, so this game's copy never dies by itself. Whether the species takes it (a shell, a phase in which it
// cannot be hurt) is not known yet; monster.step_end below reports what it actually took.
function mistrimulti_dg_damage(tarball, receiver) {
    var d = mistrimulti_dg_state();
    if (d.f < 0 || d.st != "live" || !mistrimulti_dg_ok(d)) return undefined;
    try {
        var mon = receiver.parent_id;
        if (mon == undefined) return undefined;
        var key = d.ikeys[$ string(mon)];
        if (key == undefined || !instance_exists(mon)) return undefined;
        var amount = tarball.damage;
        if (!is_real(amount) || amount <= 0) return undefined;
        d.want[$ key] = (d.want[$ key] ?? 0) + amount;
        tarball.damage = max(0, min(amount, mon.hit_points - 1));
    } catch (e) {
        mistrimulti_dg_fail(d, e);
    }
    return undefined;
}

// monster.step_end: health below what this game expects is damage the copy took (a tarball, venom). It is reported
// at the size of the hit that was noted, if any, and the copy is kept alive. A hit the species ignored costs nothing.
function mistrimulti_dg_monster_step(mon) {
    var r = __mistrimulti_runtime();
    var d = r[$ "dg"];
    if (!is_struct(d) || d.f < 0 || d.st != "live") return;
    try {
        var key = d.ikeys[$ string(mon)];
        if (key == undefined) return;
        if (d.au >= 0 && d.au != r.id) mistrimulti_dg_follow(r, d, mon, key);
        var wanted = d.want[$ key] ?? 0;
        if (wanted != 0) d.want[$ key] = 0;
        var expected = d.hp[$ key];
        var now = mon.hit_points;
        if (now >= expected) return;
        mistrimulti_dg_report(d, key, max(expected - now, wanted));
        if (now < 1) mon.hit_points = 1;
        d.hp[$ key] = mon.hit_points;
    } catch (e) {
        mistrimulti_dg_fail(d, e);
    }
}

// ---- monsters: one game per floor decides where they are -------------------------------------------------------------------------
//
// The authority is derived by every game from the same facts, so nothing has to be agreed on: the lowest slot among the games
// that are live on this floor (each says so with dm.k in its peer frame), which is the host whenever the host is there. The
// authority's game runs the monsters' AI as ever (they chase its player) and puts their state in its peer frame at 10 Hz. A
// peer frame is a snapshot where the newest wins, which is what positions need (a lost frame is replaced 100 ms later); the
// reliable event layer would resend stale positions. Every other game keeps its own copies, with their own AI running, but
// puts each copy where the authority has it (monster.step_end, every frame, easing between two samples). A copy that is
// aggro on this game's own player shows its own animation, so that what hurts this player is what this player sees.

// The slot that streams this floor, or -1. A peer counts while its counter keeps changing (a game that froze is dropped).
function mistrimulti_dg_elect(r, d) {
    var best = d.st == "live" ? r.id : -1;
    for (var i = 0; i < 8; i++) {
        if (i == r.id || (r.mask & (1 << i)) == 0 || (best >= 0 && i > best)) continue;
        var p = r.peers[i];
        var dm = is_struct(p) ? p[$ "dm"] : undefined;
        if (!is_struct(dm) || p[$ "active"] != true || dm[$ "k"] != d.key || !is_real(dm[$ "t"])) continue;
        var seen = d.seen[i];
        if (seen == undefined || seen.t != dm.t || seen.k != d.key) {
            seen = { t: dm.t, k: d.key, at: r.ticks };
            d.seen[i] = seen;
        }
        if (r.ticks - seen.at > MISTRIMULTI_DG_SILENT) continue;
        best = i;
    }
    return best;
}

function mistrimulti_dg_stream_tick(r, d) {
    var au = mistrimulti_dg_elect(r, d);
    if (au != d.au) {
        d.au = au;
        d.fol = {};
        d.fseq = -1;
        d.out = [];
        mistrimulti_trace("dgauth", "floor " + d.key + " authority " + string(au) + " (me " + string(r.id) + ")", 40);
    }
    if (au == r.id) {
        if (r.ticks - d.out_at >= MISTRIMULTI_DG_STREAM_TICKS) mistrimulti_dg_stream_build(r, d);
    } else {
        // a counter that moves (once a second) shows the other games that this one is still here
        if (r.ticks - d.out_at >= 60) {
            d.out_at = r.ticks;
            d.cnt++;
        }
        if (au >= 0) mistrimulti_dg_follow_read(r, d, au);
    }
}

// peer frame: dm = { t: counter, k: floor key, a: 1 and m: monsters when this game is the authority }
function mistrimulti_dungeon_frame(frame) {
    var r = __mistrimulti_runtime();
    var d = r[$ "dg"];
    if (!is_struct(d) || d.f < 0 || d.st != "live" || d.key == "" || !mistrimulti_dg_ok(d)) return;
    var dm = { t: d.cnt, k: d.key };
    if (d.au == r.id) {
        dm.a = 1;
        dm.m = d.out;
    }
    frame.dm = dm;
}

// [spawn x, spawn y, x, y, direction, state, frame, hidden, z] of the monsters the host's record holds, a slice per frame
function mistrimulti_dg_stream_build(r, d) {
    d.out_at = r.ticks;
    d.cnt++;
    var keys = struct_get_names(d.mons);
    var n = array_length(keys);
    var take = min(n, MISTRIMULTI_DG_STREAM);
    if (d.cur >= n) d.cur = 0;
    var out = [];
    for (var i = 0; i < take; i++) {
        var mon = d.mons[$ keys[(d.cur + i) mod n]];
        if (!instance_exists(mon) || mon.hit_points <= 0) continue;
        var p = mon.original_spawn_pos;
        var dir = ((round(mon.dir) mod 360) + 360) mod 360;
        var st = mon[$ "fsm"] != undefined ? mon.fsm.current_state_id() : 0;
        array_push(out, [round(p.x), round(p.y), clamp(round(mon.x), 0, 40000), clamp(round(mon.y), 0, 40000), dir,
            is_real(st) ? clamp(floor(st), 0, 63) : 0, clamp(floor(mon.image_index), 0, 1000),
            mon.sprite_index == spr_nothing ? 1 : 0, clamp(round(mon[$ "z"] ?? 0), -200, 200)]);
    }
    d.cur = n > 0 ? (d.cur + take) mod n : 0;
    d.out = out;
}

function mistrimulti_dg_stream_ok(e) {
    if (!is_array(e) || array_length(e) != 9) return false;
    return mistrimulti_dg_int(e[0], 0, 40000) && mistrimulti_dg_int(e[1], 0, 40000) && mistrimulti_dg_int(e[2], 0, 40000)
        && mistrimulti_dg_int(e[3], 0, 40000) && mistrimulti_dg_int(e[4], 0, 359) && mistrimulti_dg_int(e[5], 0, 63)
        && mistrimulti_dg_int(e[6], 0, 1000) && mistrimulti_dg_int(e[7], 0, 1) && mistrimulti_dg_int(e[8], -200, 200);
}

// The authority's newest frame (if not seen yet): every valid entry that names one of this game's copies becomes a target.
function mistrimulti_dg_follow_read(r, d, au) {
    var p = r.peers[au];
    var dm = is_struct(p) ? p[$ "dm"] : undefined;
    if (!is_struct(dm) || dm[$ "a"] != 1 || dm[$ "k"] != d.key || !is_array(dm[$ "m"]) || !is_real(dm[$ "t"])) return;
    if (dm.t == d.fseq || array_length(dm.m) > MISTRIMULTI_DG_STREAM) return;
    d.fseq = dm.t;
    for (var i = 0; i < array_length(dm.m); i++) {
        if (mistrimulti_dg_stream_ok(dm.m[i])) mistrimulti_dg_follow_set(r, d, dm.m[i]);
    }
}

function mistrimulti_dg_follow_set(r, d, e) {
    var key = mistrimulti_dg_cell_key(e[0], e[1]);
    var mon = d.mons[$ key];
    if (mon == undefined || !instance_exists(mon)) return;
    var f = d.fol[$ key];
    if (f == undefined) f = { at: r.ticks - MISTRIMULTI_DG_STREAM_TICKS, ss: false };
    // ease from where the copy is now to the new place over about the time between two samples
    f.fx = mon.x;
    f.fy = mon.y;
    f.dur = clamp(r.ticks - f.at, 3, 12);
    f.tx = e[2];
    f.ty = e[3];
    if (abs(f.tx - f.fx) + abs(f.ty - f.fy) > MISTRIMULTI_DG_SNAP_DIST) {
        f.fx = f.tx;
        f.fy = f.ty;
    }
    f.t0 = r.ticks;
    f.at = r.ticks;
    f.dir = e[4];
    f.s = e[5];
    f.i = e[6];
    f.h = e[7];
    f.z = e[8];
    f.fix = true;
    d.fol[$ key] = f;
}

// monster.step_end on a game that is not the authority: the copy goes where the authority has it, and (unless it is aggro on
// this game's player, whose own animation tells when it will strike) looks like the authority's copy. A copy not heard of for
// two seconds (or the sprite of a state its own config lacks) goes back to the game's own rules.
function mistrimulti_dg_follow(r, d, mon, key) {
    var f = d.fol[$ key];
    if (f == undefined || r.ticks - f.at > MISTRIMULTI_DG_STALE) return;
    var a = clamp((r.ticks - f.t0) / f.dur, 0, 1);
    mon.x = f.fx + (f.tx - f.fx) * a;
    mon.y = f.fy + (f.ty - f.fy) * a;
    if (mon.aggro || f.ss) return;
    try {
        mon.dir = f.dir;
        if (f.h == 1) {
            mon.sprite_index = spr_nothing;
        } else {
            var sprite = mon.config.sprite_catalogue[f.s][mon.get_cardinal()];
            if (mon.sprite_index != sprite) {
                mon.set_state_sprite(false, f.s);
                f.fix = true;
            }
        }
        if (f.fix) {
            mon.image_index = f.i;
            f.fix = false;
        }
        mon.image_xscale = mon.calculate_flipper();
        mon.draw_y_offset += f.z - (mon[$ "z"] ?? 0);
    } catch (e) {
        f.ss = true;
        mistrimulti_trace("dgsprite", "a monster's state " + string(f.s) + " has no sprite here: " + string(e), 10);
    }
}

// ---- nodes: claims for rocks, dig sites, chests and forageables; reports for anything else that disappears -------------------------

function mistrimulti_dg_gate(d) {
    var r = __mistrimulti_runtime();
    return r.enabled && mistrimulti_dg_ok(d) && d.f >= 0 && d.st == "live" && d.bypass == 0;
}

// Which request a tool use on this cell becomes, and the node's anchor: [kind, x, y], or undefined.
function mistrimulti_dg_swing(d, tool, x, y) {
    if (tool == ToolType.PickAxe) {
        for (var xx = 0; xx < 2; xx++) {
            for (var yy = 0; yy < 2; yy++) {
                var ci = GRID.try_node_index_for_cell(x + xx, y + yy);
                if (ci == undefined || GRID.node_object_id[ci] == undefined) continue;
                var pn = GRID.node_parent[ci];
                var cat = object_id_to_object_category(pn.object_id);
                if (d.nodes[$ mistrimulti_dg_cell_key(pn.top_left_x, pn.top_left_y)] == pn && (cat == ObjectCategory.Rock || pn.object_id == ObjectId.DigSite))
                    return ["pick", pn.top_left_x, pn.top_left_y];
                return undefined;
            }
        }
    } else if (tool == ToolType.Shovel) {
        var si = GRID.try_node_index_for_cell((x div 2) * 2, (y div 2) * 2);
        if (si != undefined && GRID.node_object_id[si] == ObjectId.DigSite) {
            var sn = GRID.node_parent[si];
            if (d.nodes[$ mistrimulti_dg_cell_key(sn.top_left_x, sn.top_left_y)] == sn) return ["dig", sn.top_left_x, sn.top_left_y];
        }
    }
    return undefined;
}

// tool.targets: a swing at a shared rock or dig site is taken out of the list and asked of the host once it is
// final; the swing is played out (with the game's own function) when the host agrees.
function mistrimulti_dg_tool_targets(value, ctx) {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    if (!mistrimulti_dg_gate(d)) return undefined;
    try {
        var tool = ctx.item.prototype.tool_type;
        if (tool != ToolType.PickAxe && tool != ToolType.Shovel) return undefined;
        // This hook runs every frame of a swing; a gap between calls means a new swing.
        if (r.ticks - d.swing_at > 3) d.swing = {};
        d.swing_at = r.ticks;
        var released = quality_to_range_pattern(ctx.item.prototype.quality) == RangePattern.One || !INPUT.check(InputId.UseToolCharged);
        var keep = List();
        var taken = false;
        for (var i = 0; i < value.count(); i++) {
            var cell = value.get(i);
            var hit = mistrimulti_dg_swing(d, tool, cell.x, cell.y);
            if (hit == undefined) {
                keep.push(cell);
                continue;
            }
            taken = true;
            var key = hit[0] + ":" + mistrimulti_dg_cell_key(hit[1], hit[2]);
            if (released && !struct_exists(d.swing, key)) {
                var data = { o: hit[0], run: d.my_run, f: d.f, x: hit[1], y: hit[2], i: item_id_to_string(ctx.item.item_id), c: ctx.range_pattern == RangePattern.One ? 0 : 1 };
                if (mistrimulti_event_request("dg_act", data) != undefined) d.swing[$ key] = true;
            }
        }
        return taken ? keep : undefined;
    } catch (e) {
        mistrimulti_dg_fail(d, e);
        return undefined;
    }
}

// object.interact: opening a chest or picking a forageable is asked of the host first.
function mistrimulti_dg_interact(node) {
    var r = __mistrimulti_runtime();
    var d = mistrimulti_dg_state();
    if (!mistrimulti_dg_gate(d)) return undefined;
    try {
        var cat = object_id_to_object_category(node.object_id);
        var chest = cat == ObjectCategory.Breakable && node.prototype[$ "chest"] != undefined;
        if (!chest && cat != ObjectCategory.Crop) return undefined;
        var key = mistrimulti_dg_cell_key(node.top_left_x, node.top_left_y);
        if (d.nodes[$ key] != node || !can_interact(node)) return undefined;
        var last = d.press[$ key];
        if (last == undefined || r.ticks - last >= MISTRIMULTI_DG_PRESS) {
            if (mistrimulti_event_request("dg_act", { o: "use", run: d.my_run, f: d.f, x: node.top_left_x, y: node.top_left_y }) != undefined) d.press[$ key] = r.ticks;
        }
        return true;
    } catch (e) {
        mistrimulti_dg_fail(d, e);
        return undefined;
    }
}

function mistrimulti_dg_new_doppel() {
    return new TangoDoppel();
}

// The host answered a claim: bring the node to the state it had, run the game's own action (drops, perks, xp,
// stamina and effects are this player's), then put the host's state over the result.
function mistrimulti_dg_perform(d, res) {
    d.bypass++;
    try {
        var key = mistrimulti_dg_cell_key(res[$ "x"], res[$ "y"]);
        var n = d.nodes[$ key];
        if (res[$ "ok"] == true && n != undefined && mistrimulti_dg_node_at(n)) {
            if (is_real(res[$ "p"]) && n[$ "hitpoints"] != undefined) n.hitpoints = res.p;
            mistrimulti_dg_run(res, n);
            if (!mistrimulti_dg_node_at(n)) struct_remove(d.nodes, key);
        }
        mistrimulti_dg_apply_node(d, res);
    } catch (e) {
        mistrimulti_dg_fail(d, e);
    }
    d.bypass--;
}

function mistrimulti_dg_run(res, n) {
    var x = res.x;
    var y = res.y;
    if (res.o == "use") {
        interact(n);
        return;
    }
    var itemid = is_string(res[$ "i"]) ? try_string_to_item_id(res.i) : undefined;
    if (itemid == undefined) return;
    var proto = ITEM_PROTOTYPES[itemid];
    var modifier = res[$ "c"] == 1 ? -1 : 0;
    var doppel = mistrimulti_dg_new_doppel();
    if (res.o == "pick") {
        var picked = pick_node(GRID, x, y, proto, modifier, undefined, doppel);
        if (picked != PickResult.Nothing) {
            if (picked != PickResult.Furniture) {
                ARI.gain_essence(proto.quality + 1, 8 * (x + 1), 8 * (y + 1));
                ARI.modify_stamina(proto.stamina_cost);
            }
            if (picked == PickResult.DigSite) ARI.gain_xp(Skill.Archaeology, XpValue.break_dig_spot);
        }
    } else if (res.o == "dig") {
        var dug = shovel_node(GRID, x, y, doppel);
        if (has_flag(dug, ShovelResult.GIVE_ESSENCE)) {
            ARI.gain_essence(proto.quality + 1, 8 * (x + 1), 8 * (y + 1));
            ARI.modify_stamina(proto.stamina_cost);
        }
        if (has_flag(dug, ShovelResult.GAIN_DIG_SITE_EXPERIENCE)) ARI.gain_xp(Skill.Archaeology, XpValue.break_dig_spot);
    }
    doppel.resolve();
}

// Shared nodes that vanished by anything but a claim (a bomb, a sword hit on a breakable, the ladder code) are
// reported to the host, which tells the other games.
function mistrimulti_dg_report_gone(r, d) {
    if (r.ticks - d.scan_at >= MISTRIMULTI_DG_SCAN) {
        d.scan_at = r.ticks;
        var keys = struct_get_names(d.nodes);
        for (var i = 0; i < array_length(keys); i++) {
            var n = d.nodes[$ keys[i]];
            if (!mistrimulti_dg_node_at(n) && array_length(d.gq) < 64) {
                array_push(d.gq, [n.top_left_x, n.top_left_y]);
                struct_remove(d.nodes, keys[i]);
            }
        }
    }
    while (array_length(d.gq) > 0 && mistrimulti_event_backlog() < MISTRIMULTI_DG_BACKLOG) {
        var c = d.gq[0];
        if (mistrimulti_event_request("dg_act", { o: "gone", run: d.my_run, f: d.f, x: c[0], y: c[1] }) == undefined) break;
        array_delete(d.gq, 0, 1);
    }
}

// ---- hooks that are not about nodes or monsters ------------------------------------------------------------------------------------

// For the MMAPI debug agent (mistrimulti.dungeon).
function mistrimulti_dungeon_debug() {
    var d = mistrimulti_dg_state();
    var floors = {};
    var keys = struct_get_names(d.floors);
    for (var i = 0; i < array_length(keys); i++) {
        var fl = d.floors[$ keys[i]];
        floors[$ keys[i]] = { st: fl.st, nodes: array_length(struct_get_names(fl.nodes)), mons: array_length(struct_get_names(fl.mons)), rev: fl.rev };
    }
    return { run: d.run, my_run: d.my_run, f: d.f, sp: d.sp, au: d.au, fol: array_length(struct_get_names(d.fol)), st: d.st, errors: d.errors, hits: d.hits, lost: d.lost,
        mons: array_length(struct_get_names(d.mons)), nodes: array_length(struct_get_names(d.nodes)), pend: array_length(d.pend), floors: floors };
}
