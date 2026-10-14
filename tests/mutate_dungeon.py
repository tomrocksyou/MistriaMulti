"""Mutation check for MistriMultiDungeon.gml: each mutation must make at least one dungeon test fail.

    python3 tests/mutate_dungeon.py

Breaks one rule of the GML at a time (letting a copy die by itself, paying drops for a remote kill, not seeding the generator,
...), runs the tests that should notice, and restores the file. Exit status 1 if a mutation goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GML = ROOT / "mod/mistrimulti/gml/MistriMultiDungeon.gml"

MUTATIONS = [
    ("a copy may die by itself", '''        tarball.damage = max(0, min(amount, mon.hit_points - 1));''', '''        tarball.damage = tarball.damage;''',
     ["test_two_players_one_enemy", "test_loss_matrix"]),
    ("a remote kill is not silent", '''    mon.skip_destroy_logic = true;
    instance_destroy(mon);''', '''    instance_destroy(mon);''', ["test_two_players_one_enemy"]),
    ("nobody is the killer", '''        res.k = from;''', '''        res.k = -1;''', ["test_two_players_one_enemy", "test_poison_and_late_hit"]),
    ("the killer's copy is removed silently", '''        if (res[$ "k"] == r.id) mon.hit_points = 0;''', '''        if (false) mon.hit_points = 0;''',
     ["test_two_players_one_enemy"]),
    ("floors are not seeded", '''        random_set_seed(mistrimulti_dg_hash(d.my_seed, "floor:" + string(flr)));''', '''        d.errors = d.errors;''',
     ["test_seed_matters", "test_same_floor"]),
    ("the itinerary is kept", '''        runner.itinerary = itinerary;''', '''        d.errors = d.errors;''', ["test_same_floor"]),
    ("extra nodes are kept", '''            if (mistrimulti_dg_node_at(n)) erase_object_node_by_parent(GRID, n);''', '''            d.errors = d.errors;''',
     ["test_same_floor"]),
    ("the record's ladder score is ignored", '''    if (header.need > 0) runner.ladder_score_needed = header.need;''', '''    d.errors = d.errors;''', ["test_same_floor"]),
    ("the host does not apply a guest's action to its own room", '''            if (from > 0 && res[$ "ok"] == true && o != "man") mistrimulti_dg_apply(d, res);''', '''            d.errors = d.errors;''',
     ["test_two_players_one_enemy"]),
    ("swings at shared rocks are not taken over", '''        return taken ? keep : undefined;''', '''        return undefined;''', ["test_nodes"]),
    ("a chest opened elsewhere stays shut", '''        if (res[$ "op"] == 1) mistrimulti_dg_open_chest(n);''', '''        d.errors = d.errors;''', ["test_nodes"]),
    ("results sent during a join are lost", '''pend[i].v > header.rv''', '''false''', ["test_results_during_a_join"]),
    ("the run never ends", '''    else if (d.used && r.ticks - d.empty_at > MISTRIMULTI_DG_EMPTY) mistrimulti_dg_new_run(d);''', '''    d.errors = d.errors;''',
     ["test_leave_and_rejoin"]),
    ("leaving is not recorded", '''        d.at[from] = undefined;
        return { ok: true, o: "here", st: "left" };''', '''        return { ok: true, o: "here", st: "left" };''', ["test_leave_and_rejoin"]),
    ("fields are not range checked", '''    return is_real(v) && v == floor(v) && v >= lo && v <= hi;''', '''    return is_real(v);''',
     ["test_hostile_input", "test_ladder_position_and_hostile_hits"]),
    ("a second ladder is allowed", '''    if (d.lad != undefined) return false;''', '''    d.errors = d.errors;''', ["test_ladder_position_and_hostile_hits"]),
    ("poison goes unreported", '''        if (now >= expected) return;''', '''        return;''', ["test_poison_and_late_hit"]),
    ("floors share a room key", '''return ":r" + string(d.my_run) + "f" + string(d.f);''', '''return ":r" + string(d.my_run);''', ["test_floors_apart"]),
    ("another room shares the record", '''    if (fl != undefined && fl.rm != room_name) {''', '''    if (false) {''', ["test_different_rooms_are_not_shared"]),
    ("a lost host does not unshare the floor", '''        if (d.offline > MISTRIMULTI_DG_OFFLINE) mistrimulti_dg_unsync(d);''', '''        d.errors = d.errors;''', ["test_unshared_floors"]),
    ("a restarted host does not adopt the run", '''        if (typeof(data[$ "rj"]) == "bool" && data.rj && !d.used && mistrimulti_dg_int(data[$ "seed"], 1, 2147483647)) {''',
     '''        if (false) {''', ["test_host_restart"]),
]

original = GML.read_text()
bad = 0
try:
    for name, old, new, tests in MUTATIONS:
        if old not in original:
            print("MISSING PATTERN:", name)
            bad += 1
            continue
        GML.write_text(original.replace(old, new, 1))
        out = subprocess.run([sys.executable, "test_dungeon.py"] + tests, cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
        caught = out.returncode != 0
        print(("caught " if caught else "NOT CAUGHT ") + name)
        bad += 0 if caught else 1
finally:
    GML.write_text(original)
sys.exit(1 if bad else 0)
