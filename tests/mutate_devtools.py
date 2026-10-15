"""Mutation check for MistriMultiDevTools.gml (and the two small edits it needs in MistriMultiStory.gml and MistriMultiBoot.gml):
each mutation must make at least one test fail.

    python3 tests/mutate_devtools.py

Breaks one rule at a time (a guest may run it, items are handed out, a refusal is ignored, the story sync does not know the
mines' scenes, the hotkey or debug function is not registered, ...), runs tests/test_devtools.py, and restores the file.
Exit status 1 if a mutation goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GML = ROOT / "mod/mistrimulti/gml"
DEV, STORY, BOOT = (GML / n for n in ("MistriMultiDevTools.gml", "MistriMultiStory.gml", "MistriMultiBoot.gml"))

# file, name, [(old, new), ...], tests that must fail
MUTATIONS = [
    (DEV, "a guest may run it (mode check gone)",
     [('if (!r.enabled || r.mode != "host" || r.id != 0)', 'if (!r.enabled)')], ["test_guest_cannot"]),
    (DEV, "a guest runtime that says it is the host may run it (id check gone)",
     [(' || r.id != 0) return', ') return')], ["test_guest_cannot"]),
    (DEV, "multiplayer off is not checked",
     [('if (!r.enabled || r.mode', 'if (r.mode')], ["test_refused_when_not_safe"]),
    (DEV, "it runs during a cutscene and the end of the day",
     [('if (MIST.is_running() || ARI.end_of_day_status != undefined) return "Not during a cutscene or the end of the day.";', '')],
     ["test_refused_when_not_safe"]),
    (DEV, "it runs before the story sync is ready",
     [('if (!st.data_ok || !st.ready) return', 'if (false) return')], ["test_refused_when_not_safe"]),
    (DEV, "items the alias asks for are handed out",
     [('            array_push(plan.skipped, requirement_to_string(i));\n', '            fulfill_requirement(i, v);\n            array_push(plan.skipped, requirement_to_string(i));\n')],
     ["test_host_unlocks_and_everyone_follows", "test_parts_it_does_not_know_are_left_alone"]),
    (DEV, "nested alias requirements are not followed",
     [('            __mistrimulti_dev_collect(REQUIREMENT_ALIASES[i], plan, depth + 1);', '            array_push(plan.skipped, "alias");')],
     ["test_host_unlocks_and_everyone_follows"]),
    (DEV, "a scene already seen is fulfilled again",
     [('            if (MIST.scene_history.contains(plan.scenes[i])) continue;\n', '')], ["test_second_press_changes_nothing"]),
    (DEV, "the fact is written again every time",
     [('            if (T2R.read(plan.facts[i][0]) == plan.facts[i][1]) continue;\n', '')], ["test_second_press_changes_nothing"]),
    (DEV, "the quest is finished again every time",
     [('            if (QUEST_LOG.completed.contains(plan.quests[i])) continue;\n', '')], ["test_second_press_changes_nothing"]),
    (DEV, "the quest is not finished",
     [('            mistrimulti_story_apply_quest(plan.quests[i], MISTRIMULTI_STORY_DONE);\n', '')],
     ["test_host_unlocks_and_everyone_follows"]),
    (DEV, "the result claims success although the game still reports locked",
     [('        out.ok = out.open;', '        out.ok = true;')], ["test_parts_it_does_not_know_are_left_alone"]),
    (DEV, "the player is not told what happened",
     [('    try { create_notification(ANCHOR.wrap_for_local(text)); } catch (e) {}', '')],
     ["test_host_unlocks_and_everyone_follows", "test_guest_cannot"]),
    (DEV, "the room is not refreshed",
     [('if (out.changed > 0 && CURRENT_LOCATION_ID != LocationId.Dungeon) setup_room();', '')],
     ["test_host_unlocks_and_everyone_follows"]),
    (DEV, "an engine failure escapes",
     [('    } catch (e) {\n        out.ok = false;', '    } catch (e) {\n        throw e;\n        out.ok = false;')], ["test_failure_is_contained"]),
    (STORY, "the story sync does not know the mines' scenes",
     [('try { __mistrimulti_story_scan(REQUIREMENT_ALIASES[Requirement.OpenedMines], scenes, facts, 0); } catch (e) {}', '')],
     ["test_host_unlocks_and_everyone_follows"]),
    (BOOT, "the debug function is not registered",
     [('        mmapi_debug_register_fn("mistrimulti.unlock_mines", mistrimulti_devtools_unlock_mines, { mod_name: "mistrimulti" });\n', '')],
     ["test_registered_for_debug_and_hotkey"]),
    (BOOT, "the hotkey is not registered",
     [('mmapi_hotkey_register_binding(unlock_binding, mistrimulti_devtools_hotkey_unlock_mines);', '')],
     ["test_registered_for_debug_and_hotkey"]),
    (BOOT, "the hotkey takes over F6 for everybody",
     [('mmapi_hotkey_binding_from_name("CONTROL+F6")', 'mmapi_hotkey_binding_from_name("F6")')], ["test_registered_for_debug_and_hotkey"]),
]

bad = 0
for path, name, edits, tests in MUTATIONS:
    original = path.read_text()
    try:
        text = original
        missing = [old for old, new in edits if old not in text]
        if missing:
            print("MISSING PATTERN:", name, "->", missing[0][:60])
            bad += 1
            continue
        for old, new in edits:
            text = text.replace(old, new, 1)
        path.write_text(text)
        out = subprocess.run([sys.executable, "test_devtools.py"] + tests, cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
        caught = out.returncode != 0
        print(("caught " if caught else "NOT CAUGHT ") + name)
        bad += 0 if caught else 1
    finally:
        path.write_text(original)
sys.exit(1 if bad else 0)
