"""Mutation check for the shared story cutscenes (the "held scene" part of MistriMultiStory.gml and the `view` field of the
rewards section in MistriMultiProgress.gml): each mutation must make at least one test fail.

    python3 tests/mutate_story_views.py

Breaks one rule of the feature at a time (a scene applied silently instead of offered, a quest not held for its scene, objects
removed twice, a reward paid twice or never, the held scenes forgotten by a restart, nobody gives up, a hand-made trigger
accepted, ...), runs the tests that should notice, and restores the file. Exit status 1 if a mutation goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GML = ROOT / "mod/mistrimulti/gml/MistriMultiStory.gml"
PROGRESS = ROOT / "mod/mistrimulti/gml/MistriMultiProgress.gml"

BASIC = ["test_view_scene_is_watched_by_everybody"]

# name, [(old, new), ...], tests that must fail
MUTATIONS = [
    ("every new world scene is applied silently, as before",
     [("            var shown = __mistrimulti_story_view_wanted(st, names[i], local) != undefined;", "            var shown = false;")],
     BASIC + ["test_view_either_player_first_and_at_once"]),
    ("the game is not told it may offer the scene again (neither when it is held nor on later passes)",
     [("    st.view[$ name] = total_days();\n    __mistrimulti_story_view_arm(name, true);\n", "    st.view[$ name] = total_days();\n"),
      ("        if (how == \"\") {\n            __mistrimulti_story_view_arm(name, true);\n            continue;", "        if (how == \"\") {\n            continue;")],
     BASIC),
    ("the quests of a held scene are not held back",
     [("        var cap = __mistrimulti_story_cap(st, names[i]);\n", "        var cap = undefined;\n")],
     BASIC + ["test_view_quest_waiting_for_the_scene"]),
    ("the objects a scene removes are removed a second time at the viewing",
     [("    MIST.blackboard.set(\"removed_scene_objects\", true);\n", "")], BASIC),
    ("the items of a once-only scene are never paid after the viewing",
     [("        if (c[$ \"give_items_once\"] == true) __mistrimulti_story_scene_gifts(name, c, true, false);\n", "")], BASIC),
    ("the baths and items are paid when the scene is held and again at the viewing",
     [("    __mistrimulti_story_scene_effects(name, CUTSCENES.get(name));\n    st.view[$ name] = total_days();",
       "    __mistrimulti_story_scene_effects(name, CUTSCENES.get(name));\n    __mistrimulti_story_scene_gifts(name, CUTSCENES.get(name), true, true);\n    st.view[$ name] = total_days();")],
     BASIC),
    ("a restart forgets which scenes were waiting to be watched",
     [("    T2R.write(\"mm_view\", array_length(struct_get_names(st.view)) == 0 ? undefined : json_stringify(st.view));", "")],
     ["test_view_survives_restarts"]),
    ("a held scene waits for ever",
     [("#macro MISTRIMULTI_STORY_PATIENCE 7 ", "#macro MISTRIMULTI_STORY_PATIENCE 1000000 ")], ["test_view_nobody_waits_for_ever"]),
    ("a player who is already past the quest step is made to wait for the scene",
     [("    if (!__mistrimulti_story_caps_hold(info, local)) {\n        __mistrimulti_story_view_why(st, name, \"this player is already past",
       "    if (false) {\n        __mistrimulti_story_view_why(st, name, \"this player is already past"),
      ("        else if (!__mistrimulti_story_caps_hold(info, local)) how = ", "        else if (false) how = ")],
     ["test_view_player_ahead_of_the_scene"]),
    ("the game may offer the scene again after it was watched",
     [("    __mistrimulti_story_view_arm(name, false);\n    struct_remove(st.view, name);", "    struct_remove(st.view, name);"),
      ("    st.watching[$ active.id] = true;\n    __mistrimulti_story_view_arm(active.id, false);\n", "    st.watching[$ active.id] = true;\n")],
     BASIC),
    ("a hand-made trigger counts as one the game arms",
     [("(trigger != undefined && trigger[$ \"manually_activated\"] != true)", "(trigger != undefined)")],
     ["test_view_falls_back_to_the_silent_route"]),
    ("a new character is made to watch the story so far",
     [("    if (T2R.read(\"mm_paid_init\") != true) {\n        var done = struct_get_names(st.sc);", "    if (false) {\n        var done = struct_get_names(st.sc);")],
     ["test_view_late_join_and_new_character"]),
    ("a quest that a scene starts is started (and finished) before the scene",
     [("    if (is_array(started)) for (var i = 0; i < array_length(started); i++) __mistrimulti_story_cap_set(caps, started[i], -1);\n", "")],
     ["test_view_scene_that_starts_a_quest"]),
    ("a scene that advances a quest at an unknown step is shown",
     [("caps[$ progressed] == undefined) {\n        return \"it advances", "false) {\n        return \"it advances")],
     ["test_view_falls_back_to_the_silent_route"]),
    ("a quest condition inside an \"or\" is ignored",
     [("            for (var j = 0; j < array_length(v); j++) if (!__mistrimulti_story_view_req(st, v[j], caps, depth + 1, inv)) return false;",
       "            for (var j = 0; j < array_length(v); j++) __mistrimulti_story_view_req(st, v[j], caps, depth + 1, inv);")],
     ["test_view_falls_back_to_the_silent_route"]),
    ("a world fact that the scene needs to be false is ignored (the mirror makes it true)",
     [("                if ((e[1] == true) == inv) return false;\n", "")], ["test_view_falls_back_to_the_silent_route"]),
    ("a scene that must not have been seen is held although the mirror marks scenes as seen",
     [("if (is_string(v[j]) && __mistrimulti_story_scene_world(st, v[j])) return false;", "if (false) return false;")],
     ["test_view_falls_back_to_the_silent_route"]),
    ("the quest task that waits for a scene is not held",
     [("    if (query != undefined) __mistrimulti_story_cap_set(caps, query.quest, query.stage);\n", "")],
     ["test_view_quest_waiting_for_the_scene"]),
    ("any number of scenes may wait at once",
     [("if (array_length(struct_get_names(st.view)) >= MISTRIMULTI_STORY_VIEW_MAX) {\n        __mistrimulti_story_view_why(st, name, \"too many",
       "if (false) {\n        __mistrimulti_story_view_why(st, name, \"too many")],
     ["test_view_many_scenes_and_the_limit"]),
    ("the held scenes are not sorted out at the start of a pass",
     [("    __mistrimulti_story_views(st, local);\n    if (!st.ready) {", "    if (!st.ready) {"),
      ("    __mistrimulti_story_views(st, local);\n    var up = ", "    var up = ")],
     BASIC),
    ("a record that no longer holds the scene still pays for it",
     [("    } else if (how != \"gone\") {", "    } else {")], ["test_view_record_replaced_and_world_left"]),
    ("leaving the world leaves the scenes switched on",
     [("    if (is_struct(st[$ \"view\"])) __mistrimulti_story_view_disarm(st);\n", "")], ["test_view_record_replaced_and_world_left"]),
    ("a scene that cannot repeat is offered although the game repeats it anyway",
     [("    if (c[$ \"can_repeat\"] == true && st.view[$ name] == undefined) return \"the game repeats it anyway\";\n", "")],
     ["test_view_falls_back_to_the_silent_route"]),
    ("a held scene with a corrupt entry in the save is switched on",
     [("            if (!MIST.scene_history.contains(names[i]) || __mistrimulti_story_view_info(st, names[i]) == undefined) continue;\n", ""),
      ("        if (!MIST.scene_history.contains(name)) how = \"gone\";\n        else if (st.watching", "        if (false) how = \"gone\";\n        else if (st.watching")],
     ["test_view_corrupt_save_is_ignored"]),
    ("a viewing is noticed only when the scene is long over",
     [("        if (MIST.is_running()) __mistrimulti_story_views_watch(st);\n", "")], BASIC),
]

PROGRESS_MUTATIONS = [
    ("the scenes waiting to be watched are not carried in the player's record",
     [("    if (array_length(struct_get_names(view)) > 0) out.view = view;\n", "")], ["test_sections_round_trip"]),
    ("the scenes waiting to be watched are not restored from the record",
     [("    T2R.write(\"mm_view\", is_struct(view) && array_length(struct_get_names(view)) > 0 ? json_stringify(view) : undefined);\n", "")],
     ["test_sections_round_trip"]),
    ("a record may hold any number of waiting scenes",
     [("        if (array_length(held) > 64) return false;\n", "")], ["test_validation"]),
    ("a waiting scene may have any day",
     [(" || day < 0 || day > 1000000) return false;", ") return false;")], ["test_validation"]),
]

PROGRESS_RUNNER = "import sys, test_progress as t\nfor n in sys.argv[1:]: getattr(t, n)()"
bad = 0
for gml_file, table in ((GML, MUTATIONS), (PROGRESS, PROGRESS_MUTATIONS)):
    original = gml_file.read_text()
    try:
        for name, edits, tests in table:
            text = original
            missing = [old for old, new in edits if old not in text]
            if missing:
                print("MISSING PATTERN:", name, "->", missing[0][:60])
                bad += 1
                continue
            for old, new in edits:
                text = text.replace(old, new, 1)
            gml_file.write_text(text)
            cmd = [sys.executable, "test_story.py"] + tests if gml_file == GML else [sys.executable, "-c", PROGRESS_RUNNER] + tests
            out = subprocess.run(cmd, cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
            caught = out.returncode != 0
            print(("caught " if caught else "NOT CAUGHT ") + name)
            bad += 0 if caught else 1
    finally:
        gml_file.write_text(original)
sys.exit(1 if bad else 0)
