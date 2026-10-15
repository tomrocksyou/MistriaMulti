"""Mutation check for the sync of building interiors: each mutation must make at least one test fail.

    python3 tests/mutate_buildings.py

Breaks one rule of the GML at a time (naming a grid by its game-local number, skipping the room check, forgetting the
snapshot when a guest walks in, ...), runs the tests that should notice, and restores the file. Exit status 1 if a mutation
goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GML = ROOT / "mod/mistrimulti/gml"

# (name, file, old text, new text, test script, tests)
MUTATIONS = [
    ("grid named by its own number", "MistriMultiBuildings.gml",
     '''    return b == undefined ? undefined : mistrimulti_building_ref(b);''',
     '''    return b == undefined ? undefined : "b" + string(grid.dyn_index);''', "test_buildings.py", ["test_identity"]),
    ("room key by grid number", "MistriMultiBuildings.gml",
     '''    return b == undefined ? string(grid.dyn_index) : mistrimulti_building_ref(b);''',
     '''    return string(grid.dyn_index);''', "test_buildings.py", ["test_guest_actions_inside"]),
    ("insides not synchronised", "MistriMultiFarm.gml",
     '''    for (var j = 0; j < array_length(inside); j++) array_push(refs, inside[j]);''',
     '''    for (var j = 0; j < 0; j++) array_push(refs, inside[j]);''', "test_buildings.py", ["test_join_and_changes"]),
    ("farm request: room unchecked", "MistriMultiFarm.gml",
     '''peer[$ "room"] == mistrimulti_room_of_grid(ls.grid)''', '''true''', "test_buildings.py", ["test_guest_actions_inside"]),
    ("guest harvest inside not claimed", "MistriMultiFarm.gml",
     '''        && GRID != undefined;''', '''        && GRID != undefined && GRID.dyn_index == undefined;''', "test_buildings.py", ["test_guest_actions_inside"]),
    ("no digests when walking in", "MistriMultiFarm.gml",
     '''    if (here != undefined && here.dyn) f.hello = true;''', '''    if (false) f.hello = true;''', "test_buildings.py", ["test_enter_and_unknown_building"]),
    ("no digests for a new building", "MistriMultiFarm.gml",
     '''    if (names != f.known) {
        f.known = names;
        f.hello = true;
    }''', '''    f.known = names;''', "test_buildings.py", ["test_enter_and_unknown_building"]),
    ("terrain request: room unchecked", "MistriMultiTerrain.gml",
     '''    if (peer.room != mistrimulti_room_of_grid(farm)) {''', '''    if (false) {''', "test_buildings.py", ["test_terrain_inside"]),
    ("terrain of the building applied to the farm", "MistriMultiTerrain.gml",
     '''    if (is_string(ref)) return mistrimulti_grid_by_ref(ref);
    return is_real(ref)''', '''    if (is_string(ref)) return GRIDS[LocationId.Farm];
    return is_real(ref)''', "test_buildings.py", ["test_terrain_inside"]),
    ("no greenhouse snapshot on join", "MistriMultiTerrain.gml",
     '''        for (var h = 0; h < array_length(houses); h++) mistrimulti_terrain_job(''',
     '''        for (var h = 0; h < 0; h++) mistrimulti_terrain_job(''', "test_buildings.py", ["test_terrain_inside"]),
    ("no greenhouse snapshot when walking in", "MistriMultiTerrain.gml",
     '''            if (mistrimulti_room_of_building(houses[k]) == room) mistrimulti_terrain_job(''',
     '''            if (false) mistrimulti_terrain_job(''', "test_buildings.py", ["test_terrain_inside"]),
    ("any number is the farm for terrain", "MistriMultiTerrain.gml",
     '''    return is_real(ref) && ref == LocationId.Farm ? GRIDS[LocationId.Farm] : undefined;''',
     '''    return GRIDS[LocationId.Farm];''', "test_buildings.py", ["test_terrain_inside"]),
    ("chest inside a building: any room of that kind", "MistriMultiContainers.gml",
     '''    if (grid != undefined && grid[$ "dyn_index"] != undefined) return room == mistrimulti_room_of_grid(grid);''',
     '''    if (false) return room == mistrimulti_room_of_grid(grid);''', "test_containers.py", ["test_chest_inside_a_building"]),
    ("chest inside a building: not shared", "MistriMultiContainers.gml",
     '''        return inside == undefined ? undefined : { key:''', '''        return undefined; return inside == undefined ? undefined : { key:''', "test_containers.py", ["test_chest_inside_a_building"]),
    ("furniture inside a barn: room unchecked", "MistriMultiRanch.gml",
     '''    return is_struct(peer) && peer[$ "room"] == room;''', '''    return true;''', "test_ranch.py", ["test_furniture_inside_buildings", "test_machine_inside_a_building"]),
    ("furniture inside a barn: placed on the farm", "MistriMultiRanch.gml",
     '''    var grid = mistrimulti_grid_by_ref(d[$ "l"]);
    if (grid == undefined || !__mistrimulti_ranch_int(d[$ "it"], 0, ItemId.LEN - 1)) return __mistrimulti_ranch_no("bad_request");
    if (!__mistrimulti_ranch_here(from, mistrimulti_room_of_grid(grid))) return __mistrimulti_ranch_no("not_here");
    var proto = ITEM_PROTOTYPES[d.it];''', '''    var grid = mistrimulti_grid_by_ref(d[$ "l"]);
    if (grid == undefined || !__mistrimulti_ranch_int(d[$ "it"], 0, ItemId.LEN - 1)) return __mistrimulti_ranch_no("bad_request");
    if (!__mistrimulti_ranch_here(from, mistrimulti_room_of_grid(grid))) return __mistrimulti_ranch_no("not_here");
    grid = GRIDS[LocationId.Farm];
    var proto = ITEM_PROTOTYPES[d.it];''', "test_ranch.py", ["test_furniture_inside_buildings"]),
]


def main():
    bad = 0
    for name, filename, old, new, script, tests in MUTATIONS:
        path = GML / filename
        original = path.read_text()
        if old not in original:
            print("MISSING PATTERN:", name)
            bad += 1
            continue
        try:
            path.write_text(original.replace(old, new, 1))
            out = subprocess.run([sys.executable, script] + tests, cwd=ROOT / "tests", capture_output=True, text=True, timeout=1800)
            caught = out.returncode != 0
        finally:
            path.write_text(original)
        print(("caught " if caught else "NOT CAUGHT ") + name, flush=True)
        bad += 0 if caught else 1
    sys.exit(1 if bad else 0)


main()
