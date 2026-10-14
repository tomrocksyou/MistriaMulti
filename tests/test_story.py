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
from story_fake import (A, G, Npc, Fake, PRELUDE, default_save, WORLD_SCENES, FARM, HOME, TOWN, BEACH, NPC_COUNT,
                        ACT_READ, ACT_EAT)

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
        self.rt.update(enabled=True)
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
    world.run(seconds * SECOND)
    f.watch(scene)
    f.scene_running = False


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
        assert g.fake.gold == 100 and not g.fake.rewards, "mirrored progress gives no reward"
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
        assert host.fake.gold == 100 and g2.fake.gold == 100 and g1.fake.gold == 110, "only the player who handed in is paid"
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
        assert_clean(world)
    print("PASS: guest progress: the host takes the story step once, every game mirrors it, only the player is paid")


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
    assert g1.fake.gold == 110 and not g1.fake.rewards.get("bridge")
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
    assert not g1.fake.rewards and g1.fake.gold == 100
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
    for slot, schedule in zip(sorted(world.games), schedules):
        world.games[slot].node.fake.new_day(schedule)


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


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    only = sys.argv[1:]
    for test in tests:
        if not only or test.__name__ in only:
            test()
