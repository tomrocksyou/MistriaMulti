// Ranch sync: animals, the farm pet, products, placed furniture and blueprints, new buildings, machines,
// farm expansion and the house (size, variant, floors and wallpapers). Design and checklist: docs/SYNC-RANCH.md.
//
// The host owns this state. Hosts publish it (change-only, plus a full snapshot whenever a game joins);
// guests apply it. A guest never changes shared state itself:
//   * Paid actions (hand feed, treats, manger, adopting, placing furniture, blueprints, floors, wallpapers,
//     machines) are VETOED locally. The guest sends a request, the host validates and applies it, and the
//     requester pays only when the host's reply says "ok" (one reply per request id, so one charge).
//   * Actions the game performs before a mod can see them (selling, renaming, moving an animal, petting,
//     buying a farm expansion or a house upgrade) run locally and are reported afterwards. The host accepts
//     or refuses; a refusal takes back what the player received (or refunds what the game charged) once.
// Positions are not shared: animals move in each game, only their logical state (hearts, flags, names,
// building, pairing, fetuses, feed in the mangers) is the host's.
//
// Event kinds: ranch_act (request/result), ranch_stable, ranch_world, ranch_struct, ranch_resync.

#macro MISTRIMULTI_RANCH_NAME_MAX 24
#macro MISTRIMULTI_RANCH_TEXT_MAX 6500
#macro MISTRIMULTI_RANCH_ANIMALS_MAX 48
#macro MISTRIMULTI_RANCH_LEDGER_MAX 400
#macro MISTRIMULTI_RANCH_WAIT_TICKS 200
#macro MISTRIMULTI_RANCH_I32 2147483647

// ---- state -------------------------------------------------------------------------------------------

// Everything here belongs to one world session; entering a world starts a new event stream and so resets it.
function __mistrimulti_ranch() {
    var r = __mistrimulti_runtime();
    var rc = r[$ "ranch"];
    if (!is_struct(rc)) {
        rc = { stream: "" };
        r.ranch = rc;
    }
    if (rc.stream != r.ev.stream) {
        rc.stream = r.ev.stream;
        __mistrimulti_ranch_reset(rc);
    }
    return rc;
}

function __mistrimulti_ranch_reset(rc) {
    rc.n = 0;
    rc.applying = 0;          // > 0 while this file changes the world: our own hooks must not react
    rc.sid = 0;               // host: snapshot counter
    rc.sent = {};             // host: building id -> last published record text
    rc.wsent = "";            // host: last published world record
    rc.binit = false;         // host: existing buildings noted
    rc.bset = {};             // host: ids of buildings that exist
    rc.bnew = [];             // host: buildings finished during this session
    rc.snaps = [];            // host: slots waiting for a full snapshot
    rc.led = [];              // host: placements of this session { rec, node, grid }
    rc.watch = [];            // host: own placements waiting for the game to confirm them
    rc.pool = {};             // building id -> [{ i, n }] products waiting to be collected
    rc.pool_loaded = false;
    rc.known = {};            // guest: animal idx -> what the host last said { b, n, p, v }
    rc.synced = false;
    rc.host_stream = "";      // guest: the host session the state above belongs to
    rc.fin = undefined;
    rc.got = {};
    rc.busy = "";             // guest: id of the paid request in flight
    rc.busy_until = 0;
    rc.pending = {};          // request id -> what to do with the answer
    rc.inflight = {};         // duplicate guard for reported actions
    rc.unresolved = [];       // guest: sales whose answer was lost (decided by the next snapshot)
    rc.deferred = {};         // guest: building records for buildings that do not exist yet
    rc.retry = [];            // guest: structures that could not be placed yet
    rc.applied = [];          // guest: placements applied for the current host session { rec, node, grid }
    rc.use = undefined;       // the item being used this frame
    rc.world_known = undefined;
    rc.world_defer = undefined;
    rc.pet_known = false;
    rc.charged = 0;           // diagnostics: paid requests settled
}

function mistrimulti_ranch_debug() {
    var rc = __mistrimulti_ranch();
    return { n: rc.n, synced: rc.synced, busy: rc.busy, pending: array_length(struct_get_names(rc.pending)),
        known: array_length(struct_get_names(rc.known)), ledger: array_length(rc.led), charged: rc.charged,
        unresolved: array_length(rc.unresolved), snaps: array_length(rc.snaps), pool: json_stringify(rc.pool) };
}

// ---- registration ------------------------------------------------------------------------------------

function mistrimulti_ranch_register_events() {
    mistrimulti_event_register("ranch_act", { on_request: mistrimulti_ranch_request, on_result: mistrimulti_ranch_result,
        on_reply: mistrimulti_ranch_reply });
    // on_peer runs once per registered function: it lives on this kind only.
    mistrimulti_event_register("ranch_stable", { on_event: mistrimulti_ranch_stable_event,
        on_blob: mistrimulti_ranch_stable_blob, on_peer: mistrimulti_ranch_peer });
    mistrimulti_event_register("ranch_world", { on_event: mistrimulti_ranch_world_event, on_blob: mistrimulti_ranch_world_blob });
    mistrimulti_event_register("ranch_struct", { on_event: mistrimulti_ranch_struct_event, on_blob: mistrimulti_ranch_struct_blob });
    mistrimulti_event_register("ranch_resync", { on_event: mistrimulti_ranch_resync_event });
}

function mistrimulti_ranch_register_hooks() {
    mmapi_filter("animal.production_gate", mistrimulti_ranch_production_gate);
    mmapi_filter("animal.product_drops", mistrimulti_ranch_product_drops);
    mmapi_guard("input.take_press", mistrimulti_ranch_take_press);
    mmapi_guard("furniture.place_guard", mistrimulti_ranch_place_guard);
    mmapi_guard("items.use_guard", mistrimulti_ranch_use_guard);
    mmapi_guard("game.save_guard", mistrimulti_ranch_save_guard);
    mmapi_override("object.interact", mistrimulti_ranch_object_interact);
    mmapi_on("ui.menu_opened", mistrimulti_ranch_menu_opened);
    mmapi_on("game.new_day", mistrimulti_ranch_new_day);
}

// ---- helpers -----------------------------------------------------------------------------------------

function __mistrimulti_ranch_int(v, lo, hi) {
    return is_real(v) && v == floor(v) && v >= lo && v <= hi;
}

function __mistrimulti_ranch_text(v, max) {
    return is_string(v) && string_length(v) <= max;
}

function __mistrimulti_ranch_say(text) {
    try { create_notification(ANCHOR.wrap_for_local(text)); }
    catch (e) { }
}

function __mistrimulti_ranch_warn(text) {
    mmapi_warn_rate_limited("mistrimulti_ranch", "mistrimulti", text);
}

function __mistrimulti_ranch_on(mode) {
    var r = __mistrimulti_runtime();
    return r.enabled && r.mode == mode;
}

// Engine constructors live here so that nothing else in this file needs `new`.
function mistrimulti_ranch_make_animal(kind, variant, sex) {
    return new PlayerAnimal(kind, variant, sex);
}

function mistrimulti_ranch_make_item(item_id) {
    return new LiveItem(item_id);
}

function __mistrimulti_ranch_cap() {
    return animal_heart_level_to_points(10);
}

// The game adds hearts through add_heart_points, which also pays the HOST's skill XP: hearts a guest earns
// are set directly instead.
function __mistrimulti_ranch_hearts(animal, delta) {
    animal.heart_points = clamp(animal.heart_points + delta, 0, __mistrimulti_ranch_cap());
}

function __mistrimulti_ranch_bid(building) {
    return string(building.top_left_x) + ":" + string(building.top_left_y);
}

function __mistrimulti_ranch_stables() {
    var out = [];
    var list = get_buildings();
    for (var i = 0; i < list.count(); i++) {
        var b = list.get(i);
        if (b.stable != undefined) array_push(out, b);
    }
    return out;
}

function __mistrimulti_ranch_stable_by_id(bid) {
    var all = __mistrimulti_ranch_stables();
    for (var i = 0; i < array_length(all); i++) {
        if (__mistrimulti_ranch_bid(all[i]) == bid) return all[i];
    }
    return undefined;
}

function __mistrimulti_ranch_stable_by_dyn(dyn) {
    if (dyn == undefined) return undefined;
    var all = __mistrimulti_ranch_stables();
    for (var i = 0; i < array_length(all); i++) {
        if (all[i].dyn_index == dyn) return all[i];
    }
    return undefined;
}

function __mistrimulti_ranch_stalls(stable) {
    var out = [];
    for (var i = 0; i < stable.stalls.count(); i++) {
        var a = stable.stalls.get(i);
        if (a != undefined) array_push(out, a);
    }
    return out;
}

function __mistrimulti_ranch_free_stall(stable) {
    for (var i = 0; i < stable.stalls.count(); i++) {
        if (stable.stalls.get(i) == undefined) return true;
    }
    return false;
}

function __mistrimulti_ranch_is_pet(a) {
    return a[$ "is_pet"] == true;
}

// ---- animal records ------------------------------------------------------------------------------------

function __mistrimulti_ranch_animal_record(a) {
    return { i: a.idx, k: a.kind, v: a.variant, s: a.sex, n: a.name, h: a.heart_points, d: a.days_old,
        u: a.unhappy_days, e: a.has_eaten == true, p: a.has_been_pat == true, o: a.has_been_outside == true,
        pd: a.production_days, t: a.ate_breeding_treat == true, w: a.breeding_with ?? -1,
        x: a.is_incubating == true, c: a.cosmetic ?? "", bd: a.birthday };
}

function __mistrimulti_ranch_variant_ok(kind, variant) {
    return __mistrimulti_ranch_text(variant, 32) && ANIMAL_PROTOTYPES[kind].variants.contains_key(variant);
}

function __mistrimulti_ranch_animal_valid(rec) {
    if (!is_struct(rec)) return false;
    if (!__mistrimulti_ranch_int(rec[$ "i"], 0, MISTRIMULTI_RANCH_I32)) return false;
    if (!__mistrimulti_ranch_int(rec[$ "k"], 0, AnimalKind.LEN - 1) || !__mistrimulti_ranch_int(rec[$ "s"], 0, Sex.LEN - 1)) return false;
    if (!__mistrimulti_ranch_variant_ok(rec.k, rec[$ "v"])) return false;
    if (!__mistrimulti_ranch_text(rec[$ "n"], MISTRIMULTI_RANCH_NAME_MAX)) return false;
    if (!is_real(rec[$ "h"]) || rec.h < 0 || rec.h > 1000000) return false;
    if (!__mistrimulti_ranch_int(rec[$ "d"], 0, 100000) || !__mistrimulti_ranch_int(rec[$ "u"], 0, 100000)) return false;
    if (!__mistrimulti_ranch_int(rec[$ "pd"], 0, 100000) || !__mistrimulti_ranch_int(rec[$ "w"], -1, MISTRIMULTI_RANCH_I32)) return false;
    if (typeof(rec[$ "e"]) != "bool" || typeof(rec[$ "p"]) != "bool" || typeof(rec[$ "o"]) != "bool") return false;
    if (typeof(rec[$ "t"]) != "bool" || typeof(rec[$ "x"]) != "bool") return false;
    if (!__mistrimulti_ranch_text(rec[$ "c"], 48) || !is_real(rec[$ "bd"]) || rec.bd < 0 || rec.bd > 1000000000) return false;
    return rec.c == "" || ANIMAL_PROTOTYPES[rec.k].cosmetics.contains_key(rec.c);
}

function __mistrimulti_ranch_set_fields(a, rec) {
    a.name = rec.n;
    a.heart_points = rec.h;
    a.days_old = rec.d;
    a.unhappy_days = rec.u;
    a.has_eaten = rec.e;
    a.has_been_pat = rec.p;
    a.has_been_outside = rec.o;
    a.production_days = rec.pd;
    a.ate_breeding_treat = rec.t;
    a.breeding_with = rec.w >= 0 ? rec.w : undefined;
    a.is_incubating = rec.x;
    a.cosmetic = rec.c == "" ? undefined : rec.c;
    a.birthday = rec.bd;
}

function __mistrimulti_ranch_manger_ids(inventory) {
    var out = [];
    for (var i = 0; i < array_length(inventory); i++) array_push(out, inventory[i] == undefined ? -1 : inventory[i].item_id);
    return out;
}

function __mistrimulti_ranch_stable_record(rc, b) {
    var stable = b.stable;
    var an = [];
    var list = __mistrimulti_ranch_stalls(stable);
    for (var i = 0; i < array_length(list); i++) array_push(an, __mistrimulti_ranch_animal_record(list[i]));
    var fe = [];
    for (var j = 0; j < stable.incubating_fetuses.count(); j++) {
        var f = stable.incubating_fetuses.get(j);
        array_push(fe, { mp: f.male_parent, fp: f.female_parent, d: f.days, k: f.animal.kind, v: f.animal.variant,
            s: f.animal.sex, n: f.animal.name });
    }
    var mg = [];
    if (b.prototype.double_manger) {
        array_push(mg, __mistrimulti_ranch_manger_ids(stable.left_inventory));
        array_push(mg, __mistrimulti_ranch_manger_ids(stable.right_inventory));
    } else {
        array_push(mg, __mistrimulti_ranch_manger_ids(stable.inventory));
    }
    var bid = __mistrimulti_ranch_bid(b);
    return { b: bid, an: an, fe: fe, mg: mg, pl: rc.pool[$ bid] ?? [] };
}

function __mistrimulti_ranch_stable_valid(rec) {
    if (!is_struct(rec) || !__mistrimulti_ranch_text(rec[$ "b"], 24)) return false;
    var an = rec[$ "an"];
    if (!is_array(an) || array_length(an) > MISTRIMULTI_RANCH_ANIMALS_MAX) return false;
    for (var i = 0; i < array_length(an); i++) if (!__mistrimulti_ranch_animal_valid(an[i])) return false;
    var fe = rec[$ "fe"];
    if (!is_array(fe) || array_length(fe) > 16) return false;
    for (var j = 0; j < array_length(fe); j++) {
        var f = fe[j];
        if (!is_struct(f) || !__mistrimulti_ranch_int(f[$ "mp"], 0, MISTRIMULTI_RANCH_I32) || !__mistrimulti_ranch_int(f[$ "fp"], 0, MISTRIMULTI_RANCH_I32)) return false;
        if (!__mistrimulti_ranch_int(f[$ "d"], -1, 1000) || !__mistrimulti_ranch_int(f[$ "k"], 0, AnimalKind.LEN - 1)) return false;
        if (!__mistrimulti_ranch_int(f[$ "s"], 0, Sex.LEN - 1) || !__mistrimulti_ranch_variant_ok(f.k, f[$ "v"])) return false;
        if (!__mistrimulti_ranch_text(f[$ "n"], MISTRIMULTI_RANCH_NAME_MAX)) return false;
    }
    var mg = rec[$ "mg"];
    if (!is_array(mg) || array_length(mg) < 1 || array_length(mg) > 2) return false;
    for (var m = 0; m < array_length(mg); m++) {
        if (!is_array(mg[m]) || array_length(mg[m]) > 16) return false;
        for (var q = 0; q < array_length(mg[m]); q++) if (!__mistrimulti_ranch_int(mg[m][q], -1, ItemId.LEN - 1)) return false;
    }
    var pl = rec[$ "pl"];
    if (!is_array(pl) || array_length(pl) > 16) return false;
    for (var p = 0; p < array_length(pl); p++) {
        if (!is_struct(pl[p]) || !__mistrimulti_ranch_int(pl[p][$ "i"], 0, ItemId.LEN - 1) || !__mistrimulti_ranch_int(pl[p][$ "n"], 1, 999)) return false;
    }
    return true;
}

// ---- guest: applying the host's state -----------------------------------------------------------------

function __mistrimulti_ranch_note(rc, a, bid) {
    var value = 0;
    try { value = a.sell_value(); }
    catch (e) { value = 0; }
    rc.known[$ string(a.idx)] = { b: bid, n: a.name, p: a.has_been_pat == true, v: value };
}

// Takes an animal out of its building without the side effects of a sale (no treat drops, no gold).
function __mistrimulti_ranch_drop(rc, a) {
    a.ate_breeding_treat = false;
    a.breeding_with = undefined;
    if (a.instance != undefined) instance_destroy(a.instance);
    if (a.stable != undefined) a.stable.deregister(a);
    if (ARI.held_animal_id == a.idx) ARI.held_animal_id = undefined;
    struct_remove(rc.known, string(a.idx));
}

function __mistrimulti_ranch_upsert(rc, b, rec) {
    var stable = b.stable;
    var a = find_animal(rec.i, false);
    if (a == undefined) {
        if (find_animal(rec.i, true) != undefined) return;     // in the daycare: not shared
        if (struct_exists(rc.inflight, "sell:" + string(rec.i))) return;     // this player just sold it
        if (!__mistrimulti_ranch_free_stall(stable)) {
            __mistrimulti_ranch_warn("A shared animal did not fit in its building.");
            return;
        }
        a = mistrimulti_ranch_make_animal(rec.k, rec.v, rec.s);
        a.idx = rec.i;
        __mistrimulti_ranch_set_fields(a, rec);
        stable.register(a);
        __mistrimulti_ranch_set_fields(a, rec);                 // register pairs treat-fed animals itself
        if (a.is_present() && a.instance == undefined) spawn_animal(a);
    } else {
        if (a.stable != stable) {
            if (!__mistrimulti_ranch_free_stall(stable)) return;
            a.ate_breeding_treat = false;
            a.breeding_with = undefined;
            if (a.stable != undefined) a.stable.deregister(a);
            stable.register(a);
            if (a.is_present() && a.instance == undefined) spawn_animal(a);
        }
        var typed = a.name;
        __mistrimulti_ranch_set_fields(a, rec);
        if (struct_exists(rc.inflight, "rename:" + string(a.idx))) a.name = typed;     // the host has not seen the new name yet
    }
    __mistrimulti_ranch_note(rc, a, __mistrimulti_ranch_bid(b));
}

function __mistrimulti_ranch_apply_manger(stable, b, mg) {
    var sides = [];
    if (b.prototype.double_manger) {
        array_push(sides, stable.left_inventory);
        array_push(sides, stable.right_inventory);
    } else {
        array_push(sides, stable.inventory);
    }
    for (var s = 0; s < min(array_length(sides), array_length(mg)); s++) {
        var inventory = sides[s];
        for (var j = 0; j < array_length(inventory); j++) {
            var want = j < array_length(mg[s]) ? mg[s][j] : -1;
            var have = inventory[j] == undefined ? -1 : inventory[j].item_id;
            if (want == have) continue;
            // Only feed can sit in a manger; edit the array in place, because the manger object shares it.
            if (want < 0) inventory[j] = undefined;
            else if (ITEM_PROTOTYPES[want].animal_feed != undefined) inventory[j] = mistrimulti_ranch_make_item(want);
        }
    }
}

function __mistrimulti_ranch_apply_stable(rc, rec) {
    var b = __mistrimulti_ranch_stable_by_id(rec.b);
    if (b == undefined) {
        rc.deferred[$ rec.b] = rec;      // the building is built later by ranch_struct
        return false;
    }
    struct_remove(rc.deferred, rec.b);
    var stable = b.stable;
    // What the player did since the last look is reported before the host's version overwrites it.
    __mistrimulti_ranch_watch_animals(rc);
    rc.applying++;
    try {
        var keep = {};
        for (var i = 0; i < array_length(rec.an); i++) {
            keep[$ string(rec.an[i].i)] = true;
            __mistrimulti_ranch_upsert(rc, b, rec.an[i]);
        }
        var extra = [];
        var here = __mistrimulti_ranch_stalls(stable);
        for (var j = 0; j < array_length(here); j++) {
            if (!struct_exists(keep, string(here[j].idx))) array_push(extra, here[j]);
        }
        for (var k = 0; k < array_length(extra); k++) __mistrimulti_ranch_drop(rc, extra[k]);
        stable.incubating_fetuses.clear();
        for (var f = 0; f < array_length(rec.fe); f++) {
            var e = rec.fe[f];
            stable.incubating_fetuses.push({ male_parent: e.mp, female_parent: e.fp, days: e.d,
                animal: { kind: e.k, variant: e.v, sex: e.s, name: e.n } });
        }
        __mistrimulti_ranch_apply_manger(stable, b, rec.mg);
        rc.pool[$ rec.b] = rec.pl;
    } catch (err) {
        __mistrimulti_ranch_warn("A shared barn update failed: " + string(err));
    }
    rc.applying--;
    return true;
}

function __mistrimulti_ranch_stable_message(rc, rec) {
    if (!__mistrimulti_ranch_on("join")) return;
    __mistrimulti_ranch_session(rc);
    if (is_struct(rec) && is_real(rec[$ "sid"])) {
        var key = string(rec.sid);
        rc.got[$ key] = (rc.got[$ key] ?? 0) + 1;
    }
    if (__mistrimulti_ranch_stable_valid(rec)) __mistrimulti_ranch_apply_stable(rc, rec);
    else __mistrimulti_ranch_warn("A shared barn update was rejected.");
    __mistrimulti_ranch_check_sync(rc);
}

function mistrimulti_ranch_stable_event(from, data, ctx) {
    if (from == 0) __mistrimulti_ranch_stable_message(__mistrimulti_ranch(), data);
    return true;
}

function mistrimulti_ranch_stable_blob(from, text, meta) {
    if (from != 0) return true;
    var data = undefined;
    try { data = json_parse(text); }
    catch (e) { __mistrimulti_ranch_warn("A shared barn update could not be read."); }
    __mistrimulti_ranch_stable_message(__mistrimulti_ranch(), data);
    return true;
}

// The snapshot is complete once the world record (sent last) has arrived and every barn message before it
// has (they may travel as blobs, which are not ordered against events).
function __mistrimulti_ranch_check_sync(rc) {
    if (rc.fin == undefined) return;
    if ((rc.got[$ string(rc.fin.sid)] ?? 0) < rc.fin.sn) return;
    rc.synced = true;
    rc.fin = undefined;
    rc.got = {};
    __mistrimulti_ranch_resolve(rc);
}

// A sale whose answer was lost is decided by what the host says after it restarted: still there means not sold.
function __mistrimulti_ranch_resolve(rc) {
    if (!rc.synced) return;
    for (var i = 0; i < array_length(rc.unresolved); i++) {
        var u = rc.unresolved[i];
        if (struct_exists(rc.known, string(u.i))) {
            ARI.modify_gold(-u.g);
            __mistrimulti_ranch_say("A sale was not completed; the gold was taken back.");
        }
    }
    rc.unresolved = [];
}

// The host's state belongs to one host session. The first message of a new one (it is already applied to
// peers[0] when it is delivered) throws away what was believed about the old one.
function __mistrimulti_ranch_session(rc) {
    var host = __mistrimulti_runtime().peers[0];
    var stream = is_struct(host) && is_struct(host[$ "ev"]) ? host.ev.s : "";
    if (stream == rc.host_stream) return;
    if (rc.host_stream != "") __mistrimulti_ranch_revert_applied(rc);
    rc.host_stream = stream;
    rc.retry = [];
    rc.synced = false;
    rc.known = {};
    rc.fin = undefined;
    rc.got = {};
    rc.pool = {};
    rc.inflight = {};
    rc.busy = "";
    rc.deferred = {};
    rc.world_known = undefined;
    rc.world_defer = undefined;
}

// A game appeared (a new session of a player, or one that came back after 10 seconds): send it everything.
function mistrimulti_ranch_peer(slot, joined, stream) {
    var r = __mistrimulti_runtime();
    if (r.enabled && r.mode == "host" && joined) __mistrimulti_ranch_want_snapshot(__mistrimulti_ranch(), slot);
}

function __mistrimulti_ranch_want_snapshot(rc, slot) {
    for (var i = 0; i < array_length(rc.snaps); i++) if (rc.snaps[i] == slot) return;
    array_push(rc.snaps, slot);
}

function mistrimulti_ranch_resync_event(from, data, ctx) {
    if (__mistrimulti_ranch_on("host") && is_real(from)) __mistrimulti_ranch_want_snapshot(__mistrimulti_ranch(), from);
    return true;
}

// ---- host: publishing --------------------------------------------------------------------------------

function __mistrimulti_ranch_send(kind, data, target) {
    if (string_byte_length(json_stringify(data)) <= MISTRIMULTI_RANCH_TEXT_MAX) return mistrimulti_event_emit(kind, data, target);
    return mistrimulti_event_send_blob(kind, json_stringify(data), target);
}

// target -1: everyone, only when the record changed. A slot: that game gets it regardless (snapshots).
function __mistrimulti_ranch_publish(rc, b, target, sid) {
    var rec = __mistrimulti_ranch_stable_record(rc, b);
    var text = json_stringify(rec);
    if (target < 0 && rc.sent[$ rec.b] == text) return true;
    if (sid > 0) rec.sid = sid;
    var ok = __mistrimulti_ranch_send("ranch_stable", rec, target);
    if (ok && target < 0) rc.sent[$ rec.b] = text;
    return ok;
}

// The pet has no barn: its state travels in the world record.
function __mistrimulti_ranch_publish_animal(rc, a) {
    var stable = a[$ "stable"];
    if (stable != undefined) __mistrimulti_ranch_publish(rc, stable.building, -1, 0);
    else rc.wsent = "";
}

function __mistrimulti_ranch_building_record(b) {
    return { x: b.top_left_x, y: b.top_left_y, o: b.object_id, vr: b.variant, n: b.name };
}

// Notes buildings the first time (they are in every game's copy of the world) and announces new ones.
function __mistrimulti_ranch_scan_buildings(rc) {
    var list = get_buildings();
    var fresh = [];
    for (var i = 0; i < list.count(); i++) {
        var b = list.get(i);
        var bid = __mistrimulti_ranch_bid(b);
        if (struct_exists(rc.bset, bid)) continue;
        rc.bset[$ bid] = true;
        if (rc.binit) {
            array_push(fresh, __mistrimulti_ranch_building_record(b));
            array_push(rc.bnew, __mistrimulti_ranch_building_record(b));
        }
    }
    rc.binit = true;
    if (array_length(fresh) > 0) __mistrimulti_ranch_send("ranch_struct", { bld: fresh }, -1);
}

function __mistrimulti_ranch_scan(rc) {
    var all = __mistrimulti_ranch_stables();
    for (var i = 0; i < array_length(all); i++) {
        if (!mistrimulti_event_can_emit(4) || mistrimulti_event_backlog() > 24) return;
        __mistrimulti_ranch_publish(rc, all[i], -1, 0);
    }
}

function __mistrimulti_ranch_live_ledger(rc) {
    var out = [];
    for (var i = 0; i < array_length(rc.led); i++) array_push(out, rc.led[i].rec);
    return out;
}

// Everything a game that just joined needs, in an order that works: buildings and placements first,
// then the barns, then the world record that says how many barn messages to expect.
function __mistrimulti_ranch_snapshot(rc, slot) {
    var all = __mistrimulti_ranch_stables();
    if (!mistrimulti_event_can_emit(array_length(all) + 4) || mistrimulti_event_backlog() > 24) return false;
    rc.sid++;
    var ok = __mistrimulti_ranch_send("ranch_struct", { full: true, bld: rc.bnew, add: __mistrimulti_ranch_live_ledger(rc) }, slot);
    for (var i = 0; i < array_length(all); i++) ok = __mistrimulti_ranch_publish(rc, all[i], slot, rc.sid) && ok;
    var world = __mistrimulti_ranch_world_record();
    world.fin = true;
    world.sid = rc.sid;
    world.sn = array_length(all);
    return __mistrimulti_ranch_send("ranch_world", world, slot) && ok;
}

function __mistrimulti_ranch_host_tick(r, rc) {
    if (r.world_path != "" && !rc.pool_loaded) __mistrimulti_ranch_pool_load(rc);
    if (GRIDS == undefined) return;
    // The ledger and the building list are kept even while nobody else is here: a later joiner needs them.
    if (!rc.binit || rc.n mod 10 == 0) __mistrimulti_ranch_scan_buildings(rc);
    if (rc.n mod 10 == 0) __mistrimulti_ranch_watch_own(rc);
    if (rc.n mod 40 == 15) __mistrimulti_ranch_ledger_check(rc);
    if (r.mask == 0) return;
    if (array_length(rc.snaps) > 0 && __mistrimulti_ranch_snapshot(rc, rc.snaps[0])) array_delete(rc.snaps, 0, 1);
    if (rc.n mod 10 == 0) __mistrimulti_ranch_scan(rc);
    if (rc.n mod 20 == 5) {
        var world = __mistrimulti_ranch_world_record();
        var text = json_stringify(world);
        if (text != rc.wsent && mistrimulti_event_can_emit(2) && __mistrimulti_ranch_send("ranch_world", world, -1)) rc.wsent = text;
    }
    // Repair: a guest's own day-change work may have disturbed its copy; each barn is sent again now and then.
    if (rc.n mod 60 == 30) {
        var all = __mistrimulti_ranch_stables();
        if (array_length(all) > 0) struct_remove(rc.sent, __mistrimulti_ranch_bid(all[(rc.n div 60) mod array_length(all)]));
    }
}

// ---- host: validating guest requests -----------------------------------------------------------------

function mistrimulti_ranch_request(from, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || !is_struct(data) || !is_string(data[$ "a"])) return { ok: false, why: "bad_request" };
    var peer = r.peers[from];
    if (from != r.id && (!is_struct(peer) || peer[$ "active"] != true)) return { ok: false, why: "not_in_world" };
    var rc = __mistrimulti_ranch();
    var a = data.a;
    var res = { ok: false, why: "unsupported" };
    try {
        if (a == "pet") res = __mistrimulti_ranch_do_pet(rc, data);
        else if (a == "feed") res = __mistrimulti_ranch_do_feed(rc, data);
        else if (a == "treat") res = __mistrimulti_ranch_do_treat(rc, data);
        else if (a == "manger") res = __mistrimulti_ranch_do_manger(rc, data, from);
        else if (a == "adopt") res = __mistrimulti_ranch_do_adopt(rc, data);
        else if (a == "sell") res = __mistrimulti_ranch_do_sell(rc, data);
        else if (a == "rename") res = __mistrimulti_ranch_do_rename(rc, data);
        else if (a == "move") res = __mistrimulti_ranch_do_move(rc, data);
        else if (a == "collect") res = __mistrimulti_ranch_do_collect(rc, data, from);
        else if (a == "place") res = __mistrimulti_ranch_do_place(rc, data, from);
        else if (a == "fgive") res = __mistrimulti_ranch_do_factory(rc, data, from);
        else if (a == "world") res = __mistrimulti_ranch_do_world(rc, data);
    } catch (err) {
        __mistrimulti_ranch_warn("A shared request failed: " + string(err));
        res = { ok: false, why: "error" };
    }
    res.a = a;
    return res;
}

// Where a player is comes from their own frames (the room key of the boot tick): requests that act on a room
// are accepted only from a player who is in it.
function __mistrimulti_ranch_here(from, loc, dyn) {
    var r = __mistrimulti_runtime();
    if (from == r.id) return true;
    var peer = r.peers[from];
    return is_struct(peer) && peer[$ "room"] == location_id_to_string(loc) + ":" + string(dyn);
}

function __mistrimulti_ranch_no(why) {
    return { ok: false, why: why };
}

function __mistrimulti_ranch_pay_item(item_id) {
    return { g: 0, it: [{ i: item_id, n: 1 }] };
}

function __mistrimulti_ranch_do_pet(rc, d) {
    if (!__mistrimulti_ranch_int(d[$ "i"], -1, MISTRIMULTI_RANCH_I32)) return __mistrimulti_ranch_no("bad_request");
    var a = find_animal(d.i, false);
    if (a == undefined) return __mistrimulti_ranch_no("gone");
    if (a.has_been_pat == true) return __mistrimulti_ranch_no("already");
    a.has_been_pat = true;
    __mistrimulti_ranch_hearts(a, fiddle_get("ranching/misc/heart_points/pet"));
    __mistrimulti_ranch_publish_animal(rc, a);
    return { ok: true };
}

// The same test the game's interaction uses (animal_feed of the right size, or anything edible).
function __mistrimulti_ranch_can_eat(a, proto) {
    if (proto.soulbind != undefined) return false;
    if (proto.recipe != undefined && !proto.tags.contains("animal_feed")) return false;
    if (proto.edible || proto.tags.contains("animals_can_eat")) return true;
    return proto.animal_feed != undefined && proto.animal_feed.animal_size == a.prototype.core.size;
}

function __mistrimulti_ranch_do_feed(rc, d) {
    if (!__mistrimulti_ranch_int(d[$ "i"], -1, MISTRIMULTI_RANCH_I32) || !__mistrimulti_ranch_int(d[$ "it"], 0, ItemId.LEN - 1)) return __mistrimulti_ranch_no("bad_request");
    var a = find_animal(d.i, false);
    if (a == undefined) return __mistrimulti_ranch_no("gone");
    if (a.has_eaten == true) return __mistrimulti_ranch_no("already");
    var proto = ITEM_PROTOTYPES[d.it];
    var res = { ok: true, pay: __mistrimulti_ranch_pay_item(d.it) };
    if (__mistrimulti_ranch_is_pet(a)) {
        if (proto.pet_treat == undefined || !proto.pet_treat.pet_kinds[a.pet_kind()]) return __mistrimulti_ranch_no("refused");
        __mistrimulti_ranch_hearts(a, ANIMAL_HEART_POINTS.base_value + ANIMAL_HEART_POINTS.feed[proto.pet_treat.tier]);
    } else {
        if (d.it == a.prototype.breeding.treat || !__mistrimulti_ranch_can_eat(a, proto)) return __mistrimulti_ranch_no("refused");
        __mistrimulti_ranch_hearts(a, item_heart_value_for_animal(proto));
        res.xp = true;
    }
    a.has_eaten = true;
    __mistrimulti_ranch_publish_animal(rc, a);
    return res;
}

// Breeding treat, with the checks of the game's conversation (the guest sees a notice instead).
function __mistrimulti_ranch_do_treat(rc, d) {
    if (!__mistrimulti_ranch_int(d[$ "i"], 0, MISTRIMULTI_RANCH_I32) || !__mistrimulti_ranch_int(d[$ "it"], 0, ItemId.LEN - 1)) return __mistrimulti_ranch_no("bad_request");
    var a = find_animal(d.i, false);
    if (a == undefined || a.stable == undefined) return __mistrimulti_ranch_no("gone");
    if (d.it != a.prototype.breeding.treat) return __mistrimulti_ranch_no("refused");
    if (a.is_incubating) return __mistrimulti_ranch_no("pregnant");
    if (a.ate_breeding_treat) return __mistrimulti_ranch_no("already");
    if (a.is_baby()) return __mistrimulti_ranch_no("baby");
    if (points_to_animal_heart_level(a.heart_points) < fiddle_get("ranching/misc/min_heart_level_for_breeding")) return __mistrimulti_ranch_no("hearts");
    if (a.stable.availability() < 1) return __mistrimulti_ranch_no("no_room");
    if (a.prototype.breeding.uses_egg && a.stable.incubator_availability() < 1) return __mistrimulti_ranch_no("no_incubator");
    var mates = __mistrimulti_ranch_stalls(a.stable);
    var partner = undefined;
    for (var i = 0; i < array_length(mates); i++) {
        var v = mates[i];
        if (v.idx == a.idx || !v.ate_breeding_treat || v.kind != a.kind || v.breeding_with != undefined) continue;
        if (v.sex == a.sex) return __mistrimulti_ranch_no("taken");
        partner = v;
    }
    a.ate_breeding_treat = true;
    if (partner != undefined) {
        a.breeding_with = partner.idx;
        partner.breeding_with = a.idx;
    }
    __mistrimulti_ranch_publish_animal(rc, a);
    return { ok: true, pay: __mistrimulti_ranch_pay_item(d.it) };
}

function __mistrimulti_ranch_do_manger(rc, d, from) {
    if (!__mistrimulti_ranch_text(d[$ "b"], 24) || !__mistrimulti_ranch_int(d[$ "sd"], 0, 1) || !__mistrimulti_ranch_int(d[$ "it"], 0, ItemId.LEN - 1)) return __mistrimulti_ranch_no("bad_request");
    var b = __mistrimulti_ranch_stable_by_id(d.b);
    if (b == undefined) return __mistrimulti_ranch_no("gone");
    if (!__mistrimulti_ranch_here(from, b.prototype.location_id, b.dyn_index)) return __mistrimulti_ranch_no("not_here");
    var proto = ITEM_PROTOTYPES[d.it];
    if (proto.animal_feed == undefined || proto.animal_feed.animal_size != b.prototype.permitted_animal_size) return __mistrimulti_ranch_no("refused");
    var inventory = b.stable[$ "inventory"];
    if (b.prototype.double_manger) inventory = d.sd == 0 ? b.stable.left_inventory : b.stable.right_inventory;
    for (var i = 0; i < array_length(inventory); i++) {
        if (inventory[i] != undefined) continue;
        inventory[i] = mistrimulti_ranch_make_item(d.it);
        __mistrimulti_ranch_publish(rc, b, -1, 0);
        return { ok: true, pay: __mistrimulti_ranch_pay_item(d.it) };
    }
    return __mistrimulti_ranch_no("full");
}

function __mistrimulti_ranch_do_adopt(rc, d) {
    if (!__mistrimulti_ranch_int(d[$ "k"], 0, AnimalKind.LEN - 1) || !__mistrimulti_ranch_int(d[$ "s"], 0, Sex.LEN - 1) || !__mistrimulti_ranch_text(d[$ "b"], 24)) return __mistrimulti_ranch_no("bad_request");
    if (!__mistrimulti_ranch_variant_ok(d.k, d[$ "v"]) || !is_string(d[$ "n"]) || string_length(d.n) < 1 || string_length(d.n) > MISTRIMULTI_RANCH_NAME_MAX) return __mistrimulti_ranch_no("bad_request");
    var animal = ANIMAL_PROTOTYPES[d.k];
    var variant = animal.variants.get(d.v);
    if (!variant.acquirable) return __mistrimulti_ranch_no("refused");
    var b = __mistrimulti_ranch_stable_by_id(d.b);
    if (b == undefined) return __mistrimulti_ranch_no("gone");
    if (b.prototype.permitted_animal_size != animal.core.size) return __mistrimulti_ranch_no("refused");
    if (b.stable.availability() < 1 || !__mistrimulti_ranch_free_stall(b.stable)) return __mistrimulti_ranch_no("no_room");
    // The price comes from the game's data, never from the guest.
    var cost = animal.pricing.buy_price * animal.pricing.tier_sell_price_multipliers[variant.tier];
    var baby = mistrimulti_ranch_make_animal(d.k, d.v, d.s);
    baby.name = d.n;
    baby.birthday = seasons(CALENDAR.season()) + days(CALENDAR.day());
    baby.cosmetic = variant.default_cosmetic;
    b.stable.register(baby);
    if (baby.is_present() && baby.instance == undefined) spawn_animal(baby);
    __mistrimulti_ranch_publish(rc, b, -1, 0);
    return { ok: true, pay: { g: cost, it: [] }, idx: baby.idx };
}

// The guest already sold it in the game (and was paid); the host decides whether the sale stands.
function __mistrimulti_ranch_do_sell(rc, d) {
    if (!__mistrimulti_ranch_int(d[$ "i"], 0, MISTRIMULTI_RANCH_I32)) return __mistrimulti_ranch_no("bad_request");
    var a = find_animal(d.i, false);
    if (a == undefined || a.stable == undefined) return __mistrimulti_ranch_no("gone");
    if (a.is_incubating) return __mistrimulti_ranch_no("pregnant");
    var value = a.sell_value();
    var b = a.stable.building;
    rc.applying++;
    __mistrimulti_ranch_drop(rc, a);
    rc.applying--;
    __mistrimulti_ranch_publish(rc, b, -1, 0);
    return { ok: true, val: value };
}

function __mistrimulti_ranch_do_rename(rc, d) {
    if (!__mistrimulti_ranch_int(d[$ "i"], 0, MISTRIMULTI_RANCH_I32) || !is_string(d[$ "n"]) || string_length(d.n) < 1 || string_length(d.n) > MISTRIMULTI_RANCH_NAME_MAX) return __mistrimulti_ranch_no("bad_request");
    var a = find_animal(d.i, false);
    if (a == undefined) return __mistrimulti_ranch_no("gone");
    a.name = d.n;
    __mistrimulti_ranch_publish_animal(rc, a);
    return { ok: true };
}

function __mistrimulti_ranch_do_move(rc, d) {
    if (!__mistrimulti_ranch_int(d[$ "i"], 0, MISTRIMULTI_RANCH_I32) || !__mistrimulti_ranch_text(d[$ "b"], 24)) return __mistrimulti_ranch_no("bad_request");
    var a = find_animal(d.i, false);
    var to = __mistrimulti_ranch_stable_by_id(d.b);
    if (a == undefined || a.stable == undefined || to == undefined) return __mistrimulti_ranch_no("gone");
    if (a.stable == to.stable) return { ok: true };
    if (to.prototype.permitted_animal_size != a.prototype.core.size || to.stable.availability() < 1 || !__mistrimulti_ranch_free_stall(to.stable)) return __mistrimulti_ranch_no("no_room");
    var from = a.stable.building;
    a.ate_breeding_treat = false;
    a.breeding_with = undefined;
    a.stable.deregister(a);
    to.stable.register(a);
    __mistrimulti_ranch_publish(rc, from, -1, 0);
    __mistrimulti_ranch_publish(rc, to, -1, 0);
    return { ok: true };
}

// Everything waiting in a barn goes to the first player who asks, once.
function __mistrimulti_ranch_do_collect(rc, d, from) {
    if (!__mistrimulti_ranch_text(d[$ "b"], 24)) return __mistrimulti_ranch_no("bad_request");
    var b = __mistrimulti_ranch_stable_by_id(d.b);
    if (b == undefined) return __mistrimulti_ranch_no("gone");
    if (!__mistrimulti_ranch_here(from, b.prototype.location_id, b.dyn_index)) return __mistrimulti_ranch_no("not_here");
    var items = rc.pool[$ d.b];
    if (!is_array(items) || array_length(items) == 0) return __mistrimulti_ranch_no("empty");
    rc.pool[$ d.b] = [];
    __mistrimulti_ranch_publish(rc, b, -1, 0);
    return { ok: true, items: items };
}

// ---- guest: asking, answers, watching ------------------------------------------------------------------

// key "" asks every time; otherwise one request per key at a time. Returns the id, "" for a duplicate,
// or undefined when the layer cannot take it now (the caller tries again later).
function __mistrimulti_ranch_ask(rc, key, data, extra) {
    if (key != "" && struct_exists(rc.inflight, key)) return "";
    var rid = mistrimulti_event_request("ranch_act", data);
    if (rid == undefined) return undefined;
    extra.a = data.a;
    extra.key = key;
    rc.pending[$ rid] = extra;
    if (key != "") rc.inflight[$ key] = rid;
    return rid;
}

// A paid request: one at a time, nothing is taken from the player until the host says yes.
function __mistrimulti_ranch_ask_paid(rc, data, extra) {
    if (rc.busy != "") {
        __mistrimulti_ranch_say("Still waiting for the host.");
        return false;
    }
    var rid = __mistrimulti_ranch_ask(rc, "", data, extra);
    if (!is_string(rid) || rid == "") {
        __mistrimulti_ranch_say("The host is busy. Try again in a moment.");
        return false;
    }
    rc.busy = rid;
    rc.busy_until = rc.n + MISTRIMULTI_RANCH_WAIT_TICKS;
    return true;
}

function __mistrimulti_ranch_charge(pay) {
    if (!is_struct(pay)) return true;
    var ok = true;
    var its = pay[$ "it"];
    if (is_array(its)) {
        for (var i = 0; i < array_length(its); i++) {
            var e = its[i];
            if (!is_struct(e) || !is_real(e[$ "i"]) || !is_real(e[$ "n"])) continue;
            var have = ARI.inventory.item_id_quantity(e.i);
            if (have < e.n) ok = false;
            ARI.inventory.remove(e.i, min(have, e.n));
        }
    }
    var g = pay[$ "g"];
    if (is_real(g) && g > 0) {
        if (ARI.get_gold() < g) ok = false;
        ARI.modify_gold(-g);
    }
    return ok;
}

function __mistrimulti_ranch_give(pay) {
    if (!is_struct(pay)) return;
    var its = pay[$ "it"];
    if (is_array(its)) {
        for (var i = 0; i < array_length(its); i++) {
            if (is_struct(its[i])) ARI.give_item(its[i].i, its[i].n);
        }
    }
    var g = pay[$ "g"];
    if (is_real(g) && g > 0) ARI.modify_gold(g);
}

function __mistrimulti_ranch_why(why) {
    if (why == "already") return "Someone already did that.";
    if (why == "gone") return "That is not there any more.";
    if (why == "no_room") return "There is no room for that.";
    if (why == "blocked") return "Something is in the way.";
    if (why == "full") return "That is full.";
    if (why == "empty") return "";
    if (why == "not_here") return "You are not close enough.";
    if (why == "pregnant") return "That animal is expecting.";
    if (why == "hearts") return "That animal needs more hearts first.";
    if (why == "taken") return "Another animal already took a treat.";
    return "The host did not accept that.";
}

// on_reply: the one place a guest pays or is made whole. The layer calls it once per request id.
function mistrimulti_ranch_reply(zero, result, ctx) {
    var rc = __mistrimulti_ranch();
    var p = rc.pending[$ ctx.id];
    if (!is_struct(p)) return true;
    struct_remove(rc.pending, ctx.id);
    if (p.key != "") struct_remove(rc.inflight, p.key);
    if (rc.busy == ctx.id) rc.busy = "";
    if (ctx.lost || ctx.expired || !is_struct(result)) {
        // The host restarted or forgot the answer: nothing was charged. A sale is decided by the next snapshot.
        if (p.a == "sell") array_push(rc.unresolved, { i: p.i, g: p.g });
        else __mistrimulti_ranch_say("The host did not confirm that.");
        mistrimulti_event_emit("ranch_resync", {}, 0);
        return true;
    }
    if (p.a == "sell") struct_remove(rc.known, string(p.i));      // answered: the animal is not ours to watch any more
    if (p.a == "world" && is_struct(rc.world_known)) rc.world_known[$ p.w] = p.v;       // answered: not a difference to report again
    if (result[$ "ok"] != true) {
        // Refused: put back what the game already took, or take back what it already gave.
        if (p.a == "sell") ARI.modify_gold(-p.g);
        else if (is_struct(p[$ "give"])) __mistrimulti_ranch_give(p.give);
        var text = __mistrimulti_ranch_why(result[$ "why"]);
        if (text != "" && p.a != "pet" && p.a != "rename" && p.a != "move") __mistrimulti_ranch_say(text);
        return true;
    }
    if (p.a == "sell") {
        if (is_real(result[$ "val"]) && result.val != p.g) ARI.modify_gold(result.val - p.g);
        return true;
    }
    if (is_struct(result[$ "pay"])) {
        if (!__mistrimulti_ranch_charge(result.pay)) __mistrimulti_ranch_say("You no longer had everything for that.");
        rc.charged++;
    }
    __mistrimulti_ranch_reply_effects(rc, p, result);
    return true;
}

function __mistrimulti_ranch_reply_effects(rc, p, result) {
    if (result[$ "xp"] == true) ARI.gain_xp(Skill.Ranching, ANIMAL_XP.feed);
    if (p.a == "treat") __mistrimulti_ranch_say("The animal took the treat.");
    if (p.a == "adopt") {
        ARI.animal_variant_unlocks[p.kind].insert(p.variant);
        var cosmetic = ANIMAL_PROTOTYPES[p.kind].variants.get(p.variant).default_cosmetic;
        if (cosmetic != undefined) ARI.animal_cosmetic_unlocks[p.kind].insert(cosmetic);
    }
    var items = result[$ "items"];
    if (is_array(items)) {
        for (var i = 0; i < array_length(items); i++) {
            var e = items[i];
            if (is_struct(e) && __mistrimulti_ranch_int(e[$ "i"], 0, ItemId.LEN - 1) && __mistrimulti_ranch_int(e[$ "n"], 1, 999)) ARI.give_item(e.i, e.n);
        }
    }
    var back = result[$ "ret"];
    if (__mistrimulti_ranch_int(back, 0, ItemId.LEN - 1)) ARI.give_item(back, 1);
}

// on_result: runs on every guest, including the requester. Placements arrive this way.
function mistrimulti_ranch_result(zero, result, ctx) {
    if (!is_struct(result) || result[$ "ok"] != true) return true;
    var rc = __mistrimulti_ranch();
    if (result[$ "a"] == "place") __mistrimulti_ranch_apply_placement(rc, result[$ "rec"]);
    return true;
}

// Reported actions: the game did them locally; tell the host. Runs a few times a second on guests.
function __mistrimulti_ranch_watch_animals(rc) {
    if (!rc.synced) return;
    var seen = {};
    var all = __mistrimulti_ranch_stables();
    for (var i = 0; i < array_length(all); i++) {
        var bid = __mistrimulti_ranch_bid(all[i]);
        var list = __mistrimulti_ranch_stalls(all[i].stable);
        for (var j = 0; j < array_length(list); j++) {
            var a = list[j];
            var key = string(a.idx);
            seen[$ key] = true;
            var k = rc.known[$ key];
            if (!is_struct(k)) continue;
            if (a.has_been_pat == true && !k.p) __mistrimulti_ranch_ask(rc, "pet:" + key, { a: "pet", i: a.idx }, {});
            else if (a.name != k.n && string_length(a.name) >= 1 && string_length(a.name) <= MISTRIMULTI_RANCH_NAME_MAX) __mistrimulti_ranch_ask(rc, "rename:" + key, { a: "rename", i: a.idx, n: a.name }, {});
            else if (bid != k.b) __mistrimulti_ranch_ask(rc, "move:" + key, { a: "move", i: a.idx, b: bid }, {});
        }
    }
    var names = struct_get_names(rc.known);
    for (var m = 0; m < array_length(names); m++) {
        if (struct_exists(seen, names[m]) || struct_exists(rc.inflight, "sell:" + names[m])) continue;
        var was = rc.known[$ names[m]];
        var id = real(names[m]);
        if (find_animal(id, true) != undefined) continue;
        // Gone from every barn and not in the daycare: the player sold it. The game already paid.
        __mistrimulti_ranch_ask(rc, "sell:" + names[m], { a: "sell", i: id }, { i: id, g: was.v });
    }
    if (PET.unlocked() && PET.has_been_pat == true && !rc.pet_known) __mistrimulti_ranch_ask(rc, "pet:-1", { a: "pet", i: PET_ID }, {});
}

// ---- hooks ---------------------------------------------------------------------------------------------

// Day-change work (production, hearts, breeding) is the host's; a guest's copy takes the result instead.
function mistrimulti_ranch_production_gate(value, ctx) {
    if (__mistrimulti_ranch_on("join")) return false;
    return undefined;
}

// With players connected the host's products wait in the barn's pool and go to whoever collects them.
function mistrimulti_ranch_product_drops(value, ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || r.mode != "host" || r.mask == 0 || !is_struct(value)) return undefined;
    try {
        var rc = __mistrimulti_ranch();
        var bid = __mistrimulti_ranch_bid(ctx.stable.building);
        var ids = [];
        var lists = [value.normal_products, value.golden_products];
        for (var l = 0; l < 2; l++) {
            for (var i = 0; i < lists[l].count(); i++) array_push(ids, lists[l].get(i).item_id);
        }
        lists[0].clear();
        lists[1].clear();
        for (var j = 0; j < array_length(ids); j++) __mistrimulti_ranch_pool_add(rc, bid, ids[j], 1);
    } catch (e) {
        __mistrimulti_ranch_warn("Products could not be pooled: " + string(e));
    }
    return undefined;
}

function __mistrimulti_ranch_pool_add(rc, bid, item_id, count) {
    var list = rc.pool[$ bid];
    if (!is_array(list)) {
        list = [];
        rc.pool[$ bid] = list;
    }
    for (var i = 0; i < array_length(list); i++) {
        if (list[i].i == item_id) {
            list[i].n = min(list[i].n + count, 999);
            return;
        }
    }
    if (array_length(list) < 16) array_push(list, { i: item_id, n: count });
}

// The host sends everything again after its own day change. A guest runs the same day change on its copy
// and asks for the host's version of the result.
function mistrimulti_ranch_new_day(ctx) {
    var rc = __mistrimulti_ranch();
    if (__mistrimulti_ranch_on("host")) {
        rc.sent = {};
        rc.wsent = "";
    } else if (__mistrimulti_ranch_on("join")) {
        mistrimulti_event_emit("ranch_resync", {}, 0);
    }
}

// Guests act through the host. The press is dropped here; the item stays in hand until the host agrees.
function mistrimulti_ranch_take_press(ctx) {
    if (!__mistrimulti_ranch_on("join")) return undefined;
    var key = ctx.local_key;
    if (key != "misc_local/feed" && key != "misc_local/place_animal_feed" && key != "misc_local/give_item") return undefined;
    var rc = __mistrimulti_ranch();
    if (rc.applying > 0) return undefined;
    if (!rc.synced) {
        __mistrimulti_ranch_say("Waiting for the host.");
        return false;
    }
    try {
        if (key == "misc_local/feed") return __mistrimulti_ranch_press_feed(rc, ctx.subject);
        if (key == "misc_local/place_animal_feed") return __mistrimulti_ranch_press_manger(rc, ctx.subject);
        return __mistrimulti_ranch_press_give(rc, ctx.subject);
    } catch (e) {
        __mistrimulti_ranch_warn("A press could not be shared: " + string(e));
    }
    return undefined;
}

function __mistrimulti_ranch_press_feed(rc, subject) {
    var me = subject[$ "me"];
    var item = ARI.held_item();
    if (!is_struct(me) || item == undefined) return undefined;
    var treat = !__mistrimulti_ranch_is_pet(me) && item.item_id == me.prototype.breeding.treat;
    __mistrimulti_ranch_ask_paid(rc, { a: treat ? "treat" : "feed", i: me.idx, it: item.item_id }, {});
    return false;
}

function __mistrimulti_ranch_press_manger(rc, subject) {
    var item = ARI.held_item();
    var b = __mistrimulti_ranch_stable_by_dyn(GRID.dyn_index);
    if (item == undefined || b == undefined) return undefined;
    __mistrimulti_ranch_ask_paid(rc, { a: "manger", b: __mistrimulti_ranch_bid(b), sd: subject[$ "left"] == true ? 0 : 1, it: item.item_id }, {});
    return false;
}

function __mistrimulti_ranch_press_give(rc, subject) {
    var node = subject[$ "node"];
    var item = ARI.held_item();
    if (!is_struct(node) || item == undefined) return undefined;
    __mistrimulti_ranch_ask_paid(rc, { a: "fgive", l: node.parent_grid.location_id, x: node.top_left_x, y: node.top_left_y, it: item.item_id }, {});
    return false;
}

// Adoption: the menu's own purchase method is replaced on guests (see ui.menu_opened).
function mistrimulti_ranch_menu_opened(ctx) {
    if (!__mistrimulti_ranch_on("join") || ctx.kind != Menu.Adoption) return;
    try { ctx.menu.adopt_animal_to_building = mistrimulti_ranch_adopt_wrapper; }
    catch (e) { __mistrimulti_ranch_warn("The adoption menu could not be shared: " + string(e)); }
}

function mistrimulti_ranch_adopt_wrapper(building_idx, animal_kind, sex, variant, cost, name) {
    var rc = __mistrimulti_ranch();
    var b = __mistrimulti_ranch_stable_by_dyn(building_idx);
    if (b == undefined || !is_string(name)) return;
    __mistrimulti_ranch_ask_paid(rc, { a: "adopt", k: animal_kind, v: variant, s: sex, n: string_copy(name, 1, MISTRIMULTI_RANCH_NAME_MAX),
        b: __mistrimulti_ranch_bid(b) }, { kind: animal_kind, variant: variant });
}

// The building site needs the host to finish it (its materials are the host's to count).
function mistrimulti_ranch_object_interact(node) {
    if (!__mistrimulti_ranch_on("join")) return undefined;
    if (node.object_id != ObjectId.StableCraftingTable) return undefined;
    __mistrimulti_ranch_say("Ask the host to finish this building.");
    return true;
}

// Walking into a barn collects what its animals made (guests and host alike; the host decides who is first).
function __mistrimulti_ranch_collect_tick(rc) {
    if (rc.n mod 10 != 0 || rc.busy != "" || GRID == undefined || GRID.dyn_index == undefined) return;
    var b = __mistrimulti_ranch_stable_by_dyn(GRID.dyn_index);
    if (b == undefined) return;
    var bid = __mistrimulti_ranch_bid(b);
    var items = rc.pool[$ bid];
    if (!is_array(items) || array_length(items) == 0) return;
    __mistrimulti_ranch_ask(rc, "collect:" + bid, { a: "collect", b: bid }, {});
}

// The product pool is part of the host's world, so it is saved beside it and read back with the same day.
function mistrimulti_ranch_save_guard(ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || r.mode != "host" || r.world_path == "") return undefined;
    try { save_text_file(r.world_path + "/ranch.json", json_stringify({ v: 1, day: total_days(), pool: __mistrimulti_ranch().pool })); }
    catch (e) { __mistrimulti_ranch_warn("The barn products could not be saved."); }
    return undefined;
}

function __mistrimulti_ranch_pool_load(rc) {
    var r = __mistrimulti_runtime();
    rc.pool_loaded = true;
    var path = r.world_path + "/ranch.json";
    if (!file_exists(path)) return;
    var data = try_read_json_file(path);
    if (!is_struct(data) || data[$ "v"] != 1 || data[$ "day"] != total_days() || !is_struct(data[$ "pool"])) return;
    var names = struct_get_names(data.pool);
    for (var i = 0; i < array_length(names); i++) {
        var list = data.pool[$ names[i]];
        if (!is_array(list)) continue;
        for (var j = 0; j < array_length(list); j++) {
            var e = list[j];
            if (is_struct(e) && __mistrimulti_ranch_int(e[$ "i"], 0, ItemId.LEN - 1) && __mistrimulti_ranch_int(e[$ "n"], 1, 999)) __mistrimulti_ranch_pool_add(rc, names[i], e.i, e.n);
        }
    }
}

// ---- placed structures: furniture, blueprints, floors, wallpapers, buildings ------------------------------

// items.use_guard sees the item; furniture.place_guard sees where it goes. Both run in the same frame.
function mistrimulti_ranch_use_guard(item) {
    var r = __mistrimulti_runtime();
    if (!r.enabled) return undefined;
    var rc = __mistrimulti_ranch();
    if (rc.applying > 0 || !is_struct(item[$ "prototype"])) return undefined;
    var use = item.prototype.use;
    if (use != ItemUse.PlaceObject && use != ItemUse.Blueprint && use != ItemUse.Flooring && use != ItemUse.Wallpaper) return undefined;
    try {
        if (use == ItemUse.PlaceObject) {
            rc.use = { t: r.ticks, item: item };
            return undefined;
        }
        if (r.mode == "join") return __mistrimulti_ranch_use_remote(rc, item, use);
        if (use == ItemUse.Blueprint) __mistrimulti_ranch_watch_blueprint(rc, item);
    } catch (e) {
        __mistrimulti_ranch_warn("An item use could not be shared: " + string(e));
    }
    return undefined;
}

function __mistrimulti_ranch_cell() {
    var ari = instance_find(obj_ari, 0);
    return ari.cell_select;
}

// Guest: blueprints and floor/wallpaper items are placed by the host.
function __mistrimulti_ranch_use_remote(rc, item, use) {
    if (!rc.synced) {
        __mistrimulti_ranch_say("Waiting for the host.");
        return false;
    }
    var data = undefined;
    if (use == ItemUse.Blueprint) {
        if (CURRENT_LOCATION_ID != LocationId.Farm) return undefined;
        var cell = __mistrimulti_ranch_cell();
        data = { a: "place", t: "b", l: CURRENT_LOCATION_ID, x: (cell.x div 2) * 2, y: (cell.y div 2) * 2,
            bp: item.prototype.blueprint.blueprint, it: item.item_id };
    } else if (is_home_location(CURRENT_LOCATION_ID)) {
        data = { a: "place", t: use == ItemUse.Flooring ? "fl" : "wp", l: CURRENT_LOCATION_ID, it: item.item_id };
    } else {
        return undefined;
    }
    __mistrimulti_ranch_ask_paid(rc, data, {});
    return false;
}

// Guest: furniture. Host: remember the placement to announce it once the game has accepted it.
function mistrimulti_ranch_place_guard(ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || ctx.stack_count > 0) return undefined;
    var rc = __mistrimulti_ranch();
    var use = rc.use;
    if (rc.applying > 0 || use == undefined || use.t != r.ticks) return undefined;
    rc.use = undefined;
    if (ctx.proto.object_id != use.item.prototype.object) return undefined;
    try {
        if (r.mode == "join") {
            var grid = ctx.grid;
            if (!rc.synced || GRIDS[grid.location_id] != grid) {
                __mistrimulti_ranch_say(rc.synced ? "Furniture can only be placed in the farm and the house in multiplayer." : "Waiting for the host.");
                return false;
            }
            var inf = try_infusion_to_string(use.item.infusion) ?? "";
            __mistrimulti_ranch_ask_paid(rc, { a: "place", t: "f", l: grid.location_id, x: ctx.x, y: ctx.y,
                o: ctx.proto.object_id, r: ctx.rotation, it: use.item.item_id, inf: inf }, {});
            return false;
        }
        if (r.mode == "host" && GRIDS[ctx.grid.location_id] == ctx.grid) {
            array_push(rc.watch, { t: "f", l: ctx.grid.location_id, x: ctx.x, y: ctx.y, o: ctx.proto.object_id, r: ctx.rotation,
                count: __mistrimulti_ranch_placed_count(ctx.proto.object_id), until: rc.n + 40 });
        }
    } catch (e) {
        __mistrimulti_ranch_warn("A placement could not be shared: " + string(e));
    }
    return undefined;
}

function __mistrimulti_ranch_placed_count(object_id) {
    return GAME_STATS.furniture_placed[$ object_id_to_string(object_id)] ?? 0;
}

function __mistrimulti_ranch_watch_blueprint(rc, item) {
    var cell = __mistrimulti_ranch_cell();
    array_push(rc.watch, { t: "b", l: LocationId.Farm, x: (cell.x div 2) * 2, y: (cell.y div 2) * 2,
        bp: item.prototype.blueprint.blueprint, it: item.item_id, until: rc.n + 40 });
}

// The nearest node of this object next to where it was placed that no ledger entry owns yet.
function __mistrimulti_ranch_find_new(rc, grid, w) {
    for (var dx = -4; dx <= 4; dx++) {
        for (var dy = -4; dy <= 4; dy++) {
            var ni = grid.try_node_index_for_cell(w.x + dx, w.y + dy);
            if (ni == undefined || grid.node_object_id[ni] != w.o) continue;
            var node = grid.node_parent[ni];
            var known = false;
            for (var i = 0; i < array_length(rc.led); i++) if (rc.led[i].node == node) known = true;
            if (!known) return node;
        }
    }
    return undefined;
}

// The first node of a blueprint site at x,y (the pieces carry the blueprint's id and corner).
function __mistrimulti_ranch_find_site(grid, x, y, bp) {
    var size = BLUEPRINT_PROTOTYPES[bp].size;
    for (var dx = 0; dx < size.x; dx++) {
        for (var dy = 0; dy < size.y; dy++) {
            var ni = grid.try_node_index_for_cell(x + dx, y + dy);
            if (ni == undefined || grid.node_object_id[ni] == undefined) continue;
            var node = grid.node_parent[ni];
            if (node[$ "blueprint_id"] == bp && node[$ "blueprint_top_left_x"] == x && node[$ "blueprint_top_left_y"] == y) return node;
        }
    }
    return undefined;
}

function __mistrimulti_ranch_ledger_add(rc, grid, rec, node) {
    if (array_length(rc.led) >= MISTRIMULTI_RANCH_LEDGER_MAX) array_delete(rc.led, 0, 1);
    array_push(rc.led, { rec: rec, node: node, grid: grid });
}

// Host: confirm and announce its own placements.
function __mistrimulti_ranch_watch_own(rc) {
    for (var i = array_length(rc.watch) - 1; i >= 0; i--) {
        var w = rc.watch[i];
        var grid = GRIDS[w.l];
        var done = false;
        if (w.t == "f" && __mistrimulti_ranch_placed_count(w.o) > w.count) {
            var node = __mistrimulti_ranch_find_new(rc, grid, w);
            done = true;
            if (node != undefined) {
                var rec = { k: "f", l: w.l, x: w.x, y: w.y, o: w.o, r: w.r, inf: node[$ "infusion"] ?? "" };
                __mistrimulti_ranch_ledger_add(rc, grid, rec, node);
                __mistrimulti_ranch_send("ranch_struct", { add: [rec] }, -1);
            }
        } else if (w.t == "b") {
            var site = __mistrimulti_ranch_find_site(grid, w.x, w.y, w.bp);
            if (site != undefined) {
                done = true;
                var brec = { k: "b", l: w.l, x: w.x, y: w.y, bp: w.bp, it: w.it };
                __mistrimulti_ranch_ledger_add(rc, grid, brec, site);
                __mistrimulti_ranch_send("ranch_struct", { add: [brec] }, -1);
            }
        }
        if (done || rc.n > w.until) array_delete(rc.watch, i, 1);
    }
}

function __mistrimulti_ranch_node_alive(e) {
    var ni = e.grid.try_node_index_for_cell(e.node.top_left_x, e.node.top_left_y);
    return ni != undefined && e.grid.node_parent[ni] == e.node;
}

// Host: placements that no longer exist are removed from the ledger and from the guests.
function __mistrimulti_ranch_ledger_check(rc) {
    var gone = [];
    for (var i = array_length(rc.led) - 1; i >= 0; i--) {
        if (__mistrimulti_ranch_node_alive(rc.led[i])) continue;
        var rec = rc.led[i].rec;
        array_push(gone, { k: rec.k, l: rec.l, x: rec.x, y: rec.y, o: rec[$ "o"] ?? -1, bp: rec[$ "bp"] ?? -1,
            tx: rc.led[i].node.top_left_x, ty: rc.led[i].node.top_left_y });
        array_delete(rc.led, i, 1);
    }
    if (array_length(gone) > 0) __mistrimulti_ranch_send("ranch_struct", { del: gone }, -1);
}

function __mistrimulti_ranch_rec_valid(rec) {
    if (!is_struct(rec) || !is_string(rec[$ "k"])) return false;
    if (!__mistrimulti_ranch_int(rec[$ "l"], 0, LocationId.LEN - 1) || GRIDS[rec.l] == undefined) return false;
    var grid = GRIDS[rec.l];
    if (!__mistrimulti_ranch_int(rec[$ "x"], 0, grid.dims.x - 1) || !__mistrimulti_ranch_int(rec[$ "y"], 0, grid.dims.y - 1)) return false;
    if (rec.k == "f") {
        return __mistrimulti_ranch_int(rec[$ "o"], 0, ObjectId.LEN - 1) && object_id_to_object_category(rec.o) == ObjectCategory.Furniture
            && __mistrimulti_ranch_int(rec[$ "r"], -64, 64) && __mistrimulti_ranch_text(rec[$ "inf"], 48);
    }
    if (rec.k == "b") return __mistrimulti_ranch_int(rec[$ "bp"], 0, Blueprint.LEN - 1) && __mistrimulti_ranch_int(rec[$ "it"], 0, ItemId.LEN - 1);
    return false;
}

// Guests (and the host's own reply path never reaches here): place what the host placed.
function __mistrimulti_ranch_apply_placement(rc, rec) {
    if (!__mistrimulti_ranch_on("join") || !is_struct(rec)) return;
    if (rec[$ "k"] == "fl" || rec[$ "k"] == "wp") {
        // A floor or wallpaper: the world record repeats it, this makes it appear at once.
        if (__mistrimulti_ranch_int(rec[$ "l"], 0, LocationId.LEN - 1) && __mistrimulti_ranch_text(rec[$ "nm"], 48)) {
            rc.applying++;
            try { __mistrimulti_ranch_set_decor(rec.l, rec.k == "fl", rec.nm); }
            catch (e) { __mistrimulti_ranch_warn("A shared floor could not be applied: " + string(e)); }
            rc.applying--;
        }
        return;
    }
    if (!__mistrimulti_ranch_rec_valid(rec)) return;
    if (!__mistrimulti_ranch_place_local(rec) && array_length(rc.retry) < 64) array_push(rc.retry, { rec: rec, until: rc.n + 600 });
}

function __mistrimulti_ranch_place_local(rec) {
    var rc = __mistrimulti_ranch();
    var grid = GRIDS[rec.l];
    var ok = false;
    rc.applying++;
    try {
        if (rec.k == "f") {
            var node = grid.write_node(rec.x, rec.y, rec.o, rec.r);
            if (node != undefined) {
                node.infusion = rec.inf == "" ? undefined : rec.inf;
                array_push(rc.applied, { rec: rec, node: node, grid: grid });
                ok = true;
            } else {
                // Already there (a snapshot after a placement we saw) counts as placed.
                var ni = grid.try_node_index_for_cell(rec.x, rec.y);
                ok = ni != undefined && grid.node_object_id[ni] == rec.o;
            }
        } else {
            ok = __mistrimulti_ranch_find_site(grid, rec.x, rec.y, rec.bp) != undefined;
            if (!ok && write_blueprint_to_location(grid, rec.x, rec.y, rec.bp, item_id_to_string(rec.it))) {
                array_push(rc.applied, { rec: rec, node: __mistrimulti_ranch_find_site(grid, rec.x, rec.y, rec.bp), grid: grid });
                ok = true;
            }
        }
    } catch (e) {
        __mistrimulti_ranch_warn("A shared placement failed: " + string(e));
        ok = true;       // do not retry a placement that throws
    }
    rc.applying--;
    return ok;
}

// The host restarted from its save: what it placed in the previous session is not in the new one. The
// placements this guest applied for it are taken back (the new host sends the ones that survived, if any).
function __mistrimulti_ranch_revert_applied(rc) {
    rc.applying++;
    try {
        for (var i = array_length(rc.applied) - 1; i >= 0; i--) {
            var e = rc.applied[i];
            if (e.node == undefined || !__mistrimulti_ranch_node_alive(e)) continue;
            if (e.rec.k == "f") erase_object_node(e.grid, e.grid.try_node_index_for_cell(e.node.top_left_x, e.node.top_left_y));
            else remove_blueprint_from_location(e.grid, e.rec.x, e.rec.y, e.rec.bp);
        }
    } catch (err) {
        __mistrimulti_ranch_warn("Shared placements could not be taken back: " + string(err));
    }
    rc.applying--;
    rc.applied = [];
}

function __mistrimulti_ranch_remove_local(rec) {
    var rc = __mistrimulti_ranch();
    if (!is_struct(rec) || !__mistrimulti_ranch_int(rec[$ "l"], 0, LocationId.LEN - 1) || GRIDS[rec.l] == undefined) return;
    var grid = GRIDS[rec.l];
    if (!__mistrimulti_ranch_int(rec[$ "tx"], 0, grid.dims.x - 1) || !__mistrimulti_ranch_int(rec[$ "ty"], 0, grid.dims.y - 1)) return;
    rc.applying++;
    try {
        if (rec.k == "f") {
            var ni = grid.try_node_index_for_cell(rec.tx, rec.ty);
            if (ni != undefined && grid.node_object_id[ni] == rec[$ "o"]) erase_object_node(grid, ni);
        } else if (rec.k == "b" && __mistrimulti_ranch_int(rec[$ "bp"], 0, Blueprint.LEN - 1)) {
            // Only while the site is still a site: a finished building stands on the same cells.
            if (__mistrimulti_ranch_find_site(grid, rec.x, rec.y, rec.bp) != undefined) remove_blueprint_from_location(grid, rec.x, rec.y, rec.bp);
        }
    } catch (e) {
        __mistrimulti_ranch_warn("A shared removal failed: " + string(e));
    }
    rc.applying--;
}

// A building the host finished: take its blueprint site away and build it where the host did.
function __mistrimulti_ranch_build_local(rec) {
    var rc = __mistrimulti_ranch();
    if (!is_struct(rec) || !__mistrimulti_ranch_int(rec[$ "o"], 0, ObjectId.LEN - 1) || object_id_to_object_category(rec.o) != ObjectCategory.Building) return true;
    var farm = GRIDS[LocationId.Farm];
    if (!__mistrimulti_ranch_int(rec[$ "x"], 0, farm.dims.x - 1) || !__mistrimulti_ranch_int(rec[$ "y"], 0, farm.dims.y - 1)) return true;
    if (!__mistrimulti_ranch_int(rec[$ "vr"], 0, 16) || !__mistrimulti_ranch_text(rec[$ "n"], 64)) return true;
    var all = get_buildings();
    for (var i = 0; i < all.count(); i++) {
        if (all.get(i).top_left_x == rec.x && all.get(i).top_left_y == rec.y) return true;
    }
    var ok = false;
    rc.applying++;
    try {
        var size = NODE_PROTOTYPES[rec.o].size;
        for (var dx = 0; dx < size.x; dx++) {
            for (var dy = 0; dy < size.y; dy++) {
                var ni = farm.try_node_index_for_cell(rec.x + dx, rec.y + dy);
                if (ni == undefined || farm.node_object_id[ni] == undefined) continue;
                var piece = farm.node_parent[ni];
                if (is_real(piece[$ "blueprint_id"])) {
                    remove_blueprint_from_location(farm, piece.blueprint_top_left_x, piece.blueprint_top_left_y, piece.blueprint_id);
                    dx = size.x;
                    break;
                }
            }
        }
        var node = farm.write_node(rec.x, rec.y, rec.o, rec.vr);
        if (node != undefined) {
            node.name = rec.n;
            ok = true;
        }
    } catch (e) {
        __mistrimulti_ranch_warn("A shared building failed: " + string(e));
        ok = true;
    }
    rc.applying--;
    return ok;
}

function __mistrimulti_ranch_struct_message(rc, data) {
    if (!__mistrimulti_ranch_on("join") || !is_struct(data)) return;
    __mistrimulti_ranch_session(rc);
    var bld = data[$ "bld"];
    if (is_array(bld)) {
        for (var b = 0; b < min(array_length(bld), 64); b++) {
            if (!__mistrimulti_ranch_build_local(bld[b]) && array_length(rc.retry) < 64) array_push(rc.retry, { build: bld[b], until: rc.n + 600 });
        }
    }
    var add = data[$ "add"];
    if (is_array(add)) {
        for (var i = 0; i < min(array_length(add), MISTRIMULTI_RANCH_LEDGER_MAX); i++) __mistrimulti_ranch_apply_placement(rc, add[i]);
    }
    var del = data[$ "del"];
    if (is_array(del)) {
        for (var j = 0; j < min(array_length(del), 64); j++) __mistrimulti_ranch_remove_local(del[j]);
    }
}

function mistrimulti_ranch_struct_event(from, data, ctx) {
    if (from == 0) __mistrimulti_ranch_struct_message(__mistrimulti_ranch(), data);
    return true;
}

function mistrimulti_ranch_struct_blob(from, text, meta) {
    if (from != 0) return true;
    var data = undefined;
    try { data = json_parse(text); }
    catch (e) { __mistrimulti_ranch_warn("A shared placement list could not be read."); }
    __mistrimulti_ranch_struct_message(__mistrimulti_ranch(), data);
    return true;
}

function __mistrimulti_ranch_retry_tick(rc) {
    for (var i = array_length(rc.retry) - 1; i >= 0; i--) {
        var e = rc.retry[i];
        var done = rc.n > e.until;
        if (!done && is_struct(e[$ "rec"])) done = __mistrimulti_ranch_place_local(e.rec);
        else if (!done) done = __mistrimulti_ranch_build_local(e.build);
        if (done) array_delete(rc.retry, i, 1);
    }
}

// Host: place what a guest asked for, if the game accepts it exactly as it would from the host's own hand.
function __mistrimulti_ranch_do_place(rc, d, from) {
    var t = d[$ "t"];
    if (!__mistrimulti_ranch_int(d[$ "l"], 0, LocationId.LEN - 1) || GRIDS[d.l] == undefined || !__mistrimulti_ranch_int(d[$ "it"], 0, ItemId.LEN - 1)) return __mistrimulti_ranch_no("bad_request");
    if (!__mistrimulti_ranch_here(from, d.l, undefined)) return __mistrimulti_ranch_no("not_here");
    var grid = GRIDS[d.l];
    var proto = ITEM_PROTOTYPES[d.it];
    if (t == "f") {
        if (!__mistrimulti_ranch_int(d[$ "x"], 0, grid.dims.x - 1) || !__mistrimulti_ranch_int(d[$ "y"], 0, grid.dims.y - 1)) return __mistrimulti_ranch_no("bad_request");
        if (!__mistrimulti_ranch_int(d[$ "o"], 0, ObjectId.LEN - 1) || !__mistrimulti_ranch_int(d[$ "r"], -64, 64) || !__mistrimulti_ranch_text(d[$ "inf"], 48)) return __mistrimulti_ranch_no("bad_request");
        if (proto.use != ItemUse.PlaceObject || proto.object != d.o || object_id_to_object_category(d.o) != ObjectCategory.Furniture) return __mistrimulti_ranch_no("refused");
        if (!__mistrimulti_ranch_placeable(d.o, d.l)) return __mistrimulti_ranch_no("refused");
        rc.applying++;
        var node = grid.write_node(d.x, d.y, d.o, d.r);
        rc.applying--;
        if (node == undefined) return __mistrimulti_ranch_no("blocked");
        node.infusion = d.inf == "" ? undefined : d.inf;
        var rec = { k: "f", l: d.l, x: d.x, y: d.y, o: d.o, r: d.r, inf: d.inf };
        __mistrimulti_ranch_ledger_add(rc, grid, rec, node);
        return { ok: true, rec: rec, pay: __mistrimulti_ranch_pay_item(d.it) };
    }
    if (t == "b") {
        if (d.l != LocationId.Farm || proto.use != ItemUse.Blueprint || !__mistrimulti_ranch_int(d[$ "bp"], 0, Blueprint.LEN - 1) || proto.blueprint.blueprint != d.bp) return __mistrimulti_ranch_no("refused");
        if (!__mistrimulti_ranch_int(d[$ "x"], 0, grid.dims.x - 1) || !__mistrimulti_ranch_int(d[$ "y"], 0, grid.dims.y - 1)) return __mistrimulti_ranch_no("bad_request");
        rc.applying++;
        var placed = write_blueprint_to_location(grid, (d.x div 2) * 2, (d.y div 2) * 2, d.bp, item_id_to_string(d.it));
        rc.applying--;
        if (!placed) return __mistrimulti_ranch_no("blocked");
        var site = __mistrimulti_ranch_find_site(grid, (d.x div 2) * 2, (d.y div 2) * 2, d.bp);
        var brec = { k: "b", l: d.l, x: (d.x div 2) * 2, y: (d.y div 2) * 2, bp: d.bp, it: d.it };
        if (site != undefined) __mistrimulti_ranch_ledger_add(rc, grid, brec, site);
        return { ok: true, rec: brec, pay: __mistrimulti_ranch_pay_item(d.it) };
    }
    if (t == "fl" || t == "wp") return __mistrimulti_ranch_do_decor(rc, d, t, proto);
    return __mistrimulti_ranch_no("bad_request");
}

function __mistrimulti_ranch_placeable(object_id, loc) {
    var proto = NODE_PROTOTYPES[object_id];
    if (array_contains(proto.placeable_locations, loc)) return true;
    return proto.house_stairs != undefined && array_contains(NODE_PROTOTYPES[proto.house_stairs.paired_object].placeable_locations, loc);
}

// ---- the house: floors and wallpapers ---------------------------------------------------------------------

function __mistrimulti_ranch_item_with(field, name) {
    for (var i = 0; i < array_length(ITEM_PROTOTYPES); i++) {
        if (ITEM_PROTOTYPES[i][$ field] == name) return ITEM_PROTOTYPES[i];
    }
    return undefined;
}

// Sets a floor or wallpaper by name. The game edits the tilemaps of the room it is in, so any other room
// only gets its data changed (the room applies it when it is entered).
function __mistrimulti_ranch_set_decor(loc, floor_not_wall, name) {
    var key = location_id_to_string(loc);
    if (!is_home_location(loc) || !__mistrimulti_ranch_text(name, 48)) return;
    if (floor_not_wall) {
        if (DECOR.floorings[$ key].flooring == name) return;
        if (loc == CURRENT_LOCATION_ID) DECOR.apply_flooring(name, false, undefined);
        else DECOR.floorings[$ key] = { flooring: name, infusion: undefined };
    } else {
        if (DECOR.wallpapers[$ key].wallpaper == name) return;
        var item = __mistrimulti_ranch_item_with("wallpaper", name);
        var mold = item == undefined ? DECOR.wallpapers[$ key].door_mold_sprite : item.door_mold;
        if (loc == CURRENT_LOCATION_ID) DECOR.apply_wallpaper(name, mold, false, undefined);
        else DECOR.wallpapers[$ key] = { infusion: undefined, wallpaper: name, door_mold_sprite: mold };
    }
}

function __mistrimulti_ranch_do_decor(rc, d, t, proto) {
    var floor_not_wall = t == "fl";
    var name = floor_not_wall ? proto.flooring : proto.wallpaper;
    if (name == undefined || !is_home_location(d.l)) return __mistrimulti_ranch_no("refused");
    var key = location_id_to_string(d.l);
    var old = floor_not_wall ? DECOR.floorings[$ key].flooring : DECOR.wallpapers[$ key].wallpaper;
    if (old == name) return __mistrimulti_ranch_no("already");
    rc.applying++;
    __mistrimulti_ranch_set_decor(d.l, floor_not_wall, name);
    rc.applying--;
    var res = { ok: true, rec: { k: t, l: d.l, nm: name }, pay: __mistrimulti_ranch_pay_item(d.it) };
    // The covering that was there comes back to the player, like the game does.
    var back = __mistrimulti_ranch_item_with(floor_not_wall ? "flooring" : "wallpaper", old);
    if (back != undefined) res.ret = back.item_id;
    rc.wsent = "";
    return res;
}

// ---- machines (apiary, terrarium) -----------------------------------------------------------------------------

function __mistrimulti_ranch_do_factory(rc, d, from) {
    if (!__mistrimulti_ranch_int(d[$ "l"], 0, LocationId.LEN - 1) || GRIDS[d.l] == undefined || !__mistrimulti_ranch_int(d[$ "it"], 0, ItemId.LEN - 1)) return __mistrimulti_ranch_no("bad_request");
    if (!__mistrimulti_ranch_here(from, d.l, undefined)) return __mistrimulti_ranch_no("not_here");
    var grid = GRIDS[d.l];
    if (!__mistrimulti_ranch_int(d[$ "x"], 0, grid.dims.x - 1) || !__mistrimulti_ranch_int(d[$ "y"], 0, grid.dims.y - 1)) return __mistrimulti_ranch_no("bad_request");
    var ni = grid.try_node_index_for_cell(d.x, d.y);
    if (ni == undefined || grid.node_object_id[ni] == undefined) return __mistrimulti_ranch_no("gone");
    var node = grid.node_parent[ni];
    if (node.prototype.factory == undefined) return __mistrimulti_ranch_no("gone");
    if (node.production_request == undefined || node.production_request != d.it) return __mistrimulti_ranch_no("already");
    var rewards = node.prototype.factory.rewards_map[node.production_tier];
    var items = [{ i: rewards[irandom(array_length(rewards) - 1)], n: 1 }];
    if (node.prototype.object_id == ObjectId.Apiary && chance_percent(15)) array_push(items, { i: ItemId.Honeycomb, n: 1 });
    node.production_request = undefined;
    node.day_count = 0;
    if (node.renderer != undefined && instance_exists(node.renderer)) node.renderer.sprite_index = node.prototype.factory.bounce_sprite;
    rc.wsent = "";
    return { ok: true, items: items, pay: __mistrimulti_ranch_pay_item(d.it) };
}

// ---- the world record: expansion, house, floors, machines, pet ------------------------------------------------------

function __mistrimulti_ranch_world_record() {
    var rec = { fx: FARM_EXPANDED == true, hu: DECOR.size_upgrade, uf: DECOR.upper_floor == true, hv: DECOR.variant,
        dc: {}, fa: [], pet: { u: false } };
    for (var i = 0; i < LocationId.LEN; i++) {
        if (!is_home_location(i)) continue;
        var key = location_id_to_string(i);
        rec.dc[$ key] = [DECOR.floorings[$ key].flooring, DECOR.wallpapers[$ key].wallpaper];
    }
    for (var j = 0; j < min(FACTORIES.count(), 32); j++) {
        var f = FACTORIES.get(j);
        array_push(rec.fa, { l: f.parent_grid.location_id, x: f.top_left_x, y: f.top_left_y, q: f.production_request ?? -1,
            t: f.production_tier ?? -1, d: f.day_count });
    }
    if (PET.unlocked()) {
        rec.pet = { u: true, n: PET.name, h: PET.heart_points, e: PET.has_eaten == true, p: PET.has_been_pat == true };
    }
    return rec;
}

function __mistrimulti_ranch_world_valid(rec) {
    if (!is_struct(rec) || typeof(rec[$ "fx"]) != "bool" || typeof(rec[$ "uf"]) != "bool") return false;
    if (!__mistrimulti_ranch_int(rec[$ "hu"], 0, HomeUpgrade.LEN - 1) || !__mistrimulti_ranch_int(rec[$ "hv"], 0, HomeVariant.LEN - 1)) return false;
    if (!is_struct(rec[$ "dc"]) || !is_array(rec[$ "fa"]) || array_length(rec.fa) > 32 || !is_struct(rec[$ "pet"])) return false;
    var names = struct_get_names(rec.dc);
    if (array_length(names) > 16) return false;
    for (var i = 0; i < array_length(names); i++) {
        var pair = rec.dc[$ names[i]];
        if (!is_array(pair) || array_length(pair) != 2 || !__mistrimulti_ranch_text(pair[0], 48) || !__mistrimulti_ranch_text(pair[1], 48)) return false;
    }
    for (var j = 0; j < array_length(rec.fa); j++) {
        var f = rec.fa[j];
        if (!is_struct(f) || !__mistrimulti_ranch_int(f[$ "l"], 0, LocationId.LEN - 1) || !__mistrimulti_ranch_int(f[$ "x"], 0, 4096) || !__mistrimulti_ranch_int(f[$ "y"], 0, 4096)) return false;
        if (!__mistrimulti_ranch_int(f[$ "q"], -1, ItemId.LEN - 1) || !__mistrimulti_ranch_int(f[$ "t"], -1, FactoryTier.LEN - 1) || !__mistrimulti_ranch_int(f[$ "d"], 0, 1000)) return false;
    }
    if (rec.pet.u != true) return true;
    return __mistrimulti_ranch_text(rec.pet[$ "n"], MISTRIMULTI_RANCH_NAME_MAX) && is_real(rec.pet[$ "h"]) && rec.pet.h >= 0 && rec.pet.h <= 1000000
        && typeof(rec.pet[$ "e"]) == "bool" && typeof(rec.pet[$ "p"]) == "bool";
}

function __mistrimulti_ranch_apply_factories(fa) {
    for (var i = 0; i < array_length(fa); i++) {
        var f = fa[i];
        var grid = GRIDS[f.l];
        if (grid == undefined) continue;
        var ni = grid.try_node_index_for_cell(f.x, f.y);
        if (ni == undefined || grid.node_object_id[ni] == undefined) continue;
        var node = grid.node_parent[ni];
        if (node.prototype.factory == undefined) continue;
        node.production_request = f.q >= 0 ? f.q : undefined;
        node.production_tier = f.t >= 0 ? f.t : undefined;
        node.day_count = f.d;
    }
}

function __mistrimulti_ranch_apply_world(rc, rec) {
    rc.applying++;
    try {
        // Rooms that are open are rebuilt by the game when it enters them: wait until the player is elsewhere.
        var away = CURRENT_LOCATION_ID != LocationId.Farm && !is_home_location(CURRENT_LOCATION_ID);
        if (rec.fx && FARM_EXPANDED != true) {
            if (away) expand_farm();
            else rc.world_defer = rec;
        }
        if (rec.hu > DECOR.size_upgrade) {
            if (away) DECOR.apply_house_upgrade(GRIDS[LocationId.PlayerHome], rec.hu);
            else rc.world_defer = rec;
        }
        if (rec.uf && DECOR.upper_floor != true) DECOR.upper_floor = true;
        if (rec.hv != DECOR.variant) DECOR.variant = rec.hv;
        var names = struct_get_names(rec.dc);
        for (var i = 0; i < array_length(names); i++) {
            for (var loc = 0; loc < LocationId.LEN; loc++) {
                if (is_home_location(loc) && location_id_to_string(loc) == names[i]) {
                    __mistrimulti_ranch_set_decor(loc, true, rec.dc[$ names[i]][0]);
                    __mistrimulti_ranch_set_decor(loc, false, rec.dc[$ names[i]][1]);
                }
            }
        }
        __mistrimulti_ranch_apply_factories(rec.fa);
        if (rec.pet.u == true && PET.unlocked()) {
            PET.name = rec.pet.n;
            PET.heart_points = rec.pet.h;
            PET.has_eaten = rec.pet.e;
            PET.has_been_pat = rec.pet.p;
        }
        rc.pet_known = rec.pet.u == true && rec.pet.p;
        // What the host has, not what this game has: a purchase made here since is then still a difference.
        rc.world_known = { fx: rec.fx, hu: rec.hu, uf: rec.uf, hv: rec.hv };
    } catch (e) {
        __mistrimulti_ranch_warn("The shared farm and house could not be updated: " + string(e));
    }
    rc.applying--;
}

function __mistrimulti_ranch_world_message(rc, rec) {
    if (!__mistrimulti_ranch_on("join")) return;
    __mistrimulti_ranch_session(rc);
    if (!__mistrimulti_ranch_world_valid(rec)) {
        __mistrimulti_ranch_warn("A shared farm update was rejected.");
        return;
    }
    __mistrimulti_ranch_watch_world(rc);
    __mistrimulti_ranch_apply_world(rc, rec);
    if (rec[$ "fin"] == true && is_real(rec[$ "sid"]) && is_real(rec[$ "sn"])) {
        rc.fin = { sid: rec.sid, sn: rec.sn };
        __mistrimulti_ranch_check_sync(rc);
    }
}

function mistrimulti_ranch_world_event(from, data, ctx) {
    if (from == 0) __mistrimulti_ranch_world_message(__mistrimulti_ranch(), data);
    return true;
}

function mistrimulti_ranch_world_blob(from, text, meta) {
    if (from != 0) return true;
    var data = undefined;
    try { data = json_parse(text); }
    catch (e) { __mistrimulti_ranch_warn("A shared farm update could not be read."); }
    __mistrimulti_ranch_world_message(__mistrimulti_ranch(), data);
    return true;
}

// What the game charges for each one-time purchase, so a refusal can give it back.
function __mistrimulti_ranch_world_cost(field, value) {
    var cost = { g: 0, it: [] };
    var data = undefined;
    if (field == "fx") {
        cost.g = EXPANSION_COST.gold;
        for (var i = 0; i < EXPANSION_COST.items.count(); i++) array_push(cost.it, { i: EXPANSION_COST.items.get(i).item_id, n: EXPANSION_COST.items.get(i).count });
        return cost;
    }
    if (field == "hu") data = DECOR.sell_data[value];
    else if (field == "uf") data = DECOR.upper_floor_sell_data;
    if (field == "hv") {
        cost.g = fiddle_get("misc/home_variant_cost");
        return cost;
    }
    if (data == undefined) return cost;
    cost.g = data.gold_cost;
    for (var j = 0; j < data.requirements.count(); j++) array_push(cost.it, { i: data.requirements.get(j).item_id, n: data.requirements.get(j).quantity });
    return cost;
}

// Guest: a purchase made at the carpenter changed the farm or the house locally; ask the host to make it real.
function __mistrimulti_ranch_watch_world(rc) {
    var known = rc.world_known;
    if (!rc.synced || !is_struct(known) || rc.world_defer != undefined) return;
    var now = { fx: FARM_EXPANDED == true, hu: DECOR.size_upgrade, uf: DECOR.upper_floor == true, hv: DECOR.variant };
    var fields = ["fx", "hu", "uf", "hv"];
    for (var i = 0; i < 4; i++) {
        var f = fields[i];
        if (now[$ f] == known[$ f]) continue;
        var give = __mistrimulti_ranch_world_cost(f, now[$ f]);
        __mistrimulti_ranch_ask(rc, "world:" + f, { a: "world", w: f, v: now[$ f] }, { give: give, w: f, v: now[$ f] });
    }
}

// Host: accept the change only if it is the very next step of what the host has.
function __mistrimulti_ranch_do_world(rc, d) {
    var w = d[$ "w"];
    if (w == "fx") {
        if (FARM_EXPANDED == true) return __mistrimulti_ranch_no("already");
        expand_farm();
    } else if (w == "hu") {
        if (!__mistrimulti_ranch_int(d[$ "v"], 1, HomeUpgrade.LEN - 1) || d.v != DECOR.size_upgrade + 1) return __mistrimulti_ranch_no("already");
        DECOR.apply_house_upgrade(GRIDS[LocationId.PlayerHome], d.v);
    } else if (w == "uf") {
        if (DECOR.upper_floor == true || DECOR.size_upgrade != HomeUpgrade.LargeWestEast) return __mistrimulti_ranch_no("already");
        DECOR.upper_floor = true;
    } else if (w == "hv") {
        if (!__mistrimulti_ranch_int(d[$ "v"], 0, HomeVariant.LEN - 1) || d.v == DECOR.variant || DECOR.upper_floor != true) return __mistrimulti_ranch_no("already");
        DECOR.variant = d.v;
    } else {
        return __mistrimulti_ranch_no("bad_request");
    }
    rc.wsent = "";
    return { ok: true };
}

// ---- tick (20 Hz, called by the boot tick while a world is loaded) ------------------------------------------------------

function mistrimulti_ranch_tick() {
    var r = __mistrimulti_runtime();
    var rc = __mistrimulti_ranch();
    rc.n++;
    if (rc.busy != "" && rc.n > rc.busy_until) rc.busy = "";
    if (r.mode == "host") {
        __mistrimulti_ranch_host_tick(r, rc);
    } else if (r.mode == "join") {
        __mistrimulti_ranch_session(rc);
        __mistrimulti_ranch_resolve(rc);
        if (rc.n mod 10 == 0) __mistrimulti_ranch_watch_animals(rc);
        if (rc.n mod 20 == 3) __mistrimulti_ranch_watch_world(rc);
        if (rc.n mod 20 == 7) __mistrimulti_ranch_retry_tick(rc);
        if (rc.n mod 20 == 11) __mistrimulti_ranch_deferred_tick(rc);
    }
    if (rc.synced || r.mode == "host") __mistrimulti_ranch_collect_tick(rc);
}

function __mistrimulti_ranch_deferred_tick(rc) {
    var names = struct_get_names(rc.deferred);
    for (var i = 0; i < array_length(names); i++) {
        var rec = rc.deferred[$ names[i]];
        if (is_struct(rec)) __mistrimulti_ranch_apply_stable(rc, rec);
    }
    if (rc.world_defer != undefined) {
        var rec_w = rc.world_defer;
        rc.world_defer = undefined;
        __mistrimulti_ranch_apply_world(rc, rec_w);
    }
}
