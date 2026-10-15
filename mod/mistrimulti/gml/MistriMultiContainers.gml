// MistriaMulti containers: host-owned chests, fridges and shipping bins (the host sells the bins at the end of its day and the
// proceeds go to the shared wallet, MistriMultiWallet.gml). Protocol, assumptions and the in-game
// checklist: docs/SYNC-CONTAINERS.md. The world items that leave or enter containers are in MistriMultiDrops.gml.
//
// A container is a furniture node with an inventory. It has a key (room tree + position) and a revision number that
// only the host increases. The host's inventory is the truth. On a guest the same inventory is a replica that the
// game's own menus edit freely; every bridge tick this file compares each slot with the last authoritative state and
// sends the difference as ONE atomic request (per slot: remove N of item A, add M of item B). The host applies it
// exactly once, or refuses it when the slots no longer hold what the guest assumed. The result carries the
// authoritative slots; every game overwrites them (the menus refresh by themselves, they watch `slot.updates`), and a
// refused guest gives back whatever its menu moved.
//
// Kinds: chest_tx (request), chest_open (request), chest_state (host event), chest_snap (host event to one guest).
// A slot state is { it: item as LiveItem.serialize() or undefined, n: count }; the wire form is a "pack":
// t = the distinct items, s = [[slot, index into t or -1, count], ...].

#macro MISTRIMULTI_CT_CHESTS 256
#macro MISTRIMULTI_CT_SLOTS 128
#macro MISTRIMULTI_CT_OPS 128
#macro MISTRIMULTI_CT_PARTS 8
#macro MISTRIMULTI_CT_TABLE 64
#macro MISTRIMULTI_CT_COUNT 9999
#macro MISTRIMULTI_CT_TX_BYTES 6000
#macro MISTRIMULTI_CT_TX_LIMIT 6500
#macro MISTRIMULTI_CT_PACK_BYTES 5500
#macro MISTRIMULTI_CT_SCAN 24
#macro MISTRIMULTI_CT_INDEX_TICKS 100
#macro MISTRIMULTI_CT_OPEN_TICKS 100
#macro MISTRIMULTI_CT_HOT_TICKS 400
#macro MISTRIMULTI_CT_STREAM_EVENTS 2

function mistrimulti_containers_register_events() {
    mistrimulti_event_register("chest_tx", { on_request: mistrimulti_chest_tx_request, on_result: mistrimulti_chest_tx_result,
        on_reply: mistrimulti_chest_tx_reply });
    mistrimulti_event_register("chest_open", { on_request: mistrimulti_chest_open_request });
    mistrimulti_event_register("chest_state", { on_event: mistrimulti_chest_state_event, on_peer: mistrimulti_chest_peer,
        on_gap: mistrimulti_chest_gap });
    mistrimulti_event_register("chest_snap", { on_event: mistrimulti_chest_snap_event });
}

// ---- registry ------------------------------------------------------------------------------------------

// Per world session (the event stream changes when the game enters a world): the chests of this game.
function __mistrimulti_ct() {
    var r = __mistrimulti_runtime();
    var ct = r[$ "ct"];
    if (!is_struct(ct) || ct.stream != r.ev.stream) {
        ct = { stream: r.ev.stream, chests: {}, keys: [], count: -1, indexed: -100000, cursor: 0,
            txs: {}, owed: [], snaps: array_create(8, undefined) };
        r.ct = ct;
    }
    return ct;
}

// The same chest has the same key in every game: the root location, then the position (nested grids add a level).
function __mistrimulti_ct_locate(node) {
    var grid = node[$ "parent_grid"];
    if (grid == undefined) return undefined;
    var key = string(node.top_left_x) + "," + string(node.top_left_y);
    for (var depth = 0; depth < 4; depth++) {
        var parent = grid[$ "parent_node"];
        if (parent == undefined) break;
        key = string(parent.top_left_x) + "," + string(parent.top_left_y) + "/" + key;
        grid = parent[$ "parent_grid"];
        if (grid == undefined) return undefined;
    }
    // The inside of a building is named by the building's place, which is the same in every game (MistriMultiBuildings.gml).
    if (grid[$ "dyn_index"] != undefined) {
        var inside = mistrimulti_grid_ref(grid);
        return inside == undefined ? undefined : { key: string(grid.location_id) + ":" + inside + "/" + key, loc: grid.location_id };
    }
    return { key: string(grid.location_id) + ":" + key, loc: grid.location_id };
}

function __mistrimulti_ct_chest(key, loc, node, size, host) {
    var c = { k: key, loc: loc, node: node, size: size, rev: host ? 0 : -1, synced: host, hot: 0, open_at: -100000,
        bin: node.prototype.interaction_chest[$ "shipping_bin"] == true,
        base: array_create(size, undefined), seen: array_create(size, 0), hold: array_create(size, false) };
    for (var i = 0; i < size; i++) {
        var slot = node.inventory.slot(i);
        c.base[i] = __mistrimulti_ct_state(slot);
        c.seen[i] = slot.updates;
    }
    return c;
}

function __mistrimulti_ct_index(ct) {
    var r = __mistrimulti_runtime();
    var nodes = STORAGE_NODES;
    if (nodes == undefined || (nodes.count() == ct.count && r.ticks - ct.indexed < MISTRIMULTI_CT_INDEX_TICKS)) return;
    ct.count = nodes.count();
    ct.indexed = r.ticks;
    var chests = {};
    var keys = [];
    for (var i = 0; i < nodes.count() && array_length(keys) < MISTRIMULTI_CT_CHESTS; i++) {
        var node = nodes.get(i);
        if (node[$ "inventory"] == undefined || node.prototype[$ "interaction_chest"] == undefined) continue;
        var where = __mistrimulti_ct_locate(node);
        var size = node.inventory.size();
        if (where == undefined || struct_exists(chests, where.key) || size < 1 || size > MISTRIMULTI_CT_SLOTS) continue;
        var old = ct.chests[$ where.key];
        chests[$ where.key] = is_struct(old) && old.node == node && old.size == size ? old
            : __mistrimulti_ct_chest(where.key, where.loc, node, size, r.mode == "host");
        array_push(keys, where.key);
    }
    ct.chests = chests;
    ct.keys = keys;
}

// Which chests to compare this tick: a rolling window over all of them, plus the ones touched recently.
function __mistrimulti_ct_scan_set(ct) {
    var r = __mistrimulti_runtime();
    var out = [];
    var n = array_length(ct.keys);
    if (n == 0) return out;
    var window = min(n, MISTRIMULTI_CT_SCAN);
    for (var j = 0; j < window; j++) array_push(out, ct.chests[$ ct.keys[(ct.cursor + j) mod n]]);
    ct.cursor = (ct.cursor + window) mod n;
    if (window < n) {
        for (var k = 0; k < n; k++) {
            var c = ct.chests[$ ct.keys[k]];
            if (c.hot > r.ticks) array_push(out, c);
        }
    }
    return out;
}

// ---- items and slot states ---------------------------------------------------------------------------------

function __mistrimulti_ct_field(it, name) {
    var v = it[$ name];
    return is_nullish(v) ? undefined : v;
}

// The nine LiveItem.serialize() fields in the game's order, with missing or null values as undefined: equal items
// give equal JSON text.
function __mistrimulti_ct_norm(it) {
    var ac = __mistrimulti_ct_field(it, "animal_cosmetic");
    if (is_struct(ac)) ac = { animal: ac[$ "animal"], cosmetic: ac[$ "cosmetic"] };
    return { item_id: __mistrimulti_ct_field(it, "item_id"), inner_item: __mistrimulti_ct_field(it, "inner_item"),
        gold_to_gain: __mistrimulti_ct_field(it, "gold_to_gain"), cosmetic: __mistrimulti_ct_field(it, "cosmetic"),
        animal_cosmetic: ac, infusion: __mistrimulti_ct_field(it, "infusion"), auto_use: __mistrimulti_ct_field(it, "auto_use"),
        pet_cosmetic_set_name: __mistrimulti_ct_field(it, "pet_cosmetic_set_name"), date_photo: __mistrimulti_ct_field(it, "date_photo") };
}

// An item received from the network: known item id, plain value types, small. Returns the normalised item or undefined.
function __mistrimulti_ct_clean(it) {
    if (!is_struct(it)) return undefined;
    var n = __mistrimulti_ct_norm(it);
    if (!is_string(n.item_id) || string_length(n.item_id) > 64 || try_string_to_item_id(n.item_id) == undefined) return undefined;
    var names = [n.inner_item, n.infusion, n.pet_cosmetic_set_name];
    for (var i = 0; i < 3; i++) {
        if (names[i] != undefined && (!is_string(names[i]) || string_length(names[i]) > 64)) return undefined;
    }
    if (n.gold_to_gain != undefined && (!is_real(n.gold_to_gain) || n.gold_to_gain < 0 || n.gold_to_gain > 1000000000)) return undefined;
    if (n.cosmetic != undefined && !is_string(n.cosmetic) && !is_real(n.cosmetic)) return undefined;
    if (n.date_photo != undefined && !is_string(n.date_photo) && !is_real(n.date_photo)) return undefined;
    if (n.auto_use != undefined && typeof(n.auto_use) != "bool") return undefined;
    var ac = n.animal_cosmetic;
    if (ac != undefined && (!is_struct(ac) || !is_string(ac.animal) || string_length(ac.animal) > 64
        || (!is_string(ac.cosmetic) && !is_real(ac.cosmetic)))) return undefined;
    if (string_byte_length(json_stringify(n)) > 400) return undefined;
    return n;
}

// Only the fields that are set travel; the receiver's __mistrimulti_ct_norm restores the rest.
function __mistrimulti_ct_wire(it) {
    var out = { item_id: it.item_id };
    var names = struct_get_names(it);
    for (var i = 0; i < array_length(names); i++) {
        if (names[i] != "item_id" && it[$ names[i]] != undefined) out[$ names[i]] = it[$ names[i]];
    }
    return out;
}

function __mistrimulti_ct_live(it) {
    try { return deserialize_live_item(__mistrimulti_ct_norm(it)); }
    catch (e) { return undefined; }
}

function __mistrimulti_ct_item_eq(a, b) {
    if (a == undefined || b == undefined) return false;
    if (json_stringify(a) == json_stringify(b)) return true;
    var x = __mistrimulti_ct_live(a);
    var y = __mistrimulti_ct_live(b);
    return x != undefined && y != undefined && x.partial_eq(y);
}

function __mistrimulti_ct_state(slot) {
    if (slot.item == undefined || slot.count <= 0) return { it: undefined, n: 0 };
    return { it: __mistrimulti_ct_norm(slot.item.serialize()), n: slot.count };
}

function __mistrimulti_ct_same(a, b) {
    return a.n == b.n && (a.n == 0 || __mistrimulti_ct_item_eq(a.it, b.it));
}

function __mistrimulti_ct_cap(it) {
    var live = __mistrimulti_ct_live(it);
    return live == undefined ? 1 : live.prototype.max_stack;
}

// ---- packs: slot states on the wire ------------------------------------------------------------------------

function __mistrimulti_ct_pack_new() {
    return { t: [], s: [], keys: {}, bytes: 0 };
}

function __mistrimulti_ct_pack_add(p, i, st) {
    var ti = -1;
    if (st.n > 0) {
        var text = json_stringify(st.it);
        ti = p.keys[$ text];
        if (ti == undefined) {
            ti = array_length(p.t);
            p.keys[$ text] = ti;
            array_push(p.t, __mistrimulti_ct_wire(st.it));
            p.bytes += string_byte_length(text) + 2;
        }
    }
    array_push(p.s, [i, ti, st.n]);
    p.bytes += 14;
}

// A pack from the network -> [{ i, st }], or undefined when anything is out of range.
function __mistrimulti_ct_unpack(p, size) {
    if (!is_struct(p) || !is_array(p[$ "t"]) || !is_array(p[$ "s"])) return undefined;
    if (array_length(p.t) > MISTRIMULTI_CT_TABLE || array_length(p.s) > MISTRIMULTI_CT_SLOTS) return undefined;
    var items = [];
    for (var i = 0; i < array_length(p.t); i++) {
        var it = __mistrimulti_ct_clean(p.t[i]);
        if (it == undefined) return undefined;
        array_push(items, it);
    }
    var out = [];
    for (var j = 0; j < array_length(p.s); j++) {
        var e = p.s[j];
        if (!is_array(e) || array_length(e) != 3 || !is_real(e[0]) || !is_real(e[1]) || !is_real(e[2])) return undefined;
        if (e[0] != floor(e[0]) || e[0] < 0 || e[0] >= size || e[1] != floor(e[1]) || e[1] < -1 || e[1] >= array_length(items)) return undefined;
        if (e[2] != floor(e[2]) || e[2] < 0 || e[2] > MISTRIMULTI_CT_COUNT || (e[1] < 0) != (e[2] == 0)) return undefined;
        array_push(out, { i: e[0], st: e[1] < 0 ? { it: undefined, n: 0 } : { it: items[e[1]], n: e[2] } });
    }
    return out;
}

// ---- the player's side of a movement ----------------------------------------------------------------------

// Take n of an item out of a place that holds the player's things (the storage menu's hand, the inventory).
function __mistrimulti_ct_take_from(inv, live, n) {
    var taken = 0;
    for (var pass = 0; pass < 2 && taken < n; pass++) {
        for (var i = 0; i < inv.size() && taken < n; i++) {
            var slot = inv.slot(i);
            if (slot.item == undefined || slot.count <= 0) continue;
            var match = pass == 0 ? slot.item.partial_eq(live) : slot.item.item_id == live.item_id;
            if (!match) continue;
            var k = min(slot.count, n - taken);
            slot.remove(k);
            taken += k;
        }
    }
    return taken;
}

function __mistrimulti_ct_player_remove(it, n) {
    var live = __mistrimulti_ct_live(it);
    if (live == undefined || n <= 0) return 0;
    var left = n;
    var menu = ANCHOR.get_menu(Menu.Storage);
    if (menu != undefined && menu[$ "left_menu"] != undefined) left -= __mistrimulti_ct_take_from(menu.left_menu.hand, live, left);
    left -= __mistrimulti_ct_take_from(ARI.inventory, live, left);
    return n - left;
}

// Items the player returns. A debt (see __mistrimulti_ct_take_back) is paid first: items the player never really had.
function __mistrimulti_ct_player_give(it, n) {
    var live = __mistrimulti_ct_live(it);
    if (live == undefined || n <= 0) return;
    var owed = __mistrimulti_ct().owed;
    for (var i = array_length(owed) - 1; i >= 0 && n > 0; i--) {
        if (!__mistrimulti_ct_item_eq(owed[i].it, it)) continue;
        var pay = min(owed[i].n, n);
        owed[i].n -= pay;
        n -= pay;
        if (owed[i].n <= 0) array_delete(owed, i, 1);
    }
    if (n > 0) ARI.give_item(live, n, false, false, false);
}

// The player must lose n of an item that a refused move had given them. If they already moved it on inside the menus, pull
// it out of the puts that are not sent yet, so it cannot reach the host. (Requests are sent one at a time, so a put that
// depends on a refused take has never left this game.)
function __mistrimulti_ct_take_back(it, n) {
    var left = n - __mistrimulti_ct_player_remove(it, n);
    var ct = __mistrimulti_ct();
    for (var k = 0; k < array_length(ct.keys) && left > 0; k++) {
        var c = ct.chests[$ ct.keys[k]];
        for (var i = 0; i < c.size && left > 0; i++) {
            if (c.hold[i]) continue;
            var slot = c.node.inventory.slot(i);
            var local = __mistrimulti_ct_state(slot);
            var base = c.base[i];
            if (local.n == 0 || !__mistrimulti_ct_item_eq(local.it, it)) continue;
            var added = local.n - (base.n > 0 && __mistrimulti_ct_item_eq(base.it, it) ? base.n : 0);
            if (added <= 0) continue;
            var cut = min(added, left);
            __mistrimulti_ct_write(c, i, local.n - cut > 0 ? { it: local.it, n: local.n - cut } : { it: undefined, n: 0 });
            c.seen[i] = -1;
            left -= cut;
        }
    }
    if (left > 0) {
        // The items are in a request that is still on its way (the player put them away before the refusal came). Note the
        // debt: if that request is refused too, what comes back is cancelled against it.
        array_push(ct.owed, { it: it, n: left });
        mmapi_warn_rate_limited("mistrimulti_containers", "mistrimulti", "A refused chest move could not take back " + string(left) + " items.");
    }
}

// A movement to or from the player: n > 0 the player gets n of the item, n < 0 the player loses -n. With an accumulator
// it is only noted (see __mistrimulti_ct_settle), without one it happens now.
function __mistrimulti_ct_flow(acc, it, n) {
    if (n == 0) return;
    if (acc != undefined) array_push(acc, { it: it, n: n });
    else if (n > 0) __mistrimulti_ct_player_give(it, n);
    else __mistrimulti_ct_take_back(it, -n);
}

// Several movements at once: net per item, and gives before takes, so that nothing is taken that is still on its way back.
function __mistrimulti_ct_settle(acc) {
    var net = [];
    for (var i = 0; i < array_length(acc); i++) {
        var found = -1;
        for (var j = 0; j < array_length(net) && found < 0; j++) if (__mistrimulti_ct_item_eq(net[j].it, acc[i].it)) found = j;
        if (found >= 0) net[found].n += acc[i].n;
        else array_push(net, { it: acc[i].it, n: acc[i].n });
    }
    for (var g = 0; g < array_length(net); g++) if (net[g].n > 0) __mistrimulti_ct_player_give(net[g].it, net[g].n);
    for (var t = 0; t < array_length(net); t++) if (net[t].n < 0) __mistrimulti_ct_take_back(net[t].it, -net[t].n);
}

// The slot is forced from state `from` (what the menu left there) to state `to`: whatever that moves goes to the
// player or comes from the player.
function __mistrimulti_ct_unflow(from, to, acc) {
    if (from.n > 0 && to.n > 0 && __mistrimulti_ct_item_eq(from.it, to.it)) {
        __mistrimulti_ct_flow(acc, to.it, from.n - to.n);
        return;
    }
    __mistrimulti_ct_flow(acc, from.it, from.n);
    __mistrimulti_ct_flow(acc, to.it, -to.n);
}

// ---- the replica: overwrite a slot without losing the menu's unsent edits -----------------------------------

function __mistrimulti_ct_write(c, i, st) {
    var slot = c.node.inventory.slot(i);
    if (st.n <= 0) {
        slot.item = undefined;
        slot.count = 0;
    } else {
        var live = __mistrimulti_ct_live(st.it);
        if (live == undefined) return;
        slot.item = live;
        slot.count = st.n;
    }
    slot.updates += 1;
}

function __mistrimulti_ct_compatible(st, it) {
    return st.n == 0 || __mistrimulti_ct_item_eq(st.it, it);
}

// `auth` is the host's state of slot i, `ref` the state our unsent edits are measured against. With no unsent edits the
// slot simply becomes `auth`. With edits of the same item the counts are merged (and the player is corrected if the
// merge is impossible). Edits of another item are undone.
function __mistrimulti_ct_reconcile(c, i, auth, ref) {
    var slot = c.node.inventory.slot(i);
    var local = __mistrimulti_ct_state(slot);
    if (__mistrimulti_ct_same(local, ref)) {
        if (!__mistrimulti_ct_same(local, auth)) __mistrimulti_ct_write(c, i, auth);
        c.base[i] = auth;
        c.seen[i] = slot.updates;
        return;
    }
    var it = auth.n > 0 ? auth.it : (ref.n > 0 ? ref.it : local.it);
    if (__mistrimulti_ct_compatible(ref, it) && __mistrimulti_ct_compatible(local, it) && __mistrimulti_ct_compatible(auth, it)) {
        var n = local.n + auth.n - ref.n;
        var cap = __mistrimulti_ct_cap(it);
        if (n < 0) {
            __mistrimulti_ct_take_back(it, -n);
            n = 0;
        } else if (n > cap) {
            __mistrimulti_ct_player_give(it, n - cap);
            n = cap;
        }
        __mistrimulti_ct_write(c, i, n > 0 ? { it: it, n: n } : { it: undefined, n: 0 });
        c.base[i] = auth;
        c.seen[i] = -1; // the merged slot still differs from the host's: the next scan sends the difference
        return;
    }
    __mistrimulti_ct_unflow(local, ref);
    __mistrimulti_ct_write(c, i, auth);
    c.base[i] = auth;
    c.seen[i] = slot.updates;
}

// ---- host: applying a transaction ---------------------------------------------------------------------------

function __mistrimulti_ct_here(peer, c) {
    var room = peer[$ "room"];
    if (!is_string(room)) return false;
    // A chest inside a building: only a player in that very building (two barns share the location).
    var grid = c.node[$ "parent_grid"];
    if (grid != undefined && grid[$ "dyn_index"] != undefined) return room == mistrimulti_room_of_grid(grid);
    var prefix = location_id_to_string(c.loc) + ":";
    return string_copy(room, 1, string_length(prefix)) == prefix;
}

function __mistrimulti_ct_parse_tx(c, data) {
    var t = data[$ "t"];
    var o = data[$ "o"];
    if (!is_array(t) || !is_array(o) || array_length(t) > MISTRIMULTI_CT_TABLE || array_length(o) < 1 || array_length(o) > MISTRIMULTI_CT_OPS) return undefined;
    var items = [];
    for (var i = 0; i < array_length(t); i++) {
        var it = __mistrimulti_ct_clean(t[i]);
        // Items that use themselves on pickup cannot be stored.
        if (it == undefined || it.auto_use == true) return undefined;
        array_push(items, it);
    }
    var ops = [];
    var used = {};
    for (var j = 0; j < array_length(o); j++) {
        var e = o[j];
        if (!is_array(e) || array_length(e) != 5) return undefined;
        for (var q = 0; q < 5; q++) if (!is_real(e[q]) || e[q] != floor(e[q])) return undefined;
        if (e[0] < 0 || e[0] >= c.size || struct_exists(used, string(e[0]))) return undefined;
        used[$ string(e[0])] = true;
        var removes = e[1] >= 0;
        var adds = e[3] >= 0;
        if (!removes && !adds) return undefined;
        if (removes && (e[1] >= array_length(items) || e[2] < 1 || e[2] > MISTRIMULTI_CT_COUNT)) return undefined;
        if (adds && (e[3] >= array_length(items) || e[4] < 1 || e[4] > MISTRIMULTI_CT_COUNT)) return undefined;
        if ((!removes && (e[1] != -1 || e[2] != 0)) || (!adds && (e[3] != -1 || e[4] != 0))) return undefined;
        array_push(ops, { i: e[0], ri: e[1], rn: e[2], ai: e[3], an: e[4] });
    }
    return { items: items, ops: ops };
}

// Applies one chest's operations; every touched slot is saved in `saved` first so that the caller can undo everything.
function __mistrimulti_ct_apply(c, tx, saved) {
    for (var j = 0; j < array_length(tx.ops); j++) {
        var op = tx.ops[j];
        var slot = c.node.inventory.slot(op.i);
        array_push(saved, { slot: slot, item: slot.item, count: slot.count });
        if (op.ri >= 0) {
            var take = __mistrimulti_ct_live(tx.items[op.ri]);
            if (take == undefined || slot.item == undefined || slot.count < op.rn || !slot.item.partial_eq(take)) return false;
            slot.remove(op.rn);
        }
        if (op.ai >= 0) {
            var put = __mistrimulti_ct_live(tx.items[op.ai]);
            if (put == undefined || slot.room_for_item(put) < op.an) return false;
            slot.add(put, op.an);
        }
    }
    return true;
}

// Host only, once per request id. The request lists the changes of one or more chests (everything the guest's menus
// changed since its last request, so that moves between chests stay together). All of it is applied, or none. The result
// has, per chest, the new revision and the authoritative state of every slot the request named.
function mistrimulti_chest_tx_request(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || player == r.id || !is_struct(data) || !is_array(data[$ "x"])) return { ok: false, why: "bad" };
    var parts = data.x;
    if (array_length(parts) < 1 || array_length(parts) > MISTRIMULTI_CT_PARTS || string_byte_length(json_stringify(data)) > MISTRIMULTI_CT_TX_LIMIT) return { ok: false, why: "bad" };
    var peer = r.peers[player];
    if (!is_struct(peer) || peer[$ "active"] != true) return { ok: false, why: "away" };
    var ct = __mistrimulti_ct();
    __mistrimulti_ct_index(ct);
    var plan = [];
    var named = {};
    for (var p = 0; p < array_length(parts); p++) {
        var part = parts[p];
        if (!is_struct(part) || !is_string(part[$ "k"]) || string_length(part.k) > 64 || struct_exists(named, part.k)) return { ok: false, why: "bad" };
        named[$ part.k] = true;
        var c = ct.chests[$ part.k];
        if (!is_struct(c)) return { ok: false, why: "unknown" };
        if (!__mistrimulti_ct_here(peer, c)) return { ok: false, why: "away" };
        var tx = __mistrimulti_ct_parse_tx(c, part);
        if (tx == undefined) return { ok: false, why: "bad" };
        array_push(plan, { c: c, tx: tx });
    }
    var saved = [];
    var good = true;
    try {
        for (var q = 0; q < array_length(plan) && good; q++) good = __mistrimulti_ct_apply(plan[q].c, plan[q].tx, saved);
    } catch (e) {
        good = false;
        mmapi_warn_rate_limited("mistrimulti_containers", "mistrimulti", "A chest transaction failed: " + string(e));
    }
    if (!good) {
        for (var b = array_length(saved) - 1; b >= 0; b--) {
            saved[b].slot.item = saved[b].item;
            saved[b].slot.count = saved[b].count;
            saved[b].slot.updates += 1;
        }
    }
    var out = [];
    var flows = [];
    var budget = MISTRIMULTI_CT_PACK_BYTES;
    for (var n = 0; n < array_length(plan); n++) {
        var pc = plan[n].c;
        var pack = __mistrimulti_ct_pack_new();
        if (good) {
            pc.rev++;
            pc.hot = r.ticks + MISTRIMULTI_CT_HOT_TICKS;
        }
        for (var m = 0; m < array_length(plan[n].tx.ops) && (good || pack.bytes < budget); m++) {
            var o = plan[n].tx.ops[m];
            var s = pc.node.inventory.slot(o.i);
            var st = __mistrimulti_ct_state(s);
            __mistrimulti_ct_pack_add(pack, o.i, st);
            if (!good) continue;
            pc.base[o.i] = st;
            pc.seen[o.i] = s.updates;
            if (o.ri >= 0) array_push(flows, { it: plan[n].tx.items[o.ri], n: o.rn });
            if (o.ai >= 0) array_push(flows, { it: plan[n].tx.items[o.ai], n: -o.an });
        }
        budget -= pack.bytes;
        array_push(out, { k: pc.k, v: pc.rev, t: pack.t, s: pack.s });
    }
    if (!good) return { ok: false, why: "conflict", x: out };
    mistrimulti_ct_record_apply(player, flows);
    return { ok: true, x: out };
}

// The guest's menu moved items between its own inventory and the chest. If the guest's game dies before its next
// checkpoint, its stored record must already say so, or the items would be lost (taken) or duplicated (stored).
// `flows`: { it, n } with n > 0 added to the player, n < 0 removed from the player. Host only. Fails soft.
function mistrimulti_ct_record_apply(player, flows) {
    var r = __mistrimulti_runtime();
    try {
        var session = r.player_sessions[player];
        var peer = r.peers[player];
        if (r.mode != "host" || !is_struct(session) || !is_struct(peer) || session.uid != peer[$ "uid"]) return false;
        var saved = mistrimulti_player_load(session.uid);
        if (saved == undefined || !is_array(saved.data[$ "inventory"])) return false;
        var changed = false;
        for (var f = 0; f < array_length(flows); f++) {
            var flow = flows[f];
            var moved = flow.n > 0 ? __mistrimulti_ct_json_add(saved.data.inventory, flow.it, flow.n)
                : __mistrimulti_ct_json_remove(saved.data.inventory, flow.it, -flow.n);
            if (moved > 0) changed = true;
        }
        return changed && mistrimulti_player_store(session.uid, saved.revision, saved.data);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_containers", "mistrimulti", "A player record could not be updated: " + string(e));
        return false;
    }
}

function __mistrimulti_ct_json_add(slots, it, n) {
    var live = __mistrimulti_ct_live(it);
    if (live == undefined) return 0;
    var cap = live.prototype.max_stack;
    var left = n;
    for (var pass = 0; pass < 2 && left > 0; pass++) {
        for (var i = 0; i < array_length(slots) && left > 0; i++) {
            var s = slots[i];
            if (!is_struct(s) || !is_real(s[$ "count"])) continue;
            var has = is_struct(s[$ "item"]) && s.count > 0;
            if (pass == 0 && has && __mistrimulti_ct_item_eq(__mistrimulti_ct_norm(s.item), it) && s.count < cap) {
                var more = min(cap - s.count, left);
                s.count += more;
                left -= more;
            } else if (pass == 1 && !has && is_array(s[$ "required_tags"]) && array_length(s.required_tags) == 0) {
                var put = min(cap, left);
                s.item = __mistrimulti_ct_norm(it);
                s.count = put;
                left -= put;
            }
        }
    }
    return n - left;
}

function __mistrimulti_ct_json_remove(slots, it, n) {
    var left = n;
    for (var i = 0; i < array_length(slots) && left > 0; i++) {
        var s = slots[i];
        if (!is_struct(s) || !is_real(s[$ "count"]) || !is_struct(s[$ "item"]) || s.count <= 0) continue;
        if (!__mistrimulti_ct_item_eq(__mistrimulti_ct_norm(s.item), it)) continue;
        var less = min(s.count, left);
        s.count -= less;
        left -= less;
        if (s.count <= 0) {
            s.count = 0;
            s.item = undefined;
        }
    }
    return n - left;
}

// ---- host: watching its own inventories, snapshots ------------------------------------------------------------

// A change the host (or the game's own code) made to a chest: announce the new slot states to every guest.
function __mistrimulti_ct_scan_host(ct) {
    var set = __mistrimulti_ct_scan_set(ct);
    for (var x = 0; x < array_length(set); x++) {
        var c = set[x];
        var inv = c.node.inventory;
        var pack = undefined;
        var pending = [];
        for (var i = 0; i < c.size; i++) {
            var slot = inv.slot(i);
            if (slot.updates == c.seen[i]) continue;
            var st = __mistrimulti_ct_state(slot);
            if (__mistrimulti_ct_same(st, c.base[i])) {
                c.seen[i] = slot.updates;
                continue;
            }
            if (pack == undefined) pack = __mistrimulti_ct_pack_new();
            __mistrimulti_ct_pack_add(pack, i, st);
            array_push(pending, { i: i, st: st, u: slot.updates });
            if (pack.bytes >= MISTRIMULTI_CT_PACK_BYTES) {
                if (!__mistrimulti_ct_flush(c, pack, pending)) return;
                pack = undefined;
                pending = [];
            }
        }
        if (pack != undefined && !__mistrimulti_ct_flush(c, pack, pending)) return;
    }
}

function __mistrimulti_ct_flush(c, pack, pending) {
    c.rev++;
    if (!mistrimulti_event_emit("chest_state", { k: c.k, v: c.rev, t: pack.t, s: pack.s })) {
        c.rev--;
        return false;
    }
    c.hot = __mistrimulti_runtime().ticks + MISTRIMULTI_CT_HOT_TICKS;
    for (var j = 0; j < array_length(pending); j++) {
        c.base[pending[j].i] = pending[j].st;
        c.seen[pending[j].i] = pending[j].u;
    }
    return true;
}

// Slots from..: states as of now, up to the size budget. `e` marks the slice that reaches the end of the chest.
function __mistrimulti_ct_slice(c, from) {
    var pack = __mistrimulti_ct_pack_new();
    var i = from;
    while (i < c.size && pack.bytes < MISTRIMULTI_CT_PACK_BYTES) {
        __mistrimulti_ct_pack_add(pack, i, __mistrimulti_ct_state(c.node.inventory.slot(i)));
        i++;
    }
    return { next: i, data: { k: c.k, v: c.rev, n: c.size, t: pack.t, s: pack.s, e: i >= c.size } };
}

// A guest asks for a chest (opening it, or after missing something): the whole chest, then the result.
function mistrimulti_chest_open_request(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || player == r.id || !is_struct(data) || !is_string(data[$ "k"]) || string_length(data.k) > 64) return { ok: false };
    var ct = __mistrimulti_ct();
    __mistrimulti_ct_index(ct);
    var c = ct.chests[$ data.k];
    if (!is_struct(c)) return { ok: false, k: data.k };
    var parts = [];
    var next = 0;
    while (next < c.size) {
        var part = __mistrimulti_ct_slice(c, next);
        array_push(parts, part.data);
        next = part.next;
    }
    // Not now: the queue is busy. The request stays at the head and is retried on a later tick.
    if (!mistrimulti_event_can_emit(array_length(parts) + 2)) return false;
    for (var i = 0; i < array_length(parts); i++) mistrimulti_event_emit("chest_snap", parts[i], player);
    c.hot = r.ticks + MISTRIMULTI_CT_HOT_TICKS;
    return { ok: true, k: c.k, v: c.rev };
}

// Joining guests receive every chest in slices, the chests of their own location first.
function __mistrimulti_ct_stream(ct) {
    var r = __mistrimulti_runtime();
    var budget = MISTRIMULTI_CT_STREAM_EVENTS;
    for (var slot = 1; slot < 8 && budget > 0; slot++) {
        var s = ct.snaps[slot];
        if (!is_struct(s)) continue;
        if (!is_array(s.order)) {
            var peer = r.peers[slot];
            var room = is_struct(peer) && is_string(peer[$ "room"]) ? peer.room : "";
            var near = [];
            var far = [];
            for (var k = 0; k < array_length(ct.keys); k++) {
                var c0 = ct.chests[$ ct.keys[k]];
                var prefix = location_id_to_string(c0.loc) + ":";
                if (string_copy(room, 1, string_length(prefix)) == prefix) array_push(near, ct.keys[k]);
                else array_push(far, ct.keys[k]);
            }
            for (var f = 0; f < array_length(far); f++) array_push(near, far[f]);
            s.order = near;
            s.pos = 0;
            s.from = 0;
        }
        while (budget > 0 && s.pos < array_length(s.order)) {
            if (mistrimulti_event_backlog() >= 16 || !mistrimulti_event_can_emit(2)) return;
            var c = ct.chests[$ s.order[s.pos]];
            if (!is_struct(c)) {
                s.pos++;
                s.from = 0;
                continue;
            }
            var part = __mistrimulti_ct_slice(c, s.from);
            if (!mistrimulti_event_emit("chest_snap", part.data, slot)) {
                ct.snaps[slot] = undefined; // the guest left; a new session asks again through on_peer
                break;
            }
            budget--;
            s.from = part.next;
            if (s.from >= c.size) {
                s.pos++;
                s.from = 0;
            }
        }
        if (is_struct(ct.snaps[slot]) && s.pos >= array_length(s.order)) ct.snaps[slot] = undefined;
    }
}

// ---- guest: sending what the menus changed --------------------------------------------------------------------

function __mistrimulti_ct_build_tx(c, dirty) {
    var t = [];
    var index = {};
    var ops = [];
    for (var j = 0; j < array_length(dirty); j++) {
        var d = dirty[j];
        var ri = -1;
        var rn = 0;
        var ai = -1;
        var an = 0;
        var same = d.pre.n > 0 && d.now.n > 0 && __mistrimulti_ct_item_eq(d.pre.it, d.now.it);
        if (same && d.now.n < d.pre.n) {
            ri = __mistrimulti_ct_table(t, index, d.pre.it);
            rn = d.pre.n - d.now.n;
        } else if (same) {
            ai = __mistrimulti_ct_table(t, index, d.now.it);
            an = d.now.n - d.pre.n;
        } else {
            if (d.pre.n > 0) {
                ri = __mistrimulti_ct_table(t, index, d.pre.it);
                rn = d.pre.n;
            }
            if (d.now.n > 0) {
                ai = __mistrimulti_ct_table(t, index, d.now.it);
                an = d.now.n;
            }
        }
        array_push(ops, [d.i, ri, rn, ai, an]);
    }
    return { k: c.k, t: t, o: ops };
}

function __mistrimulti_ct_table(t, index, it) {
    var text = json_stringify(it);
    var known = index[$ text];
    if (known == undefined) {
        known = array_length(t);
        index[$ text] = known;
        array_push(t, __mistrimulti_ct_wire(it));
    }
    return known;
}

// The changes cannot be sent as one transaction: put everything back as the host has it.
function __mistrimulti_ct_revert(groups) {
    var acc = [];
    for (var g = 0; g < array_length(groups); g++) {
        var c = groups[g].c;
        for (var j = 0; j < array_length(groups[g].dirty); j++) {
            var d = groups[g].dirty[j];
            __mistrimulti_ct_unflow(d.now, d.pre, acc);
            __mistrimulti_ct_write(c, d.i, d.pre);
            c.seen[d.i] = c.node.inventory.slot(d.i).updates;
        }
    }
    __mistrimulti_ct_settle(acc);
    mmapi_warn_rate_limited("mistrimulti_containers", "mistrimulti", "A chest change was too large and was undone.");
}

// The end-of-day sequence is running in this game: it empties the copy of every shipping bin without the player moving anything.
function __mistrimulti_ct_sleeping() {
    return ARI != undefined && (ARI[$ "end_of_day_status"] != undefined || ARI[$ "end_of_day_sequence"] == true);
}

// Everything the menus changed in the scanned chests: [{ c, dirty: [{ i, pre, now, u }] }].
function __mistrimulti_ct_collect(ct) {
    var set = __mistrimulti_ct_scan_set(ct);
    var sleeping = __mistrimulti_ct_sleeping();
    var groups = [];
    for (var x = 0; x < array_length(set); x++) {
        var c = set[x];
        var dirty = [];
        var emptied = false;
        for (var i = 0; i < c.size; i++) {
            if (c.hold[i]) continue;
            var slot = c.node.inventory.slot(i);
            if (slot.updates == c.seen[i]) continue;
            var st = __mistrimulti_ct_state(slot);
            if (__mistrimulti_ct_same(st, c.base[i])) {
                c.seen[i] = slot.updates;
            } else if (sleeping) {
                // The end-of-day sequence empties this game's copy of every shipping bin on its own; that is not the
                // player's move. The host sells the bins (once, into the shared wallet) and decides what they hold.
                c.base[i] = st;
                c.seen[i] = slot.updates;
                if (c.bin) emptied = true;
            } else {
                array_push(dirty, { i: i, pre: c.base[i], now: st, u: slot.updates });
            }
        }
        if (array_length(dirty) > 0) array_push(groups, { c: c, dirty: dirty });
        if (emptied) __mistrimulti_ct_resync(c); // show what the host's bin holds again
    }
    return groups;
}

function __mistrimulti_ct_scan_guest(ct) {
    // One request at a time: what the menus do next may depend on how this one ends.
    if (array_length(struct_get_names(ct.txs)) > 0) return;
    var groups = __mistrimulti_ct_collect(ct);
    if (array_length(groups) > 0) __mistrimulti_ct_send(ct, groups);
}

// All changed chests go in ONE request, so that a move from one chest to another is applied or refused as a whole.
function __mistrimulti_ct_send(ct, groups) {
    var r = __mistrimulti_runtime();
    var parts = [];
    var big = array_length(groups) > MISTRIMULTI_CT_PARTS;
    for (var g = 0; g < array_length(groups) && !big; g++) {
        var part = __mistrimulti_ct_build_tx(groups[g].c, groups[g].dirty);
        big = array_length(groups[g].dirty) > MISTRIMULTI_CT_OPS || array_length(part.t) > MISTRIMULTI_CT_TABLE;
        array_push(parts, part);
    }
    var data = { x: parts };
    if (big || string_byte_length(json_stringify(data)) > MISTRIMULTI_CT_TX_BYTES) {
        __mistrimulti_ct_revert(groups);
        return;
    }
    var rid = mistrimulti_event_request("chest_tx", data);
    if (rid == undefined) {
        for (var a = 0; a < array_length(groups); a++) {
            for (var j = 0; j < array_length(groups[a].dirty); j++) groups[a].c.seen[groups[a].dirty[j].i] = -1; // compare again next tick
        }
        return;
    }
    var rec = { parts: [] };
    for (var b = 0; b < array_length(groups); b++) {
        var c = groups[b].c;
        var sub = { k: c.k, slots: [], pre: [], exp: [] };
        for (var n = 0; n < array_length(groups[b].dirty); n++) {
            var d = groups[b].dirty[n];
            array_push(sub.slots, d.i);
            array_push(sub.pre, d.pre);
            array_push(sub.exp, d.now);
            c.hold[d.i] = true;
            c.base[d.i] = d.now; // expected result; later edits are measured against it
            c.seen[d.i] = d.u;
        }
        c.hot = r.ticks + MISTRIMULTI_CT_HOT_TICKS;
        array_push(rec.parts, sub);
    }
    ct.txs[$ rid] = rec;
}

// ---- guest: results and host events ---------------------------------------------------------------------------

// The host's revision `v` of chest c: is it the next one? A jump means events were missed, so ask for the chest again.
function __mistrimulti_ct_follow(ct, c, v) {
    if (!is_real(v) || v != floor(v)) return false;
    if (!c.synced) return true;
    if (v <= c.rev) return false;
    if (v > c.rev + 1) {
        c.synced = false;
        __mistrimulti_ct_resync(c);
    }
    c.rev = v;
    return true;
}

function __mistrimulti_ct_resync(c) {
    var r = __mistrimulti_runtime();
    if (r.ticks - c.open_at < MISTRIMULTI_CT_OPEN_TICKS / 2) return;
    c.open_at = r.ticks;
    mistrimulti_event_request("chest_open", { k: c.k });
}

function __mistrimulti_ct_apply_pack(c, data) {
    var states = __mistrimulti_ct_unpack(data, c.size);
    if (states == undefined) return false;
    for (var j = 0; j < array_length(states); j++) {
        var s = states[j];
        // A slot with a request in flight takes the host's answer from that request's result. A bin that this game's end of
        // day just emptied is not an edit of the player: the host's state replaces it as it is.
        var ref = c.bin && __mistrimulti_ct_sleeping() ? __mistrimulti_ct_state(c.node.inventory.slot(s.i)) : c.base[s.i];
        if (!c.hold[s.i]) __mistrimulti_ct_reconcile(c, s.i, s.st, ref);
    }
    return true;
}

function __mistrimulti_ct_chest_of(data) {
    if (!is_struct(data) || !is_string(data[$ "k"])) return undefined;
    return __mistrimulti_ct().chests[$ data.k];
}

// Every guest: a change somebody made (including this guest's own request, handled first).
function mistrimulti_chest_tx_result(player, result, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "join" || player != 0 || !is_struct(result)) return true;
    try {
        var ct = __mistrimulti_ct();
        if (ctx.mine) {
            __mistrimulti_ct_finish(ct, ctx.id, result, result[$ "ok"] == true ? 0 : 1);
            return true;
        }
        if (result[$ "ok"] != true || !is_array(result[$ "x"])) return true;
        for (var j = 0; j < array_length(result.x); j++) {
            var sub = result.x[j];
            var c = __mistrimulti_ct_chest_of(sub);
            if (is_struct(c) && __mistrimulti_ct_follow(ct, c, sub[$ "v"])) __mistrimulti_ct_apply_pack(c, sub);
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_containers", "mistrimulti", "A chest result could not be applied: " + string(e));
    }
    return true;
}

// The requester only: the host restarted (lost) or the answer was dropped from its cache (expired).
function mistrimulti_chest_tx_reply(player, result, ctx) {
    if (is_struct(result) || __mistrimulti_runtime().mode != "join") return true;
    try {
        __mistrimulti_ct_finish(__mistrimulti_ct(), ctx.id, undefined, ctx.lost ? 2 : 3);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_containers", "mistrimulti", "A chest request could not be settled: " + string(e));
    }
    return true;
}

// How a transaction of this guest ended: 0 applied, 1 refused, 2 lost with the old host, 3 applied but unknown.
function __mistrimulti_ct_finish(ct, rid, result, how) {
    var tx = ct.txs[$ rid];
    if (tx == undefined) return;
    struct_remove(ct.txs, rid);
    var acc = [];
    var subs = {};
    if (is_struct(result) && is_array(result[$ "x"])) {
        for (var a = 0; a < array_length(result.x); a++) {
            if (is_struct(result.x[a]) && is_string(result.x[a][$ "k"])) subs[$ result.x[a].k] = result.x[a];
        }
    }
    for (var p = 0; p < array_length(tx.parts); p++) {
        var part = tx.parts[p];
        var c = ct.chests[$ part.k];
        if (!is_struct(c)) continue;
        for (var j = 0; j < array_length(part.slots); j++) c.hold[part.slots[j]] = false;
        var sub = subs[$ part.k];
        var auth = {};
        var states = sub == undefined ? undefined : __mistrimulti_ct_unpack(sub, c.size);
        if (states != undefined) {
            for (var q = 0; q < array_length(states); q++) auth[$ string(states[q].i)] = states[q].st;
        }
        var mode = how;
        if (mode == 0 && (sub == undefined || !__mistrimulti_ct_follow(ct, c, sub[$ "v"]))) mode = 3;
        var unknown = mode == 2 || mode == 3;
        for (var n = 0; n < array_length(part.slots); n++) {
            var i = part.slots[n];
            var st = auth[$ string(i)];
            if (mode == 0) {
                __mistrimulti_ct_reconcile(c, i, st == undefined ? part.exp[n] : st, part.exp[n]);
            } else if (mode == 3) {
                __mistrimulti_ct_reconcile(c, i, part.exp[n], part.exp[n]);
            } else {
                // Refused or lost: give back what the menu moved, then take the host's word for the slot.
                var local = __mistrimulti_ct_state(c.node.inventory.slot(i));
                __mistrimulti_ct_unflow(local, part.pre[n], acc);
                var target = st == undefined ? part.pre[n] : st;
                __mistrimulti_ct_write(c, i, target);
                c.base[i] = target;
                c.seen[i] = c.node.inventory.slot(i).updates;
                if (st == undefined) unknown = true;
            }
        }
        if (unknown) {
            c.open_at = -100000;
            __mistrimulti_ct_resync(c);
        }
    }
    __mistrimulti_ct_settle(acc);
}

function mistrimulti_chest_state_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "join" || player != 0) return true;
    try {
        var c = __mistrimulti_ct_chest_of(data);
        if (!is_struct(c) || !__mistrimulti_ct_follow(__mistrimulti_ct(), c, data[$ "v"])) return true;
        __mistrimulti_ct_apply_pack(c, data);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_containers", "mistrimulti", "A chest update could not be applied: " + string(e));
    }
    return true;
}

function mistrimulti_chest_snap_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "join" || player != 0) return true;
    try {
        var c = __mistrimulti_ct_chest_of(data);
        if (!is_struct(c) || data[$ "n"] != c.size || !is_real(data[$ "v"])) return true;
        if (!__mistrimulti_ct_apply_pack(c, data)) return true;
        if (data[$ "e"] == true) {
            c.synced = true;
            c.rev = data.v;
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_containers", "mistrimulti", "A chest snapshot could not be applied: " + string(e));
    }
    return true;
}

// A participant appeared (a new session) or left. Host: send the new guest the chests. Guest: the host (re)appeared,
// so what we know about its chests is out of date until its snapshot arrives.
function mistrimulti_chest_peer(slot, joined, stream) {
    var r = __mistrimulti_runtime();
    var ct = __mistrimulti_ct();
    if (r.mode == "host") {
        ct.snaps[slot] = joined ? { stream: stream, order: undefined, pos: 0, from: 0 } : undefined;
    } else if (slot == 0 && joined) {
        __mistrimulti_ct_unsync(ct);
    }
}

function mistrimulti_chest_gap(slot, base, expected) {
    if (slot == 0 && __mistrimulti_runtime().mode == "join") __mistrimulti_ct_unsync(__mistrimulti_ct());
}

function __mistrimulti_ct_unsync(ct) {
    for (var i = 0; i < array_length(ct.keys); i++) ct.chests[$ ct.keys[i]].synced = false;
}

// ---- tick, hooks, diagnostics ----------------------------------------------------------------------------------

// Bridge tick (20 Hz) while a world is loaded.
function mistrimulti_containers_tick() {
    var r = __mistrimulti_runtime();
    if (!r.enabled) return;
    try {
        var ct = __mistrimulti_ct();
        if (r.mode == "host" && r.mask == 0) {
            // Alone: nothing to tell anyone, and the next guest gets a full snapshot anyway.
            ct.chests = {};
            ct.keys = [];
            ct.count = -1;
            return;
        }
        __mistrimulti_ct_index(ct);
        if (r.mode == "host") {
            __mistrimulti_ct_scan_host(ct);
            __mistrimulti_ct_stream(ct);
        } else {
            __mistrimulti_ct_scan_guest(ct);
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_containers", "mistrimulti", "Chest sync failed: " + string(e));
    }
}

// object.interact (override, always defers): a guest opening a chest asks the host for its current contents. The menu
// opens at once; the contents refresh when they arrive, and anything done on stale contents is checked by the host.
function mistrimulti_containers_interact(node) {
    var r = __mistrimulti_runtime();
    try {
        if (r.enabled && is_struct(node) && node[$ "inventory"] != undefined) {
            var ct = __mistrimulti_ct();
            __mistrimulti_ct_index(ct);
            var where = __mistrimulti_ct_locate(node);
            var c = where == undefined ? undefined : ct.chests[$ where.key];
            if (is_struct(c)) {
                c.hot = r.ticks + MISTRIMULTI_CT_HOT_TICKS;
                if (r.mode == "join" && r.ticks - c.open_at >= MISTRIMULTI_CT_OPEN_TICKS) {
                    c.open_at = r.ticks;
                    mistrimulti_event_request("chest_open", { k: c.k });
                }
            }
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_containers", "mistrimulti", "Chest open failed: " + string(e));
    }
    return undefined;
}

function mistrimulti_containers_debug() {
    var ct = __mistrimulti_ct();
    var synced = 0;
    for (var i = 0; i < array_length(ct.keys); i++) if (ct.chests[$ ct.keys[i]].synced) synced++;
    return { chests: array_length(ct.keys), synced: synced, transactions: array_length(struct_get_names(ct.txs)) };
}
