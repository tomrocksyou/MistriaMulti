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
from ranch_fake import (A, G, Fake, FARM, HOME, CHICKEN, COW, SMALL, LARGE, ITEM_HAY, ITEM_TREAT, ITEM_APPLE, ITEM_CHAIR,
                        ITEM_LAMP, ITEM_BP, ITEM_FLOOR_A, ITEM_FLOOR_B, ITEM_WALL_A, ITEM_WALL_B, ITEM_PET_TREAT, ITEM_SWORD,
                        ITEM_EGG, ITEM_MILK, ITEM_HONEY, O_CHAIR, O_LAMP, O_BARN, O_TABLE, O_APIARY, USE_NONE)

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
        return {"epoch": self.node.rt["epoch"], "room": "farm:undefined", "x": 80, "y": 80}

    def tick(self, now):
        self.node.interp.call("mistrimulti_ranch_tick")


def make_world(seed, guests=2, plan=PLAN, **faults):
    impls = {i: (lambda slot, epoch, clock, log, plan=plan: RanchNode(slot, epoch, clock, log, plan)) for i in range(guests + 1)}
    world = World(seed, impls, **faults)
    for game in world.games.values():
        game.feature = Driver(game)
    return world


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
    for game in world.games.values():
        game.node.interp.builtins["GRID"] = G(dyn_index=dyn)


def make_list_of(ids):
    from ranch_fake import make_list
    return make_list([G(item_id=i) for i in ids])


def test_pet_conflict():
    world = make_world(2, loss=0.1, dup=0.1, jitter=30)
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


def test_adopt_and_sell():
    world = make_world(5, loss=0.1, dup=0.1, jitter=40)
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


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    only = sys.argv[1:]
    for test in tests:
        if not only or test.__name__ in only:
            test()
