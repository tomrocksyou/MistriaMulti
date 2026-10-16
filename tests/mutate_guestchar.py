"""Mutation check for the guest character flow: each mutation must make at least one tests/test_guestchar.py test fail.

    python3 tests/mutate_guestchar.py

Breaks one rule of the GML at a time (an editor that starts from the host's character, a record that replaces the editor, a question
that is never asked, a lost backup, ...), runs the tests that should notice, and restores the files. Exit status 1 if a mutation
goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
C = "MistriMultiCharacter.gml"
S = "MistriMultiPlayerSync.gml"
P = "MistriMultiProgress.gml"
B = "MistriMultiBoot.gml"
V = "MistriMultiSaveSpace.gml"

MUTATIONS = [
    ("the editor starts from the host's character", C, "preset = create_default_player_animation_assets();", "preset = ARI.animation_assets().clone();",
     ["test_new_world_starts_fresh"]),
    ("the name of the host's character is kept", C, "        ARI.name = mistrimulti_character_default_name();\n", "", ["test_new_world_starts_fresh"]),
    ("the host never asks", S, '''var asking = saved != undefined && data[$ "intent"] == "new";''', '''var asking = false;''',
     ["test_new_game_into_a_world_with_a_character_asks"]),
    ("the guest never says it entered through New Game", S, '''
                intent: r[$ "character_entry"] ?? "load" }, 0)''', ''' }, 0)''', ["test_new_game_into_a_world_with_a_character_asks"]),
    ("New character restores the old record", S, "    if (data.keep >= 1 && saved != undefined) {", "    if (saved != undefined) {",
     ["test_new_game_into_a_world_with_a_character_asks"]),
    ("the replaced records are not copied aside", S, "        mistrimulti_player_keep_replaced(data.uid);\n", "", ["test_new_game_into_a_world_with_a_character_asks"]),
    ("the new character gets the old progress", P, 'var replaced = core[$ "replaced"] == true;', "var replaced = false;",
     ["test_new_game_into_a_world_with_a_character_asks"]),
    ("the new character's first upload is refused", S, "        session.revision = 0;\n        session.replaced = true;", "        session.replaced = true;",
     ["test_new_game_into_a_world_with_a_character_asks"]),
    ("the answer is never sent", C, 'ask.sent = mistrimulti_event_emit("profile_choice", { world: r.world_key, uid: r.uid, keep: ask.choice }, 0);',
     "ask.sent = true;", ["test_new_game_into_a_world_with_a_character_asks"]),
    ("a choice nobody asked for is accepted", S, "|| session.asking != true) return true;", ") return true;", ["test_forged_choices_are_ignored"]),
    ("a record replaces the new character in the editor", S, '''        if (r[$ "character_phase"] == "edit") {''', '''        if (false) {''', ["test_record_during_editing_is_ignored"]),
    ("a question closed without an answer is never repeated", C, "        if (ask.gone < 60) return;", "        return;",
     ["test_question_closed_without_answer_is_asked_again"]),
    ("an answer to an old question is accepted", C, "    if (!is_struct(ask) || ask.epoch != epoch || epoch != r.epoch) {", "    if (!is_struct(ask)) {",
     ["test_question_closed_without_answer_is_asked_again"]),
    ("a closed editor lets the guest in", C, "        r.character_menu = undefined;\n        r.character_ready_ticks = 0;\n        return;",
     "        r.character_pending = false;\n        return;", ["test_editor_closed_without_continue_opens_again"]),
    ("an invisible editor stays invisible", C, "r.character_open_ticks >= 180)", "r.character_open_ticks >= 1800000)",
     ["test_invisible_editor_is_shown_and_logged"]),
    ("a failed completion lets the guest in", C, '''    } catch (e) {
        mistrimulti_character_log("completing failed''', '''    } catch (e) {
        r.character_pending = false;
        mistrimulti_character_log("completing failed''', ["test_failures_are_logged_and_retried"]),
    ("a failed open is retried every tick", C, "        r.character_ready_ticks = -300;", "        r.character_ready_ticks = 30;", ["test_failures_are_logged_and_retried"]),
    ("the open failure is not logged", C, '''catch (e) { mistrimulti_character_log("could not be opened (" + string(e) + "); trying again in 5 seconds."); }''',
     '''catch (e) { var skipped = 1; }''', ["test_failures_are_logged_and_retried"]),
    ("the entry path is not recorded", V, "    s.entry = kind;", "", ["test_entry_path"]),
    ("the entry path is not forgotten", V, '    s.mode = "";\n    s.entry = "";', '    s.mode = "";', ["test_entry_path"]),
    ("the ghost thrash is back", B, 'if (p[$ "active"] == true && mistrimulti_local_active()) mistrimulti_update_peer(i);',
     'if (p[$ "active"] == true && r[$ "room_settled"] == true) mistrimulti_update_peer(i);', ["test_no_ghosts_while_the_guest_is_not_playing"]),
    ("the new events are not registered", S, '    mistrimulti_event_register("profile_choice", plain);\n', "", ["test_wiring"]),
]

originals = {}
bad = 0
try:
    for name, which, old, new, tests in MUTATIONS:
        path = ROOT / "mod/mistrimulti/gml" / which
        originals.setdefault(path, path.read_text())
        text = originals[path]
        if old not in text:
            print("MISSING PATTERN:", name)
            bad += 1
            continue
        path.write_text(text.replace(old, new, 1))
        out = subprocess.run([sys.executable, "test_guestchar.py"] + tests, cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
        path.write_text(text)
        caught = out.returncode != 0
        print(("caught " if caught else "NOT CAUGHT ") + name, flush=True)
        bad += 0 if caught else 1
finally:
    for path, text in originals.items():
        path.write_text(text)
sys.exit(1 if bad else 0)
