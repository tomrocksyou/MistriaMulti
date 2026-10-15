"""Mutation check for MistriMultiGuestSave.gml: each mutation must make at least one guest-save test fail.

    python3 tests/mutate_guestsave.py

Breaks one rule of the GML at a time (a guest that may save, no final flush, no goodbye, a host that is never missed, ...), runs
the tests that should notice, and restores the files. Exit status 1 if a mutation goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
G = "MistriMultiGuestSave.gml"
B = "MistriMultiBoot.gml"

MUTATIONS = [
    ("a guest may save", G, '''        mistrimulti_guestsave_blocked();
        return true;''', '''        mistrimulti_guestsave_blocked();
        return false;''', ["test_guest_save_is_vetoed", "test_wiring"]),
    ("solo folder not protected", G, '''solo_path(path)) {
            mmapi_log_error''', '''solo_path(path) && false) {
            mmapi_log_error''', ["test_guest_save_is_vetoed", "test_wiring"]),
    ("save notice repeats", G, '''if (g.notified_at < 0 || now - g.notified_at >= MISTRIMULTI_GUESTSAVE_NOTICE_GAP) {''', '''if (true) {''',
     ["test_guest_save_is_vetoed"]),
    ("save attempt does not flush", G, '''        mistrimulti_guestsave_flush();
        var now = get_timer();''', '''        var now = get_timer();''', ["test_save_attempt_sends_character"]),
    ("flush not repeated after an in-flight upload", G, '''    g.flush_pending = r.player_revision != r.player_saved_revision || r.progress_revision != r.progress_saved_revision;''',
     '''    g.flush_pending = false;''', ["test_save_attempt_sends_character"]),
    ("any menu flushes", G, ''' || ctx[$ "kind"] != Menu.Settings) return;''', ''') return;''', ["test_final_flush_on_quit_and_return"]),
    ("settings menu does not flush", G, '''        __mistrimulti_guestsave().export_now = true;
        mistrimulti_guestsave_flush();''', '''        __mistrimulti_guestsave().export_now = true;''', ["test_final_flush_on_quit_and_return", "test_export_and_import"]),
    ("no goodbye frame", G, '''        save_text_file(r.bridge + "/tx.tmp", "0\\n" + json_stringify(frame));''', '''        var skipped = frame;''', ["test_goodbye_frame"]),
    ("goodbye still says the world", G, '''active: false, world: "" };
        save_text_file''', '''active: false, world: r.world_key };
        save_text_file''', ["test_goodbye_frame"]),
    ("host does not forget a departed guest", G, '''r.player_sessions[i] = undefined;''', '''r.player_sessions[i] = r.player_sessions[i];''',
     ["test_host_forgets_a_departed_guest"]),
    ("no retry after 'already connected'", G, '''    g.retries++;
    r.player_request = "";''', '''    g.retries++;''', ["test_returning_through_another_slot_retries"]),
    ("a missing host is never noticed", G, '''if (now - g.state_at >= grace) { mistrimulti_guestsave_leave(state); return; }''',
     '''if (false) { mistrimulti_guestsave_leave(state); return; }''', ["test_host_crash_returns_guest_to_title", "test_host_closes_or_restarts_the_world"]),
    ("lost grace far too short", G, '''#macro MISTRIMULTI_GUESTSAVE_GRACE_LOST 20000000''', '''#macro MISTRIMULTI_GUESTSAVE_GRACE_LOST 1000000''',
     ["test_host_crash_returns_guest_to_title", "test_short_outage_and_waiting_guest_stay"]),
    ("a guest that never saw the host is sent away", G, '''    if (g.host_epoch == "") return;   // the host''', '''    if (false) return;   // the host''',
     ["test_short_outage_and_waiting_guest_stay"]),
    ("the host's final frame is ignored", G, '''if (host.world == "") state = "closed";''', '''if (host.world == "") state = "ok";''',
     ["test_host_closes_or_restarts_the_world"]),
    ("a restarted host is not noticed", G, '''(host.epoch == g.host_epoch && host.world == g.host_world) ? "ok" : "restarted"''', '''"ok"''',
     ["test_host_closes_or_restarts_the_world"]),
    ("the message is shown twice", G, '''    if (g.leaving) return;
    g.leaving = true;''', '''    g.leaving = true;''', ["test_leave_is_safe"]),
    ("no fade back to the title", G, '''    try { SCREEN_FADER.fade_out(FADE_SPEED_TRANSITION, mistrimulti_guestsave_exit_now); }''',
     '''    try { var skipped = 1; }''', ["test_host_crash_returns_guest_to_title"]),
    ("session state survives the title screen", G, '''    r.guestsave = undefined;''', '''    var kept = 1;''', ["test_goodbye_frame"]),
    ("export of an unacknowledged state", G, '''    if (r.player_revision != r.player_saved_revision || r.progress_revision != r.progress_saved_revision) return undefined;
    var names''', '''    var names''', ["test_export_and_import"]),
    ("import keeps the old world key", G, '''    core.world = r.world_key;
''', '''''', ["test_export_and_import", "test_import_restores_the_whole_character"]),
    ("import trusts the file", G, '''    if (!mistrimulti_player_valid(core, r.uid, r.world_key) || !mistrimulti_progress_valid(progress, r.uid, r.world_key)) {''',
     '''    if (false) {''', ["test_export_and_import"]),
    ("import for any identity", G, ''' || file[$ "uid"] != r.uid) return "That export is not for this player.";''', ''') return "That export is not for this player.";''',
     ["test_export_and_import"]),
    ("import accepts folders", G, '''|| string_pos("/", name) > 0 || string_pos("\\\\", name) > 0 || string_pos("..", name) > 0''', '''''',
     ["test_export_and_import"]),
    ("save notice not reworded", G, "        return MISTRIMULTI_GUESTSAVE_TEXT;\n    } catch (e) {",
     "        return undefined;\n    } catch (e) {", ["test_guest_save_is_vetoed"]),
    ("host's save notice reworded too", G, "        if (!mistrimulti_guestsave_is_guest()) return undefined;\n        var g = __mistrimulti_guestsave();\n        g.notice_due",
     "        var g = __mistrimulti_guestsave();\n        g.notice_due", ["test_guest_save_is_vetoed"]),
    ("every text reworded", G, 'if (!is_string(ctx) || ctx != "misc_local/save_complete") return undefined;', "if (false) return undefined;",
     ["test_guest_save_is_vetoed"]),
    ("no fallback line when the game shows none", G, "    if (g.notice_due < 0 || get_timer() < g.notice_due) return;", "    return;",
     ["test_guest_save_is_vetoed"]),
    ("fallback line on top of the game's notice", G, "        g.notice_due = -1;\n        g.rewrites++;", "        g.rewrites++;",
     ["test_guest_save_is_vetoed"]),
    ("old untrue wording", G, '"Guests do not save: the host keeps your progress."', '"Your character is saved on the host\'s computer."',
     ["test_guest_save_is_vetoed"]),
    ("local.get not registered", G, '    mmapi_filter("local.get", mistrimulti_guestsave_local_get);\n', "", ["test_wiring"]),
    ("local.get missing from the manifest", "../manifest.toml", '"local.missing", "local.get", ', '"local.missing", ', ["test_wiring"]),
    ("boot: the save guard ignores guests", B, '''    if (mistrimulti_guestsave_blocks(ctx)) return false;''', '''    if (false) return false;''', ["test_wiring"]),
    ("boot: the tick is not called", B, '''    mistrimulti_guestsave_tick();
''', '''''', ["test_wiring"]),
    ("boot: the hooks are not registered", B, '''    mistrimulti_guestsave_register_hooks();
''', '''''', ["test_wiring"]),
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
        out = subprocess.run([sys.executable, "test_guestsave.py"] + tests, cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
        path.write_text(text)
        caught = out.returncode != 0
        print(("caught " if caught else "NOT CAUGHT ") + name, flush=True)
        bad += 0 if caught else 1
finally:
    for path, text in originals.items():
        path.write_text(text)
sys.exit(1 if bad else 0)
