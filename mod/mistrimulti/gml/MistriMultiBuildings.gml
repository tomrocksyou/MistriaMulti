// MistriaMulti: addressing the insides of player buildings (barns, coops, greenhouses, the mini museum) in a way that
// is the same in every game. Design and assumptions: docs/SYNC-BUILDINGS.md.
//
// The inside of a building is a "dynamic grid": DYNAMIC_GRIDS.get(building.dyn_index). The game numbers those grids
// itself (the next free number when the building is written), so two games that built, loaded or were told about
// their buildings in a different order can disagree about the number. The building stands on the farm at a fixed
// place, which is the same in every game, so its position names its inside: "b<x>_<y>" (the building's top-left
// cell). Everything the mod sends about a grid says "l": a LocationId (a number) for a static location, or that
// name (a string) for the inside of a building. The name has no ":" so that room keys ("<location>:<part>") still
// split on the first colon.

#macro MISTRIMULTI_BLD_MAX 24

function mistrimulti_building_ref(building) {
    return "b" + string(building.top_left_x) + "_" + string(building.top_left_y);
}

// The buildings of the farm that have an inside, at most MISTRIMULTI_BLD_MAX of them.
function mistrimulti_buildings() {
    var out = [];
    try {
        if (GRIDS == undefined || DYNAMIC_GRIDS == undefined) return out;
        var list = get_buildings();
        for (var i = 0; i < list.count() && array_length(out) < MISTRIMULTI_BLD_MAX; i++) {
            var b = list.get(i);
            if (b[$ "dyn_index"] != undefined && DYNAMIC_GRIDS.get(b.dyn_index) != undefined) array_push(out, b);
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_buildings", "mistrimulti", "The buildings could not be listed: " + string(e));
        return [];
    }
    return out;
}

function mistrimulti_building_by_ref(ref) {
    if (!is_string(ref) || string_length(ref) > 16) return undefined;
    var all = mistrimulti_buildings();
    for (var i = 0; i < array_length(all); i++) {
        if (mistrimulti_building_ref(all[i]) == ref) return all[i];
    }
    return undefined;
}

function mistrimulti_building_by_dyn(dyn) {
    if (dyn == undefined) return undefined;
    var all = mistrimulti_buildings();
    for (var i = 0; i < array_length(all); i++) {
        if (all[i].dyn_index == dyn) return all[i];
    }
    return undefined;
}

// The names of all the insides this game has.
function mistrimulti_building_refs() {
    var out = [];
    var all = mistrimulti_buildings();
    for (var i = 0; i < array_length(all); i++) array_push(out, mistrimulti_building_ref(all[i]));
    return out;
}

// The name of a grid for the wire: its LocationId for a static one, the building's name for an inside (undefined
// when the building cannot be found, which means the grid is not shared).
function mistrimulti_grid_ref(grid) {
    if (grid == undefined) return undefined;
    if (grid.dyn_index == undefined) return GRIDS != undefined && GRIDS[grid.location_id] == grid ? grid.location_id : undefined;
    var b = mistrimulti_building_by_dyn(grid.dyn_index);
    return b == undefined ? undefined : mistrimulti_building_ref(b);
}

// The grid a wire name stands for, or undefined. Anything that is not a LocationId or a building's name is refused.
function mistrimulti_grid_by_ref(ref) {
    if (GRIDS == undefined) return undefined;
    if (is_string(ref)) {
        var b = mistrimulti_building_by_ref(ref);
        return b == undefined ? undefined : DYNAMIC_GRIDS.get(b.dyn_index);
    }
    if (!is_real(ref) || ref != floor(ref) || ref < 0 || ref >= LocationId.LEN) return undefined;
    var g = GRIDS[ref];
    return g == undefined || g.dyn_index != undefined ? undefined : g;
}

// The part of a room key after the location: the building's name for an inside (the grid number when the
// building is unknown), "undefined" for a static location. Players in the same barn have the same key in every game.
function mistrimulti_room_part(grid) {
    if (grid.dyn_index == undefined) return string(undefined);
    var b = mistrimulti_building_by_dyn(grid.dyn_index);
    return b == undefined ? string(grid.dyn_index) : mistrimulti_building_ref(b);
}

// The room key of a player standing in this grid (what mistrimulti_room_key() gives in that player's game).
function mistrimulti_room_of_grid(grid) {
    return location_id_to_string(grid.location_id) + ":" + mistrimulti_room_part(grid);
}

// The same for a building's inside.
function mistrimulti_room_of_building(building) {
    return location_id_to_string(building.prototype.location_id) + ":" + mistrimulti_building_ref(building);
}
