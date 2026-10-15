"""Per-player progress (MistriMultiProgress.gml): records, sync, host save commit, one partner per NPC.

    python3 tests/test_progress.py

MistriMultiProgress.gml, MistriMultiPlayerSync.gml, MistriMultiPlayerData.gml (its file storage and path functions) and
MistriMultiIdentity.gml run unmodified in tests/gml_subset.py on top of MistriMultiEvents.gml, over the simulated helpers and
network of tests/event_sim.py. Only the game is faked: a small engine (items, NPCs, quests, mail, ... with the data structures
the game's own save code uses), a file system that can fail, and a stand-in for the engine-bound core record (gold and
relationships) in place of MistriMultiPlayerData's capture/restore/validate. This checks the logic and the wiring. It does not
prove that GameMaker runs the GML like the interpreter does, or that the game accepts the restored state: see
docs/SYNC-PROGRESS.md for the in-game checklist.
"""
import json
import sys

from event_sim import GmlNode, World
import gml_subset as gml
from gml_subset import GArray, GStruct

SOLO = "local:" + "0" * 31 + "1"
ALICE = "local:" + "0" * 31 + "a"
BOB = "local:" + "0" * 31 + "b"
CAROL = "local:" + "0" * 31 + "c"
STEAM = "steam:76561198000000001"
HOST = "local:" + "0" * 32
WORLD = HOST.replace(":", "_") + "_777"

ITEMS = ["apple", "bread", "carrot", "dagger", "egg", "flour"]
ENUMS = {                          # snake name -> (CamelName, members)
    "item_id": ("ItemId", ITEMS), "monster_id": ("MonsterId", ["slime", "bat", "golem"]),
    "season": ("Season", ["spring", "summer", "fall", "winter"]),
    "tutorial": ("Tutorial", ["tools", "fishing", "cooking", "combat", "mail"]),
    "date": ("Date", ["picnic", "park", "beach"]), "animal_kind": ("AnimalKind", ["chicken", "horse"]),
    "child_id": ("ChildId", ["rune", "ember"]), "child_skin_tone": ("ChildSkinTone", ["lighter", "darker"]),
    "child_stage": ("ChildStage", ["infant", "toddler"]), "child_location": ("ChildLocation", ["cradle", "spouse", "ari"]),
    "utero": ("Utero", ["ari", "spouse", "stork"]), "object_id": ("ObjectId", ["well", "bench", "mailbox", "statue"]),
    "location_id": ("LocationId", ["farm", "town", "mines"]), "npc_id": ("NpcId", ["alice", "bob", "cara", "dan"]),
    "perk": ("Perk", ["swift", "strong", "lucky"]), "spell": ("Spell", ["spark", "heal", "gust"]),
    "sex": ("Sex", ["male", "female"]),
}
NPCS = ENUMS["npc_id"][1]


# ---- the fake game ------------------------------------------------------------------------------------------------------------

def make_set(keys=()):
    inner = GStruct({k: 0 for k in keys})
    s = GStruct(inner=inner)
    s["insert"] = lambda k: inner.__setitem__(k, 0)
    s["contains"] = lambda k: k in inner
    s["remove"] = lambda k: inner.pop(k, None) and None
    s["keys"] = lambda: GArray(inner.keys())
    s["clear"] = lambda: inner.clear()
    return s


def make_map(entries=None):
    m = GStruct(inner=GStruct(entries or {}))
    m["get"] = lambda k: m["inner"].get(k)
    m["insert"] = lambda k, v: m["inner"].__setitem__(k, v)
    m["remove"] = lambda k: m["inner"].pop(k, None) and None
    m["contains_key"] = lambda k: k in m["inner"]
    m["keys"] = lambda: GArray(m["inner"].keys())
    return m


def make_list(items=()):
    lst = GStruct(items=GArray(items))
    lst["push"] = lambda v: lst["items"].append(v)
    lst["clear"] = lambda: lst["items"].clear()
    lst["count"] = lambda: len(lst["items"])
    lst["get"] = lambda i: lst["items"][i]
    lst["to_array"] = lambda: GArray(lst["items"])
    lst["map_to"] = lambda fn: make_list([fn(x) for x in lst["items"]])
    return lst


def clone(value):
    if isinstance(value, dict):
        return GStruct({k: clone(v) for k, v in value.items()})
    if isinstance(value, list):
        return GArray(clone(v) for v in value)
    return value


def bools(n, on=()):
    return GArray([i in on for i in range(n)])


def slot_struct():
    return GStruct(required_tags=GArray(), count=0, item=None)


class Engine:
    """Everything of the game that MistriMultiProgress.gml reads and writes, shaped like the game's own save code uses it."""

    def __init__(self, host_values=True):
        self.facts = {}
        self.calls = []
        self.mist_running = False
        self.spouse_index = None
        self.mines_level = 0
        self.letters = ["welcome", "bills", "wedding"]
        self.build(host_values)

    # -- construction -------------------------------------------------------------------------------------------------------
    def build(self, host_values):
        e = self
        e.calendar = GStruct(time=100)
        e.items = GArray(GStruct(recipe=GStruct(is_default=True) if i == 0 else (GStruct(is_default=False) if i < 4 else None),
                                 max_stack=99) for i in range(len(ITEMS)))
        e.stats = GStruct(enemies_killed=0, gross_essence=0, deaths=0, faints=0, bathhouse_uses=0, bugs_missed=0,
                          fish_missed=0, cutscenes_skipped=0, fish_caught=GArray(), npcs_spoken_to=GStruct({n: 0 for n in NPCS}))
        e.t2r = GStruct(read=lambda k: e.facts.get(k), write=self.fact_write, update_daily=lambda: e.calls.append("update_daily"))
        e.mist = GStruct(scene_history=make_set(), scenes_played_today=make_set(), is_running=lambda: e.mist_running)
        e.npcs = GArray(GStruct(heart_points=0, report_relationship=(lambda i=i: e.calls.append(("relationship", i))))
                        for i in range(len(NPCS)))
        e.quests = make_map({
            "story_intro": GStruct(category=0, tasks=make_list([1, 2])), "crown_a": GStruct(category=1, tasks=make_list([1, 2, 3])),
            "heart_a": GStruct(category=4, tasks=make_list([1, 2])), "fetch_a": GStruct(category=5, tasks=make_list([1])),
            "fetch_b": GStruct(category=5, tasks=make_list([1, 2]))})
        e.quest_log = GStruct(active=make_map(), completed=make_set(), completion_timestamps=make_map(), blackboard=make_map())
        e.renown_rewards = GStruct(serialize=lambda: GArray(slot_struct() for _ in range(8)), deserialize=lambda a: e.calls.append("rewards"))
        e.inbox = GStruct(contents=make_list())
        e.inbox["push_mail"] = lambda name, taken=False, read=False: e.inbox["contents"]["push"](
            GStruct(name=name, items_taken=taken, read=read))
        e.inbox["serialize"] = lambda: GArray(GStruct(path=m["name"], read=m["read"], items_taken=m["items_taken"])
                                              for m in e.inbox["contents"]["items"])
        e.inbox["deserialize"] = lambda arr: [e.inbox["push_mail"](x["path"], x["items_taken"], x["read"]) for x in arr]
        e.inbox["on_new_day"] = lambda: e.inbox["push_mail"]("welcome") if not any(
            m["name"] == "welcome" for m in e.inbox["contents"]["items"]) else None
        e.animals = GArray(GStruct(variants=make_map({"white": GStruct(default_unlocked=True), "gold": GStruct(default_unlocked=False)}),
                                   cosmetics=make_map({"bow": 1})) for _ in range(2))
        e.ari = GStruct(
            name="Host", gold=0, perks_active=bools(3, (0, 1, 2)),
            recipe_unlocks=bools(6), recipes_created=bools(6), morning_recipe_unlocks=bools(6),
            items_acquired=bools(6), items_sold=GArray([0] * 6), monsters_killed=GArray([0] * 3),
            legendary_fish_caught=bools(4), annual_item_purchase_bans=bools(6), tutorials_seen=bools(5),
            cosmetic_unlocks=make_set(["hat_default"]), seen_cosmetics=make_set(["hat_default"]),
            animal_variant_unlocks=GArray([make_map(), make_set(["white"])]), animal_cosmetic_unlocks=GArray([make_set(), make_set()]),
            pet_cosmetic_sets_unlocked=GArray(), pet_skin_unlocks=GArray(), song_unlocks=GArray(),
            song_overrides=GArray([None] * 3), dyn_song_overrides=GStruct(), bell_sound="default",
            date_unlocks=bools(3), date_history=GArray(), wedding_date=None, proposal_date=None, disable_break_ups=False,
            disable_break_up_letters=False, festival_date_partner=None, pending_child=None, children=GArray(),
            inbox=e.inbox, crown_cooldown=None, quest_artifacts=make_map(), pinned_spell=None,
            pending_renown_entries=make_list(), mount=None, mount_mirroring_animal=None,
            has_seen_treasure_level_today=False, has_seen_ritual_level_today=False, has_seen_arena_level_today=False,
            has_gossiped_today=False, has_left_house_today=False, ate_perpetual_soup_today=False, used_object_today=bools(4))
        e.ari["spouse"] = lambda: e.spouse_index
        e.ari["build_almanac_items_remaining"] = lambda: e.calls.append("almanac")
        e.ari["set_pinned_spell"] = lambda s: e.ari.__setitem__("pinned_spell", s)
        if host_values:
            self.host_progress()

    def host_progress(self):
        """What the host's own save contains: a guest's game starts with it, so a restore must replace all of it."""
        e = self
        e.ari["recipe_unlocks"] = bools(6, (0, 1, 2, 3))
        e.ari["items_acquired"] = bools(6, (0, 1, 2, 3, 4))
        e.ari["items_sold"] = GArray([5, 0, 9, 0, 0, 1])
        e.ari["tutorials_seen"] = bools(5, (0, 1, 2, 3, 4))
        e.ari["cosmetic_unlocks"] = make_set(["hat_default", "host_hat"])
        e.ari["wedding_date"] = 50
        e.ari["inbox"]["contents"]["push"](GStruct(name="bills", items_taken=True, read=True))
        e.quest_log["completed"]["insert"]("story_intro")
        e.quest_log["active"]["insert"]("heart_a", GStruct(quest=e.quests["inner"]["heart_a"], quest_name="heart_a",
                                                         current_stage=1, blackboard=make_map()))
        e.facts["quest_heart_a_in_progress"] = True
        e.quest_log["completed"]["insert"]("fetch_a")
        e.quest_log["completion_timestamps"]["insert"]("fetch_a", 40)
        e.mines_level = 40
        e.mist["scene_history"]["insert"]("host_scene")
        e.facts["cutscene_seen_host_scene"] = 1.0
        e.facts["quest_fetch_a_complete"] = True
        e.facts["alice_has_met"] = True
        e.stats["enemies_killed"] = 99
        e.ari["has_gossiped_today"] = True

    def fact_write(self, key, value):
        if value is None:
            self.facts.pop(key, None)
        else:
            self.facts[key] = value

    # -- builtins -----------------------------------------------------------------------------------------------------------
    def builtins(self):
        e = self
        b = {"ARI": e.ari, "CALENDAR": e.calendar, "T2R": e.t2r, "MIST": e.mist, "NPCS": e.npcs, "GAME_STATS": e.stats,
             "QUESTS": e.quests, "QUEST_LOG": e.quest_log, "ITEM_PROTOTYPES": e.items, "ANIMAL_PROTOTYPES": e.animals,
             "RENOWN_REWARD_INVENTORY": e.renown_rewards, "MAXIMUM_REACHED_DUNGEON_LEVEL": e.mines_level,
             "QuestCategory": GStruct(Story=0, Crown=1, TaliChallenge=2, StillwellChallenge=3, Heart=4, Fetch=5),
             "LETTERS": GStruct(contains_key=lambda k: k in e.letters),
             "MANUAL_QUEST_UNLOCKS": make_set(), "REQUEST_BOARD_READ_ENTRIES": make_set(),
             "is_nullish": lambda v: v is None, "abs": abs,
             "array_create_ext": lambda n, fn: GArray(fn(i) for i in range(int(n))),
             "serialize_array_bool": lambda flags, fn: GArray(fn(i) for i, on in enumerate(flags) if on),
             "clone_value": clone, "opt_and_then": lambda v, fn: None if v is None else fn(v),
             "HashSet": make_set, "HashSetFromArray": lambda a: make_set(a), "MapWrap": make_map, "List": make_list,
             "Inventory": lambda n: GStruct(serialize=lambda: GArray(slot_struct() for _ in range(int(n))),
                                            deserialize=lambda a: None),
             "default_cosmetic_unlocks": lambda: make_set(["hat_default"]),
             "ari_has_recipe_anywhere": lambda i: bool(e.ari["recipe_unlocks"][i] or e.ari["recipes_created"][i]),
             "report_children_facts": lambda: e.calls.append("children_facts"),
             "serialize_renown_entry": lambda x: clone(x),
             "deserialize_renown_entry": self.renown_entry,
             "create_default_mount": lambda kind: GStruct(kind=0, variant="a", sex=0, name="Mist", cosmetic=None,
                                                          mount_mirroring_animal=None, prototype=None),
             "ActiveQuest": lambda quest, name, stage: GStruct(quest=quest, quest_name=name, current_stage=stage,
                                                               blackboard=make_map()),
             "Child": self.child,
             "string_pos": lambda needle, text: text.find(needle) + 1,
             }
        for snake, (camel, members) in ENUMS.items():
            b[camel] = GStruct(LEN=len(members))
            b[snake + "_to_string"] = (lambda members: lambda i: members[int(i)])(members)
            b["try_string_to_" + snake] = (lambda members: lambda s: members.index(s) if s in members else None)(members)
        return b

    def renown_entry(self, entry):
        if entry["type"] == "museum" and entry.get("item") not in ITEMS:
            raise gml.GmlError("unknown item")
        return GStruct(entry)

    def child(self, child_id, birthday, tone):
        e = self
        c = GStruct(id=child_id, birthday=birthday, skin_tone=tone, name="Baby", stage=0, location=None)

        def set_location(loc):
            if e.spouse_index is None:
                raise gml.GmlError("set_location needs a spouse")
            c["location"] = loc
            e.calls.append(("child_location", child_id, loc))
        c["set_location"] = set_location
        return c

    # -- helpers for tests ---------------------------------------------------------------------------------------------------
    def play(self):
        """Gives this game's player a lot of personal progress (what a guest earns while playing)."""
        e, a = self, self.ari
        a["gold"] = 120
        a["recipe_unlocks"] = bools(6, (0, 4))
        a["recipes_created"] = bools(6, (4,))
        a["items_acquired"] = bools(6, (1, 5))
        a["items_sold"] = GArray([0, 7, 0, 0, 3, 0])
        a["monsters_killed"] = GArray([2, 0, 5])
        a["legendary_fish_caught"] = bools(4, (1,))
        a["annual_item_purchase_bans"] = bools(6, (3,))
        a["tutorials_seen"] = bools(5, (2,))
        a["cosmetic_unlocks"] = make_set(["hat_default", "cape"])
        a["seen_cosmetics"] = make_set(["hat_default"])
        a["animal_variant_unlocks"] = GArray([make_set(["white", "gold"]), make_set()])
        a["animal_cosmetic_unlocks"] = GArray([make_set(["bow"]), make_set()])
        a["pet_cosmetic_sets_unlocked"] = GArray(["set_a"])
        a["pet_skin_unlocks"] = GArray(["skin_b"])
        a["song_unlocks"] = GArray(["song_one"])
        a["song_overrides"] = GArray([None, "song_one", None])
        a["dyn_song_overrides"] = GStruct({"3": "song_one"})
        a["bell_sound"] = "school_bell"
        a["date_unlocks"] = bools(3, (0, 2))
        a["date_history"] = GArray([GStruct(date=0, npc=1, timestamp=77)])
        a["wedding_date"] = 300
        a["proposal_date"] = 290
        a["disable_break_ups"] = True
        a["festival_date_partner"] = 1
        a["pending_child"] = GStruct(utero=1, due_date=400)
        e.spouse_index = 1
        a["children"] = GArray([e.child(0, 321, 1)])
        a["children"][0]["name"] = "Pip"
        a["children"][0]["location"] = 2
        a["children"][0]["stage"] = 1
        a["inbox"]["contents"]["items"].clear()
        a["inbox"]["push_mail"]("welcome", False, True)
        a["inbox"]["push_mail"]("wedding", True, False)
        a["crown_cooldown"] = 3
        a["quest_artifacts"] = make_map({"festival": GStruct(last_tier=2, last_score=40)})
        a["pinned_spell"] = 1
        a["perks_active"] = bools(3, (0, 2))
        a["pending_renown_entries"] = make_list([GStruct(type="gold", gold=5)])
        a["mount"] = GStruct(kind=1, variant="brown", sex=1, name="Dash", cosmetic="bow", mount_mirroring_animal=None, prototype=None)
        a["has_seen_arena_level_today"] = True
        a["has_gossiped_today"] = False
        a["used_object_today"] = bools(4, (1,))
        e.mist["scene_history"]["clear"]()
        e.mist["scene_history"]["insert"]("first_kiss")
        e.mist["scenes_played_today"]["insert"]("first_kiss")
        e.quest_log["active"]["inner"].clear()
        e.quest_log["completed"]["clear"]()
        e.quest_log["completion_timestamps"]["inner"].clear()
        e.quest_log["completed"]["insert"]("story_intro")          # the world's story: not part of this player's progress
        e.quest_log["completed"]["insert"]("crown_a")
        e.quest_log["completion_timestamps"]["insert"]("crown_a", 150)
        board = make_map({"apple_needed": 12})
        e.quest_log["active"]["insert"]("fetch_b", GStruct(quest=e.quests["inner"]["fetch_b"], quest_name="fetch_b",
                                                           current_stage=1, blackboard=board))
        e.stats["enemies_killed"] = 7
        e.stats["npcs_spoken_to"]["bob"] = 4
        e.interp.builtins["MAXIMUM_REACHED_DUNGEON_LEVEL"] = 12
        e.facts.update({"alice_has_met": True, "cara_is_ex": True, "cutscene_seen_first_kiss": 1.0})
        for name in ("alice", "bob"):
            e.facts[name + "_status"] = "best_friend"
        e.facts["bob_status"] = "dating"
        e.npcs[1]["heart_points"] = 40


def engine_state(node):
    """Everything restore() sets, in a form that compares: the progress sections plus the derived world facts."""
    record = json.loads(gml.to_json(node.call("mistrimulti_progress_capture")))
    return normalise(record["sections"])


def normalise(value):
    if isinstance(value, dict):
        return {k: normalise(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        items = [normalise(v) for v in value]
        return sorted(items, key=lambda x: json.dumps(x, sort_keys=True)) if all(isinstance(i, str) for i in items) else items
    return value


# ---- a fake file system -------------------------------------------------------------------------------------------------------

class FileSystem:
    def __init__(self):
        self.files = {}
        self.fail_rename = 0          # the next N renames fail (a crash between the temporary file and the final name)
        self.fail_write = 0

    def exists(self, path):
        return path in self.files

    def save(self, path, text):
        if self.fail_write > 0:
            self.fail_write -= 1
            raise gml.GmlError("disk full")
        self.files[path] = text

    def rename(self, old, new):
        if self.fail_rename > 0:
            self.fail_rename -= 1
            raise gml.GmlError("rename failed")
        self.files[new] = self.files.pop(old)

    def read(self, path):
        try:
            return gml.from_json(json.loads(self.files[path]))
        except (KeyError, ValueError):
            return None


FILESYSTEMS = {}
UIDS = {}
ENGINES = {}

STUBS = """
function mistrimulti_player_valid(data, uid, world) {
    if (!is_struct(data) || !is_real(data[$ "v"]) || data.v != 1) return false;
    if (!is_string(data[$ "uid"]) || data.uid != uid || !is_string(data[$ "world"]) || data.world != world) return false;
    if (!is_real(data[$ "gold"]) || data.gold < 0) return false;
    var relations = data[$ "relations"];
    if (!is_array(relations) || array_length(relations) != NpcId.LEN) return false;
    for (var i = 0; i < NpcId.LEN; i++) {
        var p = relations[i];
        if (!is_struct(p) || !is_real(p[$ "hearts"]) || !is_string(p[$ "status"])) return false;
        var s = p.status;
        if (s != "undefined" && s != "best_friend" && s != "dating" && s != "fiance" && s != "spouse") return false;
    }
    return true;
}

function mistrimulti_player_capture() {
    var r = __mistrimulti_runtime();
    var relations = [];
    for (var i = 0; i < NpcId.LEN; i++) {
        array_push(relations, { hearts: NPCS[i].heart_points, status: T2R.read(npc_id_to_string(i) + "_status") ?? "undefined" });
    }
    return { v: 1, uid: r.uid, world: r.world_key, day: string(CALENDAR.time), gold: ARI.gold, relations: relations };
}

function mistrimulti_player_restore(data) {
    var r = __mistrimulti_runtime();
    if (!mistrimulti_player_valid(data, r.uid, r.world_key)) return false;
    ARI.gold = data.gold;
    for (var i = 0; i < NpcId.LEN; i++) {
        NPCS[i].heart_points = data.relations[i].hearts;
        T2R.write(npc_id_to_string(i) + "_status", data.relations[i].status);
    }
    r.character_pending = false;
    r.character_loaded = true;
    mistrimulti_progress_core_ready();
    return true;
}

function mistrimulti_player_fresh() {
    ARI.gold = 0;
    for (var i = 0; i < NpcId.LEN; i++) {
        NPCS[i].heart_points = 0;
        T2R.write(npc_id_to_string(i) + "_status", "undefined");
    }
    mistrimulti_progress_core_ready();
}
"""


class ProgressNode(GmlNode):
    extra_files = ("MistriMultiIdentity.gml", "MistriMultiPlayerData.gml", "MistriMultiPlayerSync.gml", "MistriMultiProgress.gml", "MistriMultiHearts.gml")

    def builtins(self):
        self.fs = FILESYSTEMS.setdefault(self.slot, FileSystem())
        self.engine = ENGINES.setdefault(self.slot, Engine())
        ENGINES[self.slot] = self.engine
        fs = self.fs
        b = self.engine.builtins()
        b.update({
            "file_exists": fs.exists, "save_text_file": fs.save, "file_rename": fs.rename, "try_read_json_file": fs.read,
            "directory_create": lambda path: None, "mmapi_mod_data_dir": lambda mod: "data",
            "mistrimulti_data_dir": lambda: "data",
            "Game": GStruct(unique_identifier=777), "GRID": GStruct(), "obj_ari": 1, "instance_exists": lambda o: True,
            "mmapi_log_warn": lambda *a: self.warnings.append(a[-1]), "mmapi_log_error": lambda *a: self.warnings.append(a[-1]),
        })
        self.warnings = []
        return b

    def setup(self):
        self.engine.interp = self.interp
        self.interp.load(STUBS, "stubs")
        self.rt.update(uid=UIDS.get(self.slot, f"local:{self.slot:032x}"), enabled=True, character_pending=False,
                       character_owner=None, character_loaded=False, look_signature="", roster=gml.GStruct(),
                       roster_dirty=False, warning="", world_key="", world_path="", player_owner=None)
        self.interp.call("mistrimulti_player_data_initialize")

    @property
    def state(self):
        return engine_state(self)


class Driver:
    """What MistriMultiBoot.gml's tick does for the player-record features."""

    def __init__(self, game):
        self.game, self.node = game, game.node
        self.node.interp.call("mistrimulti_player_register_events")
        self.node.interp.call("mistrimulti_progress_register_events")
        self.running = True

    def frame(self):
        rt = self.node.rt
        return {"epoch": rt["epoch"], "uid": rt["uid"], "world": rt["world_key"], "active": rt["player_ready"]}

    def tick(self, now):
        if self.running:
            self.node.interp.call("mistrimulti_player_data_tick")


def make_world(seed, guests=2, **faults):
    FILESYSTEMS.clear()
    ENGINES.clear()
    UIDS.clear()
    UIDS[1], UIDS[2], UIDS[3] = ALICE, BOB, CAROL
    world = World(seed, {i: ProgressNode for i in range(guests + 1)}, **faults)
    for game in world.games.values():
        game.feature = Driver(game)
    return world


def restart(world, slot):
    """The game process of one player is closed and started again (its files stay)."""
    ENGINES.pop(slot, None)               # a new process starts from the host's world copy
    game = world.start(slot)
    game.feature = Driver(game)
    return game.node


def nodes(world):
    return [world.games[i].node for i in sorted(world.games)]


def wait_ready(world, node, ms=15000):
    """Runs until the guest is playable. Returns whether the character creator would open (a new character), and then finishes it."""
    for _ in range(ms // 250):
        world.run(250)
        if node.rt["player_ready"]:
            creating = node.rt["character_pending"]
            node.rt["character_pending"] = False
            return creating
    raise AssertionError(f"player never became ready: {node.rt['player_error']!r} {node.warnings[-2:]}")


def stored(host, uid):
    """The host's progress file for a player, or None."""
    return plain(host, "players/" + uid.replace(":", "_") + ".progress.json")


def core_file(host, uid):
    return plain(host, "players/" + uid.replace(":", "_") + ".json")


def plain(host, name):
    text = host.fs.files.get("data/worlds/" + WORLD + "/" + name)
    return None if text is None else json.loads(text)


def no_errors(world):
    for game in world.games.values():
        debug = game.node.call("mistrimulti_events_debug")
        assert debug["errors"] == 0, (game.slot, debug, game.warnings[:3], game.node.warnings[:3])


# ---- tests --------------------------------------------------------------------------------------------------------------------

def test_sections_round_trip():
    """Every section captured from a played game, validated, restored into another game and captured again is identical."""
    FILESYSTEMS.clear(); ENGINES.clear()
    world = make_world(1, guests=1)
    node = world.games[1].node
    node.engine.play()
    node.rt["uid"] = ALICE
    node.rt["world_key"] = WORLD
    record = json.loads(gml.to_json(node.call("mistrimulti_progress_capture")))
    assert set(record["sections"]) == {"recipes", "almanac", "seen", "cosmetics", "romance", "inbox", "quests", "counters", "misc",
                                       "daily"}
    assert node.call("mistrimulti_progress_valid", node.data(record), ALICE, WORLD) is True
    # The story quest stays with the world: only the personal quests are in the record.
    assert record["sections"]["quests"]["done"] == ["crown_a"] and [q["name"] for q in record["sections"]["quests"]["active"]] == ["fetch_b"]
    before = normalise(record["sections"])
    # A different game (it starts with the host's progress) restores the record.
    other = ProgressNode(5, "epoch0005", world.clock, lambda *a: None)
    other.rt["uid"], other.rt["world_key"] = ALICE, WORLD
    assert other.state != before
    other.interp.call("mistrimulti_progress_restore", other.data(record))
    other_after = other.state
    other_after["daily"].pop("day", None)
    expected = json.loads(json.dumps(before))
    expected["daily"].pop("day", None)
    assert other_after == expected, {k: (other_after[k], expected[k]) for k in expected if other_after[k] != expected[k]}
    # What the host's save contained is gone (not merged with the player's data), also the world facts derived from it.
    f = other.engine.facts
    assert "cutscene_seen_host_scene" not in f and f["cutscene_seen_first_kiss"] == 1.0
    assert not other.engine.quest_log["active"]["contains_key"]("heart_a") and f["quest_heart_a_in_progress"] is False
    assert f["quest_fetch_a_complete"] is False and f["quest_crown_a_complete"] is True and f["quest_fetch_b_in_progress"] is True
    assert f["alice_has_met"] is True and "cara_is_ex" in f and f.get("bob_has_met") is None
    assert other.engine.calls.count("update_daily") == 1 and "children_facts" in other.engine.calls
    assert other.interp.builtins["MAXIMUM_REACHED_DUNGEON_LEVEL"] == 12
    assert other.engine.quest_log["completed"]["contains"]("story_intro"), "the world's story must not be touched"
    # Daily flags from another day are not restored.
    stale = json.loads(json.dumps(record))
    stale["sections"]["daily"].update(day="99", treasure=True, gossiped=True, objects=["well"])
    other.interp.call("mistrimulti_progress_restore", other.data(stale))
    assert other.engine.ari["has_seen_treasure_level_today"] is False and other.engine.ari["has_gossiped_today"] is False
    assert list(other.engine.ari["used_object_today"]) == [False] * 4
    print("PASS: sections: capture -> validate -> restore -> capture is exact for all 10 sections; the host's personal data is "
          "replaced, story quests and world facts stay consistent")


def test_fresh_and_defaults():
    FILESYSTEMS.clear(); ENGINES.clear()
    node = ProgressNode(1, "epoch0001", World(1, {}).clock, lambda *a: None)
    node.rt["uid"], node.rt["world_key"] = ALICE, WORLD
    for name in node.call("mistrimulti_progress_sections"):
        assert node.call("mistrimulti_progress_section_valid", name, node.call("mistrimulti_progress_defaults_section", name)), name
    node.interp.call("mistrimulti_progress_fresh")
    state = node.state
    assert state["recipes"] == {"created": [], "unlocks": ["apple"]}            # only the default recipes
    assert state["almanac"]["sold"] == {} and state["quests"]["done"] == [] and state["seen"] == {"scenes": ["host_scene"], "tutorials": []}
    assert state["cosmetics"]["outfits"] == ["hat_default"] and state["cosmetics"]["animal_variants"]["chicken"] == ["white"]
    assert state["romance"]["wedding_date"] is None and state["romance"]["children"] == []
    assert [m["path"] for m in state["inbox"]["letters"]] == ["welcome"], "first letters are delivered like in a new game"
    assert state["counters"]["stats"]["enemies_killed"] == 0 and state["misc"]["mines_level"] == 0
    assert len(node.rt["progress_sigs"]) == 0, "the host has nothing yet: everything must be uploaded"
    print("PASS: fresh start: a new character gets the game's new-game defaults, none of the host's progress")


def valid(node, name, value):
    return node.call("mistrimulti_progress_section_valid", name, node.data(value))


def test_validation():
    FILESYSTEMS.clear(); ENGINES.clear()
    node = ProgressNode(1, "epoch0001", World(1, {}).clock, lambda *a: None)
    node.rt["uid"], node.rt["world_key"] = ALICE, WORLD
    node.engine.play()
    good = json.loads(gml.to_json(node.call("mistrimulti_progress_capture")))
    sections = good["sections"]
    for name, value in sections.items():
        assert valid(node, name, value), name
    bad = {
        "recipes": [{"unlocks": "apple", "created": []}, {"unlocks": [1], "created": []}, {"unlocks": [""], "created": []},
                    {"unlocks": ["x" * 97], "created": []}, {"unlocks": ["a"] * 8193, "created": []}, {"created": []}],
        "almanac": [dict(sections["almanac"], sold={"apple": -1}), dict(sections["almanac"], sold={"apple": "9"}),
                    dict(sections["almanac"], killed=[]), dict(sections["almanac"], legendary=["a"] * 17)],
        "seen": [dict(sections["seen"], scenes="x"), dict(sections["seen"], tutorials=[None])],
        "cosmetics": [dict(sections["cosmetics"], bell_sound=""), dict(sections["cosmetics"], songs=[3]),
                      dict(sections["cosmetics"], animal_variants={"chicken": "white"}),
                      dict(sections["cosmetics"], song_overrides={"farm": 5}),
                      dict(sections["cosmetics"], outfits=["o"] * 4097)],
        "romance": [dict(sections["romance"], wedding_date="soon"), dict(sections["romance"], wedding_date=10 ** 15),
                    dict(sections["romance"], children=[{}] * 5), dict(sections["romance"], no_break_ups=1),
                    dict(sections["romance"], history=[{"date": "park"}]),
                    dict(sections["romance"], pending_child={"utero": "spouse"}),
                    dict(sections["romance"], children=[dict(sections["romance"]["children"][0], name="n" * 65)])],
        "inbox": [{"letters": [{"path": "x", "read": 1, "items_taken": False}]}, {"letters": [{"read": True, "items_taken": False}]},
                  {"letters": [{"path": "x", "read": True, "items_taken": False}] * 1025}],
        "quests": [dict(sections["quests"], active=[{"name": "q", "task": -1, "board": {}}]),
                   dict(sections["quests"], active=[{"name": "q", "task": 1.5, "board": {}}]),
                   dict(sections["quests"], active=[{"name": "q", "task": 1, "board": {"a": {"b": {"c": {"d": {"e": 1}}}}}}]),
                   dict(sections["quests"], done=["q"] * 2049), dict(sections["quests"], times={"q": "late"})],
        "counters": [dict(sections["counters"], stats={"deaths": -3}), dict(sections["counters"], spoken=[])],
        "misc": [dict(sections["misc"], mines_level=-1), dict(sections["misc"], renown_rewards=[{"count": -1}]),
                 dict(sections["misc"], artifacts=[]), dict(sections["misc"], mount={"kind": 1}),
                 dict(sections["misc"], renown=[{"gold": 3}]), dict(sections["misc"], crown_cooldown="3")],
        "daily": [dict(sections["daily"], treasure=1), dict(sections["daily"], day=""), dict(sections["daily"], objects=[5])],
    }
    count = 0
    for name, variants in bad.items():
        for variant in variants:
            assert not valid(node, name, variant), (name, variant)
            count += 1
    # Whole records: wrong identity, world, version, unknown sections, oversized sections and records.
    def record(**changes):
        r = json.loads(json.dumps(good))
        r.update(changes)
        return node.call("mistrimulti_progress_valid", node.data(r), ALICE, WORLD)
    assert record() is True
    assert not record(uid=BOB) and not record(world="other") and not record(v=2) and not record(v="1") and not record(sections=[])
    assert not record(sections=dict(sections, extra={})) and not record(sections=dict(sections, recipes=3))
    huge = dict(sections, cosmetics=dict(sections["cosmetics"], outfits=["x" * 90 + str(i) for i in range(1100)]))
    assert not record(sections=huge), "a section over 96 KiB is refused"
    assert node.call("mistrimulti_progress_size", node.data({"a": {"x": "y" * 100000}})) > 100000
    print(f"PASS: validation rejects {count} malformed sections and the wrong identity/world/version/size, and accepts the real ones")


def test_migration():
    FILESYSTEMS.clear(); ENGINES.clear()
    node = ProgressNode(1, "epoch0001", World(1, {}).clock, lambda *a: None)
    node.rt["uid"], node.rt["world_key"] = ALICE, WORLD
    base = {"v": 1, "revision": 4, "data": {"v": 1, "uid": ALICE, "world": WORLD,
                                            "sections": {"almanac": {"acquired": ["apple"], "sold": {}, "killed": {}, "legendary": [], "bans": []},
                                                         "retired_section": {"x": 1}}}}
    out = json.loads(gml.to_json(node.call("mistrimulti_progress_migrate", node.data(base))))
    assert out["revision"] == 4 and list(out["data"]["sections"]) == ["almanac"], out
    assert node.call("mistrimulti_progress_valid", node.data(out["data"]), ALICE, WORLD) is True
    for broken in (dict(base, v=2), dict(base, v=0), dict(base, v="1"), dict(base, revision=-1), dict(base, revision=1.5),
                   dict(base, revision="4"), dict(base, data=3), dict(base, data={"v": 1, "sections": 3}), "text", None, 7):
        assert node.call("mistrimulti_progress_migrate", node.data(broken)) is None, broken
    print("PASS: migration: unknown sections are dropped, a newer or damaged envelope is refused")


def test_new_guest_and_deltas():
    world = make_world(11, loss=0.03, jitter=30)
    host, alice, bob = nodes(world)
    uploads = []
    original = alice.interp.functions["mistrimulti_progress_send"]
    alice.interp.functions["mistrimulti_progress_send"] = lambda kind, target, epoch, revision, data: (
        uploads.append((revision, sorted(data["sections"]))), original(kind, target, epoch, revision, data))[1]
    world.run(5000)
    wait_ready(world, alice)
    assert alice.rt["progress_loaded"] and alice.rt["progress_core_loaded"] and alice.rt["player_ready"]
    assert alice.state["recipes"]["unlocks"] == ["apple"], "the new player has the new-game recipes, not the host's"
    assert alice.state["almanac"]["sold"] == {} and alice.state["seen"]["scenes"] == ["host_scene"], "scenes the host saw are not replayed"
    # A guest does not become active (visible) before both of its records are in.
    world.run(9000)
    first = stored(host, ALICE)
    assert first is not None and first["revision"] == 1 and sorted(first["data"]["sections"]) == sorted(
        alice.call("mistrimulti_progress_sections")), first
    assert alice.rt["progress_saved_revision"] == 1 and alice.rt["player_error"] == ""
    # Progress: only the changed section is uploaded; the host merges it into its copy.
    alice.engine.ari["items_sold"] = GArray([0, 3, 0, 0, 0, 0])
    world.run(9000)
    second = stored(host, ALICE)
    assert second["revision"] == 2 and uploads[-1] == (2, ["almanac"]), uploads
    assert second["data"]["sections"]["almanac"]["sold"] == {"bread": 3}
    assert second["data"]["sections"]["recipes"] == first["data"]["sections"]["recipes"]
    # Nothing changed: nothing is sent.
    count = len(uploads)
    world.run(12000)
    assert len(uploads) == count
    # Gold changes (core record) do not touch the progress file.
    alice.engine.ari["gold"] = 55
    world.run(9000)
    assert core_file(host, ALICE)["data"]["gold"] == 55 and stored(host, ALICE)["revision"] == 2
    # The bob guest has its own, separate records.
    wait_ready(world, bob)
    world.run(9000)
    assert stored(host, BOB)["data"]["uid"] == BOB and stored(host, ALICE)["data"]["uid"] == ALICE
    no_errors(world)
    print("PASS: a new guest starts fresh, becomes active only with both records, uploads all sections once, then only changes")




def test_gating_and_order():
    """A guest is playable only when its core record AND its progress are applied, whichever arrives first."""
    FILESYSTEMS.clear(); ENGINES.clear()
    node = ProgressNode(1, "epoch0001", World(1, {}).clock, lambda *a: None)
    rt = node.rt
    rt["mode"] = "join"
    node.interp.call("mistrimulti_progress_reset_session")
    node.interp.call("mistrimulti_progress_core_ready")
    assert rt["player_ready"] is False
    node.interp.call("mistrimulti_progress_applied")
    assert rt["player_ready"] is True
    node.interp.call("mistrimulti_progress_reset_session")
    rt["player_ready"] = False
    node.interp.call("mistrimulti_progress_applied")
    assert rt["player_ready"] is False
    node.interp.call("mistrimulti_progress_core_ready")
    assert rt["player_ready"] is True
    rt["mode"] = "host"
    rt["player_ready"] = False
    node.interp.call("mistrimulti_progress_core_ready")
    assert rt["player_ready"] is True, "the host does not wait for progress"
    print("PASS: a guest is ready only with both records applied, in either order; the host is not gated")


def rejoin(world, slot, uid=None):
    """The player's game is closed and started again, possibly with another account; returns (node, new_character)."""
    if uid is not None:
        UIDS[slot] = uid
    node = restart(world, slot)
    world.run(3000)
    return node, wait_ready(world, node)


def test_returning_guest_identities_and_slots():
    world = make_world(12, guests=3, loss=0.03, jitter=30)
    host, alice, bob, steam = nodes(world)
    world.run(4000)
    assert wait_ready(world, alice) is True, "a new player creates a character"
    alice.engine.play()
    world.run(12000)
    saved, gold = alice.state, alice.engine.ari["gold"]
    assert stored(host, ALICE)["data"]["sections"]["almanac"]["sold"] == {"bread": 7, "egg": 3}
    alice_files = (stored(host, ALICE), core_file(host, ALICE))
    # The game is closed and opened again: the world copy has the host's progress, the host sends this player's back.
    alice2, creating = rejoin(world, 1)
    assert creating is False, "a returning guest does not create a character again"
    assert alice2.state == saved and alice2.engine.ari["gold"] == gold == 120
    assert alice2.engine.facts["bob_status"] == "dating" and alice2.rt["progress_revision"] == stored(host, ALICE)["revision"]
    # Another account on the same slot: a new character, and nothing of the first player.
    steam2, creating = rejoin(world, 1, STEAM)
    assert creating is True and steam2.state["almanac"]["sold"] == {} and steam2.engine.ari["gold"] == 0
    assert steam2.state["recipes"]["unlocks"] == ["apple"] and steam2.engine.facts.get("cutscene_seen_first_kiss") is None
    steam2.engine.ari["items_sold"] = GArray([0, 0, 2, 0, 0, 0])
    world.run(10000)
    assert stored(host, STEAM)["data"]["sections"]["almanac"]["sold"] == {"carrot": 2}
    assert (stored(host, ALICE), core_file(host, ALICE)) == alice_files, "another account never touches alice's files"
    # Alice comes back from another computer (slot 3): same records, exactly as before.
    alice3, creating = rejoin(world, 3, ALICE)
    assert creating is False and alice3.state == saved and alice3.engine.ari["gold"] == 120
    # Slot 1 goes back to the Steam player; its earlier record is intact.
    steam3, creating = rejoin(world, 1, STEAM)
    assert creating is False and steam3.state["almanac"]["sold"] == {"carrot": 2}
    no_errors(world)
    print("PASS: reconnect: records restored without a new character; another account or a slot change never mixes records")


def test_migration_from_core_only_record():
    """A world from before this feature: the player has a core record and no progress record."""
    world = make_world(13)
    host, alice, bob = nodes(world)
    world.run(4000)
    wait_ready(world, alice)
    alice.engine.play()
    world.run(12000)
    core_before = core_file(host, ALICE)
    for suffix in ("", ".bak", ".tmp"):
        host.fs.files.pop("data/worlds/" + WORLD + "/players/" + ALICE.replace(":", "_") + ".progress.json" + suffix, None)
    alice2, creating = rejoin(world, 1)
    assert creating is False, "the core record is restored: no new character"
    assert alice2.engine.ari["gold"] == 120 and alice2.state["almanac"]["sold"] == {}, "progress starts as a new character's"
    assert alice2.state["recipes"]["unlocks"] == ["apple"] and alice2.state["seen"]["scenes"] == ["host_scene"]
    alice2.engine.ari["items_sold"] = GArray([1, 0, 0, 0, 0, 0])
    world.run(10000)
    migrated = stored(host, ALICE)
    assert migrated["v"] == 1 and migrated["revision"] >= 1 and migrated["data"]["sections"]["almanac"]["sold"] == {"apple": 1}
    assert core_file(host, ALICE)["data"]["gold"] == core_before["data"]["gold"]
    print("PASS: migration: a core-only record is restored as before, its progress starts fresh and is then stored")


def test_crash_between_checkpoints():
    world = make_world(14)
    host, alice, bob = nodes(world)
    world.run(4000)
    wait_ready(world, alice)
    alice.engine.play()
    world.run(12000)
    synced = alice.state
    # The guest plays on, but its next checkpoint never reaches the host (network gone, then the game crashes).
    world.net.partition(0, 1)
    alice.engine.ari["items_sold"] = GArray([9, 9, 9, 9, 9, 9])
    alice.engine.ari["gold"] = 999
    world.run(7000)
    assert stored(host, ALICE)["data"]["sections"]["almanac"]["sold"] == {"bread": 7, "egg": 3}
    world.net.partition(0, 1, False)
    alice2, creating = rejoin(world, 1)
    assert creating is False and alice2.state == synced and alice2.engine.ari["gold"] == 120
    print("PASS: crash between checkpoints: the player returns to the last acknowledged checkpoint")


def test_damaged_host_files():
    world = make_world(15)
    host, alice, bob = nodes(world)
    world.run(4000)
    wait_ready(world, alice)
    alice.engine.play()
    world.run(12000)
    alice.engine.ari["items_sold"] = GArray([0, 0, 0, 0, 0, 4])
    world.run(10000)
    path = "data/worlds/" + WORLD + "/players/" + ALICE.replace(":", "_") + ".progress.json"
    assert stored(host, ALICE)["revision"] == 2 and json.loads(host.fs.files[path + ".bak"])["revision"] == 1
    # The primary file is damaged: the previous valid copy is used.
    host.fs.files[path] = '{"v":1,"revision":2,"data":'
    alice2, creating = rejoin(world, 1)
    assert creating is False and alice2.state["almanac"]["sold"] == {"bread": 7, "egg": 3}, alice2.state["almanac"]
    assert alice2.rt["progress_revision"] == 1
    # The next upload carries revision 2 again and repairs the file.
    alice2.engine.ari["items_sold"] = GArray([0, 0, 0, 0, 0, 5])
    world.run(10000)
    assert stored(host, ALICE)["revision"] == 2 and stored(host, ALICE)["data"]["sections"]["almanac"]["sold"] == {"flour": 5}
    # A record for another player is not accepted either, nor is a newer format: the guest waits, nothing is overwritten.
    host.fs.files[path] = json.dumps({"v": 1, "revision": 9, "data": dict(stored(host, ALICE)["data"], uid=BOB)})
    host.fs.files[path + ".bak"] = host.fs.files[path]
    alice3 = restart(world, 1)
    world.run(15000)
    assert alice3.rt["player_ready"] is False and alice3.rt["player_error"] == "The host progress record needs recovery."
    assert alice3.rt["progress_loaded"] is False
    assert json.loads(host.fs.files[path])["revision"] == 9, "nothing replaced the damaged record"
    host.fs.files[path] = json.dumps({"v": 2, "revision": 9, "data": {}})
    host.fs.files[path + ".bak"] = host.fs.files[path]
    alice4 = restart(world, 1)
    world.run(15000)
    assert alice4.rt["player_ready"] is False and json.loads(host.fs.files[path])["v"] == 2
    no_errors(world)
    print("PASS: damaged records: previous copy used, foreign/newer/unreadable records refused and never overwritten")


def test_interrupted_host_write():
    world = make_world(16)
    host, alice, bob = nodes(world)
    world.run(4000)
    wait_ready(world, alice)
    world.run(10000)
    path = "data/worlds/" + WORLD + "/players/" + ALICE.replace(":", "_") + ".progress.json"
    before = host.fs.files[path]
    # The host's disk fails between the temporary file and the final name: the record stays whole and the upload is retried.
    host.fs.fail_rename = 2
    alice.engine.ari["items_sold"] = GArray([0, 0, 0, 6, 0, 0])
    world.run(2500)
    assert host.fs.files[path] == before or json.loads(host.fs.files[path])["data"]["sections"]["almanac"]["sold"] == {"dagger": 6}
    world.run(12000)
    assert stored(host, ALICE)["data"]["sections"]["almanac"]["sold"] == {"dagger": 6}
    assert alice.rt["progress_saved_revision"] == alice.rt["progress_revision"]
    print("PASS: an interrupted host write leaves the record whole and the upload completes when the disk recovers")


def test_refused_and_oversized_sections():
    world = make_world(17)
    host, alice, bob = nodes(world)
    world.run(4000)
    wait_ready(world, alice)
    world.run(10000)
    # A section the host cannot accept (an empty bell sound): that section is dropped from later uploads; the rest continue.
    alice.engine.ari["bell_sound"] = ""
    alice.engine.ari["items_sold"] = GArray([0, 2, 0, 0, 0, 0])
    world.run(15000)
    assert alice.rt["progress_locked"]["cosmetics"] is True
    assert stored(host, ALICE)["data"]["sections"]["almanac"]["sold"] == {"bread": 2}, "the other sections were still saved"
    assert stored(host, ALICE)["data"]["sections"]["cosmetics"]["bell_sound"] == "default"
    alice.engine.ari["items_sold"] = GArray([0, 3, 0, 0, 0, 0])
    world.run(10000)
    assert stored(host, ALICE)["data"]["sections"]["almanac"]["sold"] == {"bread": 3}
    # A section over the size limit is never sent.
    alice.engine.ari["tutorials_seen"] = bools(5, (1,))
    alice.engine.mist["scene_history"]["clear"]()
    for i in range(1200):
        alice.engine.mist["scene_history"]["insert"](f"scene_{i:04d}_" + "x" * 90)
    world.run(12000)
    assert alice.rt["progress_locked"]["seen"] is True and "exceeds" in alice.rt["player_error"]
    assert stored(host, ALICE)["data"]["sections"]["seen"]["tutorials"] == [], "the oversized section did not replace the saved one"
    no_errors(world)
    print("PASS: a refused section and an oversized section are dropped from uploads without blocking the others")


def test_protocol_abuse():
    """The host ignores updates that skip a revision, claim another identity or another session, or are malformed."""
    world = make_world(18, guests=2)
    host, alice, bob = nodes(world)
    world.run(4000)
    wait_ready(world, alice)
    wait_ready(world, bob)
    world.run(10000)
    revision = stored(host, ALICE)["revision"]
    ok = {"v": 1, "uid": ALICE, "world": WORLD,
          "sections": {"almanac": {"acquired": ["egg"], "sold": {}, "killed": {}, "legendary": [], "bans": []}}}

    def send(node, revision, data):
        return node.call("mistrimulti_progress_send", "progress_update", 0, node.rt["epoch"], revision, node.data(data))

    assert send(alice, revision + 2, ok)                      # skips ahead
    assert send(alice, revision + 1, dict(ok, uid=BOB))       # data of another identity
    assert send(alice, revision + 1, dict(ok, world="x"))
    assert send(alice, revision + 1, dict(ok, v=2))
    assert send(alice, revision + 1, dict(ok, sections={}))
    assert send(alice, revision + 1, dict(ok, sections={"nothing": {}}))
    assert send(alice, revision + 1, dict(ok, sections=[]))
    assert send(bob, revision + 1, ok)                        # bob's session, alice's identity in the data
    world.run(4000)                                           # (a game queues at most 8 blobs)
    assert alice.call("mistrimulti_event_send_blob", "progress_update", json.dumps(ok), 0,       # a header naming bob
                      alice.data({"world": WORLD, "uid": BOB, "peer_epoch": alice.rt["epoch"], "revision": revision + 1}))
    assert alice.call("mistrimulti_event_send_blob", "progress_update", json.dumps(ok), 0,       # a header naming another session
                      alice.data({"world": WORLD, "uid": ALICE, "peer_epoch": "an-older-session", "revision": revision + 1}))
    world.run(8000)
    assert stored(host, ALICE)["revision"] == revision and stored(host, BOB)["data"]["uid"] == BOB
    assert stored(host, ALICE)["data"]["sections"]["almanac"]["acquired"] == []
    # A valid update with the next revision is applied, a replay of it is only acknowledged again.
    assert send(alice, revision + 1, ok)
    world.run(5000)
    assert stored(host, ALICE)["revision"] == revision + 1
    assert send(alice, revision + 1, ok)
    world.run(5000)
    assert stored(host, ALICE)["revision"] == revision + 1
    # Garbage that is not JSON is dropped.
    assert alice.call("mistrimulti_event_send_blob", "progress_update", "{not json", 0,
                      alice.data({"world": WORLD, "uid": ALICE, "peer_epoch": alice.rt["epoch"], "revision": revision + 2}))
    # A guest cannot push a "host record" to another guest.
    assert alice.call("mistrimulti_event_send_blob", "progress_record", json.dumps(ok), 2,
                      alice.data({"world": WORLD, "uid": BOB, "peer_epoch": bob.rt["epoch"], "revision": 99}))
    world.run(6000)
    assert bob.state["almanac"]["acquired"] == [] and bob.rt["progress_revision"] == stored(host, BOB)["revision"]
    no_errors(world)
    print("PASS: skipped revisions, foreign identities/worlds/versions, malformed and forged messages are ignored; replays are idempotent")


def test_flush_on_save():
    world = make_world(19)
    host, alice, bob = nodes(world)
    world.run(4000)
    wait_ready(world, alice)
    world.run(10000)
    revision = stored(host, ALICE)["revision"]
    alice.engine.ari["items_sold"] = GArray([0, 0, 8, 0, 0, 0])
    alice.rt["progress_checkpointed"] = world.clock.micros()     # it has just checkpointed: the next one is 5 s away
    world.run(1800)
    assert stored(host, ALICE)["revision"] == revision, "without a flush the guest waits for its next checkpoint"
    host.call("mistrimulti_progress_flush_request")
    world.run(1800)
    assert stored(host, ALICE)["revision"] == revision + 1, "the guest sent its state at once instead of at its next checkpoint"
    print("PASS: the host's flush request makes guests checkpoint immediately (new day, host save)")


SAVE = "C:/Users/me/AppData/Local/FieldsOfMistria/multiplayer/saves/game-777-autosave.sav"


def save_host(host, path=SAVE):
    host.call("mistrimulti_progress_game_saving", host.data({"save_path": path}))


def load_host(host, path=SAVE):
    host.call("mistrimulti_progress_game_loaded", host.data({"save_path": path}))


def test_commit_and_rollback():
    world = make_world(20, guests=2)
    host, alice, bob = nodes(world)
    world.run(4000)
    wait_ready(world, alice)
    alice.engine.play()
    world.run(12000)
    assert host.call("mistrimulti_commit_key", SAVE) == "game-777-autosave_sav"
    # The host saves: the committed records are exactly what the players' files hold now.
    state_a = alice.state
    working_a = stored(host, ALICE)
    save_host(host)
    commit = plain(host, "commits/game-777-autosave_sav.json")
    assert commit["day"] == "100" and commit["world"] == WORLD
    assert commit["players"][ALICE]["progress"] == working_a and commit["players"][ALICE]["core"]["data"]["gold"] == 120
    # Alice plays on (records move ahead of the save); bob joins only now.
    alice.engine.ari["items_sold"] = GArray([0, 0, 0, 0, 0, 77])
    alice.engine.ari["gold"] = 500
    world.run(2000)
    wait_ready(world, bob)
    bob.engine.ari["items_sold"] = GArray([3, 0, 0, 0, 0, 0])
    world.run(10000)
    assert stored(host, ALICE)["data"]["sections"]["almanac"]["sold"] == {"flour": 77}
    bob_record = stored(host, BOB)
    # The host crashes and reloads that save: the world is back at the save, so are the players' records.
    host2 = restart(world, 0)
    load_host(host2)
    world.run(15000)
    assert stored(host2, ALICE) == working_a
    assert core_file(host2, ALICE)["data"]["gold"] == 120
    assert stored(host2, BOB) == bob_record, "a player who joined after the save keeps the record"
    discarded = plain(host2, "commits/discarded.json")
    assert discarded["players"][ALICE]["progress"]["data"]["sections"]["almanac"]["sold"] == {"flour": 77}, "the newer state is kept aside"
    assert alice.rt["player_ready"] is True
    assert alice.state == state_a and alice.engine.ari["gold"] == 120, "the guest reloaded the committed state, not the newer one"
    # Starting a new world (no save loaded) restores nothing.
    alice.engine.ari["items_sold"] = GArray([0, 0, 1, 0, 0, 0])
    world.run(12000)
    newer = stored(host2, ALICE)
    host3 = restart(world, 0)
    world.run(9000)
    assert stored(host3, ALICE) == newer
    # A save whose day does not match the newest commit uses the previous generation; if none matches, nothing is restored.
    host3.engine.calendar["time"] = 101
    save_host(host3)                 # second generation: day 101
    host3.engine.calendar["time"] = 100
    alice.engine.ari["items_sold"] = GArray([0, 0, 0, 5, 0, 0])
    world.run(12000)
    host4 = restart(world, 0)
    load_host(host4)
    world.run(9000)
    assert stored(host4, ALICE) == working_a, "the previous generation matches the loaded day"
    alice.engine.ari["items_sold"] = GArray([0, 0, 0, 0, 6, 0])
    world.run(12000)
    newest = stored(host4, ALICE)
    assert newest != working_a
    host5 = restart(world, 0)
    host5.engine.calendar["time"] = 105
    load_host(host5)
    world.run(6000)
    assert stored(host5, ALICE) == newest and "newer" in host5.rt["player_error"], host5.rt["player_error"]
    no_errors(world)
    print("PASS: host save commit: loading the save restores the committed records (newer ones kept aside), new worlds and "
          "unmatched saves restore nothing, two generations survive an interrupted save")


def test_commit_robustness():
    world = make_world(21, guests=1)
    host, alice = nodes(world)
    world.run(4000)
    wait_ready(world, alice)
    world.run(8000)
    for path, key in (("saves/game-1-slot2.sav", "game-1-slot2_sav"), ("C:\\x\\y\\game 1-A.sav", "game_1-A_sav"),
                      ("/a/b/../..//c.d.sav", "c_d_sav"), ("", ""), ("dir/", "")):
        assert host.call("mistrimulti_commit_key", path) == key, (path, host.call("mistrimulti_commit_key", path))
    assert host.call("mistrimulti_commit_key", None) == ""
    # Saving on a guest commits nothing.
    save_host(alice)
    assert not any("commits" in name for name in alice.fs.files)
    # A failing disk is reported, the game goes on.
    host.fs.fail_write = 1
    save_host(host)
    assert "committed" in host.rt["player_error"]
    save_host(host)
    name = "data/worlds/" + WORLD + "/commits/game-777-autosave_sav.json"
    commit_text = host.fs.files[name]
    # A damaged commit is ignored.
    host.fs.files[name] = "{broken"
    host.fs.files[name + ".bak"] = "[]"
    working = stored(host, ALICE)
    host2 = restart(world, 0)
    load_host(host2)
    world.run(6000)
    assert stored(host2, ALICE) == working
    # The commit belongs to its world: a commit written for another world is not applied.
    other = json.loads(commit_text)
    other["world"] = "somewhere_else"
    host.fs.files[name] = json.dumps(other)
    host3 = restart(world, 0)
    load_host(host3)
    world.run(6000)
    assert stored(host3, ALICE) == working
    print("PASS: commit keys are sanitised; guests commit nothing; failing disks, damaged or foreign commits are survived")


def claims(host):
    return json.loads(gml.to_json(host.rt["romance"]))


def test_one_partner_per_npc():
    world = make_world(22, guests=2)
    host, alice, bob = nodes(world)
    world.run(4000)
    wait_ready(world, alice)
    wait_ready(world, bob)
    world.run(6000)
    # Alice starts dating cara (NPC 2): the host holds the claim, every game learns about it, only alice may romance cara.
    alice.engine.facts["cara_status"] = "dating"
    world.run(9000)
    assert claims(host) == {"cara": ALICE}
    assert json.loads(gml.to_json(bob.rt["romance_view"])) == {"cara": ALICE}

    def ctx(node, npc):
        return node.data({"npc_id": npc, "speaker": None, "path": None})
    assert bob.call("mistrimulti_romance_prompt_guard", ctx(bob, 2)) is False, "bob's romance prompt for cara is locked"
    assert bob.call("mistrimulti_romance_prompt_guard", ctx(bob, 1)) is None, "other NPCs stay open"
    assert alice.call("mistrimulti_romance_prompt_guard", ctx(alice, 2)) is None, "the partner is never locked"
    assert host.call("mistrimulti_romance_prompt_guard", ctx(host, 2)) is False
    assert bob.call("mistrimulti_romance_prompt_guard", bob.data({"npc_id": None})) is None
    # Bob gets there first on his side (before the claim reached him): the host keeps alice's claim and downgrades bob.
    bob.rt["romance_view"] = gml.GStruct()
    bob.engine.facts["cara_status"] = "dating"
    bob.engine.facts["dan_status"] = "dating"
    world.run(9000)
    assert claims(host) == {"cara": ALICE, "dan": BOB}
    assert core_file(host, BOB)["data"]["relations"][2]["status"] == "best_friend"
    assert core_file(host, BOB)["data"]["relations"][3]["status"] == "dating"
    assert bob.engine.facts["cara_status"] == "best_friend" and ("relationship", 2) in bob.engine.calls
    assert core_file(host, ALICE)["data"]["relations"][2]["status"] == "dating"
    # A break-up frees the NPC for someone else.
    alice.engine.facts["cara_status"] = "best_friend"
    world.run(9000)
    assert claims(host) == {"dan": BOB}
    bob.engine.facts["cara_status"] = "dating"
    world.run(9000)
    assert claims(host) == {"dan": BOB, "cara": BOB}
    # The host's own relationships claim NPCs as well; a guest cannot take the host's partner.
    host.engine.facts["alice_status"] = "spouse"
    world.run(3000)
    assert claims(host)["alice"] == HOST
    alice.engine.facts["alice_status"] = "dating"
    world.run(9000)
    assert alice.engine.facts["alice_status"] == "best_friend"
    # The registry survives a host restart (rebuilt from the stored records) and reaches a late joiner.
    host2 = restart(world, 0)
    host2.engine.facts["alice_status"] = "spouse"
    world.run(9000)
    assert claims(host2) == {"dan": BOB, "cara": BOB, "alice": HOST}, claims(host2)
    bob2, _ = rejoin(world, 2)
    assert json.loads(gml.to_json(bob2.rt["romance_view"])) == claims(host2)
    # Engaged and married players keep their NPC too, and the demotion only ever touches "dating".
    bob2.engine.facts["dan_status"] = "spouse"
    world.run(9000)
    assert claims(host2)["dan"] == BOB and core_file(host2, BOB)["data"]["relations"][3]["status"] == "spouse"
    no_errors(world)
    print("PASS: one partner per NPC: first claim wins, the later player is downgraded and told, prompts are locked for others, "
          "break-ups free the NPC, the host's partner is protected, the registry survives restarts")


def test_big_record():
    """A record near the size limit crosses the network in blobs and comes back exactly."""
    world = make_world(23, guests=1)
    host, alice = nodes(world)
    world.run(4000)
    wait_ready(world, alice)
    world.run(8000)
    for i in range(700):
        alice.engine.ari["cosmetic_unlocks"]["insert"](f"outfit_{i:04d}_" + "o" * 80)
        alice.engine.mist["scene_history"]["insert"](f"scene_{i:04d}_" + "s" * 80)
    world.run(25000)
    size = len(host.fs.files["data/worlds/" + WORLD + "/players/" + ALICE.replace(":", "_") + ".progress.json"])
    assert size > 120000, size
    saved = alice.state
    alice2, creating = rejoin(world, 1)
    world.run(20000)
    assert alice2.state == saved
    no_errors(world)
    print(f"PASS: a {size // 1000} KB progress record is stored and restored exactly (multi-chunk blobs)")


def test_restore_failure_is_contained():
    """If the game rejects part of a record, that section is not uploaded later (the host's copy survives)."""
    world = make_world(24, guests=1)
    host, alice = nodes(world)
    world.run(4000)
    wait_ready(world, alice)
    alice.engine.play()
    world.run(12000)
    saved = stored(host, ALICE)
    ENGINES.pop(1, None)
    ENGINES[1] = Engine()
    ENGINES[1].child = lambda *a: (_ for _ in ()).throw(gml.GmlError("no such child"))
    alice2 = restart_keep_engine(world, 1)
    world.run(3000)
    wait_ready(world, alice2)
    assert alice2.rt["progress_locked"]["romance"] is True and "could not be restored" in alice2.rt["player_error"]
    assert alice2.state["almanac"]["sold"] == {"bread": 7, "egg": 3}
    alice2.engine.ari["items_sold"] = GArray([0, 0, 0, 0, 1, 0])
    world.run(12000)
    after = stored(host, ALICE)
    assert after["data"]["sections"]["romance"] == saved["data"]["sections"]["romance"], "the half-restored section was not uploaded"
    assert after["data"]["sections"]["almanac"]["sold"] == {"egg": 1}
    print("PASS: a section that fails to restore is kept out of uploads; the host's copy of it survives")


def restart_keep_engine(world, slot):
    game = world.start(slot)
    game.feature = Driver(game)
    return game.node


def main():
    test_sections_round_trip()
    test_fresh_and_defaults()
    test_validation()
    test_migration()
    test_gating_and_order()
    test_new_guest_and_deltas()
    test_returning_guest_identities_and_slots()
    test_migration_from_core_only_record()
    test_crash_between_checkpoints()
    test_damaged_host_files()
    test_interrupted_host_write()
    test_refused_and_oversized_sections()
    test_protocol_abuse()
    test_flush_on_save()
    test_commit_and_rollback()
    test_commit_robustness()
    test_one_partner_per_npc()
    test_big_record()
    test_restore_failure_is_contained()
    print("ALL PASS")


if __name__ == "__main__":
    main()
