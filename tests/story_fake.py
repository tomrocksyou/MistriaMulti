"""A small stand-in for the parts of the game that MistriMultiStory.gml touches, for tests/test_story.py.

Each simulated game gets its own `Fake` (its own quest log, cutscene history, world facts, villagers), built from the same
saved description, as host and guests start from one save in the real game. Only the shape of the game's data that the GML
reads is modelled; where the real game behaves in a way nobody could check here, the stub says so in a comment. The stubs are
Python callables placed in the interpreter's builtin table.

The world the tests play in:

* Quests: three story quests (`arrival`, `bridge` with a turn-in box on its first task, `dragon`), one story-category quest
  that the calendar runs in every game (`spring_quest`, a festival's associated quest) and two personal ones (`crown_1`,
  `juniper_heart`). Handing in a task gives the player 10 gold, so a reward given twice shows.
* Cutscenes: `fire_seal` and `upgrade_the_saturday_market_plaza` (main story: remove objects / clear an area, advance a story quest, unlock a spell),
  `narrows_secret`, `alt_scene` (read by world gates), `quest_gate` (starts a story quest), `juniper_two` and `heart_change`
  (heart events), `wedding`, `date_beach`, `tutorial_intro`.
* World gates (WORLD_MODS and aliases) read those cutscenes and the facts `bridge_fixed` and `market_open`.
* Six villagers with schedules, rooms and activities; a villager follows its schedule hour by hour in every game. Juniper (2) and
  Hayden (4) can be a player's spouse; Dozy (3) and Henrietta (5) are their pets. A villager is a roommate (lives in the farm house,
  on the roommate schedule, asleep in the bed or on the floor at the start of the day) when its status fact says "spouse" in
  that game, as in the real game; `roommate_to_sleep` fails for anybody else who is not a pet, as the real one does.
* Rewards: every task gives 10 gold (`arrival`'s first also an item); `arrival` and `bridge` have quest rewards (an item, renown);
  `bridge`'s second task also starts the personal quest `juniper_heart` and the story quest `dragon`. The cutscenes `fire_seal`
  and `alt_scene` give items and baths, `juniper_two` (a heart event) gives an item. Every grant is counted per reward.
* Scenes the game starts by itself (the story that everybody watches): `dragon_day2` (a trigger area in town, needs the dragon quest
  at stage 0, advances it, removes an object, gives an item once, a bath and a world gate reads it), `bridge_vision` (waits in a task
  of the `bridge` quest), `chapter_intro` (starts the quest `chapter_000`), `night_scene` (plays when the player sleeps) and some
  that cannot be shown safely (a hand-made trigger, an "or" over a quest stage, an unknown stage). `watch` models the game's
  `check_cutscene_eligible` and `clean_up_scene` (repeat switch, history, `give_items_once`, baths, objects removed once per call,
  `quest_to_start` for a quest that is not active, `quest_to_progress`, the blackboard flag `removed_scene_objects`).
"""
import gml_subset as gml

A = gml.GArray


class G(gml.GStruct):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


# ---- enumerations -------------------------------------------------------------------------------------------

STORY, CROWN, HEART = 0, 1, 5
(R_OR, R_SEEN, R_FACT, R_FIRE, R_SERIDIA, R_MARKET, R_SUPPLY, R_INVERT) = range(8)
R_QSTAGE, R_QACTIVE, R_QDONE = 12, 13, 14
R_LEN = 15
QT_CUTSCENE = 1
CHEST = 0
FARM, HOME, TOWN, BEACH = 0, 1, 2, 3
NPC_COUNT = 6
T_GENERAL, T_MAIN, T_DRAGON, T_MARRIAGE = 1, 2, 3, 4
TURN_IN_BOX = 77
ACT_LEN = 20
ACT_IDLE, ACT_SIT, ACT_READ, ACT_EAT = 0, 1, 2, 3
NAMES = ["adeline", "eiland", "juniper", "dozy", "hayden", "henrietta"]
PETS = {2: 3, 4: 5}                       # spouse -> pet
FRIDAY = 4
R_ITEM, R_GOLD, R_QUEST, R_RENOWN = 0, 1, 2, 3
ROOMMATE = "Schedules/roommate_schedule"
STATE_INACTIVE, STATE_ACTIVE, STATE_TRAVELING = 0, 1, 2

ENUMS = {
    "QuestCategory": G(Story=STORY, Crown=CROWN, Heart=HEART, LEN=6),
    "SceneTestTarget": G(General=T_GENERAL, MainStory=T_MAIN, DragonStory=T_DRAGON, MarriageAndChildren=T_MARRIAGE),
    "FestivalId": G(LEN=2),
    "WorldMod": G(LEN=4),
    "Requirement": G(LEN=R_LEN, Or=R_OR, SeenCutscene=R_SEEN, WorldFactIs=R_FACT, BrokeFireSeal=R_FIRE,
                     SeridiaTransformed=R_SERIDIA, SaturdayMarketUnlocked=R_MARKET, SuppliedItems=R_SUPPLY, Invert=R_INVERT,
                     QuestIsAtStage=R_QSTAGE, QuestIsActive=R_QACTIVE, CompletedQuest=R_QDONE),
    "QuestQueryType": G(Cutscene=QT_CUTSCENE, Other=0),
    "SupplyType": G(Chest=CHEST, Seal=1),
    "ObjectId": G(TurnInBox=TURN_IN_BOX),
    "LocationId": G(Farm=FARM, PlayerHome=HOME, Town=TOWN, Beach=BEACH),
    "NpcId": G(LEN=NPC_COUNT),
    "Day": G(Friday=FRIDAY),
    "QuestRewardType": G(Item=R_ITEM, Gold=R_GOLD, Quest=R_QUEST, Renown=R_RENOWN),
    "Activity": G(LEN=ACT_LEN),
    "ActivityState": G(Inactive=STATE_INACTIVE, Active=STATE_ACTIVE, Traveling=STATE_TRAVELING),
}

# Macros the game defines over globals; the GML assigns to them.
PRELUDE = """
#macro STORY_ENABLED global.story_enabled
#macro CANCEL_FESTIVALS global.cancel_festivals
#macro SECRET_NARROWS global.secret_narrows
#macro SECRET_BEACH global.secret_beach
#macro SECRET_TOWER global.secret_tower
"""

QUEST_DEFS = {
    "arrival": dict(cat=STORY, tasks=3),
    "bridge": dict(cat=STORY, tasks=2, box_task=0),
    "dragon": dict(cat=STORY, tasks=2),
    "visions": dict(cat=STORY, tasks=3, cutscenes={1: "bridge_vision"}),
    "spring_quest": dict(cat=STORY, tasks=1),
    "crown_1": dict(cat=CROWN, tasks=2),
    "juniper_heart": dict(cat=HEART, tasks=2),
}
for _i in range(100):                      # a long story: chapters of one task each
    QUEST_DEFS["chapter_%03d" % _i] = dict(cat=STORY, tasks=1)
FESTIVAL_QUESTS = ["spring_quest", None]

SCENES = {
    "fire_seal": dict(target=T_MAIN, removals=1, quest_to_progress="dragon", spell=7, mana=40, items=[("sword", 1)], baths=2),
    "upgrade_the_saturday_market_plaza": dict(target=T_MAIN, nuke=[16, 16, 32, 32]),
    "narrows_secret": dict(target=T_GENERAL),
    "alt_scene": dict(target=T_GENERAL, items=[("lantern", 2)]),
    "quest_gate": dict(target=T_GENERAL, quest_to_start=["bridge"]),
    "juniper_two": dict(target=T_MAIN, warning=2, items=[("rose", 1)]),   # would look like a story scene by its target, but it is a romance choice
    "heart_change": dict(target=T_GENERAL, hearts=1, removals=1),   # removes an object, but changes hearts: a heart event
    "wedding": dict(target=T_MARRIAGE, quest_to_start=["bridge"]),  # starts a story quest, but is the player's wedding
    "date_beach": dict(target=T_GENERAL),
    "tutorial_intro": dict(target=T_GENERAL),
}
SCENES.update({
    # The scenes the game starts by itself. Every one of them is also a world scene (main/dragon story).
    "dragon_day2": dict(target=T_DRAGON, trigger=True, needs={"dragon": 0}, quest_to_progress="dragon", removals=1,
                        items=[("scale", 1)], once=True, baths=1, spell=9),
    "bridge_vision": dict(target=T_MAIN, items=[("vision_token", 1)], progress_task_quest=True),
    "chapter_intro": dict(target=T_MAIN, trigger=True, quest_to_start=["chapter_000"]),
    "night_scene": dict(target=T_MAIN, sleeping=True, removals=1),
    # Cannot be shown safely: applied silently as before.
    "manual_scene": dict(target=T_MAIN, trigger="manual", removals=1, items=[("hand_gift", 1)]),
    "or_scene": dict(target=T_MAIN, trigger=True, or_needs={"dragon": 0}, items=[("or_gift", 1)]),
    "unknown_stage_scene": dict(target=T_MAIN, trigger=True, quest_to_progress="dragon", items=[("blind_gift", 1)]),
    "repeat_scene": dict(target=T_MAIN, trigger=True, repeat=True),
    "story_mode_scene": dict(target=T_MAIN, trigger=True, story_mode=True, removals=1),
    # Requirements the mirror could break: "not seen" of a world scene, a world fact that must be false; and one it cannot.
    "inverted_scene": dict(target=T_MAIN, trigger=True, inv_seen=["alt_scene"], items=[("inv_gift", 1)]),
    "fact_false_scene": dict(target=T_MAIN, trigger=True, facts=[("caldarus_home", None)], items=[("fact_gift", 1)]),
    "fact_true_scene": dict(target=T_MAIN, trigger=True, facts=[("bridge_fixed", True)]),
    # Not a world scene by itself, but a world gate reads it; it also has a trigger.
    "gate_trigger": dict(target=T_GENERAL, trigger=True, items=[("gate_gift", 1)]),
})
WORLD_SCENES = {"fire_seal", "upgrade_the_saturday_market_plaza", "narrows_secret", "alt_scene", "quest_gate", "dragon_day2",
                "bridge_vision", "chapter_intro", "night_scene", "manual_scene", "or_scene", "unknown_stage_scene", "repeat_scene",
                "story_mode_scene", "gate_trigger", "inverted_scene", "fact_false_scene", "fact_true_scene"}

# villager schedules: name -> list of (from hour, room, activity)
SCHEDULES = {
    "s/home_day": [(0, HOME, ACT_IDLE), (8, TOWN, ACT_SIT), (14, BEACH, ACT_READ), (20, HOME, ACT_IDLE)],
    "s/town_day": [(0, HOME, ACT_IDLE), (7, TOWN, ACT_EAT), (18, TOWN, ACT_SIT), (22, HOME, ACT_IDLE)],
    "s/festival": [(0, HOME, ACT_IDLE), (9, FARM, ACT_SIT), (20, HOME, ACT_IDLE)],
    "s/roommate": [(0, HOME, ACT_IDLE), (12, FARM, ACT_IDLE), (21, HOME, ACT_IDLE)],
    # What the game gives its roommates: at home in the morning, on the farm in the afternoon, home at night.
    ROOMMATE: [(0, HOME, ACT_IDLE), (10, FARM, ACT_IDLE), (18, HOME, ACT_IDLE)],
    ROOMMATE + "_friday": [(0, HOME, ACT_IDLE), (12, FARM, ACT_IDLE), (18, HOME, ACT_IDLE)],
    ROOMMATE + "_festival": [(0, HOME, ACT_IDLE), (9, FARM, ACT_SIT), (19, HOME, ACT_IDLE)],
}


def where(schedule, hour):
    out = SCHEDULES[schedule][0]
    for entry in SCHEDULES[schedule]:
        if hour >= entry[0]:
            out = entry
    return out


# rewards: quest -> { task index: [(type, ...)] , "q": [...] } ; every other task gives 10 gold
REWARDS = {
    "arrival": {0: [(R_GOLD, 10), (R_ITEM, "seed", 1)], "q": [(R_ITEM, "trophy", 1), (R_RENOWN, 5)]},
    "bridge": {1: [(R_GOLD, 10), (R_QUEST, "juniper_heart"), (R_QUEST, "dragon"), (R_QUEST, "spring_quest")], "q": [(R_RENOWN, 3)]},
}


def task_rewards(name, t):
    return REWARDS.get(name, {}).get(t, [(R_GOLD, 10)])


def default_save():
    return {"day": 5, "quests": {"arrival": 1}, "done": [], "scenes": ["tutorial_intro"], "facts": [], "counters": [0, 0, 0],
            "personal": {"crown_1": 1}, "gold": 100, "items": {}, "renown": [], "ledger": {}, "status": {}, "baths": 0}


def RewardList(items=()):
    """The game's List of QuestReward (count, get, push)."""
    lst = list(items)
    return G(_items=lst, count=lambda: len(lst), get=lambda i: lst[int(i)], push=lambda reward: lst.append(reward))


class Npc(G):
    """A villager. The GML may only ask for a schedule swap; it must never place a villager itself."""
    engine = False
    violations = []

    def __setitem__(self, key, value):
        if key == "location_position" and not Npc.engine:
            Npc.violations.append(key)
        super().__setitem__(key, value)


class Cells(gml.GArray):
    """grid.node_object_id: the turn-in box sits in one cell (5, 5) of the town."""

    def __init__(self, fake):
        super().__init__([None] * 10000)
        self.fake = fake

    def __getitem__(self, i):
        return TURN_IN_BOX if (int(i) % 100, int(i) // 100) in self.fake.boxes else None


class Fake:
    """One game's copy of the quest log, history, facts and villagers."""

    def __init__(self, save):
        self.day = save["day"]
        self.hour = 6
        self.room = TOWN                # the room the player is in (CURRENT_LOCATION_ID)
        self.scene_running = False
        self.active_scene = None                        # MIST.active_cutscene while a scene runs
        self.played_today = set()
        self.views = {}                                 # scene -> times it ran here
        self.refused = []                               # scenes that were not eligible when a test tried to play them
        self.blackboard = {}
        self.cut = {}                                   # scene -> the one struct CUTSCENES.get returns (the mod switches can_repeat on it)
        self.nuked = set()
        self.gold = save["gold"]
        self.items = dict(save.get("items", {}))        # what the player holds (item -> count)
        self.renown = list(save.get("renown", []))      # renown entries filed for completed quests
        self.granted = {}                               # reward tag -> times granted here
        self.notes = []
        self.weekday = 2
        self.festival = False
        self.bed_log = []                               # villagers put to bed by roommate_to_sleep, in order
        self.swaps_done = []                            # perform_schedule_swap calls (villager, schedule)
        self.spells = []
        self.facts = {}
        self.history = list(save["scenes"])
        self.completed = list(save["done"])
        self.stamps = {}
        self.rewards = {}               # quest -> how many times its reward was given here
        self.starts = []                # QUEST_LOG.start calls (name, stage)
        self.removals = 0               # objects erased by a scene's object_removals
        self.plaza = 0
        self.boxes = set()
        self.active = {}
        self.save = save
        for name, stage in list(save["quests"].items()) + list(save["personal"].items()):
            self.active[name] = self.make_active(name, stage)
            for t in range(stage + 1):
                self.active[name]["initialize_requirements_on_task"](t)
        for name in save["facts"]:
            self.facts[name] = True
        for name in self.history:
            self.facts["cutscene_seen_" + name] = 1.0
        for name, level in save.get("ledger", {}).items():      # world facts are saved with the world
            self.facts["mm_paid_" + name] = True if name == "init" else level
        for name, status in save.get("status", {}).items():
            self.facts[name + "_status"] = status
        for name, value in save.get("textfacts", {}).items():      # facts that hold text (saved with the world too)
            self.facts[name] = value
        self.counters = list(save["counters"])
        self.hidden = set(save.get("hidden", []))      # quests this game's version does not know
        self.sched = ["s/home_day"] * NPC_COUNT
        self.village = list(self.sched)                 # what the game's own schedule choice gives each villager today
        self.npcs = []
        for i in range(NPC_COUNT):
            handler = G(activity=None, state=STATE_ACTIVE, request=None)
            handler["request_activity"] = lambda a, h=handler: h.__setitem__("request", int(a))
            npc = Npc(location_position=G(location_id=HOME), activity_handler=handler, swap_schedule_request=None,
                      talk_flag=True, brain_dead=False, animation="idle", prototype=G(dateable=i not in PETS.values()))
            npc["is_spouse"] = lambda i=i: self.facts.get(NAMES[i] + "_status") == "spouse"
            npc["is_roommate"] = lambda i=i: self.is_roommate(i)
            self.npcs.append(npc)
        self.place_all()
        self.ari = G(end_of_day_status=None, mana_max=10, learn_spell=lambda s: self.spells.append(int(s)),
                     set_mana=lambda v: None, free_baths=save.get("baths", 0),
                     pending_renown_entries=G(push=lambda e: self.renown.append(e)),
                     spouse=lambda: next((i for i in range(NPC_COUNT) if self.npcs[i]["is_spouse"]()), None))

    # -- quests --------------------------------------------------------------------------------------------------
    def quest_struct(self, name):
        d = QUEST_DEFS[name]
        tasks = []
        for t in range(d["tasks"]):
            req = A([None] * R_LEN)
            if d.get("box_task") == t:
                req[R_SUPPLY] = A([G(type=CHEST, point="box")])
            scene = d.get("cutscenes", {}).get(t)
            targets = [G(type=QT_CUTSCENE, cutscene=scene)] if scene else []
            tasks.append(G(requirements=req, reward_list=self.reward_list(name, t),
                           query_targets=G(count=lambda targets=targets: len(targets), get=lambda i, targets=targets: targets[int(i)])))
        return G(category=d["cat"], name=name, tasks=G(count=lambda: len(tasks), get=lambda i: tasks[int(i)]),
                 reward_list=self.reward_list(name, "q"))

    def reward_list(self, name, key):
        out = []
        for r in (REWARDS.get(name, {}).get("q", []) if key == "q" else task_rewards(name, key)):
            tag = (name, key)
            if r[0] == R_GOLD:
                out.append(G(type=R_GOLD, amount=r[1], tag=tag))
            elif r[0] == R_ITEM:
                out.append(G(type=R_ITEM, item=r[1], amount=r[2], tag=tag))
            elif r[0] == R_QUEST:
                out.append(G(type=R_QUEST, quest_name=r[1], tag=tag))
            else:
                out.append(G(type=R_RENOWN, value=r[1], tag=tag))
        return RewardList(out)

    def grant(self, rewards):
        """grant_quest_rewards: gold, items and quests are given at once; renown is filed by the game on completion."""
        for r in rewards["_items"]:
            if r["type"] == R_GOLD:
                self.gold += r["amount"]
                if isinstance(r["tag"][1], int):
                    self.rewards[r["tag"][0]] = self.rewards.get(r["tag"][0], 0) + 1
            elif r["type"] == R_ITEM:
                self.items[r["item"]] = self.items.get(r["item"], 0) + r["amount"]
            elif r["type"] == R_QUEST:
                if r["quest_name"] not in self.active and r["quest_name"] not in self.completed:
                    self.quest_start(r["quest_name"])
            if r["type"] != R_RENOWN:
                key = r["tag"] + (r["type"], r.get("quest_name") or r.get("item"))
                self.granted[key] = self.granted.get(key, 0) + 1

    def make_active(self, name, stage):
        def init(task):
            if QUEST_DEFS[name].get("box_task") == int(task):
                self.boxes.add((5, 5))
        return G(current_stage=stage, quest_name=name, initialize_requirements_on_task=init)

    def quest_start(self, name, stage=0):
        self.starts.append((name, int(stage)))
        self.active[name] = self.make_active(name, int(stage))
        for t in range(int(stage) + 1):
            self.active[name]["initialize_requirements_on_task"](t)
        return True

    def hand_in(self, name):
        """The player turns in the current task: ActiveQuest.progress(), then QuestLog.complete() (local and relative)."""
        a = self.active[name]
        self.grant(self.reward_list(name, a["current_stage"]))
        if QUEST_DEFS[name].get("box_task") == a["current_stage"]:
            self.boxes.discard((5, 5))
        a["current_stage"] += 1
        if a["current_stage"] >= QUEST_DEFS[name]["tasks"]:
            del self.active[name]
            self.completed.append(name)
            self.stamps[name] = self.day
            quest_rewards = self.reward_list(name, "q")
            if any(r["type"] == R_RENOWN for r in quest_rewards["_items"]):
                self.renown.append(name)
            self.grant(quest_rewards)           # the quest-complete popup

    def level(self, name):
        if name in self.completed:
            return "done"
        return self.active[name]["current_stage"] if name in self.active else None

    def story_levels(self):
        return {n: self.level(n) for n in QUEST_DEFS if QUEST_DEFS[n]["cat"] == STORY and n != "spring_quest"
                and self.level(n) is not None}

    # -- cutscenes -----------------------------------------------------------------------------------------------
    def scene_struct(self, name):
        if name in self.cut:
            return self.cut[name]
        d = SCENES[name]
        req = A([None] * R_LEN)
        if d.get("needs"):
            req[R_QSTAGE] = A([G(quest=q, stage=st) for q, st in d["needs"].items()])
        if d.get("needs_active"):
            req[R_QACTIVE] = A(list(d["needs_active"]))
        if d.get("inv_seen"):
            sub = A([None] * R_LEN)
            sub[R_SEEN] = A(list(d["inv_seen"]))
            req[R_INVERT] = sub
        if d.get("facts"):
            req[R_FACT] = A([A([n, v]) for n, v in d["facts"]])
        if d.get("or_needs"):
            sub = A([None] * R_LEN)
            sub[R_QSTAGE] = A([G(quest=q, stage=st) for q, st in d["or_needs"].items()])
            req[R_OR] = A([sub])
        trig = d.get("trigger")
        self.cut[name] = G(romantic_choice_warning=d.get("warning"), heart_level_changes=A([1] * d.get("hearts", 0)),
                           test_target=d["target"], object_removals=A([1] * d.get("removals", 0)),
                           nuke=A(d["nuke"]) if d.get("nuke") else None,
                           quest_to_start=A(d["quest_to_start"]) if d.get("quest_to_start") else None,
                           quest_to_progress=d.get("quest_to_progress"), spell_to_unlock=d.get("spell"), mana_to_set=d.get("mana"),
                           given_items=A([G(item_id=n, quantity=q) for n, q in d.get("items", [])]), baths=d.get("baths", 0),
                           id=name, trigger=G(location=TOWN, bbox=None, manually_activated=trig == "manual") if trig else None,
                           when_sleeping=bool(d.get("sleeping")), requirements=req, can_repeat=bool(d.get("repeat")),
                           give_items_once=bool(d.get("once")), requires_story_mode=bool(d.get("story_mode")))
        return self.cut[name]

    def requirements_ok(self, name):
        d = SCENES[name]
        for q, stage in d.get("needs", {}).items():
            if q not in self.active or self.active[q]["current_stage"] != stage:
                return False
        return all(q in self.active for q in d.get("needs_active", []))

    def would_start(self, name, sleeping=False, story=True):
        """Mist.check_cutscene_eligible for an automatic trigger (the room area, the night): would the game offer the scene?"""
        c = self.scene_struct(name)
        d = SCENES[name]
        return (bool(d.get("trigger") or d.get("sleeping")) and c.when_sleeping == sleeping and self.requirements_ok(name)
                and (name not in self.history or c.can_repeat) and (story or not c.requires_story_mode)
                and name not in self.played_today)

    def query_would_start(self, name):
        """obj_ari: a quest task waits for the scene (the quest is at that task)."""
        return any(q in self.active and self.active[q]["current_stage"] == t
                   for q, d in QUEST_DEFS.items() for t, sc in d.get("cutscenes", {}).items() if sc == name)

    @property
    def active_scene(self):
        return self._active

    @active_scene.setter
    def active_scene(self, name):
        self._active = name
        if getattr(self, "mist", None) is not None:
            self.mist["active_cutscene"] = self.scene_struct(name) if name else None

    def trigger_removals(self, name):
        """trigger_scene_object_removals: every call erases the next matching object, so a second call erases another one."""
        self.removals += SCENES[name].get("removals", 0)

    def watch(self, name, skipped=False):
        """A cutscene the player watched to its end (or skipped): the game's clean_up_scene, applied by the viewer's own game.
        A scene that is already in the history and cannot repeat is not played by the game (the call does nothing)."""
        d = SCENES[name]
        c = self.scene_struct(name)
        if name in self.history and not c.can_repeat and self.active_scene != name:     # eligibility is checked when a scene starts
            self.refused.append(name)
            return
        was_seen = name in self.history
        grant_items = not was_seen or not c.give_items_once
        self.views[name] = self.views.get(name, 0) + 1
        if not was_seen:
            self.history.append(name)
        self.played_today.add(name)
        self.facts["cutscene_seen_" + name] = 1.0
        if not self.blackboard.pop("removed_scene_objects", False):
            self.trigger_removals(name)
        self.blackboard.clear()
        if grant_items:
            for n, q in d.get("items", []):
                self.items[n] = self.items.get(n, 0) + q
        self.ari["free_baths"] += d.get("baths", 0)
        if d.get("nuke"):
            for x in range(d["nuke"][0] // 8, d["nuke"][2] // 8):          # the clear-area loop empties every cell of the rectangle
                for y in range(d["nuke"][1] // 8, d["nuke"][3] // 8):
                    self.nuked.add((x, y))
        for q in d.get("quest_to_start", []):
            if q not in self.active:                       # `if !QUEST_LOG.active.contains_key(quest)`: a finished quest starts over
                self.quest_start(q)
        if d.get("quest_to_progress"):
            q = d["quest_to_progress"]
            if q not in self.active and q not in self.completed:
                self.quest_start(q)
            if q in self.active:
                self.hand_in(q)
        if d.get("progress_task_quest"):                   # MIST.arbitrary_quest_to_progress: the quest whose task waited for it
            for q, qd in QUEST_DEFS.items():
                for t, sc in qd.get("cutscenes", {}).items():
                    if sc == name and q in self.active and self.active[q]["current_stage"] == t:
                        self.hand_in(q)
        if d.get("spell") is not None and d["spell"] not in self.spells:
            self.spells.append(d["spell"])
        if d.get("mana"):
            self.ari["mana_max"] = max(self.ari["mana_max"], d["mana"])

    @property
    def nuked_cells(self):
        return len(self.nuked)

    # -- villagers -----------------------------------------------------------------------------------------------
    def place_all(self):
        Npc.engine = True
        for i, npc in enumerate(self.npcs):
            hour, room, act = where(self.sched[i], self.hour)
            npc.location_position = G(location_id=room)
            npc.activity_handler.activity = G(id=act)
        Npc.engine = False

    def is_roommate(self, i):
        def spouse(j):
            return self.facts.get(NAMES[j] + "_status") == "spouse"
        return spouse(i) or any(PETS[j] == i and spouse(j) for j in PETS)

    def roommate_schedule(self):
        if self.weekday == FRIDAY:
            return ROOMMATE + "_friday"
        return ROOMMATE + "_festival" if self.festival else ROOMMATE

    def sleep(self, i):
        """roommate_to_sleep: a spouse goes to the bed, a pet to the floor; anybody else is an 'impossible' in the real game."""
        npc = self.npcs[i]
        if npc["is_spouse"]():
            spot = "bed"
        elif i in PETS.values():
            spot = "floor"
        else:
            raise gml.GmlError("impossible: roommate_to_sleep for a villager who is neither a spouse nor a pet")
        Npc.engine = True
        npc.talk_flag = False
        npc.location_position = G(location_id=HOME, spot=spot)
        npc.animation = "sleep"
        Npc.engine = False
        self.bed_log.append((i, spot))

    def new_day(self, schedules):
        """npcs_on_new_day: every game picks its villagers' schedules from its own facts (so they can differ per game); a
        roommate gets the roommate schedule and starts the day asleep."""
        self.day += 1
        self.hour = 6
        self.sched = list(schedules)
        self.village = list(schedules)
        self.bed_log = []
        for npc in self.npcs:
            npc.swap_schedule_request = None
        self.place_all()
        for i, npc in enumerate(self.npcs):
            if npc["is_roommate"]():
                self.sched[i] = self.roommate_schedule()
                self.sleep(i)
                npc.brain_dead = False

    def swap_now(self, i, name, finish, time):
        """perform_schedule_swap: the villager is on the new schedule at once, at the place it says for this hour."""
        if name not in SCHEDULES:
            raise gml.GmlError("no such schedule " + str(name))
        Npc.engine = True
        self.sched[int(i)] = name
        hour, room, act = where(name, self.hour)
        self.npcs[int(i)].location_position = G(location_id=room)
        self.npcs[int(i)].activity_handler.activity = G(id=act)
        Npc.engine = False
        self.swaps_done.append((int(i), name))

    def spot(self, i):
        return self.npcs[i].location_position.get("spot")

    def advance(self, hours):
        """The game's villager step, hour by hour: a villager follows its schedule; a requested swap is made as soon as the
        villager is not in the room the player is in (npcs_on_step); a requested activity starts."""
        Npc.engine = True
        for _ in range(hours):
            self.hour += 1
            for i, npc in enumerate(self.npcs):
                h = npc.activity_handler
                hour, room, act = where(self.sched[i], self.hour)
                if hour == self.hour:
                    npc.location_position = G(location_id=room)
                    h.activity = G(id=act)
                if h.request is not None:
                    h.activity = G(id=h.request)
                    h.request = None
                req = npc.swap_schedule_request
                if req is not None and npc.location_position.location_id != self.room:
                    self.sched[i] = req["schedule_name"]
                    npc.swap_schedule_request = None
                    hour, room, act = where(self.sched[i], self.hour)
                    npc.location_position = G(location_id=room)
                    h.activity = G(id=act)
        Npc.engine = False

    def where_is(self, i):
        return self.npcs[i].location_position.location_id

    def doing(self, i):
        act = self.npcs[i].activity_handler.activity
        return None if act is None else act.id

    # -- saving ----------------------------------------------------------------------------------------------------
    def export(self, counters=None):
        return {"day": self.day, "quests": {n: a["current_stage"] for n, a in self.active.items() if QUEST_DEFS[n]["cat"] == STORY},
                "done": [n for n in self.completed if QUEST_DEFS[n]["cat"] == STORY], "scenes": list(self.history),
                "facts": [n for n, v in self.facts.items() if v is True], "counters": list(counters or self.counters),
                "personal": {n: a["current_stage"] for n, a in self.active.items() if QUEST_DEFS[n]["cat"] != STORY},
                "gold": self.gold, "items": dict(self.items), "renown": list(self.renown), "baths": self.ari["free_baths"],
                "ledger": {n[len("mm_paid_"):]: v for n, v in self.facts.items() if n.startswith("mm_paid_") and v is not None},
                "status": {n[:-len("_status")]: v for n, v in self.facts.items() if n.endswith("_status") and v is not None},
                "textfacts": {n: v for n, v in self.facts.items() if n.startswith("mm_") and isinstance(v, str)}}

    # -- builtins --------------------------------------------------------------------------------------------------
    def builtins(self):
        f = self
        active = G(keys=lambda: A(f.active.keys()), get=lambda k: f.active.get(k), remove=lambda k: f.active.pop(k, None),
                   contains_key=lambda k: k in f.active)
        completed = G(keys=lambda: A(f.completed), contains=lambda k: k in f.completed,
                      insert=lambda k: f.completed.append(k) if k not in f.completed else None)
        stamps = G(insert=lambda k, v: f.stamps.__setitem__(k, v), get=lambda k: f.stamps.get(k))
        quest_log = G(active=active, completed=completed, completion_timestamps=stamps, start=f.quest_start)
        history = G(keys=lambda: A(f.history), contains=lambda k: k in f.history,
                    insert=lambda k: f.history.append(k) if k not in f.history else None)
        played = G(contains=lambda k: k in f.played_today)
        blackboard = G(set=lambda k, v: f.blackboard.__setitem__(k, v))
        mist = G(is_running=lambda: f.scene_running, scene_history=history, scenes_played_today=played, blackboard=blackboard)
        mist["active_cutscene"] = None
        f.mist = mist

        def t2_write(name, value, expiration=None):
            f.facts[name] = value

        t2r = G(read=lambda n: f.facts.get(n), write=t2_write, schedule_name=lambda i: f.sched[int(i)],
                schedule_names=lambda: A(list(SCHEDULES.keys())), request_schedule=lambda i: f.village[int(i)])

        def req(**kw):
            out = A([None] * R_LEN)
            for k, v in kw.items():
                out[{"seen": R_SEEN, "fact": R_FACT, "fire": R_FIRE, "or_": R_OR, "market": R_MARKET}[k]] = v
            return out

        aliases = A([None] * R_LEN)
        aliases[R_FIRE] = req(seen=A(["fire_seal"]))
        aliases[R_MARKET] = req(fact=A([A(["market_open", True])]))
        mods = A([G(requirements=req(seen=A(["narrows_secret"]))),
                  G(requirements=req(fact=A([A(["bridge_fixed", True])]), or_=A([req(seen=A(["alt_scene"]))]))),
                  G(requirements=req(fire=True)),
                  G(requirements=req(seen=A(["dragon_day2", "gate_trigger"])))])
        town = G(node_index_for_cell=lambda x, y: int(y) * 100 + int(x), node_object_id=Cells(f))
        grids = A([None] * 6)
        grids[TOWN] = town

        def erase(grid, ni):
            f.nuked.add((int(ni) % 100, int(ni) // 100))
            f.boxes.discard((int(ni) % 100, int(ni) // 100))

        return {
            **ENUMS,
            "ARI": f.ari, "MIST": mist, "QUEST_LOG": quest_log, "CUTSCENES": G(contains_key=lambda n: n in SCENES, get=f.scene_struct),
            "QUESTS": G(get=lambda n: f.quest_struct(n) if n in QUEST_DEFS and n not in f.hidden else None,
                        keys=lambda: A([n for n in QUEST_DEFS if n not in f.hidden])), "T2R": t2r,
            "FESTIVALS": A([G(prototype=G(associated_quest=q)) for q in FESTIVAL_QUESTS]),
            "WORLD_MODS": mods, "REQUIREMENT_ALIASES": aliases, "requirement_is_alias": lambda i: aliases[int(i)] is not None,
            "GRIDS": grids, "trellis_point_location_position": lambda point: G(location_id=TOWN, pos=G(x=40, y=40)),
            "erase_object_node": erase, "trigger_scene_object_removals": f.trigger_removals,
            "spawn_prios_on_map": lambda *a: setattr(f, "plaza", f.plaza + 1), "location_id_to_gm_room": lambda i: i,
            "spawn_priority_object": 0, "fix_plaza_footsteps": lambda: None,
            "CALENDAR": G(time=0, day_type=lambda: f.weekday, unified_time=lambda: f.hour * 3600), "total_days": lambda: f.day,
            "NPCS": A(f.npcs), "npc_id_to_string": lambda i: NAMES[int(i)],
            "try_string_to_npc_id": lambda n: NAMES.index(n) if n in NAMES else None,
            "string_pos": lambda needle, text: text.find(needle) + 1, "real": float,
            "roommate_to_sleep": lambda npc: f.sleep(f.npcs.index(npc)),
            "roommate_home_position": lambda npc=None: G(location_id=HOME, spot="floor"),
            "perform_schedule_swap": f.swap_now, "todays_festival": lambda: "festival" if f.festival else None,
            "player_wake_position": lambda: G(location_id=HOME, spot="bed"),
            "mist_give_items_after_scene": lambda items, pos: [f.items.__setitem__(i["item_id"], f.items.get(i["item_id"], 0) + i["quantity"])
                                                              for i in items],
            "grant_quest_rewards": f.grant, "List": lambda: RewardList(), "RenownEntry": G(Quest=lambda n: n),
            "create_notification": lambda text: f.notes.append(text), "ANCHOR": G(wrap_for_local=lambda t: t),
            "ACTIVITIES": G(get=lambda i: G(id=int(i)) if 0 <= int(i) < ACT_LEN else None),
        }
