"""Mutation check for the starter kit: each mutation must make at least one tests/test_starterkit.py test fail.

    python3 tests/mutate_starterkit.py

Breaks one rule of the GML at a time (a kit that is never given, given twice, given to an old character, given before the defaults
wipe the ledger, a ledger that is not carried, ...), runs the tests that should notice, and restores the files. Exit status 1 if a
mutation goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
S = "MistriMultiStory.gml"
P = "MistriMultiProgress.gml"
D = "MistriMultiPlayerData.gml"

NEW = ["test_new_guest_gets_the_kit"]

MUTATIONS = [
    ("the kit is never given", P, "        try { mistrimulti_story_kit_grant(); }", "        try { var skipped = 1; }", NEW),
    ("a new character does not raise the flag", D, "    r.kit_owed = true;    //", "    r.kit_owed = false;    //", NEW + ["test_wiring"]),
    ("the flag is never cleared (every progress start gives the kit)", P, "        r.kit_owed = false;\n        try { mistrimulti_story_kit_grant(); }",
     "        try { mistrimulti_story_kit_grant(); }", ["test_records_without_a_kit_are_left_alone", "test_wiring"]),
    ("an old character with a core record only gets the kit", P, '    if (r[$ "kit_owed"] == true) {', "    if (true) {",
     ["test_records_without_a_kit_are_left_alone", "test_wiring"]),
    ("the kit is given before the defaults wipe the ledger", P,
     "    mistrimulti_progress_restore({ sections: sections });\n", "    try { mistrimulti_story_kit_grant(); } catch (e) {}\n    mistrimulti_progress_restore({ sections: sections });\n",
     ["test_wiring", "test_new_guest_gets_the_kit"]),
    ("the ledger is not written (the kit can be given twice)", S, '    T2R.write("mm_kit", json_stringify(covered));\n', "",
     ["test_failures_are_contained", "test_rejoin_gets_nothing"]),
    ("the ledger is written after the gifts (a failed gift is retried)", S,
     '    T2R.write("mm_kit", json_stringify(covered));\n    for (var i = 0; i < array_length(covered); i++) {\n        var c = CUTSCENES.get(covered[i]);\n',
     '    for (var i = 0; i < array_length(covered); i++) {\n        var c = CUTSCENES.get(covered[i]);\n        if (T2R.read("mm_kit") == undefined && i == 0) throw "x";\n',
     ["test_failures_are_contained"]),
    ("the grant ignores the ledger", S, '    if (T2R.read("mm_kit") != undefined) return covered;\n', "", ["test_failures_are_contained"]),
    ("scenes that the host has not run are given", S, " || !MIST.scene_history.contains(names[i])) continue;", ") continue;",
     ["test_later_day_and_other_worlds", "test_new_guest_gets_the_kit"]),
    ("every scene in the history is part of the kit", S, '    return ["prologue", "day_zero", "farm_introduction", "adeline_quest_board"];',
     '    return CUTSCENES.keys();', ["test_later_day_and_other_worlds", "test_new_guest_gets_the_kit"]),
    ("the scene's bath is not given", S, "            __mistrimulti_story_scene_gifts(covered[i], c, true, true);", "            __mistrimulti_story_scene_gifts(covered[i], c, true, false);", NEW),
    ("the scene's spell and mana are not given", S, "            __mistrimulti_story_scene_spell(c);\n            var tutorial", "            var tutorial", NEW),
    ("the story mode is ignored", S, '        if (CUTSCENES.get(names[i])[$ "requires_story_mode"] == true && STORY_ENABLED != true) continue;\n', "",
     ["test_later_day_and_other_worlds"]),
    ("a failing gift breaks the progress start", S, '        } catch (e) {\n            __mistrimulti_story_warn("The starter kit of scene', '        } catch (e) {\n            throw e;\n            __mistrimulti_story_warn("The starter kit of scene',
     ["test_failures_are_contained"]),
    ("the tutorial popup is shown while the editor is open", S, " || !r.player_ready || r.character_pending) return;", " || !r.player_ready) return;",
     ["test_tutorial_after_the_editor"]),
    ("the tutorial popup is shown again and again", S, "    array_delete(list, 0, 1);\n", "", ["test_tutorial_after_the_editor"]),
    ("a seen tutorial is shown again", S, "    if (!ARI.tutorials_seen[tutorial]) await_popup", "    await_popup", ["test_tutorial_after_the_editor"]),
    ("the pump is not part of the story tick", S, '        if (r.mode == "join") __mistrimulti_story_kit_pump(r);\n', "", ["test_wiring"]),
    ("the ledger is not carried in the record", P, "    if (kit != undefined) out.kit = kit;\n", "", ["test_new_guest_gets_the_kit", "test_rejoin_gets_nothing"]),
    ("a restored record keeps the ledger of the game it lands in", P, '    T2R.write("mm_kit", is_array(v[$ "kit"]) ? json_stringify(v.kit) : undefined);\n', "",
     ["test_wiring", "test_records_without_a_kit_are_left_alone"]),
    ("a record may hold any kit list", P, "        if (!is_array(kit) || array_length(kit) > 16) return false;\n", "        if (!is_array(kit)) return false;\n", ["test_record_validation"]),
    ("a record may hold any kit entry", P, "        for (var i = 0; i < array_length(kit); i++) if (!mistrimulti_progress_text_valid(kit[i], 96)) return false;\n", "", ["test_record_validation"]),
    ("a new session keeps the flag", P, "    r.kit_owed = false;\n    r.kit_tutorials = [];\n}", "    r.kit_tutorials = [];\n}", ["test_wiring"]),
]

bad = 0
backups = {}
try:
    for name, file, old, new, tests in MUTATIONS:
        path = ROOT / "mod/mistrimulti/gml" / file
        original = backups.setdefault(file, path.read_text())
        if original.count(old) != 1:
            print("MISSING PATTERN:", name, "->", old[:60])
            bad += 1
            continue
        path.write_text(original.replace(old, new, 1))
        out = subprocess.run([sys.executable, "test_starterkit.py"] + tests, cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
        caught = out.returncode != 0
        print(("caught " if caught else "NOT CAUGHT ") + name)
        bad += 0 if caught else 1
        path.write_text(original)
finally:
    for file, text in backups.items():
        (ROOT / "mod/mistrimulti/gml" / file).write_text(text)
sys.exit(1 if bad else 0)
