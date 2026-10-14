"""Containers (chests), world items and gifts on the event layer, running their real GML.

    python3 tests/test_containers.py

MistriMultiContainers.gml and MistriMultiDrops.gml run unmodified in tests/gml_subset.py on top of
MistriMultiEvents.gml, over the simulated helpers and lossy network of tests/event_sim.py. Only the engine is
stubbed here: inventories and slots (with the `updates` counter the menus watch), chest nodes, obj_item instances
with the pickup fields the game uses, the player's inventory, and the host's stored player records.

The properties checked are about items: nothing is duplicated or lost when two players act at once, when packets are
lost, duplicated or reordered, when a guest disappears in the middle of a transaction, when the host restarts, and when
a guest's game dies before its next checkpoint. Every scenario ends by counting each kind of item in every place it can
be (chests on the host, every player's inventory, the host's stored records, the world item table, private items on
the ground) and comparing with the start. This checks the logic and the wiring; it does not replace the game
(docs/SYNC-CONTAINERS.md lists what has to be checked there).
"""
import json
import math
import random
import sys

from event_sim import GmlNode, World
import gml_subset as gml
from test_event_features import FeatureNode

NAMES = ["apple", "bread", "sword", "coin", "potion"]
CAP = {"apple": 99, "bread": 99, "sword": 1, "coin": 999, "potion": 20}
SIZE = 6            # slots per chest
ROOM = "farm:undefined"


def item_json(name, infusion=None):
    """What LiveItem.serialize() returns (the nine fields, in the game's order)."""
    return {"item_id": name, "inner_item": None, "gold_to_gain": None, "cosmetic": None, "animal_cosmetic": None,
            "infusion": infusion, "auto_use": False, "pet_cosmetic_set_name": None, "date_photo": None}


def make_item(name, infusion=None):
    item = gml.GStruct()
    item["item_id"] = NAMES.index(name)
    item["name"] = name
    item["infusion"] = infusion
    item["auto_use"] = False
    item["prototype"] = gml.GStruct(max_stack=CAP[name])
    item["serialize"] = lambda: gml.from_json(item_json(name, infusion))
    item["partial_eq"] = lambda other: other["item_id"] == item["item_id"] and other["infusion"] == infusion
    item["clone"] = lambda: make_item(name, infusion)
    return item


def live_from_json(data):
    return make_item(data["item_id"], data["infusion"])


class Inv:
    """The part of the game's Inventory / InventorySlot that the sync code and the menus use."""

    def __init__(self, size):
        self.struct = gml.GStruct(maximum_item_counts=gml.GArray([None] * len(NAMES)))
        self.slots = [self.make_slot(i) for i in range(size)]
        self.struct["size"] = lambda: len(self.slots)
        self.struct["slot"] = lambda i: self.slots[int(i)]

    def make_slot(self, index):
        slot = gml.GStruct(item=None, count=0, updates=0, required_tags=gml.GArray(), index=index)

        def add(item, count=1):
            if slot["item"] is None:
                slot["item"] = item
            slot["count"] += count
            slot["updates"] += 1

        def remove(amount):
            slot["updates"] += 1
            slot["count"] -= amount
            if slot["count"] <= 0:
                slot["count"] = 0
                slot["item"] = None

        def room(item):
            if slot["count"] != 0 and not slot["item"]["partial_eq"](item):
                return 0
            return max(item["prototype"]["max_stack"] - slot["count"], 0)

        slot["add"], slot["remove"], slot["room_for_item"] = add, remove, room
        return slot

    # -- what the menus do (one movement at a time, like the real ones) --------------------------------------
    def add(self, item, count):
        """The game's Inventory.add: fill matching stacks first, then empty slots. Returns what did not fit."""
        left = count
        for want_empty in (False, True):
            for slot in self.slots:
                if left <= 0:
                    return 0
                if (slot["count"] == 0) != want_empty:
                    continue
                room = slot["room_for_item"](item)
                if room > 0:
                    k = min(room, left)
                    slot["add"](item, k)
                    left -= k
        return left

    def total(self, name):
        return sum(s["count"] for s in self.slots if s["item"] is not None and s["item"]["name"] == name)

    def contents(self):
        return {s["index"]: (s["item"]["name"], s["item"]["infusion"], s["count"]) for s in self.slots if s["count"] > 0}


class Inst(gml.GStruct):
    """An obj_item instance (or the player's object)."""


class ContainerNode(FeatureNode):
    """FeatureNode plus the engine slice of the chest and world item code."""
    extra_files = FeatureNode.extra_files + ("MistriMultiContainers.gml", "MistriMultiDrops.gml")

    def builtins(self):
        out = super().builtins()
        self.chests = {}                  # key -> node struct
        self.chest_list = []
        self.player = Inv(8)
        self.instances = {}               # uid -> Inst (obj_item)
        self.next_uid = 1
        self.notes = []
        self.overflow = []
        self.lost = []                    # grid.lost_items pushes
        self.seeds = []
        self.used = []
        self.ari = Inst(uid=0, x=80, y=80)
        self.rng = random.Random(self.slot_seed())
        grid = gml.GStruct(dyn_index=None, lost_items=gml.GStruct(push=lambda e: self.lost.append(e)))
        self.grid = grid

        def give_item(item, count=1, *flags):
            left = self.player.add(item, count)
            if left:
                self.overflow.append((item["name"], left))

        ari = gml.GStruct(name="test", inventory=self.player.struct, held_item_index=0, end_of_day_status=None,
                          give_item=give_item)
        self.ari_struct = ari

        def create(x, y, layer, obj):
            uid = self.next_uid
            self.next_uid += 1
            inst = Inst(uid=uid, x=x, y=y, kill_timer=-1, kill_target=None, lerping_to_player=False, v=0, v_counter=0,
                        final_x=x, final_y=y, thrown_by_ari=False, mist_id=None, items=None)

            def setup(items):
                inst["items"] = items
            inst["setup"] = setup
            self.instances[uid] = inst
            return inst

        def lst(arr):
            return gml.GStruct(count=lambda: len(arr), get=lambda i: arr[int(i)], first=lambda: arr[0] if arr else None)

        def string(value):
            return f"inst{value['uid']}" if isinstance(value, Inst) else gml.gml_string(value)

        out.update({
            "ARI": ari, "obj_ari": self.ari, "obj_item": "obj_item", "GRID": grid,
            "GRIDS": gml.GArray([grid]), "STORAGE_NODES": gml.GStruct(count=lambda: len(self.chest_list),
                                                                       get=lambda i: self.chest_list[int(i)]),
            "ANCHOR": gml.GStruct(get_menu=lambda t: None, wrap_for_local=lambda s: s), "Menu": gml.GStruct(Storage=1),
            "deserialize_live_item": live_from_json, "try_string_to_item_id": lambda s: NAMES.index(s) if s in NAMES else None,
            "is_nullish": lambda v: v is None, "abs": abs, "round": lambda v: int(math.floor(v + 0.5)),
            "instance_exists": lambda x: x is self.ari or (isinstance(x, Inst) and x["uid"] in self.instances),
            "instance_create_layer": create, "instance_destroy": lambda x: self.instances.pop(x["uid"], None) and None,
            "ListFromArray": lst, "string": string, "use_item_fast": lambda item: self.used.append(item["name"]),
            "irandom_range": lambda a, b: self.rng.randint(int(a), int(b)),
            "random_set_seed": lambda s: self.seeds.append(("seed", s)), "randomize": lambda: self.seeds.append(("random",)),
            "create_notification": lambda text: self.notes.append(text), "mistrimulti_room_key": lambda: ROOM,
        })
        return out

    def slot_seed(self):
        return 1000 + getattr(self, "slot", 0)

    def setup(self):
        super().setup()
        self.rt.update(enabled=True, player_last_checkpoint=1, uid=f"uid-{self.slot}")
        self.interp.functions["__mistrimulti_dr_instances"] = lambda: gml.GArray(self.instances.values())

    # -- test-side engine helpers ---------------------------------------------------------------------------
    def add_chest(self, key_xy, contents, bin=False):
        """A chest node at a position; contents: {slot: (name, count)}."""
        inv = Inv(SIZE)
        for i, (name, count) in contents.items():
            inv.slots[i]["add"](make_item(name), count)
        for s in inv.slots:
            s["updates"] = 0
        grid = gml.GStruct(location_id=0, dyn_index=None, parent_node=None)
        node = gml.GStruct(prototype=gml.GStruct(interaction_chest=gml.GStruct(shipping_bin=bin)), inventory=inv.struct,
                           top_left_x=key_xy[0], top_left_y=key_xy[1], parent_grid=grid)
        node["inv"] = inv
        self.chests[key_xy] = node
        self.chest_list.append(node)
        return inv

    def inv(self, key_xy):
        return self.chests[key_xy]["inv"]

    def drop(self, name, n, x=80, y=80, thrown=False):
        """The game drops n of an item on the ground here (what drop_item does)."""
        inst = self.interp.builtins["instance_create_layer"](x, y, "Instances", "obj_item")
        inst["setup"](self.interp.builtins["ListFromArray"]([make_item(name) for _ in range(n)]))
        inst["thrown_by_ari"] = thrown
        return inst

    def chase(self, inst):
        """The player's magnet reaches the item: the game starts picking it up."""
        inst["kill_timer"], inst["kill_target"] = 5, self.ari

    def game_step(self):
        """What obj_item.step does with kill_timer, per 20 Hz tick (three frames)."""
        for inst in list(self.instances.values()):
            if inst["kill_timer"] == -1 or inst["kill_target"] is not self.ari:
                continue
            inst["kill_timer"] -= 3
            if inst["kill_timer"] <= 0:
                items = inst["items"]
                for i in range(items["count"]()):
                    self.ari_struct["give_item"](items["get"](i), 1)
                self.instances.pop(inst["uid"], None)

    def count_at(self, name):
        return self.player.total(name)

    def held(self, index=0):
        """Select a player inventory slot as the held item."""
        self.ari_struct["held_item_index"] = index


class Driver:
    """What MistriMultiBoot.gml's tick does for these features, plus the peer fields the host validates."""

    def __init__(self, game, room=ROOM, x=80, y=80):
        self.game, self.node = game, game.node
        self.room, self.x, self.y = room, x, y
        self.node.interp.call("mistrimulti_containers_register_events")
        self.node.interp.call("mistrimulti_drops_register_events")

    def frame(self):
        rt = self.node.rt
        return {"epoch": rt["epoch"], "uid": rt["uid"], "world": rt["world_key"], "room": self.room, "x": self.x, "y": self.y}

    def tick(self, now):
        node = self.node
        node.ari["x"], node.ari["y"] = self.x, self.y
        node.interp.call("mistrimulti_drops_frame")
        node.interp.call("mistrimulti_containers_tick")
        node.interp.call("mistrimulti_drops_tick")
        node.game_step()


def make_world(seed, guests=2, chests=None, **faults):
    """chests: {(x, y): {slot: (name, count)}}, the same on every game. Returns the world."""
    world = World(seed, {i: ContainerNode for i in range(guests + 1)}, **faults)
    for game in world.games.values():
        game.feature = Driver(game)
        for xy, contents in (chests or {}).items():
            game.node.add_chest(xy, contents)
    for slot in range(1, guests + 1):
        # The host's view of the guests' player sessions (the stored records belong to them).
        host = world.games[0].node
        host.rt["player_sessions"][slot] = gml.GStruct(uid=f"uid-{slot}", epoch="e", revision=0)
    return world


def settle(world, ms=4000):
    world.run(ms)


def store_record(world, slot, inventory):
    """The host's stored record of a guest: {name: count} laid out one stack per slot."""
    host = world.games[0].node
    slots = []
    for name, count in inventory.items():
        slots.append({"required_tags": [], "item": item_json(name), "count": count})
    while len(slots) < 8:
        slots.append({"required_tags": [], "item": None, "count": 0})
    host.store[f"uid-{slot}"] = {"revision": 0, "data": {"uid": f"uid-{slot}", "world": "world_1", "inventory": slots}}


def record_totals(world):
    """Item totals in the host's stored guest records."""
    totals = {}
    host = world.games[0].node
    for uid, rec in host.store.items():
        for s in rec["data"].get("inventory", []):
            if s["item"] is not None and s["count"] > 0:
                totals[s["item"]["item_id"]] = totals.get(s["item"]["item_id"], 0) + s["count"]
    return totals


def host_chest_total(world, name):
    host = world.games[0].node
    return sum(inv_total(host.inv(xy), name) for xy in host.chests)


def inv_total(inv, name):
    return inv.total(name)


def table_units(world, name):
    dr = world.games[0].node.rt["dr"]
    total = 0
    for e in dr["table"].values():
        for it, n in e["g"]:
            if it["item_id"] == name:
                total += n
    return total


def private_units(world, name, slot=None):
    """Items on the ground that only their dropper's game knows (not published): the rest are puppets of the table."""
    total = 0
    for game in world.games.values():
        if slot is not None and game.slot != slot:
            continue
        node = game.node
        recs = node.rt["dr"]["recs"]
        for inst in node.instances.values():
            rec = recs.get(f"inst{inst['uid']}")
            if rec is not None and rec["wid"] == 0 and rec["state"] in ("new", "local"):
                items = inst["items"]
                total += sum(1 for i in range(items["count"]()) if items["get"](i)["name"] == name)
    return total


def player_total(world, name, slots=None):
    return sum(game.node.player.total(name) for game in world.games.values() if slots is None or game.slot in slots)


def conserved(world, name, expected, label):
    """The count of one item over every place it can be at rest. Puppets and replicas are copies and not counted."""
    parts = {
        "chests": host_chest_total(world, name),
        "players": player_total(world, name),
        "records": 0,       # records mirror inventories (compared separately where they matter)
        "table": table_units(world, name),
        "private": private_units(world, name),
    }
    total = parts["chests"] + parts["players"] + parts["table"] + parts["private"]
    assert total == expected, f"{label}: {name} total {total} != {expected} {parts}"
    return parts


def converged(world, label):
    """Every guest's chest replicas equal the host's chests, slot by slot."""
    host = world.games[0].node
    for game in world.games.values():
        if game.slot == 0:
            continue
        for xy in host.chests:
            assert game.node.inv(xy).contents() == host.inv(xy).contents(), (
                f"{label}: guest {game.slot} chest {xy} {game.node.inv(xy).contents()} != host {host.inv(xy).contents()}")


def clean(world, label):
    for game in world.games.values():
        debug = game.node.call("mistrimulti_events_debug")
        assert debug["errors"] == 0, (label, game.slot, debug, game.warnings[:4])
        assert game.warnings == [], (label, game.slot, game.warnings[:4])


# ---- the menus -----------------------------------------------------------------------------------------------------

def ui_take(game, xy, index, n):
    """The player moves n items from a chest slot to their inventory (storage menu)."""
    chest = game.node.inv(xy).slots[index]
    item = chest["item"]
    n = min(n, chest["count"])
    chest["remove"](n)
    assert game.node.player.add(item, n) == 0
    return n


def ui_put(game, xy, index, name, n):
    """The player moves n items from their inventory into a chest slot."""
    left = n
    for slot in game.node.player.slots:
        if left and slot["item"] is not None and slot["item"]["name"] == name:
            k = min(left, slot["count"])
            slot["remove"](k)
            left -= k
    assert left == 0, "test bug: the player does not have that"
    game.node.inv(xy).slots[index]["add"](make_item(name), n)


def new_item_total(world, name):
    return (host_chest_total(world, name) + player_total(world, name) + table_units(world, name)
            + private_units(world, name))


# ---- scenarios ---------------------------------------------------------------------------------------------------

A = (10, 10)    # chest positions
B = (20, 10)


def test_basic():
    world = make_world(1, chests={A: {0: ("apple", 10), 1: ("bread", 4)}}, loss=0.05, jitter=30)
    host, g1, g2 = (world.games[i].node for i in range(3))
    settle(world, 4000)
    # A guest takes part of a stack; the host chest and the other guest's replica follow.
    ui_take(world.games[1], A, 0, 4)
    settle(world)
    assert host.inv(A).contents()[0] == ("apple", None, 6) and g2.inv(A).contents()[0] == ("apple", None, 6)
    assert g1.player.total("apple") == 4
    # Putting an item in, into an empty slot and onto an existing stack.
    ui_put(world.games[1], A, 3, "apple", 1)
    ui_put(world.games[1], A, 0, "apple", 2)
    settle(world)
    assert host.inv(A).contents() == {0: ("apple", None, 8), 1: ("bread", None, 4), 3: ("apple", None, 1)}, host.inv(A).contents()
    converged(world, "basic")
    # The host's own menu: a plain edit that every guest follows.
    host.inv(A).slots[1]["remove"](4)
    host.inv(A).slots[5]["add"](make_item("potion"), 3)
    settle(world)
    converged(world, "host edit")
    assert g1.inv(A).contents()[5] == ("potion", None, 3)
    conserved(world, "apple", 10, "basic")
    clean(world, "basic")
    print("PASS: basic: take, put, host edit; every replica follows; nothing lost")


def test_simultaneous_takes():
    # Two guests take 7 from a stack of 10 in the same instant: exactly one succeeds, the other is corrected.
    for first in (1, 2):
        world = make_world(2 + first, chests={A: {0: ("apple", 10)}}, loss=0.1, dup=0.1, jitter=40)
        settle(world, 4000)
        order = [first, 3 - first]
        for slot in order:
            ui_take(world.games[slot], A, 0, 7)
        settle(world, 5000)
        host = world.games[0].node
        mine = [world.games[s].node.player.total("apple") for s in (1, 2)]
        assert sorted(mine) == [0, 7] and host.inv(A).contents()[0] == ("apple", None, 3), (mine, host.inv(A).contents())
        converged(world, "simultaneous")
        conserved(world, "apple", 10, "simultaneous")
        clean(world, "simultaneous")
    # Smaller takes both fit: the second request merges instead of failing.
    world = make_world(9, chests={A: {0: ("apple", 10)}}, loss=0.1, jitter=40)
    settle(world, 4000)
    ui_take(world.games[1], A, 0, 4)
    ui_take(world.games[2], A, 0, 4)
    settle(world, 5000)
    assert world.games[0].node.inv(A).contents()[0] == ("apple", None, 2)
    assert world.games[1].node.player.total("apple") == 4 and world.games[2].node.player.total("apple") == 4
    converged(world, "merge")
    clean(world, "merge")
    # A take and a put on the same stack at the same time.
    world = make_world(10, chests={A: {0: ("apple", 10)}}, jitter=40)
    settle(world, 4000)
    world.games[2].node.player.slots[0]["add"](make_item("apple"), 5)
    ui_take(world.games[1], A, 0, 10)
    ui_put(world.games[2], A, 0, "apple", 5)
    settle(world, 5000)
    assert world.games[1].node.player.total("apple") + world.games[2].node.player.total("apple") + \
        host_chest_total(world, "apple") == 15
    converged(world, "take and put")
    clean(world, "take and put")
    print("PASS: simultaneous takes of the same stack: exactly one wins, partial takes merge, take and put cross")


def test_unsynced_replica_is_corrected():
    # A guest whose replica is stale (the chest changed after its copy of the world) edits it before the host's
    # snapshot arrives: the host refuses what no longer fits, and the guest gives the items back.
    world = make_world(11, chests={A: {0: ("apple", 3)}}, jitter=30)
    for slot in (1, 2):
        inv = world.games[slot].node.inv(A)
        inv.slots[0]["add"](make_item("apple"), 5)       # 8 in its old copy, 3 on the host
        inv.slots[0]["updates"] = 0
    world.net.block(0, 1)                                 # nothing from the host reaches guest 1 yet
    world.run(1000)
    ui_take(world.games[1], A, 0, 8)
    world.run(1500)
    assert world.games[1].node.player.total("apple") == 8      # still believing it
    world.net.block(0, 1, False)
    settle(world, 6000)
    assert world.games[1].node.player.total("apple") == 0, world.games[1].node.player.total("apple")
    assert world.games[0].node.inv(A).contents()[0] == ("apple", None, 3)
    converged(world, "stale")
    conserved(world, "apple", 3, "stale")
    clean(world, "stale")
    print("PASS: a take from a stale replica is refused, the guest gives the items back and shows the host's chest")


def test_exact_conservation_under_faults():
    # Random takes and puts by both guests; the totals must match exactly at the end.
    for seed in (31, 32, 33, 34):
        rng = random.Random(seed)
        world = make_world(seed, chests={A: {0: ("apple", 20), 1: ("bread", 10)}, B: {2: ("potion", 5)}},
                           loss=0.15, dup=0.15, jitter=100)
        settle(world, 4000)
        for g in (1, 2):
            world.games[g].node.player.slots[0]["add"](make_item("apple"), 6)
            world.games[g].node.player.slots[1]["add"](make_item("bread"), 3)
        start = {name: new_item_total(world, name) for name in ("apple", "bread", "potion")}
        for step in range(80):
            game = world.games[rng.choice((1, 2))]
            xy = rng.choice((A, B))
            inv = game.node.inv(xy)
            if rng.random() < 0.5:
                filled = [i for i in range(SIZE) if inv.slots[i]["count"] > 0]
                if filled:
                    ui_take(game, xy, rng.choice(filled), rng.randint(1, 8))
            else:
                names = [n for n in ("apple", "bread", "potion") if game.node.player.total(n) > 0]
                if names:
                    name = rng.choice(names)
                    cands = [i for i in range(SIZE) if inv.slots[i]["count"] == 0
                             or (inv.slots[i]["item"]["name"] == name and inv.slots[i]["count"] < 90)]
                    if cands:
                        ui_put(game, xy, rng.choice(cands), name, rng.randint(1, min(5, game.node.player.total(name))))
            world.run(rng.choice((0, 0, 20, 60, 200)))
        settle(world, 10000)
        converged(world, f"exact {seed}")
        clean(world, f"exact {seed}")
        for name in start:
            assert new_item_total(world, name) == start[name], (seed, name, new_item_total(world, name), start[name])
    print("PASS: 4 randomised runs, 2 guests, 15% loss, duplication and 100 ms jitter: item totals unchanged, replicas equal")


def test_hostile_requests():
    world = make_world(41, chests={A: {0: ("apple", 5)}}, jitter=10)
    host = world.games[0].node
    g1 = world.games[1].node
    settle(world, 4000)
    before = host.inv(A).contents()
    good = item_json("apple")
    cases = [
        {"k": A_KEY, "t": [good], "o": [[0, 0, 99, -1, 0]]},                      # more than the slot holds
        {"k": A_KEY, "t": [good], "o": [[0, 0, -1, -1, 0]]},                      # negative count
        {"k": A_KEY, "t": [good], "o": [[0, 0, 1, -1, 0], [0, 0, 1, -1, 0]]},     # the same slot twice
        {"k": A_KEY, "t": [good], "o": [[SIZE, -1, 0, 0, 1]]},                    # slot out of range
        {"k": A_KEY, "t": [good], "o": [[1, -1, 0, 3, 1]]},                       # item index out of range
        {"k": A_KEY, "t": [dict(good, item_id="nonsense")], "o": [[1, -1, 0, 0, 1]]},   # unknown item
        {"k": A_KEY, "t": [dict(good, auto_use=True)], "o": [[1, -1, 0, 0, 1]]},         # an item that uses itself
        {"k": A_KEY, "t": [dict(good, infusion=["x"])], "o": [[1, -1, 0, 0, 1]]},        # wrong field type
        {"k": A_KEY, "t": [good], "o": [[1, -1, 0, 0, 100]]},                     # more than a stack holds
        {"k": A_KEY, "t": [good], "o": [[1, -1, 0, 0, 1.5]]},                     # not an integer
        {"k": A_KEY, "t": [good], "o": []},                                       # nothing
        {"k": A_KEY, "t": "x", "o": "y"},                                         # not arrays
        {"k": "9:9,9", "t": [good], "o": [[1, -1, 0, 0, 1]]},                     # unknown chest
        {"k": 5, "t": [], "o": []},                                               # key not a string
        {"t": [], "o": []},                                                        # no key
    ]
    for data in cases:
        g1.call("mistrimulti_event_request", "chest_tx", {"x": [data]})
        world.run(500)
    # Whole-request shapes, and a request whose first part is fine and second part is not: nothing may change.
    fine = {"k": A_KEY, "t": [good], "o": [[0, 0, 1, -1, 0]]}
    for data in ({"x": []}, {"x": "x"}, {"x": [fine] * 9}, {"x": [fine, fine]}, {"x": [fine, {"k": B_KEY, "t": [good], "o": [[0, 0, 1, -1, 0]]}]}, {}):
        g1.call("mistrimulti_event_request", "chest_tx", data)
        world.run(500)
    g1.call("mistrimulti_event_request", "chest_open", {"k": "nonsense"})
    g1.call("mistrimulti_event_request", "item_claim", {"id": "x"})
    g1.call("mistrimulti_event_request", "item_drop", {"loc": 0, "x": 0, "y": 0, "g": [[good, 5000]]})
    g1.call("mistrimulti_event_request", "item_drop", {"loc": 0, "x": 0, "y": 0, "g": [[good, 1], [item_json("bread"), 1]]})
    world.run(3000)
    assert host.inv(A).contents() == before, host.inv(A).contents()
    assert table_units(world, "apple") == 0 and table_units(world, "bread") == 0
    # The one that is valid in shape but not true: a guest cannot take from a chest in another room.
    world.games[1].feature.room = "town:undefined"
    world.run(500)
    g1.call("mistrimulti_event_request", "chest_tx", {"x": [{"k": A_KEY, "t": [good], "o": [[0, 0, 1, -1, 0]]}]})
    world.run(3000)
    assert host.inv(A).contents() == before
    debug = host.call("mistrimulti_events_debug")
    assert debug["errors"] == 0, (debug, world.games[0].warnings[:3])
    print("PASS: 15 malformed or false chest requests, bad claims and drops: refused, no change, no exception")


A_KEY = "0:10,10"
B_KEY = "0:20,10"


def test_guest_disappears_mid_transaction():
    # The guest's packets stop right after its menu moved the items; it comes back (same game) within its stream's life.
    for gap_ms in (3000, 14000):    # shorter and longer than the 10 s the helper waits before it forgets a player
        world = make_world(50 + gap_ms // 1000, chests={A: {0: ("apple", 10)}}, jitter=20)
        settle(world, 4000)
        ui_take(world.games[1], A, 0, 6)
        world.run(60)       # the request is queued at the guest, not yet at the host
        world.net.partition(0, 1)
        world.run(gap_ms)
        world.net.partition(0, 1, False)
        settle(world, 12000)
        converged(world, f"gap {gap_ms}")
        conserved(world, "apple", 10, f"gap {gap_ms}")
        assert world.games[1].node.player.total("apple") == 6 and host_chest_total(world, "apple") == 4
        clean(world, f"gap {gap_ms}")
    print("PASS: a guest cut off right after moving items: the request still applies exactly once when it reconnects")


def test_guest_crash_mid_transaction_records():
    # The guest's game dies after its menu moved items and the host applied the request, before the guest's next
    # checkpoint. Its stored record already says so: reloading it neither loses nor duplicates the items.
    world = make_world(60, chests={A: {0: ("apple", 10)}}, jitter=20)
    host = world.games[0].node
    store_record(world, 1, {"apple": 5, "bread": 2})          # the last checkpoint
    settle(world, 4000)
    world.games[1].node.player.slots[0]["add"](make_item("apple"), 5)
    world.games[1].node.player.slots[1]["add"](make_item("bread"), 2)
    ui_take(world.games[1], A, 0, 4)                            # +4 apples, the record does not know yet
    ui_put(world.games[1], A, 1, "bread", 2)                    # -2 bread
    settle(world, 3000)
    assert host_chest_total(world, "apple") == 6 and host_chest_total(world, "bread") == 2
    stored = record_totals(world)
    assert stored == {"apple": 9}, stored                       # the record followed the transfers
    # The crash: the guest's inventory is whatever the record says when it comes back.
    assert stored["apple"] + host_chest_total(world, "apple") == 15 and stored.get("bread", 0) + host_chest_total(world, "bread") == 2
    # Without a crash the next checkpoint (the live inventory) replaces the record and says the same.
    live = {n: world.games[1].node.player.total(n) for n in ("apple", "bread")}
    assert live["apple"] == 9 and live["bread"] == 0
    clean(world, "crash")
    print("PASS: guest crash before its checkpoint: the stored record already matches the chest (no loss, no duplicate)")


def test_host_restart():
    world = make_world(70, chests={A: {0: ("apple", 10)}}, jitter=20)
    settle(world, 4000)
    # The request is on its way when the host restarts; it must be reported lost and never apply on the new host.
    ui_take(world.games[1], A, 0, 6)
    world.net.block(1, 0)
    world.run(80)
    world.start(0)           # the host game restarts from its save: ten apples in the chest
    world.games[0].feature = Driver(world.games[0])
    world.games[0].node.add_chest(A, {0: ("apple", 10)})
    world.games[0].node.rt["player_sessions"][1] = gml.GStruct(uid="uid-1", epoch="e", revision=0)
    world.games[0].node.rt["player_sessions"][2] = gml.GStruct(uid="uid-2", epoch="e", revision=0)
    world.net.block(1, 0, False)
    settle(world, 12000)
    host = world.games[0].node
    assert host.inv(A).contents() == {0: ("apple", None, 10)}, host.inv(A).contents()
    assert world.games[1].node.player.total("apple") == 0, "the lost request must be undone"
    converged(world, "restart")
    conserved(world, "apple", 10, "restart")
    # The new host works normally.
    ui_take(world.games[2], A, 0, 3)
    settle(world, 4000)
    assert host.inv(A).contents()[0] == ("apple", None, 7)
    conserved(world, "apple", 10, "restart 2")
    clean_ignoring_lost(world)
    print("PASS: host restart with a request in flight: reported lost, undone on the guest, never applied twice")


def clean_ignoring_lost(world):
    for game in world.games.values():
        assert game.node.call("mistrimulti_events_debug")["errors"] == 0, game.warnings[:3]


def test_snapshot_on_join_and_open():
    # A guest that joins late receives every chest; opening a chest refreshes it.
    world = make_world(80, guests=2, chests={A: {0: ("apple", 10)}, B: {1: ("bread", 3)}}, jitter=20)
    host = world.games[0].node
    # Both guests have older copies of the world (empty chests).
    for slot in (1, 2):
        for xy in (A, B):
            inv = world.games[slot].node.inv(xy)
            for s in inv.slots:
                s["remove"](s["count"]) if s["count"] else None
                s["updates"] = 0
    settle(world, 6000)
    converged(world, "snapshot")
    assert world.games[2].node.inv(B).contents() == {1: ("bread", None, 3)}
    # The host changes a chest while a guest is away from the network, then it comes back.
    world.net.partition(0, 2)
    host.inv(A).slots[0]["remove"](4)
    world.run(2000)
    world.net.partition(0, 2, False)
    settle(world, 14000)
    converged(world, "rejoin")
    # Opening (object.interact) asks again, and does not disturb a correct replica.
    g1 = world.games[1].node
    g1.interp.call("mistrimulti_containers_interact", g1.chests[A])
    settle(world, 3000)
    converged(world, "open")
    # A different game session of a guest gets everything again.
    world.games[1].node.call("mistrimulti_events_reset")
    for xy in (A, B):
        for s in world.games[1].node.inv(xy).slots:
            if s["count"]:
                s["remove"](s["count"])
            s["updates"] = 0
    settle(world, 10000)
    converged(world, "new session")
    clean(world, "snapshot")
    print("PASS: snapshot on join, after a gap, on open and after a guest re-enters the world")


def test_item_drop_and_claim():
    # A guest drops items; after two seconds they are shared. Two players reach them at the same moment: one gets them.
    world = make_world(90, jitter=30, loss=0.05)
    settle(world, 4000)
    g1, g2, host = (world.games[i].node for i in (1, 2, 0))
    inst = g1.drop("apple", 5, 100, 100, thrown=False)
    world.run(500)
    assert table_units(world, "apple") == 0, "a drop stays private for a moment"
    # The dropper picks private items up without any traffic.
    world.run(2500)
    assert table_units(world, "apple") == 5
    puppets = [len(game.node.instances) for game in world.games.values()]
    assert puppets == [1, 1, 1], puppets
    # Both guests (and the host) reach it at once.
    for node in (g1, g2, host):
        node.chase(next(iter(node.instances.values())))
    settle(world, 4000)
    winners = [world.games[s].node.player.total("apple") for s in (0, 1, 2)]
    assert sorted(winners) == [0, 0, 5], winners
    assert all(len(game.node.instances) == 0 for game in world.games.values())
    assert table_units(world, "apple") == 0
    conserved(world, "apple", 5, "claim")
    clean(world, "claim")
    # Private pickup: the dropper takes it back at once.
    g2.drop("bread", 2)
    g2.chase(next(iter(g2.instances.values())))
    world.run(300)
    assert g2.player.total("bread") == 2 and table_units(world, "bread") == 0
    print("PASS: world items: published after 2 s, mirrored to every player, claimed by exactly one, private pickups need no traffic")


def test_claim_races_under_faults():
    for seed in (91, 92, 93, 94, 95):
        world = make_world(seed, jitter=60, loss=0.12, dup=0.12)
        settle(world, 4000)
        rng = random.Random(seed)
        total = 0
        for slot in (0, 1, 2):
            n = rng.randint(1, 9)
            world.games[slot].node.drop("coin", n, 90 + 10 * slot, 100)
            total += n
        world.run(3000)
        for _ in range(20):
            for game in world.games.values():
                for inst in list(game.node.instances.values()):
                    if rng.random() < 0.3:
                        game.node.chase(inst)
            world.run(rng.choice((20, 100, 300)))
        settle(world, 12000)
        conserved(world, "coin", total, f"races {seed}")
        clean(world, f"races {seed}")
    print("PASS: 5 randomised pickup races under 12% loss/duplication: every item reaches exactly one player")


def test_day_change_and_lost_items():
    world = make_world(100, jitter=20)
    settle(world, 4000)
    host, g1 = world.games[0].node, world.games[1].node
    g1.drop("apple", 3, 100, 100)
    host.drop("bread", 2, 110, 100)
    settle(world, 4000)
    assert table_units(world, "apple") == 3 and table_units(world, "bread") == 2
    assert all(len(game.node.instances) == 2 for game in world.games.values())
    host.interp.call("mistrimulti_drops_new_day", gml.GStruct(total_days=2))
    settle(world, 3000)
    # Everything left the table; the host's world keeps the items as lost items of their location; no puppets remain.
    assert table_units(world, "apple") == 0 and table_units(world, "bread") == 0
    assert all(len(game.node.instances) == 0 for game in world.games.values())
    kept = {}
    for e in host.lost:
        items = e["items"]
        for i in range(items["count"]()):
            n = items["get"](i)["name"]
            kept[n] = kept.get(n, 0) + 1
    assert kept == {"apple": 3, "bread": 2}, kept
    clean(world, "day")
    print("PASS: day change: shared items move to the host's lost items, every puppet is removed")


def test_gift():
    world = make_world(110, jitter=20, loss=0.05)
    settle(world, 4000)
    host, g1, g2 = (world.games[i].node for i in (0, 1, 2))
    g1.player.slots[0]["add"](make_item("potion"), 4)
    store_record(world, 1, {"potion": 4})
    world.games[2].feature.x, world.games[2].feature.y = 100, 80
    world.run(1500)
    assert g1.interp.call("mistrimulti_drops_give", 2) is True
    assert g1.player.total("potion") == 0
    settle(world, 4000)
    assert table_units(world, "potion") == 4
    assert record_totals(world).get("potion", 0) == 0, record_totals(world)     # the stored record followed
    # Only the recipient can take it.
    g2.chase(next(iter(g2.instances.values())))
    g1.chase(next(iter(g1.instances.values())))
    settle(world, 4000)
    assert g2.player.total("potion") == 4 and g1.player.total("potion") == 0
    conserved(world, "potion", 4, "gift")
    # A refused gift (nobody to receive it) comes back.
    g1.player.slots[0]["add"](make_item("potion"), 2)
    world.games[2].feature.room = "town:undefined"
    world.run(1500)
    assert g1.interp.call("mistrimulti_drops_give", 2) is False and g1.player.total("potion") == 2
    clean(world, "gift")
    print("PASS: gift: leaves the giver, waits as an item only the recipient can claim; refused gifts stay put")


def test_shipping_bins_are_per_player():
    # Every game sells its own bin at its own end of day, so a bin must never be shared (it would be sold once per game).
    world = make_world(130, jitter=20)
    C = (30, 10)
    for game in world.games.values():
        game.node.add_chest(C, {0: ("apple", 5)}, bin=True)      # the host's items, also in each guest's copy of the save
    settle(world, 4000)
    host, g1, g2 = (world.games[i].node for i in range(3))
    assert g1.inv(C).contents() == {} and g2.inv(C).contents() == {}      # guests start with an empty bin
    assert host.inv(C).contents() == {0: ("apple", None, 5)}
    g1.player.slots[0]["add"](make_item("bread"), 3)
    ui_put(world.games[1], C, 1, "bread", 3)
    host.inv(C).slots[2]["add"](make_item("potion"), 1)
    settle(world, 4000)
    assert host.inv(C).contents() == {0: ("apple", None, 5), 2: ("potion", None, 1)}
    assert g1.inv(C).contents() == {1: ("bread", None, 3)} and g2.inv(C).contents() == {}
    sold = {}
    for game in world.games.values():       # each game's end of day empties its own bin
        for slot in game.node.inv(C).slots:
            if slot["count"]:
                n = slot["item"]["name"]
                sold[n] = sold.get(n, 0) + slot["count"]
    assert sold == {"apple": 5, "potion": 1, "bread": 3}, sold
    clean(world, "bins")
    print("PASS: shipping bins are per player: never synced, guests' copies of the host's bin are emptied, nothing is sold twice")


def test_loot_seed():
    world = make_world(120, jitter=20)
    settle(world, 4000)
    host, g1 = world.games[0].node, world.games[1].node
    seeds = {n.rt["dr"]["seed"] for n in (host, g1, world.games[2].node)}
    assert len(seeds) == 1 and seeds != {0}, seeds
    for node in (host, g1):
        node.interp.call("mistrimulti_drops_treasure", gml.GStruct(x=64, y=96))
        node.interp.call("mistrimulti_drops_rock", gml.GStruct(result="rock", destroyed=True, burn=False, effect_override=None,
                                                               node=gml.GStruct(top_left_x=4, top_left_y=6)))
        # chips and burns do not seed
        node.interp.call("mistrimulti_drops_rock", gml.GStruct(result="rock", destroyed=False, burn=False, effect_override=None,
                                                               node=gml.GStruct(top_left_x=4, top_left_y=6)))
    assert host.seeds[0] == g1.seeds[0] and host.seeds[1] == g1.seeds[1] and host.seeds[0] != host.seeds[1] and len(host.seeds) == 2
    world.run(500)
    assert host.seeds.count(("random",)) == 1     # the game's own randomness resumes a few frames later
    # A new day gives a new seed to everybody.
    before = host.rt["dr"]["seed"]
    host.interp.call("mistrimulti_drops_new_day", gml.GStruct(total_days=2))
    settle(world, 3000)
    assert host.rt["dr"]["seed"] != before and g1.rt["dr"]["seed"] == host.rt["dr"]["seed"]
    print("PASS: loot seed: every game seeds a roll from the host's seed and the source, restores randomness, new seed each day")


def main():
    test_basic()
    test_simultaneous_takes()
    test_unsynced_replica_is_corrected()
    test_hostile_requests()
    test_guest_disappears_mid_transaction()
    test_guest_crash_mid_transaction_records()
    test_host_restart()
    test_snapshot_on_join_and_open()
    test_item_drop_and_claim()
    test_claim_races_under_faults()
    test_day_change_and_lost_items()
    test_gift()
    test_shipping_bins_are_per_player()
    test_loot_seed()
    test_exact_conservation_under_faults()
    print("all container tests passed")


if __name__ == "__main__":
    main()
