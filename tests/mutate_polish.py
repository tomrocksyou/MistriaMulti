"""Mutation check for the badge and the short popup labels (MistriMultiStatus.gml, MistriMultiHudText.gml, MistriMultiSaveSpace.gml).

    python3 tests/mutate_polish.py

Breaks one rule at a time (a badge that trusts a stale control.json in a world, a badge behind the toolbar, on top of the title
screen's copyright line, long popup labels, ...), runs the tests that should notice, and restores the files. Exit status 1 if a
mutation goes unnoticed. The guest-save half of this area is in tests/mutate_guestsave.py.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
S, H, V = "MistriMultiStatus.gml", "MistriMultiHudText.gml", "MistriMultiSaveSpace.gml"
T = ["test_badge", "test_badge_in_world", "test_badge_on_screen_is_robust", "test_texts_and_keys"]

MUTATIONS = [
    ("world ignores the runtime's heartbeat", S, "    var w = __mistrimulti_world_link();", "    var w = undefined;", ["test_badge_in_world"]),
    ("world Online without a fresh heartbeat", S, "if (w.fresh && (w.mode == \"host\"", "if ((w.mode == \"host\"", ["test_badge_in_world"]),
    ("guest Online without seeing the host", S, " || (w.mask & 1) != 0)) return", " || true)) return", ["test_badge_in_world"]),
    ("stale heartbeat still Online", S, "get_timer() - seen < 3000000;", "get_timer() - seen < 3000000000;", ["test_badge_in_world"]),
    ("world says helper not running again", S, "text: \"Multiplayer: Offline - connection lost\"", "text: \"Multiplayer: Offline - helper not running\"",
     ["test_badge_in_world"]),
    ("joined shown as hosting", S, "var tag = mode == \"host\" ? \" (hosting)\" : (mode == \"join\" ? \" (joined)\" : \"\");",
     "var tag = \" (hosting)\";", ["test_badge_in_world"]),
    ("a just-started session is an error", S, "get_timer() - n.armed_at < 10000000", "false", ["test_badge"]),
    ("text changes are not logged with a reason", S, "\" (\" + status.why + \") [\"", "\" [\"", ["test_badge_in_world"]),
    ("badge behind the toolbar (HUD layer)", S, "\"popup\", \"right\", \"bottom\", -6,", "\"hud\", \"right\", \"bottom\", -6,", T),
    ("badge on the copyright line", S, "title ? -16 : -4", "-4", ["test_badge_in_world"]),
    ("badge never moves once built", H, "if (visible && (slot.x != x || slot.y != y)) {", "if (false) {", ["test_badge_in_world"]),
    ("long popup label (continue)", V, 'return "Continue world";', 'return "Continue your world";', ["test_texts_and_keys"]),
    ("long popup label (new)", V, 'return "New world";', 'return "Start a new world";', ["test_texts_and_keys"]),
    ("long popup label (hearts)", V, 'return "Own (Recommended)";', "return \"Each player's own (Recommended)\";", ["test_texts_and_keys"]),
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
        out = subprocess.run([sys.executable, "test_menu.py"] + tests, cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
        path.write_text(text)
        caught = out.returncode != 0
        print(("caught " if caught else "NOT CAUGHT ") + name, flush=True)
        bad += 0 if caught else 1
finally:
    for path, text in originals.items():
        path.write_text(text)
sys.exit(1 if bad else 0)
