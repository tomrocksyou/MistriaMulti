"""The host's developer command "unlock the mines" (MistriMultiDevTools.gml), running the real GML on the story sync.

    python3 tests/test_devtools.py [test_name ...]

MistriMultiDevTools.gml and MistriMultiStory.gml run unmodified in tests/gml_subset.py on the event layer, over the simulated
helpers and lossy network of tests/event_sim.py, with the stand-in game of tests/story_fake.py extended by what the command
touches: an alias requirement `OpenedMines` (cutscenes, a world fact, a quest, an item, an "or" group and a nested alias),
`fulfill_requirement`, `requirements_pass` and `setup_room`. Only the engine is faked. The real alias is game data that is not
in the game's scripts, so this checks the mechanism (who may run it, nothing paid twice, everybody follows, parts it does not
understand are left alone), not that the real game opens its mines: docs/DEVTOOLS.md lists what must be checked in the game.
"""
import copy
import pathlib
import sys

from event_sim import GmlNode, World
import gml_subset as gml
import story_fake as sf
from story_fake import A, G, default_save
from test_story import StoryNode, Driver, nodes, settle, wait_ready, restart, assert_clean

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOOT = ROOT / "mod/mistrimulti/gml/MistriMultiBoot.gml"

# ---- the extra game data -----------------------------------------------------------------------------------------
R_MINES, R_QUEST, R_ITEM_REQ, R_NESTED = 8, 9, 10, 11
sf.ENUMS["Requirement"] = G({**sf.ENUMS["Requirement"], "OpenedMines": R_MINES, "CompletedQuest": R_QUEST, "HasItem": R_ITEM_REQ,
                             "Nested": R_NESTED})
sf.ENUMS["LocationId"] = G(**sf.ENUMS["LocationId"], Dungeon=9)
sf.SCENES["mines_letter"] = dict(target=sf.T_MAIN, removals=1)
sf.SCENES["mines_open"] = dict(target=sf.T_MAIN, removals=1, items=[("pickaxe_gift", 1)])
sf.SCENES["mines_nested"] = dict(target=sf.T_GENERAL)        # only the gate (the alias) says this one is the world's
sf.QUEST_DEFS["mines_quest"] = dict(cat=sf.STORY, tasks=2)
MINES_SCENES = ["mines_letter", "mines_open", "mines_nested"]


class DevNode(StoryNode):
    extra_files = ("MistriMultiStory.gml", "MistriMultiDevTools.gml")
    unfulfillable = False                 # the alias also asks for something the command does not know how to bring about

    def builtins(self):
        out = super().builtins()
        f = self.fake
        f.fulfilled, f.setups, f.pickaxe_asked = [], 0, 0
        f.fail_fulfill = False
        aliases = out["REQUIREMENT_ALIASES"]
        main = A([None] * sf.R_LEN)
        main[sf.R_SEEN] = A(["mines_letter", "mines_open"])
        main[sf.R_FACT] = A([A(["mines_gate", True])])
        main[R_QUEST] = A(["mines_quest"])
        main[R_ITEM_REQ] = A([A(["pickaxe", 1])])             # HasItem: never to be handed out by the command
        main[sf.R_OR] = A([A([None] * sf.R_LEN)])
        main[R_NESTED] = True
        main[sf.R_INVERT] = False
        nested = A([None] * sf.R_LEN)
        nested[sf.R_SEEN] = A(["mines_nested"])
        aliases[R_MINES] = main
        aliases[R_NESTED] = nested

        def fulfill(i, req):
            if f.fail_fulfill:
                raise gml.GmlError("fulfill_requirement exploded")
            f.fulfilled.append((int(i), list(req)))
            if i == sf.R_SEEN:
                for name in req:                              # MIST.mark_scene_has_played + trigger_scene_object_removals
                    if name not in f.history:
                        f.history.append(name)
                        f.facts["cutscene_seen_" + name] = 1.0
                    f.removals += sf.SCENES[name].get("removals", 0)
            elif i == sf.R_FACT:
                for name, value in req:
                    f.facts[name] = value
            elif i == R_ITEM_REQ:
                f.pickaxe_asked += 1
            else:
                raise gml.GmlError("fulfill_requirement: cannot progress %d" % i)

        def passes(i):
            if i != R_MINES:
                return True
            return (all(s in f.history for s in MINES_SCENES) and f.facts.get("mines_gate") is True
                    and "mines_quest" in f.completed and not self.unfulfillable)

        def setup_room():
            f.setups += 1

        out.update({
            "Requirement": sf.ENUMS["Requirement"], "LocationId": sf.ENUMS["LocationId"],
            "fulfill_requirement": fulfill, "requirements_pass": passes, "setup_room": setup_room,
            "requirement_to_string": lambda i: "requirement_%d" % int(i),
            "mmapi_log_flush": lambda *a: None,
        })
        return out

    def unlock(self):
        return self.interp.call("mistrimulti_devtools_unlock_mines")


def make_world(seed, guests=2, **faults):
    saves = {}
    for slot in range(guests + 1):
        save = default_save()
        save["quests"]["mines_quest"] = 0
        saves[slot] = save
    impls = {i: (lambda slot, epoch, clock, log: DevNode(slot, epoch, clock, log, saves)) for i in range(guests + 1)}
    world = World(seed, impls, **faults)
    world.saves = saves
    for game in world.games.values():
        game.feature = Driver(game)
    return world


def world_has_mines(node):
    f = node.fake
    return (all(s in f.history for s in MINES_SCENES) and f.facts.get("mines_gate") is True and f.level("mines_quest") == "done")


def snapshot(node):
    f = node.fake
    return (list(f.history), dict(f.facts), list(f.completed), f.gold, dict(f.items), list(f.fulfilled), f.removals)


# ---- tests -----------------------------------------------------------------------------------------------------------

def test_host_unlocks_and_everyone_follows():
    world = make_world(1, loss=0.05, dup=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    result = host.unlock()
    # Three cutscenes (two named, one through the nested alias), one fact, one quest.
    assert result["ok"] is True and result["open"] is True and result["changed"] == 5, result
    assert "Mines unlocked" in result["text"] and result["text"] in host.fake.notes, "the host is told what happened"
    assert world_has_mines(host) and host.fake.setups == 1, "the host's own room is refreshed"
    # Brought about with the game's own functions, and only the parts it understands: no item, no gold, nothing from the "or" group.
    assert sorted(i for i, _ in host.fake.fulfilled) == [sf.R_SEEN] * 3 + [sf.R_FACT], host.fake.fulfilled
    assert host.fake.pickaxe_asked == 0 and host.fake.items == {} and host.fake.gold == 100, "the host is paid nothing"
    assert set(result["skipped"]) == {"requirement_%d" % R_ITEM_REQ, "requirement_%d" % sf.R_OR}, result
    settle(world, 8000)
    for g in (g1, g2):
        assert world_has_mines(g), (g.slot, g.fake.history, g.fake.facts, g.fake.completed)
        assert g.fake.removals == 2, "the blockers of the two scenes that remove objects are removed in this game too"
        assert g.fake.fulfilled == [], "a guest's game is changed by the story sync, never by the command"
        assert g.fake.items == {"pickaxe_gift": 1}, g.fake.items               # the scene's own gift, once
        assert g.fake.gold == 120, g.fake.gold                                # the quest's two tasks, once (the story sync's ledger)
        assert all(v == 1 for v in g.fake.granted.values()), g.fake.granted
    assert host.fake.gold == 100 and host.fake.items == {}
    assert_clean(world)
    print("PASS: the host unlocks the mines; every guest's game follows through the story sync, rewards given once")


def test_second_press_changes_nothing():
    world = make_world(2, loss=0.05, jitter=30)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    host.unlock()
    settle(world, 8000)
    before = [snapshot(n) for n in (host, g1, g2)]
    again = host.unlock()
    settle(world, 8000)
    assert again["ok"] is True and again["changed"] == 0 and "already" in again["text"], again
    assert [snapshot(n) for n in (host, g1, g2)] == before, "pressing again hands out and changes nothing"
    assert host.fake.setups == 1
    assert_clean(world)
    print("PASS: a second press changes nothing and says the mines are already open")


def test_guest_cannot():
    world = make_world(3, loss=0.0)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    settle(world, 4000)                            # the games settle their own bookkeeping first (reward ledger)
    before = [snapshot(n) for n in (host, g1, g2)]
    for g in (g1, g2):
        result = g.unlock()
        assert result["ok"] is False and result["changed"] == 0 and "host" in result["text"].lower(), result
        assert result["text"] in g.fake.notes
    # Even a guest whose runtime claims to be the host is refused unless it is player 0.
    g1.rt["mode"] = "host"
    assert g1.unlock()["ok"] is False
    g1.rt["mode"] = "join"
    g2.rt["id"] = 0
    assert g2.unlock()["ok"] is False
    g2.rt["id"] = 2
    settle(world, 8000)
    assert [snapshot(n) for n in (host, g1, g2)] == before, "nothing changed anywhere"
    assert not any(world_has_mines(n) for n in (host, g1, g2))
    assert_clean(world)
    print("PASS: a guest cannot unlock the mines, however it asks")


def test_refused_when_not_safe():
    world = make_world(4, loss=0.0)
    host, g1, g2 = nodes(world)
    # Before the story sync holds the world (nothing is read yet): no.
    early = host.unlock()
    assert early["ok"] is False and early["changed"] == 0 and "not ready" in early["text"], early
    wait_ready(world)
    host.fake.scene_running = True
    during = host.unlock()
    assert during["ok"] is False and "cutscene" in during["text"] and host.fake.fulfilled == [], during
    host.fake.scene_running = False
    host.fake.ari["end_of_day_status"] = 1
    assert host.unlock()["ok"] is False and host.fake.fulfilled == []
    host.fake.ari["end_of_day_status"] = None
    host.rt["enabled"] = False
    assert host.unlock()["ok"] is False
    host.rt["enabled"] = True
    assert host.unlock()["ok"] is True
    print("PASS: refused before the story sync is ready, during a cutscene, at the end of the day, and with multiplayer off")


def test_parts_it_does_not_know_are_left_alone():
    world = make_world(5, loss=0.0)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    host.unfulfillable = True                    # the real alias also needs something the command does not bring about
    result = host.unlock()
    assert result["ok"] is False and result["open"] is False and result["changed"] == 5, result
    assert "still report as locked" in result["text"] and len(result["skipped"]) == 2, result
    assert host.fake.pickaxe_asked == 0 and host.fake.items == {} and host.fake.gold == 100
    settle(world, 8000)
    assert world_has_mines(g1) and world_has_mines(g2), "what could be done is still shared"
    print("PASS: parts of the alias the command does not understand are reported and never handed out")


def test_late_joiner_and_lossy_network():
    world = make_world(6, guests=3, loss=0.1, dup=0.1, jitter=40)
    world.net.partition(0, 3)
    wait_ready(world, skip=3)
    host, g1, g2, g3 = nodes(world)
    host.unlock()
    settle(world, 8000)
    assert world_has_mines(g1) and world_has_mines(g2) and not world_has_mines(g3)
    world.net.partition(0, 3, False)
    settle(world, 14000)
    assert world_has_mines(g3), (g3.fake.history, g3.fake.facts, g3.fake.completed)
    # The scene's gift is given once; the quest's gold is not (the story sync's rule: a game that first sees the story only
    # after it happened is not owed the steps that came before it, docs/SYNC-STORY.md).
    assert g3.fake.items == {"pickaxe_gift": 1} and g3.fake.gold == 100, (g3.fake.items, g3.fake.gold)
    assert_clean(world)
    print("PASS: a game that was away gets the unlocked mines when it returns, rewards once")


def test_guest_restart_keeps_the_mines():
    world = make_world(7, loss=0.0)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    host.unlock()
    settle(world, 8000)
    world.saves[1] = copy.deepcopy(world.saves[1])                 # the guest's old save knows nothing of it
    restart(world, 1)
    settle(world, 14000)
    again = world.games[1].node
    assert world_has_mines(again), (again.fake.history, again.fake.facts)
    print("PASS: a guest that restarts from an older save is brought up to the unlocked mines")


def test_failure_is_contained():
    world = make_world(8, loss=0.0)
    wait_ready(world)
    host, g1, g2 = nodes(world)
    host.fake.fail_fulfill = True
    result = host.unlock()                         # must not raise
    assert result["ok"] is False and "failed" in result["text"] and result["text"] in host.fake.notes, result
    host.fake.fail_fulfill = False
    assert host.unlock()["ok"] is True, "and the command can be pressed again afterwards"
    print("PASS: an engine failure inside the command is contained, reported, and does not block a retry")


def test_registered_for_debug_and_hotkey():
    boot = BOOT.read_text(encoding="utf-8")
    assert 'mmapi_debug_register_fn("mistrimulti.unlock_mines", mistrimulti_devtools_unlock_mines, { mod_name: "mistrimulti" });' in boot
    assert 'mmapi_hotkey_binding_from_name("CONTROL+F6")' in boot and "mistrimulti_devtools_hotkey_unlock_mines" in boot
    # the registration sits in the debug-only block and the hotkey is not already used by another binding
    debug_block = boot[boot.index("if (global.__mistrimulti_debug_on) {"):boot.index("mmapi_log_info(\"mistrimulti\", \"MistriaMulti")]
    assert "mistrimulti.unlock_mines" in debug_block
    assert boot.count('"CONTROL+F6"') == 1 and '"F6"' not in boot
    world = make_world(9, loss=0.0)
    wait_ready(world)
    host = nodes(world)[0]
    host.interp.call("mistrimulti_devtools_hotkey_unlock_mines")
    assert world_has_mines(host) and any("Mines unlocked" in n for n in host.fake.notes)
    print("PASS: the debug function and the CONTROL+F6 hotkey are registered and run the command")


def test_gml_files_parse():
    # MistriMultiDevTools.gml also has to load on its own next to the whole mod, like every file (tests/test_event_layer.py).
    interp = gml.Interpreter({})
    interp.load((ROOT / "mod/mistrimulti/gml/MistriMultiDevTools.gml").read_text(encoding="utf-8"), "MistriMultiDevTools.gml")
    print("PASS: MistriMultiDevTools.gml parses")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    only = sys.argv[1:]
    for test in tests:
        if not only or test.__name__ in only:
            test()
