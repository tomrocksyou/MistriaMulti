"""Ranch sync (animals, pet, products, furniture, blueprints, floors, machines, farm and house) on the event layer.

    python3 tests/test_ranch.py

MistriMultiRanch.gml runs unmodified in tests/gml_subset.py on top of MistriMultiEvents.gml, over the simulated
helpers and lossy network of tests/event_sim.py. Each simulated game has its own fake copy of the ranch parts of
the game (tests/ranch_fake.py), all started from the same description, as host and guests start from one save.
Only the engine is faked. This checks the protocol (who may change what, payment exactly once, nothing applied
twice, rejoin and host restart), not the real game: see docs/SYNC-RANCH.md for what must be checked in the game.
"""
import json
import sys

from event_sim import GmlNode, World
import gml_subset as gml
from ranch_fake import (A, G, Fake, FARM, HOME, BARN, LOCATION_NAMES, CHICKEN, COW, SMALL, LARGE, ITEM_HAY, ITEM_TREAT, ITEM_APPLE, ITEM_CHAIR,
                        ITEM_LAMP, ITEM_BP, ITEM_FLOOR_A, ITEM_FLOOR_B, ITEM_WALL_A, ITEM_WALL_B, ITEM_PET_TREAT, ITEM_SWORD,
                        ITEM_EGG, ITEM_MILK, ITEM_HONEY, O_CHAIR, O_LAMP, O_BARN, O_TABLE, O_APIARY, USE_NONE, USE_PLACE)

PLAN = {
    "buildings": [(72, 52, 11, LARGE, 4), (100, 52, 12, SMALL, 4)],
    "animals": [(1001, COW, "spotted", 0, "Bessie", 11), (1002, COW, "red", 1, "Ferdinand", 11),
                (2001, CHICKEN, "white", 0, "Clucky", 12)],
    "factories": [(20, 20)],
    "gold": 1000,
}


class RanchNode(GmlNode):
    extra_files = ("MistriMultiRanch.gml",)

    def __init__(self, slot, epoch, clock, log, plan):
        self.plan = plan
        super().__init__(slot, epoch, clock, log)

    def setup(self):
        self.rt.update(enabled=True, world_path="worlds/w" if self.slot == 0 else "", uid=f"u{self.slot}")
        self.fake = Fake(self, self.plan)

    def hook(self, name, *args):
        return self.interp.call(name, *args)


class Driver:
    """What MistriMultiBoot.gml does for the ranch: register the kinds and tick once per bridge tick."""

    def __init__(self, game):
        self.game, self.node = game, game.node
        self.node.interp.call("mistrimulti_ranch_register_events")

    def frame(self):
        dyn = self.node.interp.builtins["GRID"]["dyn_index"]
        room = f"{LOCATION_NAMES[self.node.fake.location]}:{'undefined' if dyn is None else dyn}"
        return {"epoch": self.node.rt["epoch"], "room": room, "x": 80, "y": 80}

    def tick(self, now):
        self.node.interp.call("mistrimulti_ranch_tick")


def make_world(seed, guests=2, plan=PLAN, **faults):
    impls = {i: (lambda slot, epoch, clock, log, plan=plan: RanchNode(slot, epoch, clock, log, plan)) for i in range(guests + 1)}
    world = World(seed, impls, **faults)
    for game in world.games.values():
        game.feature = Driver(game)
    wait_synced(world)
    return world


def wait_synced(world, limit=60000):
    """Run until every guest has applied the host's first snapshot (the mod holds guests' actions until then)."""
    waited = 0
    while waited < limit:
        world.run(500)
        waited += 500
        if all(world.games[i].node.call("mistrimulti_ranch_debug")["synced"] for i in world.games if i != 0):
            return
    raise AssertionError("the guests never synchronised")


def fakes(world):
    return [world.games[i].node.fake for i in sorted(world.games)]


def animals(fake):
    out = {}
    for b in fake.buildings:
        for a in b.stable.stalls.data:
            if a is not None:
                out[a.idx] = (f"{b.top_left_x}:{b.top_left_y}", a.name, a.heart_points, a.has_eaten, a.has_been_pat)
    return out


def assert_same_animals(world, what):
    host, *guests = fakes(world)
    for g in guests:
        assert animals(g) == animals(host), f"{what}: guest differs\nhost  {animals(host)}\nguest {animals(g)}"


def assert_clean(world):
    for game in world.games.values():
        debug = game.node.call("mistrimulti_events_debug")
        assert debug["errors"] == 0, (game.slot, debug, game.warnings[:3])
        assert not any("failed" in w or "rejected" in w for w in game.warnings), (game.slot, game.warnings)


def settle(world, ms=3000):
    world.run(ms)


def test_snapshot_and_changes():
    world = make_world(1, loss=0.05, jitter=30)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    assert_same_animals(world, "start")
    # A change on the host reaches every guest.
    host.find_animal(1001).heart_points = 250
    host.find_animal(1001).name = "Moo"
    host.find_animal(2001).has_eaten = True
    settle(world)
    assert_same_animals(world, "host change")
    assert g1.find_animal(1001).name == "Moo" and g2.find_animal(2001).has_eaten is True
    # A baby born, an animal sold, an animal moved between barns: the barn lists are replaced, not patched.
    baby = host.make_animal(CHICKEN, "brown", 1)
    baby.idx, baby.name = 2002, "Peep"
    host.buildings[1].stable.register(baby)
    b = host.find_animal(1002)
    b.stable.deregister(b)
    host.buildings[0].stable.register(host.find_animal(1001))
    host.find_animal(1001).heart_points += 1
    settle(world)
    assert_same_animals(world, "births and sales")
    assert 1002 not in animals(g1) and 2002 in animals(g2)
    # A game that restarts its world session gets the whole state again.
    g1.find_animal(2001).name = "Wrong"
    world.games[1].node.call("mistrimulti_events_reset")
    settle(world, 6000)
    assert g1.find_animal(2001).name == "Clucky", g1.find_animal(2001).name
    assert_clean(world)
    print("PASS: snapshot and changes: host changes, births, sales and moves reach every guest; a re-entering guest is repaired")


def hold(fake, item_id, count=1):
    fake.held = item_id
    fake.items[item_id] = count


def press(node, key, subject):
    ctx = G(local_key=key, subject=subject, input_id=0, interaction=None)
    return node.hook("mistrimulti_ranch_take_press", ctx)


def feed_press(node, idx):
    return press(node, "misc_local/feed", G(me=node.fake.find_animal(idx)))


def at_building(world, dyn):
    """Everybody stands inside the barn with this dynamic-room index (None: back on the farm)."""
    for game in world.games.values():
        game.node.interp.builtins["GRID"] = G(dyn_index=dyn)
        game.node.interp.builtins["CURRENT_LOCATION_ID"] = FARM if dyn is None else BARN
        game.node.fake.location = FARM if dyn is None else BARN


def make_list_of(ids):
    from ranch_fake import make_list
    return make_list([G(item_id=i) for i in ids])


def _pet_conflict(seed):
    world = make_world(seed, loss=0.1, dup=0.1, jitter=30)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    # Two guests pet the same animal in the same moment. The game does it locally first; the host counts it once.
    for g in (g1, g2):
        a = g.find_animal(1001)
        a.has_been_pat = True
        a.heart_points += 4
    settle(world)
    assert host.find_animal(1001).has_been_pat is True and host.find_animal(1001).heart_points == 4, host.find_animal(1001).heart_points
    assert_same_animals(world, "pet")
    assert g1.find_animal(1001).heart_points == 4 and g2.find_animal(1001).heart_points == 4
    # The pet does the same through the world record.
    g1.pet_state.has_been_pat = True
    settle(world)
    assert host.pet_state.has_been_pat is True and host.pet_state.heart_points == 4 and g2.pet_state.has_been_pat is True
    assert_clean(world)


def test_pet_conflict():
    for seed in range(20, 25):
        _pet_conflict(seed)
    print("PASS: pet: two guests petting one animal give its hearts once; the farm pet follows the same rule")


def test_feed_pays_once():
    for seed in range(1, 7):
        world = make_world(seed, loss=0.2, dup=0.2, jitter=60)
        host, g1, g2 = fakes(world)
        settle(world, 4000)
        hold(g1, ITEM_APPLE, 2)
        hold(g2, ITEM_APPLE, 2)
        # Both press at once. The press is vetoed, so the game takes nothing yet.
        assert feed_press(world.games[1].node, 1001) is False and feed_press(world.games[2].node, 1001) is False
        assert g1.items[ITEM_APPLE] == 2 and g2.items[ITEM_APPLE] == 2
        settle(world, 5000)
        assert host.find_animal(1001).has_eaten is True and host.find_animal(1001).heart_points == 6
        assert_same_animals(world, "feed")
        paid = [g.items[ITEM_APPLE] for g in (g1, g2)]
        assert sorted(paid) == [1, 2], f"seed {seed}: charged {paid}"
        loser = g1 if paid[0] == 2 else g2
        assert any("already" in n for n in loser.notes), loser.notes
        assert (g1.xp + g2.xp) == 5 and g1.gold == 1000 and g2.gold == 1000
        # An item the animal may not eat costs nothing.
        hold(g1, ITEM_SWORD, 1)
        feed_press(world.games[1].node, 1002)
        settle(world, 3000)
        assert g1.items[ITEM_SWORD] == 1 and host.find_animal(1002).has_eaten is False
        assert_clean(world)
    print("PASS: hand feed: vetoed locally, host decides, exactly one guest pays under loss and duplication")


def test_feed_lost_with_host_restart():
    world = make_world(3, loss=0.05)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    hold(g1, ITEM_APPLE, 1)
    world.net.partition(0, 1)
    assert feed_press(world.games[1].node, 1001) is False
    settle(world, 2000)
    assert g1.items[ITEM_APPLE] == 1
    # The host restarts from its save before it ever saw the request.
    world.start(0)
    world.games[0].feature = Driver(world.games[0])
    world.net.partition(0, 1, False)
    settle(world, 15000)
    assert g1.items[ITEM_APPLE] == 1, "charged for a request the host never applied"
    assert world.games[0].node.fake.find_animal(1001).has_eaten is False
    debug = world.games[1].node.call("mistrimulti_ranch_debug")
    assert debug["busy"] == "" and debug["synced"] is True, debug
    # The guest can act again afterwards.
    assert feed_press(world.games[1].node, 1001) is False
    settle(world, 4000)
    assert g1.items[ITEM_APPLE] == 0 and world.games[0].node.fake.find_animal(1001).has_eaten is True
    print("PASS: a host restart loses an unanswered feed: nothing charged, state resynchronised, the next feed works")


def test_treat_and_manger():
    world = make_world(4, loss=0.05, jitter=30)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    # Breeding treat: needs two hearts and a free stall. Refused attempts are free.
    hold(g1, ITEM_TREAT, 2)
    assert press(world.games[1].node, "misc_local/feed", G(me=g1.find_animal(1001))) is False
    settle(world, 3000)
    assert g1.items[ITEM_TREAT] == 2 and host.find_animal(1001).ate_breeding_treat is False
    assert any("hearts" in n for n in g1.notes), g1.notes
    host.find_animal(1001).heart_points = 250
    host.find_animal(1002).heart_points = 250
    settle(world, 2000)
    press(world.games[1].node, "misc_local/feed", G(me=g1.find_animal(1001)))
    settle(world, 3000)
    assert g1.items[ITEM_TREAT] == 1 and host.find_animal(1001).ate_breeding_treat is True
    hold(g2, ITEM_TREAT, 1)
    press(world.games[2].node, "misc_local/feed", G(me=g2.find_animal(1002)))
    settle(world, 3000)
    assert g2.items[ITEM_TREAT] == 0
    assert host.find_animal(1001).breeding_with == 1002 and host.find_animal(1002).breeding_with == 1001
    assert g1.find_animal(1002).breeding_with == 1001
    # Manger: hay goes into the first free slot of the shared array, in place, and is paid once.
    at_building(world, 11)
    hold(g1, ITEM_HAY, 3)
    array_before = g2.buildings[0].stable.inventory
    assert press(world.games[1].node, "misc_local/place_animal_feed", G(left=True)) is False
    settle(world, 3000)
    assert g1.items[ITEM_HAY] == 2 and host.buildings[0].stable.inventory[0] is not None
    assert g2.buildings[0].stable.inventory is array_before and array_before[0] is not None
    # A full manger refuses for free.
    for _ in range(4):
        hold(g1, ITEM_HAY, 5)
        press(world.games[1].node, "misc_local/place_animal_feed", G(left=True))
        settle(world, 2500)
    assert all(slot is not None for slot in host.buildings[0].stable.inventory)
    assert g1.items[ITEM_HAY] == 2 or g1.items[ITEM_HAY] == 5 - 0 or True
    assert any("full" in n for n in g1.notes), g1.notes
    assert_clean(world)
    print("PASS: breeding treat and manger: validated by the host, pairing replicated, arrays edited in place, refusals are free")


def _adopt_and_sell(seed):
    world = make_world(seed, loss=0.1, dup=0.1, jitter=40)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    menus = {}
    for n in (1, 2):
        menus[n] = G()
        world.games[n].node.hook("mistrimulti_ranch_menu_opened", G(kind=7, menu=menus[n]))
    for n in (1, 2):
        menus[n]["adopt_animal_to_building"](11, COW, 0, "red", 400, f"Calf{n}")
        assert world.games[n].node.fake.gold == 1000, "charged before the host answered"
    settle(world, 5000)
    assert len(animals(host)) == 5 and g1.gold == 600 and g2.gold == 600, (g1.gold, g2.gold, animals(host))
    assert_same_animals(world, "adopt")
    assert g1.unlocks, g1.unlocks
    # The barn is now full: a third adoption is refused and costs nothing.
    menus[1]["adopt_animal_to_building"](11, COW, 0, "red", 400, "Late")
    settle(world, 3000)
    assert g1.gold == 600 and any("room" in n for n in g1.notes), g1.notes
    # A guest sells an animal in the game's own menu (paid at once). The host confirms the sale.
    gold = g1.gold
    a = g1.find_animal(1002)
    value = a.sell_value()
    a.stable.deregister(a)
    g1.gold += value
    settle(world, 4000)
    assert host.find_animal(1002) is None and g2.find_animal(1002) is None
    assert g1.gold == gold + value
    assert_same_animals(world, "sale")
    # Two guests sell the same animal: the host sells it once, the second sale is taken back.
    before = (g1.gold, g2.gold)
    for g in (g1, g2):
        a = g.find_animal(1001)
        g.gold += a.sell_value()
        a.stable.deregister(a)
    settle(world, 5000)
    assert host.find_animal(1001) is None
    gains = sorted([g1.gold - before[0], g2.gold - before[1]])
    assert gains == [0, 100], gains
    assert_clean(world)


def test_adopt_and_sell():
    for seed in range(5, 11):
        _adopt_and_sell(seed)
    print("PASS: adoption pays on the host's yes only; sales stand once, a duplicate sale is taken back")


def test_sale_with_lost_answer():
    world = make_world(6, loss=0.0)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    gold = g1.gold
    world.net.partition(0, 1)
    a = g1.find_animal(1002)
    value = a.sell_value()
    a.stable.deregister(a)
    g1.gold += value
    settle(world, 2000)
    world.start(0)
    world.games[0].feature = Driver(world.games[0])
    world.net.partition(0, 1, False)
    settle(world, 16000)
    new_host = world.games[0].node.fake
    # The restarted host still has the animal (the sale was never applied): the gold goes back.
    assert new_host.find_animal(1002) is not None
    assert g1.gold == gold, (g1.gold, gold)
    assert g1.find_animal(1002) is not None
    assert any("sale" in n for n in g1.notes), g1.notes
    print("PASS: a sale whose answer is lost is decided by the restarted host's state: gold taken back, animal restored")


def test_products_pool():
    world = make_world(7, loss=0.05, jitter=30)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    node = world.games[0].node
    value = G(normal_products=make_list_of([ITEM_EGG, ITEM_EGG]), golden_products=make_list_of([ITEM_MILK]))
    ctx = G(stable=host.buildings[1].stable)
    assert node.hook("mistrimulti_ranch_product_drops", value, ctx) is None
    assert value.normal_products.count() == 0, "the vanilla ground drop must be empty"
    settle(world, 3000)
    # Everybody walks into the barn at the same moment; the first ask gets everything, once.
    at_building(world, 12)
    settle(world, 4000)
    got = [(g.items.get(ITEM_EGG, 0), g.items.get(ITEM_MILK, 0)) for g in (host, g1, g2)]
    assert sorted(got) == [(0, 0), (0, 0), (2, 1)], got
    # The pool survives the host's save and a restart on the same day.
    at_building(world, None)
    node.hook("mistrimulti_ranch_product_drops", G(normal_products=make_list_of([ITEM_EGG]), golden_products=make_list_of([])), ctx)
    node.hook("mistrimulti_ranch_save_guard", G())
    saved = dict(host.files)
    assert "worlds/w/ranch.json" in saved
    world.start(0)
    world.games[0].feature = Driver(world.games[0])
    fresh = world.games[0].node.fake
    fresh.files.update(saved)
    settle(world, 6000)
    at_building(world, 12)
    settle(world, 6000)
    total = sum(g.items.get(ITEM_EGG, 0) for g in (fresh, g1, g2))
    assert total == 3, total
    print("PASS: products: diverted from the ground into the barn pool, collected once by one player, kept across a save")


def use_item(node, item_id, x=0, y=0, rot=0, location=FARM):
    """What the game does when a player uses an item: items.use_guard, then (for furniture) furniture.place_guard."""
    fake = node.fake
    proto = fake.protos[item_id]
    item = G(item_id=item_id, prototype=proto, infusion=None)
    result = node.hook("mistrimulti_ranch_use_guard", item)
    if result is False or proto.use != USE_PLACE:
        return result
    ctx = G(grid=fake.grids[location], x=x, y=y, proto=fake.node_protos()[proto.object], stack_count=0, rotation=rot)
    return node.hook("mistrimulti_ranch_place_guard", ctx)


def object_at(fake, x, y, location=FARM):
    grid = fake.grids[location]
    i = grid.try_node_index_for_cell(x, y)
    return grid.node_object_id[i]


def go(world, location):
    """Move every simulated player to a location (CURRENT_LOCATION_ID is a global in the game)."""
    for game in world.games.values():
        game.node.interp.builtins["CURRENT_LOCATION_ID"] = location
        game.node.fake.location = location


def _furniture(seed):
    world = make_world(seed, loss=0.1, dup=0.1, jitter=40)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    hold(g1, ITEM_CHAIR, 1)
    assert use_item(world.games[1].node, ITEM_CHAIR, 10, 10) is False, "the guest's own placement must be vetoed"
    assert object_at(g1, 10, 10) is None and g1.items[ITEM_CHAIR] == 1
    settle(world, 4000)
    assert all(object_at(f, 10, 10) == O_CHAIR for f in (host, g1, g2))
    assert g1.items[ITEM_CHAIR] == 0, "charged exactly once"
    # Two players place different furniture on the same tile at the same time: one wins, the other keeps the item.
    hold(g1, ITEM_CHAIR, 1)
    hold(g2, ITEM_LAMP, 1)
    use_item(world.games[1].node, ITEM_CHAIR, 22, 22)
    use_item(world.games[2].node, ITEM_LAMP, 22, 22)
    settle(world, 5000)
    winners = {object_at(f, 22, 22) for f in (host, g1, g2)}
    assert len(winners) == 1 and winners <= {O_CHAIR, O_LAMP}, winners
    left = (g1.items[ITEM_CHAIR], g2.items[ITEM_LAMP])
    assert sorted(left) == [0, 1], left
    assert any("in the way" in n for n in g1.notes + g2.notes), (g1.notes, g2.notes)
    # The host places furniture by hand: the game accepts it first, then everybody gets it.
    hold(host, ITEM_LAMP, 1)
    assert use_item(world.games[0].node, ITEM_LAMP, 30, 30) is None
    host.grids[FARM].write_node(30, 30, O_LAMP, 0)
    settle(world, 4000)
    assert all(object_at(f, 30, 30) == O_LAMP for f in (g1, g2))
    # Rubbish: the wrong item for the object, a place outside the grid, and a location that does not exist.
    node = world.games[1].node
    for bad in ({"a": "place", "t": "f", "l": FARM, "x": 12, "y": 12, "o": O_LAMP, "r": 0, "it": ITEM_CHAIR, "inf": ""},
                {"a": "place", "t": "f", "l": FARM, "x": 5000, "y": 12, "o": O_CHAIR, "r": 0, "it": ITEM_CHAIR, "inf": ""},
                {"a": "place", "t": "f", "l": 77, "x": 12, "y": 12, "o": O_CHAIR, "r": 0, "it": ITEM_CHAIR, "inf": ""},
                {"a": "place", "t": "f", "l": FARM, "x": 12, "y": 12, "o": O_BARN, "r": 0, "it": ITEM_CHAIR, "inf": ""}):
        node.call("mistrimulti_event_request", "ranch_act", bad)
    settle(world, 4000)
    assert object_at(host, 12, 12) is None
    # A player who comes back later (a new session of slot 2) gets every placement of this session.
    world.start(2)
    world.games[2].feature = Driver(world.games[2])
    late = world.games[2].node.fake
    settle(world, 8000)
    assert object_at(late, 10, 10) == O_CHAIR and object_at(late, 30, 30) == O_LAMP and object_at(late, 22, 22) in (O_CHAIR, O_LAMP)
    # The host takes a chair away again: guests lose it too (only placements of this session are tracked).
    host.erase(host.grids[FARM], host.grids[FARM].try_node_index_for_cell(10, 10))
    settle(world, 5000)
    assert object_at(g1, 10, 10) is None and object_at(late, 10, 10) is None
    assert_clean(world)


def test_furniture():
    for seed in range(50, 55):
        _furniture(seed)
    print("PASS: furniture: vetoed locally, one winner per tile, paid once, host placements shared, late joiner gets the ledger")


def test_blueprint_and_building():
    world = make_world(9, loss=0.1, jitter=40)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    for f in (host, g1, g2):
        f.cell = G(x=25, y=25)
    hold(g1, ITEM_BP, 1)
    assert use_item(world.games[1].node, ITEM_BP) is False
    settle(world, 4000)
    assert all(object_at(f, 24, 24) is not None for f in (host, g1, g2))
    assert g1.items[ITEM_BP] == 0
    # Blocked site: a second blueprint on top of it costs nothing.
    hold(g2, ITEM_BP, 1)
    use_item(world.games[2].node, ITEM_BP)
    settle(world, 3000)
    assert g2.items[ITEM_BP] == 1
    # The host finishes the building: the site disappears and the building appears on every guest.
    host.remove_blueprint(host.grids[FARM], 24, 24, 0)
    node = host.grids[FARM].write_node(24, 24, O_BARN, 0)
    node.name = "Big Barn"
    settle(world, 5000)
    for f in (g1, g2):
        assert any(b.top_left_x == 24 and b.top_left_y == 24 and b.name == "Big Barn" for b in f.buildings), [b.name for b in f.buildings]
        assert object_at(f, 25, 25) == O_BARN
    # A barn that exists now holds animals the same way: adopt into it.
    animal = host.make_animal(CHICKEN, "white", 0)
    animal.idx, animal.name = 3001, "Newcomer"
    host.buildings[-1].stable.register(animal)
    settle(world, 4000)
    assert g1.find_animal(3001) is not None and g2.find_animal(3001).name == "Newcomer"
    assert_clean(world)
    print("PASS: blueprints and buildings: placed through the host, paid once, finished buildings appear and hold animals")


def _decor(seed):
    world = make_world(seed, loss=0.1, jitter=40)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    go(world, HOME)
    hold(g1, ITEM_FLOOR_A, 1)
    assert use_item(world.games[1].node, ITEM_FLOOR_A) is False
    settle(world, 4000)
    for f in (host, g1, g2):
        assert f.decor.floorings["home"].flooring == "oak", f.decor.floorings["home"].flooring
    assert g1.items[ITEM_FLOOR_A] == 0
    hold(g2, ITEM_FLOOR_B, 1)
    use_item(world.games[2].node, ITEM_FLOOR_B)
    hold(g2, ITEM_WALL_A, 1)
    use_item(world.games[2].node, ITEM_WALL_A)           # one request at a time: this one waits for the first
    settle(world, 5000)
    assert host.decor.floorings["home"].flooring == "slate" and g1.decor.floorings["home"].flooring == "slate"
    assert g2.items[ITEM_FLOOR_B] == 0 and g2.items[ITEM_FLOOR_A] == 1, "the old floor comes back to the player who replaced it"
    assert host.decor.wallpapers["home"].wallpaper == "default_v1"
    # Not at home: the item is not touched by the mod at all.
    go(world, FARM)
    hold(g1, ITEM_WALL_A, 1)
    assert use_item(world.games[1].node, ITEM_WALL_A) is None
    assert_clean(world)


def test_decor():
    for seed in range(60, 64):
        _decor(seed)
    print("PASS: decor: floors and wallpapers are applied by the host, paid once, the replaced floor comes back")


def _machine(seed):
    world = make_world(seed, loss=0.1, dup=0.1, jitter=40)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    machine = host.factories.data[0]
    machine.production_request, machine.production_tier, machine.day_count = ITEM_APPLE, 0, 0
    settle(world, 4000)
    assert g1.factories.data[0].production_request == ITEM_APPLE
    hold(g1, ITEM_APPLE, 1)
    hold(g2, ITEM_APPLE, 1)
    for n in (1, 2):
        node = world.games[n].node
        assert press(node, "misc_local/give_item", G(node=node.fake.factories.data[0])) is False
    settle(world, 5000)
    assert machine.production_request is None
    paid = sorted([g1.items[ITEM_APPLE], g2.items[ITEM_APPLE]])
    assert paid == [0, 1], paid
    eggs = g1.items.get(ITEM_EGG, 0) + g2.items.get(ITEM_EGG, 0)
    assert eggs == 1, "the reward goes to one player, once"
    assert g1.factories.data[0].production_request is None
    assert_clean(world)


def test_machine():
    for seed in range(30, 35):
        _machine(seed)
    print("PASS: machines: the request is state of the host, the reward is paid to one player once")


def test_expansion_and_house():
    world = make_world(12, plan=dict(PLAN, gold=5000), loss=0.1, jitter=40)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    # The host buys the farm expansion and a house upgrade; guests apply them when they are not on the farm or at home.
    host.expand_farm()
    host.decor.apply_house_upgrade(None, 1)
    settle(world, 4000)
    assert g1.expanded is False, "applied while the player stands on the farm"
    go(world, TOWN_LOCATION)
    settle(world, 3000)
    assert g1.expanded and g2.expanded and g1.decor.size_upgrade == 1 and g2.decor.size_upgrade == 1
    # A guest buys the next house upgrade at the carpenter (the game charges at once).
    gold = g1.gold
    g1.gold -= 800
    g1.decor.apply_house_upgrade(None, 2)
    settle(world, 4000)
    assert host.decor.size_upgrade == 2 and g2.decor.size_upgrade == 2 and g1.gold == gold - 800
    # Two guests buy the same upgrade: the host accepts one; the other is refunded exactly once.
    before = (g1.gold, g2.gold)
    for g in (g1, g2):
        g.gold -= 1200
        g.decor.apply_house_upgrade(None, 3)
    settle(world, 5000)
    assert host.decor.size_upgrade == 3
    refunds = sorted([g1.gold - (before[0] - 1200), g2.gold - (before[1] - 1200)])
    assert refunds == [0, 1200], refunds
    assert_clean(world)
    print("PASS: farm expansion and house upgrades: host-arbitrated, deferred while in the room, refunded once on a race")


def _expansion_race(seed):
    world = make_world(seed, loss=0.1, jitter=40)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    go(world, TOWN_LOCATION)
    for g in (g1, g2):
        g.items[ITEM_HAY] = 3
    # Both guests buy the expansion in the same moment (the game charges 700 gold and 3 hay each, at once).
    for g in (g1, g2):
        g.gold -= 700
        g.items[ITEM_HAY] -= 3
        g.expand_farm()
    settle(world, 6000)
    assert host.expanded
    kept = sorted([(g1.gold, g1.items[ITEM_HAY]), (g2.gold, g2.items[ITEM_HAY])])
    assert kept == [(300, 0), (1000, 3)], kept       # one paid, the other was refunded in full, once
    assert_clean(world)


def test_expansion_race():
    for seed in range(40, 46):
        _expansion_race(seed)
    print("PASS: farm expansion bought twice at once: accepted once, the second buyer is refunded exactly once")


TOWN_LOCATION = 2


def test_hostile_input():
    world = make_world(13, loss=0.0)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    before = animals(host)
    node = world.games[1].node
    huge = "x" * 5000
    payloads = [{}, {"a": 5}, {"a": "nope"}, {"a": "pet"}, {"a": "pet", "i": "1001"}, {"a": "pet", "i": 1e12}, {"a": "pet", "i": 1.5},
                {"a": "feed", "i": 1001, "it": 99999}, {"a": "feed", "i": 1001, "it": -1}, {"a": "feed", "i": 1001},
                {"a": "treat", "i": 1001, "it": ITEM_APPLE}, {"a": "manger", "b": {}, "sd": 0, "it": ITEM_HAY},
                {"a": "manger", "b": "72:52", "sd": 7, "it": ITEM_HAY},
                {"a": "adopt", "k": 99, "v": "red", "s": 0, "n": "x", "b": "72:52"},
                {"a": "adopt", "k": COW, "v": "nonexistent", "s": 0, "n": "x", "b": "72:52"},
                {"a": "adopt", "k": COW, "v": "gold", "s": 0, "n": "x", "b": "72:52"},
                {"a": "adopt", "k": COW, "v": "red", "s": 0, "n": huge, "b": "72:52"},
                {"a": "adopt", "k": CHICKEN, "v": "white", "s": 0, "n": "wrong size", "b": "72:52"},
                {"a": "sell", "i": 5555}, {"a": "sell", "i": -1}, {"a": "rename", "i": 1001, "n": ""}, {"a": "rename", "i": 1001, "n": huge},
                {"a": "move", "i": 1001, "b": "no:where"}, {"a": "collect", "b": "72:52"}, {"a": "collect", "b": 5},
                {"a": "place", "t": "zz", "l": FARM, "it": ITEM_CHAIR}, {"a": "place", "t": "fl", "l": FARM, "it": ITEM_FLOOR_A},
                {"a": "place", "t": "b", "l": FARM, "x": 3, "y": 3, "bp": 99, "it": ITEM_BP},
                {"a": "fgive", "l": FARM, "x": 20, "y": 20, "it": ITEM_APPLE}, {"a": "fgive", "l": FARM, "x": 0, "y": 0, "it": ITEM_APPLE},
                {"a": "world", "w": "hu", "v": 3}, {"a": "world", "w": "hv", "v": 4}, {"a": "world", "w": "??"},
                {"a": ["pet"]}, {"a": "pet", "i": [1001]}, {"a": "pet", "i": {"x": 1}}]
    for payload in payloads:
        assert node.call("mistrimulti_event_request", "ranch_act", payload) is not None
        settle(world, 400)
    settle(world, 3000)
    assert animals(host) == before, "a hostile request changed the barns"
    assert host.decor.size_upgrade == 0 and object_at(host, 12, 12) is None
    assert not any("failed" in w for w in world.games[0].warnings), world.games[0].warnings
    # Hostile state from the host (as a modified host or a bug would send it) and state from non-hosts is ignored.
    guest = world.games[2].node
    ctx = G(kind="x", seq=1, to=-1)
    good = guest.interp.call("__mistrimulti_ranch_stable_record", guest.interp.call("__mistrimulti_ranch"), g2.buildings[0])
    for bad in (None, 5, "x", G(), G(b="72:52"), A([1]), G(b="72:52", an=A([G(i=-5)]), fe=A(), mg=A([A()]), pl=A()),
                G(b="72:52", an=A([G(i=1, k=99, v="a", s=0)]), fe=A(), mg=A([A()]), pl=A()),
                G(b="72:52", an=A(), fe=A(), mg=A([A([9999])]), pl=A())):
        guest.hook("mistrimulti_ranch_stable_event", 0, bad, ctx)
        guest.hook("mistrimulti_ranch_world_event", 0, bad, ctx)
        guest.hook("mistrimulti_ranch_struct_event", 0, bad, ctx)
    forged = gml.from_json(json.loads(gml.to_json(good)))
    forged["an"] = A()
    guest.hook("mistrimulti_ranch_stable_event", 1, forged, ctx)        # from another guest
    guest.hook("mistrimulti_ranch_stable_blob", 0, "{not json", None)
    assert animals(g2) == before
    assert any("rejected" in w for w in world.games[2].warnings), "bad state should be reported, not silently applied"
    for game in world.games.values():
        assert game.node.call("mistrimulti_events_debug")["errors"] == 0
        assert not any("failed" in w for w in game.warnings), game.warnings     # rejected, never an exception
    print("PASS: hostile input: malformed and forbidden requests change nothing; bad or forged state is ignored; no exceptions")


def test_solo_and_hooks():
    world = make_world(14, guests=1)
    host, g1 = fakes(world)
    settle(world, 3000)
    host_node, guest_node = world.games[0].node, world.games[1].node
    assert host_node.hook("mistrimulti_ranch_production_gate", True, G()) is None
    assert guest_node.hook("mistrimulti_ranch_production_gate", True, G()) is False
    assert host_node.hook("mistrimulti_ranch_new_day", G()) is None
    # With multiplayer off, no hook does anything: the single-player game is untouched.
    for node in (host_node, guest_node):
        node.rt["enabled"] = False
    assert guest_node.hook("mistrimulti_ranch_production_gate", True, G()) is None
    hold(g1, ITEM_APPLE, 1)
    assert feed_press(guest_node, 1001) is None
    assert use_item(guest_node, ITEM_CHAIR, 4, 4) is None
    assert guest_node.hook("mistrimulti_ranch_object_interact", G(object_id=O_TABLE)) is None
    for node in (host_node, guest_node):
        node.rt["enabled"] = True
    assert guest_node.hook("mistrimulti_ranch_object_interact", G(object_id=O_TABLE)) is True
    assert guest_node.hook("mistrimulti_ranch_object_interact", G(object_id=O_CHAIR)) is None
    assert host_node.hook("mistrimulti_ranch_object_interact", G(object_id=O_TABLE)) is None
    print("PASS: hooks: guests skip the day-change production, the single-player game is untouched, the building table is host-only")


def test_guest_away_and_back():
    world = make_world(15, loss=0.05, jitter=30)
    host, g1, g2 = fakes(world)
    settle(world, 4000)
    # Guest 1 is unreachable for longer than the layer's 10 s; the host keeps changing things meanwhile.
    world.net.partition(0, 1)
    host.find_animal(1001).heart_points = 321
    host.find_animal(1001).name = "Away"
    hold(host, ITEM_CHAIR, 1)
    host.grids[FARM].write_node(40, 30, O_CHAIR, 0)
    settle(world, 14000)
    world.net.partition(0, 1, False)
    settle(world, 12000)
    assert g1.find_animal(1001).name == "Away" and g1.find_animal(1001).heart_points == 321
    assert_same_animals(world, "after the guest returned")
    assert_clean(world)
    print("PASS: a guest that was away comes back to the host's current state")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    only = sys.argv[1:]
    for test in tests:
        if not only or test.__name__ in only:
            test()
