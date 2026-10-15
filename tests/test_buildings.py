"""The insides of player buildings (greenhouse, barn) are shared: farm nodes, soil and water, on the event layer.

    python3 tests/test_buildings.py

MistriMultiBuildings.gml, MistriMultiFarm.gml and MistriMultiTerrain.gml run unmodified in tests/gml_subset.py over the
simulated helpers and lossy network of tests/event_sim.py. The engine stand-in is the one of tests/test_farm_sync.py
with two dynamic grids added (a greenhouse and a barn), DYNAMIC_GRIDS, get_buildings(), and the soil and water
arrays of the terrain feature. Each game numbers its dynamic grids on its own: guest 1 uses other `dyn_index`
values than the host and guest 2, so every test also proves that the buildings are identified by their place.
docs/SYNC-BUILDINGS.md lists what only the real game can confirm.
"""
import random

from event_sim import GmlNode, World
import gml_subset as gml
import test_farm_sync as tf
from test_farm_sync import CAT, OBJ_ID, OBJECTS, PROTOS, S, vec

GH, BARN = 3, 4                                  # the LocationIds of the two interiors
NAMES = ["farm", "town", "dungeon", "greenhouse", "barn"]
SIDE = {GH: 12, BARN: 10}
# dyn_index of the greenhouse and the barn in each game: guest 1 disagrees with the host.
DYN = {0: (0, 1), 1: (4, 2), 2: (0, 1), 3: (0, 1)}
DIRT, SOIL = 1, 2


def add_object(name, **fields):
    OBJECTS.append((name, "Building", dict(size=4)))
    OBJ_ID[name] = len(OBJECTS) - 1
    proto = S(object_id=OBJ_ID[name], category_id=CAT["Building"], size=vec(4, 4))
    proto.update(fields)
    PROTOS.append(proto)


add_object("greenhouse_b", player_building_kind=1, location_id=GH)
add_object("barn_b", player_building_kind=0, location_id=BARN)
GH_AT, BARN_AT = (4, 2), (8, 2)                  # where the buildings stand on the farm
GH_REF, BARN_REF = "b4_2", "b8_2"


class Void(tf.Grid):
    """The mines (LocationId 2): never loaded in these tests, so nothing grows or spawns there."""

    def write_raw(self, *args):
        return None


class BldEngine(tf.Engine):
    """The farm stand-in plus the insides of two buildings."""

    def __init__(self, slot):
        super().__init__(slot)
        farm, town = self.grids
        self.grids = [farm, town, Void(self, 2, 4), tf.Grid(self, GH, SIDE[GH]), tf.Grid(self, BARN, SIDE[BARN])]
        self.templates = [tf.Grid(self, GH, SIDE[GH]), tf.Grid(self, BARN, SIDE[BARN])]   # GRIDS has an unused grid per interior
        self.dyn = DYN[slot]
        self.dynamic = [None] * 8
        for g in self.grids + self.templates:
            n = g.size * g.size
            g.struct.update(node_terrain_is_watered=gml.GArray([False] * n),
                            node_index_for_cell=g.index, write_ground=self.writer(g),
                            update_tilemap_for_node=lambda x, y: None)

    @staticmethod
    def writer(g):
        def write_ground(x, y, kind):
            g.struct["node_terrain_ground_kind"][g.index(x, y)] = kind
        return write_ground

    def build(self, which):
        """The game writes a building on the farm: the node, and its inside under the game's next number."""
        loc, at, name = (GH, GH_AT, "greenhouse_b") if which == "gh" else (BARN, BARN_AT, "barn_b")
        dyn = self.dyn[0 if which == "gh" else 1]
        self.grids[loc].struct["dyn_index"] = dyn
        self.dynamic[dyn] = self.grids[loc].struct
        self.put(0, name, at[0], at[1], dyn_index=dyn)

    def get_buildings(self):
        found = [n for n in self.grids[0].nodes() if n.get("dyn_index") is not None]
        return S(count=lambda: len(found), get=lambda i: found[i])

    def water_chunk(self, grid, x, y, wet):
        grid["node_terrain_is_watered"][y * grid["dims"].x + x] = bool(wet)

    def builtins(self):
        b = super().builtins()
        b["GRIDS"] = gml.GArray([self.grids[0].struct, self.grids[1].struct, self.grids[2].struct,
                                 self.templates[0].struct, self.templates[1].struct])
        b["DYNAMIC_GRIDS"] = S(get=lambda i: self.dynamic[i], count=lambda: len(self.dynamic))
        b["LocationId"] = S(Farm=0, Town=1, Dungeon=2, Greenhouse=GH, Barn=BARN, LEN=5)
        b["LOCATIONS"] = gml.GArray([S(forageables=0, dig_sites=0, serializable=True), S(forageables=3, dig_sites=1, serializable=True),
                                     S(forageables=2, dig_sites=0, serializable=True), S(forageables=0, dig_sites=0, serializable=True),
                                     S(forageables=0, dig_sites=0, serializable=True)])
        b["location_id_to_string"] = lambda i: NAMES[i]
        b["get_buildings"] = self.get_buildings
        b["PlayerBuildingKind"] = S(Stable=0, Greenhouse=1, MiniMuseum=2)
        b["water_chunk"] = self.water_chunk
        return b


class BldNode(GmlNode):
    extra_files = ("MistriMultiBuildings.gml", "MistriMultiFarm.gml", "MistriMultiTerrain.gml")

    def builtins(self):
        self.engine = BldEngine(self.slot)
        return self.engine.builtins()

    def setup(self):
        self.engine.node = self
        self.rt["enabled"] = True
        self.rt.update(watches=gml.GArray(), apply_depth=0, dirty_world=False, snapshot_pending=False, terrain_cursor=-1)
        self.interp.functions["mistrimulti_farm_new_doppel"] = self.engine.doppel


class BldDriver:
    """What MistriMultiBoot.gml does each bridge tick for these features, and the room key it puts in the frame."""

    def __init__(self, game):
        self.game, self.node = game, game.node
        self.x, self.y = 128, 128
        self.node.interp.call("mistrimulti_farm_register_events")
        self.node.interp.call("mistrimulti_terrain_register_events")

    def frame(self):
        e = self.node.engine
        part = self.node.call("mistrimulti_room_part", e.grids[e.location].struct)
        return {"room": f"{NAMES[e.location]}:{part}", "x": self.x, "y": self.y}

    def tick(self, now):
        if self.node.rt["mode"] == "host":
            self.node.call("mistrimulti_stream_terrain")
        self.node.call("mistrimulti_watch_changes")
        self.node.call("mistrimulti_farm_tick")


def populate(e, buildings=("gh", "barn")):
    tf.populate(e)
    for which in buildings:
        e.build(which)
    # The greenhouse: a soil bed with crops, a sprinkler and a fence. The barn: a fence.
    e.ground(GH, 2, 2, 10, 10, "Soil")
    e.put(GH, "turnip", 2, 2, stage=4, day_count=4)
    e.put(GH, "turnip", 4, 2, stage=2, day_count=2)
    e.put(GH, "strawberry", 6, 2, stage=4, day_count=4)
    e.put(GH, "sprinkler", 0, 0, cardinal_index=0)
    e.put(GH, "fence", 0, 11, cardinal_index=0)
    e.put(BARN, "fence", 2, 2, cardinal_index=0)
    e.put(BARN, "chest", 4, 4, cardinal_index=0)       # not ours: must survive untouched


def view(game):
    """Every synchronised node of every grid in this game: (location, x, y) -> (object, GML signature)."""
    return tf.view(game)


def setup_world(seed, guests=2, **faults):
    world = World(seed, {i: BldNode for i in range(guests + 1)}, **faults)
    for game in world.games.values():
        game.feature = BldDriver(game)
        populate(game.node.engine)
        game.node.engine.rng = random.Random(1000 + game.slot)
        game.node.engine.enter(0)
    return world


def assert_same(world, what):
    tf.assert_same(world, what)


def assert_clean(world):
    for game in world.games.values():
        debug = game.node.call("mistrimulti_events_debug")
        assert debug["errors"] == 0 and debug["backlog"] == 0, (game.slot, debug, game.warnings[:3])
        assert game.node.rt["farm"]["errors"] == 0, (game.slot, game.node.rt["farm"]["errors"], game.warnings[:3])
        assert len(game.node.rt["farm"]["pending_keys"]) == 0, (game.slot, "unpublished changes left over")


def tile(game, loc, x, y):
    g = getattr(game, "node", game).engine.grids[loc].struct
    i = y * g["dims"].x + x
    return g["node_terrain_ground_kind"][i], g["node_terrain_is_watered"][i]


def water_with_can(game, loc, x, y):
    """What the watering can does in the game: the tool.targets hook sees the cell, then the water lands."""
    e = game.node.engine
    item = S(item_id=0, prototype=S(tool_type=tf.TOOL["WateringCan"]))
    targets = [vec(x, y)]
    lst = S(count=lambda: len(targets), get=lambda i: targets[i], push=targets.append)
    game.node.call("mistrimulti_tool_targets", lst, S(item=item, range_pattern=0, x=x, y=y, cardinal=0))
    g = e.grids[loc].struct
    g["node_terrain_is_watered"][y * g["dims"].x + x] = True


# ---- scenarios --------------------------------------------------------------------------------------------------------

def test_identity():
    world = setup_world(61)
    host, g1, g2 = (world.games[i].node for i in range(3))
    world.run(1000)
    assert g1.engine.grids[GH].struct["dyn_index"] == 4 and host.engine.grids[GH].struct["dyn_index"] == 0, "the games must disagree"
    for node in (host, g1, g2):
        gh, barn = node.engine.grids[GH].struct, node.engine.grids[BARN].struct
        assert node.call("mistrimulti_grid_ref", gh) == GH_REF and node.call("mistrimulti_grid_ref", barn) == BARN_REF
        assert node.call("mistrimulti_grid_by_ref", GH_REF) is gh and node.call("mistrimulti_grid_by_ref", BARN_REF) is barn
        assert node.call("mistrimulti_grid_ref", node.engine.grids[0].struct) == 0
        assert node.call("mistrimulti_grid_by_ref", 0) is node.engine.grids[0].struct
        assert node.call("mistrimulti_room_of_grid", gh) == "greenhouse:b4_2"
        assert node.call("mistrimulti_room_of_grid", node.engine.grids[0].struct) == "farm:undefined"
        assert list(node.call("mistrimulti_building_refs")) == [GH_REF, BARN_REF]
        # Anything that is not a LocationId or the name of a building of this farm is refused.
        for bad in (None, -1, 99, 2.5, "b1_1", "", "greenhouse", "b4_2" + "x" * 20, ["b4_2"], {}, True):
            assert node.call("mistrimulti_grid_by_ref", bad) is None, bad
        assert node.call("mistrimulti_grid_by_ref", GH) is not gh, "a LocationId must not name the inside of a building"
        # A grid that is not a building's inside has no name.
        stray = S(location_id=GH, dyn_index=7, dims=vec(2, 2))
        assert node.call("mistrimulti_grid_ref", stray) is None
        assert node.call("mistrimulti_room_part", stray) == "7"
    print("PASS: buildings are named by their place on the farm: the same name in games that number their grids differently, "
          "hostile names refused")


def test_join_and_changes():
    world = setup_world(62, loss=0.05, dup=0.03, jitter=40)
    host, g1, g2 = (world.games[i].node for i in range(3))
    # The guests loaded an older save: stale and missing crops, an extra fence, a changed sprinkler.
    for guest in (g1, g2):
        guest.engine.at(GH, 2, 2)["stage"] = 1
        guest.engine.remove(GH, 6, 2)
        guest.engine.put(GH, "fence", 4, 11, cardinal_index=0)
        guest.engine.at(GH, 0, 0)["essence_supply"] = 7
    g2.engine.remove(BARN, 2, 2)
    host.engine.at(GH, 4, 2)["stage"] = 3
    world.run(12000)
    assert_same(world, "join")
    assert host.engine.at(GH, 6, 2) is not None and g1.engine.at(GH, 6, 2)["stage"] == 4
    assert g2.engine.at(BARN, 4, 4) is not None, "a chest the farm sync does not own was removed"
    locs = [[loc["id"] for loc in game.node.call("mistrimulti_farm_debug")["locs"]] for game in world.games.values()]
    assert locs[0] == locs[1] == locs[2] == [0, 1, GH_REF, BARN_REF], locs
    digests = [[loc["digest"] for loc in game.node.call("mistrimulti_farm_debug")["locs"]] for game in world.games.values()]
    assert digests[0] == digests[1] == digests[2], digests
    # The host's own play inside, with the game's own code (nothing special hooks it): harvest, plant, a day of growth.
    host.engine.enter(GH)
    e = host.engine
    assert e.interact(e.at(GH, 2, 2)) is True and e.inventory == {"turnip": 1}
    e.put(GH, "turnip", 8, 2, stage=0)
    world.run(5000)
    assert_same(world, "host harvest and planting")
    e.new_day()
    host.call("mistrimulti_farm_new_day", S(total_days=2))
    for game in list(world.games.values())[1:]:
        game.node.engine.new_day()
        game.node.call("mistrimulti_farm_new_day", S(total_days=2))
    world.run(15000)
    assert_same(world, "day change")
    assert g1.engine.at(GH, 8, 2)["stage"] == host.engine.at(GH, 8, 2)["stage"] == 1
    assert_clean(world)
    print("PASS: stale greenhouse and barn contents converge by digests and chunks, the host's harvest, planting and "
          "daily growth inside reach every guest (with different grid numbers)")


def test_guest_actions_inside():
    world = setup_world(63, guests=3, loss=0.08, dup=0.1, jitter=50)
    host, g1, g2, g3 = (world.games[i].node for i in range(4))
    world.run(5000)
    assert_same(world, "initial")
    for i in (1, 2, 3):
        world.games[i].node.engine.enter(GH)
        tf.place(world.games[i], 3, 3)
    # Two guests press harvest on the same ripe turnip: one yield, to one of them (guest 1's grid has another number).
    for guest in (g1, g2):
        assert guest.engine.interact(guest.engine.at(GH, 2, 2)) is True
        assert guest.engine.inventory == {} and guest.engine.at(GH, 2, 2) is not None
    world.run(5000)
    assert sorted(g.engine.inventory.get("turnip", 0) for g in (g1, g2)) == [0, 1]
    assert host.engine.at(GH, 2, 2) is None and g3.engine.at(GH, 2, 2) is None
    assert host.engine.inventory == {} and g3.engine.inventory == {}
    assert_same(world, "harvest inside")
    # A regrowing crop stays and starts over.
    tf.place(world.games[3], 7, 3)
    assert g3.engine.interact(g3.engine.at(GH, 6, 2)) is True
    world.run(4000)
    assert g3.engine.inventory == {"strawberry": 2}
    assert host.engine.at(GH, 6, 2)["stage"] == 3 and g1.engine.at(GH, 6, 2)["stage"] == 3
    assert_same(world, "regrowing crop")
    # Edits: guest 1 plants on the soil, charges the sprinkler, puts up a fence; the planting on bare floor is undone.
    tf.place(world.games[1], 9, 5)
    g1.engine.put(GH, "turnip", 8, 4, stage=0)
    g1.engine.at(GH, 0, 0)["essence_supply"] = 4
    g1.engine.put(GH, "fence", 10, 4, cardinal_index=0)
    g1.engine.put(GH, "turnip", 10, 10, stage=0)           # the floor there is not soil on the host
    host.engine.ground(GH, 10, 10, 12, 12, "RiverBank")
    world.run(5000)
    for game in (host, g2, g3):
        assert game.engine.at(GH, 8, 4) is not None and game.engine.at(GH, 10, 4) is not None, game.slot
        assert game.engine.at(GH, 0, 0)["essence_supply"] == 4, game.slot
        assert game.engine.at(GH, 10, 10) is None, game.slot
    assert g1.engine.at(GH, 10, 10) is None and g1.engine.inventory.get("seed_turnip", 0) == 1, g1.engine.inventory
    assert_same(world, "edits inside")
    # A guest who is not in that building is refused, even if it names it: the room key has to match.
    world.games[2].node.engine.enter(0)
    before = host.engine.at(GH, 4, 2)["stage"]
    for ref in (GH_REF, BARN_REF):
        g2.call("mistrimulti_event_request", "farm_act", {"a": "harvest", "l": ref, "x": 4, "y": 2})
        g2.call("mistrimulti_event_request", "farm_act", {"a": "edit", "l": ref, "e": [["c", 0, 11], ["r", 0, 11]]})
    world.run(4000)
    assert host.engine.at(GH, 4, 2)["stage"] == before and host.engine.at(GH, 0, 11) is not None
    # The host stands in the barn: a guest in the greenhouse cannot act on the barn's fence either.
    g1.call("mistrimulti_event_request", "farm_act", {"a": "edit", "l": BARN_REF, "e": [["r", 2, 2]]})
    world.run(3000)
    assert host.engine.at(BARN, 2, 2) is not None
    assert_same(world, "refused outside")
    assert_clean(world)
    print("PASS: guests harvest, plant, charge and build inside the greenhouse (one yield, refunds, own inventories); "
          "a guest outside the building is refused")


def test_guest_tools_inside():
    world = setup_world(64, loss=0.05, dup=0.04, jitter=40)
    host, g1, g2 = (world.games[i].node for i in range(3))
    # A dig site and a rock inside the greenhouse (only the farm has them in the real game; the code path is the same).
    for game in world.games.values():
        game.node.engine.put(GH, "stone", 8, 8, hitpoints=4)
    world.run(5000)
    assert_same(world, "initial")
    g1.engine.enter(GH)
    tf.place(world.games[1], 9, 7)
    swing = tf.swing(world.games[1], "pickaxe", [(8, 8)])
    assert swing == 1 and g1.engine.at(GH, 8, 8)["hitpoints"] == 4, "the swing hit the rock locally before the host agreed"
    world.run(3000)
    assert host.engine.at(GH, 8, 8)["hitpoints"] == 2 and g2.engine.at(GH, 8, 8)["hitpoints"] == 2 and g1.engine.at(GH, 8, 8)["hitpoints"] == 2
    tf.next_swing(world, world.games[1])
    tf.swing(world.games[1], "pickaxe", [(8, 8)])
    world.run(3000)
    assert host.engine.at(GH, 8, 8) is None and g2.engine.at(GH, 8, 8) is None and g1.engine.at(GH, 8, 8) is None
    assert g1.engine.inventory.get("stone_item") == 2 and host.engine.inventory == {} and g2.engine.inventory == {}
    assert_same(world, "rock inside")
    assert_clean(world)
    print("PASS: a guest's pickaxe inside a building is decided by the host and the yield is the swinger's")


def test_enter_and_unknown_building():
    world = setup_world(65, loss=0.03, dup=0.02, jitter=30)
    host, g1, g2 = (world.games[i].node for i in range(3))
    world.run(5000)
    # A guest whose copy drifted while it was outside is repaired as soon as it walks into the greenhouse
    # (the minute timer is far away): walking in asks the host for the digests.
    g2.engine.at(GH, 4, 2)["stage"] = 4
    g2.engine.put(GH, "fence", 6, 11, cardinal_index=0)
    host.engine.at(GH, 2, 2)["stage"] = 3
    g2.rt["farm"]["hello"] = False
    world.run(3000)
    g2.engine.enter(GH)
    world.run(3000)
    assert_same(world, "entering")
    # The host finishes a new building the guests do not have yet: their digests mention a place they cannot find, which
    # they ignore, and once the building exists in the guest too, the inside converges.
    for game in world.games.values():
        if game.slot != 2:
            continue
        game.node.engine.dynamic[game.node.engine.dyn[1]] = None
    g2.engine.grids[0].erase(g2.engine.at(0, *BARN_AT))
    host.engine.at(BARN, 2, 2)["cardinal_index"] = 1
    world.run(8000)
    assert list(g2.call("mistrimulti_building_refs")) == [GH_REF]
    assert g2.rt["farm"]["errors"] == 0
    g2.engine.build("barn")
    world.run(8000)
    assert g2.engine.at(BARN, 2, 2)["cardinal_index"] == 1
    assert_same(world, "late building")
    assert_clean(world)
    print("PASS: walking into a greenhouse repairs it at once; a building a guest does not have yet is ignored, then converges")


def test_terrain_inside():
    world = setup_world(66, loss=0.05, dup=0.03, jitter=40)
    host, g1, g2 = (world.games[i].node for i in range(3))
    world.run(5000)
    # The host's greenhouse was watered before the guests joined... (the snapshot of the greenhouse covers it)
    for game in world.games.values():
        assert tile(game, GH, 4, 4) == (SOIL, False)
    host.engine.grids[GH].struct["node_terrain_is_watered"][4 * SIDE[GH] + 4] = True
    host.call("mistrimulti_event_emit", "terrain_commit", {"tiles": [{"x": 4, "y": 4, "g": SOIL, "w": True}], "l": GH_REF})
    world.run(3000)
    assert tile(g1, GH, 4, 4) == (SOIL, True) and tile(g2, GH, 4, 4) == (SOIL, True)
    assert tile(g1, 0, 4, 4)[1] is False, "the farm's tile at the same place was changed"
    # The host's own watering is noticed by the tool hook and committed.
    host.engine.enter(GH)
    water_with_can(world.games[0], GH, 6, 6)
    world.run(3000)
    assert tile(g1, GH, 6, 6) == (SOIL, True) and tile(g2, GH, 6, 6) == (SOIL, True)
    # A guest waters the greenhouse with its own can: a request the host validates; the room key must match.
    g1.engine.enter(GH)
    tf.place(world.games[1], 8, 6)
    water_with_can(world.games[1], GH, 8, 6)
    world.run(3000)
    assert tile(world.games[0], GH, 8, 6) == (SOIL, True) and tile(world.games[2], GH, 8, 6) == (SOIL, True)
    assert tile(world.games[0], 0, 8, 6)[1] is False
    # Out of the building: a guest outside cannot water it, and a forged place changes nothing.
    g2.engine.enter(0)
    tf.place(world.games[2], 8, 8)
    before = tile(world.games[0], GH, 2, 6)
    wet = {"x": 2, "y": 6, "g": SOIL, "w": True}
    dry = dict(wet, w=False)
    g2.call("mistrimulti_event_request", "terrain", {"tiles": [wet], "before": dry, "l": GH_REF})
    g1.call("mistrimulti_event_request", "terrain", {"tiles": [wet], "before": dry, "l": BARN_REF})
    for bad in (GH, 3.5, "b99_99", "farm", ["b4_2"], {}, True):
        g1.call("mistrimulti_event_request", "terrain", {"tiles": [wet], "before": dry, "l": bad})
    world.run(3000)
    assert tile(world.games[0], GH, 2, 6) == before == (SOIL, False)
    # The same soil request on the farm (where guest 2 stands) with a place that is not the farm's.
    farm_wet, farm_dry = {"x": 2, "y": 6, "g": SOIL, "w": True}, {"x": 2, "y": 6, "g": SOIL, "w": False}
    assert tile(world.games[0], 0, 2, 6) == (SOIL, False)
    for bad in (GH, 3.5, True, "farm", 7):
        g2.call("mistrimulti_event_request", "terrain", {"tiles": [farm_wet], "before": farm_dry, "l": bad})
    world.run(3000)
    assert tile(world.games[0], 0, 2, 6) == (SOIL, False) and tile(world.games[2], 0, 2, 6) == (SOIL, False)
    # A new day dried the greenhouse on the host; the guest that was away still has the water. Walking in refreshes it.
    host.engine.grids[GH].struct["node_terrain_is_watered"][4 * SIDE[GH] + 4] = False
    g2.engine.enter(0)
    world.run(2000)
    assert tile(world.games[2], GH, 4, 4) == (SOIL, True)
    g2.engine.enter(GH)
    world.run(4000)
    assert tile(world.games[2], GH, 4, 4) == (SOIL, False), "no snapshot of the greenhouse when walking in"
    # A guest that re-enters its world gets the greenhouse's soil and water with the farm's.
    g1.engine.grids[GH].struct["node_terrain_is_watered"][6 * SIDE[GH] + 6] = False
    g1.call("mistrimulti_events_reset")
    world.run(8000)
    assert tile(world.games[1], GH, 6, 6) == (SOIL, True)
    assert_clean(world)
    print("PASS: soil and water inside the greenhouse: host and guest watering, the room check, forged places refused, "
          "snapshot on entering and on (re)joining")


def test_hostile_input():
    world = setup_world(67, loss=0.02)
    host, g1, g2 = (world.games[i].node for i in range(3))
    world.run(5000)
    g1.engine.enter(GH)
    tf.place(world.games[1], 3, 3)
    world.run(2000)
    snapshot = view(world.games[0])
    junk = [None, 7, -3, 2.5, 1e12, "", "x", "b", "b4_2 ", "b4_2" + "9" * 40, "b-1_-1", "b0_0", ["b4_2"], {"a": 1}, True]
    for bad in junk:
        g1.call("mistrimulti_event_request", "farm_act", {"a": "harvest", "l": bad, "x": 2, "y": 2})
        g1.call("mistrimulti_event_request", "farm_act", {"a": "edit", "l": bad, "e": [["a", ["turnip", 4, 4, 0, 0, 0, 0, -1]]]})
        g1.call("mistrimulti_event_request", "terrain", {"tiles": [{"x": 4, "y": 4, "g": SOIL, "w": True}], "before": {"x": 4, "y": 4, "g": SOIL, "w": False}, "l": bad})
        g1.call("mistrimulti_event_emit", "farm_want", {"l": bad, "c": [0, 1]}, 0)
        g1.call("mistrimulti_event_emit", "farm_delta", {"l": bad, "n": [["turnip", 4, 4, 0, 0, 0, 0, -1]], "g": [[2, 2]]})
        host.call("mistrimulti_event_emit", "farm_delta", {"l": bad, "n": [["turnip", 4, 4, 0, 0, 0, 0, -1]], "g": [[2, 2]]}, 2)
        host.call("mistrimulti_event_emit", "farm_chunk", {"l": bad, "c": 0, "n": [], "e": 1}, 2)
        host.call("mistrimulti_event_emit", "farm_digest", {"l": bad, "n": 3, "o": 0, "d": [1, 2, 3]}, 2)
        host.call("mistrimulti_event_emit", "terrain_commit", {"tiles": [{"x": 4, "y": 4, "g": SOIL, "w": True}], "l": bad}, 2)
        host.call("mistrimulti_event_emit", "terrain_snapshot", {"tiles": [{"x": 4, "y": 4, "g": SOIL, "w": True}], "l": bad}, 2)
    # Valid places with hostile contents.
    for ref in (GH_REF, BARN_REF):
        host.call("mistrimulti_event_emit", "farm_delta", {"l": ref, "n": [["oak", 99, 99, 4, 0, 5, 0, 1, 5], ["house", 2, 2, 0], ["turnip", 3, 3, 0, 0, 0, 0, -1]], "g": [[-1, 0], [1e9, 2]]}, 2)
        host.call("mistrimulti_event_emit", "farm_chunk", {"l": ref, "c": 9999, "n": [], "e": 1}, 2)
        host.call("mistrimulti_event_emit", "farm_digest", {"l": ref, "n": 1, "o": -5, "d": [1, 2]}, 2)
        host.call("mistrimulti_event_emit", "terrain_commit", {"tiles": [{"x": 99, "y": 99, "g": SOIL, "w": True}, {"x": 3, "y": 3, "g": 77, "w": 1}], "l": ref}, 2)
        g2.call("mistrimulti_event_emit", "farm_want", {"l": ref, "c": [1e9, -1, "q", 2.5]}, 0)
    world.run(6000)
    assert view(world.games[0]) == snapshot
    assert_same(world, "hostile")
    assert tile(world.games[0], GH, 4, 4) == (SOIL, False) and tile(world.games[2], GH, 4, 4) == (SOIL, False)
    assert_clean(world)
    print("PASS: forged and malformed places and contents are ignored without errors; nothing changes")


if __name__ == "__main__":
    import sys
    tests = [value for name, value in sorted(globals().items(), key=lambda kv: kv[1].__code__.co_firstlineno if callable(kv[1]) and hasattr(kv[1], "__code__") else 0)
             if name.startswith("test_")]
    only = sys.argv[1:]
    for test in tests:
        if not only or test.__name__ in only:
            test()
