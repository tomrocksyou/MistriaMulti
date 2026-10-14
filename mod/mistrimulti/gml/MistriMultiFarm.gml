// MistriaMulti farm world sync: crops, trees, stumps, rocks and ore, forageables, dig sites, weeds and grass, and
// fences and sprinklers, on the event layer. Design, assumptions and the in-game checklist: docs/SYNC-FARM.md.
// Soil and watering stay in MistriMultiTerrain.gml.
//
// The host owns the world. Every synchronised node is identified by its anchor cell (its top-left cell) and
// described by a record [object name, x, y, state...] of whole numbers. Each game keeps, per location, the
// signature of every anchored node it last saw, plus a digest per 8x8 cell chunk. A sliced scanner compares
// the grid with those signatures:
//   host   a change is published as a "farm_delta" (host changes, day-change growth and spawns);
//   guest  hand-made changes with no yield (planting, cutting grass, fences) go to the host as "farm_act" edits.
// Guest swings and harvests that yield items are never performed locally first: the cells are taken out of the
// tool's target list (or the interaction is claimed), the host validates and changes its world, and the guest
// runs the game's own action when the result arrives, so the yield, perks and xp are the requester's own.
// The host also sends digests (on join, after a day change, every minute); a guest asks for the chunks that
// differ, which repairs anything missed, including its own local growth and spawns.

#macro MISTRIMULTI_FARM_CHUNK 8
#macro MISTRIMULTI_FARM_HASH 1000000007
#macro MISTRIMULTI_FARM_SCAN_CURRENT 1500
#macro MISTRIMULTI_FARM_SCAN_OTHER 300
#macro MISTRIMULTI_FARM_SCAN_FAST 4000
#macro MISTRIMULTI_FARM_SCAN_TICK 6000
#macro MISTRIMULTI_FARM_BATCH 40
#macro MISTRIMULTI_FARM_PENDING 6000
#macro MISTRIMULTI_FARM_BACKLOG 24
#macro MISTRIMULTI_FARM_REACH 128
#macro MISTRIMULTI_FARM_RECONCILE 1200
#macro MISTRIMULTI_FARM_EDITS 16
#macro MISTRIMULTI_FARM_ERRORS 40
#macro MISTRIMULTI_FARM_PRESS 20

// ---- registration -------------------------------------------------------------------------------------------

// Event kinds: "farm_act" (guest request, result to everyone), "farm_delta" (host changes), "farm_digest" and
// "farm_chunk" (host to one guest or all), "farm_want" and "farm_hello" (guest to host).
function mistrimulti_farm_register_events() {
    mistrimulti_event_register("farm_act", { on_request: mistrimulti_farm_request, on_result: mistrimulti_farm_result,
        on_reply: mistrimulti_farm_reply });
    mistrimulti_event_register("farm_delta", { on_event: mistrimulti_farm_delta_event });
    mistrimulti_event_register("farm_digest", { on_event: mistrimulti_farm_digest_event });
    mistrimulti_event_register("farm_chunk", { on_event: mistrimulti_farm_chunk_event });
    mistrimulti_event_register("farm_want", { on_event: mistrimulti_farm_want_event });
    mistrimulti_event_register("farm_hello", { on_event: mistrimulti_farm_hello_event, on_peer: mistrimulti_farm_peer,
        on_gap: mistrimulti_farm_gap });
}

function mistrimulti_farm_register_hooks() {
    mmapi_filter("tool.targets", mistrimulti_farm_tool_targets);
    mmapi_override("object.interact", mistrimulti_farm_interact);
    mmapi_on("game.new_day", mistrimulti_farm_new_day);
}

// ---- state --------------------------------------------------------------------------------------------------

function mistrimulti_farm_state() {
    var r = __mistrimulti_runtime();
    if (!is_struct(r[$ "farm"])) {
        r.farm = { ids: undefined, locs: {}, errors: 0, bypass: 0, tick: 0, rotate: 0, idle: true,
            swing: {}, swing_at: -100, press: {}, pending: {}, pending_keys: [], full: false, jobs: [], chunks: [],
            hello: false, day_left: 0, day_flag: false, next_digest: 0 };
    }
    return r.farm;
}

// The farm plus every saved static location that has forageables or dig sites (never the mines, which are
// generated for each player).
function mistrimulti_farm_location_ids(f) {
    if (f.ids != undefined) return f.ids;
    var ids = [LocationId.Farm];
    if (LOCATIONS != undefined) {
        for (var i = 0; i < LocationId.LEN; i++) {
            var loc = LOCATIONS[i];
            if (i == LocationId.Farm || i == LocationId.Dungeon || !is_struct(loc) || loc.serializable != true) continue;
            if ((is_real(loc.forageables) && loc.forageables > 0) || (is_real(loc.dig_sites) && loc.dig_sites > 0)) array_push(ids, i);
        }
    }
    f.ids = ids;
    return ids;
}

function mistrimulti_farm_ok(f) {
    return f.errors < MISTRIMULTI_FARM_ERRORS && GRIDS != undefined;
}

function mistrimulti_farm_fail(f, e) {
    f.errors++;
    mmapi_warn_rate_limited("mistrimulti_farm", "mistrimulti", "A farm update failed: " + string(e));
}

function mistrimulti_farm_int(v) {
    return is_real(v) && v == floor(v) && abs(v) <= 1000000;
}

// The state for one location, rebuilt when the game loads a new grid for it. undefined for unsynchronised ones.
function mistrimulti_farm_loc(id) {
    var f = mistrimulti_farm_state();
    if (!is_real(id) || id != floor(id) || GRIDS == undefined) return undefined;
    var ids = mistrimulti_farm_location_ids(f);
    var known = false;
    for (var i = 0; i < array_length(ids); i++) if (ids[i] == id) known = true;
    if (!known) return undefined;
    var grid = GRIDS[id];
    if (grid == undefined || grid.dyn_index != undefined) return undefined;
    var ls = f.locs[$ string(id)];
    if (!is_struct(ls) || grid[$ "mm_farm"] != ls.token) {
        var w = grid.dims.x;
        var h = grid.dims.y;
        var cw = (w + MISTRIMULTI_FARM_CHUNK - 1) div MISTRIMULTI_FARM_CHUNK;
        var ch = (h + MISTRIMULTI_FARM_CHUNK - 1) div MISTRIMULTI_FARM_CHUNK;
        var token = string(id) + "-" + string(get_timer());
        grid.mm_farm = token;
        // sig: signature of the node anchored at each cell (0 = none); kind: its category + 1; cs: digest per chunk.
        ls = { id: id, token: token, grid: grid, w: w, h: h, cw: cw, ch: ch, sig: array_create(w * h, 0),
            kind: array_create(w * h, 0), cs: array_create(cw * ch, 0), cursor: 0, seeded: false, silent: true,
            fast: true, day: false, edits: [], want: [], asked: {}, digests: [], seen: {} };
        f.locs[$ string(id)] = ls;
    }
    return ls;
}

function mistrimulti_farm_viewing(ls) {
    return ls.grid.is_setup && ls.grid.location_id == CURRENT_LOCATION_ID;
}

// Whether the grid the player is in right now is this location's.
function mistrimulti_farm_current(ls) {
    return GRID != undefined && GRID[$ "mm_farm"] == ls.token;
}

// ---- nodes: signatures, records ---------------------------------------------------------------------------------

// Only these are synchronised here; buildings, chests, decor and machines belong to other features.
function mistrimulti_farm_proto_syncable(id) {
    var proto = NODE_PROTOTYPES[id];
    switch (object_id_to_object_category(id)) {
        case ObjectCategory.Crop:
        case ObjectCategory.Tree:
        case ObjectCategory.Stump:
        case ObjectCategory.Rock:
        case ObjectCategory.Grass:
        case ObjectCategory.Bush:
        case ObjectCategory.DigSite:
            return true;
        case ObjectCategory.Furniture:
            return proto.fence == true || proto.sprinkler != undefined;
    }
    return false;
}

// Crops, trees, stumps, rocks and dig sites are written on even cells; the others anywhere.
function mistrimulti_farm_even(cat) {
    return cat == ObjectCategory.Crop || cat == ObjectCategory.Tree || cat == ObjectCategory.Stump
        || cat == ObjectCategory.Rock || cat == ObjectCategory.DigSite;
}

// Number of state values in a record, and how many of the leading ones are part of the signature (the daily
// counters of grass and dig sites are not: they change for every node every day and are of no interest).
function mistrimulti_farm_value_count(cat) {
    switch (cat) {
        case ObjectCategory.Crop: return 5;
        case ObjectCategory.Tree: return 6;
        case ObjectCategory.Grass: return 5;
        case ObjectCategory.Stump:
        case ObjectCategory.Rock:
        case ObjectCategory.Furniture:
            return 2;
    }
    return 1;
}

function mistrimulti_farm_sig_count(cat) {
    if (cat == ObjectCategory.Grass) return 4;
    if (cat == ObjectCategory.DigSite) return 0;
    return mistrimulti_farm_value_count(cat);
}

function mistrimulti_farm_num(v) {
    return is_real(v) ? clamp(round(v), -1000000, 1000000) : 0;
}

// The state of a node as whole numbers; mistrimulti_farm_set_values is the exact inverse.
function mistrimulti_farm_values(cat, node) {
    switch (cat) {
        case ObjectCategory.Crop:
            return [mistrimulti_farm_num(node[$ "ctx"]), mistrimulti_farm_num(node[$ "stage"]),
                mistrimulti_farm_num(node[$ "day_count"]), node[$ "regrow_cycle"] == true ? 1 : 0,
                is_real(node[$ "managed_timer"]) ? mistrimulti_farm_num(node.managed_timer) : -1];
        case ObjectCategory.Tree:
            return [mistrimulti_farm_num(node[$ "stage"]), mistrimulti_farm_num(node[$ "day_count"]),
                mistrimulti_farm_num(node[$ "hitpoints"]), mistrimulti_farm_num(node[$ "fruiting_days"]),
                node[$ "has_fruit"] == true ? 1 : 0, mistrimulti_farm_num((node[$ "variant_idx"] ?? 0) * 100)];
        case ObjectCategory.Stump:
        case ObjectCategory.Rock:
            return [mistrimulti_farm_num(node[$ "hitpoints"]), mistrimulti_farm_num((node[$ "variant_idx"] ?? 0) * 100)];
        case ObjectCategory.Grass:
            return [mistrimulti_farm_num((node[$ "variant_idx"] ?? 0) * 100), mistrimulti_farm_num(node[$ "offset_x"]),
                mistrimulti_farm_num(node[$ "offset_y"]), node[$ "stunt_growth"] == true ? 1 : 0,
                mistrimulti_farm_num(node[$ "day_count"])];
        case ObjectCategory.Furniture:
            return [mistrimulti_farm_num(node[$ "cardinal_index"]), mistrimulti_farm_num(node[$ "essence_supply"])];
    }
    return [mistrimulti_farm_num(node[$ "day_count"])];
}

// v is a record's state values (rec[3..]).
function mistrimulti_farm_set_values(grid, node, cat, v) {
    switch (cat) {
        case ObjectCategory.Crop:
            node.ctx = v[0];
            node.stage = v[1];
            node.day_count = v[2];
            node.regrow_cycle = v[3] != 0;
            node.managed_timer = v[4] < 0 ? undefined : v[4];
            break;
        case ObjectCategory.Tree:
            node.stage = v[0];
            node.day_count = v[1];
            node.hitpoints = v[2];
            node.fruiting_days = v[3];
            node.has_fruit = v[4] != 0;
            node.variant_idx = v[5] / 100;
            // The trunk can be jumped over only while it is a sapling (as tree_node_new_day sets it).
            for (var xx = 2; xx < 4; xx++) {
                for (var yy = 2; yy < 4; yy++) set_collision_on_node(grid, node.top_left_x + xx, node.top_left_y + yy, node.stage == 0);
            }
            break;
        case ObjectCategory.Stump:
        case ObjectCategory.Rock:
            node.hitpoints = v[0];
            node.variant_idx = v[1] / 100;
            break;
        case ObjectCategory.Grass:
            node.variant_idx = v[0] / 100;
            node.offset_x = v[1];
            node.offset_y = v[2];
            node.stunt_growth = v[3] != 0;
            node.day_count = v[4];
            break;
        case ObjectCategory.Furniture:
            if (node[$ "essence_supply"] != undefined) node.essence_supply = v[1];
            break;
        default:
            node.day_count = v[0];
    }
}

function mistrimulti_farm_record(node) {
    var rec = [object_id_to_string(node.object_id), node.top_left_x, node.top_left_y];
    var v = mistrimulti_farm_values(object_id_to_object_category(node.object_id), node);
    for (var i = 0; i < array_length(v); i++) array_push(rec, v[i]);
    return rec;
}

function mistrimulti_farm_signature(node) {
    var cat = object_id_to_object_category(node.object_id);
    var v = mistrimulti_farm_values(cat, node);
    var h = (node.object_id + 1) mod MISTRIMULTI_FARM_HASH;
    h = (h * 131 + node.top_left_x) mod MISTRIMULTI_FARM_HASH;
    h = (h * 131 + node.top_left_y) mod MISTRIMULTI_FARM_HASH;
    var n = mistrimulti_farm_sig_count(cat);
    for (var i = 0; i < n; i++) h = (h * 131 + v[i] + 1000003) mod MISTRIMULTI_FARM_HASH;
    return h + 1;
}

// A node is known by one cell: its top-left one, except for a tree, whose top-left corner is free (the engine
// leaves the corners of the 6x6 square empty), so the first cell it occupies is two to the right.
function mistrimulti_farm_probe_dx(id) {
    return object_id_to_object_category(id) == ObjectCategory.Tree ? 2 : 0;
}

// The synchronised node whose known cell is ni, or undefined.
function mistrimulti_farm_node_at(grid, ni) {
    if (grid.node_object_id[ni] == undefined) return undefined;
    var node = grid.node_parent[ni];
    if (!is_struct(node)) return undefined;
    if (node.top_left_x + mistrimulti_farm_probe_dx(node.object_id) != ni mod grid.dims.x || node.top_left_y != ni div grid.dims.x) return undefined;
    return mistrimulti_farm_proto_syncable(node.object_id) ? node : undefined;
}

function mistrimulti_farm_cell(ls, x, y) {
    if (!mistrimulti_farm_int(x) || !mistrimulti_farm_int(y) || x < 0 || y < 0 || x >= ls.w || y >= ls.h) return undefined;
    return y * ls.w + x;
}

// The known cell of the node object id would have with top-left (x, y), or undefined outside the grid.
function mistrimulti_farm_slot(ls, id, x, y) {
    return mistrimulti_farm_cell(ls, x + mistrimulti_farm_probe_dx(id), y);
}

// The node with top-left (x, y), or undefined.
function mistrimulti_farm_find(ls, x, y) {
    for (var dx = 0; dx <= 2; dx += 2) {
        var ni = mistrimulti_farm_cell(ls, x + dx, y);
        var node = ni == undefined ? undefined : mistrimulti_farm_node_at(ls.grid, ni);
        if (node != undefined && node.top_left_x == x && node.top_left_y == y) return node;
    }
    return undefined;
}

// A record that is well formed and describes an object this feature owns; returns its object id.
function mistrimulti_farm_check(ls, rec) {
    if (!is_array(rec) || array_length(rec) < 3 || !is_string(rec[0]) || !mistrimulti_farm_int(rec[1]) || !mistrimulti_farm_int(rec[2])) return undefined;
    var id = try_string_to_object_id(rec[0]);
    if (id == undefined || !mistrimulti_farm_proto_syncable(id) || mistrimulti_farm_slot(ls, id, rec[1], rec[2]) == undefined) return undefined;
    var cat = object_id_to_object_category(id);
    if (array_length(rec) != 3 + mistrimulti_farm_value_count(cat)) return undefined;
    if (mistrimulti_farm_even(cat) && (rec[1] mod 2 != 0 || rec[2] mod 2 != 0)) return undefined;
    for (var i = 3; i < array_length(rec); i++) if (!mistrimulti_farm_int(rec[i])) return undefined;
    return id;
}

// ---- the per-location signature arrays ----------------------------------------------------------------------------

function mistrimulti_farm_set(ls, ni, sig, cat) {
    var old = ls.sig[ni];
    if (old != sig) {
        var c = ((ni div ls.w) div MISTRIMULTI_FARM_CHUNK) * ls.cw + ((ni mod ls.w) div MISTRIMULTI_FARM_CHUNK);
        ls.cs[c] = (ls.cs[c] + MISTRIMULTI_FARM_HASH - old + sig) mod MISTRIMULTI_FARM_HASH;
        ls.sig[ni] = sig;
    }
    ls.kind[ni] = sig == 0 ? 0 : cat + 1;
}

// Reads the grid again at ni and stores what is there; returns the node.
function mistrimulti_farm_refresh(ls, ni) {
    var node = mistrimulti_farm_node_at(ls.grid, ni);
    if (node == undefined) mistrimulti_farm_set(ls, ni, 0, -1);
    else mistrimulti_farm_set(ls, ni, mistrimulti_farm_signature(node), object_id_to_object_category(node.object_id));
    return node;
}

// A guest's own change that the scanner has not reached yet is reported before the host's state replaces it
// (otherwise two players planting the same tile at once would leave the loser without a refund).
function mistrimulti_farm_note_local(ls, ni) {
    if (ls.silent || __mistrimulti_runtime().mode != "join") return;
    var node = mistrimulti_farm_node_at(ls.grid, ni);
    var cur = node == undefined ? 0 : mistrimulti_farm_signature(node);
    if (cur == ls.sig[ni]) return;
    var was = ls.kind[ni];
    mistrimulti_farm_set(ls, ni, cur, node == undefined ? -1 : object_id_to_object_category(node.object_id));
    mistrimulti_farm_guest_change(ls, ni, was, node);
}

function mistrimulti_farm_erase(ls, ni) {
    mistrimulti_farm_note_local(ls, ni);
    var node = mistrimulti_farm_node_at(ls.grid, ni);
    if (node == undefined) return false;
    erase_object_node_by_parent(ls.grid, node);
    mistrimulti_farm_set(ls, ni, 0, -1);
    return true;
}

function mistrimulti_farm_redraw(ls, node) {
    if (!mistrimulti_farm_viewing(ls)) return;
    erase_object_renderer(node);
    ls.grid.initialize_node_renderer(node);
}

// ---- writing nodes ----------------------------------------------------------------------------------------------

function mistrimulti_farm_rotation(id, cardinal_index) {
    var cs = NODE_PROTOTYPES[id].cardinals;
    for (var j = 0; j < array_length(cs); j++) if (cs[j] == cardinal_index) return j;
    return 0;
}

// A node prototype's footprint in cells. Not every prototype has a size in the real game (crops, grass): those are 2x2.
function mistrimulti_node_size(id) {
    var size = NODE_PROTOTYPES[id][$ "size"];
    if (!is_struct(size) || !is_real(size[$ "x"]) || !is_real(size[$ "y"])) return { x: 2, y: 2 };
    return size;
}

// Removes the synchronised nodes in the way of a node about to be written (a stale copy of the same area).
function mistrimulti_farm_clear(ls, id, x, y) {
    var cat = object_id_to_object_category(id);
    if (cat == ObjectCategory.Furniture) return;
    var size = mistrimulti_node_size(id);
    var sx = cat == ObjectCategory.Tree ? 6 : size.x;
    var sy = cat == ObjectCategory.Tree ? 6 : size.y;
    for (var xx = 0; xx < sx; xx++) {
        for (var yy = 0; yy < sy; yy++) {
            if (cat == ObjectCategory.Tree && (xx < 2 || xx > 3) && (yy < 2 || yy > 3)) continue; // the tree's corners stay free
            var ni = mistrimulti_farm_cell(ls, x + xx, y + yy);
            if (ni == undefined || ls.grid.node_object_id[ni] == undefined) continue;
            var blocker = ls.grid.node_parent[ni];
            if (is_struct(blocker) && mistrimulti_farm_proto_syncable(blocker.object_id)) {
                var anchor = mistrimulti_farm_slot(ls, blocker.object_id, blocker.top_left_x, blocker.top_left_y);
                if (anchor != undefined) mistrimulti_farm_erase(ls, anchor);
            }
        }
    }
}

// Makes the grid hold the node described by rec. fresh: take only the object and place from rec and leave the
// state to the game's own defaults (a new planting). Returns the node, or undefined when it does not fit.
function mistrimulti_farm_apply(ls, rec, fresh) {
    var f = mistrimulti_farm_state();
    try {
        var id = mistrimulti_farm_check(ls, rec);
        if (id == undefined) return undefined;
        var cat = object_id_to_object_category(id);
        var ni = mistrimulti_farm_slot(ls, id, rec[1], rec[2]);
        var v = [];
        for (var i = 3; i < array_length(rec); i++) array_push(v, rec[i]);
        mistrimulti_farm_note_local(ls, ni);
        var node = mistrimulti_farm_node_at(ls.grid, ni);
        var same = node != undefined && node.object_id == id
            && (cat != ObjectCategory.Furniture || node.cardinal_index == v[0]);
        var before = same ? mistrimulti_farm_signature(node) : 0;
        if (!same) {
            if (node != undefined) mistrimulti_farm_erase(ls, ni);
            mistrimulti_farm_clear(ls, id, rec[1], rec[2]);
            var ctx = undefined;
            if (cat == ObjectCategory.Crop) ctx = fresh ? 0 : v[0];
            else if (cat == ObjectCategory.Furniture) ctx = mistrimulti_farm_rotation(id, v[0]);
            node = ls.grid.write_node_without_initializing(rec[1], rec[2], id, ctx);
            if (node == undefined) {
                mistrimulti_farm_refresh(ls, ni);
                return undefined;
            }
        }
        if (!fresh) mistrimulti_farm_set_values(ls.grid, node, cat, v);
        if (!same || mistrimulti_farm_signature(node) != before) mistrimulti_farm_redraw(ls, node);
        mistrimulti_farm_refresh(ls, ni);
        return node;
    } catch (e) {
        mistrimulti_farm_fail(f, e);
        return undefined;
    }
}

// A host change: {l, n: [records], g: [[x, y], ...]}; removals first.
function mistrimulti_farm_apply_change(data) {
    var ls = mistrimulti_farm_loc(data[$ "l"]);
    if (ls == undefined) return;
    var g = data[$ "g"];
    if (is_array(g)) {
        for (var i = 0; i < min(array_length(g), 64); i++) {
            var cell = g[i];
            var ni = is_array(cell) && array_length(cell) == 2 ? mistrimulti_farm_cell(ls, cell[0], cell[1]) : undefined;
            if (ni != undefined) mistrimulti_farm_erase(ls, ni);
        }
    }
    var n = data[$ "n"];
    if (is_array(n)) {
        for (var j = 0; j < min(array_length(n), 64); j++) mistrimulti_farm_apply(ls, n[j], false);
    }
}

// ---- the scanner --------------------------------------------------------------------------------------------------

// Looks at up to budget cells of one location, continuing where it stopped. Returns the number looked at.
function mistrimulti_farm_scan(r, f, ls, budget) {
    var grid = ls.grid;
    var total = ls.w * ls.h;
    var host = r.mode == "host";
    var done = 0;
    budget = min(budget, total); // never more than one pass at a time
    while (done < budget && !(host && f.full)) {
        var from = ls.cursor;
        var to = min(from + min(budget - done, 256), total);
        for (var ni = from; ni < to; ni++) {
            if (ls.sig[ni] == 0 && grid.node_object_id[ni] == undefined) continue;
            var node = mistrimulti_farm_node_at(grid, ni);
            var cur = node == undefined ? 0 : mistrimulti_farm_signature(node);
            if (cur == ls.sig[ni]) continue;
            var was = ls.kind[ni];
            mistrimulti_farm_set(ls, ni, cur, node == undefined ? -1 : object_id_to_object_category(node.object_id));
            if (ls.silent) continue;
            if (host) mistrimulti_farm_publish(f, ls, ni, node);
            else mistrimulti_farm_guest_change(ls, ni, was, node);
        }
        done += to - from;
        ls.cursor = to;
        if (to >= total) {
            ls.cursor = 0;
            mistrimulti_farm_wrapped(f, ls);
        }
    }
    return done;
}

// One full pass is complete: the signatures describe the grid.
function mistrimulti_farm_wrapped(f, ls) {
    ls.silent = false;
    ls.seeded = true;
    ls.fast = false;
    if (ls.day) {
        ls.day = false;
        f.day_left = max(f.day_left - 1, 0);
    }
}

function mistrimulti_farm_scan_all(r, f) {
    var ids = mistrimulti_farm_location_ids(f);
    var count = array_length(ids);
    var left = MISTRIMULTI_FARM_SCAN_TICK;
    var current = -1;
    for (var i = 0; i < count; i++) if (ids[i] == CURRENT_LOCATION_ID) current = i;
    if (current >= 0) {
        var here = mistrimulti_farm_loc(ids[current]);
        if (here != undefined) left -= mistrimulti_farm_scan(r, f, here, here.fast ? MISTRIMULTI_FARM_SCAN_FAST : MISTRIMULTI_FARM_SCAN_CURRENT);
    }
    for (var k = 0; k < count && left > 0; k++) {
        var j = (f.rotate + k) mod count;
        if (j == current) continue;
        var ls = mistrimulti_farm_loc(ids[j]);
        if (ls == undefined) continue;
        left -= mistrimulti_farm_scan(r, f, ls, min(left, ls.fast ? MISTRIMULTI_FARM_SCAN_FAST : MISTRIMULTI_FARM_SCAN_OTHER));
    }
    f.rotate = count > 0 ? (f.rotate + 1) mod count : 0;
}

// ---- host: publishing, digests, chunks ------------------------------------------------------------------------------

// Queues the current state of one anchor for the next "farm_delta"; the latest state of an anchor wins.
function mistrimulti_farm_publish(f, ls, ni, node) {
    var key = string(ls.id) + ":" + string(ni);
    var entry = node == undefined ? { l: ls.id, g: [ni mod ls.w, ni div ls.w] } : { l: ls.id, n: mistrimulti_farm_record(node) };
    if (!struct_exists(f.pending, key)) array_push(f.pending_keys, key);
    f.pending[$ key] = entry;
    f.full = array_length(f.pending_keys) >= MISTRIMULTI_FARM_PENDING;
}

function mistrimulti_farm_flush(f) {
    while (array_length(f.pending_keys) > 0 && mistrimulti_event_backlog() < MISTRIMULTI_FARM_BACKLOG && mistrimulti_event_can_emit(2)) {
        var loc = f.pending[$ f.pending_keys[0]].l;
        var data = { l: loc, n: [], g: [] };
        var taken = 0;
        while (taken < array_length(f.pending_keys) && taken < MISTRIMULTI_FARM_BATCH) {
            var entry = f.pending[$ f.pending_keys[taken]];
            if (entry.l != loc) break;
            if (is_array(entry[$ "n"])) array_push(data.n, entry.n);
            else array_push(data.g, entry.g);
            taken++;
        }
        if (!mistrimulti_event_emit("farm_delta", data)) return;
        for (var i = 0; i < taken; i++) struct_remove(f.pending, f.pending_keys[i]);
        array_delete(f.pending_keys, 0, taken);
    }
    f.full = array_length(f.pending_keys) >= MISTRIMULTI_FARM_PENDING;
}

// slot: one guest, or -1 for everyone.
function mistrimulti_farm_queue_digest(f, slot) {
    for (var i = 0; i < array_length(f.jobs); i++) if (f.jobs[i].slot == slot && f.jobs[i].i == 0 && f.jobs[i].o == 0) return;
    array_push(f.jobs, { slot: slot, i: 0, o: 0 });
}

// Sends the digests queued by joins, hellos, day changes and the minute timer, a few events per tick, when
// every change seen so far has been published.
function mistrimulti_farm_send_digests(f) {
    var ids = mistrimulti_farm_location_ids(f);
    var sent = 0;
    while (array_length(f.jobs) > 0 && sent < 2 && array_length(f.pending_keys) == 0
        && mistrimulti_event_backlog() < MISTRIMULTI_FARM_BACKLOG && mistrimulti_event_can_emit(2)) {
        var job = f.jobs[0];
        if (job.i >= array_length(ids)) {
            array_delete(f.jobs, 0, 1);
            continue;
        }
        var ls = mistrimulti_farm_loc(ids[job.i]);
        if (ls == undefined) {
            job.i++;
            job.o = 0;
            continue;
        }
        if (!ls.seeded) break;
        var d = [];
        var stop = min(job.o + 128, array_length(ls.cs));
        for (var c = job.o; c < stop; c++) array_push(d, ls.cs[c]);
        if (!mistrimulti_event_emit("farm_digest", { l: ls.id, n: array_length(ls.cs), o: job.o, d: d }, job.slot)) break;
        sent++;
        job.o = stop;
        if (job.o >= array_length(ls.cs)) {
            job.i++;
            job.o = 0;
        }
    }
}

function mistrimulti_farm_chunk_cells(ls, c) {
    var cells = [];
    var x0 = (c mod ls.cw) * MISTRIMULTI_FARM_CHUNK;
    var y0 = (c div ls.cw) * MISTRIMULTI_FARM_CHUNK;
    for (var y = y0; y < min(y0 + MISTRIMULTI_FARM_CHUNK, ls.h); y++) {
        for (var x = x0; x < min(x0 + MISTRIMULTI_FARM_CHUNK, ls.w); x++) array_push(cells, y * ls.w + x);
    }
    return cells;
}

// Sends the chunks guests asked for, whole chunks only (the guest prunes what the chunk does not list).
function mistrimulti_farm_send_chunks(r, f) {
    var sent = 0;
    while (array_length(f.chunks) > 0 && sent < 4 && mistrimulti_event_backlog() < MISTRIMULTI_FARM_BACKLOG && mistrimulti_event_can_emit(4)) {
        var job = f.chunks[0];
        array_delete(f.chunks, 0, 1);
        var ls = mistrimulti_farm_loc(job.l);
        if (ls == undefined || (r.mask & (1 << job.slot)) == 0) continue;
        var cells = mistrimulti_farm_chunk_cells(ls, job.c);
        var recs = [];
        for (var i = 0; i < array_length(cells); i++) {
            var node = mistrimulti_farm_node_at(ls.grid, cells[i]);
            if (node != undefined) array_push(recs, mistrimulti_farm_record(node));
        }
        var slices = max(1, (array_length(recs) + MISTRIMULTI_FARM_BATCH - 1) div MISTRIMULTI_FARM_BATCH);
        for (var s = 0; s < slices; s++) {
            var part = [];
            for (var k = s * MISTRIMULTI_FARM_BATCH; k < min(array_length(recs), (s + 1) * MISTRIMULTI_FARM_BATCH); k++) array_push(part, recs[k]);
            mistrimulti_event_emit("farm_chunk", { l: ls.id, c: job.c, n: part, e: s == slices - 1 ? 1 : 0 }, job.slot);
        }
        sent++;
    }
}

function mistrimulti_farm_host_tick(r, f) {
    if (r.mask == 0) {
        f.idle = true; // nobody to tell: stop scanning, and look at everything again when somebody arrives
        return;
    }
    var ids = mistrimulti_farm_location_ids(f);
    if (f.idle) {
        f.idle = false;
        for (var i = 0; i < array_length(ids); i++) {
            var ls = mistrimulti_farm_loc(ids[i]);
            if (ls != undefined) {
                ls.cursor = 0;
                ls.silent = true;
                ls.seeded = false;
                ls.fast = true;
            }
        }
    }
    mistrimulti_farm_scan_all(r, f);
    mistrimulti_farm_flush(f);
    if (f.day_flag && f.day_left == 0) {
        f.day_flag = false;
        mistrimulti_farm_queue_digest(f, -1);
    }
    f.tick++;
    if (f.tick >= f.next_digest) {
        f.next_digest = f.tick + MISTRIMULTI_FARM_RECONCILE;
        mistrimulti_farm_queue_digest(f, -1);
    }
    mistrimulti_farm_send_digests(f);
    mistrimulti_farm_send_chunks(r, f);
}

// A game that just joined (or re-entered the world) has not seen our deltas: send it the digests.
function mistrimulti_farm_peer(slot, joined, stream) {
    var r = __mistrimulti_runtime();
    var f = mistrimulti_farm_state();
    if (r.mode == "join") {
        if (slot == 0) mistrimulti_farm_forget_requests(f); // the host started over: it sends the digests again
        return;
    }
    for (var i = array_length(f.jobs) - 1; i >= 0; i--) if (f.jobs[i].slot == slot) array_delete(f.jobs, i, 1);
    for (var j = array_length(f.chunks) - 1; j >= 0; j--) if (f.chunks[j].slot == slot) array_delete(f.chunks, j, 1);
    if (joined && slot > 0) mistrimulti_farm_queue_digest(f, slot);
}

// Host events missed while this game was away: ask for the digests again.
function mistrimulti_farm_gap(slot, base, expected) {
    if (slot == 0 && __mistrimulti_runtime().mode == "join") mistrimulti_farm_forget_requests(mistrimulti_farm_state());
}

function mistrimulti_farm_hello_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode == "host" && player > 0) mistrimulti_farm_queue_digest(mistrimulti_farm_state(), player);
    return true;
}

function mistrimulti_farm_want_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    var f = mistrimulti_farm_state();
    if (r.mode != "host" || player < 1 || player > 7 || !is_struct(data) || !is_array(data[$ "c"])) return true;
    var ls = mistrimulti_farm_loc(data[$ "l"]);
    if (ls == undefined) return true;
    for (var i = 0; i < min(array_length(data.c), 32); i++) {
        var c = data.c[i];
        if (!mistrimulti_farm_int(c) || c < 0 || c >= array_length(ls.cs) || array_length(f.chunks) >= 512) continue;
        array_push(f.chunks, { slot: player, l: ls.id, c: c });
    }
    return true;
}

// ---- guest: applying what the host sends ------------------------------------------------------------------------------

function mistrimulti_farm_from_host(player) {
    var r = __mistrimulti_runtime();
    return player == 0 && r.mode == "join" && mistrimulti_farm_ok(mistrimulti_farm_state());
}

function mistrimulti_farm_delta_event(player, data, ctx) {
    if (mistrimulti_farm_from_host(player) && is_struct(data)) mistrimulti_farm_apply_change(data);
    return true;
}

function mistrimulti_farm_digest_event(player, data, ctx) {
    if (!mistrimulti_farm_from_host(player) || !is_struct(data) || !is_array(data[$ "d"])) return true;
    var ls = mistrimulti_farm_loc(data[$ "l"]);
    if (ls == undefined || array_length(data.d) > 128 || !mistrimulti_farm_int(data[$ "o"]) || data.o < 0) return true;
    if (ls.seeded) mistrimulti_farm_compare(mistrimulti_farm_state(), ls, data);
    else if (array_length(ls.digests) < 16) array_push(ls.digests, data); // compared once the first pass is done
    return true;
}

// Chunks whose digest differs from the host's are wanted.
function mistrimulti_farm_compare(f, ls, data) {
    for (var i = 0; i < array_length(data.d); i++) {
        var c = data.o + i;
        if (c >= array_length(ls.cs) || ls.cs[c] == data.d[i]) continue;
        var key = string(c);
        var asked = ls.asked[$ key];
        if (asked != undefined && f.tick - asked < MISTRIMULTI_FARM_RECONCILE) continue;
        ls.asked[$ key] = f.tick;
        array_push(ls.want, c);
    }
}

// A whole chunk from the host: write its nodes, and on the last slice remove those it does not list.
function mistrimulti_farm_chunk_event(player, data, ctx) {
    if (!mistrimulti_farm_from_host(player) || !is_struct(data) || !is_array(data[$ "n"])) return true;
    var f = mistrimulti_farm_state();
    var ls = mistrimulti_farm_loc(data[$ "l"]);
    var c = data[$ "c"];
    if (ls == undefined || !mistrimulti_farm_int(c) || c < 0 || c >= array_length(ls.cs) || array_length(data.n) > MISTRIMULTI_FARM_BATCH) return true;
    for (var k = 0; k < array_length(data.n); k++) if (mistrimulti_farm_check(ls, data.n[k]) == undefined) return true; // a damaged slice is dropped whole
    var key = string(c);
    if (!is_struct(ls.seen[$ key])) ls.seen[$ key] = {};
    var seen = ls.seen[$ key];
    for (var i = 0; i < array_length(data.n); i++) {
        var rec = data.n[i];
        mistrimulti_farm_apply(ls, rec, false); // a node that does not fit here is kept out; the digest will say so again
        seen[$ string(mistrimulti_farm_slot(ls, try_string_to_object_id(rec[0]), rec[1], rec[2]))] = true;
    }
    if (data[$ "e"] == 1) {
        var cells = mistrimulti_farm_chunk_cells(ls, c);
        for (var j = 0; j < array_length(cells); j++) {
            if (!struct_exists(seen, string(cells[j]))) mistrimulti_farm_erase(ls, cells[j]);
        }
        struct_remove(ls.seen, key);
        struct_remove(ls.asked, key);
    }
    return true;
}

// ---- guest: noticing its own hand-made changes ------------------------------------------------------------------------

// The cell now holds node (undefined: nothing) and held a node of category was - 1 (0: nothing). Only
// plantings, fences and removals with no yield are reported; growth and anything else is the host's to say.
function mistrimulti_farm_guest_change(ls, ni, was, node) {
    var x = ni mod ls.w;
    var y = ni div ls.w;
    var entry = undefined;
    if (node != undefined && was == 0) {
        var cat = object_id_to_object_category(node.object_id);
        var planted = (cat == ObjectCategory.Crop && node[$ "ctx"] == 0) || (cat == ObjectCategory.Tree && node[$ "stage"] == 0)
            || cat == ObjectCategory.Grass || cat == ObjectCategory.Furniture;
        if (planted) entry = ["a", mistrimulti_farm_record(node)];
    } else if (node == undefined && was != 0) {
        var gone = was - 1;
        if (gone == ObjectCategory.Grass) entry = ["c", x, y];
        else if (gone == ObjectCategory.Crop || gone == ObjectCategory.Furniture) entry = ["r", x, y];
    } else if (node != undefined && was == ObjectCategory.Furniture + 1 && object_id_to_object_category(node.object_id) == ObjectCategory.Furniture) {
        // A furniture piece changed in place: a charged sprinkler (the host accepts a higher charge only).
        var supply = node[$ "essence_supply"];
        if (is_real(supply) && supply > 0) entry = ["s", x, y, mistrimulti_farm_num(supply)];
    }
    if (entry != undefined && array_length(ls.edits) < 256) array_push(ls.edits, entry);
}

function mistrimulti_farm_send_edits(r, f, ls) {
    while (array_length(ls.edits) > 0) {
        var batch = [];
        for (var i = 0; i < min(array_length(ls.edits), MISTRIMULTI_FARM_EDITS); i++) array_push(batch, ls.edits[i]);
        if (mistrimulti_event_request("farm_act", { a: "edit", l: ls.id, e: batch }) == undefined) return;
        array_delete(ls.edits, 0, array_length(batch));
    }
}

function mistrimulti_farm_guest_tick(r, f) {
    if ((r.mask & 1) == 0) return; // no host: nothing can be asked
    var ids = mistrimulti_farm_location_ids(f);
    mistrimulti_farm_scan_all(r, f);
    f.tick++;
    for (var i = 0; i < array_length(ids); i++) {
        var ls = mistrimulti_farm_loc(ids[i]);
        if (ls == undefined) continue;
        mistrimulti_farm_send_edits(r, f, ls);
        if (ls.seeded && array_length(ls.digests) > 0) {
            for (var d = 0; d < array_length(ls.digests); d++) mistrimulti_farm_compare(f, ls, ls.digests[d]);
            ls.digests = [];
        }
        if (array_length(ls.want) > 0 && mistrimulti_event_can_emit(2)) {
            var batch = [];
            while (array_length(ls.want) > 0 && array_length(batch) < 24) array_push(batch, array_pop(ls.want));
            if (!mistrimulti_event_emit("farm_want", { l: ls.id, c: batch }, 0)) {
                for (var b = 0; b < array_length(batch); b++) array_push(ls.want, batch[b]);
            }
        }
    }
    if (f.hello && mistrimulti_event_emit("farm_hello", {}, 0)) f.hello = false;
    if (f.tick mod 600 == 0) mistrimulti_farm_expire(r, f);
}

// Forgets old button presses and chunk requests that were never answered.
function mistrimulti_farm_expire(r, f) {
    var names = struct_get_names(f.press);
    for (var i = 0; i < array_length(names); i++) if (r.ticks - f.press[$ names[i]] > MISTRIMULTI_FARM_PRESS) struct_remove(f.press, names[i]);
    var ids = mistrimulti_farm_location_ids(f);
    for (var k = 0; k < array_length(ids); k++) {
        var ls = mistrimulti_farm_loc(ids[k]);
        if (ls == undefined) continue;
        names = struct_get_names(ls.asked);
        for (var m = 0; m < array_length(names); m++) {
            if (f.tick - ls.asked[$ names[m]] > MISTRIMULTI_FARM_RECONCILE) struct_remove(ls.asked, names[m]);
        }
    }
}

// The host's stream changed or events were missed: chunk requests in flight will never be answered.
function mistrimulti_farm_forget_requests(f) {
    var ids = mistrimulti_farm_location_ids(f);
    for (var k = 0; k < array_length(ids); k++) {
        var ls = mistrimulti_farm_loc(ids[k]);
        if (ls == undefined) continue;
        ls.asked = {};
        ls.want = [];
        ls.seen = {};
    }
    f.hello = true;
}

// ---- tick and day change ------------------------------------------------------------------------------------------------

// Called from the bridge tick while a world is loaded.
function mistrimulti_farm_tick() {
    var r = __mistrimulti_runtime();
    var f = mistrimulti_farm_state();
    if (!r.enabled || !mistrimulti_farm_ok(f)) return;
    try {
        if (r.mode == "host") mistrimulti_farm_host_tick(r, f);
        else mistrimulti_farm_guest_tick(r, f);
    } catch (e) {
        mistrimulti_farm_fail(f, e);
    }
}

// The day's growth, spawns and weather ran in this game. The host publishes what changed and then the digests;
// a guest throws away what it has seen of its own and asks for the host's.
function mistrimulti_farm_new_day(ctx) {
    var r = __mistrimulti_runtime();
    var f = mistrimulti_farm_state();
    if (!r.enabled || !mistrimulti_farm_ok(f)) return;
    var ids = mistrimulti_farm_location_ids(f);
    f.day_left = 0;
    for (var i = 0; i < array_length(ids); i++) {
        var ls = mistrimulti_farm_loc(ids[i]);
        if (ls == undefined) continue;
        ls.cursor = 0;
        ls.fast = true;
        if (r.mode == "host") {
            ls.day = true;
            f.day_left++;
        } else {
            ls.silent = true;
            ls.seeded = false;
            ls.edits = [];
        }
    }
    if (r.mode == "host") f.day_flag = f.day_left > 0;
    else f.hello = true;
}

// ---- guest: gating actions with a yield ---------------------------------------------------------------------------------

// The hooks below act only on a guest that has a host, in a synchronised location.
function mistrimulti_farm_gate(r, f) {
    return r.enabled && r.mode == "join" && (r.mask & 1) != 0 && f.bypass == 0 && mistrimulti_farm_ok(f)
        && GRID != undefined && GRID.dyn_index == undefined;
}

// Which request the tool use on this cell becomes, or "" when the engine may handle it.
function mistrimulti_farm_swing_kind(ls, tool, x, y) {
    var grid = ls.grid;
    if (tool == ToolType.Axe) {
        var ni = grid.try_node_index_for_cell(x, y);
        if (ni == undefined || grid.node_object_id[ni] == undefined) return "";
        var node = grid.node_parent[ni];
        var cat = object_id_to_object_category(node.object_id);
        if (cat == ObjectCategory.Stump) return "chop";
        if (cat == ObjectCategory.Tree && x >= node.top_left_x + 2 && x <= node.top_left_x + 3 && y >= node.top_left_y + 2 && y <= node.top_left_y + 3) return "chop";
    } else if (tool == ToolType.PickAxe) {
        // pick_node works on the first node in the 2x2 box at the cell.
        for (var xx = 0; xx < 2; xx++) {
            for (var yy = 0; yy < 2; yy++) {
                var pi = grid.try_node_index_for_cell(x + xx, y + yy);
                if (pi == undefined || grid.node_object_id[pi] == undefined) continue;
                var pc = object_id_to_object_category(grid.node_object_id[pi]);
                if (pc == ObjectCategory.Rock || grid.node_object_id[pi] == ObjectId.DigSite) return "pick";
                return "";
            }
        }
    } else if (tool == ToolType.Shovel) {
        var si = grid.try_node_index_for_cell((x div 2) * 2, (y div 2) * 2);
        if (si != undefined && grid.node_object_id[si] == ObjectId.DigSite) return "dig";
    }
    return "";
}

// tool.targets: a guest's axe, pickaxe and shovel never hit a synchronised node themselves. The cell is taken
// out of the list and asked of the host once the swing is final; the swing is played out when the result comes.
function mistrimulti_farm_tool_targets(value, ctx) {
    var r = __mistrimulti_runtime();
    var f = mistrimulti_farm_state();
    if (!mistrimulti_farm_gate(r, f)) return undefined;
    try {
        var tool = ctx.item.prototype.tool_type;
        if (tool != ToolType.Axe && tool != ToolType.PickAxe && tool != ToolType.Shovel) return undefined;
        var ls = mistrimulti_farm_loc(CURRENT_LOCATION_ID);
        if (ls == undefined || !mistrimulti_farm_current(ls)) return undefined;
        // This hook runs every frame of a swing; a gap between calls means a new swing, which may ask again.
        if (r.ticks - f.swing_at > 3) f.swing = {};
        f.swing_at = r.ticks;
        // A tool that charges is final once the button is released; one that cannot charge swings at once.
        var released = quality_to_range_pattern(ctx.item.prototype.quality) == RangePattern.One || !INPUT.check(InputId.UseToolCharged);
        var keep = List();
        var taken = false;
        var asked = 0;
        for (var i = 0; i < value.count(); i++) {
            var cell = value.get(i);
            var kind = mistrimulti_farm_swing_kind(ls, tool, cell.x, cell.y);
            if (kind == "") {
                keep.push(cell);
                continue;
            }
            taken = true;
            if (released && asked < MISTRIMULTI_FARM_EDITS && mistrimulti_farm_ask(f, kind, ls, cell.x, cell.y, ctx)) asked++;
        }
        return taken ? keep : undefined;
    } catch (e) {
        mistrimulti_farm_fail(f, e);
        return undefined;
    }
}

// Sends a swing request once per cell and swing. Returns whether it was sent now.
function mistrimulti_farm_ask(f, kind, ls, x, y, ctx) {
    var key = kind + ":" + string(ls.id) + ":" + string(x) + ":" + string(y);
    if (struct_exists(f.swing, key)) return false;
    var data = { a: kind, l: ls.id, x: x, y: y, i: item_id_to_string(ctx.item.item_id), c: ctx.range_pattern == RangePattern.One ? 0 : 1 };
    if (mistrimulti_event_request("farm_act", data) == undefined) return false;
    f.swing[$ key] = true;
    return true;
}

// object.interact: a guest's harvest of a crop, bush or tree is asked of the host first.
function mistrimulti_farm_interact(node) {
    var r = __mistrimulti_runtime();
    var f = mistrimulti_farm_state();
    if (!mistrimulti_farm_gate(r, f)) return undefined;
    try {
        var cat = object_id_to_object_category(node.object_id);
        if (cat != ObjectCategory.Crop && cat != ObjectCategory.Bush && cat != ObjectCategory.Tree) return undefined;
        var ls = mistrimulti_farm_loc(CURRENT_LOCATION_ID);
        if (ls == undefined || !mistrimulti_farm_current(ls) || !can_interact(node)) return undefined;
        var key = string(ls.id) + ":" + string(node.top_left_x) + ":" + string(node.top_left_y);
        var last = f.press[$ key];
        if (last == undefined || r.ticks - last >= MISTRIMULTI_FARM_PRESS) {
            if (mistrimulti_event_request("farm_act", { a: "harvest", l: ls.id, x: node.top_left_x, y: node.top_left_y }) != undefined) f.press[$ key] = r.ticks;
        }
        return true; // claimed: the engine's own harvest runs when the host agrees
    } catch (e) {
        mistrimulti_farm_fail(f, e);
        return undefined;
    }
}

// ---- host: validating and applying a guest's request ---------------------------------------------------------------------

function mistrimulti_farm_reach(peer, ls, x, y) {
    return is_struct(peer) && peer[$ "active"] == true && peer[$ "room"] == location_id_to_string(ls.id) + ":" + string(undefined)
        && is_real(peer[$ "x"]) && is_real(peer[$ "y"])
        && point_distance(peer.x, peer.y, x * 8 + 8, y * 8 + 8) <= MISTRIMULTI_FARM_REACH;
}

// Adds the current state of anchor ni to a result and to the pending publication.
function mistrimulti_farm_touch(f, ls, res, ni) {
    var node = mistrimulti_farm_refresh(ls, ni);
    var key = string(ls.id) + ":" + string(ni);
    var entry;
    if (node == undefined) {
        entry = { l: ls.id, g: [ni mod ls.w, ni div ls.w] };
        if (array_length(res.g) < 32) array_push(res.g, entry.g);
    } else {
        entry = { l: ls.id, n: mistrimulti_farm_record(node) };
        if (array_length(res.n) < 32) array_push(res.n, entry.n);
    }
    if (struct_exists(f.pending, key)) f.pending[$ key] = entry; // an older state must not be published after this one
}

function mistrimulti_farm_request(player, data, ctx) {
    var r = __mistrimulti_runtime();
    var f = mistrimulti_farm_state();
    var refuse = { ok: false };
    if (r.mode != "host" || player < 1 || !is_struct(data) || !mistrimulti_farm_ok(f) || !is_string(data[$ "a"])) return refuse;
    var peer = r.peers[player];
    var ls = mistrimulti_farm_loc(data[$ "l"]);
    if (ls == undefined || !is_struct(peer) || peer[$ "active"] != true) return refuse;
    var res = { ok: false, a: data.a, l: ls.id, n: [], g: [] };
    try {
        if (data.a == "edit") mistrimulti_farm_op_edit(f, ls, peer, data, res);
        else if (mistrimulti_farm_cell(ls, data[$ "x"], data[$ "y"]) != undefined) {
            res.x = data.x;
            res.y = data.y;
            if (data.a == "harvest") mistrimulti_farm_op_harvest(f, ls, peer, res);
            else if (data.a == "chop" || data.a == "pick" || data.a == "dig") mistrimulti_farm_op_tool(f, ls, peer, data, res);
        }
    } catch (e) {
        mistrimulti_farm_fail(f, e);
        res.ok = false;
    }
    return res;
}

// Replays process_crop_harvest and interact() on the node's state only: the harvester gets the yield and the
// effects on its own game, and the host must not drop items or play effects for somebody else's action.
function mistrimulti_farm_op_harvest(f, ls, peer, res) {
    var grid = ls.grid;
    var node = mistrimulti_farm_find(ls, res.x, res.y);
    var ni = node == undefined ? mistrimulti_farm_cell(ls, res.x, res.y) : mistrimulti_farm_slot(ls, node.object_id, node.top_left_x, node.top_left_y);
    var cat = node == undefined ? -1 : object_id_to_object_category(node.object_id);
    if (node == undefined || (cat != ObjectCategory.Crop && cat != ObjectCategory.Bush && cat != ObjectCategory.Tree)
        || !mistrimulti_farm_reach(peer, ls, res.x, res.y) || !can_interact(node)) {
        mistrimulti_farm_touch(f, ls, res, ni);
        return;
    }
    res.p = mistrimulti_farm_record(node);
    var proto = node.prototype;
    if (cat == ObjectCategory.Crop) {
        res.yi = [item_id_to_string(proto.harvest), proto.count];
        var destroy = true;
        if (has_flag(node.ctx, CropFlag.MANAGED)) destroy = false;
        if (proto.post_harvest_day_to_stage != undefined) {
            node.regrow_cycle = true;
            node.day_count = 0;
            node.stage = proto.post_harvest_day_to_stage.get(0);
            destroy = false;
        }
        if (has_flag(node.ctx, CropFlag.FORAGEABLE)) destroy = true;
        if (destroy) erase_object_node_by_parent(grid, node);
        else {
            if (has_flag(node.ctx, CropFlag.MANAGED)) node.managed_timer = proto.managed_regrow_days;
            mistrimulti_farm_redraw(ls, node);
        }
    } else if (cat == ObjectCategory.Bush) {
        res.yi = [item_id_to_string(proto.harvest), proto.count];
        node.day_count = 0;
        mistrimulti_farm_redraw(ls, node);
    } else {
        node.has_fruit = false;
        node.fruiting_days = 0;
        mistrimulti_farm_redraw(ls, node);
    }
    res.ok = true;
    mistrimulti_farm_touch(f, ls, res, ni);
}

// chop, pick and dig: the damage rules of chop_node, pick_node and shovel_node, applied to the state only.
function mistrimulti_farm_op_tool(f, ls, peer, data, res) {
    var grid = ls.grid;
    var itemid = is_string(data[$ "i"]) ? try_string_to_item_id(data.i) : undefined;
    var proto = itemid == undefined ? undefined : ITEM_PROTOTYPES[itemid];
    var wanted = data.a == "chop" ? ToolType.Axe : (data.a == "pick" ? ToolType.PickAxe : ToolType.Shovel);
    var cell = mistrimulti_farm_cell(ls, data.x, data.y);
    if (proto == undefined || proto.tool_type != wanted || !mistrimulti_farm_reach(peer, ls, data.x, data.y)) {
        mistrimulti_farm_touch(f, ls, res, cell);
        return;
    }
    res.i = data.i;
    res.c = data[$ "c"] == 1 ? 1 : 0;
    var modifier = res.c == 1 ? -1 : 0;
    var damage = proto.damage + modifier;
    var node = undefined;
    var ni = cell;
    if (data.a == "dig") {
        ni = mistrimulti_farm_cell(ls, (data.x div 2) * 2, (data.y div 2) * 2);
        if (ni != undefined && grid.node_object_id[ni] == ObjectId.DigSite) node = grid.node_parent[ni];
    } else if (data.a == "pick") {
        for (var xx = 0; xx < 2 && node == undefined; xx++) {
            for (var yy = 0; yy < 2 && node == undefined; yy++) {
                var pi = grid.try_node_index_for_cell(data.x + xx, data.y + yy);
                if (pi != undefined && grid.node_object_id[pi] != undefined) {
                    ni = pi;
                    node = grid.node_parent[pi];
                }
            }
        }
    } else if (grid.node_object_id[ni] != undefined) {
        node = grid.node_parent[ni];
    }
    if (node == undefined) {
        mistrimulti_farm_touch(f, ls, res, cell);
        return;
    }
    var cat = object_id_to_object_category(node.object_id);
    var anchor = mistrimulti_farm_slot(ls, node.object_id, node.top_left_x, node.top_left_y);
    res.p = mistrimulti_farm_record(node);
    if (data.a == "chop" && cat == ObjectCategory.Tree) {
        var trunk = data.x >= node.top_left_x + 2 && data.x <= node.top_left_x + 3 && data.y >= node.top_left_y + 2 && data.y <= node.top_left_y + 3;
        if (!trunk || proto.quality + modifier < node.prototype.minimum_quality) {
            mistrimulti_farm_touch(f, ls, res, anchor);
            return;
        }
        node.hitpoints -= min(damage, node.hitpoints);
        if (node.hitpoints <= 0) mistrimulti_farm_fell(f, ls, res, node);
    } else if (data.a == "chop" && cat == ObjectCategory.Stump) {
        if (proto.quality + modifier < node.prototype.minimum_quality) {
            mistrimulti_farm_touch(f, ls, res, anchor);
            return;
        }
        node.hitpoints -= min(damage, node.hitpoints);
        if (node.hitpoints <= 0) erase_object_node_by_parent(grid, node);
    } else if (data.a == "pick" && cat == ObjectCategory.Rock) {
        if (proto.quality != QualityId.LEN - 1 && proto.quality + modifier < node.prototype.minimum_quality) {
            mistrimulti_farm_touch(f, ls, res, anchor);
            return;
        }
        node.hitpoints -= min(damage, node.hitpoints);
        if (node.hitpoints <= 0) erase_object_node_by_parent(grid, node);
    } else if ((data.a == "pick" || data.a == "dig") && node.object_id == ObjectId.DigSite) {
        erase_object_node_by_parent(grid, node);
        grid.write_node(node.top_left_x, node.top_left_y, ObjectId.DigSiteDestroyed);
    } else {
        mistrimulti_farm_touch(f, ls, res, anchor);
        return;
    }
    res.ok = true;
    mistrimulti_farm_touch(f, ls, res, anchor);
}

// A tree with no hitpoints left: a grown one leaves a stump with its look, a young one nothing (as chop_node does).
function mistrimulti_farm_fell(f, ls, res, tree) {
    var variant = tree.variant_idx;
    var stump_id = tree.prototype.stump_id;
    var grown = tree.stage > 1;
    var sx = tree.top_left_x + 2;
    var sy = tree.top_left_y + 3;
    erase_object_node_by_parent(ls.grid, tree);
    if (!grown) return;
    var stump = ls.grid.write_node(sx, sy, stump_id);
    if (stump == undefined) return;
    stump.variant_idx = variant;
    var at = mistrimulti_farm_slot(ls, stump.object_id, stump.top_left_x, stump.top_left_y);
    if (at != undefined) mistrimulti_farm_touch(f, ls, res, at);
}

// A guest's hand-made changes, each checked by itself. The result lists the host's state of every cell involved
// (which also corrects a refused one) and the items to give back for a refused planting.
function mistrimulti_farm_op_edit(f, ls, peer, data, res) {
    res.rf = [];
    var edits = data[$ "e"];
    if (!is_array(edits)) return;
    res.ok = true;
    for (var i = 0; i < min(array_length(edits), MISTRIMULTI_FARM_EDITS); i++) {
        var e = edits[i];
        if (!is_array(e) || array_length(e) < 2 || !is_string(e[0])) continue;
        if (e[0] == "a") {
            mistrimulti_farm_edit_add(f, ls, peer, e[1], res);
            continue;
        }
        var ni = array_length(e) >= 3 ? mistrimulti_farm_cell(ls, e[1], e[2]) : undefined;
        if (ni == undefined || !mistrimulti_farm_reach(peer, ls, e[1], e[2])) continue;
        var node = mistrimulti_farm_node_at(ls.grid, ni);
        var cat = node == undefined ? -1 : object_id_to_object_category(node.object_id);
        if (e[0] == "c" && cat == ObjectCategory.Grass) mistrimulti_farm_erase(ls, ni);
        else if (e[0] == "r" && cat == ObjectCategory.Crop && node.ctx == 0) mistrimulti_farm_erase(ls, ni);
        else if (e[0] == "r" && cat == ObjectCategory.Furniture && node.prototype.destructable != false) mistrimulti_farm_erase(ls, ni);
        else if (e[0] == "s" && cat == ObjectCategory.Furniture && node.prototype.sprinkler != undefined && array_length(e) >= 4
            && mistrimulti_farm_int(e[3]) && e[3] > (node[$ "essence_supply"] ?? 0) && e[3] <= 1000) {
            node.essence_supply = e[3];
        }
        mistrimulti_farm_touch(f, ls, res, ni);
    }
}

// A planting or placement: only a new, plain object on free ground the game would also accept.
function mistrimulti_farm_edit_add(f, ls, peer, rec, res) {
    var id = mistrimulti_farm_check(ls, rec);
    if (id == undefined) return;
    var cat = object_id_to_object_category(id);
    var ni = mistrimulti_farm_slot(ls, id, rec[1], rec[2]);
    var planted = (cat == ObjectCategory.Crop && rec[3] == 0) || (cat == ObjectCategory.Tree && rec[3] == 0)
        || cat == ObjectCategory.Grass || cat == ObjectCategory.Furniture;
    var node = undefined;
    if (planted && mistrimulti_farm_reach(peer, ls, rec[1], rec[2]) && mistrimulti_farm_can_add(ls, cat, rec[1], rec[2])) {
        node = mistrimulti_farm_apply(ls, rec, true);
    }
    if (node == undefined && cat != ObjectCategory.Grass && array_length(res.rf) < MISTRIMULTI_FARM_EDITS) {
        var item = mistrimulti_farm_item_for(id, cat);
        if (item != undefined) array_push(res.rf, [item_id_to_string(item), 1]);
    }
    mistrimulti_farm_touch(f, ls, res, ni);
}

// The same ground rules as can_plant_seed, can_plant_sapling and can_plant_grass, on the host's own grid.
function mistrimulti_farm_can_add(ls, cat, x, y) {
    var grid = ls.grid;
    if (cat == ObjectCategory.Furniture) return true; // write_furniture_to_location checks the footprint
    var size = cat == ObjectCategory.Tree ? 6 : (cat == ObjectCategory.Grass ? 1 : 2);
    for (var xx = 0; xx < size; xx++) {
        for (var yy = 0; yy < size; yy++) {
            if (cat == ObjectCategory.Tree && (xx < 2 || xx > 3) && (yy < 2 || yy > 3)) continue;
            var ni = mistrimulti_farm_cell(ls, x + xx, y + yy);
            if (ni == undefined || grid.node_object_id[ni] != undefined || grid.node_terrain_kind[ni] != TerrainKind.Ground) return false;
            var ground = grid.node_terrain_ground_kind[ni];
            if (cat == ObjectCategory.Crop && ground != GroundKind.Soil) return false;
            if (cat == ObjectCategory.Grass && ground != GroundKind.Grass) return false;
            if (cat == ObjectCategory.Tree && (ground == GroundKind.RiverBank || !has_flag(grid.node_flags[ni], TileFlag.Placeable))) return false;
        }
    }
    return true;
}

// The item a player spends to place an object (for giving it back when the host refuses).
function mistrimulti_farm_item_for(id, cat) {
    if (cat == ObjectCategory.Furniture) {
        var found = find_item_prototype(id);
        return found == undefined ? undefined : found.item_id;
    }
    for (var i = 0; i < ItemId.LEN; i++) {
        var p = ITEM_PROTOTYPES[i];
        if (cat == ObjectCategory.Crop && p.use == ItemUse.PlantSeed && p.crop_object == id) return i;
        if (cat == ObjectCategory.Tree && p.use == ItemUse.PlantSapling && p.sapling == id) return i;
    }
    return undefined;
}

// ---- guest: the answer ----------------------------------------------------------------------------------------------------

// Every guest but the requester applies the host's result at once. The requester waits for its reply, where
// the engine's own action runs before the result is applied.
function mistrimulti_farm_result(from, res, ctx) {
    if (!ctx.mine && mistrimulti_farm_from_host(from) && is_struct(res)) mistrimulti_farm_apply_change(res);
    return true;
}

function mistrimulti_farm_reply(from, res, ctx) {
    var f = mistrimulti_farm_state();
    if (!mistrimulti_farm_ok(f)) return;
    try {
        if (!is_struct(res)) {
            // lost (the host restarted) or expired: what happened is unknown, so ask for the host's state
            f.hello = true;
            return;
        }
        var ls = mistrimulti_farm_loc(res[$ "l"]);
        if (ls == undefined) return;
        if (res[$ "ok"] == true && res[$ "a"] != "edit" && mistrimulti_farm_cell(ls, res[$ "x"], res[$ "y"]) != undefined) mistrimulti_farm_perform(f, ls, res);
        mistrimulti_farm_apply_change(res);
        var rf = res[$ "rf"];
        if (is_array(rf)) {
            for (var i = 0; i < min(array_length(rf), MISTRIMULTI_FARM_EDITS); i++) {
                var give = rf[i];
                var item = is_array(give) && array_length(give) == 2 && is_string(give[0]) ? try_string_to_item_id(give[0]) : undefined;
                if (item != undefined && give[1] == 1) ARI.give_item(item, 1);
            }
        }
    } catch (e) {
        mistrimulti_farm_fail(f, e);
    }
}

// The host allowed the action: bring the node to the state the host had, then run the engine's own action, so
// drops, perks, xp, stamina and effects are this player's. The hooks above are bypassed meanwhile.
function mistrimulti_farm_perform(f, ls, res) {
    var here = CURRENT_LOCATION_ID == ls.id && mistrimulti_farm_current(ls);
    f.bypass++;
    try {
        if (here && is_array(res[$ "p"])) mistrimulti_farm_apply(ls, res.p, false);
        mistrimulti_farm_run(ls, res, here);
        mistrimulti_farm_adopt(ls, res);
    } catch (e) {
        mistrimulti_farm_fail(f, e);
    }
    f.bypass--;
}

// The engine's own action changed the grid: take it as seen, so that it is not mistaken for a hand-made edit.
function mistrimulti_farm_adopt(ls, res) {
    var recs = [];
    if (is_array(res[$ "p"])) array_push(recs, res.p);
    if (is_array(res[$ "n"])) {
        for (var i = 0; i < min(array_length(res.n), 32); i++) array_push(recs, res.n[i]);
    }
    for (var j = 0; j < array_length(recs); j++) {
        var id = mistrimulti_farm_check(ls, recs[j]);
        if (id != undefined) mistrimulti_farm_refresh(ls, mistrimulti_farm_slot(ls, id, recs[j][1], recs[j][2]));
    }
    if (is_array(res[$ "g"])) {
        for (var k = 0; k < min(array_length(res.g), 32); k++) {
            var cell = res.g[k];
            var ni = is_array(cell) && array_length(cell) == 2 ? mistrimulti_farm_cell(ls, cell[0], cell[1]) : undefined;
            if (ni != undefined) mistrimulti_farm_refresh(ls, ni);
        }
    }
}

function mistrimulti_farm_new_doppel() {
    return new TangoDoppel();
}

function mistrimulti_farm_run(ls, res, here) {
    var x = res.x;
    var y = res.y;
    if (res.a == "harvest") {
        var node = here ? mistrimulti_farm_find(ls, x, y) : undefined;
        if (node != undefined && node[$ "renderer"] != undefined && instance_exists(node.renderer)) {
            interact(node);
            return;
        }
        // The player left before the answer came: give the plain yield instead.
        var yi = res[$ "yi"];
        var item = is_array(yi) && array_length(yi) == 2 && is_string(yi[0]) ? try_string_to_item_id(yi[0]) : undefined;
        if (item != undefined && mistrimulti_farm_int(yi[1]) && yi[1] > 0 && yi[1] <= 64) ARI.give_item(item, yi[1]);
        return;
    }
    var itemid = here && is_string(res[$ "i"]) ? try_string_to_item_id(res.i) : undefined;
    if (itemid == undefined) return;
    var proto = ITEM_PROTOTYPES[itemid];
    var modifier = res[$ "c"] == 1 ? -1 : 0;
    var doppel = mistrimulti_farm_new_doppel();
    if (res.a == "chop") {
        if (chop_node(GRID, x, y, proto, modifier, doppel) == true) {
            ARI.gain_essence(1, 8 * (x + 1), 8 * (y + 1));
            ARI.modify_stamina(proto.stamina_cost);
        }
    } else if (res.a == "pick") {
        var picked = pick_node(GRID, x, y, proto, modifier, undefined, doppel);
        if (picked != PickResult.Nothing) {
            if (picked != PickResult.Furniture) {
                ARI.gain_essence(proto.quality + 1, 8 * (x + 1), 8 * (y + 1));
                ARI.modify_stamina(proto.stamina_cost);
            }
            if (picked == PickResult.DigSite) ARI.gain_xp(Skill.Archaeology, XpValue.break_dig_spot);
        }
    } else if (res.a == "dig") {
        var dug = shovel_node(GRID, x, y, doppel);
        if (has_flag(dug, ShovelResult.GIVE_ESSENCE)) {
            ARI.gain_essence(proto.quality + 1, 8 * (x + 1), 8 * (y + 1));
            ARI.modify_stamina(proto.stamina_cost);
        }
        if (has_flag(dug, ShovelResult.GAIN_DIG_SITE_EXPERIENCE)) ARI.gain_xp(Skill.Archaeology, XpValue.break_dig_spot);
    }
    doppel.resolve();
}

// For the MMAPI debug agent (mistrimulti.farm): "digest" is equal on the host and a guest when their worlds agree.
function mistrimulti_farm_debug() {
    var f = mistrimulti_farm_state();
    var ids = mistrimulti_farm_location_ids(f);
    var locs = [];
    for (var i = 0; i < array_length(ids); i++) {
        var ls = f.locs[$ string(ids[i])];
        if (!is_struct(ls)) continue;
        var sum = 0;
        for (var c = 0; c < array_length(ls.cs); c++) sum = (sum + ls.cs[c]) mod MISTRIMULTI_FARM_HASH;
        array_push(locs, { id: ls.id, seeded: ls.seeded, silent: ls.silent, cursor: ls.cursor, digest: sum,
            want: array_length(ls.want), edits: array_length(ls.edits) });
    }
    return { errors: f.errors, idle: f.idle, pending: array_length(f.pending_keys), jobs: array_length(f.jobs),
        chunks: array_length(f.chunks), locs: locs };
}
