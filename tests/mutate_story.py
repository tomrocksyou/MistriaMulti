"""Mutation check for MistriMultiStory.gml (and the spouse registry and rewards ledger of MistriMultiProgress.gml): each mutation
must make at least one test fail.

    python3 tests/mutate_story.py

Breaks one rule of the GML at a time (accepting personal quests, lowering the world story, skipping the boxes of a finished
stage, acting during a cutscene, moving a villager in sight, paying a step twice, housing a player's own spouse, ...), runs the
tests that should notice, and restores the file. Exit status 1 if a mutation goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GML = ROOT / "mod/mistrimulti/gml/MistriMultiStory.gml"

# name, [(old, new), ...], tests that must fail
MUTATIONS = [
    ("personal quests accepted from a claim",
     [("strict ? !(__mistrimulti_story_quest_world(st, e[0]) && __mistrimulti_story_quest_level_ok(e[0], e[1]))",
       "strict ? !__mistrimulti_story_quest_level_ok(e[0], e[1])")], ["test_hostile_input"]),
    ("the world story can go down",
     [("if (e[1] > (st.q[$ e[0]] ?? -1)) {", "if (e[1] != (st.q[$ e[0]] ?? -1)) {")], ["test_merge_rules"]),
    ("a stage that does not exist is accepted",
     [("return quest != undefined && level < quest.tasks.count();", "return quest != undefined;")], ["test_hostile_input"]),
    ("the host does not tell the other guests",
     [("    return mistrimulti_story_merge(st, data, true, MISTRIMULTI_STORY_CLAIM_MAX);\n}",
       "    mistrimulti_story_merge(st, data, true, MISTRIMULTI_STORY_CLAIM_MAX);\n    return { q: [], sc: [], f: [], k: {} };\n}")],
     ["test_guest_progress", "test_same_step_race"]),
    ("a finished quest is not marked finished",
     [("        QUEST_LOG.completed.insert(name);\n        QUEST_LOG.completion_timestamps.insert(name, CALENDAR.time);",
       "        QUEST_LOG.completion_timestamps.insert(name, CALENDAR.time);")], ["test_host_progress", "test_guest_progress"]),
    ("the turn-in boxes of a finished stage stay",
     [("        __mistrimulti_story_clear_boxes(quest, level);\n", "")], ["test_guest_progress"]),
    ("the game is changed during a cutscene and the end of day",
     [("if (MIST.is_running() || ARI.end_of_day_status != undefined) return;", "if (false) return;")], ["test_cutscene_hold"]),
    ("the snapshot is never sent",
     [("        if (!mistrimulti_event_can_emit(3) || !mistrimulti_event_send_blob(", "        if (true || !mistrimulti_event_send_blob(")],
     ["test_late_join", "test_host_scene_and_join"]),
    ("heart events and romance scenes count as the world's",
     [("        var personal = c.romantic_choice_warning != undefined || array_length(c.heart_level_changes) > 0\n            || c.test_target == SceneTestTarget.MarriageAndChildren;",
       "        var personal = false;")], ["test_world_scenes"]),
    ("the festival's quest is mirrored",
     [(" && st.festq[$ name] != true;", ";")], ["test_host_progress"]),
    ("a villager in sight is moved",
     [("if (st.miss[$ key] >= MISTRIMULTI_STORY_MISS && unseen) {", "if (st.miss[$ key] >= MISTRIMULTI_STORY_MISS) {")],
     ["test_npc_in_sight_is_left_alone"]),
    ("a plan is used on any day",
     [("if (!is_struct(plan) || plan.d != total_days()) return;", "if (!is_struct(plan)) return;")], ["test_festival_flag"]),
    ("a claim is repeated every second",
     [("        if (!is_struct(p) || p.n < up.q[i][1]) array_push(claim.q, up.q[i]);", "        array_push(claim.q, up.q[i]);")],
     ["test_claim_is_sent_once"]),
    ("a refused claim is asked again and again",
     [("            st.bad[$ \"u:\" + keys[i]] = true;\n", "")], ["test_refused_claim_is_not_repeated"]),
    ("a delta from a guest is accepted",
     [("    if (!__mistrimulti_story_on(\"join\") || from != 0) return true;\n    mistrimulti_story_merge(__mistrimulti_story(), data, false, MISTRIMULTI_STORY_CLAIM_MAX);",
       "    if (!__mistrimulti_story_on(\"join\")) return true;\n    mistrimulti_story_merge(__mistrimulti_story(), data, false, MISTRIMULTI_STORY_CLAIM_MAX);")],
     ["test_hostile_input"]),
    ("an unknown schedule is followed",
     [(" || !__mistrimulti_story_known_schedule(st, want)) continue;", ") continue;")], ["test_hostile_input"]),
    ("a new host session keeps the old mirror",
     [("    st.q = {};\n    st.sc = {};\n    st.f = {};\n    st.k = { n: 0, b: 0, t: 0 };\n    st.pend = {};\n    st.want_at = -1000000;\n}\n\nfunction __mistrimulti_story_warn",
       "    st.pend = {};\n    st.want_at = -1000000;\n}\n\nfunction __mistrimulti_story_warn")], ["test_facts_and_counters", "test_host_restart"]),
    ("a delta is merged before it is known to fit in the queue",
     [("    } else if (mistrimulti_event_can_emit(12)) {", "    } else if (true) {"),
      ("        if (!__mistrimulti_story_empty(accepted)) __mistrimulti_story_broadcast(accepted);\n    }\n    __mistrimulti_story_down",
       "        if (!__mistrimulti_story_empty(accepted) && mistrimulti_event_can_emit(12)) __mistrimulti_story_broadcast(accepted);\n    }\n    __mistrimulti_story_down")],
     ["test_many_changes"]),
    ("the guest steers villagers it cannot see and sees alike (activity)",
     [("&& unseen && handler.state != ActivityState.Traveling", "&& handler.state != ActivityState.Traveling")],
     ["test_npc_in_sight_is_left_alone", "test_npc_activity_and_room_drift", "test_npc_plan"]),
    ("a game that is ahead of the host cannot tell it",
     [("    var up = __mistrimulti_story_up(st, local);\n    var claim", "    var up = { q: [], sc: [], f: [], k: {} };\n    var claim")],
     ["test_guest_progress", "test_guest_restart", "test_host_restart"]),
    # -- rewards for the players who did not do the step
    ("a player's own step is paid a second time",
     [("    if (!st.seen_ok || T2R.read(\"mm_paid_init\") != true) return;\n", "    return;\n")],
     ["test_same_step_race", "test_rewards_exactly_once_under_loss"]),
    ("a reward that starts a story quest starts it in every game",
     [("    if (quest == undefined || quest.category == QuestCategory.Story) return;", "    if (quest == undefined) return;")],
     ["test_guest_progress"]),
    ("the ledger is not moved when a step is paid",
     [("        T2R.write(\"mm_paid_\" + names[i], target);\n        try {", "        try {")], ["test_guest_progress", "test_host_progress"]),
    ("a new character is owed the story so far",
     [("            if (level > 0) T2R.write(\"mm_paid_\" + names[i], level);\n            continue;", "            continue;")],
     ["test_rewards_new_character_is_not_owed_the_past", "test_late_join"]),
    ("the items of a world scene are not given",
     [("        if (array_length(c.given_items) > 0) mist_give_items_after_scene(c.given_items, player_wake_position());\n", "")],
     ["test_scene_items"]),
    ("the free baths of a world scene are not given",
     [("        if (c.baths > 0) ARI.free_baths += c.baths;\n", "")], ["test_scene_items"]),
    ("the quest's own rewards are not given at its end",
     [("    __mistrimulti_story_grant(quest.reward_list);\n", "")], ["test_host_progress"]),
    ("renown is not filed at the end of a quest",
     [("            ARI.pending_renown_entries.push(RenownEntry.Quest(name));\n", "")], ["test_host_progress"]),
    ("a step is paid from the start of the quest every time",
     [("        var paid = __mistrimulti_story_paid(names[i]);\n        if (first) {", "        var paid = 0;\n        if (first) {")],
     ["test_rewards_offline_and_restart", "test_guest_progress"]),
    # -- the spouses of other players live at the farm
    ("a spouse is put to bed without being a spouse (no status for the game's function)",
     [("        T2R.write(key, \"spouse\");\n", "")], ["test_guest_spouse_moves_in"]),
    ("a player's own spouse is moved in by the mod as well",
     [("        if (!is_string(owner) || owner == r.uid || NPCS[i].is_roommate()) continue;", "        if (!is_string(owner)) continue;")],
     ["test_guest_spouse_moves_in"]),
    ("every spouse gets the bed",
     [("    var bed_taken = ARI.spouse() != undefined;", "    var bed_taken = false;"),
      ("                if (!mates[m].pet) bed_taken = true;\n", "")], ["test_two_spouses_at_the_farm"]),
    ("a marriage that ends leaves the spouse at the farm",
     [("        try { __mistrimulti_story_move_out(st, real(homes[m])); }", "        try { }")],
     ["test_marriage_in_the_middle_of_a_day_and_divorce"]),
    ("a villager in sight is moved in at once",
     [("    if (morning && !here) {", "    if (morning) {")], ["test_move_in_waits_while_the_player_looks"]),
    ("the day plan swaps a housed villager back out",
     [("        if (st.homes[$ key] == plan.d) continue;\n", "")], ["test_marriage_in_the_middle_of_a_day_and_divorce"]),
    ("the pet stays in the village",
     [("        if (pet != undefined && !NPCS[pet].is_roommate()) array_push(out, { i: pet, pet: true });\n", "")],
     ["test_guest_spouse_moves_in"]),
    ("a villager nobody can marry is moved in",
     [("        if (is_struct(kind) && kind[$ \"dateable\"] == false) continue;\n", "")], ["test_bad_registry_changes_nobody"]),
    ("Fridays use the ordinary roommate schedule",
     [("    if (CALENDAR.day_type() == Day.Friday) return \"Schedules/roommate_schedule_friday\";\n", "")],
     ["test_move_in_waits_while_the_player_looks"]),
]

PROGRESS = ROOT / "mod/mistrimulti/gml/MistriMultiProgress.gml"
PROGRESS_MUTATIONS = [
    ("a dating player's partner counts as the spouse",
     [("var married = relations[i].status == \"spouse\" &&", "var married = mistrimulti_romance_romantic(relations[i].status) &&")],
     ["test_spouse_registry"]),
    ("a player can have several spouses",
     [(" && mistrimulti_romance_spouse_free(uid, name);", ";")], ["test_spouse_registry"]),
    ("a guest accepts spouses the claims do not hold",
     [("claims[$ names[i]] != undefined && claims[$ names[i]] == spouses[$ names[i]]", "true")], ["test_spouse_registry"]),
    ("a marriage that ends stays in the registry",
     [("        else if (!married && r.romance_spouse[$ name] == uid) { struct_remove(r.romance_spouse, name); r.romance_dirty = true; }\n", "")],
     ["test_spouse_registry"]),
    ("the host's ledger stays in a guest's game after its restore",
     [("    for (var i = 0; i < array_length(quests); i++) T2R.write(\"mm_paid_\" + quests[i], v.paid[$ quests[i]]);\n", "")],
     ["test_sections_round_trip"]),
    ("a ledger with a level of zero is accepted",
     [(" || level < 1 || level > 1000000) return false;", " || level > 1000000) return false;")], ["test_validation"]),
]

PROGRESS_RUNNER = "import sys, test_progress as t\nfor n in sys.argv[1:]: getattr(t, n)()"
bad = 0
for gml_file, table in ((GML, MUTATIONS), (PROGRESS, PROGRESS_MUTATIONS)):
    original = gml_file.read_text()
    try:
        for name, edits, tests in table:
            text = original
            missing = [old for old, new in edits if old not in text]
            if missing:
                print("MISSING PATTERN:", name, "->", missing[0][:60])
                bad += 1
                continue
            for old, new in edits:
                text = text.replace(old, new, 1)
            gml_file.write_text(text)
            cmd = [sys.executable, "test_story.py"] + tests if gml_file == GML else [sys.executable, "-c", PROGRESS_RUNNER] + tests
            out = subprocess.run(cmd, cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
            caught = out.returncode != 0
            print(("caught " if caught else "NOT CAUGHT ") + name)
            bad += 0 if caught else 1
    finally:
        gml_file.write_text(original)
sys.exit(1 if bad else 0)
