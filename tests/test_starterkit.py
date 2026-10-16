"""The starter kit of a new character (MistriMultiStory.gml mistrimulti_story_kit_*, wired into MistriMultiProgress.gml and
MistriMultiPlayerData.gml).

    python3 tests/test_starterkit.py            # about 20 seconds; name tests to run only those

The finding: a new guest character in a world that was already started never got the first hoe and seeds, because the game
hands them out in a first-day scene that the host had run (the scene is in the host's history, which the new character's copy of
the world inherits), so the scene never played again for the guest and the story sync's "a new character is not owed the past"
rule paid nothing. The kit gives the guest what those scenes give, read from the game's data, once.

The real MistriMultiStory.gml (kit, pump), MistriMultiProgress.gml, MistriMultiPlayerSync.gml and MistriMultiCharacter.gml run
on the event layer with tests/test_guestchar.py's faked game and editor; this file adds the game's cutscene table, an inventory
(`ARI.bag`: item -> count, which the player record stand-in carries), the give function and the popup queue. The real
`mistrimulti_player_fresh` needs the engine's inventory classes and cannot run here; its stand-in sets the same flag, and a source
check ties the real one to it. The scene names and the items they give are invented: the real ones are in the game's data files,
which the scripts do not contain (docs/SYNC-STORY.md, "Starter kit").
"""
import json
import re
import sys
from pathlib import Path

import gml_subset as gml
from gml_subset import GArray, GStruct
import test_guestchar as G
import test_progress as P
from test_progress import ALICE, no_errors

ROOT = Path(__file__).resolve().parent.parent
GML_DIR = ROOT / "mod/mistrimulti/gml"

PRELUDE = "#macro STORY_ENABLED global.story_enabled\n"

# scene -> (items, baths, spell, mana, tutorial, requires_story_mode)
SCENES = {
    "prologue": dict(),
    "day_zero": dict(mana=12),
    "farm_introduction": dict(items=[("hoe", 1), ("watering_can", 1), ("turnip_seeds", 15)], baths=1, tutorial=0, spell=2),
    "adeline_quest_board": dict(items=[("board_letter", 1)]),
    "dragon_day2": dict(items=[("dragon_scale", 1)]),
    "story_only": dict(items=[("story_gift", 1)], story_mode=True),
}
FIRST_DAY = ["prologue", "day_zero", "farm_introduction"]       # what the host's first day left in the history of the world

FRESH = """
function mistrimulti_player_fresh() {
    var r = __mistrimulti_runtime();
    r.kit_owed = true;
    ARI.bag = { lunch: 1 };
    ARI.free_baths = 0;
    ARI.gold = 0;
    for (var i = 0; i < NpcId.LEN; i++) {
        NPCS[i].heart_points = 0;
        T2R.write(npc_id_to_string(i) + "_status", "undefined");
    }
    mistrimulti_progress_core_ready();
}

function mistrimulti_player_capture() {
    var r = __mistrimulti_runtime();
    var relations = [];
    for (var i = 0; i < NpcId.LEN; i++) {
        array_push(relations, { hearts: NPCS[i].heart_points, status: T2R.read(npc_id_to_string(i) + "_status") ?? "undefined" });
    }
    return { v: 1, uid: r.uid, world: r.world_key, day: string(CALENDAR.time), gold: ARI.gold, relations: relations,
        bag: clone_value(ARI.bag), baths: ARI.free_baths,
        character: { name: string(ARI.name), look: ARI.animation_assets().serialize() } };
}

function mistrimulti_player_restore(data) {
    var r = __mistrimulti_runtime();
    if (!mistrimulti_player_valid(data, r.uid, r.world_key)) return false;
    ARI.gold = data.gold;
    ARI.name = data.character.name;
    ARI.bag = clone_value(data.bag);
    ARI.free_baths = data.baths;
    for (var i = 0; i < NpcId.LEN; i++) {
        NPCS[i].heart_points = data.relations[i].hearts;
        T2R.write(npc_id_to_string(i) + "_status", data.relations[i].status);
    }
    r.character_owner = ARI;
    r.character_pending = false;
    r.character_phase = "done";
    r.character_loaded = true;
    mistrimulti_progress_core_ready();
    return true;
}
"""


class KitNode(G.CharNode):
    extra_files = G.CharNode.extra_files + ("MistriMultiStory.gml",)
    prelude = (PRELUDE,)
    history = FIRST_DAY            # the scenes the host's world already holds when this game starts

    def builtins(self):
        b = super().builtins()
        e = self.engine
        self.give_fails = False
        self.gives = 0
        self.popups = []
        self.scenes = {name: self.scene(name, d) for name, d in SCENES.items()}
        e.ari.update(bag=GStruct({"hoe_of_the_host": 1}), free_baths=0, mana_max=10, learn_spell=lambda s: e.calls.append(("spell", s)),
                     set_mana=lambda v: e.calls.append(("mana", v)))
        for name in self.history:
            e.mist["scene_history"]["insert"](name)
            e.facts["cutscene_seen_" + name] = 1.0
        b.update({
            "CUTSCENES": GStruct(contains_key=lambda n: n in self.scenes, get=lambda n: self.scenes[n]),
            "mist_give_items_after_scene": self.give, "player_wake_position": lambda: GStruct(location_id=1),
            "await_popup": lambda fn, args: self.popups.append(list(args)), "spawn_tutorial": lambda t: None,
            "create_notification": lambda *a: None,
        })
        return b

    def scene(self, name, d):
        items = GArray(GStruct(item_id=n, quantity=q) for n, q in d.get("items", []))
        return GStruct(given_items=items, baths=d.get("baths", 0), spell_to_unlock=d.get("spell"), mana_to_set=d.get("mana"),
                       post_scene_tutorial=d.get("tutorial"), requires_story_mode=d.get("story_mode", False))

    def give(self, items, position):
        self.gives += 1
        if self.give_fails:
            self.give_fails -= 1
            raise gml.GmlError("the pockets are full")
        bag = self.engine.ari["bag"]
        for item in items:
            bag[item["item_id"]] = bag.get(item["item_id"], 0) + item["quantity"]

    def setup(self):
        super().setup()
        self.interp.globals["story_enabled"] = True
        self.interp.load(FRESH, "kit stand-ins")

    @property
    def bag(self):
        return dict(self.engine.ari["bag"])

    @property
    def ledger(self):
        text = self.engine.facts.get("mm_kit")
        return None if text is None else json.loads(text)

    def pump(self):
        self.interp.call("__mistrimulti_story_kit_pump", self.rt)


KIT = {"lunch": 1, "hoe": 1, "watering_can": 1, "turnip_seeds": 15}


def make_world(seed, history=None, guests=1, **faults):
    P.FILESYSTEMS.clear()
    P.ENGINES.clear()
    P.UIDS.clear()
    P.UIDS[1], P.UIDS[2], P.UIDS[3] = ALICE, P.BOB, P.CAROL
    node = type("Node", (KitNode,), {"history": history if history is not None else FIRST_DAY})
    world = G.World(seed, {i: node for i in range(guests + 1)}, **faults)
    for game in world.games.values():
        game.feature = G.CharDriver(game)
    return world


def join(seed, entry="new", name="Alice the first", history=None, **faults):
    """A host and a guest who joins a world it has no character in, and makes one."""
    world = make_world(seed, history, **faults)
    host, alice = world.games[0].node, world.games[1].node
    alice.rt["character_entry"] = entry
    G.run_until(world, lambda: alice.rt["player_ready"], 30000, "the guest's records are in")
    G.finish(world, alice, name)
    return world, host, alice


def restart(world, entry):
    return G.restart(world, 1, entry)


def stored_kit(host):
    record = G.host_file(host, ".progress.json")
    return record["data"]["sections"]["story_rewards"].get("kit")


# ---- tests --------------------------------------------------------------------------------------------------------------------

def test_new_guest_gets_the_kit():
    """The finding: the host's first day is over, a new guest walks out and has tools and seeds, once, as the game gives them."""
    world, host, alice = join(1)
    assert alice.bag == {**KIT} and alice.engine.ari["free_baths"] == 1, ("tools, seeds, the scene's bath", alice.bag)
    assert "hoe_of_the_host" not in alice.bag, "the host's own items are not the guest's"
    assert "board_letter" not in alice.bag and "dragon_scale" not in alice.bag, "scenes the first day did not run, and the later story, are not part of it"
    assert alice.ledger == FIRST_DAY, alice.ledger
    assert ("spell", 2) in alice.engine.calls and ("mana", 12) in alice.engine.calls, alice.engine.calls
    assert alice.gives == 1
    assert G.host_file(host, ".json")["data"]["bag"] == KIT, "the inventory reaches the host's record"
    assert stored_kit(host) == FIRST_DAY, "and the ledger reaches the host's progress record"
    assert host.bag == {"hoe_of_the_host": 1} and host.gives == 0, "the host is not touched"
    no_errors(world)
    print("PASS: a new guest character in a started world gets the first tools, seeds and the scene's bath, spell and mana, once")


def test_tutorial_after_the_editor():
    world = make_world(2)
    alice = world.games[1].node
    alice.rt["character_entry"] = "new"
    G.run_until(world, lambda: alice.rt["player_ready"], 30000, "ready")
    G.run_until(world, lambda: alice.editor is not None, 30000, "the editor")
    alice.pump()
    assert alice.popups == [] and list(alice.rt["kit_tutorials"]) == [0], "the popup waits for the editor"
    G.finish(world, alice, "Alice")
    alice.pump()
    assert [list(p) for p in alice.popups] == [[0]] and list(alice.rt["kit_tutorials"]) == []
    alice.pump()
    assert [list(p) for p in alice.popups] == [[0]], "shown once"
    # A tutorial the player has seen is not shown again.
    alice.rt["kit_tutorials"] = [0]
    alice.engine.ari["tutorials_seen"][0] = True
    alice.pump()
    assert [list(p) for p in alice.popups] == [[0]]
    print("PASS: the scene's tutorial popup comes once, after the editor, and not when it was seen")


def test_later_day_and_other_worlds():
    # The world is well on: the host's history also holds later story. Only the first-day scenes are the kit.
    world, host, alice = join(3, history=FIRST_DAY + ["adeline_quest_board", "dragon_day2"])
    assert alice.bag == {**KIT, "board_letter": 1} and "dragon_scale" not in alice.bag, alice.bag
    assert alice.ledger == FIRST_DAY + ["adeline_quest_board"]
    # A host that has not run the first day yet: nothing is owed, the game or the story sync gives it when the scene comes.
    world, host, alice = join(4, history=[])
    assert alice.bag == {"lunch": 1} and alice.ledger == [], (alice.bag, alice.ledger)
    assert stored_kit(host) == [], "the ledger says the kit was settled, with nothing in it"
    alice = restart(world, "load")
    G.run_until(world, lambda: alice.rt["player_ready"], 30000, "back")
    world.run(2000)
    assert alice.bag == {"lunch": 1} and alice.gives == 0
    # A scene that needs the story mode is skipped when the story is off.
    world = make_world(5, history=FIRST_DAY + ["adeline_quest_board"])
    alice = world.games[1].node
    alice.scenes["adeline_quest_board"]["requires_story_mode"] = True
    alice.interp.globals["story_enabled"] = False
    alice.rt["character_entry"] = "new"
    G.run_until(world, lambda: alice.rt["player_ready"], 30000, "ready")
    assert alice.ledger == FIRST_DAY and "board_letter" not in alice.bag
    print("PASS: the kit is the first-day scenes only, on any day; a host that is not there yet owes nothing; the story mode is respected")


def test_rejoin_gets_nothing():
    world, host, alice = join(6)
    alice.engine.ari["bag"]["turnip_seeds"] = 9          # the guest planted some
    world.run(9000)
    before = G.host_file(host, ".json")
    for entry in ("load", "load", "new"):
        alice = restart(world, entry)
        if entry == "new":
            G.run_until(world, lambda: alice.question() is not None, 30000, "the question")
            alice.question().tap("Keep mine")
        G.run_until(world, lambda: alice.rt["player_ready"], 30000, "ready")
        world.run(3000)
        assert alice.bag == {**KIT, "turnip_seeds": 9} and alice.gives == 0 and alice.engine.ari["free_baths"] == 1, (entry, alice.bag)
        assert alice.ledger == FIRST_DAY, 1
        assert len(alice.rt["kit_tutorials"]) == 0, 2
        assert alice.popups == [], (entry, alice.ledger, alice.rt["kit_tutorials"], alice.popups)
        assert alice.rt["kit_owed"] is False
    no_errors(world)
    print("PASS: Load Game, a second join and 'Keep mine' restore the record and give nothing again")


def test_new_character_gets_the_kit_again():
    world, host, alice = join(7)
    alice.engine.ari["bag"]["turnip_seeds"] = 0          # all planted, the hoe sold
    del alice.engine.ari["bag"]["hoe"]
    world.run(9000)
    alice = restart(world, "new")
    G.run_until(world, lambda: alice.question() is not None, 30000, "the question")
    alice.question().tap("New character")
    G.run_until(world, lambda: alice.editor is not None, 30000, "the editor")
    assert alice.bag == KIT and alice.ledger == FIRST_DAY and alice.engine.ari["free_baths"] == 1, alice.bag
    G.finish(world, alice, "Alice the second")
    assert G.host_file(host, ".json")["data"]["bag"] == KIT and stored_kit(host) == FIRST_DAY
    old = G.host_file(host, ".replaced.json")
    assert old["data"]["bag"] == {"lunch": 1, "watering_can": 1, "turnip_seeds": 0}, "the old character is kept aside"
    # And the new one is the one that comes back, without a third kit.
    alice = restart(world, "load")
    G.run_until(world, lambda: alice.rt["player_ready"], 30000, "back")
    world.run(2000)
    assert alice.bag == KIT and alice.gives == 0
    no_errors(world)
    print("PASS: a guest who picks 'New character' gets the kit again; the character that replaces it is not given a third")


def test_records_without_a_kit_are_left_alone():
    # A world from before the kit: the character has a progress record without the ledger. It is an old character; no kit.
    world, host, alice = join(8)
    path = "data/worlds/" + P.WORLD + "/players/" + ALICE.replace(":", "_") + ".progress.json"
    record = json.loads(host.fs.files[path])
    del record["data"]["sections"]["story_rewards"]["kit"]
    host.fs.files[path] = json.dumps(record)
    world.run(9000)
    alice = restart(world, "load")
    G.run_until(world, lambda: alice.rt["player_ready"], 30000, "back")
    world.run(3000)
    assert alice.gives == 0 and alice.bag == KIT and alice.ledger is None, alice.ledger
    # The core record without any progress record (the progress file was lost): an old character's inventory is not topped up.
    world, host, alice = join(9)
    for suffix in ("", ".bak", ".tmp"):
        host.fs.files.pop("data/worlds/" + P.WORLD + "/players/" + ALICE.replace(":", "_") + ".progress.json" + suffix, None)
    alice.engine.ari["bag"].pop("hoe")
    world.run(9000)
    alice = restart(world, "load")
    G.run_until(world, lambda: alice.rt["player_ready"], 30000, "back")
    world.run(3000)
    assert alice.gives == 0 and "hoe" not in alice.bag and alice.rt["kit_owed"] is False and alice.ledger is None, (alice.bag, alice.ledger)
    print("PASS: a record from before the kit, or a core record without progress, is an old character: nothing is given")


def test_failures_are_contained():
    # A gift that fails is logged and not retried: the ledger moved first.
    world = make_world(10, history=FIRST_DAY + ["adeline_quest_board"])
    alice = world.games[1].node
    alice.give_fails = 1                     # the first scene's gift fails, the next scene's is still given
    alice.rt["character_entry"] = "new"
    G.run_until(world, lambda: alice.rt["player_ready"], 30000, "ready")
    assert alice.bag == {"lunch": 1, "board_letter": 1} and alice.ledger == FIRST_DAY + ["adeline_quest_board"] and alice.gives == 2, alice.bag
    assert any("could not be given" in str(w) for w in world.games[1].warnings), world.games[1].warnings
    G.finish(world, alice, "Alice")
    world.run(9000)
    assert alice.gives == 2 and alice.bag == {"lunch": 1, "board_letter": 1}, "never retried (it might have been half given)"
    # A scene whose spell cannot be learned does not stop the scenes after it.
    world = make_world(14, history=FIRST_DAY + ["adeline_quest_board"])
    alice = world.games[1].node
    alice.engine.ari["learn_spell"] = lambda s: (_ for _ in ()).throw(gml.GmlError("no such spell"))
    alice.rt["character_entry"] = "new"
    G.run_until(world, lambda: alice.rt["player_ready"], 30000, "ready")
    assert alice.bag == {**KIT, "board_letter": 1}, alice.bag
    assert any("starter kit of scene farm_introduction could not be given" in str(w) for w in world.games[1].warnings)
    # The ledger fact makes the grant idempotent even if the flag were raised twice.
    alice.rt["kit_owed"] = True
    alice.interp.call("mistrimulti_story_kit_grant")
    assert alice.gives == 2
    # A scene the game does not know any more, or no scene table at all, breaks nothing.
    world = make_world(11)
    alice = world.games[1].node
    alice.scenes.pop("farm_introduction")
    alice.rt["character_entry"] = "new"
    G.run_until(world, lambda: alice.rt["player_ready"], 30000, "ready")
    assert alice.ledger == ["prologue", "day_zero"] and alice.bag == {"lunch": 1}
    world = make_world(12)
    alice = world.games[1].node
    alice.interp.builtins["CUTSCENES"] = GStruct(contains_key=lambda n: (_ for _ in ()).throw(gml.GmlError("no table")), get=None)
    alice.rt["character_entry"] = "new"
    G.run_until(world, lambda: alice.rt["player_ready"], 30000, "ready")
    assert alice.rt["kit_owed"] is False and alice.bag == {"lunch": 1}
    assert any("starter kit could not be given" in str(w) for w in world.games[1].warnings)
    no_errors(world)
    print("PASS: a failing gift, an unknown scene and unreadable data are contained and never retried")


def test_record_validation():
    world = make_world(13)
    node = world.games[1].node

    def valid(value):
        return node.call("mistrimulti_progress_section_valid", "story_rewards", node.data({"init": True, "paid": {}, **value}))
    assert valid({}) and valid({"kit": []}) and valid({"kit": ["farm_introduction", "day_zero"]})
    assert not valid({"kit": "farm_introduction"}) and not valid({"kit": {"a": 1}}) and not valid({"kit": [1]})
    assert not valid({"kit": ["x"] * 17}) and not valid({"kit": ["x" * 97]}) and not valid({"kit": [""]})
    print("PASS: the kit ledger in a record is validated (list of at most 16 names)")


def test_wiring():
    """The real PlayerData and tick files carry the flag and the pump (their engine parts cannot run here)."""
    data = (GML_DIR / "MistriMultiPlayerData.gml").read_text()
    fresh = data[data.index("function mistrimulti_player_fresh()"):]
    fresh = fresh[:fresh.index("\n}\n")]
    assert "r.kit_owed = true;" in fresh, "a new character raises the flag"
    assert "kit_owed" not in data[:data.index("function mistrimulti_player_fresh()")] and "kit_owed" not in data[data.index("function mistrimulti_player_fresh()") + len(fresh):], \
        "only a new character raises it (not a restore)"
    story = (GML_DIR / "MistriMultiStory.gml").read_text()
    tick = story[story.index("function mistrimulti_story_tick()"):]
    tick = tick[:tick.index("\n}\n")]
    assert 'if (r.mode == "join") __mistrimulti_story_kit_pump(r);' in tick
    progress = (GML_DIR / "MistriMultiProgress.gml").read_text()
    fresh = progress[progress.index("function mistrimulti_progress_fresh()"):]
    fresh = fresh[:fresh.index("\n}\n")]
    assert fresh.index("mistrimulti_progress_restore(") < fresh.index("mistrimulti_story_kit_grant()"), "the kit comes after the defaults wipe the ledger"
    assert 'r[$ "kit_owed"] == true' in fresh and "r.kit_owed = false;" in fresh
    reset = progress[progress.index("function mistrimulti_progress_reset_session()"):]
    assert "r.kit_owed = false;" in reset[:reset.index("\n}\n")], "a new session starts without the flag"
    assert 'T2R.write("mm_kit", is_array(v[$ "kit"])' in progress, "a restored record replaces the ledger (an old one has none)"
    assert "mistrimulti_story_kit_scenes" in story and '"farm_introduction"' in story
    manifest = (ROOT / "mod/mistrimulti/manifest.toml").read_text()
    assert "await_popup" not in manifest and "spawn_tutorial" not in manifest, "no new hook is needed"
    print("PASS: wiring: the flag, the order in the progress start, the pump in the story tick, the ledger in the record")


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    only = sys.argv[1:]
    for test in tests:
        if not only or test.__name__ in only:
            test()
    print("ALL PASS")


if __name__ == "__main__":
    main()
