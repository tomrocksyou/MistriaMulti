"""Mutation check for MistriMultiStory.gml: each mutation must make at least one story test fail.

    python3 tests/mutate_story.py

Breaks one rule of the GML at a time (accepting personal quests, lowering the world story, skipping the boxes of a finished
stage, acting during a cutscene, moving a villager in sight, ...), runs the tests that should notice, and restores the file.
Exit status 1 if a mutation goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GML = ROOT / "mod/mistrimulti/gml/MistriMultiStory.gml"

# name, [(old, new), ...], tests that must fail
MUTATIONS = [
    ("personal quests accepted from a claim",
     [("strict ? !(__mistrimulti_story_quest_world(st, e[0]) && __mistrimulti_story_quest_level_ok(e[0], e[1]))",
       "strict ? !__mistrimulti_story_quest_level_ok(e[0], e[1])")], ["test_hostile_input"]),
    ("the world story can go down",
     [("if (e[1] > (st.q[$ e[0]] ?? -1)) {", "if (e[1] != (st.q[$ e[0]] ?? -1)) {")], ["test_merge_rules"]),
    ("a stage that does not exist is accepted",
     [("return quest != undefined && level < quest.tasks.count();", "return quest != undefined;")], ["test_hostile_input"]),
    ("the host does not tell the other guests",
     [("    return mistrimulti_story_merge(st, data, true, MISTRIMULTI_STORY_CLAIM_MAX);\n}",
       "    mistrimulti_story_merge(st, data, true, MISTRIMULTI_STORY_CLAIM_MAX);\n    return { q: [], sc: [], f: [], k: {} };\n}")],
     ["test_guest_progress", "test_same_step_race"]),
    ("a finished quest is not marked finished",
     [("        QUEST_LOG.completed.insert(name);\n        QUEST_LOG.completion_timestamps.insert(name, CALENDAR.time);",
       "        QUEST_LOG.completion_timestamps.insert(name, CALENDAR.time);")], ["test_host_progress", "test_guest_progress"]),
    ("the turn-in boxes of a finished stage stay",
     [("        __mistrimulti_story_clear_boxes(quest, level);\n", "")], ["test_guest_progress"]),
    ("the game is changed during a cutscene and the end of day",
     [("if (MIST.is_running() || ARI.end_of_day_status != undefined) return;", "if (false) return;")], ["test_cutscene_hold"]),
    ("the snapshot is never sent",
     [("        if (!mistrimulti_event_can_emit(3) || !mistrimulti_event_send_blob(", "        if (true || !mistrimulti_event_send_blob(")],
     ["test_late_join", "test_host_scene_and_join"]),
    ("heart events and romance scenes count as the world's",
     [("        var personal = c.romantic_choice_warning != undefined || array_length(c.heart_level_changes) > 0\n            || c.test_target == SceneTestTarget.MarriageAndChildren;",
       "        var personal = false;")], ["test_world_scenes"]),
    ("the festival's quest is mirrored",
     [(" && st.festq[$ name] != true;", ";")], ["test_host_progress"]),
    ("a villager in sight is moved",
     [("if (st.miss[$ key] >= MISTRIMULTI_STORY_MISS && unseen) {", "if (st.miss[$ key] >= MISTRIMULTI_STORY_MISS) {")],
     ["test_npc_in_sight_is_left_alone"]),
    ("a plan is used on any day",
     [("if (!is_struct(plan) || plan.d != total_days()) return;", "if (!is_struct(plan)) return;")], ["test_festival_flag"]),
    ("a claim is repeated every second",
     [("        if (!is_struct(p) || p.n < up.q[i][1]) array_push(claim.q, up.q[i]);", "        array_push(claim.q, up.q[i]);")],
     ["test_claim_is_sent_once"]),
    ("a refused claim is asked again and again",
     [("            st.bad[$ \"u:\" + keys[i]] = true;\n", "")], ["test_refused_claim_is_not_repeated"]),
    ("a delta from a guest is accepted",
     [("    if (!__mistrimulti_story_on(\"join\") || from != 0) return true;\n    mistrimulti_story_merge(__mistrimulti_story(), data, false, MISTRIMULTI_STORY_CLAIM_MAX);",
       "    if (!__mistrimulti_story_on(\"join\")) return true;\n    mistrimulti_story_merge(__mistrimulti_story(), data, false, MISTRIMULTI_STORY_CLAIM_MAX);")],
     ["test_hostile_input"]),
    ("an unknown schedule is followed",
     [(" || !__mistrimulti_story_known_schedule(st, want)) continue;", ") continue;")], ["test_hostile_input"]),
    ("a new host session keeps the old mirror",
     [("    st.q = {};\n    st.sc = {};\n    st.f = {};\n    st.k = { n: 0, b: 0, t: 0 };\n    st.pend = {};\n    st.want_at = -1000000;\n}\n\nfunction __mistrimulti_story_warn",
       "    st.pend = {};\n    st.want_at = -1000000;\n}\n\nfunction __mistrimulti_story_warn")], ["test_facts_and_counters", "test_host_restart"]),
    ("a delta is merged before it is known to fit in the queue",
     [("    } else if (mistrimulti_event_can_emit(12)) {", "    } else if (true) {"),
      ("        if (!__mistrimulti_story_empty(accepted)) __mistrimulti_story_broadcast(accepted);\n    }\n    __mistrimulti_story_down",
       "        if (!__mistrimulti_story_empty(accepted) && mistrimulti_event_can_emit(12)) __mistrimulti_story_broadcast(accepted);\n    }\n    __mistrimulti_story_down")],
     ["test_many_changes"]),
    ("the guest steers villagers it cannot see and sees alike (activity)",
     [("&& unseen && handler.state != ActivityState.Traveling", "&& handler.state != ActivityState.Traveling")],
     ["test_npc_in_sight_is_left_alone", "test_npc_activity_and_room_drift", "test_npc_plan"]),
    ("a game that is ahead of the host cannot tell it",
     [("    var up = __mistrimulti_story_up(st, local);\n    var claim", "    var up = { q: [], sc: [], f: [], k: {} };\n    var claim")],
     ["test_guest_progress", "test_guest_restart", "test_host_restart"]),
]

original = GML.read_text()
bad = 0
try:
    for name, edits, tests in MUTATIONS:
        text = original
        missing = [old for old, new in edits if old not in text]
        if missing:
            print("MISSING PATTERN:", name, "->", missing[0][:60])
            bad += 1
            continue
        for old, new in edits:
            text = text.replace(old, new, 1)
        GML.write_text(text)
        out = subprocess.run([sys.executable, "test_story.py"] + tests, cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
        caught = out.returncode != 0
        print(("caught " if caught else "NOT CAUGHT ") + name)
        bad += 0 if caught else 1
finally:
    GML.write_text(original)
sys.exit(1 if bad else 0)
