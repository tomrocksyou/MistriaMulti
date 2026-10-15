"""Farm world sync (MistriMultiFarm.gml) on the event layer, running the real GML with the engine stubbed.

    python3 tests/test_farm_sync.py

MistriMultiFarm.gml runs unmodified in tests/gml_subset.py on top of MistriMultiEvents.gml, over the simulated
helpers and lossy network of tests/event_sim.py (the harness of tests/test_event_features.py). Only the engine is
stubbed: `Engine` models the grid, nodes, tools and inventory functions the GML calls, with the rules of the
game's own scripts (Grid.gml, Chop.gml, Pick.gml, Interact.gml, ...) so that a guest's local action, the host's
state-only change and the digests can be compared. It checks logic and wiring; it does not replace testing in
the game (docs/SYNC-FARM.md lists what to check there).
"""
import random

from event_sim import GmlNode, World
import gml_subset as gml

W = 20              # the farm is W x W cells
TOWN = 10           # a second synchronised location
CAT = dict(Breakable=0, Building=1, Bush=2, Crop=3, DigSite=4, Furniture=5, Grass=6, Rock=7, Stump=8, Tree=9, LEN=10)
TOOL = dict(Axe=0, PickAxe=1, Shovel=2, Hoe=3, WateringCan=4)
GROUND = dict(Grass=0, Dirt=1, Soil=2, RiverBank=3)
CROP = dict(MANAGED=1, FORAGEABLE=2, NO_HARVEST=4, SPAWN_GROWN=8)
EVEN = (CAT["Crop"], CAT["Tree"], CAT["Stump"], CAT["Rock"], CAT["DigSite"])


class S(gml.GStruct):
    """A GML struct that Python code can also read with attribute syntax."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


def vec(x, y):
    return S(x=x, y=y)


# name, category, prototype fields
OBJECTS = [
    ("turnip", "Crop", dict(size=2, harvest="turnip", count=1, max_stage=4, regrow=False)),
    ("strawberry", "Crop", dict(size=2, harvest="strawberry", count=2, max_stage=4, regrow=True)),
    ("mushroom", "Crop", dict(size=2, harvest="mushroom", count=1, max_stage=1, regrow=False)),
    ("oak", "Tree", dict(minimum_quality=0, stump_id="oak_stump", hp=[2, 3, 4, 6, 8])),
    ("oak_stump", "Stump", dict(size=2, minimum_quality=0, hp=4)),
    ("stone", "Rock", dict(size=2, minimum_quality=0, hp=6)),
    ("ore", "Rock", dict(size=2, minimum_quality=1, hp=8)),
    ("grass_small", "Grass", dict(size=1)),
    ("grass_medium", "Grass", dict(size=1)),
    ("berry_bush", "Bush", dict(size=2, harvest="berry", count=3, regrow_days=3)),
    ("dig_site", "DigSite", dict(size=2)),
    ("dig_site_destroyed", "DigSite", dict(size=2)),
    ("fence", "Furniture", dict(size=1, fence=True, sprinkler=None)),
    ("sprinkler", "Furniture", dict(size=1, fence=False, sprinkler=1)),
    ("chest", "Furniture", dict(size=1, fence=False, sprinkler=None)),
    ("house", "Building", dict(size=4)),
]
OBJ_ID = {name: i for i, (name, _c, _f) in enumerate(OBJECTS)}
ITEMS = ["axe", "axe_gold", "pickaxe", "pickaxe_gold", "shovel", "turnip", "strawberry", "mushroom", "berry", "wood",
         "stone_item", "ore_item", "artifact", "fruit", "seed_turnip", "sapling_oak", "fence_item"]
ITEM_ID = {name: i for i, name in enumerate(ITEMS)}


def make_prototypes():
    protos = gml.GArray()
    for name, cat, f in OBJECTS:
        p = S(object_id=OBJ_ID[name], category_id=CAT[cat])
        if "size" in f:
            p["size"] = vec(f["size"], f["size"])
        if cat == "Crop":
            p.update(harvest=ITEM_ID[f["harvest"]], count=f["count"], max_stage=f["max_stage"], managed_regrow_days=2,
                     post_harvest_day_to_stage=S(get=lambda i, m=f["max_stage"]: m - 1) if f["regrow"] else None)
        elif cat == "Tree":
            p.update(minimum_quality=f["minimum_quality"], stump_id=OBJ_ID[f["stump_id"]], hp=f["hp"])
        elif cat in ("Stump", "Rock"):
            p.update(minimum_quality=f["minimum_quality"], hp=f["hp"])
        elif cat == "Bush":
            p.update(harvest=ITEM_ID[f["harvest"]], count=f["count"], regrow_days=f["regrow_days"])
        elif cat == "Furniture":
            p.update(fence=f["fence"], sprinkler=f["sprinkler"], destructable=True, cardinals=gml.GArray([0, 1]))
        protos.append(p)
    return protos


FX = {"tool_fx/chop": S(damaged=S(node_trauma=0.7, tree=gml.GArray([S(node_trauma=0.1 * (i + 1)) for i in range(5)]))),
      "tool_fx/pick": S(damaged=S(node_trauma=0.9))}
PROTOS = make_prototypes()
ITEM_PROTOS = gml.GArray()
for _i, _name in enumerate(ITEMS):
    _p = S(item_id=_i, tool_type=None, quality=0, damage=0, stamina_cost=-4, use=-1)
    if _name.startswith(("axe", "pickaxe", "shovel")):
        _p.update(tool_type=TOOL["Axe"] if _name.startswith("axe") else TOOL["PickAxe"] if _name.startswith("pick") else TOOL["Shovel"],
                  quality=1 if _name.endswith("gold") else 0, damage=3 if _name.endswith("gold") else 2)
    if _name == "seed_turnip":
        _p.update(use=1, crop_object=OBJ_ID["turnip"])
    if _name == "sapling_oak":
        _p.update(use=2, sapling=OBJ_ID["oak"])
    if _name == "fence_item":
        _p.update(object=OBJ_ID["fence"])
    ITEM_PROTOS.append(_p)


class Grid:
    """A location's grid: the arrays and methods of the game's Grid that the GML uses."""

    def __init__(self, engine, loc, size):
        self.engine, self.loc, self.size = engine, loc, size
        n = size * size
        self.struct = S(
            dims=vec(size, size), location_id=loc, dyn_index=None, is_setup=False,
            node_object_id=gml.GArray([None] * n), node_parent=gml.GArray([None] * n),
            node_terrain_kind=gml.GArray([1] * n), node_terrain_ground_kind=gml.GArray([GROUND["Grass"]] * n),
            node_flags=gml.GArray([1] * n),
            try_node_index_for_cell=self.index, write_node_without_initializing=self.write_raw, write_node=self.write,
            initialize_node_renderer=self.draw)

    def index(self, x, y):
        return y * self.size + x if 0 <= x < self.size and 0 <= y < self.size else None

    def cells(self, oid, x, y):
        """The cells a node occupies: a tree's 6x6 square without its four 2x2 corners."""
        proto = PROTOS[oid]
        if proto.category_id == CAT["Tree"]:
            return [(x + i, y + j) for i in range(6) for j in range(6) if i in (2, 3) or j in (2, 3)]
        return [(x + i, y + j) for i in range(proto.size.x) for j in range(proto.size.y)]

    def write_raw(self, x, y, oid, ctx=None):
        proto = PROTOS[oid]
        cat = proto.category_id
        if cat in EVEN:
            x, y = x // 2 * 2, y // 2 * 2
        cells = self.cells(oid, x, y)
        for cx, cy in cells:
            i = self.index(cx, cy)
            if i is None or self.struct["node_object_id"][i] is not None:
                return None
        if cat == CAT["Grass"] and self.struct["node_terrain_ground_kind"][self.index(x, y)] != GROUND["Grass"]:
            return None
        rng = self.engine.rng
        node = S(object_id=oid, prototype=proto, top_left_x=x, top_left_y=y, renderer=None, last_update=-1)
        if cat == CAT["Crop"]:
            node.update(ctx=ctx or 0, stage=proto.max_stage if (ctx or 0) & CROP["SPAWN_GROWN"] else 0, day_count=0,
                        regrow_cycle=False, managed_timer=None)
        elif cat == CAT["Tree"]:
            node.update(stage=0, day_count=0, hitpoints=proto.hp[0], fruiting_days=0, has_fruit=False,
                        variant_idx=rng.randint(0, 99) / 100.0)
        elif cat in (CAT["Stump"], CAT["Rock"]):
            node.update(hitpoints=proto.hp, variant_idx=rng.randint(0, 99) / 100.0)
        elif cat == CAT["Grass"]:
            node.update(variant_idx=rng.randint(0, 99) / 100.0, offset_x=rng.randint(-1, 1), offset_y=rng.randint(-1, 1),
                        stunt_growth=rng.random() < 0.2, day_count=0)
        elif cat in (CAT["Bush"], CAT["DigSite"]):
            node.update(day_count=0)
        elif cat == CAT["Furniture"]:
            node.update(cardinal_index=proto.cardinals[ctx or 0])
            if proto.sprinkler is not None:
                node["essence_supply"] = 0
        for cx, cy in cells:
            i = self.index(cx, cy)
            self.struct["node_object_id"][i] = oid
            self.struct["node_parent"][i] = node
        return node

    def write(self, x, y, oid, ctx=None):
        node = self.write_raw(x, y, oid, ctx)
        if node is not None and self.struct["is_setup"]:
            self.draw(node)
        return node

    def draw(self, node):
        node["renderer"] = S(x=node["top_left_x"] * 8, y=node["top_left_y"] * 8)
        self.engine.draws += 1

    def erase(self, node):
        for i, parent in enumerate(self.struct["node_parent"]):
            if parent is node:
                self.struct["node_object_id"][i] = None
                self.struct["node_parent"][i] = None
        node["renderer"] = None

    def nodes(self):
        seen = []
        for parent in self.struct["node_parent"]:
            if parent is not None and not any(parent is s for s in seen):
                seen.append(parent)
        return seen


class Engine:
    """The game objects the GML touches, with the game's rules for the actions it replays."""

    PICK_NOTHING, PICK_ROCK, PICK_DIG, PICK_FURNITURE = 0, 1, 2, 3

    def __init__(self, slot):
        self.slot, self.rng = slot, random.Random(0)
        self.inventory, self.draws, self.stamina, self.xp, self.essence = {}, 0, 0, 0, 0
        self.charging = False
        self.location = 0
        self.grids = [Grid(self, 0, W), Grid(self, 1, TOWN)]
        self.node = None
        self.calls = []
        self.shakes = []        # (kind, trauma) of every node shake the GML asked for

    # -- helpers for the tests --
    def put(self, loc, name, x, y, ctx=None, **fields):
        """Write a node, replacing a weed in the way (the saves hold random grass)."""
        g = self.grids[loc]
        for cx, cy in g.cells(OBJ_ID[name], x, y):
            i = g.index(cx, cy)
            blocker = g.struct["node_parent"][i] if i is not None else None
            if blocker is not None and blocker["prototype"].category_id == CAT["Grass"]:
                g.erase(blocker)
        node = g.write_raw(x, y, OBJ_ID[name], ctx)
        assert node is not None, (name, x, y)
        node.update(fields)
        return node

    def remove(self, loc, x, y):
        node = self.at(loc, x, y)
        assert node is not None, (loc, x, y)
        self.grids[loc].erase(node)

    def ground(self, loc, x0, y0, x1, y1, kind):
        g = self.grids[loc].struct
        for y in range(y0, y1):
            for x in range(x0, x1):
                g["node_terrain_ground_kind"][y * g["dims"].x + x] = GROUND[kind]

    def at(self, loc, x, y):
        """The node whose top-left cell is (x, y); a tree's own top-left corner is free, so look two cells on too."""
        g = self.grids[loc]
        for dx in (0, 2):
            i = g.index(x + dx, y)
            n = g.struct["node_parent"][i] if i is not None else None
            if n is not None and n["top_left_x"] == x and n["top_left_y"] == y:
                return n
        return None

    def enter(self, loc):
        self.location = loc
        for i, g in enumerate(self.grids):
            g.struct["is_setup"] = i == loc
        b = self.node.interp.builtins
        b["CURRENT_LOCATION_ID"] = loc
        b["GRID"] = self.grids[loc].struct
        for n in self.grids[loc].nodes():     # the room's renderers are created as the player arrives
            if n["renderer"] is None:
                self.grids[loc].draw(n)

    def item(self, name):
        return S(item_id=ITEM_ID[name], prototype=ITEM_PROTOS[ITEM_ID[name]])

    def give(self, item_id, count=1):
        name = ITEMS[item_id]
        self.inventory[name] = self.inventory.get(name, 0) + count

    # -- the engine functions the GML calls --
    def can_interact(self, node):
        cat = node["prototype"].category_id
        if cat == CAT["Crop"]:
            if node["ctx"] & CROP["NO_HARVEST"] or (node["ctx"] & CROP["MANAGED"] and node["managed_timer"] is not None):
                return False
            return node["stage"] == node["prototype"].max_stage
        if cat == CAT["Bush"]:
            return node["day_count"] >= node["prototype"].regrow_days
        if cat == CAT["Tree"]:
            return node["stage"] > 1
        return False

    def interact(self, node):
        claimed = self.node.interp.call("mistrimulti_farm_interact", node)   # the object.interact override
        if claimed is not None:
            return claimed
        if not self.can_interact(node):
            return False
        proto, cat = node["prototype"], node["prototype"].category_id
        grid = self.grids[self.location]
        if cat == CAT["Crop"]:
            self.give(proto.harvest, proto.count)
            destroy = not (node["ctx"] & CROP["MANAGED"])
            if proto.post_harvest_day_to_stage is not None:
                node["regrow_cycle"], node["day_count"], node["stage"] = True, 0, proto.post_harvest_day_to_stage.get(0)
                destroy = False
            if node["ctx"] & CROP["FORAGEABLE"]:
                destroy = True
            if destroy:
                grid.erase(node)
        elif cat == CAT["Bush"]:
            self.give(proto.harvest, proto.count)
            node["day_count"] = 0
        elif cat == CAT["Tree"] and node["has_fruit"]:
            self.give(ITEM_ID["fruit"], 2)
            node["has_fruit"], node["fruiting_days"] = False, 0
        return True

    def chop_node(self, grid, x, y, item, modifier, doppel):
        g = self.grids[grid["location_id"]]
        i = g.index(x, y)
        if grid["node_object_id"][i] is None:
            return False
        node = grid["node_parent"][i]
        cat = node["prototype"].category_id
        if cat == CAT["Tree"]:
            if x not in (node["top_left_x"] + 2, node["top_left_x"] + 3) or y not in (node["top_left_y"] + 2, node["top_left_y"] + 3):
                return None
            if item.quality + modifier < node["prototype"].minimum_quality:
                return None
            node["hitpoints"] -= min(item.damage + modifier, node["hitpoints"])
            if node["hitpoints"] <= 0:
                self.give(ITEM_ID["wood"], 2)
                if node["stage"] > 1:
                    variant, sx, sy, stump = node["variant_idx"], node["top_left_x"] + 2, node["top_left_y"] + 3, node["prototype"].stump_id
                    g.erase(node)
                    g.write(sx, sy, stump)["variant_idx"] = variant
                else:
                    g.erase(node)
            return True
        if cat == CAT["Stump"]:
            if item.quality + modifier < node["prototype"].minimum_quality:
                return None
            node["hitpoints"] -= min(item.damage + modifier, node["hitpoints"])
            if node["hitpoints"] <= 0:
                self.give(ITEM_ID["wood"], 1)
                g.erase(node)
            return True
        return False

    def pick_node(self, grid, x, y, item, modifier, effect, doppel):
        g = self.grids[grid["location_id"]]
        node = None
        for xx in range(2):
            for yy in range(2):
                i = g.index(x + xx, y + yy)
                if node is None and i is not None and grid["node_object_id"][i] is not None:
                    node = grid["node_parent"][i]
        if node is None:
            return self.PICK_NOTHING
        if node["prototype"].category_id == CAT["Rock"]:
            if item.quality == 5 or item.quality + modifier >= node["prototype"].minimum_quality:
                node["hitpoints"] -= min(item.damage + modifier, node["hitpoints"])
                if node["hitpoints"] <= 0:
                    self.give(ITEM_ID["ore_item"] if node["object_id"] == OBJ_ID["ore"] else ITEM_ID["stone_item"], 2)
                    g.erase(node)
                return self.PICK_ROCK
            return self.PICK_NOTHING
        if node["object_id"] == OBJ_ID["dig_site"]:
            self.dig(g, node)
            return self.PICK_DIG
        return self.PICK_NOTHING

    def dig(self, g, node):
        x, y = node["top_left_x"], node["top_left_y"]
        self.give(ITEM_ID["artifact"], 1)
        g.erase(node)
        g.write(x, y, OBJ_ID["dig_site_destroyed"])

    def shovel_node(self, grid, x, y, doppel):
        g = self.grids[grid["location_id"]]
        i = g.index(x // 2 * 2, y // 2 * 2)
        if i is not None and grid["node_object_id"][i] == OBJ_ID["dig_site"]:
            self.dig(g, grid["node_parent"][i])
            return 2 | 4
        return 0

    def builtins(self):
        e = self
        b = {
            "GRIDS": gml.GArray([g.struct for g in self.grids]), "GRID": self.grids[0].struct, "CURRENT_LOCATION_ID": 0,
            "LocationId": S(Farm=0, Town=1, Dungeon=2, LEN=3),
            "LOCATIONS": gml.GArray([S(forageables=0, dig_sites=0, serializable=True), S(forageables=3, dig_sites=1, serializable=True),
                                  S(forageables=2, dig_sites=0, serializable=True)]),
            "location_id_to_string": lambda i: ["farm", "town"][i],
            "ObjectCategory": S(CAT), "ObjectId": S(DigSite=OBJ_ID["dig_site"], DigSiteDestroyed=OBJ_ID["dig_site_destroyed"]),
            "NODE_PROTOTYPES": PROTOS, "ITEM_PROTOTYPES": ITEM_PROTOS, "ToolType": S(TOOL), "QualityId": S(LEN=6),
            "TerrainKind": S(Ground=1), "GroundKind": S(GROUND), "TileFlag": S(Placeable=1),
            "CropFlag": S(CROP), "ItemId": S(LEN=len(ITEMS)), "ItemUse": S(PlantSeed=1, PlantSapling=2),
            "PickResult": S(Nothing=0, Rock=1, DigSite=2, Furniture=3), "ShovelResult": S(GIVE_ESSENCE=2, GAIN_DIG_SITE_EXPERIENCE=4),
            "Skill": S(Archaeology=3), "XpValue": S(break_dig_spot=5),
            "InputId": S(UseToolCharged=7), "INPUT": S(check=lambda i: e.charging),
            "RangePattern": S(One=0, OneByThree=1), "quality_to_range_pattern": lambda q: 0 if q == 0 else 1,
            "ARI": S(give_item=lambda item, count=1: e.give(item, count),
                     gain_essence=lambda amount, x, y: setattr(e, "essence", e.essence + amount),
                     modify_stamina=lambda amount: setattr(e, "stamina", e.stamina + amount),
                     gain_xp=lambda skill, xp: setattr(e, "xp", e.xp + xp)),
            "object_id_to_object_category": lambda i: None if i is None else PROTOS[i].category_id,
            "object_id_to_string": lambda i: OBJECTS[i][0],
            "try_string_to_object_id": lambda s: OBJ_ID.get(s),
            "item_id_to_string": lambda i: ITEMS[i], "try_string_to_item_id": lambda s: ITEM_ID.get(s),
            "find_item_prototype": lambda oid: next((p for p in ITEM_PROTOS if p.get("object") == oid), None),
            "erase_object_node_by_parent": lambda grid, node: e.grids[grid["location_id"]].erase(node),
            "erase_object_renderer": lambda node: node.__setitem__("renderer", None),
            "set_collision_on_node": lambda *a: None,
            # NodeRendererUtils.gml: the shake of a node's renderer; the fx tables of Chop.gml / Pick.gml (values are made up)
            "traumatize": lambda r, amount: e.shakes.append(("t", amount)),
            "rot_traumatize": lambda r, amount: e.shakes.append(("rot", amount)),
            "fiddle_get": lambda key: FX[key],
            "can_interact": self.can_interact, "interact": self.interact,
            "chop_node": self.chop_node, "pick_node": self.pick_node, "shovel_node": self.shovel_node,
            "has_flag": lambda v, f: (v & f) == f, "instance_exists": lambda v: v is not None,
            "List": lambda: (lambda items: S(count=lambda: len(items), get=lambda i: items[i], push=items.append))([]),
            "point_distance": lambda a, b, c, d: ((a - c) ** 2 + (b - d) ** 2) ** 0.5,
            "abs": abs, "round": lambda v: int(v + 0.5) if v >= 0 else -int(-v + 0.5), "clamp": lambda v, lo, hi: max(lo, min(hi, v)),
            "mmapi_filter": lambda *a: None, "mmapi_override": lambda *a: None, "mmapi_on": lambda *a: None,
            # The farm has no buildings with an inside here (tests/test_buildings.py adds them).
            "DYNAMIC_GRIDS": S(get=lambda i: None, count=lambda: 0), "get_buildings": lambda: S(count=lambda: 0, get=lambda i: None),
        }
        return b

    def doppel(self):
        return S(resolve=lambda: self.calls.append("resolve"))

    # -- the game's daily growth, run by whichever game executes it --
    def new_day(self):
        rng = self.rng
        for g in self.grids:
            for node in g.nodes():
                cat = node["prototype"].category_id
                if cat == CAT["Crop"]:
                    top = node["prototype"].max_stage
                    node["day_count"] += 1
                    if node["stage"] < top:
                        node["stage"] += 1
                    elif node["regrow_cycle"] and node["stage"] == top - 1:
                        node["stage"] = top
                elif cat == CAT["Tree"]:
                    node["day_count"] += 1
                    node["stage"] = min(4, node["day_count"] // 2)
                    node["hitpoints"] = node["prototype"].hp[node["stage"]]
                elif cat in (CAT["Bush"], CAT["DigSite"], CAT["Grass"]):
                    node["day_count"] += 1
                    if cat == CAT["Grass"] and node["object_id"] == OBJ_ID["grass_small"] and rng.random() < 0.4:
                        x, y, v = node["top_left_x"], node["top_left_y"], node["variant_idx"]
                        g.erase(node)
                        g.write_raw(x, y, OBJ_ID["grass_medium"])["variant_idx"] = v
            for _ in range(6):   # spawns: random grass and a forageable
                g.write(rng.randrange(g.size), rng.randrange(g.size), OBJ_ID["grass_small"])
            g.write(rng.randrange(g.size // 2) * 2, rng.randrange(g.size // 2) * 2, OBJ_ID["mushroom"], CROP["FORAGEABLE"] | CROP["SPAWN_GROWN"])


class FarmNode(GmlNode):
    extra_files = ("MistriMultiBuildings.gml", "MistriMultiFarm.gml")

    def builtins(self):
        self.engine = Engine(self.slot)
        return self.engine.builtins()

    def setup(self):
        self.engine.node = self
        self.rt["enabled"] = True
        self.interp.functions["mistrimulti_farm_new_doppel"] = self.engine.doppel   # `new TangoDoppel()` is engine-only


class Driver:
    """What MistriMultiBoot.gml does for this feature each bridge tick, and the peer fields it validates."""

    def __init__(self, game):
        self.game, self.node = game, game.node
        self.room, self.x, self.y = "farm:undefined", 128, 128
        self.node.interp.call("mistrimulti_farm_register_events")

    def frame(self):
        return {"room": self.room, "x": self.x, "y": self.y}

    def tick(self, now):
        self.node.call("mistrimulti_farm_tick")


def populate(e):
    """The farm and town as one save would hold them (cell coordinates are the node's top-left cell)."""
    e.ground(0, 2, 6, 13, 13, "Soil")
    e.put(0, "turnip", 2, 6, stage=4, day_count=4)
    e.put(0, "turnip", 4, 6, stage=2, day_count=2)
    e.put(0, "strawberry", 6, 6, stage=4, day_count=4)
    e.put(0, "mushroom", 18, 10, ctx=CROP["FORAGEABLE"], stage=1)
    e.put(0, "oak", 2, 14, stage=4, day_count=8, hitpoints=8, has_fruit=True)     # trunk cells x 4..5, y 16..17
    e.put(0, "oak", 12, 14, stage=0)
    e.put(0, "stone", 16, 2, hitpoints=6)
    e.put(0, "ore", 16, 6, hitpoints=8)
    e.put(0, "oak_stump", 8, 16)
    e.put(0, "berry_bush", 12, 0, day_count=3)
    e.put(0, "dig_site", 0, 16)
    e.put(0, "fence", 8, 0, cardinal_index=0)
    e.put(0, "sprinkler", 10, 0, cardinal_index=0)
    e.put(0, "chest", 6, 0, cardinal_index=0)
    e.put(0, "house", 0, 0)
    r = random.Random(5)
    for _ in range(30):            # weeds along the north and south edges, away from where the tests plant
        e.grids[0].write_raw(r.randrange(W), r.choice([3, 4, 5, 18, 19]), OBJ_ID["grass_small"])
    e.put(1, "mushroom", 4, 4, ctx=CROP["FORAGEABLE"], stage=1)
    e.put(1, "stone", 6, 6, hitpoints=6)
    e.put(1, "dig_site", 0, 0)
    e.put(1, "oak_stump", 6, 2)


def view(game):
    """Every synchronised node of every location: (location, x, y) -> (object, GML signature)."""
    node, out = game.node, {}
    for g in node.engine.grids:
        for n in g.nodes():
            cat = n["prototype"].category_id
            if cat == CAT["Building"] or (cat == CAT["Furniture"] and not (n["prototype"].fence or n["prototype"].sprinkler is not None)):
                continue
            out[(g.loc, n["top_left_x"], n["top_left_y"])] = (OBJECTS[n["object_id"]][0], node.call("mistrimulti_farm_signature", n))
    return out


def setup_world(seed, guests=2, **faults):
    world = World(seed, {i: FarmNode for i in range(guests + 1)}, **faults)
    for game in world.games.values():
        game.feature = Driver(game)
        populate(game.node.engine)
        game.node.engine.rng = random.Random(1000 + game.slot)
        game.node.engine.enter(0)
    return world


def assert_same(world, what):
    host = view(world.games[0])
    for slot, game in world.games.items():
        if slot == 0:
            continue
        guest = view(game)
        diff = sorted(set(host) ^ set(guest)) + sorted(k for k in host if k in guest and host[k] != guest[k])
        assert not diff, f"{what}: game {slot} differs from the host at {diff[:6]} ({len(diff)} nodes)"


def assert_clean(world):
    for game in world.games.values():
        debug = game.node.call("mistrimulti_events_debug")
        farm = game.node.rt["farm"]
        assert debug["errors"] == 0 and debug["backlog"] == 0, (game.slot, debug, game.warnings[:3])
        assert farm["errors"] == 0, (game.slot, farm["errors"], game.warnings[:3])
        assert len(farm["pending_keys"]) == 0, (game.slot, "unpublished changes left over")


def place(game, x, y):
    """Where the player stands, in cells."""
    game.feature.x, game.feature.y = x * 8 + 4, y * 8 + 4


def swing(game, tool, cells, pattern=0, charged=False):
    """What the Tool state does: filter the targets, then call the tool's function for every cell left.
    Returns the number of cells the hook took out of the swing."""
    e = game.node.engine
    e.charging = charged
    item = e.item(tool)
    targets = [vec(x, y) for x, y in cells]
    lst = S(count=lambda: len(targets), get=lambda i: targets[i], push=targets.append)
    out = game.node.call("mistrimulti_farm_tool_targets", lst,
                         S(item=item, range_pattern=pattern, x=cells[0][0], y=cells[0][1], cardinal=0))
    kept = targets if out is None else [out["get"](i) for i in range(out["count"]())]
    grid = e.grids[e.location].struct
    for cell in kept:
        proto = item.prototype
        modifier = 0 if pattern == 0 else -1
        if proto.tool_type == TOOL["Axe"]:
            e.chop_node(grid, cell.x, cell.y, proto, modifier, None)
        elif proto.tool_type == TOOL["PickAxe"]:
            e.pick_node(grid, cell.x, cell.y, proto, modifier, None, None)
        else:
            e.shovel_node(grid, cell.x, cell.y, None)
    return len(targets) - len(kept)


def next_swing(world, game):
    """Time passes between two swings, so the second is a new one and not the first still in progress."""
    world.run(1500)
    game.node.rt["ticks"] += 200


# ---- scenarios --------------------------------------------------------------------------------------------------------

def test_join_snapshot():
    world = setup_world(31, loss=0.05, dup=0.03, jitter=40)
    host, g1, g2 = (world.games[i].node for i in range(3))
    # The guests loaded an older save: stale growth, a felled tree, an extra weed, a missing rock, a changed fence.
    e = g1.engine
    e.at(0, 2, 6)["stage"] = 1
    e.remove(0, 2, 14)
    e.put(0, "grass_small", 19, 19)
    e.remove(0, 16, 2)
    e.at(0, 8, 0)["cardinal_index"] = 1
    e = g2.engine
    e.remove(1, 4, 4)
    e.put(1, "stone", 8, 0)
    e.put(0, "chest", 14, 0)           # not ours: must survive untouched
    # The host has moved on since: it harvested, and a new weed grew.
    host.engine.at(0, 4, 6)["stage"] = 3
    host.engine.put(0, "grass_medium", 18, 18)
    world.run(12000)
    assert_same(world, "join snapshot")
    assert g2.engine.at(0, 14, 0) is not None, "a chest the farm sync does not own was removed"
    assert list(host.rt["farm"]["ids"]) == [0, 1], "the farm and the town are synchronised, the mines (id 2) are not"
    digests = [[loc["digest"] for loc in game.node.call("mistrimulti_farm_debug")["locs"]] for game in world.games.values()]
    assert digests[0] == digests[1] == digests[2] and all(d != 0 for d in digests[0]), digests   # what the debug function shows
    assert_clean(world)
    print("PASS: join: stale saves converge by digests and chunks (changed, missing and extra nodes, two locations), "
          "unrelated objects untouched")


def test_host_changes():
    world = setup_world(32, loss=0.08, dup=0.05, jitter=60)
    host = world.games[0].node
    world.run(6000)
    assert_same(world, "initial")
    e = host.engine
    # The host's own play, using the game's own code paths: nothing special for the sync to hook.
    assert e.interact(e.at(0, 2, 6)) is True and e.inventory == {"turnip": 1}
    e.remove(0, 8, 16)
    e.put(0, "turnip", 8, 8, stage=0)
    e.remove(0, 8, 0)
    world.run(5000)
    assert_same(world, "host changes")
    # The daily growth ran in the host: crops, trees, bushes, new weeds and forageables follow. The guests ran
    # their own, different, growth too (they may or may not have gone through the sleep sequence).
    e.new_day()
    host.call("mistrimulti_farm_new_day", S(total_days=2))
    for game in list(world.games.values())[1:]:
        game.node.engine.new_day()
        game.node.call("mistrimulti_farm_new_day", S(total_days=2))
    world.run(15000)
    assert_same(world, "day change")
    assert_clean(world)
    print("PASS: host changes (harvest, removal, planting, daily growth and spawns) reach every guest; "
          "the guests' own growth is overwritten")


def test_guest_harvest():
    world = setup_world(33, guests=3, loss=0.1, dup=0.2, jitter=50)
    host, g1, g2, g3 = (world.games[i].node for i in range(4))
    world.run(5000)
    assert_same(world, "initial")
    for i in (1, 2, 3):
        place(world.games[i], 4, 8)
    # Two guests press harvest on the same ripe turnip before either hears the other's result.
    for guest in (g1, g2):
        assert guest.engine.interact(guest.engine.at(0, 2, 6)) is True    # claimed by the hook: nothing happens yet
        assert guest.engine.inventory == {} and guest.engine.at(0, 2, 6) is not None
    world.run(5000)
    got = sorted(g.engine.inventory.get("turnip", 0) for g in (g1, g2))
    assert got == [0, 1], got                      # exactly one produce, in the harvester's own inventory
    assert host.engine.inventory == {} and g3.engine.inventory == {}
    # The engine's own harvest (which removed the crop) is not mistaken for a hand-made removal: one request each.
    assert [g.rt["ev"]["next_request"] for g in (g1, g2)] == [2, 2], [g.rt["ev"]["next_request"] for g in (g1, g2)]
    assert host.engine.at(0, 2, 6) is None and g3.engine.at(0, 2, 6) is None
    assert_same(world, "after the harvest")
    # A regrowing crop stays and starts over; pressing again at once does nothing more.
    assert g3.engine.interact(g3.engine.at(0, 6, 6)) is True
    world.run(3000)
    assert g3.engine.inventory == {"strawberry": 2}, g3.engine.inventory
    berry = host.engine.at(0, 6, 6)
    assert berry["stage"] == 3 and berry["regrow_cycle"] is True and g1.engine.at(0, 6, 6)["stage"] == 3
    assert g3.engine.interact(g3.engine.at(0, 6, 6)) is False            # not ripe here either: the engine's own answer
    world.run(2000)
    assert g3.engine.inventory == {"strawberry": 2}
    # Bush, fruit tree and a forageable.
    place(world.games[1], 12, 2)
    assert g1.engine.interact(g1.engine.at(0, 12, 0)) is True
    place(world.games[2], 4, 18)
    assert g2.engine.interact(g2.engine.at(0, 2, 14)) is True
    world.run(4000)
    assert g1.engine.inventory.get("berry") == 3 and g2.engine.inventory.get("fruit") == 2
    assert host.engine.at(0, 2, 14)["has_fruit"] is False and host.engine.at(0, 12, 0)["day_count"] == 0
    assert_same(world, "bush and tree")
    # A guest that is far away is refused and corrected: no produce, and nothing changes on the host.
    place(world.games[3], 19, 19)
    host.engine.at(0, 6, 6)["stage"] = 4          # ripe again on the host, and the guests hear of it
    world.run(3000)
    assert g3.engine.interact(g3.engine.at(0, 6, 6)) is True
    world.run(3000)
    assert g3.engine.inventory == {"strawberry": 2} and host.engine.at(0, 6, 6)["stage"] == 4
    assert_same(world, "refused harvest")
    assert_clean(world)
    print("PASS: guest harvests: one produce for two racing guests, regrowing crop, bush and fruit tree, "
          "all in the harvester's own inventory; out-of-reach refused")


def test_guest_tools():
    world = setup_world(34, loss=0.06, dup=0.04, jitter=50)
    host, g1, g2 = (world.games[i].node for i in range(3))
    world.run(5000)
    place(world.games[1], 5, 19)
    # The oak (hp 8, trunk cells x 4..5, y 16..17): the swing never hits it locally; the host answers; the chop
    # then runs in the swinger's own game.
    tree = g1.engine.at(0, 2, 14)
    assert swing(world.games[1], "axe", [(4, 16)]) == 1
    assert tree["hitpoints"] == 8, "the swing hit the tree locally before the host agreed"
    world.run(3000)
    assert host.engine.at(0, 2, 14)["hitpoints"] == 6 and g1.engine.at(0, 2, 14)["hitpoints"] == 6 and g2.engine.at(0, 2, 14)["hitpoints"] == 6
    assert g1.engine.stamina == -4 and g1.engine.essence == 1
    assert swing(world.games[1], "axe", [(2, 15)]) == 0          # not the trunk: left to the engine
    for _ in range(3):
        next_swing(world, world.games[1])
        swing(world.games[1], "axe", [(5, 17)])
    world.run(3000)
    assert host.engine.at(0, 2, 14) is None and g2.engine.at(0, 2, 14) is None and g1.engine.at(0, 2, 14) is None
    stumps = [(n["top_left_x"], n["top_left_y"]) for n in host.engine.grids[0].nodes() if n["object_id"] == OBJ_ID["oak_stump"]]
    assert (4, 16) in stumps, stumps       # the stump the felled oak leaves, at its trunk
    assert g1.engine.inventory.get("wood", 0) == 2 and host.engine.inventory == {} and g2.engine.inventory == {}
    assert_same(world, "felled tree")
    # Ore needs the good pickaxe; the plain one is refused by the host.
    place(world.games[1], 17, 9)
    swing(world.games[1], "pickaxe", [(16, 6)])
    world.run(3000)
    assert host.engine.at(0, 16, 6)["hitpoints"] == 8 and g1.engine.inventory.get("ore_item", 0) == 0
    for _ in range(3):
        next_swing(world, world.games[1])
        swing(world.games[1], "pickaxe_gold", [(16, 6)])
    world.run(3000)
    assert host.engine.at(0, 16, 6) is None and g1.engine.at(0, 16, 6) is None and g1.engine.inventory.get("ore_item") == 2
    assert_same(world, "ore")
    # Dig site by shovel, by the other guest.
    place(world.games[2], 2, 18)
    swing(world.games[2], "shovel", [(0, 16)])
    world.run(3000)
    assert g2.engine.inventory.get("artifact") == 1 and g2.engine.xp == 5 and host.engine.inventory == {}
    assert host.engine.at(0, 0, 16)["object_id"] == OBJ_ID["dig_site_destroyed"] and g1.engine.at(0, 0, 16)["object_id"] == OBJ_ID["dig_site_destroyed"]
    # A swing from far away changes nothing; a swing still being charged asks for nothing.
    place(world.games[1], 19, 0)
    swing(world.games[1], "axe", [(14, 16)])
    world.run(3000)
    assert host.engine.at(0, 12, 14)["hitpoints"] == g1.engine.at(0, 12, 14)["hitpoints"]
    place(world.games[1], 13, 16)
    swing(world.games[1], "pickaxe_gold", [(16, 2)], pattern=1, charged=True)
    assert len(g1.rt["farm"]["swing"]) == 0   # nothing asked while the charge button is held
    world.run(2000)
    assert host.engine.at(0, 16, 2) is not None
    assert_same(world, "after refused swings")
    assert_clean(world)
    print("PASS: guest tools: axe, pickaxe and shovel are decided by the host, the yield goes to the swinger, "
          "bad tool / reach / charging refused")


def test_hit_shake():
    world = setup_world(41, loss=0.04, jitter=40)
    host, g1, g2 = (world.games[i].node for i in range(3))
    world.run(5000)
    place(world.games[1], 5, 19)
    # A guest's axe on the oak (stage 4, hp 8 -> 6): the host's and the other guest's copies shake with the table of the
    # oak's stage; the swinger's own game does it in chop_node (here a stub), and nobody gets items or stamina.
    swing(world.games[1], "axe", [(4, 16)])
    world.run(3000)
    assert host.engine.at(0, 2, 14)["hitpoints"] == 6
    assert host.engine.shakes == [("rot", 0.5)] and g2.engine.shakes == [("rot", 0.5)], (host.engine.shakes, g2.engine.shakes)
    assert g1.engine.shakes == [], "the swinger's copy must not shake twice"
    assert host.engine.inventory == {} and g2.engine.inventory == {} and g2.engine.stamina == 0
    # The same hit again on a stump (hp 4 -> 2) and a rock (hp 8 -> 5): the plain shake of each table.
    place(world.games[1], 9, 19)
    swing(world.games[1], "axe", [(8, 16)])
    place(world.games[1], 17, 9)
    swing(world.games[1], "pickaxe_gold", [(16, 6)])
    world.run(3000)
    assert host.engine.at(0, 8, 16)["hitpoints"] == 2 and host.engine.at(0, 16, 6)["hitpoints"] == 5
    assert host.engine.shakes == [("rot", 0.5), ("t", 0.7), ("t", 0.9)], host.engine.shakes
    assert g2.engine.shakes == host.engine.shakes, g2.engine.shakes
    # The blow that fells or breaks the node removes it without a shake (and without an item on the others).
    before = (len(host.engine.shakes), len(g2.engine.shakes))
    for _ in range(3):
        next_swing(world, world.games[1])
        place(world.games[1], 5, 19)
        swing(world.games[1], "axe", [(4, 16)])
    world.run(3000)
    assert host.engine.at(0, 2, 14) is None and g2.engine.at(0, 2, 14) is None
    assert len(host.engine.shakes) == before[0] + 2 and len(g2.engine.shakes) == before[1] + 2, "only the non-lethal hits shake"
    assert host.engine.inventory == {} and g2.engine.inventory == {}
    # A guest standing in the town has no renderer for the farm's nodes: nothing to shake there.
    g2.engine.enter(1)
    n = len(g2.engine.shakes)
    place(world.games[1], 17, 9)
    next_swing(world, world.games[1])
    swing(world.games[1], "pickaxe_gold", [(16, 6)])
    world.run(3000)
    assert host.engine.at(0, 16, 6)["hitpoints"] == 2 and len(g2.engine.shakes) == n
    # A late joiner's snapshot of damaged nodes does not shake them.
    g2.engine.enter(0)
    g1.engine.shakes.clear()
    for loc in (0, 1):
        old = g1.engine.grids[loc]
        for node in old.nodes():
            old.erase(node)
    populate(g1.engine)
    g1.engine.enter(0)
    g1.call("mistrimulti_events_reset")
    world.run(12000)
    assert g1.engine.at(0, 16, 6)["hitpoints"] == 2 and g1.engine.shakes == [], g1.engine.shakes
    # A node with no hitpoints left is going away, not being hit: the helper does not shake it (and a rise does not either).
    ls = host.rt["farm"]["locs"]["0"]
    rock = host.engine.at(0, 16, 6)
    n = len(host.engine.shakes)
    rock["hitpoints"] = 0
    host.call("mistrimulti_farm_hit_shake", ls, rock, CAT["Rock"], 5)
    rock["hitpoints"] = 2
    host.call("mistrimulti_farm_hit_shake", ls, rock, CAT["Rock"], 1)
    assert len(host.engine.shakes) == n
    host.call("mistrimulti_farm_hit_shake", ls, rock, CAT["Rock"], 5)
    assert len(host.engine.shakes) == n + 1
    assert_same(world, "after the hits")
    assert_clean(world)
    print("PASS: hit shake: another player's non-lethal hit on a tree, stump or rock shakes it (host and guests), "
          "no drops, no double shake for the swinger, none when not in the room or on a snapshot")


def test_guest_edits():
    world = setup_world(35, loss=0.06, dup=0.04, jitter=50)
    host, g1, g2 = (world.games[i].node for i in range(3))
    world.run(5000)
    place(world.games[1], 9, 4)
    # Guest 1 plants a turnip, cuts a weed, places a fence, removes the old fence, charges the sprinkler.
    e = g1.engine
    e.put(0, "turnip", 8, 8, stage=0)
    weed = next(n for n in e.grids[0].nodes() if n["object_id"] == OBJ_ID["grass_small"] and n["top_left_y"] < 10)
    wx, wy = weed["top_left_x"], weed["top_left_y"]
    e.remove(0, wx, wy)
    e.put(0, "fence", 10, 4, cardinal_index=0)
    e.remove(0, 8, 0)
    e.at(0, 10, 0)["essence_supply"] = 3
    world.run(5000)
    for who, game in (("host", host), ("guest 2", g2)):
        assert game.engine.at(0, 8, 8) is not None and game.engine.at(0, 8, 8)["object_id"] == OBJ_ID["turnip"], who
        assert game.engine.at(0, wx, wy) is None and game.engine.at(0, 10, 4) is not None and game.engine.at(0, 8, 0) is None, who
        assert game.engine.at(0, 10, 0)["essence_supply"] == 3, who
    assert_same(world, "edits")
    # Both guests plant at the same spot: the first request wins, the second is told the cell is taken.
    for i in (1, 2):
        place(world.games[i], 9, 8)
        world.games[i].node.engine.put(0, "turnip", 10, 8, stage=0)
    world.run(5000)
    assert host.engine.at(0, 10, 8) is not None
    assert g1.engine.inventory.get("seed_turnip", 0) + g2.engine.inventory.get("seed_turnip", 0) == 1, \
        (g1.engine.inventory, g2.engine.inventory)
    assert_same(world, "racing plantings")
    # A planting on ground the host says is not soil (only the guest believes it is): undone, seed given back.
    place(world.games[1], 17, 14)
    g1.engine.ground(0, 16, 12, 18, 14, "Soil")
    g1.engine.put(0, "turnip", 16, 12, stage=0)
    world.run(5000)
    assert g1.engine.at(0, 16, 12) is None and host.engine.at(0, 16, 12) is None, "an unsound planting was kept"
    assert g1.engine.inventory.get("seed_turnip", 0) >= 1
    # A sapling is placed whole (the 6x6 square without corners).
    place(world.games[2], 14, 12)
    g2.engine.put(0, "oak", 12, 6, stage=0)
    world.run(5000)
    assert host.engine.at(0, 12, 6) is not None and g1.engine.at(0, 12, 6) is not None
    assert_same(world, "sapling")
    assert_clean(world)
    print("PASS: guest edits: planting, weeds, fences and sprinkler charge reach the host and everyone; "
          "a racing or unsound planting is undone and refunded")


def test_conflicts():
    world = setup_world(39, guests=3, loss=0.05, dup=0.04, jitter=40)
    host, g1, g2, g3 = (world.games[i].node for i in range(4))
    world.run(5000)
    assert_same(world, "initial")
    # A stale tile: guest 1 is cut off (not long enough to expire) while the host fells the sapling; its swing at the
    # sapling is only answered after the link is back, and the answer is a refusal: no wood, the tree is gone.
    world.net.partition(0, 1)
    host.engine.remove(0, 12, 14)
    place(world.games[1], 14, 19)
    assert swing(world.games[1], "axe", [(14, 16)]) == 1
    world.run(3000)
    assert g1.engine.at(0, 12, 14) is not None and g1.engine.inventory == {}
    world.net.partition(0, 1, False)
    world.run(6000)
    assert g1.engine.at(0, 12, 14) is None and g1.engine.inventory == {}, g1.engine.inventory
    assert_same(world, "stale tile")
    # The host's tree wears down under the request (another player's blows, not yet published by its scanner): the
    # answer carries the oak as the host had it, and the swinger's chop runs from that state, so the oak falls for
    # the swinger too, with its wood, although the swinger believed it still had all its hitpoints.
    original = host.interp.functions["mistrimulti_farm_request"]
    worn = []

    def wear(player, data, ctx):
        if not worn and data["a"] == "chop":
            worn.append(1)
            host.engine.at(0, 2, 14)["hitpoints"] = 2
        return original(player, data, ctx)
    host.call("mistrimulti_event_register", "farm_act", S(on_request=wear, on_result=host.interp.functions["mistrimulti_farm_result"],
                                                         on_reply=host.interp.functions["mistrimulti_farm_reply"]))
    place(world.games[1], 5, 19)
    assert g1.engine.at(0, 2, 14)["hitpoints"] == 8
    assert swing(world.games[1], "axe", [(4, 16)]) == 1
    world.run(3000)
    assert worn and g1.engine.at(0, 2, 14) is None and host.engine.at(0, 2, 14) is None
    assert g1.engine.inventory == {"wood": 2}, g1.engine.inventory
    assert_same(world, "worn oak")
    # The player leaves the room before the answer arrives: the plain yield is given instead of the engine's action.
    place(world.games[2], 4, 8)
    assert g2.engine.interact(g2.engine.at(0, 2, 6)) is True
    g2.engine.enter(1)         # the host still sees the player on the farm when the request arrives
    world.run(4000)
    world.games[2].feature.room = "town:undefined"
    assert g2.engine.inventory == {"turnip": 1}, g2.engine.inventory
    assert host.engine.at(0, 2, 6) is None and g2.engine.at(0, 2, 6) is None
    assert_same(world, "left the room")
    # Another location: a forageable in the town, harvested by the guest standing there.
    place(world.games[2], 4, 6)
    assert g2.engine.interact(g2.engine.at(1, 4, 4)) is True
    world.run(4000)
    assert g2.engine.inventory.get("mushroom") == 1 and host.engine.at(1, 4, 4) is None and g1.engine.at(1, 4, 4) is None
    assert_same(world, "town forageable")
    # A local change the host did not agree to (here: a rock blown up by a bomb, which the farm sync does not gate)
    # is put back when the digests come round; asking for them at once stands in for the minute timer.
    assert g3.engine.at(0, 16, 6) is not None
    g3.engine.remove(0, 16, 6)
    g3.rt["farm"]["hello"] = True
    world.run(5000)
    assert g3.engine.at(0, 16, 6) is not None and host.engine.at(0, 16, 6) is not None
    assert_same(world, "repaired")
    # A reply that is lost (the host restarted) or expired only makes the guest ask for the host's state again.
    g1.rt["farm"]["hello"] = False
    g1.call("mistrimulti_farm_reply", 0, None, S(kind="farm_act", id="x", lost=True, expired=False, mine=True))
    assert g1.rt["farm"]["hello"] is True
    world.run(4000)
    assert_clean(world)
    print("PASS: conflicts: stale tile refused and corrected, a player who leaves before the answer still gets the yield "
          "once, a second location, a disagreeing guest repaired by the digests, a lost reply")


def test_rejoin_and_gap():
    world = setup_world(36, loss=0.05, dup=0.03, jitter=40)
    host, g1, g2 = (world.games[i].node for i in range(3))
    world.run(5000)
    assert_same(world, "initial")
    # A guest re-enters its world: new event stream, and its grids are reloaded from the older save.
    for loc in (0, 1):
        old = g1.engine.grids[loc]
        for n in old.nodes():
            old.erase(n)
    populate(g1.engine)
    g1.engine.enter(0)
    host.engine.at(0, 6, 6)["stage"] = 3
    host.engine.remove(0, 2, 14)
    g1.call("mistrimulti_events_reset")
    world.run(12000)
    assert_same(world, "re-entry")
    # A guest cut off for longer than the 10 s expiry sees a gap and is brought up to date.
    world.net.partition(0, 2)
    host.engine.put(0, "turnip", 14, 10, stage=0)
    host.engine.remove(0, 16, 2)
    world.run(14000)
    world.net.partition(0, 2, False)
    world.run(12000)
    assert_same(world, "after the partition")
    assert_clean(world)
    print("PASS: a guest that re-enters its world, or was cut off past the expiry, is brought back by digests and chunks")


def test_hostile_input():
    world = setup_world(37, loss=0.02)
    host, g1, g2 = (world.games[i].node for i in range(3))
    world.run(5000)
    place(world.games[1], 4, 8)
    chest = host.engine.at(0, 6, 0)
    bad = [
        {}, {"a": 5}, {"a": "harvest"}, {"a": "harvest", "l": "farm", "x": 1, "y": 1}, {"a": "harvest", "l": 0, "x": -1, "y": 99999},
        {"a": "harvest", "l": 0, "x": 1.5, "y": 2}, {"a": "harvest", "l": 0, "x": 4, "y": 6},   # the young turnip
        {"a": "chop", "l": 0, "x": 4, "y": 16, "i": "pickaxe"},
        {"a": "chop", "l": 0, "x": 4, "y": 16, "i": 99}, {"a": "pick", "l": 7, "x": 16, "y": 6, "i": "pickaxe"},
        {"a": "edit", "l": 0}, {"a": "edit", "l": 0, "e": "x"}, {"a": "edit", "l": 0, "e": [1, [], ["a"], ["a", 5], ["a", ["bogus", 1, 2]]]},
        {"a": "edit", "l": 0, "e": [["a", ["house", 2, 2, 0]], ["a", ["chest", 4, 4, 0, 0]], ["a", ["turnip", 3, 3, 0, 0, 0, 0, -1]],
                                    ["a", ["oak", 8, 8, 4, 0, 99, 0, 1, 0]], ["a", "x"], ["a", ["turnip", "a", 3, 0, 0, 0, 0, -1]],
                                    ["c", 8, 0], ["r", 2, 6], ["s", 10, 0, 99999], ["r", 6, 0], ["s", 10, 0, "x"], ["c", "q", 1]]},
    ]
    for data in bad:
        assert g1.call("mistrimulti_event_request", "farm_act", data) is not None
    # Host-only traffic from a guest is ignored.
    g1.call("mistrimulti_event_emit", "farm_delta", {"l": 0, "n": [["oak", 2, 2, 4, 0, 5, 0, 1, 5]], "g": [[2, 6]]})
    g1.call("mistrimulti_event_emit", "farm_chunk", {"l": 0, "c": 0, "n": [], "e": 1})
    g1.call("mistrimulti_event_emit", "farm_digest", {"l": 0, "n": 1, "o": 0, "d": [1]})
    # Garbage from the host reaches a guest: wrong types and ranges everywhere.
    for data in [{}, {"l": 0, "n": "x", "g": 5}, {"l": 0, "n": [[]], "g": [[1]]}, {"l": 9, "n": []}, {"l": 0, "n": [["oak", 1, 1]]},
                 {"l": 0, "n": [["oak", 2, 2, 4, 0, 5, 0, 1, 1e12]]}, {"l": 0, "n": [["house", 2, 2, 0]]},
                 {"l": 0, "n": [["turnip", 3, 3, 0, 0, 0, 0, -1]]}, {"l": 0, "n": [["bogus", 3, 3, 0]]},
                 {"l": 0, "n": [["turnip", "x", 3, 0, 0, 0, 0, -1]]}, {"l": 0, "n": [["oak", 19, 19, 4, 0, 5, 0, 1, 5]]}]:
        host.call("mistrimulti_event_emit", "farm_delta", data, 2)
        host.call("mistrimulti_event_emit", "farm_chunk", dict(data, c=0, e=1), 2)
        host.call("mistrimulti_event_emit", "farm_digest", dict(data, o=-5, d=[1, 2]), 2)
    for data in [{}, {"l": 0, "c": "x"}, {"l": 0, "c": [1e9, -1, 2.5, "q"]}, {"l": 5, "c": [1]}]:
        g2.call("mistrimulti_event_emit", "farm_want", data, 0)
    world.run(5000)
    assert g1.engine.at(0, 6, 0) is not None and host.engine.at(0, 6, 0) is chest
    assert host.engine.at(0, 4, 6)["stage"] == 2, "an unripe crop was harvested"
    assert_same(world, "hostile input")
    for game in world.games.values():
        assert game.node.rt["farm"]["errors"] == 0, (game.slot, game.warnings[:3])
    assert_clean(world)
    print("PASS: malformed or forged requests, results, deltas, digests and wants are ignored without errors; "
          "nothing else changes")


def test_bulk():
    world = setup_world(38, guests=3, loss=0.05, dup=0.03, jitter=40)
    host = world.games[0].node
    world.run(8000)
    e = host.engine
    # Fill the farm with weeds at once, then clear half of them again.
    n = 0
    for y in range(W):
        for x in range(W):
            if e.grids[0].write_raw(x, y, OBJ_ID["grass_small"]) is not None:
                n += 1
    assert n > 150
    world.run(300)
    for i, node in enumerate(e.grids[0].nodes()):
        if node["object_id"] == OBJ_ID["grass_small"] and i % 2 == 0:
            e.grids[0].erase(node)
    world.run(20000)
    assert_same(world, "bulk")
    for game in world.games.values():
        assert game.max_frame <= 16384
    assert_clean(world)
    print(f"PASS: {n} new weeds and a mass removal on the host converge within the event budgets (frames <= 16 KB)")


if __name__ == "__main__":
    test_join_snapshot()
    test_host_changes()
    test_guest_harvest()
    test_guest_tools()
    test_hit_shake()
    test_guest_edits()
    test_conflicts()
    test_rejoin_and_gap()
    test_hostile_input()
    test_bulk()
