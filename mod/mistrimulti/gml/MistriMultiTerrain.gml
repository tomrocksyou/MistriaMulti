// Soil and water are shared on the farm and inside buildings (the greenhouse). A tile always travels with the ref of
// its grid, "l" (MistriMultiBuildings.gml); a message without one means the farm, as it always did.
function mistrimulti_terrain_grid(ref) {
    if (GRIDS == undefined) return undefined;
    if (ref == undefined) ref = LocationId.Farm;
    if (is_string(ref)) return mistrimulti_grid_by_ref(ref);
    return is_real(ref) && ref == LocationId.Farm ? GRIDS[LocationId.Farm] : undefined;
}

// The grid the player is in, if soil and water are shared there, and its ref.
function mistrimulti_terrain_here() {
    if (GRID == undefined) return undefined;
    var ref = GRID.dyn_index == undefined ? (CURRENT_LOCATION_ID == LocationId.Farm ? LocationId.Farm : undefined) : mistrimulti_grid_ref(GRID);
    return ref == undefined ? undefined : { grid: GRID, ref: ref };
}

function mistrimulti_terrain_tile(grid, x, y) {
    if (grid == undefined || x < 0 || y < 0 || x+1 >= grid.dims.x || y+1 >= grid.dims.y) return undefined;
    var ni = grid.node_index_for_cell(x, y);
    if (grid.node_terrain_kind[ni] != TerrainKind.Ground) return undefined;
    var ground = grid.node_terrain_ground_kind[ni];
    if (ground != GroundKind.Dirt && ground != GroundKind.Soil) return undefined;
    return { x: x, y: y, g: ground, w: grid.node_terrain_is_watered[ni] == true };
}

function mistrimulti_tool_targets(value, ctx) {
    var r = __mistrimulti_runtime();
    try {
        mistrimulti_trace("tool_targets", r.mode + " tool " + string(ctx.item.prototype.tool_type) + " cells " + string(value.count())
            + " enabled " + string(r.enabled) + " depth " + string(r.apply_depth) + " mask " + string(r.mask)
            + " loc " + string(CURRENT_LOCATION_ID) + " farm " + string(LocationId.Farm));
    } catch (e) { mistrimulti_trace("tool_targets", "trace failed: " + string(e)); }
    if (!r.enabled || r.apply_depth > 0 || r.mask == 0 || GRID == undefined) return undefined;
    if (mistrimulti_terrain_here() == undefined) return undefined;
    var tool = ctx.item.prototype.tool_type;
    if (tool != ToolType.Hoe && tool != ToolType.WateringCan) return undefined;
    for (var i = 0; i < min(value.count(), 64); i++) {
        var cell = value.get(i);
        var x = floor(cell.x / 2) * 2;
        var y = floor(cell.y / 2) * 2;
        var tile = mistrimulti_terrain_tile(GRID, x, y);
        if (tile == undefined) continue;
        var found = false;
        for (var j = 0; j < array_length(r.watches); j++) {
            var watch = r.watches[j];
            if (watch.x == x && watch.y == y) { watch.until = r.ticks + 90; found = true; break; }
        }
        if (!found && array_length(r.watches) < 256) {
            array_push(r.watches, { x: x, y: y, before: tile, until: r.ticks + 90 });
        }
        r.watch_grid = GRID;
    }
    return undefined;
}

function mistrimulti_watch_changes() {
    var r = __mistrimulti_runtime();
    var here = mistrimulti_terrain_here();
    // A watch belongs to the grid it was made in: leaving the room (or entering another) drops it.
    if (here == undefined || r[$ "watch_grid"] != GRID) { r.watches = []; r.watch_grid = GRID; return; }
    for (var i = array_length(r.watches)-1; i >= 0; i--) {
        var watch = r.watches[i];
        var after = mistrimulti_terrain_tile(GRID, watch.x, watch.y);
        if (after != undefined && (after.g != watch.before.g || after.w != watch.before.w)) {
            // The host's own change is authoritative; a guest's is a request the host validates.
            var data = { tiles: [after], before: watch.before };
            if (is_string(here.ref)) data.l = here.ref;
            var sent = r.mode == "host" ? mistrimulti_event_emit("terrain_commit", data)
                : mistrimulti_event_request("terrain", data) != undefined;
            mistrimulti_trace("terrain_send", r.mode + " " + string(watch.x) + "," + string(watch.y) + " " + json_stringify(watch.before)
                + " -> " + json_stringify(after) + (sent ? " sent" : " NOT sent"));
            if (sent) {
                if (r.mode == "join") r.dirty_world = true;
                array_delete(r.watches, i, 1);
            }
        } else if (r.ticks > watch.until || after == undefined) {
            array_delete(r.watches, i, 1);
        }
    }
}

function mistrimulti_valid_tile(tile, grid) {
    if (!is_struct(tile) || !is_real(tile[$ "x"]) || !is_real(tile[$ "y"])) return false;
    if (tile.x != floor(tile.x) || tile.y != floor(tile.y) || tile.x mod 2 != 0 || tile.y mod 2 != 0) return false;
    if (tile.x < 0 || tile.y < 0 || tile.x+1 >= grid.dims.x || tile.y+1 >= grid.dims.y) return false;
    if (tile[$ "g"] != GroundKind.Dirt && tile[$ "g"] != GroundKind.Soil) return false;
    if (typeof(tile[$ "w"]) != "bool") return false;
    return true;
}

function mistrimulti_apply_terrain(tile, ref = undefined) {
    var r = __mistrimulti_runtime();
    if (GRIDS == undefined) return false;
    var farm = mistrimulti_terrain_grid(ref);     // the farm, or the inside of a building
    if (farm == undefined || !mistrimulti_valid_tile(tile, farm)) return false;
    var ni = farm.node_index_for_cell(tile.x, tile.y);
    if (farm.node_terrain_kind[ni] != TerrainKind.Ground) return false;
    // Watering is safe around crops; turning occupied cells back to dirt is not.
    if (farm.node_object_id[ni] != undefined && tile.g == GroundKind.Dirt) return false;
    r.apply_depth++;
    try {
        farm.write_ground(tile.x, tile.y, tile.g);
        water_chunk(farm, tile.x, tile.y, tile.w && tile.g == GroundKind.Soil);
        if (GRID == farm && farm.is_setup) farm.update_tilemap_for_node(tile.x, tile.y);
        r.dirty_world = r.mode == "join" || r.dirty_world;
    } catch (e) {
        r.apply_depth--;
        mmapi_warn_rate_limited("mistrimulti_terrain", "mistrimulti", "A farm update could not be applied: " + string(e));
        return false;
    }
    r.apply_depth--;
    return true;
}

// Event kinds: "terrain" (guest request, host result), "terrain_commit" (host change), "terrain_snapshot".
function mistrimulti_terrain_register_events() {
    mistrimulti_event_register("terrain", { on_request: mistrimulti_terrain_request, on_result: mistrimulti_terrain_event });
    mistrimulti_event_register("terrain_commit", { on_event: mistrimulti_terrain_event, on_peer: mistrimulti_terrain_peer });
    mistrimulti_event_register("terrain_snapshot", { on_event: mistrimulti_terrain_event });
}

// Host only, once per request id. The result (the tile as the host now has it) goes to every guest.
function mistrimulti_terrain_request(player, data, ctx) {
    var r = __mistrimulti_runtime();
    var none = { tiles: [] };
    var peer = r.peers[player];
    if (player == r.id || !is_struct(peer) || peer[$ "active"] != true || !is_struct(data)) { mistrimulti_trace("terrain_req", "refused: player " + string(player) + " not active"); return none; }
    if (!is_array(data[$ "tiles"]) || array_length(data.tiles) != 1 || GRIDS == undefined) { mistrimulti_trace("terrain_req", "refused: bad tiles"); return none; }
    var ref = data[$ "l"];
    var farm = mistrimulti_terrain_grid(ref);
    if (farm == undefined) { mistrimulti_trace("terrain_req", "refused: unknown place " + string(ref)); return none; }
    var tile = data.tiles[0];
    var before = data[$ "before"];
    if (!mistrimulti_valid_tile(tile, farm) || !mistrimulti_valid_tile(before, farm)) { mistrimulti_trace("terrain_req", "refused: invalid tile " + json_stringify(data)); return none; }
    if (peer.room != mistrimulti_room_of_grid(farm)) { mistrimulti_trace("terrain_req", "refused: guest room " + string(peer.room)); return none; }
    if (point_distance(peer.x, peer.y, tile.x*8, tile.y*8) > 256) { mistrimulti_trace("terrain_req", "refused: too far " + string(peer.x) + "," + string(peer.y) + " tile " + string(tile.x) + "," + string(tile.y)); return none; }
    var current = mistrimulti_terrain_tile(farm, tile.x, tile.y);
    if (current == undefined) { mistrimulti_trace("terrain_req", "refused: no ground at " + string(tile.x) + "," + string(tile.y)); return none; }
    // Conflicting predictions are corrected to the existing host state.
    var applied = false;
    if (current.g == before.g && current.w == before.w) applied = mistrimulti_apply_terrain(tile, ref);
    mistrimulti_trace("terrain_req", "host " + json_stringify(current) + " guest before " + json_stringify(before) + " after " + json_stringify(tile) + (applied ? " applied" : " NOT applied"));
    var committed = mistrimulti_terrain_tile(farm, tile.x, tile.y);
    if (committed == undefined) return none;
    var res = { tiles: [committed] };
    if (ref != undefined) res.l = ref;
    return res;
}

// Guests apply the host's commits, snapshots and request results.
function mistrimulti_terrain_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    var host = r.peers[0];
    if (player != 0 || r.mode != "join" || !is_struct(host) || host[$ "active"] != true || !is_struct(data)) return true;
    if (!is_array(data[$ "tiles"]) || array_length(data.tiles) > 64) return true;
    var ref = data[$ "l"];
    if (ref != undefined && !is_string(ref)) return true;
    for (var i = 0; i < array_length(data.tiles); i++) mistrimulti_apply_terrain(data.tiles[i], ref);
    return true;
}

// A game that just joined (or re-entered the world) gets the current soil and water of the farm and the greenhouses.
function mistrimulti_terrain_peer(slot, joined, stream) {
    var r = __mistrimulti_runtime();
    if (joined && r.mode == "host") r.snapshot_pending = true;
}

// The greenhouses (the insides of buildings that have soil): soil and water are shared there like on the farm.
function mistrimulti_terrain_greenhouses() {
    var out = [];
    var all = mistrimulti_buildings();
    for (var i = 0; i < array_length(all); i++) {
        if (all[i].prototype.player_building_kind == PlayerBuildingKind.Greenhouse) array_push(out, all[i]);
    }
    return out;
}

// slot: one guest, or -1 for everyone.
function mistrimulti_terrain_job(r, ref, slot) {
    var jobs = r[$ "terrain_jobs"];
    if (!is_array(jobs)) {
        jobs = [];
        r.terrain_jobs = jobs;
    }
    for (var i = 0; i < array_length(jobs); i++) if (jobs[i].ref == ref && jobs[i].slot == slot) return;
    if (array_length(jobs) < 32) array_push(jobs, { ref: ref, slot: slot, cursor: 0 });
}

// A guest that walks into a greenhouse is sent its soil and water, which may have changed (a sleep, a sprinkler)
// since it last saw them.
function mistrimulti_terrain_rooms(r) {
    var seen = r[$ "terrain_room"];
    if (!is_array(seen)) {
        seen = array_create(8, "");
        r.terrain_room = seen;
    }
    for (var slot = 1; slot < 8; slot++) {
        var peer = r.peers[slot];
        var room = (r.mask & (1 << slot)) != 0 && is_struct(peer) && is_string(peer[$ "room"]) ? peer.room : "";
        if (room == seen[slot]) continue;
        seen[slot] = room;
        if (room == "") continue;
        var houses = mistrimulti_terrain_greenhouses();
        for (var k = 0; k < array_length(houses); k++) {
            if (mistrimulti_room_of_building(houses[k]) == room) mistrimulti_terrain_job(r, mistrimulti_building_ref(houses[k]), slot);
        }
    }
}

// Sends the next slice of a grid's soil and water (at most 128 candidates per bridge tick); returns the new cursor, or -1 when done.
function mistrimulti_terrain_send(grid, cursor, ref, slot) {
    var tiles = [];
    var width = grid.dims.x div 2;
    var count = width * (grid.dims.y div 2);
    var visited = 0;
    while (cursor < count && array_length(tiles) < 32 && visited < 128) {
        var x = (cursor mod width) * 2;
        var y = (cursor div width) * 2;
        var tile = mistrimulti_terrain_tile(grid, x, y);
        if (tile != undefined) array_push(tiles, tile);
        cursor++;
        visited++;
    }
    if (array_length(tiles) > 0) {
        var data = { tiles: tiles };
        if (ref != undefined) data.l = ref;
        mistrimulti_event_emit("terrain_snapshot", data, slot);
    }
    return cursor >= count ? -1 : cursor;
}

function mistrimulti_stream_terrain() {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || r.mask == 0 || GRIDS == undefined) return;
    var farm = GRIDS[LocationId.Farm];
    if (farm == undefined) return;
    mistrimulti_terrain_rooms(r);
    if (r.snapshot_pending && r.terrain_cursor < 0) {
        r.terrain_cursor = 0;
        r.snapshot_pending = false;
        var houses = mistrimulti_terrain_greenhouses();
        for (var h = 0; h < array_length(houses); h++) mistrimulti_terrain_job(r, mistrimulti_building_ref(houses[h]), -1);
    }
    if (mistrimulti_event_backlog() >= 16 || !mistrimulti_event_can_emit(1)) return;
    if (r.terrain_cursor >= 0) {
        r.terrain_cursor = mistrimulti_terrain_send(farm, r.terrain_cursor, undefined, -1);
        return;
    }
    var jobs = r[$ "terrain_jobs"];
    if (!is_array(jobs) || array_length(jobs) == 0) return;
    var job = jobs[0];
    var grid = mistrimulti_terrain_grid(job.ref);
    if (grid == undefined || (job.slot >= 0 && (r.mask & (1 << job.slot)) == 0)) {
        array_delete(jobs, 0, 1);
        return;
    }
    job.cursor = mistrimulti_terrain_send(grid, job.cursor, job.ref, job.slot);
    if (job.cursor < 0) array_delete(jobs, 0, 1);
}
