// Story, villagers, cutscenes and festivals. Design, assumptions and checklist: docs/SYNC-STORY.md.
//
// Two kinds of state live here, both owned by the host and both small:
//
//   1. WORLD STORY STATE: the story quests (name -> stage, or done), the cutscenes whose effects belong to the
//      world (what opens a bridge, a secret area or a villager), the few T2 world facts those gates read and the
//      secret-chest counters. Every game keeps a mirror of it. A game compares its own game with the mirror once a
//      second: where the game is AHEAD, the host takes it over (a guest sends a claim, the host merges it with
//      "max", everything is idempotent); where the mirror is ahead, the game is brought up to date. Nothing in a
//      claim is relative ("+1"), so two players triggering the same step, a lost packet, a repeated claim or a host
//      restart cannot advance the story twice.
//   2. THE VILLAGERS: every game keeps simulating them (the game gives no way to stop that), but the host's
//      day plan (which schedule each villager follows today) and a coarse sample (room and activity, every few
//      seconds) are sent to the guests, and a guest steers its own villagers to match, only ever out of its own
//      sight. Dialogue, gifts, hearts and heart events stay with the player (docs/SYNC-PROGRESS.md).
//
// A cutscene is a private viewing. It never pauses or moves anybody else. While one runs, this file does nothing at
// all in that game; when it ends the next pass compares the finished state with the mirror like any other change.
//
// EVERYBODY SEES THE STORY SCENES. A world scene that another player watched is not marked as played here for the games that
// did not watch it: those games get its lasting effects (so gates and unlocks agree) and keep the scene itself, which plays
// when the game's own conditions start it (the game's skip works as always). The scene enters the history (gates that read it
// open) while "can_repeat" is switched on for it, so the game still offers it; once it ran, the switch is off again and the
// personal rest is paid once. Quests that the scene starts or advances, or that wait for it, are held back in that game so
// the scene can start. A scene that cannot be shown safely (no automatic trigger, unknown stage, a player who is ahead, not
// watched within MISTRIMULTI_STORY_PATIENCE days) falls back to the silent route and the reason is logged.
//
// Two more things belong to the personal side of a shared story step and to the villagers' homes:
//
//   3. REWARDS FOR THE PLAYERS WHO DID NOT DO THE STEP. A story step gives its rewards (items, gold, recipe scrolls, a new personal
//      quest, renown at the end of the quest) to whoever hands it in. A game that is brought up to the mirror by this file pays the
//      rewards of the stages it skipped, once: a per-player ledger ("mm_paid_<quest>" world facts, carried by the progress section
//      story_rewards) says up to which level a player has been paid, by the game or by this file.
//   4. SPOUSES OF OTHER PLAYERS. The game moves a villager into the farm house only for the player whose spouse it is (the
//      "roommate" schedule, a place in the bed). Every game moves in the spouses of all the players (the host keeps the registry,
//      MistriMultiProgress.gml), also those whose player is away.
//
// Event kinds: story_claim (request guest -> host, result to everyone), story_delta (host changes), story_snapshot
// (blob, host -> one game), story_sync (guest -> host: "send everything"; also carries on_peer and on_gap),
// npc_plan (day plan) and npc_pos (sample), both host -> guests.

#macro MISTRIMULTI_STORY_DONE 1000000      // the level of a finished quest
#macro MISTRIMULTI_STORY_PASS 20           // world pass every 20 bridge ticks (1 s)
#macro MISTRIMULTI_STORY_NPC_PASS 60       // villager pass every 60 bridge ticks (3 s)
#macro MISTRIMULTI_STORY_CLAIM_MAX 20      // entries per list in a claim or a delta (20 long names still fit in an event)
#macro MISTRIMULTI_STORY_LIST_MAX 4096     // entries per list in a snapshot
#macro MISTRIMULTI_STORY_NAME_MAX 96
#macro MISTRIMULTI_STORY_APPLY_MAX 16      // changes a pass makes to the game
#macro MISTRIMULTI_STORY_RETRY 200         // a guest asks again for the snapshot after 10 s
#macro MISTRIMULTI_STORY_MISS 3            // passes a villager may be in the wrong room before it is re-aligned
#macro MISTRIMULTI_STORY_ACTIVITIES true   // also steer what villagers do (not only where they are)
#macro MISTRIMULTI_STORY_PAY_MAX 6         // quests paid in one pass
#macro MISTRIMULTI_STORY_HOME_TRIES 3      // schedule swaps asked for one housemate in one day
#macro MISTRIMULTI_STORY_PATIENCE 7        // game days a scene may wait to be watched before it is applied silently
#macro MISTRIMULTI_STORY_VIEW_MAX 8        // scenes that may wait to be watched at the same time

// ---- state ---------------------------------------------------------------------------------------------------

// Everything here belongs to one world session; entering a world starts a new event stream and so resets it.
function __mistrimulti_story() {
    var r = __mistrimulti_runtime();
    var st = r[$ "story"];
    if (!is_struct(st)) {
        st = { stream: "" };
        r.story = st;
    }
    if (st.stream != r.ev.stream) {
        st.stream = r.ev.stream;
        __mistrimulti_story_reset(st);
    }
    return st;
}

function __mistrimulti_story_reset(st) {
    // Scenes this game was holding for their player must be offered by the game's data again only if this file says so.
    if (is_struct(st[$ "view"])) __mistrimulti_story_view_disarm(st);
    st.ticks = 0;
    st.ready = false;         // the mirror holds the host's world story (host: after its first pass)
    st.q = {};                // mirror: quest name -> level (stage, or DONE)
    st.sc = {};               // mirror: world cutscene name -> true
    st.f = {};                // mirror: world fact name -> true
    st.k = { n: 0, b: 0, t: 0 }; // mirror: secret chest counters (narrows, beach, tower)
    st.pend = {};             // guest: "q:name" -> { n: level, id: request id } claims in flight
    st.bad = {};              // entries the game refused: not tried again this session
    st.data_ok = false;       // the game's data was read (until then nothing is world-level: the story sync stays off)
    st.data_tries = 0;
    st.festq = {};            // quests the calendar runs in every game
    st.gate_scenes = {};      // cutscenes that a world gate reads
    st.gate_facts = {};       // world facts that a world gate reads
    st.qmemo = {};
    st.smemo = {};
    st.view = {};             // world scenes applied here but not yet watched here: name -> game day (the fact "mm_view")
    st.view_ok = false;       // the held scenes of the save were read
    st.watching = {};         // held scenes that began to run
    st.past = {};             // scenes that were over before this (new) character arrived: never shown
    st.vmemo = {};            // scene -> how it can be shown ({ caps } or a reason why not)
    st.vindex = undefined;    // cutscene -> { quest, stage } that waits for it
    st.vlogged = {};
    st.sched = undefined;     // known schedule names
    st.snaps = [];            // host: slots waiting for the snapshot
    st.host_stream = "";      // guest: the host session the mirror belongs to
    st.plan = undefined;      // guest: the host's day plan { d, s, cf }
    st.pos = undefined;       // guest: the host's latest sample { d, l, a }
    st.plan_stream = "";      // guest: the host session each of the two came from
    st.pos_stream = "";
    st.plan_sig = "";         // host: last plan sent
    st.pos_sig = "";          // host: last sample sent
    st.miss = {};             // guest: villager index -> passes in the wrong room / activity
    st.want_at = -1000000;
    st.seen_ok = false;       // the first rewards pass of the session has run
    st.seen = {};             // quest name -> level this game had after the last pass (a rise since then was the player's own step)
    st.homes = {};            // villager index -> day on which this game moved them into the farm house
    st.tries = {};            // villager index -> swaps asked for today
    st.tries_day = -1;
    st.last_error = "";
    st.stats = { claims: 0, applied: 0, scenes: 0, swaps: 0, steers: 0, refused: 0, paid: 0, homes: 0, shown: 0, viewed: 0, silent: 0 };
}

function __mistrimulti_story_on(mode) {
    var r = __mistrimulti_runtime();
    return r.enabled && r.mode == mode && ARI != undefined;
}

// The event stream (game session) of the host, or "": mirrors belong to one host session.
function __mistrimulti_story_host_stream() {
    var peer = __mistrimulti_runtime().peers[0];
    if (!is_struct(peer) || !is_struct(peer[$ "ev"]) || !is_string(peer.ev[$ "s"])) return "";
    return peer.ev.s;
}

// A guest follows one host session. A new one (it may have restarted from an older save) starts a new mirror: what the old
// host said says nothing about what the new one has, and the guest must be able to tell the new host what it is ahead on.
function __mistrimulti_story_follow(st, hs) {
    if (st.host_stream == hs) return;
    st.host_stream = hs;
    st.ready = false;
    st.q = {};
    st.sc = {};
    st.f = {};
    st.k = { n: 0, b: 0, t: 0 };
    st.pend = {};
    st.past = {};
    st.want_at = -1000000;
}

function __mistrimulti_story_warn(text) {
    mmapi_warn_rate_limited("mistrimulti_story", "mistrimulti", text);
}

function __mistrimulti_story_int(v, lo, hi) {
    return is_real(v) && v == floor(v) && v >= lo && v <= hi;
}

function __mistrimulti_story_name(v) {
    return is_string(v) && string_length(v) >= 1 && string_length(v) <= MISTRIMULTI_STORY_NAME_MAX;
}

function mistrimulti_story_debug() {
    var st = __mistrimulti_story();
    return { ready: st.ready, levels: st.q, quests: array_length(struct_get_names(st.q)), scenes: array_length(struct_get_names(st.sc)),
        facts: array_length(struct_get_names(st.f)), counters: st.k, pending: array_length(struct_get_names(st.pend)),
        refused: struct_get_names(st.bad), stats: st.stats, plan_day: is_struct(st.plan) ? st.plan.d : -1,
        error: st.last_error, gate_scenes: struct_get_names(st.gate_scenes), gate_facts: struct_get_names(st.gate_facts),
        housed: struct_get_names(st.homes), views: st.view, why: st.vlogged };
}

// ---- registration ----------------------------------------------------------------------------------------------

function mistrimulti_story_register_events() {
    mistrimulti_event_register("story_claim", { on_request: mistrimulti_story_claim_request, on_result: mistrimulti_story_claim_result,
        on_reply: mistrimulti_story_claim_reply });
    mistrimulti_event_register("story_delta", { on_event: mistrimulti_story_delta_event });
    mistrimulti_event_register("story_snapshot", { on_blob: mistrimulti_story_snapshot_blob });
    // on_peer and on_gap run once per registered function: they live on this kind only.
    mistrimulti_event_register("story_sync", { on_event: mistrimulti_story_sync_event, on_peer: mistrimulti_story_peer,
        on_gap: mistrimulti_story_gap });
    mistrimulti_event_register("npc_plan", { on_event: mistrimulti_story_plan_event });
    mistrimulti_event_register("npc_pos", { on_event: mistrimulti_story_pos_event });
}

// ---- what the game's own data says is world-level ------------------------------------------------------------------

// T2 world facts that are part of the dragon story (NpcUtils.gml reads caldarus_seridia_town; the game's own story test
// writes the four together). Others are found in the game's data below.
function mistrimulti_story_fixed_facts() {
    return ["caldarus_seridia_town", "seridia_is_human", "caldarus_is_human", "caldarus_home"];
}

// Walks a parsed requirement (an array indexed by Requirement id, aliases included) and collects the cutscenes it
// needs to have been seen and the world facts it needs to be true. Negated parts (Invert) are ignored.
function __mistrimulti_story_scan(req, scenes, facts, depth) {
    if (!is_array(req) || depth > 6) return;
    for (var i = 0; i < Requirement.LEN; i++) {
        var v = req[i];
        if (v == undefined) continue;
        if (requirement_is_alias(i)) {
            __mistrimulti_story_scan(REQUIREMENT_ALIASES[i], scenes, facts, depth + 1);
        } else if (i == Requirement.Or) {
            for (var j = 0; j < array_length(v); j++) __mistrimulti_story_scan(v[j], scenes, facts, depth + 1);
        } else if (i == Requirement.SeenCutscene && is_array(v)) {
            for (var j = 0; j < array_length(v); j++) if (is_string(v[j])) scenes[$ v[j]] = true;
        } else if (i == Requirement.WorldFactIs && is_array(v)) {
            for (var j = 0; j < array_length(v); j++) {
                if (is_array(v[j]) && array_length(v[j]) == 2 && is_string(v[j][0]) && v[j][1] == true) facts[$ v[j][0]] = true;
            }
        }
    }
}

// Built once per session, from the game's data: the cutscenes and facts that world gates (world mods such as the
// bridges and secret areas, the villagers' unlocks, the Saturday market) read, and the quests the calendar runs. If the
// data cannot be read (three tries) nothing counts as world-level and the story sync stays off; villagers still sync.
function __mistrimulti_story_data(st) {
    if (st.data_ok || st.data_tries >= 3) return;
    st.data_tries++;
    try {
        var festq = {};
        var scenes = {};
        var facts = {};
        for (var i = 0; i < FestivalId.LEN; i++) {
            var quest = FESTIVALS[i].prototype[$ "associated_quest"];
            if (is_string(quest)) festq[$ quest] = true;
        }
        for (var i = 0; i < WorldMod.LEN; i++) __mistrimulti_story_scan(WORLD_MODS[i].requirements, scenes, facts, 0);
        var gates = [Requirement.BrokeFireSeal, Requirement.SeridiaTransformed, Requirement.SaturdayMarketUnlocked];
        for (var i = 0; i < array_length(gates); i++) __mistrimulti_story_scan(REQUIREMENT_ALIASES[gates[i]], scenes, facts, 0);
        // What the host's developer command "unlock the mines" brings about (MistriMultiDevTools.gml) is a world gate too, so
        // the scenes and facts it needs are shared like any other. Guarded: an older game without it keeps the story sync on.
        try { __mistrimulti_story_scan(REQUIREMENT_ALIASES[Requirement.OpenedMines], scenes, facts, 0); } catch (e) {}
        st.festq = festq;
        st.gate_scenes = scenes;
        st.gate_facts = facts;
        st.data_ok = true;
    } catch (e) {
        st.last_error = "data: " + string(e);
        __mistrimulti_story_warn("Story data could not be read: " + string(e));
    }
}

function __mistrimulti_story_fact_world(st, name) {
    var fixed = mistrimulti_story_fixed_facts();
    for (var i = 0; i < array_length(fixed); i++) if (fixed[i] == name) return true;
    __mistrimulti_story_data(st);
    return st.data_ok && st.gate_facts[$ name] == true;
}

// A story quest: the game's "story" category, minus the quests the calendar starts and ends in every game (festivals).
function __mistrimulti_story_quest_world(st, name) {
    var m = st.qmemo[$ name];
    if (m != undefined) return m;
    __mistrimulti_story_data(st);
    if (!st.data_ok) return false;
    var quest = QUESTS.get(name);
    var ok = quest != undefined && quest.category == QuestCategory.Story && st.festq[$ name] != true;
    st.qmemo[$ name] = ok;
    return ok;
}

function __mistrimulti_story_quest_level_ok(name, level) {
    if (!__mistrimulti_story_int(level, 0, MISTRIMULTI_STORY_DONE)) return false;
    if (level == MISTRIMULTI_STORY_DONE) return true;
    var quest = QUESTS.get(name);
    return quest != undefined && level < quest.tasks.count();
}

function __mistrimulti_story_quests_in(list) {
    if (!is_array(list)) return false;
    for (var i = 0; i < array_length(list); i++) {
        var quest = QUESTS.get(list[i]);
        if (quest != undefined && quest.category == QuestCategory.Story) return true;
    }
    return false;
}

// A cutscene is the world's when the game's data says that it changes the world for everybody: it is part of the main or
// the dragon story, it removes objects or clears an area, it starts or advances a story quest, or a world gate reads it.
// Heart events, romance scenes and everything else stay with the player who watched them (docs/SYNC-STORY.md).
function __mistrimulti_story_scene_world(st, name) {
    var m = st.smemo[$ name];
    if (m != undefined) return m;
    __mistrimulti_story_data(st);
    if (!st.data_ok) return false;
    var ok = false;
    if (CUTSCENES.contains_key(name)) {
        var c = CUTSCENES.get(name);
        var personal = c.romantic_choice_warning != undefined || array_length(c.heart_level_changes) > 0
            || c.test_target == SceneTestTarget.MarriageAndChildren;
        if (!personal) {
            ok = st.gate_scenes[$ name] == true || c.test_target == SceneTestTarget.MainStory || c.test_target == SceneTestTarget.DragonStory
                || array_length(c.object_removals) > 0 || c.nuke != undefined
                || __mistrimulti_story_quests_in(c.quest_to_start)
                || (is_string(c.quest_to_progress) && __mistrimulti_story_quests_in([c.quest_to_progress]));
        }
    }
    st.smemo[$ name] = ok;
    return ok;
}

// ---- the world story as this game has it -------------------------------------------------------------------------------

function __mistrimulti_story_local(st) {
    __mistrimulti_story_data(st);
    var q = {};
    var keys = QUEST_LOG.active.keys();
    for (var i = 0; i < array_length(keys); i++) {
        if (!__mistrimulti_story_quest_world(st, keys[i])) continue;
        var active = QUEST_LOG.active.get(keys[i]);
        // A quest whose last task was just handed in is completed in the same frame: wait for that.
        if (__mistrimulti_story_quest_level_ok(keys[i], active.current_stage)) q[$ keys[i]] = active.current_stage;
    }
    keys = QUEST_LOG.completed.keys();
    for (var i = 0; i < array_length(keys); i++) {
        if (__mistrimulti_story_quest_world(st, keys[i])) q[$ keys[i]] = MISTRIMULTI_STORY_DONE;
    }
    var sc = {};
    keys = MIST.scene_history.keys();
    for (var i = 0; i < array_length(keys); i++) {
        if (__mistrimulti_story_name(keys[i]) && __mistrimulti_story_scene_world(st, keys[i])) sc[$ keys[i]] = true;
    }
    var f = {};
    var names = __mistrimulti_story_concat(struct_get_names(st.gate_facts), mistrimulti_story_fixed_facts());
    for (var i = 0; i < array_length(names); i++) if (T2R.read(names[i]) == true) f[$ names[i]] = true;
    return { q: q, sc: sc, f: f, k: { n: SECRET_NARROWS, b: SECRET_BEACH, t: SECRET_TOWER } };
}

function __mistrimulti_story_concat(a, b) {
    var out = [];
    for (var i = 0; i < array_length(a); i++) array_push(out, a[i]);
    for (var i = 0; i < array_length(b); i++) array_push(out, b[i]);
    return out;
}

// What this game has that the mirror does not, as a wire delta (lists, bounded).
function __mistrimulti_story_up(st, local) {
    var out = { q: [], sc: [], f: [], k: {} };
    var names = struct_get_names(local.q);
    for (var i = 0; i < array_length(names); i++) {
        var old = st.q[$ names[i]] ?? -1;
        if (local.q[$ names[i]] > old) array_push(out.q, [names[i], local.q[$ names[i]]]);
    }
    names = struct_get_names(local.sc);
    for (var i = 0; i < array_length(names); i++) if (st.sc[$ names[i]] != true) array_push(out.sc, names[i]);
    names = struct_get_names(local.f);
    for (var i = 0; i < array_length(names); i++) if (st.f[$ names[i]] != true) array_push(out.f, names[i]);
    var counters = ["n", "b", "t"];
    for (var i = 0; i < 3; i++) if (local.k[$ counters[i]] > st.k[$ counters[i]]) out.k[$ counters[i]] = local.k[$ counters[i]];
    return out;
}

function __mistrimulti_story_empty(d) {
    return array_length(d.q) == 0 && array_length(d.sc) == 0 && array_length(d.f) == 0 && array_length(struct_get_names(d.k)) == 0;
}

// Merges a wire delta into the mirror with "max" and returns the part that advanced it. `strict` (the host, for a claim
// from the network) also requires that every entry is world-level by the game's own data.
function mistrimulti_story_merge(st, d, strict, limit) {
    var out = { q: [], sc: [], f: [], k: {} };
    if (!is_struct(d)) return out;
    var q = d[$ "q"];
    if (is_array(q)) {
        for (var i = 0; i < min(array_length(q), limit); i++) {
            var e = q[i];
            if (!is_array(e) || array_length(e) != 2 || !__mistrimulti_story_name(e[0])) continue;
            if (strict ? !(__mistrimulti_story_quest_world(st, e[0]) && __mistrimulti_story_quest_level_ok(e[0], e[1]))
                : !__mistrimulti_story_int(e[1], 0, MISTRIMULTI_STORY_DONE)) continue;
            if (e[1] > (st.q[$ e[0]] ?? -1)) {
                st.q[$ e[0]] = e[1];
                array_push(out.q, [e[0], e[1]]);
            }
        }
    }
    var sc = d[$ "sc"];
    if (is_array(sc)) {
        for (var i = 0; i < min(array_length(sc), limit); i++) {
            if (!__mistrimulti_story_name(sc[i]) || (strict && !__mistrimulti_story_scene_world(st, sc[i]))) continue;
            if (st.sc[$ sc[i]] != true) {
                st.sc[$ sc[i]] = true;
                array_push(out.sc, sc[i]);
            }
        }
    }
    var f = d[$ "f"];
    if (is_array(f)) {
        for (var i = 0; i < min(array_length(f), limit); i++) {
            if (!__mistrimulti_story_name(f[i]) || (strict && !__mistrimulti_story_fact_world(st, f[i]))) continue;
            if (st.f[$ f[i]] != true) {
                st.f[$ f[i]] = true;
                array_push(out.f, f[i]);
            }
        }
    }
    var k = d[$ "k"];
    if (is_struct(k)) {
        var counters = ["n", "b", "t"];
        for (var i = 0; i < 3; i++) {
            var v = k[$ counters[i]];
            if (__mistrimulti_story_int(v, 0, 1000) && v > st.k[$ counters[i]]) {
                st.k[$ counters[i]] = v;
                out.k[$ counters[i]] = v;
            }
        }
    }
    return out;
}

// ---- changing this game to match the mirror --------------------------------------------------------------------------

// The turn-in boxes of the stages before `upto` (the game removes them on the player who hands a stage in, see
// ActiveQuest.progress; every other game would keep an empty box of a stage that is over).
function __mistrimulti_story_clear_boxes(quest, upto) {
    for (var t = 0; t < min(upto, quest.tasks.count()); t++) {
        var req = quest.tasks.get(t).requirements[Requirement.SuppliedItems];
        if (req == undefined) continue;
        for (var j = 0; j < array_length(req); j++) {
            if (req[j].type != SupplyType.Chest) continue;
            var point = trellis_point_location_position(req[j].point);
            var grid = GRIDS[point.location_id];
            var ni = grid.node_index_for_cell(point.pos.x div 8, point.pos.y div 8);
            if (grid.node_object_id[ni] == ObjectId.TurnInBox) erase_object_node(grid, ni);
        }
    }
}

// A story quest the mirror is ahead on. Rewards are NOT given (they went to the player who handed the quest in) and the
// player's renown is untouched; only the quest log and the game's own bookkeeping change.
function mistrimulti_story_apply_quest(name, level) {
    var quest = QUESTS.get(name);
    if (quest == undefined) return false;
    if (QUEST_LOG.completed.contains(name)) return true;
    var active = QUEST_LOG.active.get(name);
    if (level >= MISTRIMULTI_STORY_DONE) {
        QUEST_LOG.active.remove(name);
        QUEST_LOG.completed.insert(name);
        QUEST_LOG.completion_timestamps.insert(name, CALENDAR.time);
        T2R.write("quest_" + name + "_in_progress", false);
        T2R.write("quest_" + name + "_complete", true);
        if (active != undefined) __mistrimulti_story_clear_boxes(quest, quest.tasks.count());
        return true;
    }
    if (active == undefined) return QUEST_LOG.start(name, level);
    if (active.current_stage < level) {
        __mistrimulti_story_clear_boxes(quest, level);
        active.current_stage = level;
        active.initialize_requirements_on_task(level);
    }
    return true;
}

// The lasting effects of a world cutscene on a game that did not watch it, the way the game applies them when a scene ends
// (clean_up_scene), minus what is the viewer's alone (hearts, status effects): the scene enters the history (the gates that
// read it open), its objects are gone, its area is cleared, its spell and mana are given. Items and baths are separate.
function __mistrimulti_story_scene_effects(name, c) {
    MIST.scene_history.insert(name);
    T2R.write("cutscene_seen_" + name, 1.0);
    trigger_scene_object_removals(name);
    if (c.nuke != undefined) {
        var town = GRIDS[LocationId.Town];
        for (var xx = c.nuke[0] div 8; xx < c.nuke[2] div 8; xx++) {
            for (var yy = c.nuke[1] div 8; yy < c.nuke[3] div 8; yy++) erase_object_node(town, town.node_index_for_cell(xx, yy));
        }
    }
    if (name == "upgrade_the_saturday_market_plaza") {
        spawn_prios_on_map(GRIDS[LocationId.Town], location_id_to_gm_room(LocationId.Town), "PriorityObjectsPlazaFixed", spawn_priority_object);
        fix_plaza_footsteps();
    }
    __mistrimulti_story_scene_spell(c);
}

// The scene's spell and mana, which the game gives to everybody who sees the scene (also to a player who did not watch it).
function __mistrimulti_story_scene_spell(c) {
    if (c.spell_to_unlock != undefined) ARI.learn_spell(c.spell_to_unlock);
    if (c.mana_to_set != undefined && ARI.mana_max < c.mana_to_set) {
        ARI.mana_max = c.mana_to_set;
        ARI.set_mana(c.mana_to_set);
    }
}

// The scene's items (to the bed if the pockets are full) and free baths; either can be left out.
function __mistrimulti_story_scene_gifts(name, c, items, baths) {
    try {
        if (items && array_length(c.given_items) > 0) mist_give_items_after_scene(c.given_items, player_wake_position());
        if (baths && c.baths > 0) ARI.free_baths += c.baths;
    } catch (e) {
        __mistrimulti_story_warn("The items of scene " + name + " could not be given: " + string(e));
    }
}

// A world cutscene this player did not watch and that cannot be shown: all of it is applied, silently, and it counts as played.
// The scene is now in this player's history, so this runs once per player, here or when they watch it themselves.
function mistrimulti_story_apply_scene(name) {
    if (!CUTSCENES.contains_key(name)) return false;
    var c = CUTSCENES.get(name);
    __mistrimulti_story_scene_effects(name, c);
    __mistrimulti_story_scene_gifts(name, c, true, true);
    return true;
}

// ---- the starter kit of a new character ---------------------------------------------------------------------------------------
// A new character in a world that has been played starts from the host's copy of the world, whose history holds the scenes the
// host's first day ran. Those scenes are never shown again to the newcomer, and the story's "a new character is not owed the past"
// rule paid nothing for them, so the first tools and seeds (which the game hands out in those scenes) were never given. The kit is
// the data of those scenes, read at run time (item ids, quantities, infusions, requirements, baths, spell, mana and the tutorial
// popup): what the game's own cleanup would have given a player who watched them. It is given once, when the new character's
// progress starts; the ledger is the world fact "mm_kit" (the JSON list of the scenes it covered), carried by the progress
// section story_rewards. Scenes that are not in the history yet are not part of it: the game shows them, or the story sync
// applies them with their items, the usual way.

// The game's first-day scenes, in the order of its own story test (TestSuite "main_story": prologue, day_zero, then the scenes
// the first day triggers on the farm and at the quest board). Which of them hand out items is read from the game's data.
function mistrimulti_story_kit_scenes() {
    return ["prologue", "day_zero", "farm_introduction", "adeline_quest_board"];
}

// Gives the kit once. Returns the scenes it covered ([] when there was nothing to give, or it was given before).
function mistrimulti_story_kit_grant() {
    var r = __mistrimulti_runtime();
    var covered = [];
    if (T2R.read("mm_kit") != undefined) return covered;
    var names = mistrimulti_story_kit_scenes();
    for (var i = 0; i < array_length(names); i++) {
        if (!CUTSCENES.contains_key(names[i]) || !MIST.scene_history.contains(names[i])) continue;
        if (CUTSCENES.get(names[i])[$ "requires_story_mode"] == true && STORY_ENABLED != true) continue;
        array_push(covered, names[i]);
    }
    // The ledger moves first: a gift that fails is lost rather than given twice.
    T2R.write("mm_kit", json_stringify(covered));
    for (var i = 0; i < array_length(covered); i++) {
        var c = CUTSCENES.get(covered[i]);
        try {
            __mistrimulti_story_scene_gifts(covered[i], c, true, true);
            __mistrimulti_story_scene_spell(c);
            var tutorial = c[$ "post_scene_tutorial"];
            if (tutorial != undefined) {
                if (!is_array(r[$ "kit_tutorials"])) r.kit_tutorials = [];
                array_push(r.kit_tutorials, tutorial);
            }
        } catch (e) {
            __mistrimulti_story_warn("The starter kit of scene " + covered[i] + " could not be given: " + string(e));
        }
    }
    if (array_length(covered) > 0) mmapi_log_info("mistrimulti", "Starter kit given for: " + json_stringify(covered));
    return covered;
}

// The game shows the tutorial popup a scene names after it (the tool tutorial, for the scene that gives the tools); the new
// character gets it once the editor is over and nothing else is running, one per pass.
function __mistrimulti_story_kit_pump(r) {
    var list = r[$ "kit_tutorials"];
    if (!is_array(list) || array_length(list) == 0 || !r.player_ready || r.character_pending) return;
    var tutorial = list[0];
    array_delete(list, 0, 1);
    if (!ARI.tutorials_seen[tutorial]) await_popup(spawn_tutorial, [tutorial]);
}

// ---- cutscenes that every player watches ---------------------------------------------------------------------------------------
// A world cutscene that the game can show again is applied here as a HELD scene: its lasting effects land at once (gates agree),
// it is in the history (gates that read it open) but the game is told it may repeat it ("can_repeat"), so the trigger the game
// itself arms for it (a room area, a quest task, the night) still starts it. When it runs, the switch goes off, the objects it
// removes are not removed twice and the personal rest is paid once. Quests that it starts or advances, or that wait for it,
// are held at the level before it in this game (__mistrimulti_story_cap) until the scene has been watched.

// The scene -> { quest, stage } index of the quest tasks that wait for a cutscene (the game starts such a scene when the quest
// is at that task and the player is in its area). Built once; false if the quest data cannot be read.
function __mistrimulti_story_view_index(st) {
    if (st.vindex != undefined) return st.vindex;
    var index = {};
    try {
        var keys = QUESTS.keys();
        for (var i = 0; i < array_length(keys); i++) {
            var quest = QUESTS.get(keys[i]);
            for (var t = 0; t < quest.tasks.count(); t++) {
                var targets = quest.tasks.get(t)[$ "query_targets"];
                if (targets == undefined) continue;
                for (var k = 0; k < targets.count(); k++) {
                    var target = targets.get(k);
                    if (target.type != QuestQueryType.Cutscene || !is_string(target.cutscene)) continue;
                    var old = index[$ target.cutscene];
                    if (old == undefined || t < old.stage) index[$ target.cutscene] = { quest: keys[i], stage: t };
                }
            }
        }
    } catch (e) {
        index = false;
        st.last_error = "view index: " + string(e);
        __mistrimulti_story_warn("The quest tasks that wait for a cutscene could not be read: " + string(e));
    }
    st.vindex = index;
    return index;
}

// Lowers a cap: the highest level a quest may have in a game while a held scene waits.
function __mistrimulti_story_cap_set(caps, quest, level) {
    if (caps[$ quest] == undefined || level < caps[$ quest]) caps[$ quest] = level;
}

// The conditions of a scene's own requirement that the mirror could change in a game before it watched the scene. A quest
// condition becomes a cap (stage k: held at k, active: not finished); inside an "or", an inversion or an alias it cannot: false,
// and the scene cannot be shown. The same for what the mirror makes true for everybody (a world fact, a world scene, a finished
// story quest) when the scene needs it to be false (`inv`: inside an inversion). CompletedQuest and SeenCutscene that must be
// true only wait for the mirror, which does that anyway.
function __mistrimulti_story_view_req(st, req, caps, depth, inv) {
    if (!is_array(req) || depth > 6) return true;
    for (var i = 0; i < Requirement.LEN; i++) {
        var v = req[i];
        if (v == undefined) continue;
        if (requirement_is_alias(i)) {
            if (!__mistrimulti_story_view_req(st, REQUIREMENT_ALIASES[i], caps, depth + 1, inv)) return false;
        } else if (i == Requirement.Or) {
            for (var j = 0; j < array_length(v); j++) if (!__mistrimulti_story_view_req(st, v[j], caps, depth + 1, inv)) return false;
        } else if (i == Requirement.Invert) {
            if (!__mistrimulti_story_view_req(st, v, caps, depth + 1, !inv)) return false;
        } else if (i == Requirement.CompletedQuest && inv && is_array(v)) {
            for (var j = 0; j < array_length(v); j++) if (is_array(v[j]) && __mistrimulti_story_quest_world(st, v[j][0])) return false;
        } else if (i == Requirement.SeenCutscene && inv && is_array(v)) {
            for (var j = 0; j < array_length(v); j++) if (is_string(v[j]) && __mistrimulti_story_scene_world(st, v[j])) return false;
        } else if (i == Requirement.WorldFactIs && is_array(v)) {
            for (var j = 0; j < array_length(v); j++) {
                var e = v[j];
                if (!is_array(e) || array_length(e) != 2 || !is_string(e[0]) || !__mistrimulti_story_fact_world(st, e[0])) continue;
                if ((e[1] == true) == inv) return false;
            }
        } else if (i == Requirement.QuestIsAtStage || i == Requirement.QuestIsActive) {
            if (depth > 0 || !is_array(v)) return false;
            for (var j = 0; j < array_length(v); j++) {
                if (i == Requirement.QuestIsAtStage) {
                    __mistrimulti_story_cap_set(caps, v[j].quest, v[j].stage);
                } else {
                    var quest = QUESTS.get(v[j]);
                    if (quest == undefined) return false;
                    __mistrimulti_story_cap_set(caps, v[j], quest.tasks.count() - 1);
                }
            }
        }
    }
    return true;
}

// Can this world scene be shown to a game that did not watch it? { caps: { quest: highest level } } or a reason why not (text).
function __mistrimulti_story_view_build(st, name) {
    if (name == "upgrade_the_saturday_market_plaza") return "it builds objects that cannot be built twice";
    var c = CUTSCENES.get(name);
    if (c[$ "can_repeat"] == true && st.view[$ name] == undefined) return "the game repeats it anyway";
    var index = __mistrimulti_story_view_index(st);
    if (!is_struct(index)) return "the quest data could not be read";
    var trigger = c[$ "trigger"];
    var query = index[$ name];
    if (!((trigger != undefined && trigger[$ "manually_activated"] != true) || c[$ "when_sleeping"] == true || query != undefined)) {
        return "nothing the game arms starts it (no area, no quest task, not at night)";
    }
    var caps = {};
    if (query != undefined) __mistrimulti_story_cap_set(caps, query.quest, query.stage);
    if (!__mistrimulti_story_view_req(st, c[$ "requirements"], caps, 0, false)) return "a condition it reads cannot be held";
    var started = c.quest_to_start;
    if (is_array(started)) for (var i = 0; i < array_length(started); i++) __mistrimulti_story_cap_set(caps, started[i], -1);
    var progressed = c.quest_to_progress;
    if (is_string(progressed) && __mistrimulti_story_quest_world(st, progressed) && caps[$ progressed] == undefined) {
        return "it advances a quest at a stage nobody can tell";
    }
    var out = {};
    var quests = struct_get_names(caps);
    for (var i = 0; i < array_length(quests); i++) if (__mistrimulti_story_quest_world(st, quests[i])) out[$ quests[i]] = caps[$ quests[i]];
    return { caps: out };
}

// The answer of the above for a world scene, remembered; a reason is logged once. undefined: not showable.
function __mistrimulti_story_view_info(st, name) {
    var m = st.vmemo[$ name];
    if (m == undefined) {
        try { m = __mistrimulti_story_view_build(st, name); }
        catch (e) { m = "the data could not be read: " + string(e); }
        st.vmemo[$ name] = m;
        if (is_string(m)) __mistrimulti_story_view_why(st, name, m);
    }
    return is_struct(m) ? m : undefined;
}

function __mistrimulti_story_view_why(st, name, text) {
    if (st.vlogged[$ name] != undefined) return;
    st.vlogged[$ name] = text;
    try { mmapi_log_info("mistrimulti", "Story scene " + name + " is applied without watching: " + text); } catch (e) {}
}

// Is a world scene that is new to this game to be shown? Its info, or undefined (then it is applied silently).
function __mistrimulti_story_view_wanted(st, name, local) {
    if (st.past[$ name] == true) return undefined;
    var info = __mistrimulti_story_view_info(st, name);
    if (info == undefined) return undefined;
    if (array_length(struct_get_names(st.view)) >= MISTRIMULTI_STORY_VIEW_MAX) {
        __mistrimulti_story_view_why(st, name, "too many scenes are waiting to be watched");
        return undefined;
    }
    var c = CUTSCENES.get(name);
    if (c[$ "requires_story_mode"] == true && STORY_ENABLED != true) return undefined;
    // A player who is ahead of the scene's quest (or has finished what it starts) would see the scene advance the quest twice.
    if (!__mistrimulti_story_caps_hold(info, local)) {
        __mistrimulti_story_view_why(st, name, "this player is already past the quest step it belongs to");
        return undefined;
    }
    return info;
}

function __mistrimulti_story_caps_hold(info, local) {
    var quests = struct_get_names(info.caps);
    for (var i = 0; i < array_length(quests); i++) if ((local.q[$ quests[i]] ?? -1) > info.caps[$ quests[i]]) return false;
    return true;
}

// The highest level the held scenes allow a quest in this game, or undefined.
function __mistrimulti_story_cap(st, quest) {
    var cap = undefined;
    var names = struct_get_names(st.view);
    for (var i = 0; i < array_length(names); i++) {
        var info = __mistrimulti_story_view_info(st, names[i]);
        if (info == undefined) continue;
        var level = info.caps[$ quest];
        if (level != undefined && (cap == undefined || level < cap)) cap = level;
    }
    return cap;
}

// The held scenes are a fact of the save ("mm_view": name -> game day), carried for a guest by the progress section story_rewards.
function __mistrimulti_story_view_save(st) {
    T2R.write("mm_view", array_length(struct_get_names(st.view)) == 0 ? undefined : json_stringify(st.view));
}

function __mistrimulti_story_view_arm(name, on) {
    if (CUTSCENES.contains_key(name)) CUTSCENES.get(name).can_repeat = on;
}

// A world that is left or a stream that ends: nothing stays switched on in the game's data.
function __mistrimulti_story_view_disarm(st) {
    try {
        var names = struct_get_names(st.view);
        for (var i = 0; i < array_length(names); i++) __mistrimulti_story_view_arm(names[i], false);
    } catch (e) {}
}

// The held scenes of this save, once per session: only those that are still in the history and can still be shown.
function __mistrimulti_story_view_init(st) {
    if (st.view_ok) return;
    st.view_ok = true;
    var text = T2R.read("mm_view");
    if (!is_string(text)) return;
    var data = undefined;
    try { data = json_parse(text); }
    catch (e) { data = undefined; }
    if (is_struct(data)) {
        var names = struct_get_names(data);
        for (var i = 0; i < array_length(names); i++) {
            var day = data[$ names[i]];
            if (!__mistrimulti_story_name(names[i]) || !__mistrimulti_story_int(day, 0, 1000000) || !CUTSCENES.contains_key(names[i])) continue;
            if (!MIST.scene_history.contains(names[i]) || __mistrimulti_story_view_info(st, names[i]) == undefined) continue;
            if (array_length(struct_get_names(st.view)) >= MISTRIMULTI_STORY_VIEW_MAX) break;
            st.view[$ names[i]] = day;
            __mistrimulti_story_view_arm(names[i], true);
        }
    }
    __mistrimulti_story_view_save(st);
}

// A world scene new to this game, to be shown: its effects land, the game may play it. Items and baths wait for the viewing.
function mistrimulti_story_apply_scene_view(st, name) {
    if (!CUTSCENES.contains_key(name)) return false;
    __mistrimulti_story_scene_effects(name, CUTSCENES.get(name));
    st.view[$ name] = total_days();
    __mistrimulti_story_view_arm(name, true);
    __mistrimulti_story_view_save(st);
    st.stats.shown++;
    return true;
}

// Every tick: a held scene that is running now is being watched. The game's repeat switch goes off at once (it must not offer
// the scene a third time) and its end does not remove the scene's objects again.
function __mistrimulti_story_views_watch(st) {
    if (array_length(struct_get_names(st.view)) == 0) return;
    var active = MIST.active_cutscene;
    if (!is_struct(active) || !is_string(active[$ "id"]) || st.view[$ active.id] == undefined) return;
    st.watching[$ active.id] = true;
    __mistrimulti_story_view_arm(active.id, false);
    MIST.blackboard.set("removed_scene_objects", true);
}

// A held scene is over: watched (played or skipped), or given up. `silent`: the personal rest of the scene is paid now.
function __mistrimulti_story_view_finish(st, name, how) {
    var c = CUTSCENES.get(name);
    __mistrimulti_story_view_arm(name, false);
    struct_remove(st.view, name);
    struct_remove(st.watching, name);
    if (how == "viewed") {
        // The game paid the baths, and the items unless the scene gives its items only once (the scene was in the history).
        if (c[$ "give_items_once"] == true) __mistrimulti_story_scene_gifts(name, c, true, false);
        st.stats.viewed++;
    } else if (how != "gone") {
        __mistrimulti_story_scene_gifts(name, c, true, true);
        st.stats.silent++;
        __mistrimulti_story_view_why(st, name, how);
    }
}

// Start of a pass: sorts out the held scenes. Watched ones are done; one that waits too long, that cannot start any more
// (the player went past its quest step) or that is no longer known is applied silently, so nothing waits for ever.
function __mistrimulti_story_views(st, local) {
    __mistrimulti_story_view_init(st);
    var names = struct_get_names(st.view);
    var changed = false;
    for (var i = 0; i < array_length(names); i++) {
        var name = names[i];
        var info = __mistrimulti_story_view_info(st, name);
        var how = "";
        if (!MIST.scene_history.contains(name)) how = "gone";
        else if (st.watching[$ name] == true || MIST.scenes_played_today.contains(name)) how = "viewed";
        else if (info == undefined) how = "the scene can no longer be shown";
        else if (total_days() - st.view[$ name] >= MISTRIMULTI_STORY_PATIENCE) how = "not watched within " + string(MISTRIMULTI_STORY_PATIENCE) + " days";
        else if (!__mistrimulti_story_caps_hold(info, local)) how = "this player went past the quest step it belongs to";
        if (how == "") {
            __mistrimulti_story_view_arm(name, true);
            continue;
        }
        __mistrimulti_story_view_finish(st, name, how);
        changed = true;
    }
    if (changed) __mistrimulti_story_view_save(st);
}

function __mistrimulti_story_set_counter(key, value) {
    if (key == "n") SECRET_NARROWS = value;
    else if (key == "b") SECRET_BEACH = value;
    else SECRET_TOWER = value;
}

// Brings the game up to the mirror (a few changes per pass; each one guarded, a refused one is not tried again).
function __mistrimulti_story_down(st, local) {
    var left = MISTRIMULTI_STORY_APPLY_MAX;
    // Scenes first: a scene that is held decides, before any quest changes, how far its quests may be brought.
    var names = struct_get_names(st.sc);
    for (var i = 0; i < array_length(names) && left > 0; i++) {
        var key = "s:" + names[i];
        if (local.sc[$ names[i]] == true || MIST.scene_history.contains(names[i]) || st.bad[$ key] == true) continue;
        left--;
        try {
            var shown = __mistrimulti_story_view_wanted(st, names[i], local) != undefined;
            if (shown ? mistrimulti_story_apply_scene_view(st, names[i]) : mistrimulti_story_apply_scene(names[i])) st.stats.scenes++;
            else { st.bad[$ key] = true; st.stats.refused++; }
        } catch (e) {
            st.bad[$ key] = true;
            st.stats.refused++;
            st.last_error = key + ": " + string(e);
            __mistrimulti_story_warn("Story scene " + names[i] + " could not be applied: " + string(e));
        }
    }
    names = struct_get_names(st.q);
    for (var i = 0; i < array_length(names) && left > 0; i++) {
        var key = "q:" + names[i];
        // A quest that a held scene starts, advances or waits for is brought only as far as the scene allows.
        var want = st.q[$ names[i]];
        var cap = __mistrimulti_story_cap(st, names[i]);
        if (cap != undefined && cap < want) want = cap;
        if (want <= (local.q[$ names[i]] ?? -1) || st.bad[$ key] == true) continue;
        left--;
        try {
            if (mistrimulti_story_apply_quest(names[i], want)) st.stats.applied++;
            else { st.bad[$ key] = true; st.stats.refused++; }
        } catch (e) {
            st.bad[$ key] = true;
            st.stats.refused++;
            st.last_error = key + ": " + string(e);
            __mistrimulti_story_warn("Story quest " + names[i] + " could not be applied: " + string(e));
        }
    }
    names = struct_get_names(st.f);
    for (var i = 0; i < array_length(names); i++) if (local.f[$ names[i]] != true) T2R.write(names[i], true);
    var counters = ["n", "b", "t"];
    for (var i = 0; i < 3; i++) if (st.k[$ counters[i]] > local.k[$ counters[i]]) __mistrimulti_story_set_counter(counters[i], st.k[$ counters[i]]);
}

// ---- events ------------------------------------------------------------------------------------------------------------

// The host merges a guest's claim. Everything is checked against the game's data; the result (the part that advanced the
// world) goes to every guest, and the host's own game picks it up in its next pass.
function mistrimulti_story_claim_request(from, data, ctx) {
    if (!__mistrimulti_story_on("host") || from == 0) return { q: [], sc: [], f: [], k: {} };
    var st = __mistrimulti_story();
    if (!st.ready) return false;
    return mistrimulti_story_merge(st, data, true, MISTRIMULTI_STORY_CLAIM_MAX);
}

function mistrimulti_story_claim_result(from, result, ctx) {
    if (!__mistrimulti_story_on("join")) return true;
    mistrimulti_story_merge(__mistrimulti_story(), result, false, MISTRIMULTI_STORY_CLAIM_MAX);
    return true;
}

// Does the mirror have what a claim key ("q:name", "s:name", "f:name", "k:counter") asked for?
function __mistrimulti_story_mirror_has(st, key, n) {
    var kind = string_char_at(key, 1);
    var name = string_copy(key, 3, string_length(key) - 2);
    if (kind == "q") return (st.q[$ name] ?? -1) >= n;
    if (kind == "s") return st.sc[$ name] == true;
    if (kind == "f") return st.f[$ name] == true;
    return (st.k[$ name] ?? 0) >= n;
}

function mistrimulti_story_claim_reply(from, result, ctx) {
    if (!__mistrimulti_story_on("join")) return true;
    var st = __mistrimulti_story();
    var keys = struct_get_names(st.pend);
    for (var i = 0; i < array_length(keys); i++) {
        var p = st.pend[$ keys[i]];
        if (p.id != ctx.id) continue;
        struct_remove(st.pend, keys[i]);
        // Answered, and the host's world still lacks it: the host refused it (it does not know the quest, or by its data the
        // entry is not the world's). It is not asked again in this session. (A lost or expired answer says nothing: ask again.)
        if (ctx[$ "lost"] != true && ctx[$ "expired"] != true && !__mistrimulti_story_mirror_has(st, keys[i], p.n)) {
            st.bad[$ "u:" + keys[i]] = true;
            st.stats.refused++;
        }
    }
    return true;
}

function mistrimulti_story_delta_event(from, data, ctx) {
    if (!__mistrimulti_story_on("join") || from != 0) return true;
    mistrimulti_story_merge(__mistrimulti_story(), data, false, MISTRIMULTI_STORY_CLAIM_MAX);
    return true;
}

function mistrimulti_story_snapshot_blob(from, text, meta) {
    if (!__mistrimulti_story_on("join") || from != 0) return true;
    var st = __mistrimulti_story();
    var data = undefined;
    try { data = json_parse(text); }
    catch (e) { return true; }
    if (!is_struct(data)) return true;
    __mistrimulti_story_follow(st, __mistrimulti_story_host_stream());
    mistrimulti_story_merge(st, data, false, MISTRIMULTI_STORY_LIST_MAX);
    // A new character is not owed the story so far, scenes included: what is over when it arrives is never shown to it.
    if (T2R.read("mm_paid_init") != true) {
        var done = struct_get_names(st.sc);
        for (var i = 0; i < array_length(done); i++) st.past[$ done[i]] = true;
    }
    if (typeof(data[$ "se"]) == "bool" && STORY_ENABLED != data.se) STORY_ENABLED = data.se;
    st.ready = true;
    return true;
}

// The host's game sees a guest (a new session, or the same one back after an absence): it gets the snapshot.
// (A guest learns that the host is a new session from the stream id of the host's frames, see the guest pass.)
function mistrimulti_story_peer(slot, joined, stream) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || r.mode != "host" || !joined) return;
    var st = __mistrimulti_story();
    for (var i = 0; i < array_length(st.snaps); i++) if (st.snaps[i] == slot) return;
    array_push(st.snaps, slot);
}

function mistrimulti_story_gap(slot, base, expected) {
    if (slot == 0 && __mistrimulti_runtime().mode == "join") __mistrimulti_story().want_at = -1000000;
}

function mistrimulti_story_sync_event(from, data, ctx) {
    if (!__mistrimulti_story_on("host") || from == 0) return true;
    var st = __mistrimulti_story();
    for (var i = 0; i < array_length(st.snaps); i++) if (st.snaps[i] == from) return true;
    array_push(st.snaps, from);
    return true;
}

// ---- villagers: day plan and samples ------------------------------------------------------------------------------------

// The schedule a villager follows, or "" (a villager that has none yet, or a game that cannot tell).
function __mistrimulti_story_schedule_name(i) {
    try {
        var name = T2R.schedule_name(i);
        return is_string(name) ? name : "";
    } catch (e) {
        return "";
    }
}

function mistrimulti_story_npc_capture() {
    var s = [];
    var l = [];
    var a = [];
    for (var i = 0; i < NpcId.LEN; i++) {
        array_push(s, __mistrimulti_story_schedule_name(i));
        var npc = NPCS[i];
        array_push(l, npc.location_position == undefined ? -1 : npc.location_position.location_id);
        var act = npc.activity_handler.activity;
        array_push(a, act == undefined ? -1 : act.id);
    }
    return { s: s, l: l, a: a };
}

function __mistrimulti_story_plan_valid(d) {
    if (!is_struct(d) || !__mistrimulti_story_int(d[$ "d"], 1, 1000000) || typeof(d[$ "cf"]) != "bool") return false;
    var s = d[$ "s"];
    if (!is_array(s) || array_length(s) != NpcId.LEN) return false;
    for (var i = 0; i < NpcId.LEN; i++) if (!is_string(s[i]) || string_length(s[i]) > 160) return false;
    return true;
}

function __mistrimulti_story_pos_valid(d) {
    if (!is_struct(d) || !__mistrimulti_story_int(d[$ "d"], 1, 1000000)) return false;
    var l = d[$ "l"];
    var a = d[$ "a"];
    if (!is_array(l) || !is_array(a) || array_length(l) != NpcId.LEN || array_length(a) != NpcId.LEN) return false;
    for (var i = 0; i < NpcId.LEN; i++) {
        if (!__mistrimulti_story_int(l[i], -1, 1000) || !__mistrimulti_story_int(a[i], -1, 1000)) return false;
    }
    return true;
}

function mistrimulti_story_plan_event(from, data, ctx) {
    if (!__mistrimulti_story_on("join") || from != 0 || !__mistrimulti_story_plan_valid(data)) return true;
    var st = __mistrimulti_story();
    // A plan for an earlier day than the one we hold is late (it was queued behind a loss): ignore it, unless it comes from
    // another host session (which may have restarted from an older save).
    var hs = __mistrimulti_story_host_stream();
    if (!is_struct(st.plan) || st.plan_stream != hs || data.d >= st.plan.d) {
        st.plan = data;
        st.plan_stream = hs;
    }
    return true;
}

function mistrimulti_story_pos_event(from, data, ctx) {
    if (!__mistrimulti_story_on("join") || from != 0 || !__mistrimulti_story_pos_valid(data)) return true;
    var st = __mistrimulti_story();
    var hs = __mistrimulti_story_host_stream();
    if (!is_struct(st.pos) || st.pos_stream != hs || data.d >= st.pos.d) {
        st.pos = data;
        st.pos_stream = hs;
    }
    return true;
}

// Host: sends the day plan when it changes (a new day, or a swap the game made) and the sample when it changes.
function __mistrimulti_story_npc_host(st) {
    var cap = mistrimulti_story_npc_capture();
    var plan = { d: total_days(), s: cap.s, cf: CANCEL_FESTIVALS == true };
    var plan_sig = json_stringify(plan);
    if (plan_sig != st.plan_sig && mistrimulti_event_can_emit(2) && mistrimulti_event_emit("npc_plan", plan, -1)) st.plan_sig = plan_sig;
    var pos = { d: plan.d, l: cap.l, a: cap.a };
    var pos_sig = json_stringify(pos);
    if (pos_sig != st.pos_sig && mistrimulti_event_can_emit(2) && mistrimulti_event_emit("npc_pos", pos, -1)) st.pos_sig = pos_sig;
}

function __mistrimulti_story_known_schedule(st, name) {
    if (st.sched == undefined) {
        st.sched = {};
        var names = T2R.schedule_names();
        for (var i = 0; i < array_length(names); i++) st.sched[$ names[i]] = true;
    }
    return st.sched[$ name] == true;
}

function __mistrimulti_story_swap(st, npc, name) {
    // The game's own deferred request: it swaps the schedule (and fast-forwards it to the time now) as soon as the
    // villager is not in the room the player is in, so nobody sees a villager jump.
    npc.swap_schedule_request = { schedule_name: name, finish: false };
    st.stats.swaps++;
}

// Guest: steer the villagers to the host's plan. Only a villager out of the player's sight is ever moved.
function __mistrimulti_story_npc_guest(st) {
    var plan = st.plan;
    if (!is_struct(plan) || plan.d != total_days()) return;
    if (CANCEL_FESTIVALS != plan.cf) CANCEL_FESTIVALS = plan.cf;
    var pos = is_struct(st.pos) && st.pos.d == plan.d ? st.pos : undefined;
    for (var i = 0; i < NpcId.LEN; i++) {
        var want = plan.s[i];
        var npc = NPCS[i];
        var key = string(i);
        // A villager this game moved into the farm house today is the house pass's (until the host's plan says the same, it may
        // still show the village schedule: that would only swap them back out).
        if (st.homes[$ key] == plan.d) continue;
        if (want == "" || npc.swap_schedule_request != undefined || !__mistrimulti_story_known_schedule(st, want)) continue;
        if (__mistrimulti_story_schedule_name(i) != want) {
            __mistrimulti_story_swap(st, npc, want);
            st.miss[$ key] = 0;
            continue;
        }
        if (pos == undefined || npc.location_position == undefined) continue;
        var here = npc.location_position.location_id;
        var unseen = here != CURRENT_LOCATION_ID && pos.l[i] != CURRENT_LOCATION_ID;
        if (pos.l[i] != -1 && here != pos.l[i]) {
            st.miss[$ key] = (st.miss[$ key] ?? 0) + 1;
            if (st.miss[$ key] >= MISTRIMULTI_STORY_MISS && unseen) {
                __mistrimulti_story_swap(st, npc, want);
                st.miss[$ key] = 0;
            }
            continue;
        }
        if (!MISTRIMULTI_STORY_ACTIVITIES) continue;
        var handler = npc.activity_handler;
        var mine = handler.activity == undefined ? -1 : handler.activity.id;
        if (pos.a[i] >= 0 && pos.a[i] != mine && unseen && handler.state != ActivityState.Traveling && handler.request == undefined
            && pos.a[i] < Activity.LEN && ACTIVITIES.get(pos.a[i]) != undefined) {
            st.miss[$ key] = (st.miss[$ key] ?? 0) + 1;
            if (st.miss[$ key] >= MISTRIMULTI_STORY_MISS) {
                handler.request_activity(pos.a[i]);
                st.stats.steers++;
                st.miss[$ key] = 0;
            }
        } else {
            st.miss[$ key] = 0;
        }
    }
}

// ---- the pass ----------------------------------------------------------------------------------------------------------

// Host: the snapshot a game gets when it joins (and again on request): the whole world story, the plan and the sample.
function __mistrimulti_story_snapshot(st) {
    var up = { q: [], sc: [], f: [], k: st.k, se: STORY_ENABLED == true };
    var names = struct_get_names(st.q);
    for (var i = 0; i < min(array_length(names), MISTRIMULTI_STORY_LIST_MAX); i++) array_push(up.q, [names[i], st.q[$ names[i]]]);
    names = struct_get_names(st.sc);
    for (var i = 0; i < min(array_length(names), MISTRIMULTI_STORY_LIST_MAX); i++) array_push(up.sc, names[i]);
    names = struct_get_names(st.f);
    for (var i = 0; i < min(array_length(names), MISTRIMULTI_STORY_LIST_MAX); i++) array_push(up.f, names[i]);
    return up;
}

function __mistrimulti_story_send_snapshots(st) {
    while (array_length(st.snaps) > 0) {
        var slot = st.snaps[0];
        if (!mistrimulti_event_can_emit(3) || !mistrimulti_event_send_blob("story_snapshot", json_stringify(__mistrimulti_story_snapshot(st)), slot)) return;
        array_delete(st.snaps, 0, 1);
        // The plan and the sample follow the snapshot in the same stream: a joining game never steers villagers on a stale plan.
        var cap = mistrimulti_story_npc_capture();
        mistrimulti_event_emit("npc_plan", { d: total_days(), s: cap.s, cf: CANCEL_FESTIVALS == true }, slot);
        mistrimulti_event_emit("npc_pos", { d: total_days(), l: cap.l, a: cap.a }, slot);
    }
}

// Bridge tick (20 Hz) while a world is loaded and the player is in it.
function mistrimulti_story_tick() {
    var r = __mistrimulti_runtime();
    if (!r.enabled || ARI == undefined) return;
    try {
        var st = __mistrimulti_story();
        st.ticks++;
        // A held scene that begins to run is being watched (every tick: a short scene must not slip through).
        if (MIST.is_running()) __mistrimulti_story_views_watch(st);
        if (st.ticks mod MISTRIMULTI_STORY_PASS != 0) return;
        // A joining game gets its snapshot at once, even while the host watches a cutscene: it is only data.
        if (r.mode == "host" && st.ready) __mistrimulti_story_send_snapshots(st);
        // A cutscene is private and changes the game while it runs; the end-of-day sequence rebuilds the world. In both,
        // nothing is compared or applied. The next pass sees the finished state.
        if (MIST.is_running() || ARI.end_of_day_status != undefined) return;
        if (r.mode == "join") __mistrimulti_story_kit_pump(r);
        if (r.mode == "host") __mistrimulti_story_host_pass(st);
        else __mistrimulti_story_guest_pass(st);
        if (st.ticks mod MISTRIMULTI_STORY_NPC_PASS == 0) __mistrimulti_story_house_pass(st, false);
        if (st.ticks mod MISTRIMULTI_STORY_NPC_PASS == 0 && st.ready) {
            if (r.mode == "host" && r.mask != 0) __mistrimulti_story_npc_host(st);
            else if (r.mode == "join") __mistrimulti_story_npc_guest(st);
        }
    } catch (e) {
        __mistrimulti_story().last_error = string(e);
        __mistrimulti_story_warn("Story sync failed: " + string(e));
    }
}

function __mistrimulti_story_host_pass(st) {
    var local = __mistrimulti_story_local(st);
    __mistrimulti_story_own_steps(st, local);
    __mistrimulti_story_views(st, local);
    if (!st.ready) {
        // First pass of this session: the host's own game is the world as it was saved. Nobody needs a delta for it.
        mistrimulti_story_merge(st, __mistrimulti_story_up(st, local), false, MISTRIMULTI_STORY_LIST_MAX);
        st.ready = true;
    } else if (mistrimulti_event_can_emit(12)) {
        // At most 4 events per list in a pass, and only when they fit in the queue: what does not fit is still "ahead" of the
        // mirror and goes in the next pass, so a full queue can delay a delta but never lose one.
        var accepted = mistrimulti_story_merge(st, __mistrimulti_story_up(st, local), false, 4 * MISTRIMULTI_STORY_CLAIM_MAX);
        if (!__mistrimulti_story_empty(accepted)) __mistrimulti_story_broadcast(accepted);
    }
    __mistrimulti_story_down(st, local);
    __mistrimulti_story_rewards(st);
}

// A delta is cut into events that fit (a name has at most 96 characters, an event at most 8 KB). Scenes go first: a game that
// learns of a held scene before it learns of the quest levels that belong to it holds those quests back (see the cap).
function __mistrimulti_story_broadcast(d) {
    for (var i = 0; i < array_length(d.sc); i += MISTRIMULTI_STORY_CLAIM_MAX) {
        mistrimulti_event_emit("story_delta", { q: [], sc: __mistrimulti_story_slice(d.sc, i), f: [], k: {} });
    }
    for (var i = 0; i < array_length(d.q); i += MISTRIMULTI_STORY_CLAIM_MAX) {
        mistrimulti_event_emit("story_delta", { q: __mistrimulti_story_slice(d.q, i), sc: [], f: [], k: {} });
    }
    for (var i = 0; i < array_length(d.f); i += MISTRIMULTI_STORY_CLAIM_MAX) {
        mistrimulti_event_emit("story_delta", { q: [], sc: [], f: __mistrimulti_story_slice(d.f, i), k: {} });
    }
    if (array_length(struct_get_names(d.k)) > 0) mistrimulti_event_emit("story_delta", { q: [], sc: [], f: [], k: d.k });
}

function __mistrimulti_story_slice(list, start) {
    var out = [];
    for (var i = start; i < min(array_length(list), start + MISTRIMULTI_STORY_CLAIM_MAX); i++) array_push(out, list[i]);
    return out;
}

function __mistrimulti_story_guest_pass(st) {
    var r = __mistrimulti_runtime();
    var hs = __mistrimulti_story_host_stream();
    if ((r.mask & 1) == 0 || hs == "") return;
    __mistrimulti_story_follow(st, hs);
    if (!st.ready) {
        // The host sends the snapshot by itself when it sees us; ask again if it has not come after 10 seconds.
        if (st.ticks - st.want_at >= MISTRIMULTI_STORY_RETRY && mistrimulti_event_emit("story_sync", {}, 0)) st.want_at = st.ticks;
        return;
    }
    var local = __mistrimulti_story_local(st);
    __mistrimulti_story_own_steps(st, local);
    __mistrimulti_story_views(st, local);
    var up = __mistrimulti_story_up(st, local);
    var claim = { q: [], sc: [], f: [], k: up.k };
    // Entries already claimed at this level are in flight: do not repeat them.
    for (var i = 0; i < array_length(up.q) && array_length(claim.q) < MISTRIMULTI_STORY_CLAIM_MAX; i++) {
        var p = st.pend[$ "q:" + up.q[i][0]];
        if (st.bad[$ "u:q:" + up.q[i][0]] == true) continue;
        if (!is_struct(p) || p.n < up.q[i][1]) array_push(claim.q, up.q[i]);
    }
    for (var i = 0; i < array_length(up.sc) && array_length(claim.sc) < MISTRIMULTI_STORY_CLAIM_MAX; i++) {
        if (!is_struct(st.pend[$ "s:" + up.sc[i]]) && st.bad[$ "u:s:" + up.sc[i]] != true) array_push(claim.sc, up.sc[i]);
    }
    for (var i = 0; i < array_length(up.f) && array_length(claim.f) < MISTRIMULTI_STORY_CLAIM_MAX; i++) {
        if (!is_struct(st.pend[$ "f:" + up.f[i]]) && st.bad[$ "u:f:" + up.f[i]] != true) array_push(claim.f, up.f[i]);
    }
    var counters = struct_get_names(claim.k);
    for (var i = 0; i < array_length(counters); i++) {
        var p = st.pend[$ "k:" + counters[i]];
        if ((is_struct(p) && p.n >= claim.k[$ counters[i]]) || st.bad[$ "u:k:" + counters[i]] == true) struct_remove(claim.k, counters[i]);
    }
    if (!__mistrimulti_story_empty(claim)) {
        var id = mistrimulti_event_request("story_claim", claim);
        if (id != undefined) {
            st.stats.claims++;
            for (var i = 0; i < array_length(claim.q); i++) st.pend[$ "q:" + claim.q[i][0]] = { n: claim.q[i][1], id: id };
            for (var i = 0; i < array_length(claim.sc); i++) st.pend[$ "s:" + claim.sc[i]] = { n: 1, id: id };
            for (var i = 0; i < array_length(claim.f); i++) st.pend[$ "f:" + claim.f[i]] = { n: 1, id: id };
            counters = struct_get_names(claim.k);
            for (var i = 0; i < array_length(counters); i++) st.pend[$ "k:" + counters[i]] = { n: claim.k[$ counters[i]], id: id };
        }
    }
    __mistrimulti_story_down(st, local);
    __mistrimulti_story_rewards(st);
}

// ---- rewards of story steps the player did not do ------------------------------------------------------------------------
// Ledger: how far this player has been paid for each story quest (see the header). A quest at level L has had the rewards of its
// tasks 0..L-1 given; level DONE adds the quest's own rewards (items, and the renown entry the game files on completion).

function __mistrimulti_story_paid(name) {
    var level = T2R.read("mm_paid_" + name);
    return is_real(level) ? level : 0;
}

// Before a pass changes anything: a level that rose since the end of the last pass (a quest that was not there counts as rising
// from nothing) was this player's own step, which the game has paid, so the ledger moves up with it. (A level this file raised is
// recorded in `seen` at the end of its pass. In the first pass of a session nothing counts: the game was just loaded.)
function __mistrimulti_story_own_steps(st, local) {
    if (!st.seen_ok || T2R.read("mm_paid_init") != true) return;
    var names = struct_get_names(local.q);
    for (var i = 0; i < array_length(names); i++) {
        var seen = st.seen[$ names[i]] ?? -1;
        if (local.q[$ names[i]] > seen && local.q[$ names[i]] > __mistrimulti_story_paid(names[i])) {
            T2R.write("mm_paid_" + names[i], local.q[$ names[i]]);
        }
    }
}

// A reward that starts a quest: a story quest is the mirror's business, any other is this player's own.
function __mistrimulti_story_reward_quest(name) {
    var quest = QUESTS.get(name);
    if (quest == undefined || quest.category == QuestCategory.Story) return;
    if (QUEST_LOG.active.contains_key(name) || QUEST_LOG.completed.contains(name)) return;
    QUEST_LOG.start(name);
}

function __mistrimulti_story_grant(rewards) {
    var out = List();
    for (var i = 0; i < rewards.count(); i++) {
        var reward = rewards.get(i);
        if (reward.type == QuestRewardType.Quest) __mistrimulti_story_reward_quest(reward.quest_name);
        else out.push(reward);
    }
    grant_quest_rewards(out);
}

// The rewards of the levels from..to-1 of a quest, as the game gives them when the player hands the stages in.
function __mistrimulti_story_pay(name, from, to) {
    var quest = QUESTS.get(name);
    if (quest == undefined) return;
    for (var t = from; t < min(to, quest.tasks.count()); t++) __mistrimulti_story_grant(quest.tasks.get(t).reward_list);
    if (to < MISTRIMULTI_STORY_DONE) return;
    __mistrimulti_story_grant(quest.reward_list);
    for (var j = 0; j < quest.reward_list.count(); j++) {
        if (quest.reward_list.get(j).type == QuestRewardType.Renown) {
            ARI.pending_renown_entries.push(RenownEntry.Quest(name));
            break;
        }
    }
}

// After the pass brought this game up to the mirror. First time in this player's ledger: everything that exists now counts as
// paid (a new character, or a record from before the ledger: the story so far is not owed). Afterwards: whatever this game has
// passed that the mirror also holds, and the player has not been paid for, is paid now, once. The ledger moves first, so a
// reward that fails is lost rather than given twice.
function __mistrimulti_story_rewards(st) {
    if (!st.data_ok) return;
    var local = __mistrimulti_story_local(st);
    var names = struct_get_names(local.q);
    var more = struct_get_names(st.q);
    for (var i = 0; i < array_length(more); i++) if (local.q[$ more[i]] == undefined) array_push(names, more[i]);
    var left = MISTRIMULTI_STORY_PAY_MAX;
    var paid_any = false;
    var first = T2R.read("mm_paid_init") != true;
    for (var i = 0; i < array_length(names); i++) {
        var have = local.q[$ names[i]] ?? -1;
        var level = max(have, st.q[$ names[i]] ?? -1);
        var paid = __mistrimulti_story_paid(names[i]);
        if (first) {
            if (level > 0) T2R.write("mm_paid_" + names[i], level);
            continue;
        }
        var target = min(have, st.q[$ names[i]] ?? -1);
        if (target <= paid || left <= 0) continue;
        left--;
        T2R.write("mm_paid_" + names[i], target);
        try {
            __mistrimulti_story_pay(names[i], paid, target);
            st.stats.paid++;
            paid_any = true;
        } catch (e) {
            st.last_error = "pay " + names[i] + ": " + string(e);
            __mistrimulti_story_warn("The rewards of story quest " + names[i] + " could not be given: " + string(e));
        }
    }
    if (first) T2R.write("mm_paid_init", true);
    // The levels this pass ends with: a rise before the next pass is the player's.
    st.seen = local.q;
    st.seen_ok = true;
    if (paid_any) {
        try { create_notification(ANCHOR.wrap_for_local("Story reward: you received the rewards of a story step another player completed.")); }
        catch (e) {}
    }
}

// ---- spouses of other players live at the farm -------------------------------------------------------------------------------
// In the game a villager lives in the farm house (the "roommate" schedule, a place next to the player's bed, a routine at home)
// when the villager is the spouse of the player of that game; that is a fact of the game's own relationship status, which is
// the player's own. So a game moves in the spouses of the other players itself, the way the game does it for its own, using the
// game's own functions. The host's registry (MistriMultiProgress.gml) says who is married to whom, for players who are away too.

// Juniper and Hayden bring their pet when they are the spouse (Npc.is_roommate in the game).
function __mistrimulti_story_pet_of(name) {
    if (name == "juniper") return "dozy";
    if (name == "hayden") return "henrietta";
    return "";
}

// The villagers who live at the farm in this game because of another player, in villager order: { i, pet }. A villager who
// is a roommate here already (this player's own spouse and pet) is the game's.
function __mistrimulti_story_housemates() {
    var r = __mistrimulti_runtime();
    var map = r.mode == "host" ? r[$ "romance_spouse"] : r[$ "romance_spouse_view"];
    var out = [];
    if (!is_struct(map)) return out;
    for (var i = 0; i < NpcId.LEN; i++) {
        var name = npc_id_to_string(i);
        var owner = map[$ name];
        if (!is_string(owner) || owner == r.uid || NPCS[i].is_roommate()) continue;
        // Only a villager the player can marry (a stored record can say anything; the registry itself keeps one spouse a player).
        var kind = NPCS[i].prototype;
        if (is_struct(kind) && kind[$ "dateable"] == false) continue;
        array_push(out, { i: i, pet: false });
        var pet = try_string_to_npc_id(__mistrimulti_story_pet_of(name));
        if (pet != undefined && !NPCS[pet].is_roommate()) array_push(out, { i: pet, pet: true });
    }
    return out;
}

// The schedule the game gives its roommates today (NpcDatabase.npcs_on_new_day).
function __mistrimulti_story_roommate_schedule() {
    if (CALENDAR.day_type() == Day.Friday) return "Schedules/roommate_schedule_friday";
    if (todays_festival() != undefined) return "Schedules/roommate_schedule_festival";
    return "Schedules/roommate_schedule";
}

// Wakes up at home: next to the player's bed, or on the floor of the house when the bed is taken. The game's own function
// puts a spouse in the bed: it asks the villager's relationship status, so the status reads "spouse" for that one call.
function __mistrimulti_story_to_bed(npc, mate, bed_taken) {
    if (mate.pet) {
        roommate_to_sleep(npc);
    } else if (bed_taken) {
        npc.location_position = roommate_home_position(npc);
        npc.talk_flag = false;
    } else {
        var key = npc_id_to_string(mate.i) + "_status";
        var old = T2R.read(key);
        T2R.write(key, "spouse");
        var failure = undefined;
        try { roommate_to_sleep(npc); }
        catch (e) { failure = e; }
        T2R.write(key, old);
        if (failure != undefined) throw failure;
    }
    npc.brain_dead = false;
}

// Moves one villager in. True when they live at home today. At the start of a day (the player has just woken) out of sight, the
// game's own swap is made now and the villager starts the day asleep; in the middle of a day, or in the room the player is in,
// the game's deferred swap does it as soon as the villager is out of sight (as for every schedule this file steers).
function __mistrimulti_story_move_in(st, mate, morning, bed_taken) {
    var key = string(mate.i);
    var want = __mistrimulti_story_roommate_schedule();
    if (!__mistrimulti_story_known_schedule(st, want)) return false;
    if (__mistrimulti_story_schedule_name(mate.i) == want) return true;
    var npc = NPCS[mate.i];
    var here = npc.location_position != undefined && npc.location_position.location_id == CURRENT_LOCATION_ID;
    if (morning && !here) {
        perform_schedule_swap(mate.i, want, false, CALENDAR.unified_time());
        __mistrimulti_story_to_bed(npc, mate, bed_taken);
        st.stats.swaps++;
        return true;
    }
    if (npc.swap_schedule_request == undefined && (st.tries[$ key] ?? 0) < MISTRIMULTI_STORY_HOME_TRIES) {
        st.tries[$ key] = (st.tries[$ key] ?? 0) + 1;
        __mistrimulti_story_swap(st, npc, want);
    }
    return false;
}

// A villager the registry no longer lists (the marriage ended) goes back to the schedule the game would give them.
function __mistrimulti_story_move_out(st, index) {
    var npc = NPCS[index];
    if (string_pos("roommate", __mistrimulti_story_schedule_name(index)) > 0 && npc.swap_schedule_request == undefined) {
        __mistrimulti_story_swap(st, npc, T2R.request_schedule(index));
    }
}

// `morning`: the game has just started a new day (the hook) and moved every villager to the start of their schedule.
function __mistrimulti_story_house_pass(st, morning) {
    var day = total_days();
    if (st.tries_day != day) {
        st.tries_day = day;
        st.tries = {};
    }
    var mates = __mistrimulti_story_housemates();
    var listed = {};
    var bed_taken = ARI.spouse() != undefined;
    for (var m = 0; m < array_length(mates); m++) {
        var key = string(mates[m].i);
        listed[$ key] = true;
        if (st.homes[$ key] == day) continue;
        try {
            if (__mistrimulti_story_move_in(st, mates[m], morning, bed_taken)) {
                st.homes[$ key] = day;
                st.stats.homes++;
                if (!mates[m].pet) bed_taken = true;
            }
        } catch (e) {
            st.homes[$ key] = day;
            st.last_error = "home " + key + ": " + string(e);
            __mistrimulti_story_warn("A villager could not be moved into the farm house: " + string(e));
        }
    }
    var homes = struct_get_names(st.homes);
    for (var m = 0; m < array_length(homes); m++) {
        if (listed[$ homes[m]] == true) continue;
        struct_remove(st.homes, homes[m]);
        try { __mistrimulti_story_move_out(st, real(homes[m])); }
        catch (e) { __mistrimulti_story_warn("A villager could not leave the farm house: " + string(e)); }
    }
}

// game.new_day: every villager has just been put at the start of today's schedule by the game.
function mistrimulti_story_new_day(ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || ARI == undefined) return;
    try { __mistrimulti_story_house_pass(__mistrimulti_story(), true); }
    catch (e) { __mistrimulti_story_warn("Housing the villagers failed: " + string(e)); }
}
