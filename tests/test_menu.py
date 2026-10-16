"""The in-game Multiplayer menu (MistriMultiMenu.gml, the badge in MistriMultiStatus.gml, the entry points in MistriMultiSaveSpace.gml).

    python3 tests/test_menu.py                                                  # GML logic against a scripted fake launcher
    python3 tests/test_menu.py LAUNCHER HELPER FAKEGAME                         # also the end-to-end test (Linux binaries)

The three GML files run unmodified in tests/gml_subset.py. The game's engine is faked: files (a dictionary, or the real
disk in the end-to-end test), the clock, the popups (MultipleChoicePopup, popup_creator, text_input_popup: a tap closes the
popup first and then calls the button's callback, exactly like the game's own code) and the localizer (the mod's
local.missing filter answers, as MMAPI would). A FakeLauncher plays the part of mistrimulti-launcher: it consumes cmd.txt and
publishes menu/status.json. The end-to-end test replaces it with the real launcher, helper and a real host (a second launcher),
inside the private network namespace the other launcher tests use (run it through unshare -n; see scripts / runall).

Not provable here: how the real game draws and closes these popups, MMAPI's file functions on a real disk, the hook names
(see docs/SYNC-MENU.md, "In-game checklist").
"""
import json
import os
from pathlib import Path
import sys
import time

import gml_subset as gml
from hud_fake import FakeAnchor, ALIGN, LAYERS
from hud_fake import FakeAnchor, ALIGN, LAYERS
from gml_subset import GStruct, GArray

ROOT = Path(__file__).resolve().parent.parent
GML_DIR = ROOT / "mod/mistrimulti/gml"
FILES = ("MistriMultiSaveSpace.gml", "MistriMultiStatus.gml", "MistriMultiMenu.gml", "MistriMultiHudText.gml")
MOD = "mod"                       # stands for mmapi_mod_data_dir("mistrimulti")
FRAME_US = 16667


class NoPopup(AssertionError):
    pass


class Popup:
    """One popup on screen. A tap closes it first, then runs the callback (Anchor's MultipleChoicePopup and PopupMenu do this)."""

    def __init__(self, env, kind, title, body=None):
        self.env, self.kind, self.title, self.body = env, kind, title, body
        self.buttons = []                       # (label key, callback, args)
        self.closed = False
        self.input_cb = None
        self.struct = GStruct(close_requested=False, close=self.close, create_button=self.create_button,
                              spawn=self.spawn, option=self.option, popup=None)
        self.struct["popup"] = self.struct
        env.screens.append(self)

    def close(self):
        if self.closed:
            self.env.errors.append("popup closed twice")
        self.closed = True
        self.struct["close_requested"] = True

    def create_button(self, label, cb=None, args=None):
        self.buttons.append((label, cb, list(args) if args else []))
        return GStruct()

    def spawn(self):
        return self.struct

    def option(self, label, cb, args):
        self.buttons.append((label, cb, list(args) if args else []))
        return self.struct

    def text(self, key):
        return self.env.local(key)


class Env:
    def __init__(self, disk=None, clock=None):
        self.disk = disk                        # None: files live in a dictionary, else the real mod data folder
        self.files = {}
        self.us = 5_000_000
        self.clock = clock
        self.screens, self.notes, self.logs, self.errors, self.entered = [], [], [], [], []
        self.launcher = None
        b = {
            "get_timer": self.get_timer, "mmapi_mod_data_dir": lambda name: MOD if disk is None else str(disk),
            "mistrimulti_data_dir": lambda: MOD if disk is None else str(disk),
            "file_exists": self.file_exists, "try_read_json_file": self.read_json, "save_text_file": self.save,
            "file_rename": self.rename, "MultipleChoicePopup": self.mcp, "popup_creator": self.popup_creator,
            "text_input_popup": self.text_input, "create_notification": self.notes.append,
            "Align": ALIGN, "AnchorLayer": LAYERS, "obj_ari": "obj_ari",
            "mmapi_log_info": lambda mod, text: self.logs.append(("info", text)),
            "mmapi_log_error": lambda mod, text: self.logs.append(("error", text)),
            "mmapi_log_flush": lambda mod: None, "mmapi_warn_rate_limited": lambda k, m, t: self.logs.append(("warn", t)),
            "string_lower": str.lower, "string_pos": lambda needle, hay: hay.find(needle) + 1,
            "version_to_string": lambda v: v, "GAME_VERSION": "1.0.6", "instance_exists": lambda o: True, "Setup": GStruct(),
            "Menu": GStruct(Load=3), "string_width": lambda t: len(t) * 6, "string_height": lambda t: 12,
            "NORMAL_MINSPEC_WIDTH": 480, "NORMAL_MINSPEC_HEIGHT": 270,
            "mistrimulti_savespace_enter": lambda kind, arg: self.entered.append((kind, arg)),
            "Game": GStruct(unique_identifier=123456), "LoadStateId": GStruct(New=1, Load=2),
        }
        self.interp = gml.Interpreter(b)
        self.anchor = FakeAnchor(self.interp)       # the game's ANCHOR: text nodes the badge lives in
        for name in FILES:
            self.interp.load((GML_DIR / name).read_text(encoding="utf-8"), name)
        # Engine parts of MistriMultiSaveSpace.gml are replaced by recorders; the menu only needs these three.
        self.interp.functions["mistrimulti_savespace_enter"] = lambda kind, arg: self.entered.append((kind, arg))
        self.interp.functions["mistrimulti_savespace_popup"] = self.savespace_popup
        # Boot parts the on-screen text uses: the runtime struct (room_settled) and the trace log
        sp = self.interp.call("__mistrimulti_savespace")            # what the title menu's own functions do (TitleMenu.enter_game ...)
        self.title_calls = []
        sp["orig_enter_game"] = lambda arg: self.title_calls.append(("enter_game", arg))
        sp["orig_transition_to"] = lambda target: self.title_calls.append(("transition_to", target))
        self.rt = GStruct(room_settled=True, enabled=False, mode="off", mask=0, peers=GArray([None] * 8))
        self.interp.functions["__mistrimulti_runtime"] = lambda: self.rt
        self.interp.functions["mistrimulti_trace"] = lambda key, text, limit=30: self.logs.append(("trace", text))

    # -- engine
    def path(self, path):
        return path if self.disk is None else path

    def get_timer(self):
        return time.monotonic_ns() // 1000 if self.disk is not None else self.us

    def file_exists(self, path):
        return path in self.files if self.disk is None else os.path.exists(path)

    def read_json(self, path):
        try:
            text = self.files[path] if self.disk is None else Path(path).read_text()
            return gml.from_json(json.loads(text))
        except (KeyError, ValueError, OSError):
            return None

    def save(self, path, text):
        if self.disk is None:
            self.files[path] = text
        else:
            Path(path).write_text(text)

    def rename(self, old, new):
        if self.disk is None:
            self.files[new] = self.files.pop(old)
        else:
            os.replace(old, new)

    def local(self, key):
        """local_get: a key the game does not know goes through the mod's local.missing filter."""
        out = self.interp.call("mistrimulti_local_missing", None, GStruct(key=key, fallback=key))
        return key if out is None else out

    def mcp(self, title):
        return Popup(self, "choice", title).struct

    def popup_creator(self, title, body=None):
        return Popup(self, "popup", title, body).struct

    def text_input(self, title, start, width, cb, args):
        p = Popup(self, "input", title)
        p.input_cb, p.input_args = cb, list(args)
        return p.struct

    def savespace_popup(self, title, body):
        Popup(self, "popup", title, body)

    # -- driving the "game"
    def open_screens(self):
        return [s for s in self.screens if not s.closed]

    def top(self):
        shown = self.open_screens()
        if not shown:
            raise NoPopup("no popup on screen")
        return shown[-1]

    def screen_text(self):
        t = self.top()
        label = [self.local(b[0]) for b in t.buttons]
        return self.local(t.title), (self.local(t.body) if t.body else ""), label

    def tap(self, label_part):
        t = self.top()
        for label, cb, args in t.buttons:
            if label_part.lower() in self.local(label).lower():
                if t.kind == "choice":
                    t.close()                   # MultipleChoicePopup closes itself, then runs the callback
                elif t.kind == "popup":
                    t.close()
                self.interp.call_value(cb, args, 0)
                return
        raise AssertionError(f"no button {label_part!r} in {self.screen_text()}")

    def type(self, text):
        t = self.top()
        assert t.kind == "input", t.kind
        t.close()
        self.interp.call_value(t.input_cb, [text] + t.input_args, 0)

    def dismiss_input(self):
        t = self.top()
        assert t.kind == "input"
        t.close()                               # closed without confirming (Escape / the Steam keyboard was cancelled)

    def frames(self, n=1):
        for _ in range(n):
            self.us += FRAME_US
            if self.launcher is not None:
                self.launcher.frame(self)
            self.interp.call("mistrimulti_menu_tick")
            self.interp.call("mistrimulti_savespace_tick")
            self.interp.call("mistrimulti_badge_tick")
            if self.errors:
                raise AssertionError(self.errors)

    def until(self, cond, limit=1500):
        for _ in range(limit):
            self.frames()
            try:
                if cond():
                    return
            except NoPopup:
                pass
        raise AssertionError("never happened: " + str(self.screen_text() if self.open_screens() else "no popup"))

    def wait_for(self, cond, secs):
        """Real-time waiting (end-to-end test): one frame every 30 ms until cond() holds."""
        end = time.monotonic() + secs
        while time.monotonic() < end:
            self.frames(1)
            time.sleep(0.03)
            try:
                if cond():
                    return True
            except NoPopup:
                pass
        return False

    def errors_logged(self):
        return [t for k, t in self.logs if k == "error"]

    def begin(self, kind="new", arg="state"):
        self.interp.call("mistrimulti_menu_begin", kind, arg)

    def new_game(self):
        """The player presses New Game on the title screen (the wrapper the mod puts over TitleMenu.enter_game)."""
        self.interp.call("mistrimulti_title_enter_game", GStruct(type=1))

    def load_game(self):
        self.interp.call("mistrimulti_title_transition_to", 3)


class FakeLauncher:
    """mistrimulti-launcher as the menu sees it: consumes menu/cmd.txt, publishes menu/status.json."""

    def __init__(self, env):
        self.env = env
        self.hb, self.seq, self.state, self.err, self.session = 100, 0, "idle", 0, "none"
        self.scan, self.helper = 0, 1
        self.addrs = ["100.64.0.5", "192.168.1.20"]
        self.hosts = []
        self.hw = self.hf = self.dw = 0           # the host's current world, its flags, the downloaded world (after a join)
        self.queue = []                         # (state, err, session) answers to the next command, one per publish
        self.cmds = []                          # every command received, as a dict
        self.alive = True
        self.frame_no = 0
        self.script = {}                        # cmd -> list of (state, err, session)
        self.pending_scan = False
        self.consume_every = 1                  # a slow launcher takes a while to pick a command up

    def publish(self):
        self.hb += 1
        doc = {"v": 1, "hb": self.hb, "seq": self.seq, "state": self.state, "err": self.err, "session": self.session,
               "helper": self.helper, "scan": self.scan, "port": 7777, "hw": self.hw, "hf": self.hf, "dw": self.dw, "addrs": self.addrs if self.session == "host" else [],
               "hosts": self.hosts}
        self.env.files[f"{MOD}/menu/status.json"] = json.dumps(doc)

    def frame(self, env):
        self.frame_no += 1
        if not self.alive:
            return
        path = f"{MOD}/menu/cmd.txt"
        if path in env.files and self.frame_no % self.consume_every == 0:
            text = env.files.pop(path)
            cmd = dict(line.split("=", 1) for line in text.split("\n") if "=" in line)
            if int(cmd["seq"]) == self.seq:                  # the real launcher answers each sequence number once
                return
            self.cmds.append(cmd)
            self.seq = int(cmd["seq"])
            self.queue = list(self.script.get(cmd["cmd"], []))
            self.pending_scan = cmd["cmd"] == "scan"
            if cmd["cmd"] == "stop":
                self.state, self.err, self.session = "idle", 0, "none"
            self.step()
        elif self.frame_no % 30 == 0:
            if self.queue:
                self.step()
            else:
                self.publish()

    def step(self):
        if self.queue:
            self.state, self.err, self.session = self.queue.pop(0)
        if self.pending_scan and self.state != "scanning":      # a scan counts when it ended (like the real launcher)
            self.scan += 1
            self.pending_scan = False
        self.publish()


def make(launcher=True, **kw):
    env = Env()
    env.launcher = FakeLauncher(env)
    env.launcher.script["scan"] = [("idle", 0, "none")]
    env.launcher.publish()
    for k, v in kw.items():
        setattr(env.launcher, k, v)
    return env


def labels(env):
    return env.screen_text()[2]


def settle(env, n=40):
    env.frames(n)


# ---------------------------------------------------------------------------------------------------------------------------
def test_unavailable_launcher():
    env = make()
    env.files.pop(f"{MOD}/menu/status.json")
    env.begin()
    title, body, _ = env.screen_text()
    assert "offline" in title.lower() and "Start the game from Steam" in body, (title, body)
    env.screens.clear()
    env.files[f"{MOD}/menu/status.json"] = "{ not json"
    env.begin()
    assert "not running" in env.screen_text()[1]
    # a helper that is not installed says so
    env2 = make(helper=0)
    env2.launcher.publish()
    env2.begin()
    assert "helper program is missing" in env2.screen_text()[1], env2.screen_text()
    # a launcher whose heartbeat stopped
    env3 = make()
    env3.frames(10)
    env3.launcher.alive = False
    env3.frames(60 * 6)
    env3.screens.clear()
    env3.begin()
    assert "stopped answering" in env3.screen_text()[1], env3.screen_text()
    # a launcher that ended says "stopped" at once
    env4 = make(state="stopped")
    env4.launcher.publish()
    env4.begin()
    assert "stopped answering" in env4.screen_text()[1]
    print("PASS: menu: an absent, unreadable, stopped or helper-less launcher is explained in plain words, nothing else starts")


def test_host_flow():
    env = make()
    env.launcher.script["host"] = [("idle", 0, "none")] * 3 + [("hosting", 0, "host")]
    env.frames(5)
    env.begin("new", "STATE")
    title, _, opts = env.screen_text()
    assert title == "Multiplayer" and opts == ["Host a game", "Join a game", "Cancel"], (title, opts)
    env.tap("Host a game")
    env.frames(30)
    assert env.screen_text()[0] == "Host a game" and "Start hosting" in labels(env)[0], env.screen_text()
    assert env.launcher.cmds == []
    env.tap("Start hosting")
    env.frames(40)
    assert env.screen_text()[0] == "Multiplayer" and "Starting" in env.screen_text()[1], env.screen_text()
    assert env.launcher.cmds and env.launcher.cmds[0]["cmd"] == "host" and "password" not in env.launcher.cmds[0], env.launcher.cmds
    env.until(lambda: env.screen_text()[0] == "You are hosting")
    body = env.screen_text()[1]
    assert "Tailscale: 100.64.0.5" in body and "This network: 192.168.1.20" in body, body
    assert labels(env) == ["Stop hosting", "Start playing"]
    env.tap("Start playing")
    env.frames(5)
    assert env.entered == [("new", "STATE")], env.entered
    assert env.interp.call("__mistrimulti_menu")["flow"] is None
    assert not env.open_screens()
    print("PASS: menu: Host a game -> Start hosting -> addresses to give to friends -> Start playing enters the multiplayer world")


def test_host_password_and_cancel():
    env = make()
    env.launcher.script["host"] = [("hosting", 0, "host")]
    env.begin()
    env.tap("Host a game")
    env.frames(30)
    env.tap("Set a password")
    env.frames(30)
    assert env.top().kind == "input" and "password" in env.local(env.top().title)
    env.type("pa$$w0rd!")
    env.frames(30)
    assert env.screen_text()[0] == "Host a game" and "Change the password" in labels(env)[1]
    env.tap("Start hosting")
    env.until(lambda: env.screen_text()[0] == "You are hosting")
    assert env.launcher.cmds[-1]["password"] == "pa$$w0rd!", env.launcher.cmds[-1]
    # Stop hosting tells the launcher to stop, and nothing is entered
    env.tap("Stop hosting")
    env.frames(5)
    assert env.launcher.cmds[-1]["cmd"] == "stop" and env.launcher.session == "none" and not env.entered
    # invalid passwords never reach the launcher: a space, a newline (injection of another key), too long, empty
    for bad in ("two words", "ab\ncmd=join", "x" * 65, "é1"):
        env2 = make()
        env2.begin()
        env2.tap("Host a game")
        env2.frames(30)
        env2.tap("Set a password")
        env2.frames(30)
        env2.type(bad)
        env2.frames(30)
        assert "cannot be used" in env2.screen_text()[1], (bad, env2.screen_text())
        assert env2.launcher.cmds == []
    # Back from the host screen returns to the choice
    env3 = make()
    env3.begin()
    env3.tap("Host a game")
    env3.frames(30)
    env3.tap("Back")
    env3.frames(30)
    assert env3.screen_text()[2] == ["Host a game", "Join a game", "Cancel"]
    env3.tap("Cancel")
    env3.frames(30)
    assert not env3.open_screens() and env3.launcher.cmds == [], "cancel before any command must not send one"
    print("PASS: menu: host password (valid ones sent, invalid or injecting ones refused), Stop hosting, Back and Cancel")


def hosts(*items):
    out = []
    for ip, name, flags in items:
        out.append({"ip": ip, "port": 7777, "flags": flags, "name": name})
    return out


def test_join_flow():
    env = make()
    env.launcher.hosts = hosts(("100.64.0.9", "DECK", 0), ("192.168.1.30", "PC", 2))
    env.launcher.script["scan"] = [("scanning", 0, "none"), ("scanning", 0, "none"), ("idle", 0, "none")]
    env.launcher.script["join"] = [("joining", 0, "join"), ("downloading", 0, "join"), ("ready", 0, "join")]
    env.begin("load", None)
    env.tap("Join a game")
    env.frames(30)
    assert "Looking for hosts" in env.screen_text()[1]
    env.until(lambda: env.screen_text()[0].startswith("Join a game"))
    title, _, opts = env.screen_text()
    assert title == "Join a game: pick a host", title
    assert opts == ["DECK  100.64.0.9", "PC  192.168.1.30  [password]", "Type an address", "Refresh", "Cancel"], opts
    env.tap("DECK")
    env.frames(14)
    assert "Connecting to 100.64.0.9" in env.screen_text()[1], env.screen_text()
    join = env.launcher.cmds[-1]
    assert join == {"seq": join["seq"], "cmd": "join", "host": "100.64.0.9", "port": "7777"}, join
    env.until(lambda: not env.open_screens() and env.entered)
    assert env.entered == [("load", None)]
    assert any("downloaded" in t for k, t in env.logs)
    print("PASS: menu: Join a game scans, lists the hosts found, joins the picked one and enters the world after the download")


def test_join_password_and_room():
    env = make()
    env.launcher.hosts = hosts(("192.168.1.30", "PC", 2 | 1))
    env.launcher.script["join"] = [("joining", 0, "join"), ("ready", 0, "join")]
    env.begin()
    env.tap("Join a game")
    env.until(lambda: env.screen_text()[0].startswith("Join a game"))
    env.tap("PC")
    env.frames(30)
    assert env.top().kind == "input" and "room code" in env.local(env.top().title)
    env.type("zzzz")                                        # not a room code
    env.frames(30)
    assert "not valid" in env.screen_text()[1] and not [c for c in env.launcher.cmds if c["cmd"] == "join"]
    env.tap("Try again")
    env.frames(30)
    assert env.top().kind == "input"
    env.type("ABCDEF12")
    env.frames(30)
    assert "password" in env.local(env.top().title), "a host with both flags asks for the room code, then the password"
    env.type("tops3cret")
    env.until(lambda: env.entered)
    join = [c for c in env.launcher.cmds if c["cmd"] == "join"][-1]
    assert join["room"] == "abcdef12" and join["password"] == "tops3cret" and join["host"] == "192.168.1.30", join
    print("PASS: menu: a host that needs a room code and a password gets both, validated, lowercase room")


def test_typed_address_and_errors():
    env = make()
    env.launcher.script["join"] = [("error", 26, "none")]
    env.begin()
    env.tap("Join a game")
    env.until(lambda: env.screen_text()[0].startswith("Join a game"))
    assert env.screen_text()[0] == "Join a game: no host found", env.screen_text()
    env.tap("Type an address")
    env.frames(30)
    assert env.top().kind == "input"
    env.type("999.1.1.1")
    env.frames(30)
    assert "not valid" in env.screen_text()[1] and not [c for c in env.launcher.cmds if c["cmd"] == "join"]
    env.tap("Try again")
    env.frames(30)
    env.type("100.101.102.103")
    env.until(lambda: "needs a password" in env.screen_text()[1])
    join = [c for c in env.launcher.cmds if c["cmd"] == "join"][-1]
    assert join["host"] == "100.101.102.103" and join["port"] == "7777" and "password" not in join, join
    # the host wants a password: Try again asks for it; a wrong one is reported and asked again
    env.launcher.script["join"] = [("error", 21, "none")]
    env.tap("Try again")
    env.frames(30)
    assert env.top().kind == "input" and "password" in env.local(env.top().title)
    env.type("wrong")
    env.until(lambda: "Wrong password" in env.screen_text()[1])
    assert [c for c in env.launcher.cmds if c["cmd"] == "join"][-1]["password"] == "wrong"
    # an unusable password typed for a join never reaches the launcher
    env.tap("Try again")
    env.frames(30)
    n = len([c for c in env.launcher.cmds if c["cmd"] == "join"])
    env.type("two words")
    env.frames(30)
    assert "cannot be used" in env.screen_text()[1] and len([c for c in env.launcher.cmds if c["cmd"] == "join"]) == n
    env.launcher.script["join"] = [("joining", 0, "join"), ("ready", 0, "join")]
    env.tap("Try again")
    env.frames(30)
    env.type("right-one")
    env.until(lambda: env.entered)
    # every command has its own sequence number
    seqs = [c["seq"] for c in env.launcher.cmds]
    assert len(set(seqs)) == len(seqs) and len(seqs) >= 4, seqs
    # every error code has words (and an unknown one still says something)
    for code in (1, 2, 3, 4, 5, 6, 7, 21, 22, 23, 24, 26, 41, 42, 43, 44, 45, 46, 47, 99):
        text = env.interp.call("mistrimulti_menu_error_text", code)
        assert len(text) > 20 and "None" not in text, (code, text)
    assert "sleep in bed" in env.interp.call("mistrimulti_menu_error_text", 42)
    assert "port" in env.interp.call("mistrimulti_menu_error_text", 41)
    print("PASS: menu: typed addresses are validated, a missing or wrong password is asked for again, every error has plain words")


def test_cancel_and_timeouts():
    # cancelling the wait sends stop
    env = make()
    env.launcher.script["join"] = [("joining", 0, "join")] + [("joining", 0, "join")] * 40
    env.launcher.hosts = hosts(("100.64.0.9", "DECK", 0))
    env.begin()
    env.tap("Join a game")
    env.until(lambda: env.screen_text()[0].startswith("Join a game"))
    env.tap("DECK")
    env.frames(60)
    assert "Connecting" in env.screen_text()[1]
    env.tap("Cancel")
    env.frames(30)
    assert env.launcher.cmds[-1]["cmd"] == "stop" and not env.open_screens() and not env.entered
    # a launcher that goes silent while we wait
    env = make()
    env.begin()
    env.tap("Join a game")
    env.launcher.alive = False
    env.until(lambda: env.open_screens() and "host did not answer" in env.screen_text()[1], 2000)
    # a download that never ends
    env = make()
    env.launcher.hosts = hosts(("100.64.0.9", "DECK", 0))
    env.launcher.script["join"] = [("downloading", 0, "join")] * 400
    env.begin()
    env.tap("Join a game")
    env.until(lambda: env.screen_text()[0].startswith("Join a game"))
    env.tap("DECK")
    env.frames(60)
    env.until(lambda: "Downloading" in env.screen_text()[1])
    env.until(lambda: "did not answer" in env.screen_text()[1], 8000)
    # closing the text box without confirming returns to the list; Escape on a wait popup cancels
    env = make()
    env.begin()
    env.tap("Join a game")
    env.until(lambda: env.screen_text()[0].startswith("Join a game"))
    env.tap("Type an address")
    env.frames(30)
    env.dismiss_input()
    env.frames(60)
    assert env.screen_text()[0].startswith("Join a game"), env.screen_text()
    env.launcher.script["scan"] = [("scanning", 0, "none")] * 50
    env.tap("Refresh")
    env.frames(20)
    env.top().close()                                       # the player pressed Escape on "Looking for hosts"
    env.frames(30)
    assert not env.open_screens() and env.launcher.cmds[-1]["cmd"] == "stop"
    print("PASS: menu: Cancel and Escape stop the session, a silent launcher or a stuck download ends with a message, a cancelled text box goes back")


def test_commands_are_queued_in_order():
    env = make()
    env.launcher.consume_every = 25
    env.launcher.script["host"] = [("hosting", 0, "host")]
    first = env.interp.call("mistrimulti_menu_send", "host", GStruct(password="abc"))
    second = env.interp.call("mistrimulti_menu_send", "stop", None)
    third = env.interp.call("mistrimulti_menu_send", "scan", None)
    assert first < second < third
    env.frames(200)
    assert [c["cmd"] for c in env.launcher.cmds] == ["host", "stop", "scan"], env.launcher.cmds
    assert env.launcher.cmds[0]["password"] == "abc" and [int(c["seq"]) for c in env.launcher.cmds] == [first, second, third]
    assert len(env.interp.call("__mistrimulti_menu")["outbox"]) == 0
    print("PASS: menu: commands are written one at a time in order; a stop right after a join cannot replace it")


def test_refresh_and_scan_failure():
    env = make()
    env.launcher.script["scan"] = [("error", 7, "none")]
    env.begin()
    env.tap("Join a game")
    env.until(lambda: env.screen_text()[0].startswith("Join a game") or env.screen_text()[0].startswith("Searching"))
    assert "Searching is not available" in env.screen_text()[0], env.screen_text()
    assert "Type an address" in labels(env)
    env.launcher.script["scan"] = [("idle", 0, "none")]
    env.launcher.hosts = hosts(("100.64.0.9", "DECK", 0))
    env.tap("Refresh")
    env.until(lambda: env.screen_text()[0] == "Join a game: pick a host")
    print("PASS: menu: a failed scan still offers Type an address; Refresh scans again")


def test_hostile_status_file():
    env = make()
    doc = {"v": 1, "hb": 5, "seq": 1, "state": "idle", "err": 0, "session": "none", "helper": 1, "scan": 1, "port": 7777,
           "addrs": ["100.64.0.5", "not an ip", 7, "1.2.3.4.5", "999.1.1.1", "<script>"],
           "hosts": [{"ip": "10.0.0.1", "port": 7777, "flags": 2, "name": "x" * 100}, {"ip": "bad", "port": 7777, "flags": 0, "name": "a"},
                     {"ip": "10.0.0.2", "port": 99999, "flags": 0, "name": "b"}, {"ip": "10.0.0.3", "port": "7777", "flags": 0},
                     "text", {"ip": "10.0.0.4", "port": 7777, "flags": 0, "name": 5}]}
    env.files[f"{MOD}/menu/status.json"] = json.dumps(doc)
    st = env.interp.call("mistrimulti_menu_clean", gml.from_json(doc))
    assert list(st["addrs"]) == ["100.64.0.5"], st["addrs"]
    assert [h["ip"] for h in st["hosts"]] == ["10.0.0.1", "10.0.0.4"] and len(st["hosts"][0]["name"]) == 31, st["hosts"]
    assert st["hosts"][1]["name"] == ""
    for bad in (None, 5, "x", GArray(), GStruct(v=2, hb=1, seq=1, state="idle", err=0), GStruct(v=1, hb="1", seq=1, state="idle", err=0)):
        assert env.interp.call("mistrimulti_menu_clean", bad) is None
    assert env.interp.call("mistrimulti_menu_valid_ip", "1.2.3.4") and not env.interp.call("mistrimulti_menu_valid_ip", "1.2.3")
    assert not env.interp.call("mistrimulti_menu_valid_ip", "1..3.4") and not env.interp.call("mistrimulti_menu_valid_ip", "01.2.3.4.")
    assert env.interp.call("mistrimulti_menu_valid_room", "aBcdEF12") and not env.interp.call("mistrimulti_menu_valid_room", "abcdeg12")
    print("PASS: menu: a hostile or damaged status.json is cleaned field by field; addresses, rooms and passwords are validated")


def test_title_entered_stops_sessions():
    env = make()
    env.launcher.script["host"] = [("hosting", 0, "host")]
    env.begin()
    env.tap("Host a game")
    env.frames(30)
    env.tap("Start hosting")
    env.until(lambda: env.screen_text()[0] == "You are hosting")
    env.tap("Start playing")
    env.frames(5)
    assert env.launcher.session == "host"
    n = len(env.launcher.cmds)
    env.interp.call("mistrimulti_badge_tick")
    env.interp.call("mistrimulti_menu_title_entered")        # the player quit to the title screen
    env.frames(5)
    assert env.launcher.cmds[n]["cmd"] == "stop" and env.launcher.session == "none"
    n = len(env.launcher.cmds)
    env.interp.call("mistrimulti_menu_title_entered")        # nothing running: no command
    env.frames(5)
    assert len(env.launcher.cmds) == n
    print("PASS: menu: returning to the title screen stops a running host or join, and sends nothing when idle")


def test_texts_and_keys():
    env = make()
    for i in range(200):                                     # the text table does not grow without bound
        env.interp.call("mistrimulti_menu_t", f"line {i}")
    st = env.interp.call("__mistrimulti_menu")
    assert len(st["texts"]) <= 81, len(st["texts"])
    key = env.interp.call("mistrimulti_menu_t", "hello")
    assert env.local(key) == "hello"
    assert env.local("mistrimulti/multiplayer") == "Multiplayer" and env.local("misc_local/cancel") == "misc_local/cancel"
    # The popup buttons are about 97 px wide (the mod widens them to the popup, but the game's text does not wrap): short labels.
    for key in ("mistrimulti/singleplayer", "mistrimulti/multiplayer", "mistrimulti/continue_world", "mistrimulti/new_world",
                "mistrimulti/opt_hearts_own", "mistrimulti/opt_hearts_shared"):
        assert 0 < len(env.local(key)) <= 18, (key, env.local(key))
    assert env.local("mistrimulti/continue_world") == "Continue world" and env.local("mistrimulti/new_world") == "New world"
    print("PASS: menu: dynamic texts get their own keys, are bounded, other keys are left to the game, and the popup button labels are short")


def test_failure_never_reaches_the_game():
    env = make()
    env.begin()
    # the popup constructor of the game throws: the flow resets, the error is logged, no exception escapes the tick
    def boom(*a):
        raise gml.GmlError("popup failed")
    env.interp.builtins["MultipleChoicePopup"] = boom
    env.tap("Host a game")
    env.frames(30)
    assert env.errors_logged() and not env.interp.call("__mistrimulti_menu").get("flow")
    assert env.launcher.cmds[-1]["cmd"] == "stop"
    env.logs.clear()
    env = make()
    env.begin()
    env.interp.builtins["save_text_file"] = boom
    env.tap("Host a game")
    env.frames(30)
    env.tap("Start hosting")
    env.frames(30)
    assert env.errors_logged(), env.logs
    print("PASS: menu: popup or file failures are logged and reset the flow; the game is never given an exception")


def badge(env):
    env.interp.call("mistrimulti_netstatus_refresh")
    return env.interp.call("mistrimulti_status_text")


def shown(env):
    """The badge as the player sees it: (text, colour) of the visible coloured node, or None."""
    nodes = [n for n in env.anchor.nodes if not n["freed"] and not n["stale"] and n["alpha"] == 1 and n["z"] == 900 and n["layer"] == LAYERS["Popup"]]
    assert len(nodes) <= 1, nodes
    return (nodes[0]["text"], nodes[0]["color"]) if nodes else None


GREEN, AMBER, RED = 40 + 200 * 256 + 70 * 65536, 20 + 170 * 256 + 230 * 65536, 50 + 60 * 256 + 220 * 65536


def test_badge():
    env = make()
    env.frames(5)
    b = badge(env)
    assert b["text"].startswith("Multiplayer: Idle") and b["level"] == "idle", b
    t, c = shown(env)
    assert t.startswith("Multiplayer: Idle") and c == AMBER, (t, c)
    assert "helper not running" not in t
    # no launcher at all: Offline with the reason, and a first log line says why
    env.files.pop(f"{MOD}/menu/status.json")
    b = badge(env)
    assert b["text"].startswith("Multiplayer: Offline - launcher not running") and b["level"] == "offline", b
    env.interp.call("mistrimulti_badge_tick")                # shows what the refresh just read
    t, c = shown(env)
    assert t.startswith("Multiplayer: Offline - launcher not running") and c == RED, (t, c)
    assert any("Badge: Multiplayer: Offline - launcher not running" in t and "does not exist" in t for k, t in env.logs), env.logs
    assert any("on screen for the first time" in t for k, t in env.logs)
    # launcher present
    env.launcher.publish()
    assert badge(env)["level"] == "idle"
    env.launcher.helper = 0
    env.launcher.publish()
    assert badge(env)["text"] == "Multiplayer: Offline - helper program missing"
    env.launcher.helper = 1
    env.launcher.publish()
    # a hosting session: Online only while the helper's own heartbeat moves
    env.files[f"{MOD}/control.json"] = json.dumps({"enabled": True, "mode": "host", "id": 0, "bridge": MOD + "/bridge_0"})
    b = badge(env)
    assert b["text"] == "Multiplayer: Starting..." and not b["online"] and b["level"] == "idle", b    # no heartbeat yet: not an error
    for i in range(3):
        env.files[f"{MOD}/bridge_0/status.json"] = json.dumps({"running": True, "heartbeat": 1000 + i})
        env.frames(1)
        b = badge(env)
    assert b["text"] == "Multiplayer: Online (hosting)" and b["online"] and b["level"] == "online", b
    env.interp.call("mistrimulti_badge_tick")
    assert shown(env) == ("Multiplayer: Online (hosting)", GREEN), shown(env)
    env.us += 4_000_000                                      # the helper's heartbeat stops
    env.launcher.publish()
    b = badge(env)
    assert b["text"] == "Multiplayer: Offline - helper stopped" and b["why"], b
    env.files[f"{MOD}/control.json"] = json.dumps({"enabled": False, "mode": "idle", "id": 0, "bridge": ""})
    env.launcher.publish()
    assert badge(env)["level"] == "idle" and badge(env)["text"] == "Multiplayer: Idle - ready"
    # the launcher stopped answering
    env.us += 5_000_000
    assert badge(env)["text"] == "Multiplayer: Offline - launcher stopped"
    env.launcher.state = "stopped"
    env.launcher.publish()
    assert badge(env)["text"] == "Multiplayer: Offline - launcher stopped"
    # an old game version
    env.interp.builtins["GAME_VERSION"] = "9.9.9"
    assert "game updated" in badge(env)["text"]
    print("PASS: menu: the badge says Offline (with the reason), Idle or Online in red / amber / green, and logs every change of its text with the reason")


def world_runtime(env, mode, beat, mask):
    """The runtime as MistriMultiBoot.gml's tick leaves it: helper status.json read, heartbeat seen, peer mask."""
    env.rt.update(enabled=True, mode=mode, status=GStruct(running=True, mask=mask, heartbeat=beat), status_heartbeat=beat,
                  status_seen_at=env.us, mask=mask)


def test_badge_in_world():
    """In a multiplayer world the badge follows the signals the event layer uses (heartbeat + peer mask), not control.json."""
    env = make()
    env.launcher.publish()
    # control.json says nothing useful (no session file at all) yet both players play: Online, never 'helper not running'
    world_runtime(env, "host", 7, 0b11)
    env.frames(70)
    assert shown(env)[0] == "Multiplayer: Online (hosting)" and shown(env)[1] == GREEN, shown(env)
    world_runtime(env, "join", 8, 0b11)
    env.frames(70)
    assert shown(env) == ("Multiplayer: Online (joined)", GREEN), shown(env)
    assert any("Badge: Multiplayer: Online (joined)" in t and "heartbeat 8" in t and "mask 3" in t for k, t in env.logs), env.logs
    # a guest that does not see the host yet is not Online
    world_runtime(env, "join", 9, 0b10)
    env.frames(70)
    assert shown(env) == ("Multiplayer: Joining the host...", AMBER), shown(env)
    # a heartbeat that stopped moving: Offline with a plain reason; the world coming back flips it again
    world_runtime(env, "join", 9, 0b11)
    env.us += 4_000_000
    env.frames(70)
    assert shown(env) == ("Multiplayer: Offline - connection lost", RED), shown(env)
    world_runtime(env, "host", 12, 0b01)
    env.frames(70)
    assert shown(env)[0] == "Multiplayer: Online (hosting)"
    # the runtime has not read the helper yet (first second of the world)
    env.rt.update(status=None, status_seen_at=0, status_heartbeat=-1)
    env.frames(70)
    assert shown(env)[0] == "Multiplayer: Connecting..."
    # every text change was logged with its reason
    texts = [t for k, t in env.logs if t.startswith("Badge: ")]
    assert len(texts) >= 6 and all("(" in t and "[" in t for t in texts), texts
    # position: above the game's copyright line on the title screen, the plain corner in a world
    env = make()
    env.rt.update(enabled=False)
    env.interp.builtins["instance_exists"] = lambda o: o != "obj_ari"
    env.frames(3)
    main = [n for n in env.anchor.nodes if n["z"] == 900][0]
    assert main["pos"][1] <= -14, main["pos"]
    env.interp.builtins["instance_exists"] = lambda o: True
    env.frames(3)
    main = [n for n in env.anchor.nodes if n["z"] == 900 and not n["freed"]][0]
    back = [n for n in env.anchor.nodes if n["z"] == 901 and not n["freed"]][0]
    assert main["pos"][1] == -4 and back["pos"] == (main["pos"][0] + 1, main["pos"][1] + 1), (main["pos"], back["pos"])
    print("PASS: menu: in a world the badge reads the event layer's heartbeat and peer mask (Online hosting / joined), is never stale, "
          "and sits above the title screen's copyright line")


def test_badge_on_screen_is_robust():
    env = make()
    env.frames(5)
    assert shown(env) is not None
    # the nodes: one coloured text and a black copy behind it, bottom right on the Popup layer (above the HUD and the toolbar), in the same text
    mains = [n for n in env.anchor.nodes if n["z"] == 900]
    backs = [n for n in env.anchor.nodes if n["z"] == 901]
    assert len(mains) == len(backs) == 1 and backs[0]["text"] == mains[0]["text"] and backs[0]["color"] == 0
    assert mains[0]["align"] == (ALIGN["RightIn"], ALIGN["BottomIn"]) and mains[0]["pos"][0] < 0 and mains[0]["pos"][1] < 0
    # ticks do not make new nodes
    before = len(env.anchor.nodes)
    env.frames(300)
    assert len(env.anchor.nodes) == before
    # ANCHOR rebuilt by the game (nodes freed, or only replaced): the badge builds itself again
    for free in (True, False):
        env.anchor.rebuild(free=free)
        env.frames(2)
        t = shown(env)
        assert t is not None and t[0].startswith("Multiplayer: Idle"), (free, t)
    # nothing is created while a room change is not settled (in a world), but the title screen is never held back
    env.anchor.rebuild()
    env.rt["room_settled"] = False
    env.frames(5)
    assert shown(env) is None
    env.interp.builtins["instance_exists"] = lambda o: o != "obj_ari"
    env.frames(2)
    assert shown(env) is not None
    env.interp.builtins["instance_exists"] = lambda o: True
    env.anchor.rebuild()
    env.frames(2)
    assert shown(env) is None
    env.rt["room_settled"] = True
    env.frames(2)
    assert shown(env) is not None
    # neither title screen nor multiplayer world (e.g. a singleplayer world): the badge hides, and comes back
    env.interp.builtins["instance_exists"] = lambda o: False
    env.frames(2)
    assert shown(env) is None
    env.interp.builtins["instance_exists"] = lambda o: True
    env.frames(2)
    assert shown(env) is not None
    # ANCHOR throwing: nothing reaches the game, the failure is logged, and it recovers
    env = make()
    env.anchor.broken = True
    env.frames(5)
    assert shown(env) is None and not env.errors
    assert any(k == "warn" and "On-screen text 'badge' failed" in t for k, t in env.logs), env.logs
    env.anchor.broken = False
    env.frames(2)
    assert shown(env) is not None
    # ANCHOR without a screen canvas yet, or an enum missing: no node, no exception
    env = make()
    env.interp.builtins["ANCHOR"] = GStruct()
    env.frames(5)
    assert shown(env) is None
    env.interp.builtins["ANCHOR"] = env.anchor.struct
    del env.interp.builtins["AnchorLayer"]
    env.frames(5)
    assert shown(env) is None
    # a throwing status read degrades to a visible Offline text instead of nothing
    env = make()

    def boom(*a):
        raise gml.GmlError("no text")
    env.interp.builtins["try_read_json_file"] = boom
    env.interp.call("mistrimulti_badge_tick")                # (the menu's own tick is guarded by Boot, not called here)
    t = shown(env)
    assert t is not None and t[0] == "Multiplayer: Offline - status unavailable", t
    # the draw hook never firing is reported by the watchdog; firing silences it
    env = make()
    for _ in range(901):
        env.interp.call("mistrimulti_badge_watchdog")
    assert any("ui.draw_gui hook has not fired" in t for k, t in env.logs)
    env = make()
    env.interp.call("mistrimulti_draw_status", 1)
    for _ in range(901):
        env.interp.call("mistrimulti_badge_watchdog")
    assert not any("ui.draw_gui hook has not fired" in t for k, t in env.logs)
    print("PASS: menu: the badge is a coloured ANCHOR text node with an outline copy; rebuilt after ANCHOR is rebuilt, held during room "
          "changes, hidden outside title / multiplayer worlds, never throws, and the watchdog reports a silent draw hook")


# ---------------------------------------------------------------------------------------------------------------------------
# Real-game finding 1: New Game > Multiplayer > Host a game > Cancel left New Game dead until the game was restarted.
# The game closes any popup by itself on Escape (and on a click outside it) WITHOUT calling a button, so a flag that only a button
# callback cleared stayed set. These tests walk every way out of every screen and then start the flow again.

def sp_mp_question(env):
    env.new_game()
    assert env.screen_text()[0] == "Singleplayer or Multiplayer?", env.screen_text()


def at_choose(env):
    sp_mp_question(env)
    env.tap("Multiplayer")
    assert env.screen_text()[0] == "Multiplayer" and labels(env) == ["Host a game", "Join a game", "Cancel"], env.screen_text()


def at_host(env):
    at_choose(env)
    env.tap("Host a game")
    env.frames(30)
    assert env.screen_text()[0] == "Host a game", env.screen_text()


def at_wait_host(env):
    env.launcher.script["host"] = [("idle", 0, "none")] * 400
    at_host(env)
    env.tap("Start hosting")
    env.frames(40)
    assert "Starting" in env.screen_text()[1], env.screen_text()


def at_hosting(env):
    env.launcher.script["host"] = [("hosting", 0, "host")]
    at_host(env)
    env.tap("Start hosting")
    env.until(lambda: env.screen_text()[0] == "You are hosting")


def at_join_list(env):
    env.launcher.hosts = hosts(("100.64.0.9", "DECK", 0), ("192.168.1.30", "PC", 2), ("10.0.0.7", "ROOM", 1))
    at_choose(env)
    env.tap("Join a game")
    env.until(lambda: env.screen_text()[0].startswith("Join a game: pick"))


def at_wait_scan(env):
    env.launcher.script["scan"] = [("scanning", 0, "none")] * 400
    at_choose(env)
    env.tap("Join a game")
    env.frames(40)
    assert "Looking for hosts" in env.screen_text()[1], env.screen_text()


def at_wait_join(env):
    env.launcher.script["join"] = [("joining", 0, "join")] * 400
    at_join_list(env)
    env.tap("DECK")
    env.frames(40)
    assert "Connecting" in env.screen_text()[1], env.screen_text()


def at_downloading(env):
    env.launcher.script["join"] = [("joining", 0, "join"), ("downloading", 0, "join")] + [("downloading", 0, "join")] * 400
    at_join_list(env)
    env.tap("DECK")
    env.until(lambda: "Downloading" in env.screen_text()[1])


def at_error(code):
    def go(env):
        env.launcher.script["join"] = [("error", code, "none")]
        at_join_list(env)
        env.tap("DECK")
        env.until(lambda: env.screen_text()[1] == env.interp.call("mistrimulti_menu_error_text", code))
    return go


def at_text_box(kind):
    def go(env):
        if kind == "host_pass":
            at_host(env)
            env.tap("Set a password")
        elif kind == "ip":
            at_join_list(env)
            env.tap("Type an address")
        elif kind == "password":
            at_join_list(env)
            env.tap("PC")
        else:
            at_join_list(env)
            env.tap("ROOM")
        env.frames(30)
        assert env.top().kind == "input", env.screen_text()
    return go


def at_world_mismatch(env):
    env.launcher.script["join"] = [("joining", 0, "join"), ("ready", 0, "join")]
    env.launcher.hw, env.launcher.dw, env.launcher.hf = 7, 9, 3
    at_join_list(env)
    env.tap("DECK")
    env.until(lambda: "different world" in env.screen_text()[1])


def check_fresh(env, name, stopped):
    """Nothing of the flow is left, the launcher has no session, and New Game works again all the way to the Host / Join choice."""
    env.frames(60)
    sp = env.interp.call("__mistrimulti_savespace")
    assert not env.open_screens(), (name, [env.screen_text()])
    assert env.interp.call("__mistrimulti_menu")["flow"] is None, name
    assert sp["choosing"] is False, (name, "the choosing flag is still set")
    assert env.launcher.session == "none" and env.launcher.state in ("idle", "error"), (name, env.launcher.session, env.launcher.state)
    if stopped:
        assert any(c["cmd"] == "stop" for c in env.launcher.cmds[-2:]), (name, "no stop was sent", env.launcher.cmds[-3:])
    assert not env.entered, name
    env.new_game()                                          # the player presses New Game again
    assert env.screen_text()[0] == "Singleplayer or Multiplayer?", (name, "New Game does nothing", env.open_screens())
    env.tap("Multiplayer")
    assert env.screen_text()[0] == "Multiplayer", name
    env.tap("Cancel")
    env.frames(30)
    assert not env.open_screens() and sp["choosing"] is False, name
    # Load Game asks the same question
    env.load_game()
    assert env.screen_text()[0] == "Singleplayer or Multiplayer?", (name, "Load Game does nothing")
    env.top().close()
    env.frames(30)
    assert sp["choosing"] is False, name


def test_every_cancel_path_resets_and_can_restart():
    screens = [
        # name, how to get there, [(how to leave, stop expected)]
        ("question", sp_mp_question, [("escape", False)]),
        ("choose", at_choose, [("Cancel", False), ("escape", False)]),
        ("host", at_host, [("escape", False), ("Back,Cancel", False)]),
        ("wait for the host to start", at_wait_host, [("Cancel", True), ("escape", True)]),
        ("hosting", at_hosting, [("Stop hosting", True), ("escape", True)]),
        ("host list", at_join_list, [("Cancel", False), ("escape", False)]),
        ("looking for hosts", at_wait_scan, [("Cancel", True), ("escape", True)]),
        ("connecting", at_wait_join, [("Cancel", True), ("escape", True)]),
        ("downloading", at_downloading, [("Cancel", True), ("escape", True)]),
        ("wrong password", at_error(21), [("Close", True), ("escape", True)]),
        ("host unreachable", at_error(4), [("Close", True), ("escape", True)]),
        ("world not saved yet", at_error(48), [("Close", True), ("escape", True)]),
        ("world changed", at_world_mismatch, [("Close", True), ("escape", True)]),
        ("password box", at_text_box("password"), [("dismiss,Cancel", False), ("dismiss,escape", False)]),
        ("room box", at_text_box("room"), [("dismiss,Cancel", False), ("dismiss,escape", False)]),
        ("address box", at_text_box("ip"), [("dismiss,Cancel", False), ("dismiss,escape", False)]),
        ("host password box", at_text_box("host_pass"), [("dismiss,escape", False), ("dismiss,Back,Cancel", False)]),
    ]
    walked = 0
    for name, reach, leaves in screens:
        for leave, stopped in leaves:
            env = make()
            env.rt.update()
            label = f"{name} / {leave}"
            reach(env)
            for step in leave.split(","):
                if step == "escape":
                    env.top().close()                       # the game's own Escape / click outside: no button callback runs
                elif step == "dismiss":
                    env.dismiss_input()
                    env.frames(60)                          # back to the screen before the text box
                    assert env.open_screens(), (label, "no screen after closing the text box")
                else:
                    env.tap(step)
                env.frames(30)
            check_fresh(env, label, stopped)
            walked += 1
    # a 'Try again' that is cancelled afterwards, and the same screen reached twice in one game
    env = make()
    at_error(21)(env)
    env.tap("Try again")
    env.frames(30)
    assert env.top().kind == "input"
    env.dismiss_input()
    env.frames(60)
    env.top().close()
    check_fresh(env, "password retry dismissed", False)
    for _ in range(3):                                      # host, cancel, host, cancel ... in the same game session
        env.launcher.script["host"] = [("hosting", 0, "host")]
        at_hosting(env)
        env.tap("Stop hosting")
        check_fresh(env, "repeated host", True)
        walked += 1
    print(f"PASS: menu: {walked + 1} ways out of every host / join screen (Cancel, Close, Back, Escape, a closed text box) leave nothing behind, "
          "stop the session where one was started, and New Game and Load Game work again")


def test_stuck_flags_heal_themselves():
    # The Escape key on the Singleplayer / Multiplayer question used to leave `choosing` set for good.
    env = make()
    sp_mp_question(env)
    env.top().close()
    assert env.interp.call("__mistrimulti_savespace")["choosing"] is True          # before any tick: the wrapper itself must cope
    env.new_game()
    assert env.screen_text()[0] == "Singleplayer or Multiplayer?", "New Game must work right after Escape"
    # a flag nobody owns (an exception somewhere): the tick clears it
    env = make()
    env.interp.call("__mistrimulti_savespace")["choosing"] = True
    env.frames(3)
    env.new_game()
    assert env.screen_text()[0] == "Singleplayer or Multiplayer?"
    # a flow whose popup the game closed: reset at once when New Game is pressed, before the tick noticed
    env = make()
    env.launcher.script["host"] = [("hosting", 0, "host")]
    at_hosting(env)
    env.top().close()
    env.new_game()
    assert env.screen_text()[0] == "Singleplayer or Multiplayer?" and env.interp.call("__mistrimulti_menu")["flow"] is None
    env.frames(30)
    assert env.launcher.cmds[-1]["cmd"] == "stop" and env.launcher.session == "none", "the session of the dead flow is stopped"
    # a flow with nothing on screen and nothing coming resets itself after three seconds
    env = make()
    env.begin()
    env.interp.call("__mistrimulti_menu")["flow"]["popup"] = None
    env.frames(5)                                                           # the savespace tick notices at once
    assert env.interp.call("__mistrimulti_menu")["flow"] is None and env.interp.call("__mistrimulti_savespace")["choosing"] is False
    env = make()                                                            # and the flow's own watchdog does when that flag is gone
    env.begin()
    env.interp.call("__mistrimulti_savespace")["choosing"] = False
    env.interp.call("__mistrimulti_menu")["flow"]["popup"] = None
    env.frames(150)
    assert env.interp.call("__mistrimulti_menu")["flow"] is not None
    env.frames(60)
    assert env.interp.call("__mistrimulti_menu")["flow"] is None and env.launcher.cmds[-1]["cmd"] == "stop"
    # beginning again while an old flow is still around closes its popups and stops its session
    env = make()
    env.launcher.script["host"] = [("hosting", 0, "host")]
    at_hosting(env)
    first = env.top()
    env.begin()
    env.frames(30)
    assert first.closed and env.screen_text()[0] == "Multiplayer" and env.launcher.cmds[-1]["cmd"] == "stop", env.launcher.cmds[-2:]
    # a session the launcher runs for another reason (an older launcher.cfg) is stopped by a Cancel on a screen that never started one
    env = make()
    env.launcher.state, env.launcher.session = "hosting", "host"
    env.launcher.publish()
    env.frames(70)
    env.begin()
    env.tap("Cancel")
    env.frames(30)
    assert env.launcher.cmds[-1]["cmd"] == "stop" and env.launcher.session == "none", env.launcher.cmds
    # a failing Singleplayer / Multiplayer popup never leaves the flag set; the game continues with its own New Game
    env = make()

    def boom(*a):
        raise gml.GmlError("popup failed")
    env.interp.builtins["MultipleChoicePopup"] = boom
    env.new_game()
    assert env.interp.call("__mistrimulti_savespace")["choosing"] is False and env.title_calls == [("enter_game", env.title_calls[0][1])]
    print("PASS: menu: a stale choosing flag, a flow whose popup was closed by the game and a flow with nothing on screen all heal; New Game works")


def test_mutation_probe_cancel():
    """The watchdog is what makes Escape work: with the dismissed-popup rule broken, the walk above must fail (see tests/mutate_joinflow.py)."""
    env = make()
    at_hosting(env)
    env.top().close()
    env.frames(5)
    assert env.interp.call("__mistrimulti_menu")["flow"] is None and env.launcher.cmds[-1]["cmd"] == "stop"
    print("PASS: menu: Escape on the hosting screen stops hosting at once")


# ---------------------------------------------------------------------------------------------------------------------------
# Real-game finding 2: the host started a new world without saving; the guest got the host's older save and ended up in the wrong world.

def test_world_check_before_entering():
    # matching worlds: enter. Not told (older launcher / host): enter as before.
    for hw, hf, dw in ((7, 3, 7), (0, 0, 9), (0, 0, 0), (9, 1, 0)):
        env = make()
        env.launcher.hw, env.launcher.hf, env.launcher.dw = hw, hf, dw
        env.launcher.hosts = hosts(("100.64.0.9", "DECK", 0))
        env.launcher.script["join"] = [("joining", 0, "join"), ("ready", 0, "join")]
        env.begin("new", "S")
        env.tap("Join a game")
        env.until(lambda: env.screen_text()[0].startswith("Join a game"))
        env.tap("DECK")
        env.until(lambda: env.entered)
        assert env.entered == [("new", "S")], (hw, hf, dw)
    # the world that arrived is not the world the host plays: not entered, the session is stopped, plain words, Try again joins again
    env = make()
    env.launcher.hw, env.launcher.hf, env.launcher.dw = 31337, 3, 7
    env.launcher.hosts = hosts(("100.64.0.9", "DECK", 0))
    env.launcher.script["join"] = [("joining", 0, "join"), ("ready", 0, "join")]
    env.begin("new", "S")
    env.tap("Join a game")
    env.until(lambda: env.screen_text()[0].startswith("Join a game"))
    env.tap("DECK")
    env.until(lambda: "different world" in env.screen_text()[1])
    assert not env.entered and env.launcher.session == "none", (env.entered, env.launcher.session)
    assert any("host plays world 31337" in t for k, t in env.logs)
    joins = len([c for c in env.launcher.cmds if c["cmd"] == "join"])
    env.launcher.hw, env.launcher.dw = 31337, 31337
    env.launcher.script["join"] = [("joining", 0, "join"), ("ready", 0, "join")]
    env.tap("Try again")
    env.until(lambda: env.entered)
    assert len([c for c in env.launcher.cmds if c["cmd"] == "join"]) == joins + 1
    assert [c for c in env.launcher.cmds if c["cmd"] == "join"][-1]["host"] == "100.64.0.9"
    # the host started a new world it has not saved: the launcher says 48; the words are exactly the ones asked for
    text = env.interp.call("mistrimulti_menu_error_text", 48)
    assert text == "The host has started a new world but has not saved it yet. Ask them to sleep or save once, then press Join again.", text
    env = make()
    env.launcher.hosts = hosts(("100.64.0.9", "DECK", 0))
    env.launcher.script["join"] = [("joining", 0, "join"), ("error", 48, "none")]
    env.begin("new", "S")
    env.tap("Join a game")
    env.until(lambda: env.screen_text()[0].startswith("Join a game"))
    env.tap("DECK")
    env.until(lambda: "not saved it yet" in env.screen_text()[1])
    assert labels(env) == ["Close", "Try again"] and not env.entered
    env.launcher.script["join"] = [("joining", 0, "join"), ("ready", 0, "join")]
    env.launcher.hw = env.launcher.dw = 5
    env.tap("Try again")
    env.until(lambda: env.entered)
    # the list says which hosts have a world that nobody can download yet
    env = make()
    env.launcher.hosts = hosts(("10.0.0.1", "SAVED", 12), ("10.0.0.2", "FRESH", 4), ("10.0.0.3", "OLD", 0), ("10.0.0.4", "PW", 6))
    env.begin()
    env.tap("Join a game")
    env.until(lambda: env.screen_text()[0].startswith("Join a game"))
    opts = labels(env)
    assert opts[:4] == ["SAVED  10.0.0.1", "FRESH  10.0.0.2  [new world, not saved]", "OLD  10.0.0.3", "PW  10.0.0.4  [password]  [new world, not saved]"], opts
    print("PASS: menu: a guest enters only when the downloaded world is the world the host plays; an unsaved host world and a world that "
          "changed are explained in plain words and can be retried")


def host_game(env, id=123456):
    """A host mod runtime with its world loaded (what MistriMultiBoot / PlayerSync leave behind)."""
    env.interp.builtins["Game"]["unique_identifier"] = id
    env.rt.update(enabled=True, mode="host", player_ready=True, world_key="host_uid_" + str(id), mask=1, peers=GArray([None] * 8))


def test_host_publishes_its_world():
    env = make()
    env.files.pop(f"{MOD}/menu/world.txt", None)
    env.rt.update(enabled=True, mode="host", player_ready=False, world_key="")
    env.frames(5)
    assert f"{MOD}/menu/world.txt" not in env.files, "nothing is published before the world is loaded"
    host_game(env, 123456)
    env.frames(2)
    assert env.files[f"{MOD}/menu/world.txt"] == "id=123456\n", env.files.get(f"{MOD}/menu/world.txt")
    assert f"{MOD}/menu/world.tmp" not in env.files, "written with a temporary file and renamed"
    # published once per world, not every frame
    writes = []
    real = env.save
    env.interp.builtins["save_text_file"] = lambda path, text: (writes.append(path), real(path, text))[1]
    env.frames(300)
    assert writes == [], writes
    # another world (the host went through the title screen and loaded or started another)
    env.interp.call("mistrimulti_menu_title_entered")
    host_game(env, 777)
    env.frames(2)
    assert env.files[f"{MOD}/menu/world.txt"] == "id=777\n"
    # a write that fails is retried, not forgotten
    env.interp.call("mistrimulti_menu_title_entered")
    host_game(env, 888)
    state = {"fail": True}

    def flaky(path, text):
        if state["fail"]:
            raise gml.GmlError("disk full")
        return real(path, text)
    env.interp.builtins["save_text_file"] = flaky
    env.frames(10)
    assert env.files[f"{MOD}/menu/world.txt"] == "id=777\n"
    state["fail"] = False
    env.frames(200)
    assert env.files[f"{MOD}/menu/world.txt"] == "id=888\n"
    # ids the launcher could not read are never published
    for bad in (0, -5, 2147483648, "12", None):
        env2 = make()
        host_game(env2, 5)
        env2.interp.builtins["Game"]["unique_identifier"] = bad
        env2.frames(5)
        assert f"{MOD}/menu/world.txt" not in env2.files, bad
    # a guest publishes nothing
    env3 = make()
    host_game(env3, 5)
    env3.rt["mode"] = "join"
    env3.frames(5)
    assert f"{MOD}/menu/world.txt" not in env3.files
    print("PASS: menu: a host tells its launcher which world it plays (once per world, retried when the write fails, never a bad id, never a guest)")


def test_guest_notices_another_world():
    env = make()
    env.interp.builtins["Game"]["unique_identifier"] = 7
    env.rt.update(enabled=True, mode="join", mask=1, peers=GArray([GStruct(world="hostuid_9", epoch="e")] + [None] * 7))
    env.frames(3)
    assert env.rt["world_mismatch"] is True, "the host plays world 9, this game loaded world 7"
    env.rt["peers"][0] = GStruct(world="hostuid_7", epoch="e")
    env.frames(3)
    assert env.rt["world_mismatch"] is False
    for peer in (GStruct(world="", epoch="e"), GStruct(world="nounderscore", epoch="e"), GStruct(world="x_12ab", epoch="e"), None):
        env.rt["peers"][0] = peer
        env.frames(3)
        assert env.rt["world_mismatch"] is False, peer                      # not told / not understood: no verdict
    env.rt["peers"][0] = GStruct(world="hostuid_9", epoch="e")
    env.rt["mask"] = 0                                                      # the host is not connected (yet)
    env.frames(3)
    assert env.rt["world_mismatch"] is False
    env.rt["mask"] = 1
    env.rt["enabled"] = False                                               # no session
    env.frames(3)
    assert env.rt["world_mismatch"] is False
    # an identity with underscores: the world id is what follows the LAST underscore
    assert env.interp.call("mistrimulti_world_key_id", "steam_76561_0123_4242") == "4242"
    assert env.interp.call("mistrimulti_world_key_id", "none") == "" and env.interp.call("mistrimulti_world_key_id", 5) == ""
    print("PASS: menu: a guest notices that the host plays another world than the downloaded one (and nothing else)")


class SaveWorld:
    """The parts of the game the early save of a new world touches."""

    def __init__(self, env):
        self.env = env
        self.fsm_state = "Default"
        self.saves, self.states, self.sequences = [], [], []
        self.open_popup = False
        self.save_fails = False
        self.running_scene = False
        self.at_home = True
        self.loading = False
        me = self
        fsm = GStruct(current_state_id=lambda: me.fsm_state, change_state=lambda s: (me.states.append(s), me.__setattr__("fsm_state", s))[0])
        b = env.interp.builtins
        b.update(ARI=GStruct(save_position=None), obj_ari=GStruct(fsm=fsm, x=10, y=20), CURRENT_LOCATION_ID=3,
                 PlayerState=GStruct(Default="Default", Dummy="Dummy"), FADE_SPEED_TRANSITION=30,
                 CLOCK=GStruct(time_stopped=True), MIST=GStruct(is_running=lambda: me.running_scene),
                 LOAD_SEQUENCE=GStruct(is_active=lambda: me.loading, start=lambda key, fn, args, fade: me.sequences.append((key, fn))),
                 LocationPosition=lambda loc, pos: GStruct(loc=loc, pos=pos), Vec2=lambda x, y: (x, y),
                 is_home_location=lambda loc: me.at_home,
                 exact_save_path=lambda ident, manual, other=None: f"saves/game-{ident}-autosave.sav", save_game=self.save)
        env.anchor.struct["popup_is_open"] = lambda: me.open_popup

    def save(self, path):
        if self.save_fails:
            raise gml.GmlError("save failed")
        self.saves.append(path)


def test_new_world_is_saved_early():
    env = make()
    w = SaveWorld(env)
    sp = env.interp.call("__mistrimulti_savespace")
    host_game(env, 4242)
    # a CONTINUED world is never touched
    env.frames(200)
    assert w.sequences == [] and w.saves == []
    # a new world: not while a scene, a popup, a loading screen or another room is in the way
    sp["new_world"] = True
    for blocker, set_it, clear_it in (("scene", lambda: setattr(w, "running_scene", True), lambda: setattr(w, "running_scene", False)),
                                      ("popup", lambda: setattr(w, "open_popup", True), lambda: setattr(w, "open_popup", False)),
                                      ("loading", lambda: setattr(w, "loading", True), lambda: setattr(w, "loading", False)),
                                      ("away from home", lambda: setattr(w, "at_home", False), lambda: setattr(w, "at_home", True)),
                                      ("not in control", lambda: setattr(w, "fsm_state", "Cutscene"), lambda: setattr(w, "fsm_state", "Default"))):
        set_it()
        env.frames(200)
        assert w.sequences == [], blocker
        clear_it()
    env.frames(70)
    assert len(w.sequences) == 1 and w.sequences[0][0] == "misc_local/saving", w.sequences
    assert w.states == ["Dummy"], "the player is held still while the game saves"
    env.frames(300)
    assert len(w.sequences) == 1, "one attempt only"
    # the game runs our function inside its loading sequence: it saves THE WORLD'S autosave file through save_game (so every guard runs)
    env.interp.call_value(w.sequences[0][1], [], 0)
    assert w.saves == ["saves/game-4242-autosave.sav"], w.saves
    assert w.states == ["Dummy", "Default"] and env.notes[-1] == "MistriaMulti: your new world is saved. Friends can join now."
    assert env.interp.builtins["ARI"]["save_position"] is not None
    env.frames(400)
    assert len(w.sequences) == 1 and len(w.saves) == 1, "the player is in control again: still only one save"
    # a save that throws still finishes the loading sequence (the screen must not stay black) and tells the host the truth
    env2 = make()
    w2 = SaveWorld(env2)
    w2.save_fails = True
    env2.interp.call("__mistrimulti_savespace")["new_world"] = True
    host_game(env2, 55)
    env2.frames(80)
    result = env2.interp.call_value(w2.sequences[0][1], [], 0)
    assert result is True and w2.states[-1] == "Default" and "could not be saved" in env2.notes[-1], (result, env2.notes)
    # nothing is saved before the launcher knows the world (a guest could not download it yet), and never for a guest
    env3 = make()
    w3 = SaveWorld(env3)
    env3.interp.call("__mistrimulti_savespace")["new_world"] = True
    host_game(env3, 66)
    env3.interp.builtins["save_text_file"] = lambda p, t: (_ for _ in ()).throw(gml.GmlError("no disk"))
    env3.frames(200)
    assert w3.sequences == [], "the world note comes first"
    env3.rt["mode"] = "join"
    env3.frames(200)
    assert w3.sequences == []
    # still not saved after two minutes (the player is busy): the host is told once, in plain words
    env4 = make()
    w4 = SaveWorld(env4)
    w4.running_scene = True
    env4.interp.call("__mistrimulti_savespace")["new_world"] = True
    host_game(env4, 77)
    env4.frames(60 * 100)
    assert env4.notes == [], "not before two minutes"
    env4.frames(60 * 40)
    assert len(env4.notes) == 1 and "not saved yet" in env4.notes[0] and "Sleep or save" in env4.notes[0], env4.notes
    env4.frames(60 * 60)
    assert len(env4.notes) == 1
    print("PASS: menu: a NEW host world is saved once, as soon as the player is in control at home, through the game's own save; the host is told "
          "in plain words; a continued world, a guest or a busy player is left alone")


def test_only_a_new_world_is_marked():
    env = make()
    env.interp.functions["mistrimulti_world_options_default"] = lambda: GStruct(hearts="own")
    env.interp.functions["mistrimulti_world_options_pending"] = lambda *a: GStruct(hearts="own")
    sp = env.interp.call("__mistrimulti_savespace")
    env.interp.functions["mistrimulti_savespace_newest_world"] = lambda: GStruct(path="old")
    env.interp.builtins["LoadState"] = GStruct(Load=lambda w: ("load", w["path"]))
    env.interp.call("mistrimulti_savespace_host_choice", True, "STATE")             # Continue world
    assert sp["new_world"] is False and env.title_calls == [("enter_game", ("load", "old"))], (sp["new_world"], env.title_calls)
    env.interp.call("mistrimulti_world_options_hearts", "own", "STATE")             # New world: the hearts question was answered
    assert sp["new_world"] is True and env.title_calls[-1] == ("enter_game", "STATE")
    print("PASS: menu: only a NEW host world is marked for the early save; Continue world is not")


def test_title_entered_forgets_the_world_state():
    env = make()
    w = SaveWorld(env)
    env.interp.call("__mistrimulti_savespace")["new_world"] = True
    host_game(env, 1)
    env.frames(80)
    assert len(w.sequences) == 1
    sp = env.interp.call("__mistrimulti_savespace")
    sp["choosing"] = True
    env.interp.call("mistrimulti_title_entered", GStruct())
    assert sp["new_world"] is False and sp["choosing"] is False
    m = env.interp.call("__mistrimulti_menu")
    assert m["published"] == "" and m["save_tried"] is False
    print("PASS: menu: the title screen clears the published-world and early-save state")


# ---------------------------------------------------------------------------------------------------------------------------
# End to end: the GML menu against the real launcher + helper, joining a real host (a second launcher), Linux binaries.
def e2e(launcher, helper, fake):
    import tempfile
    import shutil
    import subprocess

    def sandbox():
        root = Path(tempfile.mkdtemp(prefix="menutest-"))
        for d in ("bin", "game", "home"):
            (root / d).mkdir()
        shutil.copy(launcher, root / "bin" / "mistrimulti-launcher")
        shutil.copy(helper, root / "bin" / "mistrimulti-helper-linux")
        shutil.copy(fake, root / "game" / "FieldsOfMistria")
        for f in list((root / "bin").iterdir()) + list((root / "game").iterdir()):
            f.chmod(0o755)
        mod = root / "data" / "mod_data" / "mistrimulti"
        (root / "data" / "saves").mkdir(parents=True)
        mod.mkdir(parents=True)
        return root, mod

    def start(root, extra_env=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "STEAM_", "MISTRIMULTI_", "MM_"))}
        env.update(HOME=str(root / "home"), MISTRIMULTI_DATA_DIR=str(root / "data"))
        env.update(extra_env or {})
        return subprocess.Popen([str(root / "bin" / "mistrimulti-launcher"), "--steam", str(root / "game" / "FieldsOfMistria"), "--slow"],
                                cwd=root / "game", env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    host_root, host_mod = sandbox()
    guest_root, guest_mod = sandbox()
    (host_root / "data" / "multiplayer" / "saves").mkdir(parents=True)
    (host_root / "data" / "multiplayer" / "saves" / "game-7-autosave.sav").write_bytes(b"THE HOSTS WORLD" * 400)
    procs = []
    try:
        procs.append(start(host_root))
        procs.append(start(guest_root, {"MISTRIMULTI_SCAN_EXTRA": "127.0.0.1"}))
        for mod in (host_mod, guest_mod):
            end = time.monotonic() + 15
            while not (mod / "menu" / "status.json").exists() and time.monotonic() < end:
                time.sleep(0.1)
            assert (mod / "menu" / "status.json").exists(), "launcher did not publish a status"
        # The host's player uses the menu to host (with a password)
        h = Env(disk=host_mod)
        h.begin("new", "S")
        h.tap("Host a game")
        h.frames(20)
        h.tap("Set a password")
        h.frames(20)
        h.type("tops3cret")
        h.frames(20)
        h.tap("Start hosting")
        assert h.wait_for(lambda: h.screen_text()[0] == "You are hosting", 20), "host screen never appeared"
        h.tap("Start playing")
        h.frames(5)
        assert h.entered == [("new", "S")]
        assert json.loads((host_mod / "control.json").read_text())["mode"] == "host"
        # The friend joins from the menu: scan, pick, password, world download
        g = Env(disk=guest_mod)
        g.begin("new", "G")
        g.tap("Join a game")
        assert g.wait_for(lambda: g.screen_text()[0].startswith("Join a game"), 30), "no host list"
        title, _, opts = g.screen_text()
        assert title == "Join a game: pick a host" and "[password]" in opts[0] and "127.0.0.1" in opts[0], (title, opts)
        g.tap("127.0.0.1")
        g.frames(20)
        assert g.top().kind == "input"
        g.type("not-the-password")
        assert g.wait_for(lambda: "Wrong password" in g.screen_text()[1], 40), "no wrong-password message"
        g.tap("Try again")
        g.frames(20)
        g.type("tops3cret")
        g.wait_for(lambda: bool(g.entered), 40)
        assert g.entered == [("new", "G")], (g.entered, g.screen_text() if g.open_screens() else "")
        world = guest_root / "data" / "multiplayer" / "saves" / "game-7-autosave.sav"
        assert world.read_bytes() == b"THE HOSTS WORLD" * 400, "world not downloaded"
        ctl = json.loads((guest_mod / "control.json").read_text())
        assert ctl["enabled"] is True and ctl["mode"] == "join" and 1 <= ctl["id"] <= 7, ctl
        # leaving to the title screen stops the guest's helper session
        g.frames(70)
        g.interp.call("mistrimulti_menu_title_entered")
        g.frames(20)
        end = time.monotonic() + 15
        while time.monotonic() < end and json.loads((guest_mod / "control.json").read_text())["enabled"]:
            g.frames(1); time.sleep(0.05)
        assert json.loads((guest_mod / "control.json").read_text())["enabled"] is False
        # and the badge of the host reads Online while its helper runs
        h.interp.call("mistrimulti_netstatus_refresh")
        h.frames(1)
        time.sleep(1.2)
        h.interp.call("mistrimulti_netstatus_refresh")
        h.us = h.get_timer()
        text = h.interp.call("mistrimulti_status_text")["text"]
        assert text.startswith("Multiplayer: Online"), text
        print("PASS: menu end to end: the GML menu hosts with a password, a second player scans, is refused with a wrong password, "
              "joins with the right one, downloads the world and leaves; the real launcher, helper and badge agree")
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.communicate(timeout=30)
            except Exception:
                p.kill()
        shutil.rmtree(host_root, ignore_errors=True)
        shutil.rmtree(guest_root, ignore_errors=True)


def e2e_world(launcher, helper, fake):
    """The GML host mod publishes the world it plays; the REAL launcher serves that world (not the newest save) and refuses to hand over
    anything for a world that was never saved; the GML guest menu enters only on a match. Linux binaries, a real host and guest launcher."""
    import tempfile
    import shutil
    import subprocess

    def sandbox():
        root = Path(tempfile.mkdtemp(prefix="menuworld-"))
        for d in ("bin", "game", "home"):
            (root / d).mkdir()
        shutil.copy(launcher, root / "bin" / "mistrimulti-launcher")
        shutil.copy(helper, root / "bin" / "mistrimulti-helper-linux")
        (root / "game" / "FieldsOfMistria").write_text("#!/bin/sh\nsleep 120\n")
        for f in list((root / "bin").iterdir()) + list((root / "game").iterdir()):
            f.chmod(0o755)
        mod = root / "data" / "mod_data" / "mistrimulti"
        (root / "data" / "saves").mkdir(parents=True)
        mod.mkdir(parents=True)
        return root, mod

    def start(root, extra_env=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "STEAM_", "MISTRIMULTI_", "MM_"))}
        env.update(HOME=str(root / "home"), MISTRIMULTI_DATA_DIR=str(root / "data"))
        env.update(extra_env or {})
        return subprocess.Popen([str(root / "bin" / "mistrimulti-launcher"), "--steam", str(root / "game" / "FieldsOfMistria")],
                                cwd=root / "game", env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    host_root, host_mod = sandbox()
    guest_root, guest_mod = sandbox()
    saves = host_root / "data" / "multiplayer" / "saves"
    saves.mkdir(parents=True)
    (saves / "game-7-autosave.sav").write_bytes(b"WORLD SEVEN " * 300)
    (saves / "game-8-autosave.sav").write_bytes(b"WORLD EIGHT " * 300)
    os.utime(saves / "game-7-autosave.sav", (1_700_000_000, 1_700_000_000))
    os.utime(saves / "game-8-autosave.sav", (1_700_000_900, 1_700_000_900))
    procs = []
    try:
        procs.append(start(host_root))
        procs.append(start(guest_root, {"MISTRIMULTI_SCAN_EXTRA": "127.0.0.1"}))
        for mod in (host_mod, guest_mod):
            end = time.monotonic() + 15
            while not (mod / "menu" / "status.json").exists() and time.monotonic() < end:
                time.sleep(0.1)
            assert (mod / "menu" / "status.json").exists(), "launcher did not publish a status"
        h = Env(disk=host_mod)
        h.begin("new", "S")
        h.tap("Host a game")
        h.frames(20)
        h.tap("Start hosting")
        assert h.wait_for(lambda: h.screen_text()[0] == "You are hosting", 20), "host screen never appeared"
        h.tap("Start playing")
        h.frames(5)
        host_game(h, 7)                                         # the host's world is loaded: world 7 (not the newest save)
        assert h.wait_for(lambda: (host_mod / "menu" / "world.txt").exists(), 5), "the host mod did not publish its world"
        assert (host_mod / "menu" / "world.txt").read_text() == "id=7\n"

        def join(env_guest, saved=True):
            env_guest.begin("new", "G")
            env_guest.tap("Join a game")
            assert env_guest.wait_for(lambda: env_guest.screen_text()[0].startswith("Join a game"), 30), "no host list"
            title, _, opts = env_guest.screen_text()
            assert title == "Join a game: pick a host" and ("[new world" not in opts[0]) == saved, (title, opts)
            env_guest.tap("127.0.0.1")
            env_guest.wait_for(lambda: bool(env_guest.entered) or "Try again" in str(env_guest.screen_text()[2]), 40)

        g = Env(disk=guest_mod)
        join(g)
        assert g.entered == [("new", "G")], (g.entered, g.screen_text() if g.open_screens() else "")
        saved = guest_root / "data" / "multiplayer" / "saves"
        assert (saved / "game-7-autosave.sav").read_bytes() == b"WORLD SEVEN " * 300 and not (saved / "game-8-autosave.sav").exists(), \
            "the guest must get the world the host plays, not the newest save"
        g.interp.call("mistrimulti_menu_title_entered")
        g.frames(30)
        time.sleep(2)
        # the host starts a new world it has not saved
        host_game(h, 99)
        assert h.wait_for(lambda: (host_mod / "menu" / "world.txt").read_text() == "id=99\n", 5)
        g2 = Env(disk=guest_mod)
        end = time.monotonic() + 40
        while time.monotonic() < end:                           # the host may still count the previous session for a few seconds
            g2.screens.clear()
            join(g2, saved=False)
            if g2.open_screens() and "not saved it yet" in g2.screen_text()[1]:
                break
            if g2.open_screens() and "already in use" in g2.screen_text()[1]:
                g2.tap("Close")
                time.sleep(2)
        assert not g2.entered and g2.open_screens(), g2.entered
        body = g2.screen_text()[1]
        assert body == "The host has started a new world but has not saved it yet. Ask them to sleep or save once, then press Join again.", body
        assert not (saved / "game-99-autosave.sav").exists()
        # the host saves it (the early save); Try again enters
        (saves / "game-99-autosave.sav").write_bytes(b"BRAND NEW WORLD " * 100)
        for _ in range(12):                                     # "slot in use" while the host still counts an earlier session: ask again
            if g2.entered:
                break
            if g2.open_screens() and g2.screen_text()[0].startswith("Join a game"):
                g2.tap("127.0.0.1")
            elif g2.open_screens() and "Try again" in g2.screen_text()[2]:
                g2.tap("Try again")
            g2.wait_for(lambda: bool(g2.entered) or (g2.open_screens() and ("Try again" in g2.screen_text()[2] or g2.screen_text()[0].startswith("Join a game"))), 40)
            time.sleep(1.5)
        assert g2.entered == [("new", "G")], (g2.entered, g2.screen_text() if g2.open_screens() else "")
        assert (saved / "game-99-autosave.sav").read_bytes() == b"BRAND NEW WORLD " * 100
        print("PASS: menu end to end (world): the host mod names its world, the real launcher serves that world and not the newest save, "
              "an unsaved new world is refused with the plain words, and the guest enters once the host has saved it")
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.communicate(timeout=30)
            except Exception:
                p.kill()
        shutil.rmtree(host_root, ignore_errors=True)
        shutil.rmtree(guest_root, ignore_errors=True)


ALL = [test_unavailable_launcher, test_host_flow, test_host_password_and_cancel, test_join_flow, test_join_password_and_room,
       test_typed_address_and_errors, test_cancel_and_timeouts, test_commands_are_queued_in_order, test_refresh_and_scan_failure, test_hostile_status_file,
       test_title_entered_stops_sessions, test_texts_and_keys, test_failure_never_reaches_the_game, test_badge,
       test_badge_in_world, test_badge_on_screen_is_robust, test_every_cancel_path_resets_and_can_restart, test_stuck_flags_heal_themselves,
       test_mutation_probe_cancel, test_world_check_before_entering, test_host_publishes_its_world, test_guest_notices_another_world,
       test_new_world_is_saved_early, test_only_a_new_world_is_marked, test_title_entered_forgets_the_world_state]

if __name__ == "__main__":
    only = [n for n in os.environ.get("ONLY", "").split(",") if n]
    for fn in ALL:
        if not only or fn.__name__ in only:
            fn()
    if len(sys.argv) >= 4 and (not only or "e2e" in only):
        e2e(*(Path(a).resolve() for a in sys.argv[1:4]))
    if len(sys.argv) >= 4 and (not only or "e2e_world" in only):
        e2e_world(*(Path(a).resolve() for a in sys.argv[1:4]))
    print("PASS")
