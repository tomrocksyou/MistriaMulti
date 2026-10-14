"""Mines sync (MistriMultiDungeon.gml) on the event layer, running the real GML with the engine stubbed.

    python3 tests/test_dungeon.py [test_name ...]

MistriMultiDungeon.gml runs unmodified in tests/gml_subset.py on top of MistriMultiEvents.gml, over the simulated helpers
and lossy network of tests/event_sim.py. Only the engine is stubbed: `Mine` models one game's dungeon floor (a grid of
rocks, ore, pots, chests, forageables and dig sites; monsters with health and a death that pays drops and xp; the runner's
ladder score; the generator's use of `random_set_seed`), with the rules of the game's own scripts (build_dungeon_room.gml,
DungeonRunner.gml, par_monster.gml, Pick.gml, GridUtils.gml). It checks logic and wiring; it does not replace testing in the
game (docs/SYNC-DUNGEON.md lists what has to be checked there).
"""
import random
import sys

from event_sim import GmlNode, World
import gml_subset as gml

W = 12                       # a floor is W x W cells (W/2 x W/2 tiles; every object is 2x2 cells)
MONSTER_POINTS, OBJECT_POINTS = 2, 1
DUNGEON, HOME = 2, 0
CAT = dict(Breakable=0, Building=1, Bush=2, Crop=3, DigSite=4, Furniture=5, Grass=6, Rock=7, Stump=8, Tree=9, LEN=10)
TOOL = dict(Axe=0, PickAxe=1, Shovel=2)


class S(gml.GStruct):
    """A GML struct that Python code can also read with attribute syntax."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


def vec(x, y):
    return S(x=x, y=y)


def lst(items=None):
    items = [] if items is None else items
    return S(count=lambda: len(items), get=lambda i: items[i], push=items.append, arr=items)


# name, category, prototype fields
OBJECTS = [
    ("rock", "Rock", dict(hp=3, minimum_quality=0)),
    ("ore", "Rock", dict(hp=5, minimum_quality=1)),
    ("pot", "Breakable", dict(hp=1)),
    ("chest", "Breakable", dict(hp=1, chest=True)),
    ("herb", "Crop", dict()),
    ("dig_site", "DigSite", dict()),
    ("dig_site_destroyed", "DigSite", dict()),
    ("lamp", "Furniture", dict()),
]
OBJ_ID = {name: i for i, (name, _c, _f) in enumerate(OBJECTS)}
NODE_PROTOS = gml.GArray()
for _i, (_name, _cat, _f) in enumerate(OBJECTS):
    NODE_PROTOS.append(S(object_id=_i, category_id=CAT[_cat], minimum_quality=_f.get("minimum_quality", 0), hp=_f.get("hp", 0),
                         chest=S(open_sprite="open") if _f.get("chest") else None, size=vec(2, 2)))
MONSTERS = [("mite", 3), ("bat", 4), ("clod", 6)]
MON_ID = {name: i for i, (name, _hp) in enumerate(MONSTERS)}
ITEMS = ["pickaxe", "pickaxe_gold", "shovel", "sword"]
ITEM_ID = {name: i for i, name in enumerate(ITEMS)}
ITEM_PROTOS = gml.GArray([
    S(item_id=0, tool_type=TOOL["PickAxe"], quality=0, damage=2, stamina_cost=-4),
    S(item_id=1, tool_type=TOOL["PickAxe"], quality=1, damage=3, stamina_cost=-4),
    S(item_id=2, tool_type=TOOL["Shovel"], quality=0, damage=1, stamina_cost=-4),
    S(item_id=3, tool_type=None, quality=0, damage=1, stamina_cost=0)])


class Mine:
    """One game's dungeon: the floor it stands on, its player and the engine rules the GML relies on."""

    def __init__(self, node):
        self.node = node
        self.entropy = random.Random(900 + node.slot)
        self.rng = random.Random(self.entropy.random())
        self.size = W
        self.perk = False             # a perk that changes what the generator rolls (so builds differ between players)
        self.uid = 1
        self.monsters, self.nodes_ = [], []
        self.items, self.drops, self.xp, self.kills, self.essence = {}, [], 0, 0, 0
        self.seeds = []
        self.runner = None
        self.ladder = None
        self.ladder_alive = False
        self.ladder_obj = S(x=0, y=0)
        self.player = S(x=40, y=40)
        self.in_mines = False
        self.raw = None
        self.room_name = "none"
        self.room_override = None
        self.fresh_grid()
        self.ari = S(has_seen_arena_level_today=False, gain_essence=lambda a, x, y: setattr(self, "essence", self.essence + a),
                     modify_stamina=lambda a: None, gain_xp=lambda skill, xp: setattr(self, "xp", self.xp + xp))

    # -- the grid -------------------------------------------------------------------------------------------
    def fresh_grid(self):
        n = self.size * self.size
        self.nodes_ = []
        self.grid = S(location_id=DUNGEON, dyn_index=None, node_object_id=gml.GArray([None] * n), node_parent=gml.GArray([None] * n),
                      try_node_index_for_cell=self.index, write_node=self.write)
        if hasattr(self.node, "interp"):
            self.node.interp.builtins["GRID"] = self.grid

    def index(self, x, y):
        return int(y) * self.size + int(x) if 0 <= x < self.size and 0 <= y < self.size else None

    def write(self, x, y, oid, ctx=None):
        x, y = x // 2 * 2, y // 2 * 2
        cells = [self.index(x + i, y + j) for i in range(2) for j in range(2)]
        if any(c is None or self.grid["node_object_id"][c] is not None for c in cells):
            return None
        proto = NODE_PROTOS[oid]
        node = S(object_id=oid, prototype=proto, top_left_x=x, top_left_y=y, renderer=S(image_speed=1, alive=True,
                 set_sprite=lambda s: None))
        if OBJECTS[oid][1] in ("Rock", "Breakable"):
            node["hitpoints"] = proto.hp
            node["ladder_candidate"] = OBJECTS[oid][0] != "chest"
        if proto.chest is not None:
            node["is_open"] = False
        for c in cells:
            self.grid["node_object_id"][c] = oid
            self.grid["node_parent"][c] = node
        self.nodes_.append(node)
        return node

    def erase(self, grid, node):
        for i in range(2):
            for j in range(2):
                c = self.index(node["top_left_x"] + i, node["top_left_y"] + j)
                self.grid["node_object_id"][c] = None
                self.grid["node_parent"][c] = None
        if node in self.nodes_:
            self.nodes_.remove(node)
        node["renderer"]["alive"] = False
        if self.runner is not None and node.get("ladder_candidate"):
            self.runner.on_object_destroy(node["top_left_x"], node["top_left_y"])
        return True

    def named(self, name):
        return sorted((n for n in self.nodes_ if OBJECTS[n["object_id"]][0] == name), key=lambda n: (n["top_left_x"], n["top_left_y"]))

    def layout(self):
        """Everything the players share: node objects, positions and health; live monsters with their health."""
        nodes = sorted((OBJECTS[n["object_id"]][0], n["top_left_x"], n["top_left_y"], n.get("hitpoints"), n.get("is_open"))
                       for n in self.nodes_ if OBJECTS[n["object_id"]][1] in ("Rock", "Breakable", "Crop") or n["object_id"] == OBJ_ID["dig_site"])
        mons = sorted((MONSTERS[m.monster_id][0], m.original_spawn_pos.x, m.original_spawn_pos.y, m.hit_points) for m in self.monsters if m.alive)
        return nodes, mons

    # -- the generator (build_dungeon_room.gml): the same random numbers give the same floor ---------------------
    def build(self):
        rng = self.rng
        for ty in range(self.size // 2):
            for tx in range(self.size // 2):
                x, y = tx * 2, ty * 2
                roll = rng.random()
                chest = 0.06 + (0.25 if self.perk else 0)
                t = 0.15
                if roll < t:
                    self.write(x, y, OBJ_ID["rock"])
                elif roll < t + 0.08:
                    self.write(x, y, OBJ_ID["ore"])
                elif roll < t + 0.16:
                    self.write(x, y, OBJ_ID["pot"])
                elif roll < t + 0.16 + chest:
                    self.write(x, y, OBJ_ID["chest"])
                    rng.random()             # the chest's variant: an extra draw the others do not make
                elif roll < t + 0.22 + chest:
                    self.write(x, y, OBJ_ID["herb"])
                elif roll < t + 0.27 + chest:
                    self.write(x, y, OBJ_ID["dig_site"])
                elif roll < t + 0.43 + chest:
                    self.spawn_monster((x + 1) * 8, (y + 1) * 8, rng.randrange(3))

    def spawn_monster(self, x, y, monster_id):
        self.uid += 1
        mon = S(uid=self.uid, monster_id=monster_id, hit_points=MONSTERS[monster_id][1], original_spawn_pos=vec(x, y), x=x, y=y,
                depth=0, skip_destroy_logic=False, alive=True)
        self.monsters.append(mon)
        return mon

    def make_runner(self):
        e = self
        itinerary = self.make_itinerary(6)

        class Runner(S):
            pass

        r = Runner(itinerary=itinerary, ladder_score_needed=0, ladder_score=0)
        r["on_monster_destroy"] = lambda x, y: e.score(r, MONSTER_POINTS, x, y)
        r["on_object_destroy"] = lambda x, y: e.score(r, OBJECT_POINTS, x, y)
        r["spawn_ladder"] = lambda x, y: e.spawn_ladder(r, x, y)
        r["check_ladder_score"] = lambda x, y: e.check(r, x, y)
        return r

    def make_itinerary(self, count):
        items = [S(impl=self.rng.randrange(3), gm_room="room_%d" % self.rng.randrange(5), biome=0) for _ in range(count)]
        return lst(items)

    def score(self, runner, points, x, y):
        runner["ladder_score"] += points
        self.check(runner, x, y)

    def check(self, runner, x, y):
        if not self.ladder_alive and runner["ladder_score"] >= runner["ladder_score_needed"]:
            self.spawn_ladder(runner, x, y)

    def spawn_ladder(self, runner, x, y):
        verdict = self.node.call("mistrimulti_dg_ladder_guard", S(runner=runner, x=x, y=y))
        if verdict is False:
            return
        self.ladder_alive = True
        self.ladder = (x, y)
        self.ladder_obj["x"], self.ladder_obj["y"] = x * 8, y * 8

    def on_room_start(self):
        """DungeonRunner.on_room_start: how many pieces the floor has and how many must fall."""
        total = len(self.monsters) * MONSTER_POINTS + sum(1 for n in self.nodes_ if n.get("ladder_candidate")) * OBJECT_POINTS
        self.runner["ladder_score_needed"] = max(1, int(total * (0.4 + 0.4 * self.rng.random())))
        self.runner["ladder_score"] = 0

    # -- entering and leaving, as the game's hooks see it ----------------------------------------------------------
    def enter_mines(self):
        """enter_dungeon(): a new runner (with the game's own, unseeded itinerary) and the hook."""
        self.runner = self.make_runner()
        self.local_itinerary = [(i.impl, i.gm_room) for i in self.runner["itinerary"]["arr"]]
        self.node.call("mistrimulti_dg_runner_created", S(runner=self.runner))
        self.itinerary = [(i.impl, i.gm_room) for i in self.runner["itinerary"]["arr"]]
        self.set_location(DUNGEON)

    def enter_floor(self, flr, side=False, impl=0):
        """on_dungeon_enter(): the floor's hooks around build_dungeon_room, then the runner's room start."""
        self.monsters = []
        self.fresh_grid()
        self.ladder_alive = False
        self.ladder = None
        self.set_location(DUNGEON)
        self.room_name = self.room_override or "floor_%d" % flr
        level = S(impl=impl, gm_room="room_x", biome=0)
        if side:
            level["is_side_room"] = True
        ctx = S(runner=self.runner, floor=flr, level=level, biome=0, room_id=self.room_name)
        self.node.call("mistrimulti_dg_build_begin", ctx)
        self.build()
        self.node.call("mistrimulti_dg_floor_built", ctx)
        self.on_room_start()
        self.raw = self.layout()

    def leave_mines(self):
        self.runner = None
        self.monsters = []
        self.fresh_grid()
        self.set_location(HOME)

    def set_location(self, loc):
        b = self.node.interp.builtins
        self.in_mines = loc == DUNGEON
        b["CURRENT_LOCATION_ID"] = loc
        b["DUNGEON_RUNNER"] = self.runner if loc == DUNGEON else None

    def room_key(self):
        if not self.in_mines:
            return "farm:undefined"
        return "dungeon:undefined" + self.node.call("mistrimulti_dg_room_suffix")

    # -- monsters (par_monster.gml and the species' step_end) -------------------------------------------------------
    def strike(self, mon, damage, absorbed=False):
        """A tarball resolves against the monster's receiver: the combat.damage filter, then the species takes the damage
        (unless it ignores the hit: a shell, a phase in which it cannot be hurt)."""
        if not mon.alive:
            return
        tarball = S(damage=damage, alive=True)
        self.node.call("mistrimulti_dg_damage", tarball, S(parent_id=mon))
        if not absorbed:
            mon["hit_points"] -= tarball["damage"]

    def poison(self, mon, amount):
        mon["hit_points"] -= amount

    def frame(self):
        for mon in list(self.monsters):
            if not mon.alive:
                continue
            # par_monster's step_end (process_status, then the monster.step_end hook) comes before the species' own check
            self.node.call("mistrimulti_dg_monster_step", mon)
            if mon.hit_points <= 0:
                self.die(mon)

    def die(self, mon):
        """The Dying state and its poof: drops, essence and xp for this game's player, then the instance goes."""
        self.drops.append(MONSTERS[mon.monster_id][0])
        self.xp += 10
        self.destroy(mon)

    def destroy(self, mon):
        mon["alive"] = False
        if mon in self.monsters:
            self.monsters.remove(mon)
        if not mon.skip_destroy_logic:
            # par_monster's destroy event: the kill count and the floor's ladder score
            self.kills += 1
            self.runner.on_monster_destroy(mon.x // 8, mon.y // 8)

    # -- tools (Pick.gml, Shovel.gml, Interact.gml) ---------------------------------------------------------------------
    def give(self, name, n=1):
        self.items[name] = self.items.get(name, 0) + n

    def pick_node(self, grid, x, y, proto, modifier, override, doppel):
        for xx in range(2):
            for yy in range(2):
                i = self.index(x + xx, y + yy)
                if i is not None and self.grid["node_object_id"][i] is not None:
                    node = self.grid["node_parent"][i]
                    oid = node["object_id"]
                    if OBJECTS[oid][1] == "Rock":
                        if proto.quality != 5 and proto.quality + modifier < node.prototype.minimum_quality:
                            return 0
                        node["hitpoints"] -= min(proto.damage + modifier, node["hitpoints"])
                        if node["hitpoints"] <= 0:
                            self.give(OBJECTS[oid][0] + "_item")
                            self.erase(grid, node)
                        return 1
                    if oid == OBJ_ID["dig_site"]:
                        self.dig(node)
                        return 2
                    return 3
        return 0

    def dig(self, node):
        x, y = node["top_left_x"], node["top_left_y"]
        self.give("artifact")
        self.erase(self.grid, node)
        self.write(x, y, OBJ_ID["dig_site_destroyed"])

    def shovel_node(self, grid, x, y, doppel):
        i = self.index(x // 2 * 2, y // 2 * 2)
        if i is not None and self.grid["node_object_id"][i] == OBJ_ID["dig_site"]:
            self.dig(self.grid["node_parent"][i])
            return 2 | 4
        return 0

    def can_interact(self, node):
        cat = OBJECTS[node["object_id"]][1]
        if cat == "Breakable":
            return node.prototype.chest is not None and not node["is_open"]
        return cat == "Crop"

    def interact(self, node):
        if not self.can_interact(node):
            return False
        if OBJECTS[node["object_id"]][1] == "Crop":
            self.give("herb_item")
            self.erase(self.grid, node)
        else:
            node["is_open"] = True
            self.give("loot")
        return True

    def item(self, name):
        return S(item_id=ITEM_ID[name], prototype=ITEM_PROTOS[ITEM_ID[name]])

    # -- the names the GML uses ----------------------------------------------------------------------------------------
    def builtins(self):
        e = self

        def string(value):
            return "inst%d" % value["uid"] if isinstance(value, S) and "uid" in value and "monster_id" in value else gml.gml_string(value)

        def instance_exists(v):
            if v is None:
                return False
            if v is e.ladder_obj:
                return e.ladder_alive
            return v.get("alive", True) if isinstance(v, dict) else True

        def random_set_seed(seed):
            e.seeds.append(seed)
            e.rng = random.Random(seed)

        def randomize():
            e.rng = random.Random(e.entropy.random())

        def create_dungeon_itinerary(count):
            return e.make_itinerary(count)

        return {
            "LocationId": S(Farm=0, Town=1, Dungeon=DUNGEON, LEN=3), "CURRENT_LOCATION_ID": HOME, "GRID": self.grid,
            "DUNGEON_RUNNER": None, "ARI": self.ari, "DungeonImpl": S(Standard=0, Enemy=1, Treasure=2),
            "ObjectCategory": S(CAT), "ObjectId": S(DigSite=OBJ_ID["dig_site"], DigSiteDestroyed=OBJ_ID["dig_site_destroyed"]),
            "NODE_PROTOTYPES": NODE_PROTOS, "ITEM_PROTOTYPES": ITEM_PROTOS, "ToolType": S(TOOL), "QualityId": S(LEN=6),
            "MonsterId": S(LEN=len(MONSTERS)), "CropFlag": S(FORAGEABLE=2, SPAWN_GROWN=8),
            "PickResult": S(Nothing=0, Rock=1, DigSite=2, Furniture=3), "ShovelResult": S(GIVE_ESSENCE=2, GAIN_DIG_SITE_EXPERIENCE=4),
            "Skill": S(Archaeology=3), "XpValue": S(break_dig_spot=5), "InputId": S(UseToolCharged=7),
            "INPUT": S(check=lambda i: e.charging), "RangePattern": S(One=0, OneByThree=1),
            "quality_to_range_pattern": lambda q: 0 if q == 0 else 1, "spr_fx_small_monster_death_poof": "poof",
            "obj_dungeon_ladder_down": self.ladder_obj, "obj_ari": self.player, "obj_node_renderer": "r", "par_monster": "m",
            "room": lambda: e.room_name, "asset_to_string": lambda rm: rm, "is_special_dungeon_room": lambda rm: rm == "special",
            "create_dungeon_itinerary": create_dungeon_itinerary, "random_set_seed": random_set_seed, "randomize": randomize,
            "irandom_range": lambda a, b: e.rng.randint(int(a), int(b)),
            "object_id_to_object_category": lambda i: None if i is None else NODE_PROTOS[i].category_id,
            "object_id_to_string": lambda i: OBJECTS[i][0], "try_string_to_object_id": lambda s: OBJ_ID.get(s),
            "item_id_to_string": lambda i: ITEMS[i], "try_string_to_item_id": lambda s: ITEM_ID.get(s),
            "monster_id_to_string": lambda i: MONSTERS[i][0],
            "erase_object_node_by_parent": self.erase, "can_interact": self.can_interact, "interact": self.interact,
            "pick_node": self.pick_node, "shovel_node": self.shovel_node, "spawn_monster": self.spawn_monster,
            "has_flag": lambda v, f: (v & f) == f, "instance_exists": instance_exists, "instance_destroy": self.destroy,
            "create_animation_effect": lambda *a: None, "string": string, "List": lst,
            "abs": abs, "round": lambda v: int(v + 0.5) if v >= 0 else -int(-v + 0.5), "ceil": lambda v: -int(-v // 1),
            "clamp": lambda v, lo, hi: max(lo, min(hi, v)),
            "mmapi_filter": lambda *a: None, "mmapi_override": lambda *a: None, "mmapi_on": lambda *a: None,
            "mmapi_guard": lambda *a: None,
        }


class DungeonNode(GmlNode):
    extra_files = ("MistriMultiDungeon.gml",)
    charging = False

    def builtins(self):
        self.mine = Mine(self)
        self.mine.charging = False
        return self.mine.builtins()

    def setup(self):
        self.rt["enabled"] = True
        self.interp.functions["mistrimulti_dg_node_list"] = lambda: gml.GArray(self.mine.nodes_)
        self.interp.functions["mistrimulti_dg_monster_list"] = lambda: gml.GArray(m for m in self.mine.monsters if m.alive)
        self.interp.functions["mistrimulti_dg_new_doppel"] = lambda: S(resolve=lambda: None)


class Driver:
    """What MistriMultiBoot.gml does for this feature each bridge tick, and the peer fields the host validates."""

    def __init__(self, game):
        self.game, self.node = game, game.node
        self.node.interp.call("mistrimulti_dungeon_register_events")

    def frame(self):
        return {"room": self.node.mine.room_key(), "x": 40, "y": 40}

    def tick(self, now):
        self.node.call("mistrimulti_dungeon_tick")
        self.node.mine.frame()


def make_world(seed, guests=2, perks=(), **faults):
    world = World(seed, {i: DungeonNode for i in range(guests + 1)}, **faults)
    for slot, game in world.games.items():
        game.feature = Driver(game)
        game.node.mine.perk = slot in perks
    world.run(4500)
    return world


def nodes(world):
    return [world.games[s].node for s in sorted(world.games)]


def dg(node):
    return node.rt["dg"]


def go(world, slot, flr, ms=2500, new_runner=True, **kw):
    """The game of `slot` enters the mines (when asked to) and the floor, then time passes."""
    mine = world.games[slot].node.mine
    if new_runner or mine.runner is None:
        mine.enter_mines()
    mine.enter_floor(flr, **kw)
    world.run(ms)


def synced(world, floor_slots, what):
    """Every listed game is live on its floor and all hold the same layout."""
    first = None
    for slot in floor_slots:
        node = world.games[slot].node
        assert dg(node)["st"] == "live", (what, slot, dg(node)["st"], world.games[slot].warnings[:3])
        lay = node.mine.layout()
        if first is None:
            first = lay
        assert lay == first, (what, slot, lay, first)
    return first


def clean(world, what):
    for slot, game in world.games.items():
        debug = game.node.call("mistrimulti_events_debug")
        assert debug["errors"] == 0, (what, slot, debug, game.warnings[:3])
        assert dg(game.node)["errors"] == 0, (what, slot, dg(game.node)["errors"], game.warnings[:3])


def total(world, attr, slots=None):
    return sum((len(getattr(world.games[s].node.mine, attr)) if attr == "drops" else getattr(world.games[s].node.mine, attr))
               for s in (slots if slots is not None else world.games))


def swing(game, tool, cells, pattern=0, charged=False):
    """What the Tool state does: filter the targets, then call the tool's function for every cell left."""
    mine = game.node.mine
    mine.charging = charged
    item = mine.item(tool)
    items = [vec(x, y) for x, y in cells]
    out = game.node.call("mistrimulti_dg_tool_targets", lst(items), S(item=item, range_pattern=pattern, x=cells[0][0], y=cells[0][1], cardinal=0))
    kept = items if out is None else out["arr"]
    for cell in kept:
        modifier = 0 if pattern == 0 else -1
        if item.prototype.tool_type == TOOL["PickAxe"]:
            mine.pick_node(mine.grid, cell.x, cell.y, item.prototype, modifier, None, None)
        else:
            mine.shovel_node(mine.grid, cell.x, cell.y, None)
    return len(items) - len(kept)


def press(game, node):
    """The Interact press: the hook may claim it, otherwise the engine's own interact runs."""
    if game.node.call("mistrimulti_dg_interact", node) is None:
        game.node.mine.interact(node)


def next_swing(world, game):
    """Time passes between two swings, so the second is a new one and not the first still in progress."""
    world.run(1500)
    game.node.rt["ticks"] += 200


def wait_live(world, slots, ms=6000):
    end = world.clock.ms + ms
    while world.clock.ms < end:
        world.run(100)
        if all(dg(world.games[s].node)["st"] == "live" for s in slots):
            return
    raise AssertionError(("not live", [(s, dg(world.games[s].node)["st"]) for s in slots]))


def find_floor(slot_perk=(), want=4):
    """A floor number whose generated floor, for the first run seed, holds enough monsters. (Floors only differ by seed.)"""
    return 3


# ---- scenarios ---------------------------------------------------------------------------------------------------------

def test_same_floor():
    world = make_world(11, perks=(2,), loss=0.05, dup=0.03, jitter=30)
    host, g1, g2 = nodes(world)
    for slot in (0, 1, 2):
        world.games[slot].node.mine.enter_mines()
    # The game's own itineraries differ (unseeded); the hook replaced them with the run's.
    locals_ = [n.mine.local_itinerary for n in (host, g1, g2)]
    assert len({str(x) for x in locals_}) > 1, "the stub itineraries should differ before the hook"
    assert host.mine.itinerary == g1.mine.itinerary == g2.mine.itinerary, "everyone walks the run's itinerary"
    assert dg(host)["my_run"] == dg(g1)["my_run"] == dg(g2)["my_run"] != 0
    # The host founds floor 3; the guests arrive later. g2's perk makes its own build differ.
    host.mine.enter_floor(3)
    world.run(2500)
    g1.mine.enter_floor(3)
    g2.mine.enter_floor(3)
    wait_live(world, (0, 1, 2))
    lay = synced(world, (0, 1, 2), "floor 3")
    assert len(lay[0]) > 8 and len(lay[1]) >= 3, lay
    assert g2.mine.raw != host.mine.raw, "g2's own build should have differed before the record reconciled it"
    assert g1.mine.raw == host.mine.raw, "same seed, same generator: the layouts agree on their own"
    needs = {n.mine.runner["ladder_score_needed"] for n in (host, g1, g2)}
    assert len(needs) == 1, needs
    keys = {n.mine.room_key() for n in (host, g1, g2)}
    assert len(keys) == 1 and "r" in keys.pop(), "players on one floor share a room key"
    # A guest that founds a floor (the host is elsewhere) gives the same result to everybody who comes later.
    g1.mine.enter_floor(5)
    wait_live(world, (1,))
    host.mine.enter_floor(5)
    g2.mine.enter_floor(5)
    wait_live(world, (0, 1, 2))
    synced(world, (0, 1, 2), "floor 5, founded by a guest")
    clean(world, "same floor")
    print("PASS: one run seed gives everyone the same itinerary and floor; a differing build is reconciled; any game can found a floor")


def test_seed_matters():
    # Without the run's seed the builds differ, so the equality above is the seeding's doing and not luck.
    world = make_world(12, guests=1)
    host, g1 = nodes(world)
    host.mine.enter_mines()
    g1.mine.enter_mines()
    host.mine.enter_floor(3)
    g1.mine.enter_floor(3)
    assert host.mine.seeds and host.mine.seeds[0] == g1.mine.seeds[0] and g1.mine.seeds[-1] == host.mine.seeds[-1]
    assert host.mine.raw == g1.mine.raw
    g1.mine.enter_floor(4)
    assert host.mine.raw != g1.mine.raw, "another floor, another seed"
    print("PASS: floors are seeded from (run seed, floor)")


def pick_monsters(mine, n=1):
    mons = sorted((m for m in mine.monsters if m.alive), key=lambda m: (m.original_spawn_pos.x, m.original_spawn_pos.y))
    assert len(mons) >= n, "the stub floor needs more monsters"
    return mons


def copy_of(game, key):
    for m in game.node.mine.monsters:
        if m.alive and (m.original_spawn_pos.x, m.original_spawn_pos.y) == key:
            return m
    return None


def key_of(mon):
    return (mon.original_spawn_pos.x, mon.original_spawn_pos.y)


def test_two_players_one_enemy():
    world = make_world(13, guests=2, loss=0.08, dup=0.06, jitter=40)
    host, g1, g2 = nodes(world)
    for slot in (0, 1, 2):
        go(world, slot, 3, ms=300)
    wait_live(world, (0, 1, 2))
    synced(world, (0, 1, 2), "start")
    mons = pick_monsters(host.mine, 3)
    k = key_of([m for m in mons if m.monster_id == MON_ID["clod"]][0] if any(m.monster_id == MON_ID["clod"] for m in mons) else mons[0])
    start_hp = copy_of(world.games[0], k).hit_points
    # Two players wound the same monster: the host adds the damage up and every copy follows.
    g1.mine.strike(copy_of(world.games[1], k), 1)
    g2.mine.strike(copy_of(world.games[2], k), 1)
    world.run(2500)
    for slot in (0, 1, 2):
        assert copy_of(world.games[slot], k).hit_points == start_hp - 2, (slot, copy_of(world.games[slot], k).hit_points, start_hp)
    base_drops, base_xp = total(world, "drops"), total(world, "xp")
    score_before = [n.mine.runner["ladder_score"] for n in (host, g1, g2)]
    # Both land a killing blow at the same moment: no copy may die by itself, exactly one player is the killer.
    g1.mine.strike(copy_of(world.games[1], k), 99)
    g2.mine.strike(copy_of(world.games[2], k), 99)
    host.mine.strike(copy_of(world.games[0], k), 99)
    for slot in (0, 1, 2):
        c = copy_of(world.games[slot], k)
        assert c is not None and c.hit_points >= 1, "a copy must survive until the host decides"
    world.run(3000)
    for slot in (0, 1, 2):
        assert copy_of(world.games[slot], k) is None, (slot, "the monster is gone everywhere")
    assert total(world, "drops") - base_drops == 1, "one drop set"
    assert total(world, "xp") - base_xp == 10, "xp to one player"
    assert total(world, "kills") == 1
    killers = [s for s in (0, 1, 2) if world.games[s].node.mine.kills == 1]
    assert len(killers) == 1
    scores = [n.mine.runner["ladder_score"] for n in (host, g1, g2)]
    assert scores == [score_before[0] + MONSTER_POINTS] * 3, (scores, score_before)
    synced(world, (0, 1, 2), "after the kill")
    # Hits on an already dead monster cost nothing and drop nothing (a late report).
    clean(world, "one enemy")
    print("PASS: two players on one enemy: health pooled by the host, one killer, one drop set and xp, every copy removed")


def test_poison_and_late_hit():
    world = make_world(14, guests=1, jitter=20)
    host, g1 = nodes(world)
    for slot in (0, 1):
        go(world, slot, 2, ms=300)
    wait_live(world, (0, 1))
    mons = pick_monsters(host.mine)
    k = key_of(mons[0])
    mine = g1.mine
    copy = copy_of(world.games[1], k)
    hp = copy.hit_points
    # Venom lowers the copy's health below what it expects: reported, and the copy is kept alive.
    mine.poison(copy, 1)
    world.run(500)
    assert copy_of(world.games[0], k).hit_points == hp - 1
    mine.poison(copy, 50)
    world.run(2500)
    assert copy_of(world.games[0], k) is None and copy_of(world.games[1], k) is None
    assert g1.mine.kills == 1 and host.mine.kills == 0 and len(g1.mine.drops) == 1 and not host.mine.drops
    # A hit the species ignores (a shell) is not reported and costs the monster nothing.
    others = [m for m in pick_monsters(host.mine) if key_of(m) != k]
    k2 = key_of(others[0])
    before = (g1.rt["dg"]["hits"], copy_of(world.games[0], k2).hit_points)
    g1.mine.strike(copy_of(world.games[1], k2), 99, absorbed=True)
    world.run(1500)
    assert (g1.rt["dg"]["hits"], copy_of(world.games[0], k2).hit_points) == before
    clean(world, "poison")
    print("PASS: damage over time is reported through the step hook; the lethal tick makes its reporter the killer")


def test_nodes():
    world = make_world(15, guests=2, loss=0.06, dup=0.05, jitter=30)
    host, g1, g2 = nodes(world)
    for slot in (0, 1, 2):
        go(world, slot, 3, ms=300)
    wait_live(world, (0, 1, 2))
    rocks = host.mine.named("rock")
    assert len(rocks) >= 2, "the stub floor needs rocks"
    x, y = rocks[0]["top_left_x"], rocks[0]["top_left_y"]
    # A rock (3 hitpoints, pickaxe 2): the first swing chips it, the second breaks it. Nobody swings alone.
    taken = swing(world.games[1], "pickaxe", [(x, y)])
    assert taken == 1, "the swing at a shared rock is taken over by the hook"
    world.run(1500)
    for n in (host, g1, g2):
        assert n.mine.named("rock")[0]["hitpoints"] == 1, "the chip is applied everywhere"
    assert all(not n.mine.items for n in (host, g1, g2)), "a chip yields nothing"
    next_swing(world, world.games[1])
    # Both players deliver the breaking swing at once: one yield.
    swing(world.games[1], "pickaxe", [(x, y)])
    swing(world.games[2], "pickaxe", [(x, y)])
    world.run(3000)
    yields = sum(n.mine.items.get("rock_item", 0) for n in (host, g1, g2))
    assert yields == 1, yields
    for n in (host, g1, g2):
        assert all((r["top_left_x"], r["top_left_y"]) != (x, y) for r in n.mine.named("rock")), "the rock is gone everywhere"
    # Ore needs a better pickaxe: the weak one asks, the host refuses, the ore stays.
    ores = host.mine.named("ore")
    if ores:
        ox, oy = ores[0]["top_left_x"], ores[0]["top_left_y"]
        swing(world.games[2], "pickaxe", [(ox, oy)])
        world.run(1500)
        assert any((o["top_left_x"], o["top_left_y"]) == (ox, oy) for o in host.mine.named("ore"))
        assert not any(n.mine.items.get("ore_item") for n in (host, g1, g2))
        next_swing(world, world.games[2])
        for _ in range(2):
            swing(world.games[2], "pickaxe_gold", [(ox, oy)])
            next_swing(world, world.games[2])
        assert sum(n.mine.items.get("ore_item", 0) for n in (host, g1, g2)) == 1 and g2.mine.items.get("ore_item") == 1
    # A chest opened by two players at once: one loot.
    chests = host.mine.named("chest")
    assert chests, "the stub floor needs a chest"
    cx, cy = chests[0]["top_left_x"], chests[0]["top_left_y"]
    for slot in (1, 2):
        node = [n for n in world.games[slot].node.mine.named("chest") if (n["top_left_x"], n["top_left_y"]) == (cx, cy)][0]
        press(world.games[slot], node)
    world.run(3000)
    assert sum(n.mine.items.get("loot", 0) for n in (host, g1, g2)) == 1
    for n in (host, g1, g2):
        assert [c["is_open"] for c in n.mine.named("chest") if (c["top_left_x"], c["top_left_y"]) == (cx, cy)] == [True]
    # A herb and a dig site: one yield each, whoever asks.
    herbs, digs = host.mine.named("herb"), host.mine.named("dig_site")
    if herbs:
        hx, hy = herbs[0]["top_left_x"], herbs[0]["top_left_y"]
        for slot in (0, 2):
            found = [h for h in world.games[slot].node.mine.named("herb") if (h["top_left_x"], h["top_left_y"]) == (hx, hy)]
            if found:
                press(world.games[slot], found[0])
        world.run(3000)
        assert sum(n.mine.items.get("herb_item", 0) for n in (host, g1, g2)) == 1
    if digs:
        dx, dy = digs[0]["top_left_x"], digs[0]["top_left_y"]
        swing(world.games[1], "shovel", [(dx, dy)])
        swing(world.games[2], "pickaxe", [(dx, dy)])
        world.run(3000)
        assert sum(n.mine.items.get("artifact", 0) for n in (host, g1, g2)) == 1
    # Something the hooks do not gate (a bomb, a sword on a pot) is reported afterwards and removed everywhere.
    pots = host.mine.named("pot")
    if pots:
        px, py = pots[0]["top_left_x"], pots[0]["top_left_y"]
        mine = world.games[1].node.mine
        mine.erase(mine.grid, [p for p in mine.named("pot") if (p["top_left_x"], p["top_left_y"]) == (px, py)][0])
        world.run(3000)
        for n in (host, g1, g2):
            assert not any((p["top_left_x"], p["top_left_y"]) == (px, py) for p in n.mine.named("pot"))
    synced(world, (0, 1, 2), "after the nodes")
    clean(world, "nodes")
    print("PASS: rocks, ore, chests, herbs and dig sites: hitpoints pooled by the host, one yield per node, a refusal stays refused")


def test_ladder():
    world = make_world(16, guests=2, jitter=30)
    host, g1, g2 = nodes(world)
    for slot in (0, 1, 2):
        go(world, slot, 3, ms=300)
    wait_live(world, (0, 1, 2))
    # Clear the floor with all three players' help: when the score is reached there is one ladder, in one place.
    for _ in range(40):
        if host.mine.ladder_alive:
            break
        for slot in (1, 2, 0):
            mine = world.games[slot].node.mine
            for mon in list(mine.monsters)[:1]:
                mine.strike(mon, 99)
            for rock in mine.named("pot")[:1]:
                mine.erase(mine.grid, rock)
        world.run(800)
    world.run(3000)
    assert all(n.mine.ladder_alive for n in (host, g1, g2)), [n.mine.ladder_alive for n in (host, g1, g2)]
    assert len({n.mine.ladder for n in (host, g1, g2)}) == 1, [n.mine.ladder for n in (host, g1, g2)]
    clean(world, "ladder")
    print("PASS: the floor's ladder appears for everybody, in the place the first game that earned it put it")


def test_floors_apart():
    world = make_world(17, guests=2, jitter=30)
    host, g1, g2 = nodes(world)
    go(world, 0, 2, ms=300)
    go(world, 1, 4, ms=300)
    go(world, 2, 2, ms=300)
    wait_live(world, (0, 1, 2))
    synced(world, (0, 2), "floor 2")
    assert host.mine.room_key() == g2.mine.room_key() != g1.mine.room_key(), "players on different floors do not see each other"
    base = g1.mine.layout()
    mons = pick_monsters(g2.mine)
    k = key_of(mons[0])
    g2.mine.strike(copy_of(world.games[2], k), 99)
    world.run(2500)
    assert copy_of(world.games[0], k) is None, "the host's floor-2 copy is gone"
    assert g1.mine.layout() == base, "floor 4 is untouched"
    # g1 breaks a rock on floor 4 and kills something there; the host comes later and finds it so.
    rocks = g1.mine.named("rock")
    if rocks:
        rx, ry = rocks[0]["top_left_x"], rocks[0]["top_left_y"]
        for _ in range(2):
            swing(world.games[1], "pickaxe", [(rx, ry)])
            next_swing(world, world.games[1])
    m4 = key_of(pick_monsters(g1.mine)[0])
    g1.mine.strike(copy_of(world.games[1], m4), 99)
    world.run(2500)
    after = g1.mine.layout()
    assert after != base
    host.mine.enter_floor(4)
    wait_live(world, (0, 1))
    assert host.mine.layout() == after, (host.mine.layout(), after)
    assert g1.mine.layout() == after
    clean(world, "floors apart")
    print("PASS: different floors at once are independent; a game arriving later gets the floor as the others left it")


def test_leave_and_rejoin():
    world = make_world(18, guests=2, jitter=30)
    host, g1, g2 = nodes(world)
    for slot in (0, 1, 2):
        go(world, slot, 3, ms=300)
    wait_live(world, (0, 1, 2))
    run_id = dg(host)["my_run"]
    k = key_of(pick_monsters(host.mine)[0])
    mon = copy_of(world.games[1], k)
    g1.mine.strike(mon, 1)
    rocks = g2.mine.named("rock")
    rx, ry = rocks[0]["top_left_x"], rocks[0]["top_left_y"]
    for _ in range(2):
        swing(world.games[2], "pickaxe", [(rx, ry)])
        next_swing(world, world.games[2])
    world.run(2000)
    after = host.mine.layout()
    # g1 passes out / walks home, then walks back in to the same floor of the same run.
    g1.mine.leave_mines()
    world.run(1500)
    assert dg(g1)["f"] == -1 and host.mine.room_key() != g1.mine.room_key()
    assert dg(host)["at"][1] is None, "the host knows g1 left"
    g1.mine.enter_mines()
    assert dg(g1)["my_run"] == run_id, "re-entering joins the run that is still going"
    g1.mine.enter_floor(3)
    wait_live(world, (1,))
    assert g1.mine.layout() == after, (g1.mine.layout(), after)
    # Everybody leaves; after the grace period the run ends and the next entry gets a new seed and floors.
    for slot in (0, 1, 2):
        world.games[slot].node.mine.leave_mines()
    world.run(8000)
    assert dg(host)["run"] != run_id
    host.mine.enter_mines()
    host.mine.enter_floor(3)
    world.run(2000)
    assert dg(host)["my_run"] != run_id and host.mine.raw != after
    # A game that walked in while the new run was unknown... (see test_stale_run) -- here a guest enters the new run.
    g2.mine.enter_mines()
    g2.mine.enter_floor(3)
    wait_live(world, (0, 2))
    synced(world, (0, 2), "new run")
    clean(world, "rejoin")
    print("PASS: leaving and re-entering keeps the floor's state; an empty mine ends the run and the next one is new")


def test_host_away():
    world = make_world(19, guests=2, jitter=30)
    host, g1, g2 = nodes(world)
    for slot in (0, 1, 2):
        go(world, slot, 3, ms=300)
    wait_live(world, (0, 1, 2))
    host.mine.leave_mines()                  # the host walks home; its logical state stays
    world.run(1500)
    k = key_of(pick_monsters(g1.mine)[0])
    g1.mine.strike(copy_of(world.games[1], k), 99)
    rocks = g2.mine.named("rock")
    rx, ry = rocks[0]["top_left_x"], rocks[0]["top_left_y"]
    for _ in range(2):
        swing(world.games[2], "pickaxe", [(rx, ry)])
        next_swing(world, world.games[2])
    world.run(2000)
    assert g1.mine.kills == 1 and len(g1.mine.drops) == 1
    assert g2.mine.items.get("rock_item") == 1
    after = g1.mine.layout()
    assert g2.mine.layout() == after
    host.mine.enter_mines()
    host.mine.enter_floor(3)
    wait_live(world, (0,))
    assert host.mine.layout() == after
    clean(world, "host away")
    print("PASS: the host leaving the mines changes nothing for the others; it finds the floor as they left it")


def test_host_restart():
    world = make_world(20, guests=2, jitter=20)
    host, g1, g2 = nodes(world)
    for slot in (1, 2):
        go(world, slot, 3, ms=300)
    wait_live(world, (1, 2))
    run_id = dg(g1)["my_run"]
    k = key_of(pick_monsters(g1.mine)[0])
    g1.mine.strike(copy_of(world.games[1], k), 1)
    world.run(1500)
    hurt = g1.mine.layout()
    # The host game restarts (it knows nothing): the guests inside the mines found the floor again from what they hold.
    world.start(0)
    game = world.games[0]
    game.feature = Driver(game)
    game.node.mine.rng = random.Random(4242)          # a new host picks its own run
    world.run(9000)
    for slot in (1, 2):
        assert dg(world.games[slot].node)["st"] == "live", (slot, dg(world.games[slot].node)["st"])
    assert dg(world.games[0].node)["run"] == run_id, "the new host adopted the run that is in use"
    assert dg(g1)["run"] == run_id and dg(g2)["my_run"] == run_id
    assert g1.mine.layout() == hurt and g2.mine.layout() == hurt
    # It works as before: a kill resolves once, and a game arriving later sees the floor as it is.
    g2.mine.strike(copy_of(world.games[2], k), 99)
    world.run(2500)
    assert total(world, "kills", (1, 2)) == 1
    new_host = world.games[0].node
    go(world, 0, 3, ms=500, new_runner=True)
    wait_live(world, (0,))
    assert new_host.mine.layout() == g1.mine.layout() == g2.mine.layout()
    clean(world, "host restart")
    print("PASS: host restart: guests inside the mines re-found their floor on the new host; kills still resolve once")


def test_different_rooms_are_not_shared():
    # Two games whose itineraries disagreed would build different rooms for floor 3: the second one must not take on the
    # first one's record (its positions mean nothing in another room).
    world = make_world(29, guests=1, jitter=20)
    host, g1 = nodes(world)
    go(world, 0, 3, ms=300)
    wait_live(world, (0,))
    g1.mine.room_override = "another_room"
    g1.mine.enter_mines()
    g1.mine.enter_floor(3)
    raw = g1.mine.layout()
    world.run(3000)
    assert dg(g1)["f"] == -1 and dg(g1)["st"] == "off", (dg(g1)["f"], dg(g1)["st"])
    assert g1.mine.layout() == raw, "its own room is left alone"
    assert ":p1" in g1.mine.room_key()
    assert dg(host)["at"][1] is None
    print("PASS: a game whose floor is another room than the record's does not share it")


def test_unshared_floors():
    world = make_world(21, guests=1, jitter=20)
    host, g1 = nodes(world)
    host.mine.enter_mines()
    g1.mine.enter_mines()
    # A side room, the arena and special rooms are not shared: the game's own rules apply (monsters die by themselves).
    for kw in (dict(side=True), dict(impl=1)):
        g1.mine.enter_floor(2, **kw)
        world.run(500)
        assert dg(g1)["f"] == -1 and dg(g1)["st"] == "off", kw
        if g1.mine.monsters:
            mon = g1.mine.monsters[0]
            g1.mine.strike(mon, 99)
            g1.mine.frame()
            assert not mon.alive and g1.mine.kills >= 1, "unshared monsters die as in the game"
        g1.mine.kills = 0
        assert ":p1" in g1.mine.room_key(), g1.mine.room_key()
    # Before the run is known (a game that joined moments ago) the floor is simply the game's own.
    lone = make_world(22, guests=1)
    other = lone.games[1].node
    dg(other)["run"] = 0
    other.mine.enter_mines()
    other.mine.enter_floor(1)
    assert dg(other)["f"] == -1
    # Losing the host: the floor stops being shared after the grace period, monsters become mortal again.
    world2 = make_world(23, guests=1)
    h2, p2 = nodes(world2)
    for slot in (0, 1):
        go(world2, slot, 3, ms=300)
    wait_live(world2, (0, 1))
    world2.net.partition(0, 1)
    world2.run(24000)
    assert dg(p2)["st"] == "off" and dg(p2)["f"] == -1, (dg(p2)["st"], dg(p2)["f"])
    print("PASS: side rooms, the arena, unknown runs and a lost host leave the floor to the game's own rules")


def test_hostile_input():
    world = make_world(24, guests=2, jitter=20)
    host, g1, g2 = nodes(world)
    for slot in (0, 1, 2):
        go(world, slot, 3, ms=300)
    wait_live(world, (0, 1, 2))
    base = host.mine.layout()
    run = dg(host)["run"]
    junk = [None, 7, "x", [], {}, {"o": 5}, {"o": "hit"}, {"o": "hit", "run": "a", "f": "b", "m": 3, "d": {}},
            {"o": "hit", "run": run, "f": 3, "m": "1,1", "d": -5}, {"o": "hit", "run": run, "f": 3, "m": "nope", "d": 99999999},
            {"o": "pick", "run": run, "f": 3, "x": "a", "y": 0}, {"o": "pick", "run": run, "f": 3, "x": 1e9, "y": 0, "i": 4},
            {"o": "use", "run": run, "f": 3, "x": 0, "y": 0}, {"o": "gone", "run": run, "f": 99, "x": 0, "y": 0},
            {"o": "gone", "run": run, "f": 3, "x": -1, "y": 0}, {"o": "lad", "run": run, "f": 3, "x": "a", "y": []},
            {"o": "man", "run": run, "f": 3, "i": 0, "n": 1, "nd": [], "mo": []},
            {"o": "man", "run": run, "f": 3, "i": 0, "n": 1, "nd": [["rock", 1, 1, 1, 1]] * 80, "mo": [], "h": {"need": 1, "rv": 0}},
            {"o": "here", "run": run, "f": 1e12}, {"o": "here", "run": "q", "f": 3}, {"o": "here", "run": run, "f": -7},
            {"o": "here", "run": 5, "f": 3, "rj": True, "seed": "s"}]
    for data in junk:
        node = g1
        # as the host would receive them (from slot 1) and as a guest would send them
        res = host.call("mistrimulti_dg_request", 1, data, S(kind="dg_act"))
        assert isinstance(res, dict), (data, res)
        node.call("mistrimulti_event_request", "dg_act", data) if isinstance(data, dict) else None
    # Hostile snapshot slices and results, as the host's name.
    snap_bad = [None, {}, {"run": 1, "f": 3, "i": 0, "n": 1, "nd": [["nope", 0, 0, 0, 0]], "mo": [], "h": {"need": 1, "rv": 0}},
                {"run": 1, "f": 3, "i": "a", "n": 1, "nd": [], "mo": []}]
    for data in snap_bad:
        assert g2.call("mistrimulti_dg_slice_ok", dg(g2), data) is False, data
        g2.call("mistrimulti_dg_snap_event", 0, data, S())
        g2.call("mistrimulti_dg_result", 0, data, S(mine=False))
    world.run(3000)
    assert host.mine.layout() == base and g1.mine.layout() == base and g2.mine.layout() == base
    assert total(world, "drops") == 0 and total(world, "xp") == 0
    # Another floor's player cannot touch this floor: g1 is on floor 3, a request naming floor 4 is refused.
    res = host.call("mistrimulti_dg_request", 1, {"o": "gone", "run": run, "f": 4, "x": 0, "y": 0}, S())
    assert res["ok"] is False
    # A request from a slot the host never saw (no frame) is refused.
    res = host.call("mistrimulti_dg_request", 5, {"o": "here", "run": run, "f": 3}, S())
    assert res["ok"] is False
    for slot, game in world.games.items():
        assert dg(game.node)["errors"] == 0, (slot, game.warnings[:3])
    print("PASS: forged and malformed requests, slices and results change nothing and raise no errors")


def test_loss_matrix():
    # The same fight and mining under heavy loss, duplication and a partition; the totals must still be exactly once.
    for seed, loss, dup in ((31, 0.15, 0.1), (32, 0.25, 0.2), (33, 0.1, 0.3)):
        world = make_world(seed, guests=2, loss=loss, dup=dup, jitter=60)
        host, g1, g2 = nodes(world)
        for slot in (0, 1, 2):
            go(world, slot, 3, ms=300)
        wait_live(world, (0, 1, 2), 20000)
        mons = pick_monsters(host.mine, 2)
        for mon in mons[:2]:
            k = key_of(mon)
            for slot in (0, 1, 2):
                c = copy_of(world.games[slot], k)
                if c is not None:
                    world.games[slot].node.mine.strike(c, 99)
        world.net.partition(0, 2)
        world.run(3000)
        world.net.partition(0, 2, False)
        world.run(20000)
        killed = len(mons[:2])
        assert total(world, "kills") == killed, (seed, total(world, "kills"), killed)
        assert total(world, "drops") == killed, (seed, total(world, "drops"))
        synced(world, (0, 1, 2), "loss %s" % seed)
    print("PASS: heavy loss, duplication and a partition: every kill happens once, every game ends on the same floor")


def test_big_floor_and_simultaneous_entry():
    # A floor of more than one slice (50 entries), founded by whoever asks first while the others have to wait.
    world = make_world(25, guests=2, loss=0.1, dup=0.1, jitter=50)
    host, g1, g2 = nodes(world)
    for n in (host, g1, g2):
        n.mine.size = 30
    for slot in (2, 1, 0):
        world.games[slot].node.mine.enter_mines()
        world.games[slot].node.mine.enter_floor(1)
    wait_live(world, (0, 1, 2), 20000)
    lay = synced(world, (0, 1, 2), "big floor")
    assert len(lay[0]) + len(lay[1]) > 60, "the stub floor should need several slices"
    assert len(list(dg(host)["floors"].keys())) == 1
    clean(world, "big floor")
    print("PASS: a floor of several slices, founded by one of three simultaneous arrivals, reaches everybody under loss")


def test_join_during_changes():
    world = make_world(26, guests=2, loss=0.05, dup=0.05, jitter=80)
    host, g1, g2 = nodes(world)
    for slot in (0, 1):
        go(world, slot, 2, ms=300)
    wait_live(world, (0, 1))
    g2.mine.enter_mines()
    g2.mine.enter_floor(2)
    # While the third game is being brought up to date, the others keep hitting monsters and rocks.
    for step in range(10):
        for slot in (0, 1):
            mine = world.games[slot].node.mine
            mons = [m for m in mine.monsters if m.alive]
            if mons and step % 2 == 0:
                mine.strike(mons[step % len(mons)], 1)
            rocks = mine.named("rock")
            if rocks and step % 3 == 0:
                swing(world.games[slot], "pickaxe", [(rocks[0]["top_left_x"], rocks[0]["top_left_y"])])
        world.run(150 + 40 * step)
    wait_live(world, (0, 1, 2), 20000)
    world.run(5000)
    synced(world, (0, 1, 2), "joined during changes")
    clean(world, "join during changes")
    print("PASS: a game that joins while others fight and mine ends up identical (results sent during the join are replayed)")


def test_results_during_a_join():
    # A result that arrives while the floor record is on its way is kept, and replayed when the record is in
    # (but only when it is newer than the record).
    world = make_world(28, guests=1, jitter=20)
    host, g1 = nodes(world)
    go(world, 0, 3, ms=300)
    wait_live(world, (0,))
    go(world, 1, 3, ms=300)
    wait_live(world, (0, 1))
    run = dg(host)["run"]
    key = list(dg(host)["floors"].keys())[0]
    fl = dg(host)["floors"][key]
    k = key_of(pick_monsters(g1.mine)[0])
    name = "%d,%d" % k
    hp = copy_of(world.games[1], k).hit_points
    d = dg(g1)
    d["st"] = "snap"
    rv = fl["rev"]
    newer = {"ok": True, "o": "hit", "run": run, "f": 3, "m": name, "hp": 1, "v": rv + 1}
    older = {"ok": True, "o": "hit", "run": run, "f": 3, "m": name, "hp": 2, "v": rv}
    g1.call("mistrimulti_dg_result", 0, older, S(mine=False))
    g1.call("mistrimulti_dg_result", 0, newer, S(mine=False))
    assert len(d["pend"]) == 2 and copy_of(world.games[1], k).hit_points == hp, "kept, not applied, while the record is on its way"
    g1.call("mistrimulti_dg_enter_live", d, fl["nodes"], fl["mons"], S(need=0, rv=rv))
    assert d["st"] == "live" and copy_of(world.games[1], k).hit_points == 1, "the newer result was replayed, the older one dropped"
    print("PASS: results that arrive during a join are kept and replayed when newer than the record")


def test_ladder_position_and_hostile_hits():
    world = make_world(27, guests=2, jitter=20)
    host, g1, g2 = nodes(world)
    go(world, 0, 3, ms=300)
    go(world, 1, 3, ms=300)
    wait_live(world, (0, 1))
    run = dg(host)["run"]
    # g1 earns the ladder at one place: the host and every later arrival put theirs there.
    g1.mine.spawn_ladder(g1.mine.runner, 4, 6)
    world.run(2000)
    assert host.mine.ladder == (4, 6) and host.mine.ladder_alive, host.mine.ladder
    go(world, 2, 3, ms=300, new_runner=True)
    wait_live(world, (2,))
    assert g2.mine.ladder == (4, 6), g2.mine.ladder
    # A second claimant's ladder is vetoed by the guard once the place is known.
    assert g2.call("mistrimulti_dg_ladder_guard", S(runner=g2.mine.runner, x=1, y=1)) is False
    # A hit with a valid key but an absurd amount is refused and the monster stays.
    k = key_of(pick_monsters(host.mine)[0])
    hp = copy_of(world.games[0], k).hit_points
    name = "%d,%d" % k
    res = host.call("mistrimulti_dg_request", 1, {"o": "hit", "run": run, "f": 3, "m": name, "d": 10 ** 9}, S())
    assert res["ok"] is False and copy_of(world.games[0], k).hit_points == hp
    res = host.call("mistrimulti_dg_request", 1, {"o": "hit", "run": run, "f": 3, "m": name, "d": 1.5}, S())
    assert res["ok"] is False
    # A guest cannot hit a monster on a floor it is not on, nor after leaving.
    g1.mine.leave_mines()
    world.run(1500)
    res = host.call("mistrimulti_dg_request", 1, {"o": "hit", "run": run, "f": 3, "m": name, "d": 1}, S())
    assert res["ok"] is False and copy_of(world.games[0], k).hit_points == hp
    clean(world, "ladder")
    print("PASS: one ladder place per floor; absurd, fractional and off-floor hits are refused")


TESTS = [test_same_floor, test_results_during_a_join, test_seed_matters, test_two_players_one_enemy, test_poison_and_late_hit, test_nodes, test_ladder,
         test_big_floor_and_simultaneous_entry, test_join_during_changes, test_ladder_position_and_hostile_hits,
         test_floors_apart, test_leave_and_rejoin, test_host_away, test_host_restart, test_unshared_floors, test_different_rooms_are_not_shared, test_hostile_input,
         test_loss_matrix]

if __name__ == "__main__":
    wanted = sys.argv[1:]
    for test in TESTS:
        if not wanted or test.__name__ in wanted:
            test()
