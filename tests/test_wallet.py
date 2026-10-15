"""Shared wallet and shipping bins on the event layer, running their real GML.

    python3 tests/test_wallet.py [test_name ...]

MistriMultiWallet.gml and MistriMultiContainers.gml run unmodified in tests/gml_subset.py on top of MistriMultiEvents.gml,
over the simulated helpers and lossy network of tests/event_sim.py. Only the engine is stubbed: the player (gold, the
`player.gold_delta` filter wrapped around Ari.modify_gold exactly where the MMAPI seam sits, set_gold flooring at 0),
chest and shipping-bin nodes, the end-of-day sale, the calendar and a file system.

Properties checked: the pool never goes negative; gold is neither created nor lost (pool - debt equals the start plus the sum
of every change the games actually applied) under loss, duplication, jitter, a guest away for longer than the 10 s expiry
and a host restart; concurrent spending of two players never overdraws the pool; the host's save commit restores the pool;
a day end with several bins credits the proceeds once. This checks the logic and the wiring; it does not replace the game
(docs/SYNC-WALLET.md lists what has to be checked there).
"""
import math
import random
import sys

from event_sim import World
import gml_subset as gml
from test_containers import ContainerNode, make_item, ui_put, ui_take, settle, converged, SIZE

VALUE = {"apple": 10, "bread": 25, "sword": 100, "coin": 1, "potion": 40}
DISK = {}                      # the host's files (they survive a host restart)
START = 500                    # the host's gold in its save
A, B, C = (10, 10), (20, 10), (30, 10)


class WalletNode(ContainerNode):
    extra_files = ContainerNode.extra_files + ("MistriMultiWallet.gml",)
    perk = 1.0                 # bin_value multiplier of this game's player

    def builtins(self):
        out = super().builtins()
        self.changes = []      # what Ari.modify_gold really changed in this game
        self.filtered = []     # (value, returned) of the player.gold_delta filter
        self.hud = []
        self.calendar = gml.GStruct(time=100)
        ari = self.ari_struct
        ari["gold"] = START if self.slot == 0 else 70 + self.slot       # guests start with their own personal gold
        ari["end_of_day_sequence"] = False

        def set_gold(v):
            ari["gold"] = max(math.floor(v), 0)
            self.hud.append(ari["gold"])

        def modify_gold(d):
            before = ari["gold"]
            r = self.interp.call("mistrimulti_wallet_gold_delta", d, gml.GStruct(player=ari))
            self.filtered.append((d, r))
            set_gold(before + (d if r is None else r))
            # What the player really gained or spent (a host's debt repayment is not a spend: it only shrinks the debt).
            dropped = r is not None and r == 0 and d != 0 and ari["end_of_day_sequence"] and self.slot != 0
            self.changes.append(0 if dropped else max(math.floor(before + d), 0) - before)

        ari["get_gold"] = lambda: ari["gold"]
        ari["set_gold"] = set_gold
        ari["modify_gold"] = modify_gold

        def read(path):
            return gml.from_json(__import__("json").loads(DISK[path]))

        def rename(a, b):
            DISK[b] = DISK.pop(a)

        out.update({
            "CALENDAR": self.calendar, "file_exists": lambda p: p in DISK, "try_read_json_file": read,
            "save_text_file": lambda p, t: DISK.__setitem__(p, t), "file_rename": rename,
            "string": lambda v: str(v) if isinstance(v, (int, str)) else gml.gml_string(v),
        })
        return out

    def setup(self):
        super().setup()
        self.rt.update(player_ready=True, character_pending=False, world_path="/w", world_key="world_1", enabled=True)


class Driver:
    def __init__(self, game):
        self.game, self.node = game, game.node
        self.node.interp.call("mistrimulti_containers_register_events")
        self.node.interp.call("mistrimulti_wallet_register_events")

    def frame(self):
        rt = self.node.rt
        return {"epoch": rt["epoch"], "uid": rt["uid"], "world": rt["world_key"], "room": "farm:undefined", "x": 80, "y": 80}

    def tick(self, now):
        self.node.interp.call("mistrimulti_containers_tick")
        self.node.interp.call("mistrimulti_wallet_tick")


def make_world(seed, guests=2, bins=True, **faults):
    DISK.clear()
    world = World(seed, {i: WalletNode for i in range(guests + 1)}, **faults)
    for game in world.games.values():
        game.feature = Driver(game)
        game.node.perk = 1.5 if game.slot == 0 else 1.0
        if bins:
            for xy in (A, B, C):
                game.node.add_chest(xy, {}, bin=True)
    return world


def restart_host(world, load_key=None):
    """The host game restarts from its save (gold START in the save file)."""
    DISK_SAVED_GOLD = world.saved_gold
    game = world.start(0)
    game.feature = Driver(game)
    game.node.perk = 1.5
    for xy in (A, B, C):
        game.node.add_chest(xy, {}, bin=True)
    game.node.ari_struct["gold"] = DISK_SAVED_GOLD
    if load_key is not None:
        game.node.interp.call("mistrimulti_wallet_game_loaded", gml.GStruct(save_path="C:/saves/" + load_key))
    return game


def golds(world):
    return [g.node.ari_struct["gold"] for g in sorted(world.games.values(), key=lambda g: g.slot)]


def pool(world):
    return world.games[0].node.rt["wallet"]["pool"]


def debt(world):
    return world.games[0].node.rt["wallet"]["debt"]


def earn(game, n):
    game.node.ari_struct["modify_gold"](n)


def spend(game, n):
    """A shop: the game only lets the player pay what they see."""
    if game.node.ari_struct["gold"] >= n:
        game.node.ari_struct["modify_gold"](-n)
        return True
    return False


def changes(world):
    return sum(sum(g.node.changes) for g in world.games.values())


def check_conserved(world, start, label):
    """pool - debt == start + every applied change; everyone shows the pool."""
    p, d = pool(world), debt(world)
    assert p >= 0 and d >= 0, (label, p, d)
    assert p - d == start + changes(world), f"{label}: pool {p} debt {d} start {start} changes {changes(world)}"
    assert all(g == p for g in golds(world)), f"{label}: pool {p} but players show {golds(world)}"


def clean(world, label):
    for game in world.games.values():
        assert game.node.call("mistrimulti_events_debug")["errors"] == 0, (label, game.slot, game.warnings[:3])
        assert game.warnings == [], (label, game.slot, game.warnings[:3])


def start_world(seed, **faults):
    world = make_world(seed, **faults)
    world.saved_gold = START
    settle(world, 4000)
    return world


# ---- scenarios -------------------------------------------------------------------------------------------------------

def test_mirror_and_basic():
    world = start_world(1, jitter=20)
    # Everyone shows the host's gold; the guests' own personal gold is not part of the pool.
    assert golds(world) == [START, START, START] and pool(world) == START, golds(world)
    # A guest earns and spends: the HUD moves at once, the host and the other guest follow.
    g1, g2, host = world.games[1], world.games[2], world.games[0]
    earn(g1, 100)
    assert g1.node.ari_struct["gold"] == 600                    # at once, before the host answered
    settle(world, 1500)
    assert golds(world) == [600] * 3 and pool(world) == 600
    assert spend(g2, 250)
    settle(world, 1500)
    assert golds(world) == [350] * 3
    # The host's own changes reach the guests.
    earn(host, 40)
    assert spend(host, 90)
    settle(world, 1500)
    assert golds(world) == [300] * 3 and pool(world) == 300 and debt(world) == 0
    check_conserved(world, START, "basic")
    # Several changes in one frame keep their order and all arrive.
    for n in (5, 7, 11):
        earn(g1, n)
    spend(g1, 2)
    settle(world, 1500)
    assert golds(world) == [321] * 3
    check_conserved(world, START, "burst")
    clean(world, "basic")
    print("PASS: one pool: guests mirror the host, personal gold is not added, changes apply at once and arrive in order")


def test_concurrent_spending():
    world = start_world(2, jitter=30)
    host, g1, g2 = (world.games[i] for i in range(3))
    # Pool 500. Both guests see 500 and each buys for 400 at the same moment.
    assert spend(g1, 400) and spend(g2, 400)
    low = []
    world.run(3000, check=lambda: low.append(pool(world)))
    assert min(low) >= 0
    assert pool(world) == 0 and debt(world) == 300, (pool(world), debt(world))
    assert golds(world) == [0, 0, 0], golds(world)
    # The shortfall is paid from the next income: no gold appears from nowhere.
    earn(host, 1000)
    settle(world, 2000)
    assert pool(world) == 700 and debt(world) == 0 and golds(world) == [700] * 3, (pool(world), debt(world), golds(world))
    # A spend by the host while a guest spends: still exact.
    assert spend(host, 300) and spend(g1, 400)
    settle(world, 2000)
    assert pool(world) == 0 and debt(world) == 0 and golds(world) == [0, 0, 0]
    # The game does not let a guest spend what its mirror does not have.
    assert not spend(g2, 1)
    clean(world, "concurrent")
    print("PASS: concurrent spending never overdraws: the pool stops at 0, the shortfall is a debt that income pays first")


def test_exactly_once_under_faults():
    for seed, faults in ((10, dict(loss=0.12, dup=0.1, jitter=40)), (11, dict(loss=0.2, dup=0.2, jitter=80, latency=30))):
        world = start_world(seed, **faults)
        rng = random.Random(seed)
        # Plenty of gold, so no spend is ever cut short: the final pool must be the exact sum.
        earn(world.games[0], 100000 - START)
        settle(world, 3000)
        for _ in range(250):
            game = world.games[rng.randrange(3)]
            n = rng.randint(1, 60)
            if rng.random() < 0.5:
                earn(game, n)
            else:
                spend(game, n)
            world.run(rng.randint(0, 120))
        settle(world, 20000)
        check_conserved(world, START, f"faults {seed}")
        assert all(not g.node.rt["wallet"]["queue"] and not g.node.rt["wallet"]["pending"] for g in world.games.values() if g.slot)
        clean(world, f"faults {seed}")
    print("PASS: 250 random changes by three players under loss, duplication and jitter: every change applied exactly once")


def test_overdraw_fuzz():
    # Near zero, with races: the pool never goes negative and gold is conserved (pool - debt = start + applied changes).
    world = start_world(20, loss=0.1, dup=0.1, jitter=40)
    rng = random.Random(20)
    low = []
    for _ in range(200):
        game = world.games[rng.randrange(3)]
        n = rng.randint(20, 400)
        (earn if rng.random() < 0.45 else spend)(game, n)
        world.run(rng.randint(0, 60), check=lambda: low.append(pool(world)))
    settle(world, 20000)
    assert min(low) >= 0
    check_conserved(world, START, "overdraw fuzz")
    clean(world, "overdraw fuzz")
    print("PASS: spending races near zero: never negative, nothing created or lost")


def test_guest_away_and_back():
    world = start_world(30, jitter=20)
    host, g1, g2 = (world.games[i] for i in range(3))
    # The guest is cut off for longer than the 10 s expiry and keeps playing; the host moves on meanwhile.
    world.net.partition(0, 1)
    earn(g1, 60)
    assert spend(g1, 25)
    earn(host, 1000)
    world.run(13000)
    assert g1.node.ari_struct["gold"] == START + 35, g1.node.ari_struct["gold"]       # local view while away
    assert pool(world) == START + 1000
    world.net.partition(0, 1, False)
    settle(world, 15000)
    assert pool(world) == START + 1000 + 35, pool(world)       # its changes applied once, in order
    check_conserved(world, START, "away")
    # A guest that misses host events (a gap) asks again.
    world.net.partition(0, 2)
    earn(host, 5)
    world.run(13000)
    world.net.partition(0, 2, False)
    settle(world, 15000)
    check_conserved(world, START, "gap")
    clean(world, "away")
    print("PASS: a guest away longer than the expiry: its changes apply once on return, everything converges")


def test_late_joiner_snapshot():
    world = make_world(40, jitter=20)
    world.saved_gold = START
    world.net.partition(0, 2)           # guest 2 joins late
    world.run(3000)
    earn(world.games[0], 123)
    world.run(2000)
    assert golds(world)[0] == golds(world)[1] == START + 123 and golds(world)[2] != START + 123
    world.net.partition(0, 2, False)
    settle(world, 6000)
    assert golds(world) == [START + 123] * 3, golds(world)
    # A guest that re-enters the world (new session) is told again; its old personal gold never reaches the pool.
    g2 = world.games[2].node
    g2.call("mistrimulti_events_reset")
    g2.ari_struct["gold"] = 9999
    g2.rt["wallet"] = None
    settle(world, 8000)
    assert golds(world) == [START + 123] * 3 and pool(world) == START + 123
    clean(world, "late joiner")
    print("PASS: a joining or re-entering guest is told the pool; its personal gold is replaced, never added")


def test_host_restart():
    world = start_world(50, jitter=20)
    host, g1, g2 = (world.games[i] for i in range(3))
    earn(g1, 200)
    settle(world, 2000)
    # The host saves (day 100) with pool 700; the save file holds the pool as the host's gold.
    host.node.interp.call("mistrimulti_wallet_game_saving", gml.GStruct(save_path="C:/saves/game-1-autosave.sav"))
    assert host.node.ari_struct["gold"] == 700 and any("wallet" in p for p in DISK)
    world.saved_gold = 650               # the save file's own gold field lags: the commit of the pool wins
    spend(g2, 600)
    settle(world, 2000)
    assert pool(world) == 100
    # A request is on its way when the host dies: reported lost, never applied by the new host.
    earn(g1, 50)
    world.net.block(1, 0)
    world.run(80)
    restart_host(world, "game-1-autosave.sav")
    world.net.block(1, 0, False)
    settle(world, 14000)
    assert pool(world) == 700, pool(world)               # the committed pool of the loaded save
    assert golds(world) == [700] * 3, golds(world)       # guests follow the new host, the lost request is not replayed
    # The new host works normally.
    assert spend(g1, 300)
    earn(world.games[0], 5)
    settle(world, 3000)
    assert golds(world) == [405] * 3 and debt(world) == 0
    # A save of another day, or an unreadable commit, is not used; the host's own gold in the save is the pool.
    world.saved_gold = 321
    DISK_BAK = dict(DISK)
    host2 = restart_host(world, "game-1-autosave.sav")
    world.games[0].node.calendar["time"] = 999
    settle(world, 6000)
    assert pool(world) == 321, pool(world)
    DISK.update({k: "garbage{" for k in DISK if "wallet" in k})
    world.saved_gold = 77
    restart_host(world, "game-1-autosave.sav")
    settle(world, 8000)
    assert pool(world) == 77 and golds(world) == [77] * 3
    print("PASS: host restart: the committed pool of the loaded save is restored, lost requests are dropped, stale or damaged "
          "commits fall back to the host's own gold")


def test_hostile_requests():
    world = start_world(60, jitter=10)
    host, g1 = world.games[0], world.games[1]
    for bad in (10 ** 12, -10 ** 12, 1.5, "100", None, [1], {"x": 1}, float(10 ** 8 + 1), -(10 ** 8 + 1)):
        g1.node.call("mistrimulti_event_request", "wallet_tx", {"d": bad})
    g1.node.call("mistrimulti_event_request", "wallet_tx", {})
    g1.node.call("mistrimulti_event_request", "wallet_tx", 5)
    settle(world, 4000)
    assert pool(world) == START and debt(world) == 0
    # The largest legal income and spend still work and the pool is capped.
    g1.node.call("mistrimulti_event_request", "wallet_tx", {"d": 10 ** 8})
    for _ in range(12):
        g1.node.call("mistrimulti_event_request", "wallet_tx", {"d": 10 ** 8})
        world.run(300)
    settle(world, 4000)
    assert pool(world) == 999999999, pool(world)
    # A host message from a guest, or a state event from a guest, is ignored.
    g2 = world.games[2]
    g2.node.call("mistrimulti_event_emit", "wallet_state", {"g": 1, "s": 0})
    settle(world, 3000)
    assert golds(world) == [999999999] * 3, golds(world)
    clean(world, "hostile")
    print("PASS: hostile wallet requests refused (types, ranges, huge or fractional amounts); the pool is capped; forged state ignored")


def test_filter_gating():
    world = start_world(70)
    g1 = world.games[1].node
    ari = g1.ari_struct
    f = lambda v, ctx: g1.interp.call("mistrimulti_wallet_gold_delta", v, ctx)
    other = gml.GStruct(gold=5)
    assert f(10, gml.GStruct(player=other)) is None             # another player's Ari is not ours
    assert f(None, gml.GStruct(player=ari)) is None and f(10, None) is None
    assert f("5", gml.GStruct(player=ari)) is None
    g1.rt["enabled"] = False
    assert f(10, gml.GStruct(player=ari)) is None               # multiplayer off: the game's own delta
    g1.rt["enabled"] = True
    g1.rt["character_pending"] = True
    assert f(10, gml.GStruct(player=ari)) is None               # creating the character: untouched
    g1.rt["character_pending"] = False
    assert f(10.7, gml.GStruct(player=ari)) == 10               # fractions floor like set_gold
    assert f(-10 ** 6, gml.GStruct(player=ari)) == -ari["gold"]  # clamped like set_gold
    print("PASS: the filter ignores other players, bad values, character creation and a disabled mod, and floors like the game")


def test_alone():
    world = make_world(80, guests=0)
    world.saved_gold = START
    settle(world, 2000)
    host = world.games[0]
    earn(host, 25)
    assert spend(host, 100)
    settle(world, 1000)
    assert golds(world) == [425] and pool(world) == 425
    check_conserved(world, START, "alone")
    print("PASS: a host with nobody connected keeps the pool exactly like the game's own gold")


# ---- shipping bins ----------------------------------------------------------------------------------------------------

def end_of_day(game):
    """EodMenu: end_of_day_sequence is set, then sell_shipping_bin_items drains every bin and pays modify_gold once."""
    node = game.node
    ari = node.ari_struct
    ari["end_of_day_status"] = 0
    ari["end_of_day_sequence"] = True
    total = 0
    for chest in node.chest_list:
        if chest["prototype"]["interaction_chest"]["shipping_bin"]:
            for slot in chest["inv"].slots:
                if slot["count"]:
                    total += round(VALUE[slot["item"]["name"]] * slot["count"] * node.perk)
                    slot["remove"](slot["count"])
    ari["modify_gold"](total)                 # called even when nothing was sold
    return total


def wake(game):
    game.node.ari_struct["end_of_day_sequence"] = False
    game.node.ari_struct["end_of_day_status"] = None


def fill_bins(world):
    g1, g2, host = world.games[1], world.games[2], world.games[0]
    g1.node.player.slots[0]["add"](make_item("apple"), 20)
    g2.node.player.slots[0]["add"](make_item("bread"), 4)
    host.node.player.slots[0]["add"](make_item("sword"), 1)
    ui_put(g1, A, 0, "apple", 12)
    ui_put(g2, B, 1, "bread", 4)
    ui_put(host, C, 0, "sword", 1)
    ui_put(g1, C, 2, "apple", 8)
    settle(world, 4000)
    converged(world, "bins filled")


def test_bins_are_shared():
    world = start_world(90, jitter=20)
    host, g1, g2 = (world.games[i] for i in range(3))
    # Items in the bins reach every game (the guests also start with the host's bin contents through the snapshot).
    host.node.inv(A).slots[3]["add"](make_item("coin"), 7)
    fill_bins(world)
    assert g2.node.inv(A).contents()[0] == ("apple", None, 12) and g2.node.inv(C).contents()[0] == ("sword", None, 1)
    # A guest can take its own items back before the day ends.
    ui_take(g1, C, 2, 8)
    settle(world, 3000)
    assert host.node.inv(C).contents() == {0: ("sword", None, 1)}
    converged(world, "taken back")
    clean(world, "bins shared")
    print("PASS: shipping bins are host-owned and synced: any player puts items in or takes them back")


def test_day_end_host_first():
    world = start_world(100, jitter=20)
    fill_bins(world)
    host, g1, g2 = (world.games[i] for i in range(3))
    proceeds = round(10 * 20 * 1.5) + round(25 * 4 * 1.5) + round(100 * 1 * 1.5)          # the host's perks apply
    assert host.node.inv(A).contents()[0][2] == 12
    sold = end_of_day(host)
    assert sold == proceeds
    settle(world, 3000)
    assert pool(world) == START + proceeds, (pool(world), START + proceeds)
    assert golds(world) == [START + proceeds] * 3
    for g in world.games.values():
        for xy in (A, B, C):
            assert world.games[g.slot].node.inv(xy).contents() == {}, (g.slot, xy)
    # The guests' own end of day runs later: their copies are empty, nothing is paid, nothing is sold twice.
    for g in (g1, g2):
        assert end_of_day(g) == 0
    settle(world, 3000)
    assert pool(world) == START + proceeds and golds(world) == [START + proceeds] * 3
    for g in world.games.values():
        wake(g)
    check_conserved(world, START, "day end")
    clean(world, "day end host first")
    print("PASS: day end, host first: the bins are sold once with the host's perks, the proceeds are credited once to the pool")


def test_day_end_guest_first():
    world = start_world(110, jitter=20)
    fill_bins(world)
    host, g1, g2 = (world.games[i] for i in range(3))
    proceeds = round(10 * 20 * 1.5) + round(25 * 4 * 1.5) + round(100 * 1 * 1.5)
    # A guest goes to bed before the host: its game empties its own copy of the bins and "sells" it. Nothing is paid.
    local = end_of_day(g1)
    assert local == 10 * 20 + 25 * 4 + 100 * 1          # what its summary screen shows (its own perks)
    settle(world, 3000)
    assert pool(world) == START and golds(world) == [START] * 3
    # Its copy shows the host's bins again, and the guest cannot take them out by accident.
    assert g1.node.inv(A).contents()[0] == ("apple", None, 12), g1.node.inv(A).contents()
    wake(g1)
    # Then the host ends the day: one sale, one payment.
    assert end_of_day(host) == proceeds
    end_of_day(g2)
    settle(world, 4000)
    assert pool(world) == START + proceeds and golds(world) == [START + proceeds] * 3, (pool(world), golds(world))
    for g in world.games.values():
        for xy in (A, B, C):
            assert g.node.inv(xy).contents() == {}
        wake(g)
    check_conserved(world, START, "guest first")
    clean(world, "day end guest first")
    print("PASS: day end, guest first: the guest's local sale pays nothing, the host's sale pays once, bins end up empty everywhere")


def test_day_end_faults_and_next_day():
    world = start_world(120, loss=0.1, dup=0.1, jitter=40)
    fill_bins(world)
    host, g1, g2 = (world.games[i] for i in range(3))
    proceeds = round(10 * 20 * 1.5) + round(25 * 4 * 1.5) + round(100 * 1 * 1.5)
    end_of_day(host)
    end_of_day(g1)
    end_of_day(g2)
    settle(world, 12000)
    for g in world.games.values():
        wake(g)
    assert pool(world) == START + proceeds and golds(world) == [START + proceeds] * 3
    # The next day works the same, with a guest-only bin and gold earned elsewhere in between.
    g2.node.player.slots[1]["add"](make_item("potion"), 3)
    ui_put(g2, B, 0, "potion", 3)
    earn(g1, 15)
    settle(world, 4000)
    end_of_day(g1)                       # the guest sleeps first again
    end_of_day(host)
    end_of_day(g2)
    settle(world, 12000)
    for g in world.games.values():
        wake(g)
    assert pool(world) == START + proceeds + 15 + round(40 * 3 * 1.5), pool(world)
    assert golds(world) == [pool(world)] * 3
    check_conserved(world, START, "two days")
    clean(world, "day end faults")
    print("PASS: two day ends under packet loss: each sale credited once, bins empty, everyone shows the pool")


def test_empty_bins_and_payments_around_the_end_of_day():
    world = start_world(130, jitter=20)
    host, g1 = world.games[0], world.games[1]
    assert end_of_day(g1) == 0 and end_of_day(host) == 0
    # Only the first gold change of the sequence is the shipping payout; a later one in the same sequence counts.
    earn(g1, 10)
    settle(world, 2000)
    assert pool(world) == START + 10
    for g in world.games.values():
        wake(g)
    earn(g1, 5)                          # outside the sequence a guest's change is always counted, even the first
    settle(world, 2000)
    assert pool(world) == START + 15 and golds(world) == [START + 15] * 3
    check_conserved(world, START, "empty bins")
    print("PASS: an empty day end pays nothing; only the first change of a guest's end-of-day sequence is dropped")


TESTS = [test_mirror_and_basic, test_concurrent_spending, test_exactly_once_under_faults, test_overdraw_fuzz,
         test_guest_away_and_back, test_late_joiner_snapshot, test_host_restart, test_hostile_requests, test_filter_gating,
         test_alone, test_bins_are_shared, test_day_end_host_first, test_day_end_guest_first,
         test_day_end_faults_and_next_day, test_empty_bins_and_payments_around_the_end_of_day]


def main():
    names = sys.argv[1:]
    for test in TESTS:
        if not names or test.__name__ in names:
            test()
    print("all wallet tests passed")


if __name__ == "__main__":
    main()
