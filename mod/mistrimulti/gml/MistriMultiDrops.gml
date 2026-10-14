// MistriMulti world items: loose items on the ground (obj_item) as host-owned objects with ids, pickup claims that are
// granted to exactly one player, direct gifts between players, and host-seeded loot rolls. Protocol, assumptions and the
// in-game checklist: docs/SYNC-CONTAINERS.md. Chest contents are in MistriMultiContainers.gml.
//
// Every game has its own obj_item instances; they are puppets of one table that the host owns:
//   table[id] = { id, loc, x, y, g: [[item, n], ...], by: slot that dropped it, f: uid it is meant for or "" }
// A drop stays private to the game that made it for 2 seconds (the dropper has first pick, and most drops are collected by
// then without any traffic). After that it is published: `item_drop` (request) makes the host create the entry and tell
// everybody, and the other games spawn a matching instance. Picking up is a claim: the game's own pickup is cancelled at the
// last moment (the same way it refuses a full inventory), `item_claim` (request) asks the host, the host removes the entry
// and the answer is broadcast, so exactly one player receives the items and every other instance disappears.
// Kinds: item_drop, item_claim (requests); item_snap (host event to one guest), item_day (host event to everybody).

#macro MISTRIMULTI_DR_TABLE 256
#macro MISTRIMULTI_DR_GROUPS 6
#macro MISTRIMULTI_DR_COUNT 999
#macro MISTRIMULTI_DR_PUBLISH_TICKS 120
#macro MISTRIMULTI_DR_PENDING 8
#macro MISTRIMULTI_DR_STREAM_EVENTS 2
#macro MISTRIMULTI_DR_PER_EVENT 2
#macro MISTRIMULTI_DR_RETRY_TICKS 120
#macro MISTRIMULTI_DR_REACH 200
#macro MISTRIMULTI_DR_GIVE_REACH 96

function mistrimulti_drops_register_events() {
    mistrimulti_event_register("item_drop", { on_request: mistrimulti_drops_drop_request, on_result: mistrimulti_drops_drop_result,
        on_reply: mistrimulti_drops_drop_reply });
    mistrimulti_event_register("item_claim", { on_request: mistrimulti_drops_claim_request, on_result: mistrimulti_drops_claim_result,
        on_reply: mistrimulti_drops_claim_reply });
    mistrimulti_event_register("item_snap", { on_event: mistrimulti_drops_snap_event });
    mistrimulti_event_register("item_day", { on_event: mistrimulti_drops_day_event, on_peer: mistrimulti_drops_peer });
}

// ---- state ---------------------------------------------------------------------------------------------

// Per world session. recs: instance -> what this game knows about it; bound: entry id -> instance.
function __mistrimulti_dr() {
    var r = __mistrimulti_runtime();
    var dr = r[$ "dr"];
    if (!is_struct(dr) || dr.stream != r.ev.stream) {
        dr = { stream: r.ev.stream, table: {}, ids: [], next: 1, recs: {}, bound: {}, rids: {}, claims: {}, gives: {}, pending: 0,
            snaps: array_create(8, undefined), room: -1, seed: 0, reseed: 0, respawn: 0, day: false };
        if (r.mode == "host") dr.seed = irandom_range(1, 2147483000);
        r.dr = dr;
    }
    return dr;
}

// The location this game is in, or -1 when items are not shared here (no world, or a per-player dungeon floor).
function __mistrimulti_dr_room() {
    if (!instance_exists(obj_ari) || GRID == undefined || ARI == undefined || GRID.dyn_index != undefined) return -1;
    return CURRENT_LOCATION_ID;
}

// Every obj_item instance of this room.
function __mistrimulti_dr_instances() {
    var list = [];
    with (obj_item) array_push(list, id);
    return list;
}

function __mistrimulti_dr_track(dr, inst, state) {
    var rec = { inst: inst, state: state, wid: 0, born: __mistrimulti_runtime().ticks, rid: "", claim: "", retry: 0, origin: true };
    dr.recs[$ string(inst)] = rec;
    return rec;
}

function __mistrimulti_dr_untrack(dr, rec) {
    if (rec.wid != 0 && dr.bound[$ string(rec.wid)] == rec.inst) struct_remove(dr.bound, string(rec.wid));
    struct_remove(dr.recs, string(rec.inst));
}

// ---- entries ----------------------------------------------------------------------------------------------

// An entry from the network (or built from a local instance) -> the normalised entry, or undefined when anything is wrong.
function __mistrimulti_dr_entry(e) {
    if (!is_struct(e) || !is_real(e[$ "id"]) || e.id != floor(e.id) || e.id < 1) return undefined;
    if (!is_real(e[$ "loc"]) || e.loc != floor(e.loc) || e.loc < 0 || e.loc > 255) return undefined;
    if (!is_real(e[$ "x"]) || !is_real(e[$ "y"]) || abs(e.x) > 100000 || abs(e.y) > 100000) return undefined;
    var g = e[$ "g"];
    if (!is_array(g) || array_length(g) < 1 || array_length(g) > MISTRIMULTI_DR_GROUPS) return undefined;
    var groups = [];
    var kind = "";
    var total = 0;
    for (var i = 0; i < array_length(g); i++) {
        var pair = g[i];
        if (!is_array(pair) || array_length(pair) != 2 || !is_real(pair[1]) || pair[1] != floor(pair[1]) || pair[1] < 1) return undefined;
        var it = __mistrimulti_ct_clean(pair[0]);
        if (it == undefined || (kind != "" && it.item_id != kind)) return undefined;
        kind = it.item_id;
        total += pair[1];
        if (total > MISTRIMULTI_DR_COUNT) return undefined;
        array_push(groups, [__mistrimulti_ct_wire(it), pair[1]]);
    }
    var by = e[$ "by"];
    var f = e[$ "f"];
    return { id: e.id, loc: e.loc, x: e.x, y: e.y, g: groups,
        by: is_real(by) && by >= 0 && by < 8 ? by : 0, f: is_string(f) && string_length(f) <= 80 ? f : "" };
}

// The units of an entry as live items (the game keeps one LiveItem per unit in an obj_item's list).
function __mistrimulti_dr_units(e) {
    var units = [];
    for (var i = 0; i < array_length(e.g); i++) {
        for (var k = 0; k < e.g[i][1]; k++) {
            var live = __mistrimulti_ct_live(e.g[i][0]);
            if (live != undefined) array_push(units, live);
        }
    }
    return units;
}

// The groups of a local instance, or undefined when it cannot be shared.
function __mistrimulti_dr_groups(inst) {
    var groups = [];
    var kind = -1;
    if (inst.items.count() < 1 || inst.items.count() > MISTRIMULTI_DR_COUNT) return undefined;
    for (var i = 0; i < inst.items.count(); i++) {
        var live = inst.items.get(i);
        var it = __mistrimulti_ct_norm(live.serialize());
        if (kind != -1 && live.item_id != kind) return undefined;
        kind = live.item_id;
        var last = array_length(groups) - 1;
        if (last >= 0 && __mistrimulti_ct_item_eq(groups[last][0], it)) {
            groups[last][1] += 1;
        } else {
            if (array_length(groups) >= MISTRIMULTI_DR_GROUPS) return undefined;
            array_push(groups, [it, 1]);
        }
    }
    for (var w = 0; w < array_length(groups); w++) groups[w][0] = __mistrimulti_ct_wire(groups[w][0]);
    return groups;
}

function __mistrimulti_dr_put(dr, e) {
    var key = string(e.id);
    if (!struct_exists(dr.table, key)) array_push(dr.ids, key);
    dr.table[$ key] = e;
}

// Drop an entry: from the table, and its instance in this game (a mirror or the dropper's own).
function __mistrimulti_dr_remove(dr, id) {
    var key = string(id);
    struct_remove(dr.table, key);
    for (var i = 0; i < array_length(dr.ids); i++) {
        if (dr.ids[i] == key) {
            array_delete(dr.ids, i, 1);
            break;
        }
    }
    var inst = dr.bound[$ key];
    struct_remove(dr.bound, key);
    if (inst == undefined) return;
    struct_remove(dr.recs, string(inst));
    if (instance_exists(inst)) instance_destroy(inst);
}

// A puppet instance of an entry, when this game is in its room and has none yet.
function __mistrimulti_dr_spawn(dr, e) {
    if (__mistrimulti_dr_room() != e.loc) return;
    var known = dr.bound[$ string(e.id)];
    if (known != undefined && instance_exists(known)) return;
    var units = __mistrimulti_dr_units(e);
    if (array_length(units) == 0) return;
    var inst = instance_create_layer(e.x, e.y, "Instances", obj_item);
    inst.setup(ListFromArray(units));
    inst.final_x = e.x;
    inst.final_y = e.y;
    inst.v_counter = 60; // no bounce: it was lying there already
    inst.thrown_by_ari = false;
    var rec = __mistrimulti_dr_track(dr, inst, e.f != "" && e.f != __mistrimulti_runtime().uid ? "locked" : "shared");
    rec.wid = e.id;
    rec.origin = false;
    dr.bound[$ string(e.id)] = inst;
}

// Forget everything shared: the host's table was replaced (restart) or a day passed. Instances that this game's player
// dropped keep living as private items (and are published again) when `keep` is set.
function __mistrimulti_dr_clear(dr, keep) {
    var names = struct_get_names(dr.recs);
    for (var i = 0; i < array_length(names); i++) {
        var rec = dr.recs[$ names[i]];
        if (rec.wid == 0 && rec.state != "pub") continue;
        if (keep && rec.origin) {
            rec.state = "new";
            rec.wid = 0;
            rec.rid = "";
            rec.claim = "";
            rec.born = __mistrimulti_runtime().ticks;
        } else {
            if (instance_exists(rec.inst)) instance_destroy(rec.inst);
            struct_remove(dr.recs, names[i]);
        }
    }
    dr.table = {};
    dr.ids = [];
    dr.bound = {};
    dr.rids = {};
    dr.claims = {};
    dr.pending = 0;
}

// ---- publishing what this game dropped -------------------------------------------------------------------------

function __mistrimulti_dr_publish(dr, rec) {
    var inst = rec.inst;
    var groups = __mistrimulti_dr_groups(inst);
    if (groups == undefined) {
        rec.state = "local";
        return;
    }
    var data = { loc: CURRENT_LOCATION_ID, x: round(inst.x), y: round(inst.y), g: groups, f: "", inv: inst.thrown_by_ari == true };
    var rid = mistrimulti_event_request("item_drop", data);
    if (rid == undefined) return;
    rec.state = "pub";
    rec.rid = rid;
    dr.rids[$ rid] = rec;
    dr.pending++;
}

function __mistrimulti_dr_scan(dr) {
    var r = __mistrimulti_runtime();
    var room = __mistrimulti_dr_room();
    var list = __mistrimulti_dr_instances();
    var alive = {};
    for (var i = 0; i < array_length(list); i++) {
        var inst = list[i];
        var key = string(inst);
        alive[$ key] = true;
        var rec = dr.recs[$ key];
        if (rec == undefined) rec = __mistrimulti_dr_track(dr, inst, room >= 0 ? "new" : "local");
        if (rec.state == "new" && room >= 0 && r.mask != 0 && r.ticks - rec.born >= MISTRIMULTI_DR_PUBLISH_TICKS
            && dr.pending < MISTRIMULTI_DR_PENDING && inst.kill_timer == -1 && inst.mist_id == undefined) {
            __mistrimulti_dr_publish(dr, rec);
        }
    }
    // Instances that no longer exist (picked up, room left, destroyed by the game).
    var names = struct_get_names(dr.recs);
    for (var j = 0; j < array_length(names); j++) {
        if (alive[$ names[j]] == undefined) __mistrimulti_dr_untrack(dr, dr.recs[$ names[j]]);
    }
}

// Entering a room: puppets for every shared entry of it.
function __mistrimulti_dr_enter(dr) {
    var room = __mistrimulti_dr_room();
    if (room == dr.room) return;
    dr.room = room;
    if (room < 0) return;
    for (var i = 0; i < array_length(dr.ids); i++) {
        var e = dr.table[$ dr.ids[i]];
        if (e != undefined) __mistrimulti_dr_spawn(dr, e);
    }
}

// ---- picking up -----------------------------------------------------------------------------------------------

// Every frame: the moment the game starts to pick up a shared item, cancel it (the way it refuses a full inventory) and
// ask the host. Private items are picked up by the game as usual.
function mistrimulti_drops_frame() {
    var r = __mistrimulti_runtime();
    if (!r.enabled) return;
    try {
        var dr = __mistrimulti_dr();
        var names = struct_get_names(dr.recs);
        for (var i = 0; i < array_length(names); i++) {
            var rec = dr.recs[$ names[i]];
            if (rec.state == "new" || rec.state == "local" || !instance_exists(rec.inst)) continue;
            var inst = rec.inst;
            if (inst.kill_timer == -1 || inst.kill_target != obj_ari) continue;
            inst.kill_timer = -1;
            inst.lerping_to_player = false;
            inst.v = 0;
            if (rec.state != "shared" || rec.claim != "" || rec.retry > r.ticks) continue;
            var rid = mistrimulti_event_request("item_claim", { id: rec.wid });
            if (rid != undefined) {
                rec.claim = rid;
                dr.claims[$ rid] = rec;
            }
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "Item pickup failed: " + string(e));
    }
}

// The items of a granted claim go to this game's player, the way the game's own pickup gives them.
function __mistrimulti_dr_grant(groups) {
    if (!is_array(groups)) return;
    for (var i = 0; i < array_length(groups); i++) {
        var it = is_array(groups[i]) && array_length(groups[i]) == 2 ? __mistrimulti_ct_clean(groups[i][0]) : undefined;
        var n = is_array(groups[i]) && array_length(groups[i]) == 2 ? groups[i][1] : 0;
        if (it == undefined || !is_real(n) || n < 1 || n > MISTRIMULTI_DR_COUNT) continue;
        if (it.auto_use == true) {
            for (var k = 0; k < n; k++) use_item_fast(__mistrimulti_ct_live(it));
        } else {
            var live = __mistrimulti_ct_live(it);
            if (live != undefined) ARI.give_item(live, n, true, true, true);
        }
    }
    // A guest's record on the host already contains the items; the next checkpoint should say so too.
    var r = __mistrimulti_runtime();
    if (r.mode == "join") r.player_last_checkpoint = 0;
}

function __mistrimulti_dr_location_ok(peer, loc) {
    var room = peer[$ "room"];
    var prefix = location_id_to_string(loc) + ":";
    return is_string(room) && string_copy(room, 1, string_length(prefix)) == prefix;
}

// Host only, once per request id. At most one player gets an entry.
function mistrimulti_drops_claim_request(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || !is_struct(data) || !is_real(data[$ "id"])) return { ok: false, why: "bad" };
    var dr = __mistrimulti_dr();
    var e = dr.table[$ string(data.id)];
    if (e == undefined) return { ok: false, id: data.id, why: "gone" };
    var peer = r.peers[player];
    var uid = r.uid;
    if (player != r.id) {
        if (!is_struct(peer) || peer[$ "active"] != true || !__mistrimulti_dr_location_ok(peer, e.loc)
            || !is_real(peer[$ "x"]) || !is_real(peer[$ "y"]) || point_distance(peer.x, peer.y, e.x, e.y) > MISTRIMULTI_DR_REACH) {
            return { ok: false, id: data.id, why: "away" };
        }
        uid = peer[$ "uid"];
    }
    if (e.f != "" && e.f != uid) return { ok: false, id: data.id, why: "locked" };
    __mistrimulti_dr_remove(dr, data.id);
    if (player != r.id) {
        var flows = [];
        for (var i = 0; i < array_length(e.g); i++) array_push(flows, { it: e.g[i][0], n: e.g[i][1] });
        mistrimulti_ct_record_apply(player, flows);
    }
    return { ok: true, id: data.id, by: player, g: e.g };
}

function __mistrimulti_dr_claim_done(dr, rid) {
    var rec = dr.claims[$ rid];
    struct_remove(dr.claims, rid);
    if (rec != undefined) rec.claim = "";
    return rec;
}

function __mistrimulti_dr_claim_settled(dr, result, ctx) {
    var id = result[$ "id"];
    if (!is_real(id)) return;
    if (result[$ "ok"] == true) {
        __mistrimulti_dr_remove(dr, id);
        if (ctx.mine) {
            __mistrimulti_dr_claim_done(dr, ctx.id);
            __mistrimulti_dr_grant(result[$ "g"]);
        }
    } else if (ctx.mine) {
        var rec = __mistrimulti_dr_claim_done(dr, ctx.id);
        var why = result[$ "why"];
        if (why == "gone") __mistrimulti_dr_remove(dr, id);
        else if (rec != undefined && why == "locked") rec.state = "locked";
        else if (rec != undefined) rec.retry = __mistrimulti_runtime().ticks + MISTRIMULTI_DR_RETRY_TICKS;
    }
}

function mistrimulti_drops_claim_result(player, result, ctx) {
    if (__mistrimulti_runtime().mode != "join" || player != 0 || !is_struct(result)) return true;
    try { __mistrimulti_dr_claim_settled(__mistrimulti_dr(), result, ctx); }
    catch (e) { mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "An item claim could not be applied: " + string(e)); }
    return true;
}

// The requester: the host's own claims arrive here (the host receives no results); lost or expired answers too.
function mistrimulti_drops_claim_reply(player, result, ctx) {
    var r = __mistrimulti_runtime();
    try {
        var dr = __mistrimulti_dr();
        if (is_struct(result)) {
            if (r.mode == "host") __mistrimulti_dr_claim_settled(dr, result, ctx);
        } else {
            // Lost: the host that held the table restarted, nothing was granted. Expired: granted, but the answer is gone.
            var rec = __mistrimulti_dr_claim_done(dr, ctx.id);
            if (ctx.expired) mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "An item claim answer expired.");
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "An item claim could not be settled: " + string(e));
    }
    return true;
}

// ---- host: creating entries --------------------------------------------------------------------------------------

function mistrimulti_drops_drop_request(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || !is_struct(data)) return { ok: false, why: "bad" };
    var dr = __mistrimulti_dr();
    var peer = r.peers[player];
    if (player != r.id && (!is_struct(peer) || peer[$ "active"] != true)) return { ok: false, why: "away" };
    var e = __mistrimulti_dr_entry({ id: dr.next, loc: data[$ "loc"], x: data[$ "x"], y: data[$ "y"], g: data[$ "g"], by: player, f: data[$ "f"] });
    if (e == undefined) return { ok: false, why: "bad" };
    if (array_length(dr.ids) >= MISTRIMULTI_DR_TABLE) return { ok: false, why: "full" };
    if (player != r.id && !__mistrimulti_dr_location_ok(peer, e.loc)) return { ok: false, why: "away" };
    dr.next++;
    __mistrimulti_dr_put(dr, e);
    if (player != r.id) {
        if (data[$ "inv"] == true) {
            // It came out of the guest's inventory; remove it from the stored record too (docs/SYNC-CONTAINERS.md).
            var flows = [];
            for (var i = 0; i < array_length(e.g); i++) array_push(flows, { it: e.g[i][0], n: -e.g[i][1] });
            mistrimulti_ct_record_apply(player, flows);
        }
        __mistrimulti_dr_spawn(dr, e);
    }
    return { ok: true, e: e };
}

// This game's request for an entry came back: bind the dropper's own instance to it, or spawn a puppet.
function __mistrimulti_dr_created(dr, result, ctx) {
    var e = __mistrimulti_dr_entry(result[$ "e"]);
    var rec = ctx.mine ? dr.rids[$ ctx.id] : undefined;
    if (ctx.mine) {
        struct_remove(dr.rids, ctx.id);
        if (rec != undefined) dr.pending = max(dr.pending - 1, 0);
    }
    var give = ctx.mine ? dr.gives[$ ctx.id] : undefined;
    if (give != undefined) struct_remove(dr.gives, ctx.id);
    if (result[$ "ok"] != true || e == undefined) {
        if (rec != undefined) rec.state = "local";
        if (give != undefined) __mistrimulti_ct_player_give(give.it, give.n); // refused: the giver gets it back
        return;
    }
    __mistrimulti_dr_put(dr, e);
    if (rec != undefined && dr.recs[$ string(rec.inst)] == rec && instance_exists(rec.inst)) {
        rec.state = e.f != "" && e.f != __mistrimulti_runtime().uid ? "locked" : "shared";
        rec.wid = e.id;
        dr.bound[$ string(e.id)] = rec.inst;
    } else {
        __mistrimulti_dr_spawn(dr, e);
    }
}

function mistrimulti_drops_drop_result(player, result, ctx) {
    if (__mistrimulti_runtime().mode != "join" || player != 0 || !is_struct(result)) return true;
    try { __mistrimulti_dr_created(__mistrimulti_dr(), result, ctx); }
    catch (e) { mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "An item drop could not be applied: " + string(e)); }
    return true;
}

function mistrimulti_drops_drop_reply(player, result, ctx) {
    var r = __mistrimulti_runtime();
    try {
        var dr = __mistrimulti_dr();
        if (is_struct(result)) {
            if (r.mode == "host") __mistrimulti_dr_created(dr, result, ctx);
            return true;
        }
        var rec = dr.rids[$ ctx.id];
        var give = dr.gives[$ ctx.id];
        struct_remove(dr.rids, ctx.id);
        struct_remove(dr.gives, ctx.id);
        if (rec != undefined) dr.pending = max(dr.pending - 1, 0);
        if (ctx.lost) {
            // The old host's table is gone with it: publish again to the new one, or hand the gift back.
            if (rec != undefined && dr.recs[$ string(rec.inst)] == rec) {
                rec.state = "new";
                rec.rid = "";
                rec.born = r.ticks;
            }
            if (give != undefined) __mistrimulti_ct_player_give(give.it, give.n);
        } else if (rec != undefined && instance_exists(rec.inst)) {
            // Expired: the host has the entry, we never learned its id. The snapshot after a rejoin spawns it.
            instance_destroy(rec.inst);
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "An item drop could not be settled: " + string(e));
    }
    return true;
}

// ---- gifts ---------------------------------------------------------------------------------------------------------

// Give the stack in hand to the participant `target` (a slot): it lands at their feet as an entry only they can claim.
// The stack leaves the inventory at once and comes back if the host refuses.
function mistrimulti_drops_give(target) {
    var r = __mistrimulti_runtime();
    var dr = __mistrimulti_dr();
    var room = __mistrimulti_dr_room();
    var peer = is_real(target) && target >= 0 && target < 8 && target != r.id ? r.peers[target] : undefined;
    if (!r.enabled || room < 0 || !is_struct(peer) || peer[$ "active"] != true || !is_string(peer[$ "uid"]) || !__mistrimulti_dr_location_ok(peer, room)) return false;
    var slot = ARI.inventory.slot(ARI.held_item_index);
    if (slot.item == undefined || slot.count < 1 || slot.count > MISTRIMULTI_DR_COUNT) return false;
    var it = __mistrimulti_ct_norm(slot.item.serialize());
    var n = slot.count;
    var rid = mistrimulti_event_request("item_drop", { loc: room, x: round(peer.x), y: round(peer.y), g: [[it, n]], f: peer.uid, inv: true });
    if (rid == undefined) return false;
    slot.remove(n);
    dr.gives[$ rid] = { it: it, n: n };
    return true;
}

// F9: give the stack in hand to the nearest player in this room.
function mistrimulti_drops_give_hotkey() {
    var r = __mistrimulti_runtime();
    if (!r.enabled || ARI == undefined || !instance_exists(obj_ari)) return;
    try {
        var best = -1;
        var range = MISTRIMULTI_DR_GIVE_REACH;
        for (var i = 0; i < 8; i++) {
            var p = r.peers[i];
            if (i == r.id || !is_struct(p) || p[$ "active"] != true || p[$ "room"] != mistrimulti_room_key()) continue;
            var d = point_distance(obj_ari.x, obj_ari.y, p.x, p.y);
            if (d <= range) {
                range = d;
                best = i;
            }
        }
        var text = best < 0 || !mistrimulti_drops_give(best) ? "Nobody nearby, or nothing to give." : "Item given.";
        create_notification(ANCHOR.wrap_for_local(text));
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "Giving failed: " + string(e));
    }
}

// ---- snapshots, days, seeds --------------------------------------------------------------------------------------

// A participant appeared or left. Host: the new guest gets the table. Guest: a (re)started host has a new table.
function mistrimulti_drops_peer(slot, joined, stream) {
    var r = __mistrimulti_runtime();
    var dr = __mistrimulti_dr();
    if (r.mode == "host") {
        dr.snaps[slot] = joined ? { stream: stream, ids: __mistrimulti_dr_copy(dr.ids), pos: 0, first: true } : undefined;
    } else if (slot == 0 && joined) {
        __mistrimulti_dr_clear(dr, true);
    }
}

function __mistrimulti_dr_copy(list) {
    var out = [];
    for (var i = 0; i < array_length(list); i++) array_push(out, list[i]);
    return out;
}

function __mistrimulti_dr_stream(dr) {
    var budget = MISTRIMULTI_DR_STREAM_EVENTS;
    for (var slot = 1; slot < 8 && budget > 0; slot++) {
        var s = dr.snaps[slot];
        if (!is_struct(s)) continue;
        while (budget > 0 && (s.first || s.pos < array_length(s.ids))) {
            if (mistrimulti_event_backlog() >= 16 || !mistrimulti_event_can_emit(2)) return;
            var batch = [];
            while (array_length(batch) < MISTRIMULTI_DR_PER_EVENT && s.pos < array_length(s.ids)) {
                var e = dr.table[$ s.ids[s.pos]];
                s.pos++;
                if (e != undefined) array_push(batch, e);
            }
            var data = { e: batch, seed: dr.seed };
            if (s.first) data.r = true;
            if (!mistrimulti_event_emit("item_snap", data, slot)) {
                dr.snaps[slot] = undefined;
                break;
            }
            s.first = false;
            budget--;
        }
        if (is_struct(dr.snaps[slot]) && !s.first && s.pos >= array_length(s.ids)) dr.snaps[slot] = undefined;
    }
}

function mistrimulti_drops_snap_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "join" || player != 0 || !is_struct(data) || !is_array(data[$ "e"]) || array_length(data.e) > 8) return true;
    try {
        var dr = __mistrimulti_dr();
        if (data[$ "r"] == true) __mistrimulti_dr_clear(dr, true);
        if (is_real(data[$ "seed"])) dr.seed = data.seed;
        for (var i = 0; i < array_length(data.e); i++) {
            var e = __mistrimulti_dr_entry(data.e[i]);
            if (e == undefined || array_length(dr.ids) >= MISTRIMULTI_DR_TABLE) continue;
            __mistrimulti_dr_put(dr, e);
            __mistrimulti_dr_spawn(dr, e);
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "An item snapshot could not be applied: " + string(e));
    }
    return true;
}

// game.new_day (host): loose items of the shared table follow the game's own rule for items left on the ground, they
// stay in their location (the grid's lost items, saved with the world). Every game drops its puppets; the day also
// brings a new seed for loot rolls.
function mistrimulti_drops_new_day(ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || r.mode != "host") return;
    try {
        var dr = __mistrimulti_dr();
        for (var i = 0; i < array_length(dr.ids); i++) {
            var e = dr.table[$ dr.ids[i]];
            var grid = e == undefined ? undefined : GRIDS[e.loc];
            if (grid != undefined) grid.lost_items.push({ x: e.x, y: e.y, items: ListFromArray(__mistrimulti_dr_units(e)) });
        }
        __mistrimulti_dr_clear(dr, false);
        dr.seed = irandom_range(1, 2147483000);
        // Before any request of the new day is answered, so every guest sees the day change first.
        dr.day = !mistrimulti_event_emit("item_day", { seed: dr.seed });
        dr.room = -2;
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "The day change for world items failed: " + string(e));
    }
}

function mistrimulti_drops_day_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "join" || player != 0 || !is_struct(data)) return true;
    try {
        var dr = __mistrimulti_dr();
        __mistrimulti_dr_clear(dr, false);
        if (is_real(data[$ "seed"])) dr.seed = data.seed;
        dr.room = -2;
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "The day change for world items failed: " + string(e));
    }
    return true;
}

// game.save_guard (host): the game is about to store the loose items of this room as lost items. Ours are in the table;
// drop the puppets for the save and bring them back right after.
function mistrimulti_drops_before_save() {
    var r = __mistrimulti_runtime();
    if (!r.enabled || r.mode != "host") return;
    try {
        var dr = __mistrimulti_dr();
        var names = struct_get_names(dr.recs);
        for (var i = 0; i < array_length(names); i++) {
            var rec = dr.recs[$ names[i]];
            if (rec.wid == 0) continue;
            if (instance_exists(rec.inst)) instance_destroy(rec.inst);
            __mistrimulti_dr_untrack(dr, rec);
        }
        dr.respawn = r.ticks + 30;
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "Items could not be set aside for the save: " + string(e));
    }
}

// Loot rolls that follow from the host's seed: the result depends only on (host seed, source), so no player can reroll
// it and every game that rolls it gets the same answer. The game's own randomness resumes a few frames later.
function __mistrimulti_dr_seed(source) {
    var r = __mistrimulti_runtime();
    if (!r.enabled) return;
    var dr = __mistrimulti_dr();
    if (dr.seed == 0) return;
    random_set_seed(__mistrimulti_ev_hash(MISTRIMULTI_EV_FNV_OFFSET, string(dr.seed) + ":" + source));
    dr.reseed = r.ticks + 6;
}

// dungeon.treasure_chest: fires before the chest's loot is rolled.
function mistrimulti_drops_treasure(ctx) {
    try { __mistrimulti_dr_seed("chest:" + string(CURRENT_LOCATION_ID) + ":" + string(round(ctx.x)) + "," + string(round(ctx.y))); }
    catch (e) { mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "Loot seed failed: " + string(e)); }
}

// resource.node_picked: fires when a rock breaks, before its drops are rolled.
function mistrimulti_drops_rock(ctx) {
    try {
        if (ctx.result != "rock" || ctx.destroyed != true || ctx.burn == true || ctx.effect_override != undefined) return;
        __mistrimulti_dr_seed("rock:" + string(CURRENT_LOCATION_ID) + ":" + string(ctx.node.top_left_x) + "," + string(ctx.node.top_left_y));
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "Loot seed failed: " + string(e));
    }
}

// ---- tick ---------------------------------------------------------------------------------------------------------

// Bridge tick (20 Hz) while a world is loaded.
function mistrimulti_drops_tick() {
    var r = __mistrimulti_runtime();
    if (!r.enabled) return;
    try {
        var dr = __mistrimulti_dr();
        if (dr.reseed > 0 && r.ticks >= dr.reseed) {
            randomize();
            dr.reseed = 0;
        }
        if (dr.respawn > 0 && r.ticks >= dr.respawn) {
            dr.respawn = 0;
            dr.room = -2;
        }
        if (dr.day && mistrimulti_event_emit("item_day", { seed: dr.seed })) dr.day = false;
        __mistrimulti_dr_scan(dr);
        __mistrimulti_dr_enter(dr);
        if (r.mode == "host") __mistrimulti_dr_stream(dr);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_drops", "mistrimulti", "World item sync failed: " + string(e));
    }
}

function mistrimulti_drops_debug() {
    var dr = __mistrimulti_dr();
    return { entries: array_length(dr.ids), tracked: array_length(struct_get_names(dr.recs)), pending: dr.pending, seed: dr.seed };
}
