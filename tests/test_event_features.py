"""The migrated features (farm terrain, player records) on the event layer, running their real GML.

    python3 tests/test_event_features.py

MistriMultiTerrain.gml, MistriMultiPlayerSync.gml, MistriMultiIdentity.gml and MistriMultiProgress.gml run unmodified in
tests/gml_subset.py on top of MistriMultiEvents.gml, over the simulated helpers and network of
tests/event_sim.py. Only the engine is stubbed: a small farm grid, and the player-record storage and
validation functions of MistriMultiPlayerData.gml (which need the real game). This checks the handler
wiring, the request/result flow and the record transfer; it does not replace testing in the game.

MistriMultiClock.gml runs the same way (ClockNode): the game's clock, bed, pass-out and end-of-day flow are
simulated frame by frame (see docs/SYNC-CLOCK.md).
"""
import json

from event_sim import GmlNode, World
import gml_subset as gml

DIRT, SOIL, GROUND = 1, 2, 1
SIZE = 40


class Grid:
    """The fields and methods of the game's farm grid that MistriMultiTerrain.gml uses."""

    def __init__(self):
        cells = SIZE * SIZE
        self.struct = gml.GStruct(
            dims=gml.GStruct(x=SIZE, y=SIZE), is_setup=False,
            node_terrain_kind=gml.GArray([GROUND] * cells),
            node_terrain_ground_kind=gml.GArray([DIRT] * cells),
            node_terrain_is_watered=gml.GArray([False] * cells),
            node_object_id=gml.GArray([None] * cells),
            node_index_for_cell=lambda x, y: int(y) * SIZE + int(x),
            write_ground=self.write_ground, update_tilemap_for_node=lambda x, y: None)

    def write_ground(self, x, y, g):
        self.struct["node_terrain_ground_kind"][int(y) * SIZE + int(x)] = g

    def water(self, grid, x, y, wet):
        grid["node_terrain_is_watered"][int(y) * SIZE + int(x)] = bool(wet)

    def tile(self, x, y):
        i = y * SIZE + x
        return (self.struct["node_terrain_ground_kind"][i], self.struct["node_terrain_is_watered"][i])


class FeatureNode(GmlNode):
    extra_files = ("MistriMultiTerrain.gml", "MistriMultiPlayerSync.gml", "MistriMultiIdentity.gml", "MistriMultiProgress.gml")

    def builtins(self):
        self.grid = Grid()
        self.store = {}            # uid -> {"revision", "data"} (host's player records)
        self.calls = []
        mist = gml.GStruct(is_running=lambda: False)
        return {
            "GRIDS": gml.GArray([self.grid.struct]), "LocationId": gml.GStruct(Farm=0),
            "TerrainKind": gml.GStruct(Ground=GROUND), "GroundKind": gml.GStruct(Dirt=DIRT, Soil=SOIL),
            "CURRENT_LOCATION_ID": 0, "water_chunk": self.grid.water,
            "location_id_to_string": lambda i: "farm", "point_distance": lambda a, b, c, d: ((a - c) ** 2 + (b - d) ** 2) ** 0.5,
            "string_replace_all": lambda s, a, b: s.replace(a, b), "file_exists": lambda path: False,
            "MIST": mist, "ARI": gml.GStruct(name="test"),
            "mistrimulti_player_load": lambda uid: gml.from_json(self.store[uid]) if uid in self.store else None,
            "mistrimulti_player_path": lambda uid: "players/" + uid,
            "mistrimulti_player_valid": lambda data, uid, world: isinstance(data, dict) and data.get("uid") == uid
                and data.get("world") == world,
            "mistrimulti_player_store": self.player_store,
            "mistrimulti_player_restore": lambda data: self.calls.append(("restore", json.loads(gml.to_json(data)))) or True,
            "mistrimulti_player_capture": lambda: gml.GStruct(captured=True),
            "mistrimulti_player_fresh": self.player_fresh,
        }

    def player_store(self, uid, revision, data):
        self.store[uid] = {"revision": revision, "data": json.loads(gml.to_json(data))}
        return True

    def player_fresh(self):
        self.calls.append(("fresh",))
        self.rt["player_ready"] = True

    def setup(self):
        self.rt.update(uid=f"local:{self.slot:032x}", dirty_world=False, apply_depth=0, snapshot_pending=False,
                       terrain_cursor=-1, world_key="world_1", player_ready=self.slot == 0, player_revision=0,
                       player_saved_revision=0, player_signature="", player_error="", player_request="",
                       player_sessions=gml.GArray([None] * 8), warning="")
        self.interp.call("mistrimulti_progress_initialize")


class Driver:
    """What MistriMultiBoot.gml's tick does for these features, plus the peer fields features validate."""

    def __init__(self, game, room="farm:undefined", x=80, y=80):
        self.game, self.node = game, game.node
        self.room, self.x, self.y = room, x, y
        self.node.interp.call("mistrimulti_terrain_register_events")
        self.node.interp.call("mistrimulti_player_register_events")

    def frame(self):
        rt = self.node.rt
        return {"epoch": rt["epoch"], "uid": rt["uid"], "world": rt["world_key"], "room": self.room,
                "x": self.x, "y": self.y}

    def tick(self, now):
        if self.node.rt["mode"] == "host":
            self.node.interp.call("mistrimulti_stream_terrain")


def make_world(seed, guests=2, **faults):
    world = World(seed, {i: FeatureNode for i in range(guests + 1)}, **faults)
    for game in world.games.values():
        game.feature = Driver(game)
    return world


def request(node, data):
    return node.call("mistrimulti_event_request", "terrain", data)


def test_terrain():
    world = make_world(21, loss=0.05, jitter=40)
    host, guest, other = (world.games[i].node for i in range(3))
    world.run(4000)
    # Host commits reach every guest; the snapshot sent when a game joins covers earlier changes.
    host.grid.write_ground(4, 4, SOIL)
    host.grid.water(host.grid.struct, 4, 4, True)
    host.call("mistrimulti_event_emit", "terrain_commit", {"tiles": [{"x": 4, "y": 4, "g": SOIL, "w": True}]})
    world.run(3000)
    assert guest.grid.tile(4, 4) == (SOIL, True) and other.grid.tile(4, 4) == (SOIL, True)
    # A guest's hoe: a request the host validates and applies once; every guest applies the result.
    dirt = {"x": 10, "y": 10, "g": DIRT, "w": False}
    soil = dict(dirt, g=SOIL)
    rid = request(guest, {"tiles": [soil], "before": dirt})
    assert rid is not None
    world.run(3000)
    assert host.grid.tile(10, 10) == (SOIL, False) and other.grid.tile(10, 10) == (SOIL, False)
    # A conflicting prediction is corrected to the host's state; an out-of-reach request changes nothing.
    request(other, {"tiles": [dict(dirt, w=True)], "before": dirt})
    far = {"x": 30, "y": 30, "g": DIRT, "w": False}
    world.games[2].feature.x = -5000
    request(other, {"tiles": [dict(far, g=SOIL)], "before": far})
    # A guest cannot commit for the host.
    other.call("mistrimulti_event_emit", "terrain_commit", {"tiles": [dict(far, g=SOIL)]})
    world.run(3000)
    assert host.grid.tile(10, 10) == (SOIL, False) and other.grid.tile(10, 10) == (SOIL, False)
    assert host.grid.tile(30, 30) == (DIRT, False) and guest.grid.tile(30, 30) == (DIRT, False)
    # A guest that re-enters its world gets a fresh snapshot of the host's farm.
    guest.grid.write_ground(4, 4, DIRT)
    guest.call("mistrimulti_events_reset")
    world.run(6000)
    assert guest.grid.tile(4, 4) == (SOIL, True), "no snapshot after re-entering"
    for game in world.games.values():
        debug = game.node.call("mistrimulti_events_debug")
        assert debug["errors"] == 0 and debug["backlog"] == 0, (game.slot, debug, game.warnings[:3])
    print("PASS: terrain: host commits, guest requests applied once by the host, conflicts corrected, "
          "out-of-reach and guest commits rejected, snapshot on (re)join")


def test_player_records():
    world = make_world(22, loss=0.05, jitter=40)
    host, guest, other = (world.games[i].node for i in range(3))
    world.run(4000)
    uid = guest.rt["uid"]
    # A new player: the host has no record, so the guest starts fresh.
    assert guest.call("mistrimulti_event_emit", "profile_request", {"world": "world_1", "uid": uid}, 0)
    world.run(3000)
    assert guest.calls == [("fresh",)] and guest.rt["player_error"] == "", guest.rt["player_error"]
    # An exact multi-chunk record upload, stored once and confirmed.
    profile = {"v": 1, "uid": uid, "world": "world_1", "inventory": ["item 日本 " + "x" * 90] * 600}
    guest.rt["player_revision"] = 1
    assert guest.interp.call("mistrimulti_player_send", "profile_update", 0, guest.rt["epoch"], 1, guest.data(profile))
    world.run(8000)
    assert host.store[uid] == {"revision": 1, "data": profile}
    assert guest.rt["player_saved_revision"] == 1
    # The same identity in another slot is refused while the first is connected.
    other.rt["uid"] = uid
    world.run(1500)
    other.call("mistrimulti_event_emit", "profile_request", {"world": "world_1", "uid": uid}, 0)
    world.run(3000)
    assert other.rt["player_error"] == "This player identity is already connected.", other.rt["player_error"]
    # Re-entering the world: the host sends the saved record back, and the guest restores it.
    guest.interp.call("mistrimulti_player_reset_session")
    guest.rt["player_request"] = ""
    world.run(2000)
    guest.call("mistrimulti_event_emit", "profile_request", {"world": "world_1", "uid": uid}, 0)
    world.run(8000)
    assert ("restore", profile) in guest.calls and guest.rt["player_revision"] == 1, guest.calls[-1:]
    # A revision that skips ahead is ignored; nothing replaces the saved record.
    guest.interp.call("mistrimulti_player_send", "profile_update", 0, guest.rt["epoch"], 5, guest.data(dict(profile, x=1)))
    world.run(5000)
    assert host.store[uid]["revision"] == 1
    for game in world.games.values():
        debug = game.node.call("mistrimulti_events_debug")
        assert debug["errors"] == 0 and debug["backlog"] == 0 and debug["blobs"] == 0, (game.slot, debug, game.warnings)
    print("PASS: player records: fresh start, exact multi-chunk upload stored and confirmed, duplicate identity "
          "refused, record restored after re-entry, out-of-order revision ignored")


# ---- clock, weather and the all-player sleep vote (MistriMultiClock.gml) ----------------------------------

HOUR = 3600
DAWN, LAST = 6 * HOUR, 26 * HOUR
EOD_MENU = 7
BED = {"object_id": 1, "prototype": {"bed_kind": 0}, "top_left_x": 4, "top_left_y": 4}


class Popup:
    """The PopupMenu calls the clock file makes: create_button, spawn, close, close_callback."""

    def __init__(self, node, title):
        self.node, self.title, self.buttons, self.open = node, title, [], False
        self.struct = gml.GStruct(create_button=self.create_button, spawn=self.spawn, close=self.close,
                                  close_callback=None)

    def create_button(self, label, callback=None, args=None):
        self.buttons.append((label, callback, args))

    def spawn(self):
        self.open = True
        self.node.popups.append(self)

    def close(self):
        if not self.open:
            return
        self.open = False
        self.node.popups.remove(self)
        if self.struct["close_callback"] is not None:
            self.node.interp.call_value(self.struct["close_callback"], [], 0)

    def tap(self, label):
        for name, callback, args in self.buttons:
            if name == label:
                self.close()                     # the game closes a popup before running the button
                if callback is not None:
                    self.node.interp.call_value(callback, list(args or []), 0)
                return
        raise AssertionError(f"no button {label} on {self.title}")


class ClockNode(GmlNode):
    """MistriMultiClock.gml with the game's clock, calendar, weather, bed, pass-out and end-of-day flow stubbed.

    The end of day follows the game: end_day() -> (end-of-day menu) -> the player taps Next Day after
    `next_day_delay` ms -> menu.end_sequence() -> new_day() (calendar +1, a new Clock at 6 am, the host saves)
    -> wake up 300 ms later.
    """
    extra_files = ("MistriMultiClock.gml",)

    def builtins(self):
        self.minutes = 5                     # real minutes per game day (the game's default is 15)
        self.day = 0                         # days since the start; total_days() = day + 1
        self.menu_open = False               # a pausing menu (inventory...)
        self.popups, self.actions, self.new_days, self.notes, self.scenes, self.jumps = [], [], [], [], [], []
        self.saves, self.passouts, self.now, self.next_day_delay = 0, 0, 0, 400
        self.eod, self.ending, self.mist = None, False, False
        self.history = []                    # (day, time) after every frame
        self.ari = gml.GStruct(name="test", end_of_day_status=None, end_of_day_sequence=False,
                               used_object_today=gml.GArray([False] * 8), last_bed_used=None)
        self.weather = gml.GStruct(forecast=gml.GArray([0] * 28), weather=0, under_spell=False,
                                   set_weather=self.set_weather)
        self.clock = self.new_clock(DAWN)
        no = lambda *a: None
        return {
            "ARI": self.ari, "CLOCK": self.clock, "WEATHER": self.weather, "Weather": gml.GStruct(LEN=4),
            "CALENDAR": gml.GStruct(day=lambda: self.day % 28), "total_days": lambda: self.day + 1,
            "MINUTES_PER_DAY": self.minutes,
            "game_paused": self.paused, "instance_exists": lambda o: True, "obj_ari": "obj_ari",
            "par_NPC": "par_NPC", "instance_number": lambda o: 0, "instance_find": no, "npc_id_to_string": str,
            "MIST": gml.GStruct(is_running=lambda: self.mist, request_scene=self.request_scene,
                                blackboard=gml.GStruct(insert=no)),
            "ANCHOR": gml.GStruct(popup_is_open=lambda: bool(self.popups),
                                  get_menu=lambda kind: self.eod if kind == EOD_MENU else None),
            "Menu": gml.GStruct(Eod=EOD_MENU), "EndOfDayStatus": gml.GStruct(Normal=0, Fainted=1),
            "popup_creator": lambda title, body: Popup(self, title).struct,
            "end_day": lambda *a: self.end_day(), "create_notification": self.notes.append,
            "ObjectCategory": gml.GStruct(Furniture=2), "object_id_to_object_category": lambda oid: 2,
            "Requirement": gml.GStruct(Sleep=1), "requirements_pass": lambda req: True,
            "is_home_location": lambda loc: True, "CURRENT_LOCATION_ID": 0,
            "TAXI": gml.GStruct(is_traveling=lambda: False), "T2R": gml.GStruct(write=no),
            "GRID": gml.GStruct(node_index_for_cell=lambda x, y: 0),
        }

    def setup(self):
        self.rt.update(enabled=True, clock=None, snapshot_pending=False)

    # -- the game ------------------------------------------------------------------------------------------
    def gspf(self):
        return 86400 / (self.minutes * 60 * 60)

    def configure(self, day=0, time=DAWN, minutes=5):
        self.day, self.minutes = day, minutes
        self.interp.builtins.update(MINUTES_PER_DAY=minutes)
        self.set_clock(time)
        self.clock["time_stopped"] = False

    def new_clock(self, time):
        return gml.GStruct(time=time, time_stopped=False, side_buffer=0.0, jump=self.jump)

    def set_clock(self, time):
        self.clock = self.new_clock(time)
        if hasattr(self, "interp"):
            self.interp.builtins["CLOCK"] = self.clock

    def jump(self, time):
        if time < self.clock["time"]:
            return
        self.jumps.append((self.clock["time"], min(time, LAST)))
        self.clock["time"] = min(time, LAST)

    def set_weather(self, weather, atmosphere=None):
        self.weather["weather"] = weather

    def paused(self):
        return bool(self.popups) or self.menu_open or self.mist

    def later(self, ms, fn):
        self.actions.append((self.now + ms, fn))

    def request_scene(self, scene):
        self.scenes.append(scene)
        self.mist = True

        def scene_done():
            self.mist = False
            if self.ari["end_of_day_status"] is None:
                self.ari["end_of_day_status"] = 0
            self.end_day()
        self.later(300, scene_done)

    def end_day(self):
        assert not self.ending, "end_day twice in one day"
        self.ending = True
        self.later(200, self.open_eod)

    def pass_out(self):
        self.passouts += 1
        self.ari["end_of_day_status"] = 1
        self.end_day()
        self.call("mistrimulti_clock_pass_out", {"faint": True})

    def open_eod(self):
        self.eod = gml.GStruct(end_sequence=self.end_sequence)
        self.call("mistrimulti_clock_menu_opened", gml.GStruct(menu=self.eod, kind=EOD_MENU))
        self.clock["time_stopped"] = True
        self.ari["end_of_day_sequence"] = True
        self.later(self.next_day_delay, lambda: self.interp.call_value(self.eod["end_sequence"], [], 0))

    def end_sequence(self):
        assert self.eod is not None and self.ending
        self.day += 1
        self.new_days.append(self.day + 1)
        self.set_clock(DAWN)
        self.clock["time_stopped"] = True
        self.weather["weather"] = self.weather["forecast"][self.day % 28]
        self.call("mistrimulti_clock_new_day", {"total_days": self.day + 1})
        if self.slot == 0:
            self.saves += 1                   # guests' saves are vetoed by mistrimulti_save_guard
        self.later(300, self.wake)

    def wake(self):
        self.eod, self.ending = None, False
        self.ari["end_of_day_sequence"] = False
        self.ari["end_of_day_status"] = None
        self.clock["time_stopped"] = False

    def step_frame(self):
        self.call("mistrimulti_clock_frame", self.clock)
        clock = self.clock
        natural = 0 if self.paused() or clock["time_stopped"] else self.gspf()
        out = self.call("mistrimulti_clock_time_advance", natural, clock)
        advance = natural if out is None else out
        assert advance >= 0 and advance <= 2 * self.gspf() * 3 + 1e-9, advance
        clock["side_buffer"] += advance
        if clock["side_buffer"] >= 1:
            clock["time"] += int(clock["side_buffer"])
            clock["side_buffer"] -= int(clock["side_buffer"])
        if clock["time"] >= LAST and self.ari["end_of_day_status"] is None and not self.paused() \
                and not clock["time_stopped"] and not self.ending:
            self.pass_out()                   # obj_ari.should_faint
        self.history.append((self.day, clock["time"]))

    # -- test helpers --------------------------------------------------------------------------------------
    def popup(self, title):
        return next((p for p in self.popups if p.title == title), None)

    def go_to_bed(self):
        assert self.call("mistrimulti_clock_bed_interact", BED) is True
        self.popup("misc_local/bed").tap("misc_local/sleep")

    def get_up(self):
        self.popup("mistrimulti/sleep_wait_title").tap("mistrimulti/get_up")

    def state(self):
        return self.interp.call("mistrimulti_clock_state")

    def lines(self):
        return list(self.interp.call("mistrimulti_clock_lines"))


class ClockDriver:
    def __init__(self, game):
        self.game, self.node = game, game.node
        self.node.interp.call("mistrimulti_clock_register_events")
        self.active = True

    def frame(self):
        return {"active": self.active}

    def tick(self, now):
        node = self.node
        node.now = now
        due = [a for a in node.actions if a[0] <= now]
        node.actions = [a for a in node.actions if a[0] > now]
        for _t, fn in due:
            fn()
        for _ in range(3):                    # 60 frames per second, 20 bridge ticks per second
            node.step_frame()


def clock_world(seed, guests=2, **faults):
    world = World(seed, {i: ClockNode for i in range(guests + 1)}, **faults)
    for game in world.games.values():
        game.feature = ClockDriver(game)
    return world


def join(world, slot, **config):
    game = world.start(slot, ClockNode)
    game.node.configure(**config)
    game.feature = ClockDriver(game)
    return game.node


def nodes(world):
    return [world.games[s].node for s in sorted(world.games)]


def check_days(world, days, label):
    """Every game ended each day exactly once and in order; only the host saved, once per day."""
    for node in nodes(world):
        assert node.new_days == days, (label, node.slot, node.new_days)
        assert node.day + 1 == days[-1] if days else True
        for (d1, t1), (d2, t2) in zip(node.history, node.history[1:]):
            assert d2 > d1 or t2 >= t1, (label, node.slot, "clock went backwards", (d1, t1), (d2, t2))
        assert not [w for w in node.game_warnings if "failed" in w], (label, node.slot, node.game_warnings[:3])
        debug = node.call("mistrimulti_events_debug")
        assert debug["errors"] == 0, (label, node.slot, debug)
    host = world.games[0].node
    assert host.saves == len(host.new_days), (label, host.saves, host.new_days)


def attach_warnings(world):
    for game in world.games.values():
        game.node.game_warnings = game.warnings


def run_until(world, condition, limit, label):
    end = world.clock.ms + limit
    while not condition():
        assert world.clock.ms < end, f"{label}: timed out"
        world.run(100)


def spread(world):
    times = [n.clock["time"] for n in nodes(world) if n.eod is None and not n.paused()]
    return max(times) - min(times) if times else 0


def test_clock_sync():
    world = clock_world(31, loss=0.05, dup=0.05, jitter=40)
    host, guest, slow = nodes(world)
    attach_warnings(world)
    host.configure(time=9 * HOUR)
    guest.configure(time=DAWN)                     # joined from the host's save: 6 am
    slow.configure(time=DAWN, minutes=10)          # a different day-length setting of its own
    host.weather["forecast"] = gml.GArray([1, 2, 3] + [0] * 25)
    host.weather["weather"] = 1
    world.run(4000)
    # Far behind: one jump to world time, then both follow the host's clock closely and smoothly.
    assert guest.jumps and slow.jumps, (guest.jumps, slow.jumps)
    worst = 0
    for _ in range(40):
        world.run(250)
        worst = max(worst, spread(world))
    assert worst < 150, f"clocks drifted {worst} game seconds apart"
    assert guest.weather["forecast"][2] == 3 and guest.weather["weather"] == 1 and slow.weather["weather"] == 1
    # A guest in a menu stops (as in the game), then catches up smoothly without jumping.
    jumps = len(guest.jumps)
    guest.menu_open = True
    world.run(2000)
    behind = host.clock["time"] - guest.clock["time"]
    assert behind > 400, behind
    guest.menu_open = False
    world.run(4000)
    assert len(guest.jumps) == jumps and spread(world) < 150, (guest.jumps, spread(world))
    # The host in a menu: world time runs on for the guests, and the host catches up afterwards.
    w = host.rt["clock"]["w"]
    host.menu_open = True
    world.run(2000)
    assert host.rt["clock"]["w"] - w > 400 and guest.clock["time"] - host.clock["time"] > 400
    host.menu_open = False
    world.run(4000)
    assert spread(world) < 150
    # Everyone paused: world time stops, as it does in the game.
    for node in nodes(world):
        node.menu_open = True
    world.run(1500)
    w = host.rt["clock"]["w"]
    world.run(2000)
    assert host.rt["clock"]["w"] == w, "world time ran while every player was paused"
    for node in nodes(world):
        node.menu_open = False
    # A guest whose clock is ahead (a cutscene moved it) waits for world time; it never goes back.
    world.run(2000)
    guest.clock["time"] += 2 * HOUR
    ahead = guest.clock["time"]
    world.run(3000)
    assert ahead <= guest.clock["time"] < ahead + 150, (ahead, guest.clock["time"])
    run_until(world, lambda: spread(world) < 150, 40000, "ahead guest rejoins world time")
    # Every player jumping forward (a cutscene all of them saw) moves world time too.
    for node in nodes(world):
        node.clock["time"] += HOUR
    w = host.rt["clock"]["w"]
    world.run(5000)
    assert host.rt["clock"]["w"] > w + HOUR - 200 and spread(world) < 150, (w, host.rt["clock"]["w"])
    check_days(world, [], "sync")
    print("PASS: clock: a late guest jumps to world time, clocks stay within 150 game s under loss, other day "
          "speeds follow the host's, menus pause only the player in them (smooth catch-up), all paused stops "
          "world time, ahead clocks wait (never backwards), common jumps move world time, weather follows the host")


def test_sleep_vote():
    world = clock_world(32, loss=0.05, dup=0.05, jitter=40)
    host, guest, other = nodes(world)
    attach_warnings(world)
    for node in (host, guest, other):
        node.configure(time=20 * HOUR)
    other.next_day_delay = 2500                   # a player who reads the summary for a while
    world.run(3000)
    # Early bed: ready, the counter shows it, the day goes on for the others.
    guest.go_to_bed()
    world.run(1500)
    assert guest.state() == "bed" and guest.popup("mistrimulti/sleep_wait_title") is not None
    assert "1/3 sleeping" in host.lines() and "1/3 sleeping" in other.lines(), (host.lines(), other.lines())
    # Cancel: out of bed, not counted any more.
    guest.get_up()
    world.run(1500)
    assert guest.state() == "awake" and host.lines() == [], host.lines()
    # Everyone in bed: each game runs the game's own sleep, end of day and new_day exactly once.
    host.go_to_bed()
    guest.go_to_bed()
    world.run(2000)
    assert "2/3 sleeping" in other.lines() and host.new_days == []
    other.go_to_bed()
    run_until(world, lambda: all(n.new_days == [2] and n.eod is None for n in nodes(world)), 20000, "all slept")
    assert all(n.scenes == ["sleep"] for n in nodes(world)), [n.scenes for n in nodes(world)]
    # The next day runs on the host's clock again, and nobody is counted as sleeping.
    world.run(4000)
    assert spread(world) < 150 and all(n.state() == "awake" and n.lines() == [] for n in nodes(world))
    # 2 am: whoever is awake passes out (ready); a bed sleeper and the pass-outs end the day together.
    for node in nodes(world):
        node.clock["time"] = LAST - 900
    host.rt["clock"]["w"] = LAST - 900
    guest.go_to_bed()
    run_until(world, lambda: all(n.new_days == [2, 3] for n in nodes(world)), 30000, "pass out")
    assert (host.passouts, other.passouts, guest.passouts) == (1, 1, 0), (host.passouts, other.passouts)
    assert host.scenes == other.scenes == ["sleep"] and guest.scenes == ["sleep", "sleep"]
    world.run(2000)
    check_days(world, [2, 3], "vote")
    print("PASS: sleep vote: bed counts as ready with a counter, getting up cancels, the day ends only when all "
          "are asleep, pass-outs at 2 am count, one sleep scene / end of day / new_day per player, host saves once")


def test_sleep_disconnect_and_late_join():
    world = clock_world(33, loss=0.03, jitter=30)
    host, guest, away = nodes(world)
    attach_warnings(world)
    for node in (host, guest, away):
        node.configure(time=21 * HOUR)
    world.run(3000)
    host.go_to_bed()
    guest.go_to_bed()
    world.run(1500)
    assert "2/3 sleeping" in host.lines()
    # A player who disconnects while the others sleep no longer holds the day once it expires.
    world.net.partition(2, 0)
    run_until(world, lambda: host.new_days == [2] and guest.new_days == [2], 30000, "disconnect")
    assert away.new_days == []
    # Back with the same session: it is a day behind, so it ends its day (once) as soon as it is free.
    away.menu_open = True
    world.net.partition(2, 0, False)
    world.run(4000)
    assert away.new_days == [], "ended the day inside a menu"
    away.menu_open = False
    run_until(world, lambda: away.new_days == [2] and away.eod is None, 20000, "catch up")
    assert any("day_ended" in note for note in away.notes)
    run_until(world, lambda: spread(world) < 150, 10000, "back on world time")
    # A late joiner during a vote must sleep too; it arrives at 6 am and jumps to world time.
    host.go_to_bed()
    guest.go_to_bed()
    world.run(1500)
    late = join(world, 3, day=1, time=DAWN)
    late.game_warnings = world.games[3].warnings
    world.run(4000)
    assert late.jumps and "2/4 sleeping" in host.lines(), (late.jumps, host.lines())
    away.go_to_bed()
    world.run(3000)
    assert host.new_days == [2] and "3/4 sleeping" in late.lines()
    late.go_to_bed()
    run_until(world, lambda: all(n.new_days[-1:] == [3] and n.eod is None for n in nodes(world)), 20000, "late")
    assert late.new_days == [3] and host.new_days == [2, 3]
    late_days = late.new_days
    late.new_days = [2, 3]                       # it joined on day 2: compare the rest
    check_days(world, [2, 3], "disconnect")
    late.new_days = late_days
    print("PASS: sleep vote: a disconnected player stops counting, catches up one day once when back and free, "
          "a late joiner jumps to world time and must sleep too")


def test_sleep_timeout_and_host_restart():
    world = clock_world(34, loss=0.03, dup=0.03, jitter=30)
    host, guest, stuck = nodes(world)
    attach_warnings(world)
    for node in (host, guest, stuck):
        node.configure(time=LAST - 600)
    world.run(2000)
    # Stuck in a menu at 2 am: the others pass out; after the timeout the host ends the day anyway.
    stuck.menu_open = True
    run_until(world, lambda: host.eod is not None and guest.eod is not None, 20000, "pass out")
    world.run(10000)
    assert host.new_days == [], "the day ended before the 2 am timeout"
    run_until(world, lambda: host.new_days == [2] and guest.new_days == [2], 70000, "timeout")
    stuck.menu_open = False
    run_until(world, lambda: stuck.new_days == [2] and stuck.eod is None, 20000, "stuck catches up")
    world.run(3000)
    # Host restart mid-vote: a guest in bed stays ready for the new host; nothing ends twice.
    guest.go_to_bed()
    world.run(2000)
    world.net.helpers[0].alive = False
    del world.net.helpers[0]
    del world.games[0]
    world.run(3000)
    host = join(world, 0, day=1, time=DAWN)      # the host reloads its save: day 2, 6 am
    host.game_warnings = world.games[0].warnings
    world.run(5000)
    assert guest.state() == "bed" and "1/3 sleeping" in host.lines(), host.lines()
    assert stuck.clock["time"] > host.clock["time"], "a guest clock went back to the restarted host's"
    host.go_to_bed()
    stuck.go_to_bed()
    run_until(world, lambda: all(n.new_days[-1:] == [3] and n.eod is None for n in nodes(world)), 20000, "restart")
    assert host.new_days == [3] and host.saves == 1 and guest.new_days == [2, 3] and stuck.new_days == [2, 3]
    host.new_days = [2, 3]
    host.saves = 2
    check_days(world, [2, 3], "restart")
    print("PASS: sleep vote: the 2 am timeout ends the day for a player stuck in a menu (who then ends it once), "
          "a host restart keeps the guests' sleep state, guest clocks never go back")


def test_clock_untrusted_input():
    world = clock_world(35)
    host, guest, _other = nodes(world)
    attach_warnings(world)
    for node in nodes(world):
        node.configure(time=10 * HOUR)
    world.run(3000)
    ctx = {"kind": "x", "seq": 1, "to": -1}
    vote = dict(guest.rt["clock"]["vote"])
    for bad in ({"d": "2", "n": 0, "m": 3, "a": 1}, {"d": 2, "n": 5, "m": 3, "a": 1}, {"d": 2, "n": 0, "m": 3, "a": 9},
                {"d": 2.5, "n": 0, "m": 3, "a": 1}, [], "x", {"d": 1, "n": 0, "m": 99, "a": 0}):
        guest.call("mistrimulti_clock_vote_event", 0, bad, ctx)
        guest.call("mistrimulti_clock_event", 0, bad, ctx)
        guest.call("mistrimulti_clock_weather_event", 0, {"d": 1, "f": [9] * 28}, ctx)
        host.call("mistrimulti_clock_report", 1, {"run": 1, "a": True, "d": 1, "t": 5}, ctx)
        host.call("mistrimulti_clock_report", 1, {"run": True, "a": True, "d": 1, "t": LAST + 5}, ctx)
    assert dict(guest.rt["clock"]["vote"]) == vote and guest.rt["clock"]["weather"] is None
    # A vote from another guest (not the host) and a guest forging the host's request slot are ignored.
    guest.call("mistrimulti_clock_vote_event", 2, {"d": 1, "n": 0, "m": 3, "a": 1}, ctx)
    assert dict(guest.rt["clock"]["vote"]) == vote
    result = host.call("mistrimulti_clock_sleep_request", 0, {"d": 1, "s": "eod"}, ctx)
    assert result["ok"] is False
    host.call("mistrimulti_clock_sleep_request", 1, {"d": 1, "s": "dancing"}, ctx)
    host.call("mistrimulti_clock_sleep_request", 1, {"d": -1, "s": "eod"}, ctx)
    assert host.rt["clock"]["votes"][1] is None or host.rt["clock"]["votes"][1]["s"] == "awake"
    world.run(2000)
    check_days(world, [], "input")
    print("PASS: clock: malformed or forged clock, vote, weather, report and sleep data is ignored")


if __name__ == "__main__":
    test_terrain()
    test_player_records()
    test_clock_sync()
    test_sleep_vote()
    test_sleep_disconnect_and_late_join()
    test_sleep_timeout_and_host_restart()
    test_clock_untrusted_input()
