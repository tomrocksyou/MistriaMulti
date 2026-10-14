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
* Six villagers with schedules, rooms and activities; a villager follows its schedule hour by hour in every game.
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
R_LEN = 12
CHEST = 0
FARM, HOME, TOWN, BEACH = 0, 1, 2, 3
NPC_COUNT = 6
T_GENERAL, T_MAIN, T_DRAGON, T_MARRIAGE = 1, 2, 3, 4
TURN_IN_BOX = 77
ACT_LEN = 20
ACT_IDLE, ACT_SIT, ACT_READ, ACT_EAT = 0, 1, 2, 3
STATE_INACTIVE, STATE_ACTIVE, STATE_TRAVELING = 0, 1, 2

ENUMS = {
    "QuestCategory": G(Story=STORY, Crown=CROWN, Heart=HEART, LEN=6),
    "SceneTestTarget": G(General=T_GENERAL, MainStory=T_MAIN, DragonStory=T_DRAGON, MarriageAndChildren=T_MARRIAGE),
    "FestivalId": G(LEN=2),
    "WorldMod": G(LEN=3),
    "Requirement": G(LEN=R_LEN, Or=R_OR, SeenCutscene=R_SEEN, WorldFactIs=R_FACT, BrokeFireSeal=R_FIRE,
                     SeridiaTransformed=R_SERIDIA, SaturdayMarketUnlocked=R_MARKET, SuppliedItems=R_SUPPLY, Invert=R_INVERT),
    "SupplyType": G(Chest=CHEST, Seal=1),
    "ObjectId": G(TurnInBox=TURN_IN_BOX),
    "LocationId": G(Farm=FARM, PlayerHome=HOME, Town=TOWN, Beach=BEACH),
    "NpcId": G(LEN=NPC_COUNT),
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
    "spring_quest": dict(cat=STORY, tasks=1),
    "crown_1": dict(cat=CROWN, tasks=2),
    "juniper_heart": dict(cat=HEART, tasks=2),
}
for _i in range(100):                      # a long story: chapters of one task each
    QUEST_DEFS["chapter_%03d" % _i] = dict(cat=STORY, tasks=1)
FESTIVAL_QUESTS = ["spring_quest", None]

SCENES = {
    "fire_seal": dict(target=T_MAIN, removals=1, quest_to_progress="dragon", spell=7, mana=40),
    "upgrade_the_saturday_market_plaza": dict(target=T_MAIN, nuke=[16, 16, 32, 32]),
    "narrows_secret": dict(target=T_GENERAL),
    "alt_scene": dict(target=T_GENERAL),
    "quest_gate": dict(target=T_GENERAL, quest_to_start=["bridge"]),
    "juniper_two": dict(target=T_MAIN, warning=2),                  # would look like a story scene by its target, but it is a romance choice
    "heart_change": dict(target=T_GENERAL, hearts=1, removals=1),   # removes an object, but changes hearts: a heart event
    "wedding": dict(target=T_MARRIAGE, quest_to_start=["bridge"]),  # starts a story quest, but is the player's wedding
    "date_beach": dict(target=T_GENERAL),
    "tutorial_intro": dict(target=T_GENERAL),
}
WORLD_SCENES = {"fire_seal", "upgrade_the_saturday_market_plaza", "narrows_secret", "alt_scene", "quest_gate"}

# villager schedules: name -> list of (from hour, room, activity)
SCHEDULES = {
    "s/home_day": [(0, HOME, ACT_IDLE), (8, TOWN, ACT_SIT), (14, BEACH, ACT_READ), (20, HOME, ACT_IDLE)],
    "s/town_day": [(0, HOME, ACT_IDLE), (7, TOWN, ACT_EAT), (18, TOWN, ACT_SIT), (22, HOME, ACT_IDLE)],
    "s/festival": [(0, HOME, ACT_IDLE), (9, FARM, ACT_SIT), (20, HOME, ACT_IDLE)],
    "s/roommate": [(0, HOME, ACT_IDLE), (12, FARM, ACT_IDLE), (21, HOME, ACT_IDLE)],
}


def where(schedule, hour):
    out = SCHEDULES[schedule][0]
    for entry in SCHEDULES[schedule]:
        if hour >= entry[0]:
            out = entry
    return out


def default_save():
    return {"day": 5, "quests": {"arrival": 1}, "done": [], "scenes": ["tutorial_intro"], "facts": [], "counters": [0, 0, 0],
            "personal": {"crown_1": 1}, "gold": 100}


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
        self.gold = save["gold"]
        self.spells = []
        self.facts = {}
        self.history = list(save["scenes"])
        self.completed = list(save["done"])
        self.stamps = {}
        self.rewards = {}               # quest -> how many times its reward was given here
        self.starts = []                # QUEST_LOG.start calls (name, stage)
        self.removals = 0               # objects erased by a scene's object_removals
        self.nuked_cells = 0
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
        self.counters = list(save["counters"])
        self.hidden = set(save.get("hidden", []))      # quests this game's version does not know
        self.sched = ["s/home_day"] * NPC_COUNT
        self.npcs = []
        for i in range(NPC_COUNT):
            handler = G(activity=None, state=STATE_ACTIVE, request=None)
            handler["request_activity"] = lambda a, h=handler: h.__setitem__("request", int(a))
            self.npcs.append(Npc(location_position=G(location_id=HOME), activity_handler=handler, swap_schedule_request=None))
        self.place_all()
        self.ari = G(end_of_day_status=None, mana_max=10, learn_spell=lambda s: self.spells.append(int(s)),
                     set_mana=lambda v: None)

    # -- quests --------------------------------------------------------------------------------------------------
    def quest_struct(self, name):
        d = QUEST_DEFS[name]
        tasks = []
        for t in range(d["tasks"]):
            req = A([None] * R_LEN)
            if d.get("box_task") == t:
                req[R_SUPPLY] = A([G(type=CHEST, point="box")])
            tasks.append(G(requirements=req))
        return G(category=d["cat"], tasks=G(count=lambda: len(tasks), get=lambda i: tasks[int(i)]))

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
        self.gold += 10
        self.rewards[name] = self.rewards.get(name, 0) + 1
        if QUEST_DEFS[name].get("box_task") == a["current_stage"]:
            self.boxes.discard((5, 5))
        a["current_stage"] += 1
        if a["current_stage"] >= QUEST_DEFS[name]["tasks"]:
            del self.active[name]
            self.completed.append(name)
            self.stamps[name] = self.day

    def level(self, name):
        if name in self.completed:
            return "done"
        return self.active[name]["current_stage"] if name in self.active else None

    def story_levels(self):
        return {n: self.level(n) for n in QUEST_DEFS if QUEST_DEFS[n]["cat"] == STORY and n != "spring_quest"
                and self.level(n) is not None}

    # -- cutscenes -----------------------------------------------------------------------------------------------
    def scene_struct(self, name):
        d = SCENES[name]
        return G(romantic_choice_warning=d.get("warning"), heart_level_changes=A([1] * d.get("hearts", 0)),
                 test_target=d["target"], object_removals=A([1] * d.get("removals", 0)),
                 nuke=A(d["nuke"]) if d.get("nuke") else None,
                 quest_to_start=A(d["quest_to_start"]) if d.get("quest_to_start") else None,
                 quest_to_progress=d.get("quest_to_progress"), spell_to_unlock=d.get("spell"), mana_to_set=d.get("mana"))

    def watch(self, name):
        """A cutscene the player watched to its end: the game's clean_up_scene effects, applied by the viewer's own game."""
        d = SCENES[name]
        if name in self.history:
            return
        self.history.append(name)
        self.facts["cutscene_seen_" + name] = 1.0
        self.removals += d.get("removals", 0)
        if d.get("nuke"):
            self.nuked_cells += 4        # the clear-area command empties every cell of the rectangle
        for q in d.get("quest_to_start", []):
            if q not in self.active and q not in self.completed:
                self.quest_start(q)
        if d.get("quest_to_progress"):
            q = d["quest_to_progress"]
            if q not in self.active and q not in self.completed:
                self.quest_start(q)
            if q in self.active:
                self.hand_in(q)
        if d.get("spell") is not None:
            self.spells.append(d["spell"])
        if d.get("mana"):
            self.ari["mana_max"] = max(self.ari["mana_max"], d["mana"])

    # -- villagers -----------------------------------------------------------------------------------------------
    def place_all(self):
        Npc.engine = True
        for i, npc in enumerate(self.npcs):
            hour, room, act = where(self.sched[i], self.hour)
            npc.location_position = G(location_id=room)
            npc.activity_handler.activity = G(id=act)
        Npc.engine = False

    def new_day(self, schedules):
        """npcs_on_new_day: every game picks its villagers' schedules from its own facts (so they can differ per game)."""
        self.day += 1
        self.hour = 6
        self.sched = list(schedules)
        for npc in self.npcs:
            npc.swap_schedule_request = None
        self.place_all()

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
                "gold": self.gold}

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
        mist = G(is_running=lambda: f.scene_running, scene_history=history)

        def t2_write(name, value, expiration=None):
            f.facts[name] = value

        t2r = G(read=lambda n: f.facts.get(n), write=t2_write, schedule_name=lambda i: f.sched[int(i)],
                schedule_names=lambda: A(list(SCHEDULES.keys())))

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
                  G(requirements=req(fire=True))])
        town = G(node_index_for_cell=lambda x, y: int(y) * 100 + int(x), node_object_id=Cells(f))
        grids = A([None] * 6)
        grids[TOWN] = town

        def erase(grid, ni):
            f.nuked_cells += 1
            f.boxes.discard((int(ni) % 100, int(ni) // 100))

        return {
            **ENUMS,
            "ARI": f.ari, "MIST": mist, "QUEST_LOG": quest_log, "CUTSCENES": G(contains_key=lambda n: n in SCENES, get=f.scene_struct),
            "QUESTS": G(get=lambda n: f.quest_struct(n) if n in QUEST_DEFS and n not in f.hidden else None), "T2R": t2r,
            "FESTIVALS": A([G(prototype=G(associated_quest=q)) for q in FESTIVAL_QUESTS]),
            "WORLD_MODS": mods, "REQUIREMENT_ALIASES": aliases, "requirement_is_alias": lambda i: aliases[int(i)] is not None,
            "GRIDS": grids, "trellis_point_location_position": lambda point: G(location_id=TOWN, pos=G(x=40, y=40)),
            "erase_object_node": erase, "trigger_scene_object_removals": lambda name: setattr(f, "removals", f.removals + SCENES[name].get("removals", 0)),
            "spawn_prios_on_map": lambda *a: setattr(f, "plaza", f.plaza + 1), "location_id_to_gm_room": lambda i: i,
            "spawn_priority_object": 0, "fix_plaza_footsteps": lambda: None,
            "CALENDAR": G(time=0), "total_days": lambda: f.day, "NPCS": A(f.npcs),
            "ACTIVITIES": G(get=lambda i: G(id=int(i)) if 0 <= int(i) < ACT_LEN else None),
        }
