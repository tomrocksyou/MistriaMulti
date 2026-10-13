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
    if (!r.enabled || r.apply_depth > 0 || r.mask == 0 || GRID == undefined) return undefined;
    if (CURRENT_LOCATION_ID != LocationId.Farm || GRID.dyn_index != undefined) return undefined;
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
    }
    return undefined;
}

function mistrimulti_watch_changes() {
    var r = __mistrimulti_runtime();
    if (CURRENT_LOCATION_ID != LocationId.Farm || GRID == undefined) { r.watches = []; return; }
    for (var i = array_length(r.watches)-1; i >= 0; i--) {
        var watch = r.watches[i];
        var after = mistrimulti_terrain_tile(GRID, watch.x, watch.y);
        if (after != undefined && (after.g != watch.before.g || after.w != watch.before.w)) {
            var kind = r.mode == "host" ? "terrain_commit" : "terrain_request";
            var data = { tiles: [after], before: watch.before };
            if (mistrimulti_emit(kind, data)) {
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

function mistrimulti_apply_terrain(tile) {
    var r = __mistrimulti_runtime();
    if (GRIDS == undefined) return false;
    var farm = GRIDS[LocationId.Farm];
    if (farm == undefined || !mistrimulti_valid_tile(tile, farm)) return false;
    var ni = farm.node_index_for_cell(tile.x, tile.y);
    if (farm.node_terrain_kind[ni] != TerrainKind.Ground) return false;
    // Watering is safe around crops; turning occupied cells back to dirt is not.
    if (farm.node_object_id[ni] != undefined && tile.g == GroundKind.Dirt) return false;
    r.apply_depth++;
    try {
        farm.write_ground(tile.x, tile.y, tile.g);
        water_chunk(farm, tile.x, tile.y, tile.w && tile.g == GroundKind.Soil);
        if (CURRENT_LOCATION_ID == LocationId.Farm && farm.is_setup) farm.update_tilemap_for_node(tile.x, tile.y);
        r.dirty_world = r.mode == "join" || r.dirty_world;
    } catch (e) {
        r.apply_depth--;
        mmapi_warn_rate_limited("mistrimulti_terrain", "mistrimulti", "A farm update could not be applied.");
        return false;
    }
    r.apply_depth--;
    return true;
}

function mistrimulti_accept_terrain(player, data) {
    var r = __mistrimulti_runtime();
    if (!is_array(data[$ "tiles"]) || array_length(data.tiles) != 1 || GRIDS == undefined) return true;
    var farm = GRIDS[LocationId.Farm];
    if (farm == undefined) return true;
    var tile = data.tiles[0];
    var before = data[$ "before"];
    if (!mistrimulti_valid_tile(tile, farm) || !mistrimulti_valid_tile(before, farm)) return true;
    var peer = r.peers[player];
    if (peer.room != location_id_to_string(LocationId.Farm) + ":" + string(undefined)) return true;
    if (point_distance(peer.x, peer.y, tile.x*8, tile.y*8) > 256) return true;
    var current = mistrimulti_terrain_tile(farm, tile.x, tile.y);
    if (current == undefined) return true;
    if (array_length(r.queue) >= 256) return false; // do not ACK an unqueued commit
    // Conflicting predictions are corrected to the existing host state.
    if (current.g == before.g && current.w == before.w) mistrimulti_apply_terrain(tile);
    var committed = mistrimulti_terrain_tile(farm, tile.x, tile.y);
    return mistrimulti_emit("terrain_commit", { tiles: [committed] });
}

function mistrimulti_stream_terrain() {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || r.mask == 0 || GRIDS == undefined) return;
    var farm = GRIDS[LocationId.Farm];
    if (farm == undefined) return;
    if (r.snapshot_pending && r.terrain_cursor < 0) { r.terrain_cursor = 0; r.snapshot_pending = false; }
    if (r.terrain_cursor < 0 || array_length(r.queue) >= 4) return;
    var tiles = [];
    // Scan at most 128 snapshot candidates per bridge tick.
    var width = farm.dims.x div 2;
    var count = width * (farm.dims.y div 2);
    var visited = 0;
    while (r.terrain_cursor < count && array_length(tiles) < 32 && visited < 128) {
        var x = (r.terrain_cursor mod width) * 2;
        var y = (r.terrain_cursor div width) * 2;
        var tile = mistrimulti_terrain_tile(farm, x, y);
        if (tile != undefined) array_push(tiles, tile);
        r.terrain_cursor++;
        visited++;
    }
    if (array_length(tiles) > 0) mistrimulti_emit("terrain_snapshot", { tiles: tiles });
    if (r.terrain_cursor >= count) r.terrain_cursor = -1;
}
