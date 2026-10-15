"""Shared town rank (renown) on the event layer, running its real GML.

    python3 tests/test_renown.py [test_name ...]

MistriMultiRenown.gml (and the renown capture of MistriMultiProgress.gml) run unmodified in tests/gml_subset.py on top of
MistriMultiEvents.gml, over the simulated helpers and lossy network of tests/event_sim.py. Only the engine is stubbed: the player
(renown, the pending entry list drained at the day rollover through modify_renown with the `player.renown_delta` filter wrapped
around it exactly where the MMAPI seam sits, set_renown raising levels and giving one reward per level crossed, the rank every
10 levels), the renown entries, the story/other quest categories, the calendar and a file system.

Properties checked: every gain of any player reaches the host's total once and every game; every game gets each level's reward and
each rank-up exactly once (never twice, never skipped) and the level-up popups of the end-of-day menu; the shipping gold and the
story quests are counted once (from the host); packet loss, duplication, a guest away beyond the 10 s expiry, a host restart with
its save commit, and a guest that re-enters the world. This checks the logic and the wiring; it does not replace the game
(docs/SYNC-RENOWN.md lists what has to be checked there).
"""
import json
import math
import random
import sys

from event_sim import World
import gml_subset as gml
from test_event_features import FeatureNode

DISK = {}                       # the host's files (they survive a host restart)
PER_LEVEL = 100                 # renown per level in this stub
MAX_LEVEL = 100
MAX_RENOWN = PER_LEVEL * MAX_LEVEL
RANK = 10                       # levels per rank
GOLD, MUSEUM, QUEST = 0, 1, 2
QUEST_VALUE = 30


def level_of(renown):
    return min(int(renown) // PER_LEVEL, MAX_LEVEL)


def entry_value(e):
    if e["type"] == GOLD:
        return math.ceil(e["gold"] * 0.01)
    if e["type"] == MUSEUM:
        return 5
    return QUEST_VALUE


def gold_for(renown):
    """Gold of a shipping sale that is worth `renown` (the game: ceil(0.01 * gold))."""
    return renown * 100


def make_list(items=()):
    arr = list(items)
    lst = gml.GStruct()
    lst["items"] = arr
    lst["count"] = lambda: len(arr)
    lst["get"] = lambda i: arr[int(i)]
    lst["push"] = lambda v: arr.append(v)
    lst["remove"] = lambda i: arr.pop(int(i))
    return lst


class RenownNode(FeatureNode):
    extra_files = FeatureNode.extra_files + ("MistriMultiRenown.gml",)

    def builtins(self):
        out = super().builtins()
        self.rewards = []           # level numbers whose reward this game gave
        self.rank_ups = []          # rank reached
        self.requested = []         # (value, returned) of the filter
        self.counted = 0            # renown the games' rules say this player's drains add to the world
        self.calendar = gml.GStruct(time=100)
        self.pending = make_list()
        ari = gml.GStruct(name="test", renown=0, pending_renown_entries=self.pending)
        self.ari_struct = ari

        def set_renown(val):
            old = level_of(ari["renown"])
            ari["renown"] = max(0, min(math.floor(val), MAX_RENOWN))
            new = level_of(ari["renown"])
            if new <= old:
                return
            if new // RANK != old // RANK:
                self.rank_ups.append(new // RANK)
            for level in range(old + 1, new + 1):
                self.rewards.append(level)

        def modify_renown(d):
            r = self.interp.call("mistrimulti_renown_delta", d, gml.GStruct(player=ari))
            self.requested.append((d, r))
            set_renown(ari["renown"] + (d if r is None else r))

        def on_new_day():
            """Ari.on_new_day: List.drain keeps the entry in the list while the callback runs."""
            items = self.pending["items"]
            while items:
                e = items[0]
                modify_renown(entry_value(e))
                items.pop(0)

        ari["set_renown"], ari["modify_renown"], ari["on_new_day"] = set_renown, modify_renown, on_new_day

        def read(path):
            try:
                return gml.from_json(json.loads(DISK[path]))
            except ValueError:
                return None                # the game's try_read_json_file returns undefined for a damaged file

        def rename(a, b):
            DISK[b] = DISK.pop(a)

        factory = gml.GStruct(Gold=lambda g: gml.GStruct(type=GOLD, gold=g),
                              MuseumDonation=lambda i: gml.GStruct(type=MUSEUM, item_id=i),
                              Quest=lambda q: gml.GStruct(type=QUEST, quest_key=q))
        out.update({
            "ARI": ari, "CALENDAR": self.calendar, "file_exists": lambda p: p in DISK, "try_read_json_file": read,
            "save_text_file": lambda p, t: DISK.__setitem__(p, t), "file_rename": rename,
            "string": lambda v: str(v) if isinstance(v, (int, str)) else gml.gml_string(v),
            "RenownEntry": factory, "RenownEntryType": gml.GStruct(Gold=GOLD, MuseumDonation=MUSEUM, Quest=QUEST),
            "renown_entry_value": entry_value, "renown_level_total_cost": lambda lv: PER_LEVEL * lv,
            "MAX_RENOWN_LEVEL": MAX_LEVEL, "QuestCategory": gml.GStruct(Story=0),
            "QUESTS": gml.GStruct(get=lambda name: gml.GStruct(category=0 if str(name).startswith("story") else 1)),
            "serialize_renown_entry": lambda e: gml.GStruct(dict(e)),
        })
        return out

    def setup(self):
        super().setup()
        self.rt.update(player_ready=True, character_pending=False, world_path="/w", world_key="world_1", enabled=True)


class Driver:
    def __init__(self, game):
        self.game, self.node = game, game.node
        self.node.interp.call("mistrimulti_renown_register_events")

    def frame(self):
        rt = self.node.rt
        return {"epoch": rt["epoch"], "uid": rt["uid"], "world": rt["world_key"], "room": "farm:undefined", "x": 80, "y": 80}

    def tick(self, now):
        self.node.interp.call("mistrimulti_renown_tick")


def make_world(seed, guests=2, **faults):
    DISK.clear()
    world = World(seed, {i: RenownNode for i in range(guests + 1)}, **faults)
    for game in world.games.values():
        game.feature = Driver(game)
    return world


def start_world(seed, **faults):
    world = make_world(seed, **faults)
    world.run(4000)
    return world


def restart_host(world, renown, load_key=None):
    """The host game restarts from its save (the renown the host had applied then)."""
    game = world.start(0)
    game.feature = Driver(game)
    game.node.ari_struct["renown"] = renown
    if load_key is not None:
        game.node.interp.call("mistrimulti_renown_game_loaded", gml.GStruct(save_path="C:/saves/" + load_key))
    return game


# ---- what the players do ---------------------------------------------------------------------------------------------

def ari(game):
    return game.node.ari_struct


def sale(game, renown):
    """The end-of-day sale: the game files a gold entry (`sell_shipping_bin_items`)."""
    game.node.pending["push"](gml.GStruct(type=GOLD, gold=gold_for(renown)))


def donate(game, n=1):
    for i in range(n):
        game.node.pending["push"](gml.GStruct(type=MUSEUM, item_id=i))


def quest(game, name):
    game.node.pending["push"](gml.GStruct(type=QUEST, quest_key=name))


def counts(slot, entry):
    """Which drained entries add to the world's renown (docs/SYNC-RENOWN.md), written down independently of the GML."""
    if entry["type"] == GOLD or (entry["type"] == QUEST and str(entry["quest_key"]).startswith("story")):
        return slot == 0
    return True


def roll(game):
    """The game's day rollover for one player. Returns the expected contribution to the world's renown."""
    items = game.node.pending["items"]
    add = sum(entry_value(e) for e in items if not e.get("mm_carrier") and counts(game.slot, e))
    ari(game)["on_new_day"]()
    return add


def popup_levels(game):
    """What the end-of-day menu would play: the levels between renown and renown + every pending entry."""
    total = ari(game)["renown"] + sum(entry_value(e) for e in game.node.pending["items"])
    return level_of(min(total, MAX_RENOWN)) - level_of(ari(game)["renown"])


def pool(world):
    return world.games[0].node.rt["renown"]["pool"]


def renowns(world):
    return [ari(g)["renown"] for g in sorted(world.games.values(), key=lambda g: g.slot)]


def carriers(game):
    return [e for e in game.node.pending["items"] if e.get("mm_carrier")]


def settle(world, ms=3000):
    world.run(ms)


def rollover_everyone(world, expected=None, ms=3000):
    """Everybody goes through a day rollover, the news spreads, and everybody goes through the next one."""
    total = 0
    for _ in range(2):
        for g in sorted(world.games.values(), key=lambda g: g.slot):
            total += roll(g)
        settle(world, ms)
    return total


def check_rewards_once(world, label):
    for g in world.games.values():
        want = list(range(1, level_of(ari(g)["renown"]) + 1))
        got = sorted(g.node.rewards)
        assert got == want, f"{label}: game {g.slot} rewards {got} for renown {ari(g)['renown']}"
        assert len(g.node.rewards) == len(set(g.node.rewards)), (label, g.slot, g.node.rewards)


def check_same(world, expected_pool, label):
    assert pool(world) == expected_pool, f"{label}: pool {pool(world)} != {expected_pool}"
    assert renowns(world) == [expected_pool] * len(world.games), f"{label}: pool {pool(world)} but players are at {renowns(world)}"
    assert all(not carriers(g) for g in world.games.values()), label
    check_rewards_once(world, label)


def clean(world, label):
    for game in world.games.values():
        assert game.node.call("mistrimulti_events_debug")["errors"] == 0, (label, game.slot, game.warnings[:3])
        assert game.warnings == [], (label, game.slot, game.warnings[:3])


# ---- scenarios -------------------------------------------------------------------------------------------------------

def test_shipping_rank_up_reaches_every_player():
    """The field report: the host's shipping payout ranked the host up; the guests got nothing."""
    world = start_world(1, jitter=20)
    host, g1, g2 = (world.games[i] for i in range(3))
    sale(host, 1500)                                 # 15 levels: crosses the first rank
    assert popup_levels(host) == 15
    roll(host)                                       # the host sleeps: the entry is drained
    assert host.node.rank_ups == [1] and host.node.rewards == list(range(1, 16))
    settle(world)
    # The guests have not slept yet: the gain is in their pending list, so their own end-of-day menu plays the level-ups.
    for g in (g1, g2):
        assert ari(g)["renown"] == 0 and len(carriers(g)) == 1 and popup_levels(g) == 15, (g.slot, carriers(g))
        assert g.node.rewards == [] and g.node.rank_ups == []
    roll(g1)
    roll(g2)
    for g in (g1, g2):
        assert g.node.rewards == list(range(1, 16)) and g.node.rank_ups == [1], (g.slot, g.node.rewards, g.node.rank_ups)
    settle(world)
    check_same(world, 1500, "shipping")
    # Nothing is given again, however often the days pass or the ticks run.
    rollover_everyone(world)
    check_same(world, 1500, "shipping again")
    for g in world.games.values():
        assert g.node.rank_ups == [1]
        assert [r for r in g.node.requested if r[1] == 0] == []
    clean(world, "shipping")
    print("PASS: the host's shipping payout ranks everyone up: popups, rewards and the rank-up once per player")


def test_guest_gain_reaches_host_and_other_guest():
    world = start_world(2, jitter=20)
    host, g1, g2 = (world.games[i] for i in range(3))
    donate(g1, 100)                                  # museum donations: 500 renown
    quest(g1, "fetch_1")
    roll(g1)
    assert ari(g1)["renown"] == 500 + QUEST_VALUE and g1.node.rank_ups == []        # applied at once, as the game does
    settle(world)
    assert pool(world) == 500 + QUEST_VALUE
    for g in (host, g2):
        assert len(carriers(g)) == 1 and ari(g)["renown"] == 0
    rollover_everyone(world)
    check_same(world, 500 + QUEST_VALUE, "guest gain")
    assert all(g.node.rewards == list(range(1, 6)) for g in world.games.values())
    clean(world, "guest gain")
    print("PASS: a guest's museum and quest gains go to the host's total and to the other players, once")


def test_everyone_gains_at_once():
    for seed, faults in ((3, dict(jitter=40)), (4, dict(loss=0.15, dup=0.15, jitter=60, latency=25))):
        world = start_world(seed, **faults)
        host, g1, g2 = (world.games[i] for i in range(3))
        sale(host, 400)
        donate(g1, 20)
        quest(g1, "fetch_1")
        donate(g2, 12)
        quest(g2, "fetch_2")
        quest(g2, "fetch_3")
        total = 0
        for g in (g1, g2, host):                      # all three sleep in the same moment
            total += roll(g)
        total_expected = 400 + 100 + QUEST_VALUE + 60 + 2 * QUEST_VALUE
        assert total == total_expected
        settle(world, 8000)
        total += rollover_everyone(world, ms=8000)
        check_same(world, total_expected, f"all at once {seed}")
        clean(world, f"all at once {seed}")
    print("PASS: three players gaining in the same moment: the total is the exact sum, every game ends on it")


def test_rank_reached_by_one_player():
    world = start_world(5, jitter=20)
    host, g1, g2 = (world.games[i] for i in range(3))
    donate(host, 189)                                # 945 renown: level 9, one short of the rank
    roll(host)
    rollover_everyone(world)
    check_same(world, 945, "before")
    assert all(g.node.rank_ups == [] and level_of(ari(g)["renown"]) == 9 for g in world.games.values())
    donate(g2, 13)                                   # +65 -> 1010: level 10, the rank
    roll(g2)
    assert g2.node.rank_ups == [1] and g2.node.rewards[-1] == 10
    settle(world)
    rollover_everyone(world)
    check_same(world, 1010, "after")
    for g in world.games.values():
        assert g.node.rank_ups == [1] and g.node.rewards.count(10) == 1, (g.slot, g.node.rank_ups, g.node.rewards)
    # Two players cross the next rank in one night: each game crosses it once.
    donate(host, 100)
    donate(g1, 100)
    donate(g2, 1)
    rollover_everyone(world)
    check_same(world, 1010 + 1005, "two cross")
    assert all(g.node.rank_ups == [1, 2] for g in world.games.values())
    clean(world, "rank")
    print("PASS: a rank reached by one player gives every player the reward and the rank-up exactly once")


def test_each_kind_is_counted_once():
    world = start_world(6, jitter=20)
    host, g1, g2 = (world.games[i] for i in range(3))
    # The guests' copies of the shipping sale are not counted (the host sells the shared bins); neither is a guest's copy of a
    # story quest (the host's game pays it too); a guest's own quest and museum donation are.
    sale(g1, 700)
    sale(g2, 700)
    quest(g1, "story_a")
    quest(g2, "story_a")
    quest(g1, "fetch_1")
    donate(g2, 2)
    roll(g1)
    roll(g2)
    assert ari(g1)["renown"] == QUEST_VALUE and ari(g2)["renown"] == 10
    settle(world)
    assert pool(world) == QUEST_VALUE + 10
    # The host's own sale and its mirrored story quest count once each.
    sale(host, 100)
    quest(host, "story_a")
    rollover_everyone(world)
    check_same(world, QUEST_VALUE + 10 + 100 + QUEST_VALUE, "kinds")
    clean(world, "kinds")
    print("PASS: shipping and story renown are counted once (from the host); a guest's own quests and donations count")


def test_exactly_once_under_faults():
    for seed, faults in ((10, dict(loss=0.12, dup=0.1, jitter=40)), (11, dict(loss=0.2, dup=0.2, jitter=80, latency=30))):
        world = start_world(seed, **faults)
        rng = random.Random(seed)
        expected = 0
        for _ in range(120):
            game = world.games[rng.randrange(3)]
            what = rng.random()
            if what < 0.25:
                sale(game, rng.randint(1, 60))
            elif what < 0.55:
                donate(game, rng.randint(1, 4))
            elif what < 0.7:
                quest(game, rng.choice(["story_a", "story_b", "fetch_1", "fetch_2"]))
            elif what < 0.9:
                expected += roll(game)
            world.run(rng.randint(0, 400))
        settle(world, 20000)
        expected += rollover_everyone(world, ms=15000)
        check_same(world, min(expected, MAX_RENOWN), f"faults {seed}")
        for g in world.games.values():
            assert not g.node.rt["renown"]["queue"] and not g.node.rt["renown"]["pending"], g.slot
        clean(world, f"faults {seed}")
    print("PASS: 120 random gains and rollovers by three players under loss, duplication and jitter: one total, rewards once")


def test_guest_away_and_back():
    world = start_world(30, jitter=20)
    host, g1, g2 = (world.games[i] for i in range(3))
    world.net.partition(0, 1)                        # the guest is cut off for longer than the 10 s expiry
    donate(g1, 10)
    roll(g1)                                         # it keeps playing alone: its own gain is applied locally
    sale(host, 300)
    roll(host)
    world.run(13000)
    assert ari(g1)["renown"] == 50 and pool(world) == 300
    world.net.partition(0, 1, False)
    settle(world, 15000)
    assert pool(world) == 350, pool(world)           # its gain applied once, in order
    rollover_everyone(world, ms=4000)
    check_same(world, 350, "away")
    # A guest that misses host events (a gap) is told again.
    world.net.partition(0, 2)
    donate(host, 40)
    roll(host)
    world.run(13000)
    world.net.partition(0, 2, False)
    settle(world, 15000)
    rollover_everyone(world, ms=4000)
    check_same(world, 550, "gap")
    clean(world, "away")
    print("PASS: a guest away longer than the expiry: its gains apply once on return and it catches up with the others")


def test_joining_and_rejoining():
    world = start_world(40, jitter=20)
    host, g1, g2 = (world.games[i] for i in range(3))
    sale(host, 500)
    roll(host)
    rollover_everyone(world)
    check_same(world, 500, "base")

    def reenter(game, renown, pending=()):
        """The guest's game starts a new world session; its record restored `renown` (and its queued gains)."""
        node = game.node
        node.call("mistrimulti_events_reset")
        node.rt["renown"] = None
        ari(game)["renown"] = renown
        node.pending["items"][:] = list(pending)
        node.rewards.clear()
        node.rank_ups.clear()

    # A brand-new character (no renown of its own) starts at the farm's rank, without the rewards of levels it never reached.
    reenter(g2, 0)
    settle(world, 5000)
    assert ari(g2)["renown"] == 500 and g2.node.rewards == [] and not carriers(g2)
    # A returning player who was behind catches up: the missing levels are paid once, at its next day.
    reenter(g1, 200)
    settle(world, 5000)
    assert ari(g1)["renown"] == 200 and len(carriers(g1)) == 1 and popup_levels(g1) == 3
    roll(g1)
    assert g1.node.rewards == [3, 4, 5] and ari(g1)["renown"] == 500
    # A guest that is ahead (an old personal total) keeps its level, is not given back rewards and the pool is untouched.
    reenter(g1, 900)
    settle(world, 5000)
    assert ari(g1)["renown"] == 900 and not carriers(g1) and pool(world) == 500 and g1.node.rewards == []
    donate(host, 100)                                # +500 -> pool 1000: it is passed, its gap is the difference only
    rollover_everyone(world)
    assert pool(world) == 1000 and ari(g1)["renown"] == 1000 and g1.node.rewards == [10]
    # Its old queued shipping entry from the personal days is not counted for the world.
    reenter(g2, 1000, [gml.GStruct(type=GOLD, gold=gold_for(50)), gml.GStruct(type=MUSEUM, item_id=1)])
    settle(world, 5000)
    roll(g2)
    settle(world)
    assert pool(world) == 1005, pool(world)
    clean(world, "rejoin")
    print("PASS: joining or re-entering: new characters start at the pool, those behind catch up once, those ahead are untouched")


def test_host_restart():
    world = start_world(50, jitter=20)
    host, g1, g2 = (world.games[i] for i in range(3))
    sale(host, 200)
    roll(host)
    donate(g1, 40)                                   # 200 more
    roll(g1)
    settle(world)
    assert pool(world) == 400 and ari(host)["renown"] == 200 and len(carriers(host)) == 1
    # The host saves (day 100): the carrier leaves the list, the commit keeps the pool.
    host.node.interp.call("mistrimulti_renown_game_saving", gml.GStruct(save_path="C:/saves/game-1-autosave.sav"))
    assert carriers(host) == [] and any("renown" in p for p in DISK)
    settle(world, 1000)
    assert len(carriers(host)) == 1                  # derived again
    # Everything below happens after the save and is lost with the reload.
    donate(g2, 10)
    roll(g2)
    settle(world)
    assert pool(world) == 450
    # The host reloads that save: its game holds the 200 it had applied, the commit holds the 400.
    restart_host(world, 200, "game-1-autosave.sav")
    settle(world, 14000)
    assert pool(world) == 400, pool(world)
    host = world.games[0]
    assert len(carriers(host)) == 1
    roll(host)
    rollover_everyone(world)
    assert pool(world) == 400 and ari(host)["renown"] == 400
    assert host.node.rewards == [3, 4], host.node.rewards          # the levels it had not reached
    # Guests that were already ahead of the reloaded total (g2's 50 had reached g1 before the reload) keep what they have.
    assert ari(g2)["renown"] == 450 and ari(g1)["renown"] == 450
    # A save of another day, or an unreadable commit, is not used; the host's own renown is the pool.
    restart_host(world, 100, "game-1-autosave.sav")
    world.games[0].node.calendar["time"] = 999
    settle(world, 6000)
    assert pool(world) == 100, pool(world)
    DISK.update({k: "garbage{" for k in DISK if "renown" in k})
    restart_host(world, 90, "game-1-autosave.sav")
    settle(world, 6000)
    assert pool(world) == 90
    # The previous generation is used when the newest commit is damaged.
    world.games[0].node.interp.call("mistrimulti_renown_game_saving", gml.GStruct(save_path="C:/saves/x.sav"))
    world.games[0].node.interp.call("mistrimulti_renown_game_saving", gml.GStruct(save_path="C:/saves/x.sav"))
    path = "/w/commits/x_sav.renown.json"
    assert path in DISK and path + ".bak" in DISK
    DISK[path] = "garbage{"
    restart_host(world, 5, "x.sav")
    settle(world, 6000)
    assert pool(world) == 90, pool(world)
    print("PASS: host restart: the committed total restores what the save lacks; stale or damaged commits fall back safely")


def test_a_lost_request_is_dropped():
    world = start_world(55, jitter=20)
    host, g1 = world.games[0], world.games[1]
    donate(g1, 10)
    world.net.block(1, 0)
    roll(g1)
    world.run(80)
    restart_host(world, 0)
    world.net.block(1, 0, False)
    settle(world, 14000)
    # At most once across a host restart: the new host cannot know whether the old one had applied it.
    assert pool(world) == 0 and ari(g1)["renown"] == 50
    donate(world.games[0], 3)
    rollover_everyone(world)
    assert pool(world) == 15 and ari(g1)["renown"] == 50      # the guest stays ahead until the total passes it
    clean(world, "lost")
    print("PASS: a request lost with a host restart is dropped, never replayed; the guest keeps what it applied")


def test_carrier_does_not_wait_for_the_answer():
    world = start_world(65, jitter=20)
    host, g1 = world.games[0], world.games[1]
    world.net.block(1, 0)                            # the guest's request cannot reach the host (the host's news can)
    donate(g1, 100)                                  # +500 applied in the guest's game, unanswered
    roll(g1)
    sale(host, 300)
    roll(host)
    settle(world, 3000)
    assert pool(world) == 300 and ari(g1)["renown"] == 500
    assert [entry_value(e) for e in carriers(g1)] == [300]       # its own unanswered 500 counts as already applied
    world.net.block(1, 0, False)
    settle(world, 5000)
    rollover_everyone(world)
    check_same(world, 800, "unanswered")
    clean(world, "unanswered")
    print("PASS: a guest's own unanswered gain counts as applied: the others' gain still reaches it at once, nothing twice")


def test_hostile_requests_and_state():
    world = start_world(60, jitter=10)
    host, g1, g2 = (world.games[i] for i in range(3))
    # One at a time (a huge gain and a huge loss would cancel through the clamp and hide each other).
    for bad in (10 ** 12, -10 ** 12, 1.5, "100", None, [1], {"x": 1}, float(10 ** 7 + 1), -(10 ** 7 + 1), True):
        g1.node.call("mistrimulti_event_request", "renown_tx", {"d": bad})
        world.run(500)
        assert pool(world) == 0, bad
    g1.node.call("mistrimulti_event_request", "renown_tx", {})
    g1.node.call("mistrimulti_event_request", "renown_tx", 5)
    settle(world, 4000)
    assert pool(world) == 0
    # The largest legal gain still works and the total is capped at what the game can hold.
    for _ in range(3):
        g1.node.call("mistrimulti_event_request", "renown_tx", {"d": 10 ** 7})
        world.run(300)
    settle(world, 4000)
    assert pool(world) == MAX_RENOWN, pool(world)
    # A negative request cannot take it below zero.
    for _ in range(3):
        g1.node.call("mistrimulti_event_request", "renown_tx", {"d": -10 ** 7})
        world.run(300)
    settle(world, 4000)
    assert pool(world) == 0
    # A state event from a guest, or with a forged total, is ignored.
    g2.node.call("mistrimulti_event_emit", "renown_state", {"p": 777})
    host.node.call("mistrimulti_event_emit", "renown_state", {"p": 10 ** 9})
    host.node.call("mistrimulti_event_emit", "renown_state", {"p": 1.5})
    host.node.call("mistrimulti_event_emit", "renown_state", {"p": "7"})
    settle(world, 3000)
    assert pool(world) == 0 and g1.node.rt["renown"]["known"] == 0 and g2.node.rt["renown"]["known"] == 0
    # (The carriers the guests got while the total was high stay: a game is never taken back.)
    assert renowns(world) == [0, 0, 0] and all(sum(entry_value(e) for e in carriers(g)) <= MAX_RENOWN for g in (g1, g2))
    clean(world, "hostile")
    print("PASS: hostile renown requests and state events are refused; the total stays within the game's range")


def test_filter_gating():
    world = start_world(70)
    g1 = world.games[1]
    node, a = g1.node, ari(g1)
    f = lambda v, ctx: node.interp.call("mistrimulti_renown_delta", v, ctx)
    sent = lambda: len(node.rt["renown"]["queue"]) + len(node.rt["renown"]["pending"])
    own = gml.GStruct(player=a)
    node.pending["items"][:] = []
    base = sent()
    assert f(5, gml.GStruct(player=gml.GStruct(renown=1))) is None and sent() == base       # another player's Ari
    assert f(None, own) is None and f("5", own) is None and f(5, None) is None
    node.rt["enabled"] = False
    assert f(5, own) is None and sent() == base                                              # multiplayer off
    node.rt["enabled"] = True
    node.rt["character_pending"] = True
    assert f(5, own) is None and sent() == base                                              # creating the character
    node.rt["character_pending"] = False
    # A carrier is already part of the total: never sent. The guest's copy of shipping and story is dropped.
    carrier = gml.GStruct(type=GOLD, gold=gold_for(7), mm_carrier=True)
    node.pending["items"][:] = [carrier]
    assert f(7, own) is None and sent() == base
    node.pending["items"][:] = [gml.GStruct(type=GOLD, gold=gold_for(7))]
    assert f(7, own) == 0 and sent() == base
    node.pending["items"][:] = [gml.GStruct(type=QUEST, quest_key="story_x")]
    assert f(QUEST_VALUE, own) == 0 and sent() == base
    # An own gain, a call that is not a drain, and an entry that does not match the value are sent.
    node.pending["items"][:] = [gml.GStruct(type=MUSEUM, item_id=1)]
    assert f(5, own) is None
    node.pending["items"][:] = []
    assert f(3, own) is None
    node.pending["items"][:] = [gml.GStruct(type=GOLD, gold=gold_for(7))]
    assert f(9, own) is None                                                                  # another mod changed the value
    node.pending["items"][:] = []
    assert f(0, own) is None
    settle(world, 1000)
    assert pool(world) == 17, pool(world)
    # The host counts everything it drains except carriers.
    h = world.games[0].node
    hf = lambda v, ctx: h.interp.call("mistrimulti_renown_delta", v, ctx)
    h.pending["items"][:] = [gml.GStruct(type=GOLD, gold=gold_for(7), mm_carrier=True)]
    assert hf(7, gml.GStruct(player=ari(world.games[0]))) is None and pool(world) == 17
    h.pending["items"][:] = [gml.GStruct(type=GOLD, gold=gold_for(7))]
    assert hf(7, gml.GStruct(player=ari(world.games[0]))) is None and pool(world) == 24
    print("PASS: the filter ignores other players, bad values, character creation and a disabled mod; carriers are never counted")


def test_carriers_are_derived_state():
    world = start_world(80, jitter=20)
    host, g1, g2 = (world.games[i] for i in range(3))
    donate(g1, 30)
    roll(g1)
    world.run(300)
    for _ in range(50):                              # many ticks never pile carriers up
        world.run(100)
        assert len(carriers(host)) <= 1 and len(carriers(g2)) <= 1
    assert len(carriers(host)) == 1 and entry_value(carriers(host)[0]) == 150
    # The record of the player (MistriMultiProgress.gml) keeps its own queued gains and never a carrier.
    g2.node.pending["push"](gml.GStruct(type=MUSEUM, item_id=3))
    out = g2.node.interp.call("mistrimulti_progress_capture_renown")
    assert [e["type"] for e in out] == [MUSEUM] and not any(e.get("mm_carrier") for e in out), out
    # A save never holds them (the game would load them back as ordinary shipping gold), the next tick makes them again.
    for g in (host, g2):
        g.node.interp.call("mistrimulti_renown_game_saving", gml.GStruct(save_path="C:/saves/s.sav"))
        assert carriers(g) == [], g.slot
    world.run(500)
    assert len(carriers(host)) == 1 and len(carriers(g2)) == 1
    # Another gain while a carrier waits adds only the difference.
    sale(host, 50)
    roll(host)
    settle(world)
    assert [entry_value(e) for e in carriers(g2)] == [200]            # one carrier per game, grown by the later gain
    rollover_everyone(world)
    check_same(world, 205, "derived")                                 # (+5: the donation queued in g2's record above)
    clean(world, "derived")
    print("PASS: carriers are derived from the total: one per gap, never saved, never in the player's record")


def test_alone():
    world = make_world(90, guests=0)
    world.run(2000)
    host = world.games[0]
    sale(host, 1200)
    donate(host, 2)
    roll(host)
    world.run(1000)
    assert ari(host)["renown"] == 1210 and pool(world) == 1210 and not carriers(host)
    assert host.node.rewards == list(range(1, 13)) and host.node.rank_ups == [1]
    host.node.interp.call("mistrimulti_renown_game_saving", gml.GStruct(save_path="C:/saves/a.sav"))
    check_rewards_once(world, "alone")
    print("PASS: a host with nobody connected behaves exactly like the game's own renown")


TESTS = [test_shipping_rank_up_reaches_every_player, test_guest_gain_reaches_host_and_other_guest, test_everyone_gains_at_once,
         test_rank_reached_by_one_player, test_each_kind_is_counted_once, test_exactly_once_under_faults,
         test_guest_away_and_back, test_joining_and_rejoining, test_host_restart, test_a_lost_request_is_dropped,
         test_carrier_does_not_wait_for_the_answer, test_hostile_requests_and_state, test_filter_gating, test_carriers_are_derived_state, test_alone]


def main():
    names = sys.argv[1:]
    for test in TESTS:
        if not names or test.__name__ in names:
            test()
    print("all renown tests passed")


if __name__ == "__main__":
    main()
