"""Mutation check for the title-screen version label and Update button (MistriMultiUpdateUI.gml and its three small edits).

    python3 tests/mutate_updateui.py

Breaks one rule at a time (a comparison turned round, a button for every release, a click during a run, unclean messages, nodes
on the wrong parent, a label outside the title screen, the wiring left out, ...), runs tests/test_updateui.py and restores the
files. Exit status 1 if a mutation goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GML = ROOT / "mod/mistrimulti/gml"
U, S, B, M = "MistriMultiUpdateUI.gml", "MistriMultiStatus.gml", "MistriMultiBoot.gml", "MistriMultiMenu.gml"

MUTATIONS = [
    ("newer version compared the wrong way", U, "if (pa[i] > pb[i]) return true;", "if (pa[i] < pb[i]) return true;"),
    ("any text accepted as the release version", U, 'if (mistrimulti_version_valid(latest)) u.latest = latest;',
     'if (is_string(latest)) u.latest = latest;'),
    ("button for every state", U, 'base.button = mistrimulti_update_available() != "";', "base.button = true;"),
    ("a second click while the first is unanswered", U, "if (u.pending || m.status == undefined || !m.alive) return;", "if (m.status == undefined) return;"),
    ("a click during a run", U, "if (!is_struct(up) || mistrimulti_update_active(up) || mistrimulti_update_available() == \"\") return;",
     "if (!is_struct(up)) return;"),
    ("an old result taken for the new run", U, "u.base_run = up.run;", "u.base_run = 0;"),
    ("the end text is not plain words", U, 'text: "Installed. Restart the game"', 'text: "done"'),
    ("messages are not cleaned", U, "if (c < 32 || c > 126) return \"\";", "if (c < 0) return \"\";"),
    ("label not next to the game's text", U, "u.label = ANCHOR.text(parent)", "u.label = ANCHOR.text(ANCHOR.screen_canvas)"),
    ("label shown outside the title screen", U, "if (!on_title) { mistrimulti_updateui_hide(u); return; }", "if (false) { return; }"),
    ("the fallback never waits for the game's text", U, "if (u.title_since < 300) return;", "if (u.title_since < 0) return;"),
    ("the button never switches off", U, "if (u.button_on != view.button) { u.button.set_enabled(view.button); u.button_on = view.button; }",
     "if (u.button_on != view.button) { u.button_on = view.button; }"),
    ("the mod's own version is stale", U, 'function mistrimulti_mod_version() { return "0.4.6"; }', 'function mistrimulti_mod_version() { return "0.4.5"; }'),
    ("the in-world badge says nothing", S, "title ? status.text : status.text + mistrimulti_update_note()", "status.text"),
    ("the tick is not wired", B, "mistrimulti_updateui_tick(); ", ""),
    ("the status cleaner drops the update fields", M, "upd: mistrimulti_update_fields(raw),", "upd: undefined,"),
]

originals = {}
bad = 0
try:
    for name, which, old, new in MUTATIONS:
        path = GML / which
        originals.setdefault(path, path.read_text())
        text = originals[path]
        if old not in text:
            print("MISSING PATTERN:", name)
            bad += 1
            continue
        path.write_text(text.replace(old, new, 1))
        out = subprocess.run([sys.executable, "test_updateui.py"], cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
        path.write_text(text)
        caught = out.returncode != 0
        print(("caught " if caught else "NOT CAUGHT ") + name, flush=True)
        bad += 0 if caught else 1
finally:
    for path, text in originals.items():
        path.write_text(text)
sys.exit(1 if bad else 0)
