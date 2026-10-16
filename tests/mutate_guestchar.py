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
K = "MistriMultiCharPicker.gml"

MUTATIONS = [
    ("the editor starts from the host's character", C, "preset = create_default_player_animation_assets();", "preset = ARI.animation_assets().clone();",
     ["test_new_world_starts_fresh"]),
    ("the name of the host's character is kept", C, "        ARI.name = mistrimulti_character_default_name();\n", "", ["test_new_world_starts_fresh"]),
    ("the host never asks", S, '''var asking = saved != undefined && data[$ "intent"] == "new";''', '''var asking = false;''',
     ["test_new_game_into_a_world_with_a_character_asks"]),
    ("the guest never says it entered through New Game", S, '''
                intent: r[$ "character_entry"] ?? "load" }, 0)''', ''' }, 0)''', ["test_new_game_into_a_world_with_a_character_asks"]),
    ("New character restores the old record", S, "    } else if (data.keep == 1 && saved != undefined) {", "    } else if (saved != undefined) {",
     ["test_new_game_into_a_world_with_a_character_asks"]),
    ("the replaced records are not copied aside", S, "        mistrimulti_player_keep_replaced(data.uid);\n", "", ["test_new_game_into_a_world_with_a_character_asks"]),
    ("the new character gets the old progress", P, 'var replaced = core[$ "replaced"] == true;', "var replaced = false;",
     ["test_new_game_into_a_world_with_a_character_asks"]),
    ("the new character's first upload is refused", S, "        session.revision = 0;\n        session.replaced = true;", "        session.replaced = true;",
     ["test_new_game_into_a_world_with_a_character_asks"]),
    ("the answer is never sent", C, 'ask.sent = mistrimulti_event_emit("profile_choice", { world: r.world_key, uid: r.uid, keep: ask.choice, gen: ask.gen }, 0);',
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
    # The choice between a player's characters in a world, and the Load Game list (MistriMultiCharPicker.gml).
    ("a sixth generation is kept", K, "    return 5;", "    return 6;", ["test_history_keeps_five_generations"]),
    ("a full history rotates out the newest generation", K, "slot = items[array_length(items) - 1].slot;", "slot = items[0].slot;",
     ["test_history_keeps_five_generations"]),
    ("the list is not newest first", K, "items[j].seq > items[j - 1].seq", "items[j].seq < items[j - 1].seq", ["test_history_keeps_five_generations"]),
    ("a character is stored again every time it is replaced", K, "if (slot < 0 && items[i].sig == sig) return true;", "",
     ["test_unfinished_new_character_is_not_listed_twice"]),
    ("the unfinished copy of the current character is offered", K, "            if (items[i].sig == sig) continue;\n", "",
     ["test_unfinished_new_character_is_not_listed_twice"]),
    ("a swap loses the former current character", K, "try { parked = mistrimulti_history_park(uid, core, progress, slot); } catch (e) {}", "parked = true;",
     ["test_pick_an_earlier_character_swaps"]),
    ("a swap that fails halfway leaves the other character's progress", K, "            mistrimulti_player_store(uid, core.revision, core.data);\n", "",
     ["test_pick_keeps_everything_when_writes_fail"]),
    ("a swap is repeated when its answer is sent again", S, "        if (!session.swapped) {", "        if (true) {", ["test_swap_is_not_repeated_when_the_answer_is_retried"]),
    ("a choice number beyond 2 starts over", S, "|| data.keep < 0 || data.keep > 2) return true;", "|| data.keep < 0) return true;", ["test_forged_generation_choices"]),
    ("Keep mine never lists the characters", K, "if (array_length(list) < 2 || !is_struct(ask)", "if (true || !is_struct(ask)", ["test_picker_lists_own_characters"]),
    ("the list has no New character", K, '    mcp.option(mistrimulti_menu_t("New character"), mistrimulti_character_chosen, [0, ask.epoch, 0]);\n', "",
     ["test_picker_lists_own_characters"]),
    ("the current character's row means an earlier one", K, "[list[i].id == 0 ? 1 : 2, ask.epoch, list[i].id]", "[2, ask.epoch, list[i].id]",
     ["test_pick_the_current_character"]),
    ("the chosen character number is not sent", C, "keep: ask.choice, gen: ask.gen }", "keep: ask.choice }", ["test_pick_an_earlier_character_swaps"]),
    ("a refused choice is not asked again", S, "            mistrimulti_charpicker_failed(r);\n", "", ["test_pick_keeps_everything_when_writes_fail"]),
    ("the character of 0.4.5 is not imported", K, "    if (!file_exists(core_path)) return;", "    return;", ["test_character_of_version_045_is_in_the_history"]),
    ("the imported files are not renamed", K, "    file_rename(core_path, core_path + \".imported\");\n", "", ["test_character_of_version_045_is_in_the_history"]),
    ("the host's Load Game list shows the guest's character", V, 'mistrimulti_savespace_mode() == "join") mistrimulti_charcache_apply', "mistrimulti_savespace_mode() != \"\") mistrimulti_charcache_apply",
     ["test_load_list_shows_the_guests_own_character"]),
    ("the world is mapped under the wrong number", K, "worlds[$ entry.game] = r.world_key;", 'worlds[$ "0"] = r.world_key;', ["test_load_list_shows_the_guests_own_character"]),
    ("a cached name of any length is shown", K, " || string_length(entry.name) > 64) return;", ") return;", ["test_load_list_never_breaks_a_save"]),
    ("the cache is rewritten at every checkpoint", K, '        if (r[$ "charcache_sig"] == signature) return;\n', "", ["test_character_cache_follows_the_character"]),
    ("the cache is not written after a restore", S, "        mistrimulti_charcache_remember();\n        return true;", "        return true;", ["test_character_cache_follows_the_character"]),
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
