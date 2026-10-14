"""The migrated features (farm terrain, player records) on the event layer, running their real GML.

    python3 tests/test_event_features.py

MistriMultiTerrain.gml, MistriMultiPlayerSync.gml, MistriMultiIdentity.gml and MistriMultiProgress.gml run unmodified in
tests/gml_subset.py on top of MistriMultiEvents.gml, over the simulated helpers and network of
tests/event_sim.py. Only the engine is stubbed: a small farm grid, and the player-record storage and
validation functions of MistriMultiPlayerData.gml (which need the real game). This checks the handler
wiring, the request/result flow and the record transfer; it does not replace testing in the game.
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


if __name__ == "__main__":
    test_terrain()
    test_player_records()
