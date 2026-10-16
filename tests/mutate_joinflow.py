"""Mutation check for the join flow: every way out of the Host / Join screens, and the world the guest gets (docs/SYNC-MENU.md).

    python3 tests/mutate_joinflow.py                 # the GML half (about 2 minutes)
    unshare -n python3 tests/mutate_joinflow.py --asm   # also the assembly half: rebuilds the Linux programs and runs the launcher tests
                                                        # in a private network namespace (lo must be up, as scripts/runall.sh does)

Breaks one rule at a time, runs the tests that should notice, and restores the files. Exit status 1 if a mutation goes unnoticed.
"""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GML = ROOT / "mod/mistrimulti/gml"
M, V, G, P = "MistriMultiMenu.gml", "MistriMultiSaveSpace.gml", "MistriMultiGuestSave.gml", "MistriMultiPlayerSync.gml"
WALK = ["test_every_cancel_path_resets_and_can_restart"]
HEAL = ["test_stuck_flags_heal_themselves"]
CHECK = ["test_world_check_before_entering"]

MENU_MUTATIONS = [
    ("Escape / click outside a popup is not a Cancel", M, 'if (f.stage != "input" && f.popup != undefined && f.popup[$ "close_requested"] == true) {', "if (false) {", WALK + HEAL + ["test_mutation_probe_cancel"],
     (V, "    if (s.choosing) mistrimulti_savespace_choosing_live();\n", "")),
    ("reset leaves the choosing flag set", M, "    m.flow = undefined;\n    __mistrimulti_savespace().choosing = false;\n    if (f != undefined) {", "    m.flow = undefined;\n    if (f != undefined) {", WALK,
     (V, "    s.choosing = false;\n    s.choose_popup = undefined;\n    try { mistrimulti_menu_reset(true); }", "    try { mistrimulti_menu_reset(true); }")),
    ("a cancel never stops the session", M, "    if (f != undefined && f.stage != \"choose\" && f.stage != \"host\" && f.stage != \"list\" && f.stage != \"input\") return true;", "    if (false) return true;", WALK),
    ("a cancel ignores a running session the stage does not show", M, "    return st.session != \"none\" || st.state == \"hosting\" || st.state == \"joining\" || st.state == \"downloading\" || st.state == \"ready\";", "    return false;", HEAL),
    ("a flow with nothing on screen is never reset", M, "if (f.idle > 180) {", "if (f.idle > 180000000) {", HEAL),
    ("beginning again leaves the old flow open", M, "    if (m.flow != undefined) mistrimulti_menu_reset(true);      // a flow that was left behind", "    // a flow that was left behind", HEAL),
    ("a dead flow counts as alive", M, "    if (f.popup != undefined && f.popup[$ \"close_requested\"] != true) return true;\n    if (f.input", "    if (f.popup != undefined) return true;\n    if (f.input", HEAL),
    ("the guest enters whatever world arrived", M, "if (st.hw != 0 && st.dw != 0 && st.hw != st.dw) {", "if (false) {", CHECK),
    ("a mismatch is not retryable", M, "if ((f.err == 48 || f.err == 49) && f.role == \"join\" && mistrimulti_menu_valid_ip(f.ip))", "if (false)", CHECK),
    ("unsaved world words changed", M, "has not saved it yet. Ask them to sleep or save once, then press Join again.", "has not saved it.", CHECK),
    ("the host list does not mark an unsaved world", M, "if ((h.flags & 4) != 0 && (h.flags & 8) == 0) text +=", "if (false) text +=", CHECK),
    ("a host never tells its launcher the world", M, "    if (m.published != key && get_timer() >= m.publish_at) {", "    if (false) {", ["test_host_publishes_its_world"]),
    ("the world note is rewritten every frame", M, "            m.published = key;\n", "", ["test_host_publishes_its_world"]),
    ("the note carries the wrong id", M, "\"id=\" + key + \"\\n\"", "\"id=\" + string(floor(id) + 1) + \"\\n\"", ["test_host_publishes_its_world"]),
    ("a guest cannot see another world", M, "    if (string(Game.unique_identifier) != theirs) {", "    if (false) {", ["test_guest_notices_another_world"]),
    ("a new world is not saved early", M, "    if (__mistrimulti_savespace()[$ \"new_world\"] != true || m.save_tried) return;", "    return;", ["test_new_world_is_saved_early"]),
    ("a continued world is saved too", M, "    if (__mistrimulti_savespace()[$ \"new_world\"] != true || m.save_tried) return;", "    if (m.save_tried) return;", ["test_new_world_is_saved_early"]),
    ("the early save ignores a running scene", M, " || MIST.is_running() ||", " ||", ["test_new_world_is_saved_early"]),
    ("the early save runs away from home", M, " || !is_home_location(CURRENT_LOCATION_ID)) {", ") {", ["test_new_world_is_saved_early"]),
    ("the early save repeats", M, "    m.save_tried = true;\n    mistrimulti_menu_log(\"saving", "    mistrimulti_menu_log(\"saving", ["test_new_world_is_saved_early"]),
    ("a failed early save leaves the screen black", M, "        done = true;\n    } catch (e) {\n        mmapi_log_error(\"mistrimulti\", \"Saving the new world failed: \" + string(e));\n    }", "        done = true;\n    } catch (e) {\n        throw e;\n    }", ["test_new_world_is_saved_early"]),
    ("the host is not told", M, "\"MistriaMulti: your new world is saved. Friends can join now.\"", "\"Saved.\"", ["test_new_world_is_saved_early"]),
    ("the early save does not wait for the world note", M, "    if (m.published == key) mistrimulti_menu_early_save(r, m);", "    mistrimulti_menu_early_save(r, m);", ["test_new_world_is_saved_early"]),
    ("a stale flag survives the title screen", V, "    s.choosing = false;\n    s.choose_popup = undefined;\n    s.new_world = false;", "    s.new_world = false;", ["test_title_entered_forgets_the_world_state"]),
    ("a new world is not marked for the early save", V, "    s.new_world = true;   // the host starts", "    // the host starts", ["test_only_a_new_world_is_marked"]),
    ("a continued world is marked as new", V, "    if (continue_world && world != undefined) s.orig_enter_game(LoadState.Load(world));",
     "    if (continue_world && world != undefined) { s.new_world = true; s.orig_enter_game(LoadState.Load(world)); }", ["test_only_a_new_world_is_marked"]),
    ("choosing is trusted without a live popup", V, "    if (p != undefined && p[$ \"close_requested\"] != true) return true;\n    if (p == undefined && mistrimulti_menu_flow_alive()) return true;", "    return true;", HEAL + WALK),
]

GUEST_MUTATIONS = [
    ("the guest stays in the wrong world", G, 'if (state != "closed" && r[$ "world_mismatch"] == true) state = "wrongworld";', "", "test_guestsave.py", ["test_wrong_world_is_left"]),
    ("the guest hands its character to the wrong world", P, '        if (r[$ "world_mismatch"] == true) { r.player_ready = false; r.player_error = "The host plays another world."; return; }', "", "test_guestsave.py", ["test_wrong_world_gets_no_character"]),
    ("wrong-world words missing", G, 'case "mistrimulti/guest_wrong_body": return "The host is playing a different world', 'case "mistrimulti/guest_wrong_body_x": return "The host is playing a different world', "test_guestsave.py", ["test_wrong_world_is_left"]),
]

# (file, old, new, tests) for the assembly half; only run with --asm. NASM sources of the Linux programs (the Windows twins are the same text).
ASM_MUTATIONS = [
    ("the server ignores the host's world note", "linux/launcher.asm", "    cmp dword [wh_id], 0\n    je .anyworld\n    mov rcx, r13\n    call wf_name_id\n    cmp eax, [wh_id]                    ; the mod named the world being played: only that world's saves count\n    jne .each\n.anyworld:", "", "test_world_info"),
    ("an unsaved world gets someone else's save", "linux/launcher.asm", "    cmp dword [wh_id], 0\n    je .sendhdr\n    mov byte [wf_hdr+5], 4", "    jmp .sendhdr\n    mov byte [wf_hdr+5], 4", "test_world_info"),
    ("the world info is added after signing", "linux/launcher.asm", "    call wh_fill_hdr\n    call wa_sign_header\n    lea rcx, [wf_hdr]\n    mov edx, 144\n    call wf_send_all\n    test eax, eax\n    jz .free", "    call wa_sign_header\n    call wh_fill_hdr\n    lea rcx, [wf_hdr]\n    mov edx, 144\n    call wf_send_all\n    test eax, eax\n    jz .free", "test_world_info"),
    ("the discovery answer says nothing about the world", "linux/launcher.asm", "    call wh_disc_flags\n    mov rcx, [disc_sock]", "    mov rcx, [disc_sock]", "test_world_info"),
    ("a stop leaves the world note behind", "linux/menu.inc", "FN sess_stop\n    call wh_forget\n", "FN sess_stop\n", "test_menu_world_note_and_join"),
    ("the guest does not report the world info", "linux/menu.inc", "    mov eax, [wf_host_id]               ; which world", "    xor eax, eax                        ; which world", "test_menu_world_note_and_join"),
    ("the guest client ignores status 4", "linux/net.inc", "    cmp eax, 4\n    je .unsaved\n", "", "test_menu_world_note_and_join"),
    ("a note id of zero filter accepts any digits", "common/textutil.inc", "    cmp rax, 0x7fffffff\n    ja .no\n    inc ecx\n    cmp ecx, 12\n    jb .l\n.e: test ecx, ecx", "    inc ecx\n    cmp ecx, 12\n    jb .l\n.e: test ecx, ecx", "test_world_info"),
]


def run(cmd, env=None, cwd=None):
    return subprocess.run(cmd, cwd=cwd or ROOT / "tests", capture_output=True, text=True, timeout=1800, env=env)


originals = {}
bad = 0


def mutate(path, old, new):
    originals.setdefault(path, path.read_text())
    text = originals[path]
    if old not in text:
        return False
    path.write_text(text.replace(old, new, 1))
    return True


def restore(path):
    path.write_text(originals[path])


try:
    for name, which, old, new, tests, *more in MENU_MUTATIONS:
        path = GML / which
        if not mutate(path, old, new) or any(not mutate(GML / w2, o2, n2) for w2, o2, n2 in more):
            print("MISSING PATTERN:", name)
            bad += 1
            continue
        out = run([sys.executable, "test_menu.py"], env=dict(os.environ, ONLY=",".join(tests)))
        restore(path)
        for w2, _, _ in more:
            restore(GML / w2)
        print(("caught " if out.returncode != 0 else "NOT CAUGHT ") + name, flush=True)
        bad += 0 if out.returncode != 0 else 1
    for name, which, old, new, script, tests in GUEST_MUTATIONS:
        path = GML / which
        if not mutate(path, old, new):
            print("MISSING PATTERN:", name)
            bad += 1
            continue
        out = run([sys.executable, script] + tests)
        restore(path)
        print(("caught " if out.returncode != 0 else "NOT CAUGHT ") + name, flush=True)
        bad += 0 if out.returncode != 0 else 1
    if "--asm" in sys.argv:
        for name, which, old, new, test in ASM_MUTATIONS:
            path = ROOT / which
            if not mutate(path, old, new):
                print("MISSING PATTERN:", name)
                bad += 1
                continue
            build = subprocess.run(["sh", "scripts/build-linux.sh"], cwd=ROOT, capture_output=True, text=True)
            if build.returncode != 0:
                restore(path)
                print("BUILD FAILED:", name, build.stderr[-300:])
                bad += 1
                continue
            args = [sys.executable, "-I", "test_launcher_linux.py"] + [str(ROOT / "build" / n) for n in
                    ("mistrimulti-launcher", "mistrimulti-helper-linux", "fakegame-linux", "mistrimulti-manager")]
            out = run(args, env=dict(os.environ, ONLY=test))
            restore(path)
            print(("caught " if out.returncode != 0 else "NOT CAUGHT ") + name, flush=True)
            bad += 0 if out.returncode != 0 else 1
finally:
    for path, text in originals.items():
        path.write_text(text)
    if "--asm" in sys.argv:
        subprocess.run(["sh", "scripts/build-linux.sh"], cwd=ROOT, capture_output=True)
sys.exit(1 if bad else 0)
