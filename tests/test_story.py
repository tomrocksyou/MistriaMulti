"""Story, villagers, cutscenes and festivals (MistriMultiStory.gml) on the event layer, running the real GML.

    python3 tests/test_story.py [test_name ...]

MistriMultiStory.gml runs unmodified in tests/gml_subset.py on top of MistriMultiEvents.gml, over the simulated helpers and
lossy network of tests/event_sim.py. Each simulated game has its own fake copy of the story parts of the game
(tests/story_fake.py: quest log, cutscene history, world facts, villagers), all started from one saved description, as host and
guests start from one save. Only the engine is faked. This checks the protocol (who may change what, nothing advanced twice,
rejoin, host restart, late join, scenes and villagers) and not the real game: docs/SYNC-STORY.md lists what must be checked there.
"""
import copy
import json
import sys

from event_sim import GmlNode, World
import gml_subset as gml
import story_fake as sf
from story_fake import (A, G, Npc, Fake, PRELUDE, default_save, WORLD_SCENES, FARM, HOME, TOWN, BEACH, NPC_COUNT,
                        ACT_READ, ACT_EAT, ROOMMATE)

FIXED_FACTS = ["caldarus_seridia_town", "seridia_is_human", "caldarus_is_human", "caldarus_home"]
WORLD_FACTS = FIXED_FACTS + ["bridge_fixed", "market_open"]
SECOND = 1000


class StoryNode(GmlNode):
    extra_files = ("MistriMultiStory.gml",)
    prelude = (PRELUDE,)

    def __init__(self, slot, epoch, clock, log, saves):
        self.saves = saves
        super().__init__(slot, epoch, clock, log)

    def builtins(self):
        self.fake = Fake(copy.deepcopy(self.saves.get(self.slot) or default_save()))
        out = self.fake.builtins()
        out["CURRENT_LOCATION_ID"] = self.fake.room
        return out

    def setup(self):
        self.rt.update(enabled=True, uid="local:%032x" % self.slot, romance_spouse=gml.GStruct(), romance_spouse_view=gml.GStruct())
        g = self.interp.globals
        g["story_enabled"] = True
        g["cancel_festivals"] = False
        for name, value in zip(("secret_narrows", "secret_beach", "secret_tower"), self.fake.counters):
            g[name] = value

    def counters(self):
        g = self.interp.globals
        return [g["secret_narrows"], g["secret_beach"], g["secret_tower"]]

    def set_counter(self, index, value):
        self.interp.globals[("secret_narrows", "secret_beach", "secret_tower")[index]] = value

    def set_room(self, room):
        self.fake.room = room
        self.interp.builtins["CURRENT_LOCATION_ID"] = room

    def debug(self):
        return self.interp.call("mistrimulti_story_debug")


class Driver:
    """What MistriMultiBoot.gml does for the story: register the kinds and tick once per bridge tick."""

    def __init__(self, game):
        self.game, self.node = game, game.node
        self.node.interp.call("mistrimulti_story_register_events")

    def frame(self):
        return {"epoch": self.node.rt["epoch"], "room": "town:undefined", "x": 80, "y": 80}

    def tick(self, now):
        self.node.interp.call("mistrimulti_story_tick")


def make_world(seed, guests=2, saves=None, **faults):
    saves = {} if saves is None else saves
    impls = {i: (lambda slot, epoch, clock, log: StoryNode(slot, epoch, clock, log, saves)) for i in range(guests + 1)}
    world = World(seed, impls, **faults)
    world.saves = saves
    for game in world.games.values():
        game.feature = Driver(game)
    return world


def restart(world, slot):
    game = world.start(slot)
    game.feature = Driver(game)
    return game


def nodes(world):
    return [world.games[i].node for i in sorted(world.games)]


def fakes(world):
    return [n.fake for n in nodes(world)]


def settle(world, ms=6000):
    world.run(ms)


def synced(world):
    return all(world.games[i].node.debug()["ready"] for i in world.games)


def wait_ready(world, limit=60000, skip=None):
    waited = 0
    while waited < limit:
        world.run(500)
        waited += 500
        if all(world.games[i].node.debug()["ready"] for i in world.games if i != skip):
            return
    raise AssertionError("the mirrors never became ready")


def world_state(node):
    f = node.fake
    return {"quests": f.story_levels(), "scenes": sorted(s for s in f.history if s in WORLD_SCENES),
            "facts": sorted(n for n in WORLD_FACTS if f.facts.get(n) is True), "counters": node.counters()}


def assert_converged(world, what=""):
    host, *guests = nodes(world)
    for g in guests:
        assert world_state(g) == world_state(host), f"{what}: guest {g.slot} differs\nhost  {world_state(host)}\nguest {world_state(g)}"


def assert_clean(world):
    for game in world.games.values():
        debug = game.node.call("mistrimulti_events_debug")
        assert debug["errors"] == 0, (game.slot, debug, game.warnings[:3])
        assert not any("failed" in w or "could not" in w for w in game.warnings), (game.slot, game.warnings)


def play(world, slot, scene, seconds=3):
    """A player watches a cutscene: while it runs the game is busy (the mod does nothing in it), then its effects land."""
    f = world.games[slot].node.fake
    f.scene_running = True
    f.active_scene = scene
    world.run(seconds * SECOND)
    f.watch(scene)
    f.scene_running = False
    f.active_scene = None


def stage_of(node, quest):
    return node.fake.level(quest)


# ---- world story -------------------------------------------------------------------------------------------------------

def test_start():
    world = make_world(1, loss=0.05, jitter=30)
    wait_ready(world)
    settle(world, 3000)
    assert_converged(world, "start")
    host, g1, g2 = nodes(world)
    assert host.debug()["quests"] == 1 and g1.debug()["quests"] == 1
    assert_clean(world)
    print("PASS: start: every game holds the host's story")


def test_host_progress():
    world = make_world(2, loss=0.05, dup=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    host.fake.hand_in("arrival")                  # stage 1 -> 2
    host.fake.quest_start("dragon")
    host.fake.quest_start("juniper_heart")        # personal: must stay with the host
    settle(world)
    assert stage_of(g1, "arrival") == 2 and stage_of(g2, "arrival") == 2 and stage_of(g1, "dragon") == 0
    assert stage_of(g1, "juniper_heart") is None and stage_of(g2, "juniper_heart") is None
    host.fake.hand_in("arrival")                  # done
    host.fake.quest_start("bridge")
    settle(world)
    for g in (g1, g2):
        assert stage_of(g, "arrival") == "done" and stage_of(g, "bridge") == 0
        assert (5, 5) in g.fake.boxes, "the turn-in box of the first task is placed in this game's copy of the world"
        assert g.fake.gold == 120 and g.fake.rewards == {"arrival": 2}, (g.fake.gold, g.fake.rewards)
        assert g.fake.items == {"trophy": 1} and g.fake.renown == ["arrival"], "the quest's own rewards and renown reach the others too"
    assert_converged(world, "host progress")
    # The festival's quest is run by every game itself and is never mirrored, even though the game files it under "story".
    host.fake.quest_start("spring_quest")
    settle(world, 4000)
    assert stage_of(g1, "spring_quest") is None and stage_of(g2, "spring_quest") is None
    assert_clean(world)
    print("PASS: host progress: story steps are mirrored without rewards; personal and festival quests are not")


def test_guest_progress():
    for seed in range(3):
        world = make_world(10 + seed, loss=0.1, dup=0.1, jitter=40)
        wait_ready(world)
        host, g1, g2 = nodes(world)
        g1.fake.hand_in("arrival")
        settle(world, 5000)
        assert stage_of(host, "arrival") == 2 and stage_of(g2, "arrival") == 2, (stage_of(host, "arrival"), stage_of(g2, "arrival"))
        assert host.fake.gold == 110 and g2.fake.gold == 110 and g1.fake.gold == 110, "everybody is paid for the step, once"
        g1.fake.hand_in("arrival")
        g1.fake.quest_start("bridge")
        settle(world, 5000)
        for g in (host, g2):
            assert stage_of(g, "arrival") == "done" and stage_of(g, "bridge") == 0 and (5, 5) in g.fake.boxes
        # Each mirrored game changed its quest log once per step: no start, no repeat.
        assert host.fake.starts == [("bridge", 0)], host.fake.starts
        assert host.fake.export()["done"] == ["arrival"], "the host's own save carries the story the guest advanced"
        g1.fake.hand_in("bridge")                 # task 0 handed in: the box goes away on the player who did it
        settle(world, 5000)
        assert stage_of(host, "bridge") == 1 and (5, 5) not in host.fake.boxes and (5, 5) not in g2.fake.boxes
        g1.fake.hand_in("bridge")
        settle(world, 5000)
        assert stage_of(host, "bridge") == "done" and stage_of(g2, "bridge") == "done"
        assert_converged(world, "guest progress")
        for n in (host, g1, g2):
            assert n.fake.gold == 140 and n.fake.items == {"trophy": 1} and n.fake.renown == ["arrival", "bridge"], \
                (n.slot, n.fake.gold, n.fake.items, n.fake.renown)
            assert all(v == 1 for v in n.fake.granted.values()), (n.slot, n.fake.granted)
            assert stage_of(n, "juniper_heart") == 0, "a reward that starts a personal quest starts it for everybody, once"
            assert stage_of(n, "dragon") == 0
            assert stage_of(n, "spring_quest") == (0 if n is g1 else None), \
                "the calendar's quest is the calendar's: a mirrored reward does not start it"
        assert [x for x in host.fake.starts if x[0] in ("dragon", "juniper_heart")] == [("dragon", 0), ("juniper_heart", 0)] or \
            [x for x in host.fake.starts if x[0] in ("dragon", "juniper_heart")] == [("juniper_heart", 0), ("dragon", 0)], host.fake.starts
        assert_clean(world)
    print("PASS: guest progress: the host takes the story step once, every game mirrors it, everybody is paid its rewards once")


def test_same_step_race():
    for seed in range(4):
        world = make_world(20 + seed, loss=0.15, dup=0.15, jitter=60)
        wait_ready(world)
        host, g1, g2 = nodes(world)
        # Three players take the same step at the same moment; each did it in their own game.
        for n in (host, g1, g2):
            n.fake.hand_in("arrival")
        settle(world, 6000)
        for n in (host, g1, g2):
            assert stage_of(n, "arrival") == 2, (n.slot, stage_of(n, "arrival"))
            assert n.fake.rewards == {"arrival": 1}, "every player is paid once for their own hand-in"
        # The same flag raised twice: a world cutscene watched by two players, a fact, a secret chest.
        play(world, 1, "narrows_secret", 1)
        play(world, 2, "narrows_secret", 1)
        for n in (g1, g2):
            n.fake.facts["caldarus_home"] = True
        g1.set_counter(0, 1)
        g2.set_counter(0, 2)
        g1.set_counter(1, 3)
        settle(world, 6000)
        for n in (host, g1, g2):
            assert n.fake.history.count("narrows_secret") == 1
            assert n.fake.facts.get("caldarus_home") is True
            assert n.counters() == [2, 3, 0], n.counters()
        # A world scene with a relative effect (advance the dragon quest by one): two viewers, one step in the world.
        play(world, 1, "fire_seal", 1)
        play(world, 2, "fire_seal", 1)
        settle(world, 6000)
        for n in (host, g1, g2):
            assert stage_of(n, "dragon") == 1, (n.slot, stage_of(n, "dragon"))
        assert host.fake.removals == 1 and host.fake.spells == [7], "the host applied the scene's lasting effects once"
        assert_converged(world, "race")
        assert_clean(world)
    print("PASS: two or three players taking the same step advance the world once; rewards stay personal")


def test_world_scenes():
    world = make_world(3, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    play(world, 0, "fire_seal", 2)
    settle(world, 5000)
    for g in (g1, g2):
        f = g.fake
        assert "fire_seal" in f.history and f.facts.get("cutscene_seen_fire_seal") == 1.0
        assert f.removals == 1 and f.spells == [7] and f.ari["mana_max"] == 40
        assert stage_of(g, "dragon") == 1
    play(world, 0, "upgrade_the_saturday_market_plaza", 1)
    play(world, 0, "alt_scene", 1)           # read by a world mod through an "or"
    play(world, 0, "quest_gate", 1)          # starts a story quest
    settle(world, 5000)
    for g in (g1, g2):
        assert g.fake.nuked_cells == 4 and g.fake.plaza == 1
        assert "alt_scene" in g.fake.history and "quest_gate" in g.fake.history and stage_of(g, "bridge") == 0
    # Heart events, romance scenes and the like stay with the player.
    claims = g1.debug()["stats"]["claims"]
    for scene in ("juniper_two", "heart_change", "wedding", "date_beach"):
        play(world, 1, scene, 1)
    settle(world, 5000)
    for n in (host, g2):
        assert not {"juniper_two", "heart_change", "wedding", "date_beach"} & set(n.fake.history), n.fake.history
    assert g1.debug()["stats"]["claims"] == claims, "a private scene is not even claimed"
    assert_converged(world, "scenes")
    assert_clean(world)
    print("PASS: world cutscenes change every game once (objects, area, spell); heart events and romance scenes stay private")


def test_facts_and_counters():
    saves = {}
    world = make_world(4, saves=saves, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    g1.fake.facts["bridge_fixed"] = True               # read by a world gate in the game's data
    g1.fake.facts["market_open"] = True                # read by an alias gate
    g1.fake.facts["caldarus_seridia_town"] = True      # the dragon story's own fact
    g1.fake.facts["just_my_mood"] = True               # nobody's gate reads it
    g1.set_counter(2, 1)
    settle(world, 5000)
    for n in (host, g2):
        assert n.fake.facts.get("bridge_fixed") is True and n.fake.facts.get("market_open") is True
        assert n.fake.facts.get("caldarus_seridia_town") is True and n.fake.facts.get("just_my_mood") is None
        assert n.counters() == [0, 0, 1]
    # A counter never goes back: a restarted host with an older save takes the guests' value again.
    saves[0] = {**default_save(), "counters": [0, 0, 0]}
    restart(world, 0)
    settle(world, 12000)
    assert world.games[0].node.counters() == [0, 0, 1], world.games[0].node.counters()
    assert_clean(world)
    print("PASS: world facts and secret counters: only what a world gate reads is shared, and only upwards")


def test_late_join():
    world = make_world(5, guests=3, loss=0.05, jitter=30)
    world.net.partition(0, 3)
    wait_ready(world, skip=3)
    host, g1, g2, g3 = nodes(world)
    host.fake.hand_in("arrival")
    host.fake.quest_start("bridge")
    g1.fake.hand_in("arrival")
    play(world, 0, "fire_seal", 1)
    g2.fake.facts["caldarus_home"] = True
    g2.set_counter(1, 2)
    settle(world, 6000)
    assert stage_of(g3, "arrival") == 1 and "fire_seal" not in g3.fake.history      # nothing has reached the late game
    world.net.partition(0, 3, False)
    settle(world, 12000)
    assert synced(world)
    assert_converged(world, "late join")
    assert stage_of(g3, "bridge") == 0 and (5, 5) in g3.fake.boxes and g3.fake.removals == 1
    assert g3.fake.gold == 100 and not g3.fake.rewards
    assert_clean(world)
    print("PASS: late join: a game that arrives after everything happened gets the whole story at once")


def test_away_and_back():
    world = make_world(6, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    world.net.partition(0, 1)
    host.fake.hand_in("arrival")
    play(world, 0, "narrows_secret", 1)
    settle(world, 14000)                  # longer than the layer's 10 s: the guest expires and returns in the same session
    assert stage_of(g1, "arrival") == 1
    world.net.partition(0, 1, False)
    settle(world, 14000)
    assert stage_of(g1, "arrival") == 2 and "narrows_secret" in g1.fake.history
    assert_converged(world, "away and back")
    assert_clean(world)
    print("PASS: a guest that was away for more than ten seconds comes back to the host's story")


def test_guest_restart():
    saves = {}
    world = make_world(7, saves=saves, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    host.fake.hand_in("arrival")
    play(world, 0, "narrows_secret", 1)
    settle(world, 5000)
    # The guest's game restarts from its old copy of the world: older than the host's story, with its own personal quest.
    saves[1] = {**default_save(), "personal": {"crown_1": 1, "juniper_heart": 0}}
    restart(world, 1)
    settle(world, 12000)
    g1 = world.games[1].node
    assert synced(world)
    assert stage_of(g1, "arrival") == 2 and "narrows_secret" in g1.fake.history
    assert g1.debug()["stats"]["claims"] == 0, "a game behind the host claims nothing"
    assert stage_of(g1, "juniper_heart") == 0 and stage_of(g1, "crown_1") == 1, "personal quests are untouched"
    assert stage_of(nodes(world)[0], "juniper_heart") is None
    assert_converged(world, "guest restart")
    # The same game restarts again from a save that is AHEAD of the host (it was played alone): the host takes the progress.
    saves[1] = {**default_save(), "quests": {"arrival": 2, "bridge": 1}, "done": [], "scenes": ["tutorial_intro", "alt_scene"]}
    restart(world, 1)
    settle(world, 12000)
    host = nodes(world)[0]
    assert stage_of(host, "bridge") == 1 and "alt_scene" in host.fake.history
    assert_converged(world, "guest ahead")
    assert_clean(world)
    print("PASS: a restarted guest catches up and keeps its personal quests; progress made ahead of the host is not lost")


def test_host_restart():
    saves = {}
    world = make_world(8, saves=saves, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    host.fake.hand_in("arrival")
    g1.fake.facts["caldarus_home"] = True
    settle(world, 5000)
    saves[0] = host.fake.export(host.counters())              # the host saves here
    g1.fake.hand_in("arrival")                                  # done
    g1.fake.quest_start("bridge")
    play(world, 1, "narrows_secret", 1)
    settle(world, 5000)
    assert stage_of(host, "arrival") == "done"
    # The host crashes and restarts from the save above: the story the guests made after it is not in it.
    restart(world, 0)
    settle(world, 15000)
    host = nodes(world)[0]
    assert synced(world)
    assert stage_of(host, "arrival") == "done" and stage_of(host, "bridge") == 0 and "narrows_secret" in host.fake.history, \
        "the guests re-assert their progress to the restarted host"
    assert_converged(world, "host restart")
    assert g1.fake.gold == 120 and not g1.fake.rewards.get("bridge")
    # The restarted host went back to a save from before the guests' steps: it is paid for them again, once (its inventory was
    # rolled back with the save, and so was its ledger).
    assert host.fake.gold == 120 and host.fake.items == {"trophy": 1}, (host.fake.gold, host.fake.items)
    assert g1.fake.gold == 120 and g1.fake.items == {"trophy": 1}, "the guests are not paid again"
    # A claim that is in flight while the host restarts is neither lost nor applied twice.
    world.net.partition(0, 2)
    g2.fake.hand_in("bridge")                  # bridge task 0
    settle(world, 3000)
    saves[0] = host.fake.export(host.counters())
    restart(world, 0)
    world.net.partition(0, 2, False)
    settle(world, 15000)
    host = nodes(world)[0]
    assert stage_of(host, "bridge") == 1 and stage_of(g2, "bridge") == 1 and stage_of(g1, "bridge") == 1
    assert g2.debug()["pending"] == 0
    assert_clean(world)
    print("PASS: host restart: guests' progress returns to the restarted host once; in-flight claims survive")


def test_cutscene_hold():
    world = make_world(9, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    claims = g1.debug()["stats"]["claims"]
    g1.fake.scene_running = True              # a long scene on the guest
    g1.fake.hand_in("arrival")                # the quest log changes during the scene (the game's own bookkeeping)
    host.fake.quest_start("dragon")           # meanwhile the world goes on
    host.fake.hand_in("arrival")
    settle(world, 8000)
    assert g1.debug()["stats"]["claims"] == claims, "nothing is claimed during a scene"
    assert stage_of(g2, "dragon") == 0, "the others are not held by the scene"
    assert stage_of(g1, "dragon") is None, "nothing is applied during a scene"
    g1.fake.scene_running = False
    settle(world, 6000)
    assert stage_of(g1, "dragon") == 0 and stage_of(g1, "arrival") == 2
    assert_converged(world, "after scene")
    # The end-of-day sequence is left alone in the same way.
    g2.fake.ari["end_of_day_status"] = 1
    host.fake.quest_start("bridge")
    settle(world, 5000)
    assert stage_of(g2, "bridge") is None
    g2.fake.ari["end_of_day_status"] = None
    settle(world, 4000)
    assert stage_of(g2, "bridge") == 0
    assert_clean(world)
    print("PASS: a cutscene (or the end of day) holds only its own game: nobody else waits, nothing is applied mid-scene")


def test_host_scene_and_join():
    world = make_world(11, loss=0.05, jitter=30)
    world.net.partition(0, 2)
    wait_ready(world, skip=2)
    host, g1, g2 = nodes(world)
    host.fake.hand_in("arrival")
    settle(world, 3000)
    host.fake.scene_running = True            # the host is watching a cutscene when a new game arrives
    world.net.partition(0, 2, False)
    settle(world, 12000)
    assert stage_of(g2, "arrival") == 2 and g2.debug()["ready"], "the snapshot is data: a scene on the host does not delay it"
    host.fake.scene_running = False
    assert_clean(world)
    print("PASS: a game that joins while the host watches a cutscene still gets the story at once")


def test_many_changes():
    world = make_world(19, guests=3, loss=0.05, dup=0.05, jitter=40)
    world.net.partition(0, 3)
    wait_ready(world, skip=3)
    host, g1, g2, g3 = nodes(world)
    # The host's send queue is full for a while (it holds 512 events and nobody acknowledges while the guests are cut off, but
    # for less than the ten seconds after which the layer drops a guest): changes are delayed, never lost.
    for _ in range(506):
        assert host.call("mistrimulti_event_emit", "filler", {})
    assert not host.call("mistrimulti_event_can_emit", 12)
    world.net.partition(0, 1)
    world.net.partition(0, 2)
    for i in range(100):
        host.fake.quest_start("chapter_%03d" % i)
        host.fake.hand_in("chapter_%03d" % i)
    settle(world, 5000)
    assert stage_of(g1, "chapter_000") is None and host.call("mistrimulti_event_backlog") >= 506
    world.net.partition(0, 1, False)
    world.net.partition(0, 2, False)
    settle(world, 25000)
    for g in (g1, g2):
        assert all(stage_of(g, "chapter_%03d" % i) == "done" for i in range(100)), [i for i in range(100) if stage_of(g, "chapter_%03d" % i) != "done"]
    # A game that arrives now gets the whole long story from the snapshot, a few changes per second.
    world.net.partition(0, 3, False)
    settle(world, 30000)
    assert all(stage_of(g3, "chapter_%03d" % i) == "done" for i in range(100))
    assert_converged(world, "many changes")
    for g in (g1, g2):
        assert g.fake.gold == 1100 and all(g.fake.rewards.get("chapter_%03d" % i) == 1 for i in range(100)), (g.slot, g.fake.gold)
    assert g3.fake.gold == 100 and not g3.fake.rewards, "a game that joins after the steps is not paid for them"
    assert_clean(world)
    print("PASS: a hundred story steps at once, a full send queue and a late joiner: every game gets all of them, nothing is paid twice")


def test_quiet():
    world = make_world(12, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    host.fake.hand_in("arrival")
    g1.fake.quest_start("dragon")
    play(world, 2, "narrows_secret", 1)
    settle(world, 10000)
    assert_converged(world, "quiet")
    seqs = [world.games[i].node.rt["ev"]["next"] for i in world.games]
    claims = [n.debug()["stats"]["claims"] for n in nodes(world)]
    settle(world, 20000)
    assert [world.games[i].node.rt["ev"]["next"] for i in world.games] == seqs, "a converged world sends nothing more"
    assert [n.debug()["stats"]["claims"] for n in nodes(world)] == claims
    print("PASS: once converged, nobody sends anything (no echo between mirrors)")


def test_claim_is_sent_once():
    world = make_world(17, loss=0.0)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    world.net.partition(0, 1)
    g1.fake.hand_in("arrival")
    settle(world, 8000)                       # the host is out of reach: the claim waits, it is not repeated every second
    assert g1.debug()["stats"]["claims"] == 1, g1.debug()["stats"]
    assert g1.call("mistrimulti_event_requests_pending") == 1
    world.net.partition(0, 1, False)
    settle(world, 6000)
    assert stage_of(host, "arrival") == 2 and g1.debug()["stats"]["claims"] == 1
    print("PASS: a claim in flight is not repeated while it waits for the host")


def test_refused_claim_is_not_repeated():
    saves = {0: {**default_save(), "hidden": ["dragon"]}}              # the host's version does not know this quest
    world = make_world(21, saves=saves, loss=0.0)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    g1.fake.quest_start("dragon")
    settle(world, 12000)
    assert stage_of(host, "dragon") is None and stage_of(g2, "dragon") is None
    assert g1.debug()["stats"]["claims"] == 1 and g1.debug()["stats"]["refused"] == 1, g1.debug()
    # A claim the host takes is fine, and nothing else is held back by the refused one.
    g1.fake.hand_in("arrival")
    settle(world, 5000)
    assert stage_of(host, "arrival") == 2 and g1.debug()["stats"]["claims"] == 2
    assert_clean(world)
    print("PASS: a claim the host refuses is asked once, not every second")


def test_data_unreadable():
    world = make_world(22, loss=0.0)
    for n in nodes(world):
        n.interp.builtins["WORLD_MODS"] = None           # the game's data cannot be read
    wait_ready(world)
    host, g1, g2 = nodes(world)
    host.fake.hand_in("arrival")
    g1.fake.facts["caldarus_home"] = True
    new_day(world)
    settle(world, 8000)
    assert stage_of(g1, "arrival") == 1, "the story sync stays off when it cannot tell what is the world's"
    assert g1.debug()["error"].startswith("data"), g1.debug()["error"]
    assert g2.fake.npcs[0].swap_schedule_request is not None, "the villagers still follow the host"
    print("PASS: if the game's data cannot be read, the story sync switches itself off and the villagers keep working")


def json_of(value):
    return json.loads(gml.to_json(value))


def test_merge_rules():
    """The merge that every mirror and the host's claim handling use: max, idempotent, bounded, validated."""
    world = make_world(24, loss=0.0)
    wait_ready(world)
    host = nodes(world)[0]
    st = host.interp.call("__mistrimulti_story")

    def merge(d, strict=True, limit=20):
        return json_of(host.call("mistrimulti_story_merge", st, d, strict, limit))

    assert merge({"q": [["arrival", 2]]})["q"] == [["arrival", 2]]
    assert merge({"q": [["arrival", 2]]})["q"] == [], "the same level again changes nothing"
    assert merge({"q": [["arrival", 1]]})["q"] == [] and st["q"]["arrival"] == 2, "a lower level never lowers the story"
    assert merge({"q": [["arrival", 1000000]]})["q"] == [["arrival", 1000000]]
    assert merge({"q": [["arrival", 2]]})["q"] == [] and st["q"]["arrival"] == 1000000, "done is final"
    assert merge({"q": [["bridge", 2]]})["q"] == [], "a stage the quest does not have is refused"
    assert merge({"sc": ["narrows_secret", "narrows_secret", "wedding"]})["sc"] == ["narrows_secret"]
    assert merge({"f": ["caldarus_home", "bridge_fixed", "my_mood", "gold"]})["f"] == ["caldarus_home", "bridge_fixed"]
    assert merge({"k": {"n": 3, "b": 1}})["k"] == {"n": 3, "b": 1} and merge({"k": {"n": 2, "b": 1}})["k"] == {}
    assert merge({"k": {"t": 1001}})["k"] == {}
    # Not strict (a mirror applying what the host said): names must still be sane, but the game's data is not consulted.
    assert merge({"q": [["not_in_this_version", 4]]}, False)["q"] == [["not_in_this_version", 4]]
    assert merge({"q": [["a", 1], ["b", 1], ["c", 1]]}, False, 2)["q"] == [["a", 1], ["b", 1]], "the limit cuts a list"
    print("PASS: the merge is max, idempotent, validated and bounded")


def test_hostile_input():
    world = make_world(18, loss=0.0)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    before = (world_state(host), host.debug()["quests"], host.fake.starts[:])
    bad = [
        None, 5, "quests", [], [[1]], {"q": "arrival"}, {"q": [["arrival"]]}, {"q": [[5, 1]]}, {"q": [["arrival", -1]]},
        {"q": [["arrival", 1.5]]}, {"q": [["arrival", "3"]]}, {"q": [["arrival", 99]]}, {"q": [["arrival", 0]]}, {"q": [["arrival", 10 ** 9]]},
        {"q": [["no_such_quest", 1]]}, {"q": [["crown_1", 1]]}, {"q": [["juniper_heart", 0]]}, {"q": [["spring_quest", 0]]},
        {"q": [["x" * 200, 1]]}, {"q": [["", 1]]}, {"q": [[["arrival"], 1]]}, {"q": "x" * 5000},
        {"sc": ["wedding", "date_beach", "juniper_two", "no_such_scene", "tutorial_intro", 5, None, "y" * 300]},
        {"f": ["just_my_mood", "gold", 7, None, "z" * 200]},
        {"k": {"n": -1, "b": 1.5, "t": 99999, "x": 4}}, {"k": [1, 2, 3]}, {"k": "n"},
    ]
    for data in bad:
        g1.call("mistrimulti_event_request", "story_claim", data)
    # Events that only the host may send, sent by a guest to everybody else.
    g1.call("mistrimulti_event_emit", "story_delta", {"q": [["dragon", 1]], "sc": ["fire_seal"], "f": ["caldarus_home"], "k": {"n": 5}})
    g1.call("mistrimulti_event_emit", "npc_plan", {"d": g2.fake.day, "s": ["s/festival"] * NPC_COUNT, "cf": True})
    g1.call("mistrimulti_event_emit", "npc_pos", {"d": g2.fake.day, "l": [BEACH] * NPC_COUNT, "a": [1] * NPC_COUNT})
    g1.call("mistrimulti_event_send_blob", "story_snapshot", '{"q":[["dragon",1]],"sc":["fire_seal"],"f":[],"k":{}}', -1)
    # Plans the host itself could not have made.
    host.call("mistrimulti_event_emit", "npc_plan", {"d": g2.fake.day, "s": ["s/home_day"] * (NPC_COUNT - 1), "cf": False})
    host.call("mistrimulti_event_emit", "npc_plan", {"d": g2.fake.day, "s": ["no such schedule"] * NPC_COUNT, "cf": False})
    host.call("mistrimulti_event_emit", "npc_plan", {"d": "x", "s": ["s/home_day"] * NPC_COUNT, "cf": False})
    host.call("mistrimulti_event_emit", "npc_pos", {"d": g2.fake.day, "l": [99999] * NPC_COUNT, "a": [-1] * NPC_COUNT})
    host.call("mistrimulti_event_emit", "npc_pos", {"d": g2.fake.day, "l": [1, 2], "a": []})
    settle(world, 12000)
    assert world_state(host) == before[0] and host.fake.starts == before[2], "no hostile claim changed the host"
    for g in (g1, g2):
        assert "fire_seal" not in g.fake.history and stage_of(g, "dragon") is None and g.counters() == [0, 0, 0]
        assert g.interp.globals["cancel_festivals"] is False
        assert g.fake.sched == ["s/home_day"] * NPC_COUNT
    assert all(n.swap_schedule_request is None for g in (g1, g2) for n in g.fake.npcs)
    assert stage_of(host, "arrival") == 1 and stage_of(host, "crown_1") == 1
    assert host.debug()["levels"]["arrival"] == 1, "a stale claim (stage 0) never lowers the world story"
    # A claim is cut at 20 entries per list: a valid entry behind that is ignored, one before it is applied.
    bogus = [["bogus%d" % i, 1] for i in range(25)]
    g1.call("mistrimulti_event_request", "story_claim", {"q": bogus + [["arrival", 2]]})
    settle(world, 4000)
    assert stage_of(host, "arrival") == 1
    g1.call("mistrimulti_event_request", "story_claim", {"q": [["arrival", 2]] + bogus})
    settle(world, 4000)
    assert stage_of(host, "arrival") == 2
    assert_converged(world, "oversized")
    assert_clean(world)
    print("PASS: hostile input: malformed, oversized, personal, festival or spoofed story data changes nothing")


# ---- villagers ----------------------------------------------------------------------------------------------------------

DAY_HOST = ["s/home_day", "s/town_day", "s/festival", "s/roommate", "s/home_day", "s/town_day"]
DAY_G1 = ["s/home_day", "s/festival", "s/festival", "s/home_day", "s/home_day", "s/town_day"]     # villagers 1, 3 differ
DAY_G2 = ["s/town_day"] * NPC_COUNT


def new_day(world, schedules=(DAY_HOST, DAY_G1, DAY_G2)):
    """The game starts a new day in every game (npcs_on_new_day), then the game.new_day hook runs."""
    for slot, schedule in zip(sorted(world.games), schedules):
        node = world.games[slot].node
        node.fake.new_day(schedule)
        node.call("mistrimulti_story_new_day", {})


def sample(world):
    return [[(f.where_is(i), f.doing(i), f.sched[i]) for i in range(NPC_COUNT)] for f in fakes(world)]


def test_npc_plan():
    for seed in range(3):
        world = make_world(30 + seed, loss=0.1, jitter=40)
        wait_ready(world)
        host, g1, g2 = nodes(world)
        host.set_room(FARM)
        g1.set_room(HOME)               # g1 stands where the villagers sleep: it sees them at the start
        g2.set_room(BEACH)
        new_day(world)
        settle(world, 7000)             # the plan arrives and is turned into the game's own swap requests
        assert g2.fake.npcs[0].swap_schedule_request is not None and g2.fake.npcs[1].swap_schedule_request is None
        for hour in range(1, 16):       # every game's villager step, one game hour at a time
            for f in fakes(world):
                f.advance(1)
            settle(world, 3000)
            if hour >= 3:
                s = sample(world)
                assert s[1] == s[0] and s[2] == s[0], f"hour {6 + hour}:\n{s[0]}\n{s[1]}\n{s[2]}"
        assert not Npc.violations, "the mod never places a villager itself, it only asks the game to swap schedules"
        assert_clean(world)
    print("PASS: villagers: every game follows the host's day plan, the same place and activity at the same hour")


def test_npc_never_moved_in_sight():
    world = make_world(13, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    g1.set_room(HOME)
    new_day(world)
    settle(world, 7000)
    # Villager 1 stands in the guest's room (home) under the guest's own schedule until it walks out of it on its own.
    assert g1.fake.where_is(1) == HOME and g1.fake.sched[1] == "s/festival" and g1.fake.npcs[1].swap_schedule_request is not None
    g1.fake.advance(1)
    assert g1.fake.where_is(1) == HOME and g1.fake.sched[1] == "s/festival", "still in sight: still untouched"
    assert not Npc.violations
    for _ in range(4):
        g1.fake.advance(1)
    assert g1.fake.where_is(1) != HOME or g1.fake.sched[1] == "s/town_day"
    assert g1.fake.sched[1] == "s/town_day", "swapped once it was out of sight"
    print("PASS: a villager in the player's room is never moved; the swap waits until it has left")


def test_npc_activity_and_room_drift():
    world = make_world(14, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    for n in (host, g1, g2):
        n.set_room(FARM)
    new_day(world, (DAY_HOST, DAY_HOST, DAY_HOST))
    for f in fakes(world):
        f.advance(2)                    # hour 8: villager 0 (home_day) walks to town and sits
    settle(world, 7000)
    assert sample(world)[0] == sample(world)[1] == sample(world)[2]
    # In the guest's game villager 0 is somewhere else and doing something else, out of sight: it is steered back.
    Npc.engine = True
    g1.fake.npcs[0].location_position = G(location_id=BEACH)
    g1.fake.npcs[3].activity_handler.activity = G(id=ACT_READ)
    g2.fake.npcs[1].activity_handler.activity = G(id=ACT_EAT)
    Npc.engine = False
    settle(world, 15000)
    for f in fakes(world):
        f.advance(1)
    settle(world, 6000)
    s = sample(world)
    assert s[1][0][0] == s[0][0][0], "the room drift of a villager out of sight is repaired (re-aligned to the schedule)"
    assert s[1][3][1] == s[0][3][1] and s[2][1][1] == s[0][1][1], "so is its activity"
    assert_clean(world)
    print("PASS: a villager that drifted to another room or activity out of sight is brought back to the host's")


def test_npc_in_sight_is_left_alone():
    world = make_world(23, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    for n in (host, g1, g2):
        n.set_room(FARM)
    new_day(world, (DAY_HOST, DAY_HOST, DAY_HOST))
    for f in fakes(world):
        f.advance(2)                    # hour 8: villager 0 is in town
    settle(world, 6000)
    # The guest stands in town, where villager 0 is, but its own is doing something else: in sight, so untouched.
    g1.set_room(TOWN)
    Npc.engine = True
    g1.fake.npcs[0].activity_handler.activity = G(id=ACT_READ)
    Npc.engine = False
    settle(world, 15000)
    assert g1.fake.npcs[0].activity_handler.request is None and g1.fake.doing(0) == ACT_READ
    # The guest stands on the beach, where its own villager 0 has drifted to (the host's is in town): in sight, so untouched.
    g1.set_room(BEACH)
    Npc.engine = True
    g1.fake.npcs[0].location_position = G(location_id=BEACH)
    Npc.engine = False
    settle(world, 15000)
    assert g1.fake.npcs[0].swap_schedule_request is None and g1.fake.where_is(0) == BEACH
    # The guest walks away: now it is brought back to where the host's villager is.
    g1.set_room(FARM)
    settle(world, 12000)
    assert g1.fake.npcs[0].swap_schedule_request is not None
    g1.fake.advance(1)
    host.fake.advance(1)
    assert g1.fake.where_is(0) == host.fake.where_is(0)
    assert not Npc.violations
    print("PASS: a villager the player can see is never corrected; it is, once the player looks away")


def test_festival_flag():
    world = make_world(15, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    new_day(world)
    host.interp.globals["cancel_festivals"] = True
    settle(world, 8000)
    assert g1.interp.globals["cancel_festivals"] is True and g2.interp.globals["cancel_festivals"] is True
    # A plan is only used on its own day: a guest that is a day ahead of the host's world does not take it.
    host.interp.globals["cancel_festivals"] = False
    g1.fake.day += 1
    g1.interp.globals["cancel_festivals"] = False
    settle(world, 8000)
    host.interp.globals["cancel_festivals"] = True
    settle(world, 8000)
    assert g1.interp.globals["cancel_festivals"] is False and g2.interp.globals["cancel_festivals"] is True
    print("PASS: the festival-cancel flag follows the host's plan, and a plan is used only on its own day")


def test_heart_event_is_private():
    world = make_world(16, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    for n in (host, g1, g2):
        n.set_room(FARM)
    new_day(world, (DAY_HOST, DAY_HOST, DAY_HOST))
    settle(world, 6000)
    host_before = sample(world)[0]
    # The guest's heart event moves its own villagers around (the game's scene clean-up respawns them from their own state).
    play(world, 1, "juniper_two", 2)
    Npc.engine = True
    g1.fake.npcs[3].location_position = G(location_id=BEACH)
    Npc.engine = False
    g1.fake.npcs[3].swap_schedule_request = {"schedule_name": "s/festival", "finish": False}
    settle(world, 8000)
    assert sample(world)[0] == host_before and sample(world)[2] == host_before, "nothing the guest does moves anybody else's villagers"
    assert_clean(world)
    print("PASS: a heart event never moves villagers for the other players")


# ---- rewards of story steps for the players who did not do the step -------------------------------------------------------------

def paid_once(*games):
    """Every reward every game has been given was given once."""
    for n in games:
        assert all(v == 1 for v in n.fake.granted.values()), (n.slot, n.fake.granted)


def test_rewards_offline_and_restart():
    saves = {}
    world = make_world(40, saves=saves, loss=0.1, dup=0.1, jitter=40)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    # g1 is away for longer than the layer waits (it is expired) while the story moves twice.
    world.net.partition(0, 1)
    host.fake.hand_in("arrival")                       # task 1: 10 gold
    settle(world, 3000)
    host.fake.hand_in("arrival")                       # task 2: 10 gold, then the quest's trophy and renown
    host.fake.quest_start("bridge")
    settle(world, 14000)
    assert stage_of(g2, "arrival") == "done" and g2.fake.gold == 120 and g2.fake.items == {"trophy": 1} and g2.fake.renown == ["arrival"]
    assert stage_of(g1, "arrival") == 1 and g1.fake.gold == 100, "the guest that is away has been given nothing yet"
    world.net.partition(0, 1, False)
    settle(world, 14000)
    assert stage_of(g1, "arrival") == "done"
    assert g1.fake.gold == 120 and g1.fake.items == {"trophy": 1} and g1.fake.renown == ["arrival"], (g1.fake.gold, g1.fake.items)
    paid_once(host, g1, g2)
    # The guest's game is closed and started again from its old world copy, with the ledger of its record (it had been given
    # everything up to the first task of arrival); the host has moved on since.
    host.fake.hand_in("bridge")                        # 10 gold
    settle(world, 5000)
    saves[1] = {**default_save(), "ledger": {"init": 1, "arrival": 1}}
    restart(world, 1)
    settle(world, 14000)
    g1 = world.games[1].node
    assert stage_of(g1, "arrival") == "done" and stage_of(g1, "bridge") == 1
    assert g1.fake.gold == 130 and g1.fake.items == {"trophy": 1} and g1.fake.renown == ["arrival"], \
        (g1.fake.gold, g1.fake.items, g1.fake.renown)
    paid_once(g1)
    # Its record is saved with the ledger; the next restart, even from a world copy that is older again, is given nothing more.
    saved = g1.fake.export()
    assert saved["ledger"] == {"init": True, "arrival": 1000000, "bridge": 1}, saved["ledger"]
    saves[1] = {**saved, "quests": {"arrival": 1}, "done": []}
    restart(world, 1)
    settle(world, 12000)
    g1 = world.games[1].node
    assert stage_of(g1, "arrival") == "done" and g1.fake.gold == 130 and g1.fake.items == {"trophy": 1}, (g1.fake.gold, g1.fake.items)
    assert g1.fake.renown == ["arrival"]
    assert_clean(world)
    print("PASS: rewards: a guest that was away, or restarted from an older world, is paid once for what it missed")


def test_rewards_new_character_is_not_owed_the_past():
    saves = {0: {**default_save(), "quests": {"arrival": 2, "bridge": 1}, "done": ["dragon"]}}
    world = make_world(41, saves=saves, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    settle(world, 6000)
    # The guests joined (as new characters) a story that was well on its way, and the host has no ledger yet: nothing of it is owed.
    for n in (host, g1, g2):
        assert n.fake.gold == 100 and not n.fake.items and not n.fake.renown and not n.fake.rewards, (n.slot, n.fake.gold, n.fake.items)
        assert n.fake.facts.get("mm_paid_init") is True and n.fake.facts.get("mm_paid_arrival") == 2
        assert n.fake.facts.get("mm_paid_dragon") == 1000000 and n.fake.facts.get("mm_paid_bridge") == 1
    host.fake.hand_in("arrival")                       # the next step is owed to everybody
    settle(world, 6000)
    for n in (host, g1, g2):
        assert n.fake.gold == 110 and n.fake.items == {"trophy": 1} and n.fake.renown == ["arrival"], (n.slot, n.fake.gold)
    paid_once(host, g1, g2)
    assert_clean(world)
    print("PASS: rewards: a new character (or a game without a ledger) is not owed the story so far; the next step is")


def test_rewards_exactly_once_under_loss():
    for seed in range(3):
        world = make_world(42 + seed, loss=0.15, dup=0.15, jitter=60)
        wait_ready(world)
        host, g1, g2 = nodes(world)
        # Steps by all three players, one at the same moment by two of them, and the last by a guest.
        host.fake.hand_in("arrival")
        settle(world, 3000)
        g1.fake.hand_in("arrival")
        g2.fake.hand_in("arrival")                     # the same step as g1's, at the same moment (arrival is now done)
        settle(world, 3000)
        g2.fake.quest_start("bridge")
        settle(world, 2000)
        g2.fake.hand_in("bridge")
        host.fake.hand_in("bridge")                    # again the same step twice
        settle(world, 9000)
        g1.fake.hand_in("bridge")
        settle(world, 9000)
        for n in (host, g1, g2):
            assert stage_of(n, "arrival") == "done" and stage_of(n, "bridge") == "done"
        # Every player was paid for each of the five steps once: a step two players took is each one's own.
        for n in (host, g1, g2):
            assert n.fake.items.get("trophy") == 1 and n.fake.renown.count("arrival") == 1 and n.fake.renown.count("bridge") == 1, \
                (n.slot, n.fake.items, n.fake.renown)
        assert_converged(world, "rewards under loss")
        assert_clean(world)
    print("PASS: rewards: under loss and duplication, two players taking one step, nobody is paid twice for anything")


def test_scene_items():
    for seed in range(2):
        world = make_world(44 + seed, loss=0.1, dup=0.1, jitter=40)
        wait_ready(world)
        host, g1, g2 = nodes(world)
        world.net.partition(0, 2)
        play(world, 0, "fire_seal", 2)                 # items, free baths, advances the dragon quest, a spell
        play(world, 1, "alt_scene", 1)                 # a scene that a world gate reads: its items go to everybody
        play(world, 1, "juniper_two", 1)               # a heart event: its item is the watcher's alone
        settle(world, 5000)
        assert g1.fake.items == {"sword": 1, "lantern": 2, "rose": 1}, g1.fake.items
        assert host.fake.items == {"sword": 1, "lantern": 2} and host.fake.ari["free_baths"] == 2, host.fake.items
        assert g2.fake.items == {} and g2.fake.ari["free_baths"] == 0, "the guest that is away has not got them yet"
        world.net.partition(0, 2, False)
        settle(world, 14000)
        assert g2.fake.items == {"sword": 1, "lantern": 2}, g2.fake.items
        assert g2.fake.ari["free_baths"] == 2 and g1.fake.ari["free_baths"] == 2
        # Two players watching the same scene at the same moment are each given its items once.
        before = (host.fake.items, g1.fake.items)
        play(world, 0, "quest_gate", 1)
        settle(world, 6000)
        assert (host.fake.items, g1.fake.items) == before
        paid_once(host, g1, g2)
        assert_clean(world)
    # Both watch the same scene at once (in two games at the same time): once each, the third game gets it once.
    world = make_world(48, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    host.fake.scene_running = g1.fake.scene_running = True
    world.run(2000)
    host.fake.watch("alt_scene")
    g1.fake.watch("alt_scene")
    host.fake.scene_running = g1.fake.scene_running = False
    settle(world, 8000)
    for n in (host, g1, g2):
        assert n.fake.items == {"lantern": 2}, (n.slot, n.fake.items)
    print("PASS: rewards: a world cutscene's items and baths reach the players who did not watch it, once; heart events stay private")


def test_failed_reward_is_not_repeated():
    world = make_world(49, loss=0.0)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    real = g1.interp.builtins["grant_quest_rewards"]
    calls = []

    def failing(rewards):
        calls.append(1)
        raise gml.GmlError("the reward could not be given")
    g1.interp.builtins["grant_quest_rewards"] = failing
    host.fake.hand_in("arrival")
    settle(world, 6000)
    assert len(calls) == 1 and g1.fake.gold == 100 and stage_of(g1, "arrival") == 2
    assert any("could not be given" in w for w in world.games[1].warnings), world.games[1].warnings
    g1.interp.builtins["grant_quest_rewards"] = real
    settle(world, 10000)
    assert len(calls) == 1 and g1.fake.gold == 100, "a reward that failed is not retried (it might have been half given)"
    host.fake.hand_in("arrival")                       # the next step is paid
    settle(world, 6000)
    assert g1.fake.gold == 110 and g1.fake.items == {"trophy": 1}
    print("PASS: rewards: a reward that cannot be given is logged and not retried; the next step is paid")


# ---- spouses of other players live at the farm --------------------------------------------------------------------------------

def uid(slot):
    return "local:%032x" % slot


def marry(world, owner, name, native=True):
    """The host's registry says `owner` is married to `name` (the guests got it in romance_claims); the owner's own game has the
    status fact the game's relationship code writes."""
    nodes(world)[0].rt["romance_spouse"][name] = uid(owner)
    for n in nodes(world)[1:]:
        n.rt["romance_spouse_view"][name] = uid(owner)
    if native:
        world.games[owner].node.fake.facts[name + "_status"] = "spouse"


def divorce(world, owner, name):
    nodes(world)[0].rt["romance_spouse"].pop(name, None)
    for n in nodes(world)[1:]:
        n.rt["romance_spouse_view"].pop(name, None)
    world.games[owner].node.fake.facts[name + "_status"] = "best_friend"


def at_farm(n, i):
    return n.fake.where_is(i) in (FARM, HOME)


def test_guest_spouse_moves_in():
    for seed in range(2):
        Npc.violations.clear()
        world = make_world(50 + seed, loss=0.1, jitter=40)
        wait_ready(world)
        host, g1, g2 = nodes(world)
        marry(world, 1, "juniper")                      # g1 is married to Juniper (2); her pet Dozy (3) comes along
        new_day(world, ([ "s/home_day"] * NPC_COUNT,) * 3)
        for n in (host, g1, g2):
            assert n.fake.sched[2] == ROOMMATE and n.fake.sched[3] == ROOMMATE, (n.slot, n.fake.sched)
            assert n.fake.spot(2) == "bed" and n.fake.spot(3) == "floor", (n.slot, n.fake.spot(2), n.fake.spot(3))
            assert n.fake.npcs[2].brain_dead is False and n.fake.npcs[2].talk_flag is False
            assert n.fake.facts.get("juniper_status") == ("spouse" if n.slot == 1 else None), "the status is the player's own"
        assert g1.fake.swaps_done == [] and list(g1.debug()["housed"]) == [], "the game moved in its own player's spouse itself"
        assert list(host.debug()["housed"]) == ["2", "3"] and list(g2.debug()["housed"]) == ["2", "3"]
        assert not Npc.violations
        for hour in range(1, 15):
            for f in fakes(world):
                f.advance(1)
            settle(world, 3000)
            s = sample(world)
            assert s[1] == s[0] and s[2] == s[0], f"hour {6 + hour}:\n{s[0]}\n{s[1]}\n{s[2]}"
            for n in (host, g1, g2):
                assert at_farm(n, 2) and at_farm(n, 3), (n.slot, hour, n.fake.where_is(2))
            assert all(f.sched[2] == ROOMMATE for f in fakes(world))
        assert not Npc.violations
        # The next day starts the same way, and nothing was asked twice on the first.
        swaps = len(host.fake.swaps_done)
        new_day(world, ([ "s/town_day"] * NPC_COUNT,) * 3)
        assert all(f.sched[2] == ROOMMATE and f.spot(2) == "bed" for f in fakes(world)) and len(host.fake.swaps_done) == swaps + 2
        assert_clean(world)
    print("PASS: a guest's spouse (and the pet) lives at the farm in every game: roommate schedule, bed, daily routine, every day")


def test_two_spouses_at_the_farm():
    Npc.violations.clear()
    world = make_world(52, loss=0.1, jitter=40)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    marry(world, 0, "hayden")                           # the host is married to Hayden (4) and Henrietta (5) lives with them
    marry(world, 1, "juniper")                          # and g1 to Juniper (2) and Dozy (3)
    new_day(world, ([ "s/home_day"] * NPC_COUNT,) * 3)
    for n in (host, g1, g2):
        assert all(n.fake.sched[i] == ROOMMATE for i in (2, 3, 4, 5)), (n.slot, n.fake.sched)
        assert all(at_farm(n, i) for i in (2, 3, 4, 5))
    # One bed: the player's own spouse has it in the game's own way; the other player's spouse starts the day on the floor.
    assert (host.fake.spot(4), host.fake.spot(2)) == ("bed", "floor")
    assert (g1.fake.spot(2), g1.fake.spot(4)) == ("bed", "floor")
    assert (g2.fake.spot(2), g2.fake.spot(4)) == ("bed", "floor"), "a player with no spouse: the first one in villager order"
    assert all(n.fake.spot(i) == "floor" for n in (host, g1, g2) for i in (3, 5))
    for hour in range(1, 15):
        for f in fakes(world):
            f.advance(1)
        settle(world, 3000)
        s = sample(world)
        assert s[1] == s[0] and s[2] == s[0], f"hour {6 + hour}:\n{s[0]}\n{s[1]}\n{s[2]}"
        assert all(at_farm(n, i) for n in (host, g1, g2) for i in (2, 3, 4, 5))
    assert_clean(world)
    print("PASS: two spouses at the farm (the host's and a guest's): both live there in every game, one bed, nobody left in the village")


def test_spouse_of_an_absent_guest():
    Npc.violations.clear()
    world = make_world(53, guests=1, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1 = nodes(world)
    host.rt["romance_spouse"]["juniper"] = uid(5)       # a guest who is not in this session (a stored record says so)
    g1.rt["romance_spouse_view"]["juniper"] = uid(5)
    new_day(world, ([ "s/home_day"] * NPC_COUNT,) * 2)
    for n in (host, g1):
        assert n.fake.sched[2] == ROOMMATE and n.fake.spot(2) == "bed" and n.fake.sched[3] == ROOMMATE
    for hour in range(1, 15):
        for f in fakes(world):
            f.advance(1)
        settle(world, 3000)
        assert all(at_farm(n, 2) and at_farm(n, 3) for n in (host, g1))
        assert sample(world)[1] == sample(world)[0]
    # The host alone (nobody connected) does the same.
    solo = make_world(54, guests=0, loss=0.0)
    solo_host = nodes(solo)[0]
    solo_host.rt["romance_spouse"]["hayden"] = uid(7)
    new_day(solo, ([ "s/home_day"] * NPC_COUNT,))
    assert solo_host.fake.sched[4] == ROOMMATE and solo_host.fake.sched[5] == ROOMMATE and solo_host.fake.spot(4) == "bed"
    print("PASS: the spouse of a guest who is away lives at the farm all the same (also with nobody else connected)")


def test_marriage_in_the_middle_of_a_day_and_divorce():
    Npc.violations.clear()
    world = make_world(55, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    for n in (host, g1, g2):
        n.set_room(BEACH)
    new_day(world, ([ "s/home_day"] * NPC_COUNT,) * 3)
    for f in fakes(world):
        f.advance(4)                                    # hour 10
    settle(world, 4000)
    assert all(f.sched[2] == "s/home_day" for f in fakes(world))
    marry(world, 1, "juniper")                          # the wedding was this morning; the registry just changed
    settle(world, 7000)
    for f in fakes(world):
        f.advance(1)
    settle(world, 7000)
    for f in fakes(world):
        f.advance(1)
    settle(world, 4000)
    for n in (host, g2):
        assert n.fake.sched[2] == ROOMMATE and n.fake.sched[3] == ROOMMATE, (n.slot, n.fake.sched)
    assert g1.fake.sched[2] == ROOMMATE, "the guest's own game follows the host's plan (the game moves a spouse in on the next day)"
    assert not Npc.violations, "mid-day the game's own deferred swap does it, out of sight"
    assert host.fake.swaps_done == [] and list(host.debug()["housed"]) == ["2", "3"]
    # Marriage ends: the villagers go back to the schedule the game would give them.
    divorce(world, 1, "juniper")
    settle(world, 7000)
    for f in fakes(world):
        f.advance(1)
    settle(world, 7000)
    for f in fakes(world):
        f.advance(1)
    settle(world, 4000)
    for n in (host, g1, g2):
        assert n.fake.sched[2] == "s/home_day" and n.fake.sched[3] == "s/home_day", (n.slot, n.fake.sched)
    assert list(host.debug()["housed"]) == []
    assert_clean(world)
    print("PASS: a marriage in the middle of a day moves the spouse in out of sight; a divorce sends them back")


def test_move_in_waits_while_the_player_looks():
    Npc.violations.clear()
    world = make_world(56, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    marry(world, 1, "juniper")
    g2.set_room(HOME)                                   # g2 stands where the villagers wake up
    new_day(world, ([ "s/home_day"] * NPC_COUNT,) * 3)
    assert g2.fake.sched[2] == "s/home_day" and g2.fake.swaps_done == [], "in sight: not moved at once"
    assert g2.fake.spot(2) is None
    settle(world, 7000)
    assert g2.fake.npcs[2].swap_schedule_request is not None and not Npc.violations
    g2.set_room(BEACH)
    g2.fake.advance(1)
    assert g2.fake.sched[2] == ROOMMATE and not Npc.violations
    # Fridays and festival days have their own roommate schedule.
    for weekday, festival, name in ((4, False, ROOMMATE + "_friday"), (2, True, ROOMMATE + "_festival")):
        for n in (host, g1, g2):
            n.fake.weekday, n.fake.festival = weekday, festival
            n.set_room(BEACH)
        new_day(world, ([ "s/home_day"] * NPC_COUNT,) * 3)
        assert all(f.sched[2] == name and f.sched[3] == name for f in fakes(world)), [f.sched for f in fakes(world)]
    print("PASS: a villager in the player's sight is moved in only after they leave; Friday and festival days use the game's schedules")


def test_bad_registry_changes_nobody():
    world = make_world(57, loss=0.0)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    own = g2.rt["uid"]
    g2.rt["romance_spouse_view"].update({"nobody": uid(1), "juniper": 5, "adeline": own, "eiland": None, "hayden": ["x"]})
    host.rt["romance_spouse"].update({"adeline": host.rt["uid"], "dozy": uid(1)})
    new_day(world, ([ "s/home_day"] * NPC_COUNT,) * 3)
    settle(world, 6000)
    assert g2.fake.sched == ["s/home_day"] * NPC_COUNT and g2.fake.swaps_done == [] and list(g2.debug()["housed"]) == []
    # The host's own registry entry is the game's business, and a pet is not somebody's spouse.
    assert host.fake.sched[0] == "s/home_day" and host.fake.sched[3] == "s/home_day" and list(host.debug()["housed"]) == []
    assert_clean(world)
    print("PASS: a malformed or forged registry (unknown names, wrong types, the player's own spouse) moves nobody and breaks nothing")


# ---- everybody sees the story scenes (held scenes) -------------------------------------------------------------------------------
# A world scene that one player watched is given to the others as its lasting effects only; each game plays the scene itself when
# its own conditions start it. See "Cutscenes that every player watches" in docs/SYNC-STORY.md.

def view_saves(guests=2, **extra):
    """Every game starts from a character that has been in this world before (its rewards ledger is seeded) with the dragon quest
    waiting at its first task: the scene `dragon_day2` needs exactly that."""
    saves = {}
    for slot in range(guests + 1):
        saves[slot] = {**default_save(), "quests": {"arrival": 1, "dragon": 0, "visions": 0},
                       "ledger": {"init": True, "arrival": 1}, **extra}
    return saves


def views_of(node):
    return dict(node.fake.views)


def held(node):
    return sorted(node.debug()["views"])


def assert_held_in(node, scene, quest, level):
    """The scene's effects landed (history, gate fact), the game still offers it, the quest waits for it."""
    f = node.fake
    assert scene in f.history and f.facts.get("cutscene_seen_" + scene) == 1.0, (node.slot, "effects missing", f.history)
    assert f.scene_struct(scene).can_repeat is True and scene in held(node), (node.slot, held(node))
    assert f.views.get(scene) is None, (node.slot, "the scene must not have been played by the mirror")
    assert stage_of(node, quest) == level, (node.slot, quest, stage_of(node, quest))


def test_view_scene_is_watched_by_everybody():
    """The real-game finding: the guest watched the dragon scene, the host never saw it. Now every game plays it once."""
    for seed in range(2):
        saves = view_saves()
        world = make_world(60 + seed, saves=saves, loss=0.05, dup=0.05, jitter=30)
        wait_ready(world)
        settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
        host, g1, g2 = nodes(world)
        assert all(n.fake.would_start("dragon_day2") for n in (host, g1, g2))
        play(world, 1, "dragon_day2", 3)                        # the guest watches it
        settle(world, 8000)
        assert views_of(g1) == {"dragon_day2": 1} and g1.fake.items == {"scale": 1} and g1.fake.ari["free_baths"] == 1
        assert stage_of(g1, "dragon") == 1 and g1.fake.gold == 110 and g1.fake.removals == 1
        for n in (host, g2):
            assert_held_in(n, "dragon_day2", "dragon", 0)
            f = n.fake
            assert f.removals == 1 and f.spells == [9], "the world effects landed once"
            assert f.would_start("dragon_day2"), "the game still offers the scene"
            assert f.items == {} and f.ari["free_baths"] == 0 and f.gold == 100, "the personal rest waits for the viewing"
        assert held(g1) == [], "the player who watched it has nothing to watch"
        # The host sees it now (and the game's skip, which ends the scene the same way, is the other player's choice).
        play(world, 0, "dragon_day2", 3)
        settle(world, 8000)
        assert views_of(host) == {"dragon_day2": 1} and held(host) == []
        assert host.fake.removals == 1, "the objects it removes are not removed twice"
        assert host.fake.items == {"scale": 1}, "a scene that gives its items once: paid once, after the viewing"
        assert host.fake.ari["free_baths"] == 1 and host.fake.gold == 110 and host.fake.spells == [9]
        assert not host.fake.would_start("dragon_day2") and host.fake.scene_struct("dragon_day2").can_repeat is False
        assert stage_of(host, "dragon") == 1
        assert_held_in(g2, "dragon_day2", "dragon", 0)
        play(world, 2, "dragon_day2", 1)                        # the other guest skips it
        settle(world, 8000)
        for n in (host, g1, g2):
            f = n.fake
            assert views_of(n) == {"dragon_day2": 1}, (n.slot, f.views)
            assert f.removals == 1 and f.spells == [9] and f.items == {"scale": 1} and f.ari["free_baths"] == 1, (n.slot, f.items)
            assert f.gold == 110 and f.rewards == {"dragon": 1}, (n.slot, f.gold, f.rewards)
            assert stage_of(n, "dragon") == 1 and held(n) == []
            assert not f.would_start("dragon_day2") and f.scene_struct("dragon_day2").can_repeat is False
            assert f.refused == []
        assert_converged(world, "held scene")
        assert_clean(world)
    print("PASS: held scene: the guest watches it, then the host and the other guest play it themselves; effects and rewards once")


def test_view_either_player_first_and_at_once():
    for order in ((0, 1), (1, 0), (2,), (0, 1, 2), (2, 1)):
        for seed in range(2):
            world = make_world(70 + seed + 10 * len(order), saves=view_saves(), loss=0.15, dup=0.15, jitter=60)
            wait_ready(world)
            settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
            host, g1, g2 = nodes(world)
            if len(order) == 3:
                for slot in order:                              # all three at the same moment
                    world.games[slot].node.fake.scene_running = True
                    world.games[slot].node.fake.active_scene = "dragon_day2"
                world.run(2000)
                for slot in order:
                    world.games[slot].node.fake.watch("dragon_day2")
                    world.games[slot].node.fake.scene_running = False
                    world.games[slot].node.fake.active_scene = None
            else:
                for slot in order:
                    play(world, slot, "dragon_day2", 2)
                    settle(world, 4000)
            settle(world, 8000)
            for slot in (0, 1, 2):
                if slot not in order:
                    play(world, slot, "dragon_day2", 2)
            settle(world, 12000)
            for n in (host, g1, g2):
                f = n.fake
                assert views_of(n) == {"dragon_day2": 1}, (order, n.slot, f.views)
                assert f.removals == 1 and f.spells == [9] and f.items == {"scale": 1} and f.ari["free_baths"] == 1, (order, n.slot, f.items, f.removals)
                assert f.gold == 110 and f.rewards == {"dragon": 1} and stage_of(n, "dragon") == 1, (order, n.slot, f.gold)
                assert held(n) == [] and not f.would_start("dragon_day2") and f.refused == [], (order, n.slot, held(n), f.refused)
                assert all(v == 1 for v in f.granted.values()), f.granted
            assert_converged(world, "order %s" % (order,))
            assert_clean(world)
    print("PASS: held scene: whoever triggers it first, in any order or all at once, under loss, everybody sees it once and is paid once")


def test_view_late_join_and_new_character():
    saves = view_saves(guests=3)
    saves[3]["ledger"] = {}                                      # slot 3 is a brand-new character
    world = make_world(80, guests=3, saves=saves, loss=0.05, jitter=30)
    world.net.partition(0, 3)
    wait_ready(world, skip=3)
    settle(world, 3000)
    world.net.partition(0, 2)
    host, g1, g2, g3 = nodes(world)
    play(world, 1, "dragon_day2", 2)
    settle(world, 6000)
    assert held(host) == ["dragon_day2"] and g2.fake.history == ["tutorial_intro"]
    world.net.partition(0, 2, False)
    world.net.partition(0, 3, False)
    settle(world, 14000)
    assert synced(world)
    assert_held_in(g2, "dragon_day2", "dragon", 0)               # a character that was away is shown it when it returns
    f3 = g3.fake
    assert "dragon_day2" in f3.history and f3.views == {} and held(g3) == [] and not f3.would_start("dragon_day2")
    assert f3.items == {"scale": 1} and f3.ari["free_baths"] == 1, "a new character is not owed the scene: it gets the scene's gifts at once"
    assert stage_of(g3, "dragon") == 1 and f3.scene_struct("dragon_day2").can_repeat is False
    play(world, 2, "dragon_day2", 2)
    play(world, 0, "dragon_day2", 2)
    settle(world, 8000)
    for n in (host, g1, g2, g3):
        assert n.fake.items == {"scale": 1} and n.fake.removals == 1 and stage_of(n, "dragon") == 1, (n.slot, n.fake.items)
    assert_converged(world, "late join")
    assert_clean(world)
    print("PASS: held scene: a returning player that joins later is shown it; a new character is not owed it")


def test_view_survives_restarts():
    saves = view_saves()
    world = make_world(81, saves=saves, loss=0.05, jitter=30)
    wait_ready(world)
    settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
    host, g1, g2 = nodes(world)
    play(world, 1, "dragon_day2", 2)
    settle(world, 6000)
    assert held(host) == ["dragon_day2"] and held(g2) == ["dragon_day2"]
    # The host crashes and restarts from a save made while it was waiting to see the scene.
    saves[0] = host.fake.export(host.counters())
    assert "mm_view" in saves[0]["textfacts"]
    restart(world, 0)
    settle(world, 15000)
    host = nodes(world)[0]
    assert_held_in(host, "dragon_day2", "dragon", 0)
    assert host.fake.would_start("dragon_day2")
    # The guest restarts too, from a save with the scene held.
    saves[2] = g2.fake.export(g2.counters())
    restart(world, 2)
    settle(world, 15000)
    g2 = nodes(world)[2]
    assert_held_in(g2, "dragon_day2", "dragon", 0)
    play(world, 0, "dragon_day2", 2)
    play(world, 2, "dragon_day2", 2)
    settle(world, 12000)
    for n in nodes(world):
        assert views_of(n) == {"dragon_day2": 1} and n.fake.items == {"scale": 1} and stage_of(n, "dragon") == 1, (n.slot, n.fake.views, n.fake.items)
        # a game that restarted starts counting again; none of them removed anything at the viewing
        assert n.fake.removals == (1 if n.slot == 1 else 0), (n.slot, n.fake.removals)
    assert_converged(world, "restarts")
    assert_clean(world)
    print("PASS: held scene: a host or guest that restarts while waiting to see the scene still gets it, once")


def test_view_corrupt_save_is_ignored():
    texts = ["not json", "[1,2]", '{"nowhere": 3, "dragon_day2": "x"}', '{"dragon_day2": 4}', '{"dragon_day2": -1}']
    for text in texts:
        saves = view_saves(textfacts={"mm_view": text})
        world = make_world(82, saves=saves, loss=0.0)
        wait_ready(world)
        settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
        settle(world, 3000)
        for n in nodes(world):
            # '{"dragon_day2": 4}' names a scene that is not in the history: nothing is held and nothing is switched on
            assert held(n) == [] and n.fake.scene_struct("dragon_day2").can_repeat is False, (text, n.slot, held(n))
            assert n.fake.facts.get("mm_view") is None, "an unusable list is dropped"
            assert n.fake.items == {} and n.debug()["stats"]["silent"] == 0, "and nothing is paid for it"
        assert_clean(world)
    print("PASS: held scene: an unusable list of held scenes in a save is dropped without effect")


def test_view_gate_agrees_at_once():
    world = make_world(83, saves=view_saves(), loss=0.05, jitter=30)
    wait_ready(world)
    settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
    host, g1, g2 = nodes(world)
    assert "gate_trigger" in host.debug()["gate_scenes"] and "dragon_day2" in host.debug()["gate_scenes"]
    play(world, 1, "gate_trigger", 2)                           # a scene a world gate reads, started by an area
    settle(world, 6000)
    for n in (host, g2):
        assert "gate_trigger" in n.fake.history and n.fake.facts.get("cutscene_seen_gate_trigger") == 1.0, "the gate opens in every game"
        assert n.fake.would_start("gate_trigger") and n.fake.items == {}
    play(world, 0, "gate_trigger", 2)
    settle(world, 6000)
    assert host.fake.items == {"gate_gift": 1} and g1.fake.items == {"gate_gift": 1} and g2.fake.items == {}
    assert not host.fake.would_start("gate_trigger")
    assert_clean(world)
    print("PASS: held scene: the gate a scene opens agrees in every game at once, the scene itself is still offered")


def test_view_quest_waiting_for_the_scene():
    # A task of the quest "visions" waits for a cutscene (a quest query target): the game starts it when the quest is at that task.
    world = make_world(84, saves=view_saves(), loss=0.05, jitter=30)
    wait_ready(world)
    settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
    host, g1, g2 = nodes(world)
    g1.fake.hand_in("visions")                                   # task 0
    settle(world, 5000)
    assert all(stage_of(n, "visions") == 1 and n.fake.query_would_start("bridge_vision") for n in (host, g1, g2))
    play(world, 1, "bridge_vision", 2)                          # the guest watches it: the task is done, the quest moves on
    settle(world, 8000)
    assert stage_of(g1, "visions") == 2 and g1.fake.items == {"vision_token": 1}
    for n in (host, g2):
        assert stage_of(n, "visions") == 1, "held at the task that waits for the scene"
        assert n.fake.query_would_start("bridge_vision"), "the game can still start it"
        assert held(n) == ["bridge_vision"] and n.fake.items == {}
    play(world, 2, "bridge_vision", 2)
    settle(world, 6000)
    assert stage_of(g2, "visions") == 2 and stage_of(host, "visions") == 1 and held(host) == ["bridge_vision"]
    play(world, 0, "bridge_vision", 2)
    settle(world, 8000)
    for n in (host, g1, g2):
        assert stage_of(n, "visions") == 2 and n.fake.items == {"vision_token": 1} and held(n) == [], (n.slot, n.fake.items)
        assert n.fake.gold == 120 and n.fake.rewards == {"visions": 2}, (n.slot, n.fake.gold, n.fake.rewards)
        assert n.fake.views == {"bridge_vision": 1}
    assert_converged(world, "quest waiting for a scene")
    assert_clean(world)
    print("PASS: held scene: a quest task that waits for the scene stays at that task in the game that has not seen it")


def test_view_scene_that_starts_a_quest():
    saves = view_saves()
    world = make_world(85, saves=saves, loss=0.05, jitter=30)
    wait_ready(world)
    settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
    host, g1, g2 = nodes(world)
    play(world, 0, "chapter_intro", 2)                          # starts chapter_000
    host.fake.hand_in("chapter_000")
    settle(world, 8000)
    assert stage_of(host, "chapter_000") == "done"
    for n in (g1, g2):
        assert stage_of(n, "chapter_000") is None, "a quest the scene starts is not started or finished before the scene"
        assert held(n) == ["chapter_intro"] and n.fake.would_start("chapter_intro")
    play(world, 1, "chapter_intro", 2)
    settle(world, 8000)
    assert stage_of(g1, "chapter_000") == "done" and g1.fake.starts.count(("chapter_000", 0)) == 1
    assert stage_of(g2, "chapter_000") is None
    play(world, 2, "chapter_intro", 2)
    settle(world, 8000)
    for n in (host, g1, g2):
        assert stage_of(n, "chapter_000") == "done" and n.fake.starts.count(("chapter_000", 0)) == 1, (n.slot, n.fake.starts)
        assert n.fake.gold == 110 and n.fake.rewards == {"chapter_000": 1}, (n.slot, n.fake.gold, n.fake.rewards)
    assert_converged(world, "scene that starts a quest")
    assert_clean(world)
    print("PASS: held scene: a quest the scene starts is not started, finished or restarted behind the scene's back")


def test_view_night_scene():
    world = make_world(86, saves=view_saves(), loss=0.05, jitter=30)
    wait_ready(world)
    settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
    host, g1, g2 = nodes(world)
    play(world, 2, "night_scene", 2)
    settle(world, 6000)
    for n in (host, g1):
        assert n.fake.would_start("night_scene", sleeping=True) and not n.fake.would_start("night_scene"), "offered when the player sleeps"
        assert held(n) == ["night_scene"] and n.fake.removals == 1
    play(world, 0, "night_scene", 2)
    play(world, 1, "night_scene", 2)
    settle(world, 6000)
    assert all(n.fake.removals == 1 and n.fake.views == {"night_scene": 1} and held(n) == [] for n in (host, g1, g2))
    assert_clean(world)
    print("PASS: held scene: a scene played when the player sleeps is offered at night to the players who did not see it")


def test_view_falls_back_to_the_silent_route():
    # Scenes that cannot be shown safely are applied silently, as before, and the reason is logged. Played by the host.
    cases = [("manual_scene", "hand_gift", "nothing the game arms"), ("or_scene", "or_gift", "cannot be held"),
             ("unknown_stage_scene", "blind_gift", "stage nobody can tell"), ("repeat_scene", None, "repeats it anyway"),
             ("upgrade_the_saturday_market_plaza", None, "cannot be built twice"),
             ("inverted_scene", "inv_gift", "cannot be held"), ("fact_false_scene", "fact_gift", "cannot be held")]
    for scene, gift, reason in cases:
        world = make_world(87, saves=view_saves(), loss=0.05, jitter=30)
        wait_ready(world)
        settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
        host, g1, g2 = nodes(world)
        play(world, 0, scene, 2)
        settle(world, 8000)
        for n in (g1, g2):
            f = n.fake
            assert scene in f.history and held(n) == [] and f.views == {}, (scene, n.slot, held(n))
            assert (scene == "repeat_scene" or not f.would_start(scene)) and f.scene_struct(scene).can_repeat is (scene == "repeat_scene")
            if gift:
                assert f.items.get(gift) == 1, (scene, f.items)
            assert any(reason in why for why in n.debug()["why"].values()), (scene, n.debug()["why"])
        assert_converged(world, scene)
        assert_clean(world)
    # The story mode is off (the host's setting): a scene that needs it is never offered, so it is applied silently.
    world = make_world(88, saves=view_saves(), loss=0.05, jitter=30)
    wait_ready(world)
    settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
    host, g1, g2 = nodes(world)
    for n in (host, g1, g2):
        n.interp.globals["story_enabled"] = False
    play(world, 0, "story_mode_scene", 2)
    settle(world, 8000)
    assert all("story_mode_scene" in n.fake.history and held(n) == [] for n in (g1, g2))
    print("PASS: held scene: a scene that cannot be shown safely (hand-made trigger, unknown quest step, repeatable, ...) is applied silently, with the reason logged")


def test_view_player_ahead_of_the_scene():
    world = make_world(89, saves=view_saves(), loss=0.05, jitter=30)
    wait_ready(world)
    settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
    host, g1, g2 = nodes(world)
    world.net.partition(0, 2)
    g2.fake.active["dragon"]["current_stage"] = 1                # this player went on without the scene
    play(world, 0, "dragon_day2", 2)
    settle(world, 6000)
    world.net.partition(0, 2, False)
    settle(world, 14000)
    assert held(g1) == ["dragon_day2"]
    f = g2.fake
    assert "dragon_day2" in f.history and held(g2) == [] and not f.would_start("dragon_day2")
    assert f.items == {"scale": 1} and f.ari["free_baths"] == 1, "no scene to wait for: its gifts are paid at once"
    assert any("past the quest step" in why for why in g2.debug()["why"].values())
    assert_clean(world)
    print("PASS: held scene: a player who is already past the scene's quest step gets it silently instead of a second advance")


def test_view_nobody_waits_for_ever():
    world = make_world(90, saves=view_saves(), loss=0.05, jitter=30)
    wait_ready(world)
    settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
    host, g1, g2 = nodes(world)
    play(world, 1, "dragon_day2", 2)
    settle(world, 6000)
    assert held(host) == ["dragon_day2"] and stage_of(host, "dragon") == 0
    for f in (host.fake, g2.fake):
        f.day += 3
    settle(world, 3000)
    assert held(host) == ["dragon_day2"], "three days are not enough"
    for f in (host.fake, g2.fake):
        f.day += 5                                               # eight days since the scene was applied
    settle(world, 6000)
    for n in (host, g2):
        f = n.fake
        assert held(n) == [] and not f.would_start("dragon_day2") and f.scene_struct("dragon_day2").can_repeat is False
        assert f.items == {"scale": 1} and f.ari["free_baths"] == 1, "given up: the gifts are paid"
        assert stage_of(n, "dragon") == 1, "the quest is no longer held"
        assert f.gold == 110 and f.rewards == {"dragon": 1} and f.views == {}, (f.gold, f.rewards)
        assert any("not watched within" in why for why in n.debug()["why"].values())
    assert_converged(world, "patience")
    assert_clean(world)
    print("PASS: held scene: a scene nobody watches is given up after seven days; the quest and the gifts are released")


def test_view_scene_already_running_when_it_arrives():
    world = make_world(91, saves=view_saves(), loss=0.05, jitter=30)
    wait_ready(world)
    settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
    host, g1, g2 = nodes(world)
    g2.fake.scene_running = True                                 # the guest is watching it itself when the host's news arrives
    g2.fake.active_scene = "dragon_day2"
    world.run(1000)
    play(world, 0, "dragon_day2", 1)
    world.run(3000)
    assert "dragon_day2" not in g2.fake.history and held(g2) == [], "nothing is applied to a game while its scene runs"
    g2.fake.watch("dragon_day2")
    g2.fake.scene_running = False
    g2.fake.active_scene = None
    settle(world, 8000)
    assert views_of(g2) == {"dragon_day2": 1} and g2.fake.removals == 1 and g2.fake.items == {"scale": 1} and held(g2) == []
    assert stage_of(g2, "dragon") == 1 and g2.fake.gold == 110
    assert_held_in(g1, "dragon_day2", "dragon", 0)
    assert_clean(world)
    print("PASS: held scene: a player already in the scene when the news arrives sees it once and gets nothing twice")


def test_view_many_scenes_and_the_limit():
    # More scenes wait than the limit allows: the rest are applied silently. (Eight at most, so that no quest is held by a crowd.)
    for i in range(10):
        sf.SCENES["x_scene_%d" % i] = dict(target=sf.T_MAIN, trigger=True, items=[("x_gift_%d" % i, 1)])
        sf.WORLD_SCENES.add("x_scene_%d" % i)
    try:
        world = make_world(92, saves=view_saves(), loss=0.0)
        wait_ready(world)
        settle(world, 3000)                                          # a pass has run: the rewards ledger knows the starting levels
        host, g1, g2 = nodes(world)
        for i in range(10):
            play(world, 0, "x_scene_%d" % i, 1)
        settle(world, 25000)
        for n in (g1, g2):
            assert len(held(n)) == 8, held(n)
            silent = [i for i in range(10) if "x_scene_%d" % i not in held(n)]
            assert len(silent) == 2 and all(n.fake.items.get("x_gift_%d" % i) == 1 for i in silent), n.fake.items
            assert all("x_scene_%d" % i in n.fake.history for i in range(10))
        assert_clean(world)
    finally:
        for i in range(10):
            sf.SCENES.pop("x_scene_%d" % i, None)
            sf.WORLD_SCENES.discard("x_scene_%d" % i)
    print("PASS: held scene: at most eight scenes wait at a time; the rest are applied silently")



def test_view_record_replaced_and_world_left():
    world = make_world(93, saves=view_saves(), loss=0.05, jitter=30)
    wait_ready(world)
    settle(world, 3000)
    host, g1, g2 = nodes(world)
    play(world, 1, "dragon_day2", 2)
    settle(world, 6000)
    assert held(g2) == ["dragon_day2"] and g2.fake.scene_struct("dragon_day2").can_repeat is True
    # The progress record of an older save replaces the history (docs/SYNC-PROGRESS.md): the scene is no longer in it. Nothing
    # is paid for the scene that was held (it was not watched).
    g2.fake.history.remove("dragon_day2")
    settle(world, 3000)
    assert g2.fake.items == {} and g2.fake.ari["free_baths"] == 0 and g2.debug()["stats"]["silent"] == 0
    assert held(g2) == ["dragon_day2"], "the mirror still has the scene: it is held again, as for any game that has not seen it"
    # Leaving the world (a new event stream): the game's data is clean again for the next world.
    assert held(host) == ["dragon_day2"] and host.fake.scene_struct("dragon_day2").can_repeat is True
    host.call("__mistrimulti_story_reset", host.rt["story"])
    assert host.fake.scene_struct("dragon_day2").can_repeat is False and held(host) == []
    print("PASS: held scene: a record that no longer holds the scene pays nothing; leaving the world switches every scene off")


def test_view_requirements_the_mirror_cannot_break():
    # A scene that needs a world fact to be true (the mirror only makes facts true) can be held.
    world = make_world(94, saves=view_saves(), loss=0.05, jitter=30)
    wait_ready(world)
    settle(world, 3000)
    host, g1, g2 = nodes(world)
    play(world, 0, "fact_true_scene", 2)
    settle(world, 6000)
    assert held(g1) == ["fact_true_scene"] and held(g2) == ["fact_true_scene"], (held(g1), held(g2))
    play(world, 1, "fact_true_scene", 1)
    settle(world, 4000)
    assert held(g1) == [] and held(g2) == ["fact_true_scene"]
    assert_clean(world)
    print("PASS: held scene: a scene that needs a world fact to be true is held like any other")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    only = sys.argv[1:]
    for test in tests:
        if not only or test.__name__ in only:
            test()
