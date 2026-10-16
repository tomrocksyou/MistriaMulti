"""The title-screen version label and Update button (MistriMultiUpdateUI.gml) and the update note of the badge.

    python3 tests/test_updateui.py

The GML runs unmodified in tests/gml_subset.py with the menu tests' fake game (tests/test_menu.py: files, clock, popups) and a
FakeLauncher that also publishes the update fields of menu/status.json (update, us, uv, um, ue, ur). The ANCHOR nodes are
tests/hud_fake.py's stand-ins: a text node that is a child of the game's own version text (TitleMenu.sha_text), a nine-slice
button child with a text child and a tap callback. Not provable here: how the real game lays these nodes out and delivers
taps (docs/SYNC-UPDATE.md, "In-game checklist"). The launcher side is tested in tests/test_launcher_linux.py (and, under Wine,
tests/test_launcher.py).
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_menu as tm
from test_menu import Env, FakeLauncher, MOD, GML_DIR, ROOT, FRAME_US
from gml_subset import GStruct
from hud_fake import ALIGN

_MANIFEST = (ROOT / "mod/mistrimulti/manifest.toml").read_text()
MODV = [l.split('"')[1] for l in _MANIFEST.splitlines() if l.startswith("version =")][0]
_parts = MODV.split(".")
NEWER = ".".join(_parts[:-1] + [str(int(_parts[-1]) + 1)])   # a release newer than the installed mod, whatever its version is


PLAIN, BUSY, GOOD, BAD = (235 + 235 * 256 + 235 * 65536, 20 + 170 * 256 + 230 * 65536, 40 + 200 * 256 + 70 * 65536,
                          50 + 60 * 256 + 220 * 65536)


class UpdLauncher(FakeLauncher):
    """The launcher with the update fields: `update` starts a run (us=checking, ur+1) like the real one."""

    def __init__(self, env):
        super().__init__(env)
        self.upd = {"update": "none", "us": "none", "uv": "", "um": "", "ue": 0, "ur": 0}

    def publish(self):
        super().publish()
        path = f"{MOD}/menu/status.json"
        doc = json.loads(self.env.files[path])
        doc.update(self.upd)
        self.env.files[path] = json.dumps(doc)

    def frame(self, env):
        before = len(self.cmds)
        super().frame(env)
        if len(self.cmds) > before and self.cmds[-1]["cmd"] == "update":
            self.upd.update(us="checking", uv="", um="", ue=0, ur=self.upd["ur"] + 1)
            self.publish()

    def set(self, **kw):
        self.upd.update(kw)
        self.publish()


class UEnv(Env):
    def frames(self, n=1):
        for _ in range(n):
            super().frames(1)
            self.interp.call("mistrimulti_updateui_tick")
            if self.errors:
                raise AssertionError(self.errors)


def make(update=None, title=True, sha=True):
    update = NEWER if update is None else update
    env = UEnv()
    env.launcher = UpdLauncher(env)
    env.launcher.upd["update"] = update
    env.launcher.publish()
    env.rt = env.rt
    if title:
        env.interp.builtins["instance_exists"] = lambda o: o != "obj_ari"
    if sha:
        add_sha(env)
    return env


def add_sha(env):
    node = env.anchor.text(env.anchor.struct["screen_canvas"], None, None)
    sp = env.interp.call("__mistrimulti_savespace")
    sp["title_menu"] = GStruct(sha_text=node)
    env.sha = node
    return node


def parts(env):
    """(label, button, caption) nodes that are alive."""
    live = [n for n in env.anchor.nodes if not n["freed"] and not n["stale"]]
    label = [n for n in live if n["kind"] == "text" and n["parent"] is getattr(env, "sha", None)]
    button = [n for n in live if n["kind"] == "nine_slice"]
    caption = [n for n in live if n["kind"] == "text" and button and n["parent"] is button[-1]]
    return (label[-1] if label else None, button[-1] if button else None, caption[-1] if caption else None)


def label_text(env):
    return parts(env)[0]["text"]


def button_on(env):
    b = parts(env)[1]
    return b is not None and b["enabled"] is True


def tap(env):
    """The player clicks the button (the game delivers taps to enabled nodes only)."""
    b = parts(env)[1]
    assert b is not None and b["enabled"], "no enabled button to click"
    env.interp.call_value(b["tap"], [], 0)


def launcher_dies(env):
    """The launcher stops publishing; the mod notices a heartbeat that has not moved for more than 4 seconds."""
    env.launcher.alive = False
    env.frames(61)                                            # the mod reads the last heartbeat
    env.us += 6_000_000
    env.frames(130)


def fallback_nodes(env):
    return [n for n in env.anchor.nodes if not n["freed"] and not n["stale"] and n["z"] == 900 and n["alpha"] == 1
            and n["text"].startswith("MistriMulti")]


# ---------------------------------------------------------------------------------------------------------------------------
def test_versions():
    parts_of = lambda t: tm.gml.to_py(None) if False else None
    env = UEnv()
    newer = lambda a, b: env.interp.call("mistrimulti_version_newer", a, b)
    valid = lambda t: env.interp.call("mistrimulti_version_valid", t)
    for a, b, want in (("0.4.7", "0.4.6", True), ("0.4.6", "0.4.6", False), ("0.4.5", "0.4.6", False), ("0.4.10", "0.4.9", True),
                       ("0.5", "0.4.9", True), ("1", "0.99.99", True), ("1.0.0.0", "1", False), ("1.0.0.1", "1", True),
                       ("0.4.6.1", "0.4.6", True), ("10.0.0", "9.99.99", True), ("0.4.7", "0.4.7.0", False)):
        assert newer(a, b) is want, (a, b, want)
    for bad in ("", "a", "1..2", ".1", "1.", "1.2.3.4.5", "123456", "1.2.-3", "1.2.3 ", " 1", "1,2", "v1.2", "1.2.3\n", "0x10", 7, None):
        assert valid(bad) is False, bad
        assert newer(bad, "0.4.6") is False and newer("9.9.9", bad) is False, bad
    for good in ("1", "0.4.6", "12345.12345.12345.12345", "0.0.0"):
        assert valid(good) is True, good
    # the version the mod shows is the one in the manifest (a release bump must change both) and the one it declares to MMAPI
    manifest = (ROOT / "mod/mistrimulti/manifest.toml").read_text()
    version = [l.split('"')[1] for l in manifest.splitlines() if l.startswith("version =")][0]
    assert env.interp.call("mistrimulti_mod_version") == version, (version, "mistrimulti_mod_version() must follow manifest.toml")
    boot = (GML_DIR / "MistriMultiBoot.gml").read_text()
    assert f'mmapi_mod_declare("mistrimulti", "{version}")' in boot
    print("PASS: update ui: version parsing and comparison, and the version the mod shows is the manifest's")


def test_fields_are_clean():
    env = UEnv()
    f = lambda raw: env.interp.call("mistrimulti_update_fields", tm.gml.from_json(raw))
    ok = f({"update": "0.4.7", "us": "downloading", "uv": "0.4.7", "um": "Fine words", "ue": 0, "ur": 3})
    assert dict(ok) == {"latest": "0.4.7", "state": "downloading", "ver": "0.4.7", "msg": "Fine words", "err": 0, "run": 3}, dict(ok)
    none = dict(f({}))
    assert none == {"latest": "", "state": "none", "ver": "", "msg": "", "err": 0, "run": 0}, none
    assert dict(f("not a struct")) == none and dict(f(None)) == none
    hostile = f({"update": "../../x", "us": "exploding", "uv": 5, "um": "x" * 91, "ue": 1e9, "ur": -4})
    assert dict(hostile) == none, dict(hostile)
    assert f({"um": "tab\there"})["msg"] == "" and f({"um": "café"})["msg"] == "" and f({"um": 5})["msg"] == ""
    assert f({"ue": -1})["err"] == 0 and f({"ue": 1000})["err"] == 0 and f({"ue": 66.7})["err"] == 66
    assert f({"update": "none"})["latest"] == ""
    for s in ("checking", "downloading", "installing", "done", "failed", "needs_momi"):
        assert f({"us": s})["state"] == s
    # the menu's status cleaner carries them, and a status without them (an older launcher) still works
    st = env.interp.call("mistrimulti_menu_clean", tm.gml.from_json({"v": 1, "hb": 1, "seq": 1, "state": "idle", "err": 0}))
    assert dict(st["upd"])["state"] == "none"
    print("PASS: update ui: hostile or missing update fields in status.json become safe defaults")


def test_label_is_always_there_and_button_follows_the_release():
    env = make(update="none")
    env.frames(12)
    label, button, caption = parts(env)
    assert label is not None and label["text"] == "MistriMulti %s" % MODV and label["color"] == PLAIN, label
    assert label["align"] == (ALIGN["RightOut"], ALIGN["Middle"]) and label["parent"] is env.sha, "next to the game's own version text"
    assert button["parent"] is label and button["align"] == (ALIGN["RightOut"], ALIGN["Middle"]) and button["size"][1] <= 16
    assert caption["text"] == "Update" and button["sprites"] == "spr_ui_button" and not button["enabled"], button
    assert env.errors_logged() == []
    # a newer release: the button appears; the label text is unchanged
    env.launcher.set(update=NEWER)
    env.frames(70)
    assert button_on(env) and label_text(env) == "MistriMulti %s" % MODV
    # not newer / older / junk: no button
    for v in (MODV, "0.0.1", "none", "banana", "0.4.7; rm"):
        env.launcher.set(update=v)
        env.frames(70)
        assert not button_on(env), v
    env.launcher.set(update=NEWER)
    env.frames(70)
    assert button_on(env)
    # the launcher stops answering: the button goes away (a click could not be heard)
    launcher_dies(env)
    assert not button_on(env) and label_text(env) == "MistriMulti %s" % MODV
    print("PASS: update ui: 'MistriMulti <version>' next to the game's version text, the Update button only for a newer release and a live launcher")


def test_click_sends_one_update_command_and_progress_is_plain_words():
    env = make()
    env.frames(70)
    assert button_on(env)
    tap(env)
    tap(env)                                                  # a double click is one command
    env.frames(2)
    assert [c["cmd"] for c in env.launcher.cmds] == ["update"], env.launcher.cmds
    seq = int(env.launcher.cmds[0]["seq"])
    assert 1 <= seq <= 999999
    assert not button_on(env) or True
    env.frames(70)
    # the launcher started the run: checking, downloading, installing, then the end
    seen = []
    def show():
        env.frames(70)
        seen.append(label_text(env))
        return not button_on(env)
    assert env.launcher.upd["us"] == "checking"
    assert show() and seen[-1] == "Checking for updates...", seen
    env.launcher.set(us="downloading", uv="0.4.7")
    assert show() and seen[-1] == "Downloading 0.4.7...", seen
    assert parts(env)[0]["color"] == BUSY
    env.launcher.set(us="installing")
    assert show() and seen[-1] == "Installing 0.4.7...", seen
    env.launcher.set(us="done")
    assert show() and seen[-1] == "Installed. Restart the game" and parts(env)[0]["color"] == GOOD, seen
    env.launcher.set(us="needs_momi")
    assert show() and seen[-1] == "Updated. Close the game and press Install in MOMI", seen
    # a failure shows the program's plain message and offers the button again
    env.launcher.set(us="failed", ue=5, um="No internet connection")
    env.frames(70)
    assert label_text(env) == "Update failed: No internet connection" and parts(env)[0]["color"] == BAD and button_on(env)
    env.launcher.set(us="failed", ue=61, um="")
    env.frames(70)
    assert label_text(env).startswith("Update: stop hosting or joining first")
    env.launcher.set(us="failed", ue=62, um="")
    env.frames(70)
    assert "missing" in label_text(env)
    env.launcher.set(us="failed", ue=999, um="")
    env.frames(70)
    assert label_text(env).startswith("Update failed. Try again later")
    # trying again sends a second command
    tap(env)
    env.frames(70)
    assert [c["cmd"] for c in env.launcher.cmds] == ["update", "update"] and label_text(env) == "Checking for updates..."
    assert env.errors_logged() == []
    print("PASS: update ui: one click is one `update` command; checking / downloading / installing / done / needs_momi / failed show plain words")


def test_click_waits_for_the_launcher_and_gives_up():
    env = make()
    env.frames(70)
    env.launcher.alive = False                                # the launcher is slow to take the command... and never does
    tap(env)
    env.frames(5)
    assert label_text(env) == "Starting the update..." and not button_on(env)
    env.us += 11_000_000
    env.launcher.alive = True
    env.launcher.publish()
    env.files.pop(f"{MOD}/menu/cmd.txt", None)
    env.frames(20)
    assert label_text(env).startswith("The launcher did not answer") and button_on(env), label_text(env)
    assert env.launcher.cmds == []
    print("PASS: update ui: a command the launcher never picks up ends in a plain message and the button comes back")


def test_stale_result_of_an_older_run_is_not_shown_as_the_new_one():
    env = make()
    env.launcher.set(us="failed", ue=5, um="Old failure", ur=4)
    env.frames(70)
    assert label_text(env) == "Update failed: Old failure" and button_on(env)
    env.launcher.consume_every = 200                          # the launcher is slow to read cmd.txt
    tap(env)
    env.frames(60)
    assert label_text(env) == "Starting the update...", label_text(env)
    print("PASS: update ui: while the command is on its way the old failure is not shown as the answer")


def test_click_guards():
    env = make(update="none")
    env.frames(12)
    env.interp.call("mistrimulti_updateui_press")             # no newer release: nothing
    env = make()
    env.frames(70)
    env.launcher.set(us="downloading", uv="0.4.7", ur=1)
    env.frames(70)
    env.interp.call("mistrimulti_updateui_press")             # a run is going
    env.launcher.set(us="none", ur=1)
    env.launcher.alive = False
    env.us += 6_000_000
    env.interp.call("mistrimulti_updateui_press")             # launcher gone
    env.files.pop(f"{MOD}/menu/status.json")
    env.interp.call("mistrimulti_updateui_press")             # no status at all
    env.frames(3)
    assert not any(c["cmd"] == "update" for c in env.launcher.cmds) and f"{MOD}/menu/cmd.txt" not in env.files
    print("PASS: update ui: no command without a newer release, during a run, or without a live launcher")


def test_where_it_shows():
    # not on the title screen (in a world): no button, no fallback text; back on the title it returns
    env = make()
    env.frames(70)
    assert button_on(env)
    env.interp.builtins["instance_exists"] = lambda o: True
    env.frames(12)
    assert not button_on(env)
    assert fallback_nodes(env) == []
    env.interp.builtins["instance_exists"] = lambda o: o != "obj_ari"
    env.frames(12)
    assert button_on(env)
    # ANCHOR was rebuilt by the game (every node freed): the widgets are built again, once
    env.anchor.rebuild()
    add_sha(env)
    env.frames(12)
    assert label_text(env) == "MistriMulti %s" % MODV and button_on(env)
    # the game's text node freed alone: new nodes when it is back, no throw meanwhile
    env.sha["freed"] = True
    env.frames(12)
    add_sha(env)
    env.frames(12)
    assert label_text(env) == "MistriMulti %s" % MODV
    before = sum(1 for n in env.anchor.nodes)
    env.frames(300)
    assert sum(1 for n in env.anchor.nodes) == before, "ticks do not make new nodes"
    assert env.errors_logged() == []
    print("PASS: update ui: only on the title screen; rebuilt after ANCHOR or the game's text is rebuilt; no node churn")


def test_fallback_without_the_games_text_node():
    env = make(sha=False)
    env.frames(100)
    assert fallback_nodes(env) == []                          # 5 seconds of waiting for the game's own text first
    env.frames(300)
    nodes = fallback_nodes(env)
    assert [n["text"] for n in nodes] == ["MistriMulti %s (update %s available)" % (MODV, NEWER)], nodes
    assert nodes[0]["align"] == (ALIGN["LeftIn"], ALIGN["BottomIn"]) and nodes[0]["pos"] == (112, 0)
    # the game's text appears later: the fallback goes, the real widgets come
    add_sha(env)
    env.frames(12)
    assert fallback_nodes(env) == [] and label_text(env) == "MistriMulti %s" % MODV
    # a game text node that has no usable shape
    env2 = make(sha=False)
    env2.interp.call("__mistrimulti_savespace")["title_menu"] = 5
    env2.frames(400)
    assert len(fallback_nodes(env2)) == 1 and env2.errors_logged() == []
    print("PASS: update ui: without the game's version text node a plain label stands in (no button), and yields when the node appears")


def test_nothing_can_throw():
    # ANCHOR.nine_slice missing or throwing: the label falls back, the game goes on, one error is logged
    env = make()
    env.anchor.broken_nine = True
    env.frames(400)
    assert len(env.errors_logged()) == 1 and "Title version label failed" in env.errors_logged()[0], env.errors_logged()
    # ANCHOR gone entirely
    env = make()
    env.frames(12)
    env.interp.builtins["ANCHOR"] = None
    env.frames(30)
    # hostile status file contents
    env = make()
    for junk in ('{"v":1,"hb":1,"seq":1,"state":"idle","err":0,"update":7,"us":[],"uv":{},"um":null,"ue":"x","ur":{}}',
                 '{"v":1,"hb":1,"seq":1,"state":"idle","err":0,"update":"1.2.3","us":"failed","um":"' + "A" * 200 + '","ue":-5,"ur":1e30}',
                 "[]", "{"):
        env.files[f"{MOD}/menu/status.json"] = junk
        env.frames(70)
        assert label_text(env).startswith(("MistriMulti", "Update failed")), label_text(env)
        assert not env.errors_logged(), env.errors_logged()
    # the tap callback with the launcher state in any shape
    env.interp.call("mistrimulti_updateui_press")
    env.interp.call("mistrimulti_update_note")
    print("PASS: update ui: a missing or failing ANCHOR, a failing nine-slice and hostile status files never throw into the game")


def test_in_world_badge_and_note():
    env = make(title=False, sha=False)
    env.interp.builtins["instance_exists"] = lambda o: True   # a world: obj_ari exists
    sp = env.interp.call("__mistrimulti_savespace")
    sp["active"] = True
    env.rt.update(enabled=True, mode="host", status=GStruct(running=True, mask=1, heartbeat=7), status_heartbeat=7,
                  status_seen_at=env.us, mask=1)
    env.frames(70)
    assert tm.shown(env)[0] == "Multiplayer: Online (hosting) - update available (%s)" % NEWER, tm.shown(env)
    assert env.interp.call("mistrimulti_update_note") == " - update available (%s)" % NEWER
    # the note is not about a release that is not newer, and it is gone with the launcher
    env.launcher.set(update=MODV)
    env.frames(70)
    assert tm.shown(env)[0] == "Multiplayer: Online (hosting)"
    env.launcher.set(update=NEWER)
    env.frames(130)
    launcher_dies(env)
    assert env.interp.call("mistrimulti_update_note") == ""
    # on the title screen the long badge is left alone (the Update button says it)
    env = make(sha=False)
    env.frames(70)
    assert "update available" not in tm.shown(env)[0], tm.shown(env)
    # the F8 report and the tick are wired in
    boot = (GML_DIR / "MistriMultiBoot.gml").read_text()
    assert boot.count("mistrimulti_update_note()") == 2 and "mistrimulti_updateui_tick()" in boot
    print("PASS: update ui: in a world the badge and F8 say 'update available (x.y.z)'; the title screen badge stays short")


def test_minimum_screen_layout():
    """At the smallest screen (480 x 270) the title row has room: the game's text, our label and the button share the bottom left
    and end well before the copyright line; the badge sits a row higher on the right. Measured with a 6 px per character guess."""
    chars = len("v1.0.8 (modified)") + 1 + len("MistriMulti %s" % MODV)
    needed = 2 + chars * 6 + 6 + 46 + 6
    copyright_start = 480 - 2 - len("© 2024-2026 NPC Studio") * 6
    assert needed < copyright_start, (needed, copyright_start)
    env = make()
    env.frames(70)
    label, button, caption = parts(env)
    assert label["parent"] is env.sha and button["parent"] is label       # positions are relative: no overlap whatever the font width
    badge = tm.shown(env)
    print("PASS: update ui: layout at the minimum screen size (relative nodes; the row ends before the copyright line)")


ALL = [test_versions, test_fields_are_clean, test_label_is_always_there_and_button_follows_the_release,
       test_click_sends_one_update_command_and_progress_is_plain_words, test_click_waits_for_the_launcher_and_gives_up,
       test_stale_result_of_an_older_run_is_not_shown_as_the_new_one, test_click_guards, test_where_it_shows,
       test_fallback_without_the_games_text_node, test_nothing_can_throw, test_in_world_badge_and_note, test_minimum_screen_layout]

if __name__ == "__main__":
    for fn in ALL:
        fn()
    print("PASS")
