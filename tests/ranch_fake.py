"""A small stand-in for the parts of the game that MistriMultiRanch.gml touches, for tests/test_ranch.py.

Each simulated game gets its own `Fake` (its own buildings, animals, inventory, farm grid, house decor, pet and
machines), built from the same starting description so that host and guests begin as copies of one save, as they
do in the real game. Only the shape of the game's data that the GML reads is modelled; where the real game
behaves in a way nobody could check here, the stub says so. The stubs are Python callables placed in the
interpreter's builtin table, so values that the game keeps in globals (FARM_EXPANDED, CURRENT_LOCATION_ID, GRID)
are updated by replacing the builtin.
"""
import json

import gml_subset as gml

A = gml.GArray


class G(gml.GStruct):
    """A GML struct whose fields can also be read and written as Python attributes."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

# ---- enumerations (values are arbitrary but distinct) ---------------------------------------------------

FARM, HOME, TOWN, BARN = 0, 1, 2, 3
LOCATION_NAMES = {FARM: "farm", HOME: "home", TOWN: "town", BARN: "barn"}
O_BARN, O_TABLE, O_CHAIR, O_LAMP, O_APIARY = 1, 2, 3, 4, 5
FILLER, O_SITE_BOX = 9, 10
ITEM_HAY, ITEM_TREAT, ITEM_APPLE, ITEM_EGG, ITEM_CHAIR, ITEM_LAMP, ITEM_BP, ITEM_FLOOR_A, ITEM_FLOOR_B, \
    ITEM_WALL_A, ITEM_WALL_B, ITEM_BEE, ITEM_HONEY, ITEM_PET_TREAT, ITEM_SWORD, ITEM_MILK = range(1, 17)
ITEM_COUNT = 20
USE_NONE, USE_PLACE, USE_BLUEPRINT, USE_FLOORING, USE_WALLPAPER = 0, 1, 2, 3, 4
SMALL, LARGE = 0, 1
CHICKEN, COW = 0, 1

ENUMS = {
    "LocationId": G(Farm=FARM, PlayerHome=HOME, Town=TOWN, Barn=BARN, LEN=4),
    "ObjectId": G(LEN=16, StableCraftingTable=O_TABLE, Apiary=O_APIARY),
    "ObjectCategory": G(Furniture=0, Building=1),
    "ItemId": G(LEN=ITEM_COUNT, Honeycomb=ITEM_HONEY),
    "ItemUse": G(PlaceObject=USE_PLACE, Blueprint=USE_BLUEPRINT, Flooring=USE_FLOORING, Wallpaper=USE_WALLPAPER),
    "AnimalKind": G(LEN=2),
    "Sex": G(LEN=2),
    "Blueprint": G(LEN=2),
    "HomeUpgrade": G(Small=0, Large=1, LargeWest=2, LargeWestEast=3, LEN=4),
    "HomeVariant": G(LEN=13),
    "FactoryTier": G(LEN=5),
    "Menu": G(Adoption=7, Title=0),
    "Skill": G(Ranching=3),
}

VARIANTS = {CHICKEN: {"white": 0, "brown": 1}, COW: {"spotted": 0, "red": 1, "gold": 3}}
COSMETICS = {CHICKEN: ["bow"], COW: []}


def make_list(items=None):
    data = list(items or [])
    lst = G()
    lst.update(count=lambda: len(data), get=lambda i: data[int(i)], push=lambda v: data.append(v),
               clear=lambda: data.clear(), remove=lambda i: data.pop(int(i)),
               set=lambda i, v: data.__setitem__(int(i), v), contains=lambda v: v in data)
    lst.data = data
    return lst


def make_map(entries):
    return G(contains_key=lambda k: k in entries, get=lambda k: entries[k], keys=lambda: A(entries.keys()))


def item_proto(item_id, **fields):
    proto = G(item_id=item_id, soulbind=None, recipe=None, tags=make_list(), edible=False, animal_feed=None,
              pet_treat=None, use=USE_NONE, object=None, blueprint=None, flooring=None, wallpaper=None, door_mold=None,
              stars=None)
    proto.update(fields)
    return proto


def item_protos():
    protos = [item_proto(i) for i in range(ITEM_COUNT)]
    protos[ITEM_HAY] = item_proto(ITEM_HAY, animal_feed=G(animal_size=LARGE, tier=0))
    protos[ITEM_TREAT] = item_proto(ITEM_TREAT)
    protos[ITEM_APPLE] = item_proto(ITEM_APPLE, edible=True)
    protos[ITEM_CHAIR] = item_proto(ITEM_CHAIR, use=USE_PLACE, object=O_CHAIR)
    protos[ITEM_LAMP] = item_proto(ITEM_LAMP, use=USE_PLACE, object=O_LAMP)
    protos[ITEM_BP] = item_proto(ITEM_BP, use=USE_BLUEPRINT, blueprint=G(blueprint=0))
    protos[ITEM_FLOOR_A] = item_proto(ITEM_FLOOR_A, use=USE_FLOORING, flooring="oak")
    protos[ITEM_FLOOR_B] = item_proto(ITEM_FLOOR_B, use=USE_FLOORING, flooring="slate")
    protos[ITEM_WALL_A] = item_proto(ITEM_WALL_A, use=USE_WALLPAPER, wallpaper="stripe", door_mold="mold_a")
    protos[ITEM_WALL_B] = item_proto(ITEM_WALL_B, use=USE_WALLPAPER, wallpaper="dots", door_mold="mold_b")
    protos[ITEM_PET_TREAT] = item_proto(ITEM_PET_TREAT, pet_treat=G(tier=1, pet_kinds=A([True])))
    return protos


def animal_proto(kind):
    variants = {name: G(key=name, tier=tier, acquirable=name != "gold", default_cosmetic="bow" if kind == CHICKEN else None)
                for name, tier in VARIANTS[kind].items()}
    return G(core=G(size=SMALL if kind == CHICKEN else LARGE), breeding=G(treat=ITEM_TREAT, uses_egg=kind == CHICKEN),
             variants=make_map(variants), cosmetics=make_map({c: True for c in COSMETICS[kind]}),
             pricing=G(buy_price=200, tier_sell_price_multipliers=A([1, 2, 3, 4])))


class Fake:
    """One game's data and the engine functions the ranch code calls."""

    def __init__(self, node, plan):
        self.node = node
        self.plan = plan
        self.notes = []
        self.files = {}
        self.items = {}
        self.gold = plan.get("gold", 1000)
        self.xp = 0
        self.held = None
        self.unlocks = []
        self.expanded = False
        self.location = FARM
        self.grid_dyn = None
        self.rolls = []
        self.warnings = []
        self.protos = item_protos()
        self.animal_protos = [animal_proto(CHICKEN), animal_proto(COW)]
        self.buildings = []
        self.daycare = []
        self.pet_state = G(name="Mochi", heart_points=0, has_eaten=False, has_been_pat=False, is_pet=True, idx=-1)
        self.pet_state.update(unlocked=lambda: True, pet_kind=lambda: 0)
        self.factories = make_list()
        self.grids = A([self.make_grid(FARM, 60, 40), self.make_grid(HOME, 30, 30), self.make_grid(TOWN, 10, 10), self.make_grid(BARN, 10, 10)])
        self.decor = self.make_decor()
        self.stats = G(furniture_placed=G())
        for spec in plan.get("buildings", []):
            self.add_building(*spec)
        for spec in plan.get("animals", []):
            self.add_animal(*spec)
        for spec in plan.get("factories", []):
            self.add_factory(*spec)
        self.ari = self.make_ari()
        self.install(node)

    # ---- world pieces -------------------------------------------------------------------------------

    def make_grid(self, location, w, h):
        cells = w * h
        grid = G(dims=G(x=w, y=h), location_id=location, dyn_index=None, parent_node=None,
                 node_object_id=A([None] * cells), node_parent=A([None] * cells))

        def index(x, y):
            return int(y) * w + int(x) if 0 <= x < w and 0 <= y < h else None

        grid.try_node_index_for_cell = index
        grid.node_index_for_cell = index
        grid.write_node = lambda x, y, o, r: self.write_node(grid, x, y, o, r)
        return grid

    def occupy(self, grid, node, cells):
        for cx, cy in cells:
            i = grid.try_node_index_for_cell(cx, cy)
            grid.node_object_id[i] = node.object_id
            grid.node_parent[i] = node

    def free(self, grid, cells):
        for cx, cy in cells:
            i = grid.try_node_index_for_cell(cx, cy)
            if i is None or grid.node_object_id[i] is not None:
                return False
        return True

    def write_node(self, grid, x, y, o, r):
        cells = [(x + dx, y + dy) for dx in range(2) for dy in range(2)]
        if not self.free(grid, cells):
            return None
        node = G(object_id=o, top_left_x=x, top_left_y=y, parent_grid=grid, infusion=None, cardinal_index=r,
                 prototype=self.node_protos()[o], renderer=None)
        if o == O_APIARY:
            node.update(production_request=None, production_tier=None, day_count=0)
            self.factories.data.append(node)
        self.occupy(grid, node, cells)
        if o == O_BARN:
            node.update(variant=0, name="Barn")
        if self.node_protos()[o].category == 0 and grid.location_id in (FARM, HOME):
            key = str(o)
            self.stats.furniture_placed[key] = self.stats.furniture_placed.get(key, 0) + 1
        return node

    def node_protos(self):
        if not hasattr(self, "_node_protos"):
            protos = []
            for o in range(16):
                protos.append(G(object_id=o, category=1 if o == O_BARN else 0, placeable_locations=A([FARM, HOME]),
                                house_stairs=None, size=G(x=2, y=2), factory=None))
            protos[O_APIARY].factory = G(rewards_map=A([A([ITEM_EGG]) for _ in range(5)]), bounce_sprite="bounce")
            self._node_protos = protos
        return self._node_protos

    def add_building(self, x, y, dyn, size, capacity, double=False):
        stable = G(stalls=make_list([None] * capacity), incubating_fetuses=make_list())
        building = G(top_left_x=x, top_left_y=y, dyn_index=dyn, object_id=O_BARN, variant=0, name=f"Barn{dyn}", stable=stable,
                     prototype=G(player_building_kind=0, max_occupants=capacity, double_manger=double, manger_size=4, location_id=BARN,
                                 permitted_animal_size=size, incubators=1))
        stable.building = building
        if double:
            stable.left_inventory, stable.right_inventory = A([None] * 4), A([None] * 4)
        else:
            stable.inventory = A([None] * 4)

        def register(animal, move=True):
            for i in range(capacity):
                if stable.stalls.data[i] is None:
                    stable.stalls.data[i] = animal
                    animal.stable = stable
                    return
            raise gml.GmlError("Tried to add an animal to a full stall!")

        def deregister(animal):
            for i in range(capacity):
                if stable.stalls.data[i] is animal:
                    stable.stalls.data[i] = None
            animal.stable = None

        def availability():
            used = sum(1 for a in stable.stalls.data if a is not None)
            return capacity - used - len(stable.incubating_fetuses.data)

        stable.register, stable.deregister, stable.availability = register, deregister, availability
        stable.incubator_availability = lambda: 1
        stable.animals = lambda: make_list([a for a in stable.stalls.data if a is not None])
        self.buildings.append(building)
        return building

    def add_animal(self, idx, kind, variant, sex, name, dyn, **fields):
        building = next(b for b in self.buildings if b.dyn_index == dyn)
        a = G(idx=idx, kind=kind, variant=variant, sex=sex, name=name, heart_points=0, days_old=10, unhappy_days=0,
              has_eaten=False, has_been_pat=False, has_been_outside=False, production_days=0, ate_breeding_treat=False,
              breeding_with=None, is_incubating=False, cosmetic=None, birthday=5, stable=None, instance=None, is_pet=False)
        a.update(fields)
        a.prototype = self.animal_protos[kind]
        a.is_baby = lambda: a.days_old < 3
        a.can_pet = lambda: not a.has_been_pat
        a.is_present = lambda: False
        a.sell_value = lambda: 100 + int(a.heart_points) // 10
        building.stable.register(a)
        return a

    def add_factory(self, x, y):
        return self.write_node(self.grids[FARM], x, y, O_APIARY, 0)

    def make_decor(self):
        d = G(size_upgrade=0, upper_floor=False, variant=0, floorings=G(), wallpapers=G())
        for loc in (HOME,):
            key = LOCATION_NAMES[loc]
            d.floorings[key] = G(flooring="default_v1", infusion=None)
            d.wallpapers[key] = G(wallpaper="default_v1", door_mold_sprite="mold_0", infusion=None)

        def apply_flooring(name, ret, infusion):
            d.floorings[LOCATION_NAMES[self.location]] = G(flooring=name, infusion=infusion)
            return True

        def apply_wallpaper(name, mold, ret, infusion):
            d.wallpapers[LOCATION_NAMES[self.location]] = G(wallpaper=name, door_mold_sprite=mold, infusion=infusion)
            return True

        def apply_house_upgrade(grid, size):
            d.size_upgrade = size

        d.apply_flooring, d.apply_wallpaper, d.apply_house_upgrade = apply_flooring, apply_wallpaper, apply_house_upgrade
        d.sell_data = A([None, G(gold_cost=500, requirements=make_list([G(item_id=ITEM_HAY, quantity=2)])),
                         G(gold_cost=800, requirements=make_list()), G(gold_cost=1200, requirements=make_list())])
        d.upper_floor_sell_data = G(gold_cost=2000, requirements=make_list())
        return d

    def make_ari(self):
        fake = self

        class Inventory(G):
            pass

        inv = G()
        inv.item_id_quantity = lambda i: fake.items.get(int(i), 0)

        def remove(i, n):
            fake.items[int(i)] = fake.items.get(int(i), 0) - int(n)

        inv.remove = remove
        unlock = lambda: G(insert=lambda v: fake.unlocks.append(v))
        ari = G(inventory=inv, held_animal_id=None, animal_variant_unlocks=A([unlock(), unlock()]),
                animal_cosmetic_unlocks=A([unlock(), unlock()]))
        ari.get_gold = lambda: fake.gold
        ari.modify_gold = lambda n: setattr(fake, "gold", max(int(fake.gold + n), 0))
        ari.give_item = lambda i, n=1: fake.items.__setitem__(int(i), fake.items.get(int(i), 0) + int(n))
        ari.gain_xp = lambda skill, xp: setattr(fake, "xp", fake.xp + xp)
        ari.held_item = lambda: None if fake.held is None else G(item_id=fake.held, prototype=fake.protos[fake.held], infusion=None)
        return ari

    # ---- engine functions ----------------------------------------------------------------------------

    def find_animal(self, idx, daycare=False):
        if idx == -1:
            return self.pet_state
        for b in self.buildings:
            for a in b.stable.stalls.data:
                if a is not None and a.idx == idx:
                    return a
        if daycare:
            for a in self.daycare:
                if a.idx == idx:
                    return a
        return None

    def make_animal(self, kind, variant, sex):
        a = G(idx=1000000 + len(self.rolls), kind=kind, variant=variant, sex=sex, name="Anon", heart_points=0, days_old=0,
              unhappy_days=0, has_eaten=False, has_been_pat=False, has_been_outside=False, production_days=0,
              ate_breeding_treat=False, breeding_with=None, is_incubating=False, cosmetic=None, birthday=0, stable=None,
              instance=None, is_pet=False)
        self.rolls.append(a)
        a.prototype = self.animal_protos[kind]
        a.is_baby = lambda: a.days_old < 3
        a.can_pet = lambda: not a.has_been_pat
        a.is_present = lambda: False
        a.sell_value = lambda: 100 + int(a.heart_points) // 10
        return a

    def erase(self, grid, i):
        node = grid.node_parent[i]
        for k in range(len(grid.node_parent)):
            if grid.node_parent[k] is node:
                grid.node_parent[k] = None
                grid.node_object_id[k] = None
        if node in self.factories.data:
            self.factories.data.remove(node)
        return True

    def write_blueprint(self, grid, x, y, bp, item):
        cells = [(x + dx, y + dy) for dx in range(4) for dy in range(4)]
        if not self.free(grid, cells):
            return False
        box = G(object_id=O_SITE_BOX, top_left_x=x, top_left_y=y, parent_grid=grid, blueprint_id=bp,
                blueprint_top_left_x=x, blueprint_top_left_y=y, blueprint_spawner=item)
        self.occupy(grid, box, cells[:1])
        filler = G(object_id=FILLER, top_left_x=x + 1, top_left_y=y + 1, parent_grid=grid)
        self.occupy(grid, filler, cells[1:])
        return True

    def remove_blueprint(self, grid, x, y, bp):
        for dx in range(4):
            for dy in range(4):
                i = grid.try_node_index_for_cell(x + dx, y + dy)
                grid.node_object_id[i] = None
                grid.node_parent[i] = None

    def write_building(self, grid, x, y, o, variant):
        cells = [(x + dx, y + dy) for dx in range(4) for dy in range(4)]
        if not self.free(grid, cells):
            return None
        dyn = 100 + len(self.buildings)
        self.add_building(x, y, dyn, SMALL, 4)
        node = self.buildings[-1]
        node.update(parent_grid=grid, top_left_x=x, top_left_y=y, variant=variant)
        self.occupy(grid, node, cells)
        return node

    def expand_farm(self):
        self.expanded = True
        self.node.interp.builtins["FARM_EXPANDED"] = True

    def install(self, node):
        fake = self
        interp = node.interp
        interp.builtins.update(ENUMS)
        interp.functions["mistrimulti_ranch_make_animal"] = self.make_animal
        interp.functions["mistrimulti_ranch_make_item"] = lambda i: G(item_id=i, prototype=self.protos[i])
        self.grids[FARM].write_node = lambda x, y, o, r: (
            self.write_building(self.grids[FARM], x, y, o, r) if o == O_BARN else self.write_node(self.grids[FARM], x, y, o, r))

        def get_buildings():
            return make_list(self.buildings)

        pet_fiddle = {"ranching/misc/heart_points/pet": 4, "ranching/misc/min_heart_level_for_breeding": 2,
                      "misc/home_variant_cost": 300}
        builtins = {
            "get_buildings": get_buildings, "find_animal": self.find_animal, "ANIMAL_PROTOTYPES": A(self.animal_protos),
            "ITEM_PROTOTYPES": A(self.protos), "NODE_PROTOTYPES": A(self.node_protos()),
            "BLUEPRINT_PROTOTYPES": A([G(size=G(x=4, y=4)), G(size=G(x=4, y=4))]), "GRIDS": self.grids, "GRID": G(dyn_index=None),
            "DECOR": self.decor, "ARI": self.ari, "PET": self.pet_state, "PET_ID": -1, "FACTORIES": self.factories,
            "FARM_EXPANDED": False, "CURRENT_LOCATION_ID": FARM, "GAME_STATS": self.stats,
            "ANIMAL_HEART_POINTS": G(base_value=2, feed=A([1, 2, 3, 4])), "ANIMAL_XP": G(feed=5),
            "EXPANSION_COST": G(gold=700, items=make_list([G(item_id=ITEM_HAY, count=3)])),
            "fiddle_get": lambda path: pet_fiddle[path],
            "animal_heart_level_to_points": lambda lvl: 100 * lvl, "points_to_animal_heart_level": lambda p: int(p // 100),
            "item_heart_value_for_animal": lambda proto: 6, "spawn_animal": lambda a: None,
            "instance_destroy": lambda i: None, "instance_exists": lambda i: False, "instance_find": lambda o, n: G(cell_select=self.cell),
            "obj_ari": "obj_ari", "create_notification": lambda t: fake.notes.append(t),
            "ANCHOR": G(wrap_for_local=lambda t: t), "clamp": lambda v, lo, hi: max(lo, min(hi, v)),
            "real": lambda s: float(s) if "." in s else int(s), "array_contains": lambda arr, v: v in arr,
            "irandom": lambda n: 0, "chance_percent": lambda p: False, "seasons": lambda s: 1000 * s, "days": lambda d: d,
            "CALENDAR": G(season=lambda: 1, day=lambda: 3), "total_days": lambda: self.day,
            "location_id_to_string": lambda i: LOCATION_NAMES[int(i)], "is_home_location": lambda i: int(i) == HOME,
            "object_id_to_object_category": lambda o: self.node_protos()[int(o)].category,
            "object_id_to_string": lambda o: str(int(o)), "item_id_to_string": lambda i: "item" + str(int(i)),
            "try_infusion_to_string": lambda inf: None, "erase_object_node": self.erase,
            "write_blueprint_to_location": self.write_blueprint, "remove_blueprint_from_location": self.remove_blueprint,
            "expand_farm": self.expand_farm, "save_text_file": lambda p, t: self.files.__setitem__(p, t),
            "file_exists": lambda p: p in self.files,
            "try_read_json_file": lambda p: gml.from_json(json.loads(self.files[p])),
            "string_lower": lambda s: s.lower(),
        }
        interp.builtins.update(builtins)

    cell = G(x=20, y=20)
    day = 7
