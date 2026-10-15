// Separate houses (world option "Separate houses", experimental). First step: prove the mechanics in the real game.
//
// The farmhouse is painted into the farm room, so a second house is a farm building (the mini museum's outside, the only
// building the game can place that is not a barn, coop or greenhouse) whose interior is its own copy of the house
// (reserve_dynamic_room(LocationId.PlayerHome), the way a barn gets its interior). The building's door leads to the
// building's own room type, so game.room_transition_pre sends it to the house room instead, and the house's front door,
// which leads to the farmhouse door, is sent back to this building's door.
//
// F10 (host, separate-houses world, on the farm): place a house next to you. Houses are remembered in
// worlds/<world>/houses.json on the host. Not done yet: one house per player made automatically, guests seeing and
// entering houses, furniture inside a house synchronised, sleeping and waking up in your own house, house upgrades
// (the size, wallpaper and side rooms of the main house apply to every house).

function mistrimulti_houses_separate() {
    return mistrimulti_world_options()[$ "houses"] == "separate";
}

function __mistrimulti_houses() {
    var r = __mistrimulti_runtime();
    if (!is_struct(r[$ "houses"])) {
        r.houses = { list: [], loaded: "" };
    }
    return r.houses;
}

// Host: the houses of the world just loaded (worlds/<world>/houses.json).
function mistrimulti_houses_load() {
    var r = __mistrimulti_runtime();
    var h = __mistrimulti_houses();
    if (h.loaded == r.world_path) return;
    h.loaded = r.world_path;
    h.list = [];
    var path = r.world_path + "/houses.json";
    if (!file_exists(path)) return;
    var data = try_read_json_file(path);
    if (!is_struct(data) || !is_array(data[$ "list"])) return;
    for (var i = 0; i < array_length(data.list); i++) {
        var e = data.list[i];
        if (is_struct(e) && is_real(e[$ "dyn"]) && is_real(e[$ "x"]) && is_real(e[$ "y"])) array_push(h.list, { dyn: e.dyn, x: e.x, y: e.y, owner: is_string(e[$ "owner"]) ? e.owner : "" });
    }
    mistrimulti_trace("house", "loaded " + string(array_length(h.list)) + " houses: " + json_stringify(h.list), 200);
}

function mistrimulti_houses_save() {
    var r = __mistrimulti_runtime();
    if (r.world_path == "") return;
    save_text_file(r.world_path + "/houses.json", json_stringify({ v: 1, list: __mistrimulti_houses().list }));
}

function mistrimulti_houses_find(dyn) {
    var h = __mistrimulti_houses();
    if (!is_real(dyn)) return undefined;
    for (var i = 0; i < array_length(h.list); i++) if (h.list[i].dyn == dyn) return h.list[i];
    return undefined;
}

// F10: place a test house next to the host.
function mistrimulti_houses_probe() {
    var r = __mistrimulti_runtime();
    try {
        if (!r.enabled || r.mode != "host") { create_notification(ANCHOR.wrap_for_local("Only the host can place a house.")); return; }
        if (!mistrimulti_houses_separate()) { create_notification(ANCHOR.wrap_for_local("This world uses a shared house.")); return; }
        if (CURRENT_LOCATION_ID != LocationId.Farm || GRID == undefined || GRID.dyn_index != undefined || !instance_exists(obj_ari)) {
            create_notification(ANCHOR.wrap_for_local("Stand on the farm to place a house."));
            return;
        }
        mistrimulti_houses_load();
        var farm = GRIDS[LocationId.Farm];
        var proto = NODE_PROTOTYPES[ObjectId.MiniMuseum];
        mistrimulti_trace("house", "building size " + json_stringify(proto.size) + " entrance " + json_stringify(proto.entrance_offset)
            + " offset " + json_stringify(proto.offset) + " room " + string(proto[$ "location_id"]), 200);
        var ax = obj_ari.x div 8;
        var ay = obj_ari.y div 8;
        var spot = undefined;
        for (var radius = 2; radius < 40 && spot == undefined; radius += 2) {
            for (var dx = -radius; dx <= radius && spot == undefined; dx += 2) {
                for (var dy = -radius; dy <= radius && spot == undefined; dy += 2) {
                    var tx = ((ax + dx) div 2) * 2;
                    var ty = ((ay + dy - proto.size.y) div 2) * 2;
                    if (can_write_building(farm, tx, ty, proto, true)) spot = { x: tx, y: ty };
                }
            }
        }
        if (spot == undefined) {
            create_notification(ANCHOR.wrap_for_local("No free space for a house nearby: clear some ground first."));
            mistrimulti_trace("house", "no free spot near " + string(ax) + "," + string(ay), 200);
            return;
        }
        var interior = reserve_dynamic_room(LocationId.PlayerHome);
        push_dynamic_room(interior);
        mistrimulti_trace("house", "interior dyn " + string(interior.dyn_index) + " location " + string(interior.location_id), 200);
        var node = write_building_to_location(farm, spot.x, spot.y, proto, { variant: 0, dyn_index: interior.dyn_index });
        if (node == undefined) {
            mistrimulti_trace("house", "write_building_to_location refused " + json_stringify(spot), 200);
            create_notification(ANCHOR.wrap_for_local("The house could not be placed."));
            return;
        }
        node.name = "House";
        try { farm.initialize_node_renderer(node); }
        catch (e) { mistrimulti_trace("house", "renderer failed: " + string(e), 200); }
        array_push(__mistrimulti_houses().list, { dyn: interior.dyn_index, x: spot.x, y: spot.y, owner: r.uid });
        mistrimulti_houses_save();
        mistrimulti_trace("house", "placed at " + json_stringify(spot) + " dyn " + string(interior.dyn_index), 200);
        create_notification(ANCHOR.wrap_for_local("House placed. Walk in through its door."));
    } catch (e) {
        mmapi_log_error("mistrimulti", "Placing a house failed: " + string(e));
        mmapi_log_flush("mistrimulti");
    }
}

// game.room_transition_pre: into a house -> the house room; out of a house -> that house's door on the farm.
function mistrimulti_houses_transition(ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || !mistrimulti_houses_separate()) return;
    try {
        if (r.mode == "host") mistrimulti_houses_load();
        var it = ctx.itinerary;
        var into = mistrimulti_houses_find(it[$ "dyn_index"]);
        if (into != undefined) {
            ctx.gm_room = location_id_to_gm_room(LocationId.PlayerHome);
            mistrimulti_trace("house", "entering house dyn " + string(into.dyn) + " (was room " + string(it.destination) + ")", 200);
            return;
        }
        var here = GRID == undefined ? undefined : mistrimulti_houses_find(GRID.dyn_index);
        if (here != undefined && it.destination == LocationId.Farm) {
            var proto = NODE_PROTOTYPES[ObjectId.MiniMuseum];
            var ex = here.x * 8 + proto.offset.x + proto.entrance_offset.x;
            var ey = here.y * 8 + proto.offset.y + proto.entrance_offset.y;
            it.set_exact_position(ex, ey);
            it.dyn_index = undefined;
            mistrimulti_trace("house", "leaving house dyn " + string(here.dyn) + " to " + string(ex) + "," + string(ey), 200);
        } else if (here != undefined) {
            mistrimulti_trace("house", "leaving house dyn " + string(here.dyn) + " to room " + string(it.destination), 200);
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_houses", "mistrimulti", "House door failed: " + string(e));
    }
}
