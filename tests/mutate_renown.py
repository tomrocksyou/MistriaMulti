"""Mutation check for MistriMultiRenown.gml (and the renown capture in MistriMultiProgress.gml): each mutation must make at
least one renown test fail.

    python3 tests/mutate_renown.py

Breaks one rule of the GML at a time (counting the guests' shipping copy, forgetting the commit, never marking carriers, ...),
runs the tests that should notice, and restores the files. Exit status 1 if a mutation goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RENOWN = ROOT / "mod/mistrimulti/gml/MistriMultiRenown.gml"
PROGRESS = ROOT / "mod/mistrimulti/gml/MistriMultiProgress.gml"

MUTATIONS = [
    (RENOWN, "carriers are not marked (so they are counted again)", "    entry.mm_carrier = true;\n", "",
     ["test_shipping_rank_up_reaches_every_player", "test_filter_gating"]),
    (RENOWN, "a guest's copy of the shipping sale is sent", "if (kind == \"gold\" || kind == \"story\") return 0;",
     "if (kind == \"story\") return 0;", ["test_each_kind_is_counted_once"]),
    (RENOWN, "a guest's copy of a story quest is sent", "if (kind == \"gold\" || kind == \"story\") return 0;",
     "if (kind == \"gold\") return 0;", ["test_each_kind_is_counted_once"]),
    (RENOWN, "the host does not add its own gains to the pool", "            w.pool = __mistrimulti_renown_clamp(w.pool + d);\n            w.dirty = true;",
     "            w.dirty = true;", ["test_shipping_rank_up_reaches_every_player"]),
    (RENOWN, "the host does not announce its own gains", "            w.dirty = true;\n        }\n    } catch", "        }\n    } catch",
     ["test_shipping_rank_up_reaches_every_player"]),
    (RENOWN, "a guest's own gain is not sent", "            if (d != 0) {\n                d = max(", "            if (false) {\n                d = max(",
     ["test_guest_gain_reaches_host_and_other_guest"]),
    (RENOWN, "a guest's unanswered gain is forgotten (it gets its own gain back as a carrier)",
     "    for (var j = 0; j < array_length(ids); j++) sum += w.pending[$ ids[j]];\n", "",
     ["test_carrier_does_not_wait_for_the_answer"]),
    (RENOWN, "an answered gain stays pending", "        if (ctx.mine && struct_exists(w.pending, ctx.id)) struct_remove(w.pending, ctx.id);\n        __mistrimulti_renown_take",
     "        __mistrimulti_renown_take", ["test_guest_gain_reaches_host_and_other_guest", "test_exactly_once_under_faults"]),
    (RENOWN, "answers do not carry the total", "if (is_struct(result) && result[$ \"ok\"] == true && __mistrimulti_renown_total(result[$ \"p\"])) w.known = result.p;",
     "", ["test_guest_gain_reaches_host_and_other_guest", "test_everyone_gains_at_once"]),
    (RENOWN, "amounts are not range checked", " && d >= -MISTRIMULTI_RENOWN_MAX_DELTA && d <= MISTRIMULTI_RENOWN_MAX_DELTA;", ";",
     ["test_hostile_requests_and_state"]),
    (RENOWN, "fractional amounts accepted", "return is_real(d) && d == floor(d) && d >=", "return is_real(d) && d >=",
     ["test_hostile_requests_and_state"]),
    (RENOWN, "the pool is not capped at what the game can hold", "    return max(0, min(v, __mistrimulti_renown_max()));", "    return max(0, v);",
     ["test_hostile_requests_and_state"]),
    (RENOWN, "a forged state total is accepted from anybody", "    if (__mistrimulti_runtime().mode != \"join\" || from != 0) return true;\n    try {\n        var w = __mistrimulti_renown();\n        if (is_struct(data)",
     "    if (__mistrimulti_runtime().mode != \"join\") return true;\n    try {\n        var w = __mistrimulti_renown();\n        if (is_struct(data)",
     ["test_hostile_requests_and_state"]),
    (RENOWN, "an empty carrier is made when nothing is missing", "    if (gap < 1) return;", "    if (gap < 0) return;",
     ["test_carriers_are_derived_state", "test_joining_and_rejoining"]),
    (RENOWN, "every gap makes a new carrier", "        if (__mistrimulti_renown_is_carrier(e)) {\n            e.gold = (renown_entry_value(e) + gap) * 100 - 50;\n            return;\n        }",
     "        if (false) return;", ["test_carriers_are_derived_state"]),
    (RENOWN, "the carrier is not counted as carried (it is created again and again)", "        if (__mistrimulti_renown_is_carrier(e)) sum += renown_entry_value(e);",
     "", ["test_shipping_rank_up_reaches_every_player", "test_carriers_are_derived_state"]),
    (RENOWN, "carriers stay in the list at a save", "        if (__mistrimulti_renown_is_carrier(list.get(i))) list.remove(i);", "",
     ["test_host_restart", "test_carriers_are_derived_state"]),
    (RENOWN, "the commit is never used", "if (commit != undefined) pool = max(pool, commit.renown);", "", ["test_host_restart"]),
    (RENOWN, "the commit's day is not checked", "c[$ \"day\"] == string(CALENDAR.time)", "true", ["test_host_restart"]),
    (RENOWN, "a new character is paid every past rank-up", "        if (ARI.renown == 0 && carried == 0) {", "        if (false) {",
     ["test_joining_and_rejoining"]),
    (RENOWN, "a guest that is ahead is taken back", "    if (gap < 1) return;",
     "    if (gap < 0) { ARI.renown = want; return; }\n    if (gap < 1) return;", ["test_joining_and_rejoining", "test_a_lost_request_is_dropped"]),
    (RENOWN, "no snapshot for a joining guest (nor a request of its own)", [("if (r.mode == \"host\") w.snaps[slot] = joined && slot != 0;",
     "if (r.mode == \"host\") w.snaps[slot] = false;"), ("else if (slot == 0 && joined) w.resync = true;", "")], None,
     ["test_joining_and_rejoining", "test_guest_away_and_back"]),
    (RENOWN, "another player's renown goes through the filter", " || ctx[$ \"player\"] != ARI) return undefined;", ") return undefined;",
     ["test_filter_gating"]),
    (RENOWN, "an entry that does not match the value is trusted", "    if (renown_entry_value(e) != value) return \"own\";\n", "",
     ["test_filter_gating"]),
    (RENOWN, "a lost request stays pending forever", "        if (struct_exists(w.pending, ctx.id)) struct_remove(w.pending, ctx.id);\n        if (!is_struct(result))",
     "        if (!is_struct(result))", ["test_a_lost_request_is_dropped", "test_exactly_once_under_faults"]),
    (PROGRESS, "the player's record keeps the carriers", "        if (is_struct(e) && e[$ \"mm_carrier\"] == true) continue;\n        array_push(out, serialize_renown_entry(e));",
     "        array_push(out, serialize_renown_entry(e));", ["test_carriers_are_derived_state"]),
]

originals = {path: path.read_text() for path in (RENOWN, PROGRESS)}
bad = 0
try:
    for path, name, old, new, tests in MUTATIONS:
        pairs = old if isinstance(old, list) else [(old, new)]
        text = originals[path]
        if any(a not in text for a, _b in pairs):
            print("MISSING PATTERN:", name)
            bad += 1
            continue
        for a, b in pairs:
            text = text.replace(a, b, 1)
        path.write_text(text)
        out = subprocess.run([sys.executable, "test_renown.py"] + tests, cwd=ROOT / "tests", capture_output=True, text=True, timeout=1800)
        caught = out.returncode != 0
        print(("caught " if caught else "NOT CAUGHT ") + name, flush=True)
        bad += 0 if caught else 1
        path.write_text(originals[path])
finally:
    for path, text in originals.items():
        path.write_text(text)
sys.exit(1 if bad else 0)
