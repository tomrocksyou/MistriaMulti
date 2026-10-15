// Developer commands for testing (docs/DEVTOOLS.md). Host only; nothing here is reachable from the network.
//
// Unlock the mines: the game's own alias requirement `OpenedMines` (the requirement its automated story test fulfills before
// the stone refinery quest) is brought about with the game's own fulfill_requirement, step by step: the cutscenes it needs
// are marked seen (with their object removals), the world facts it needs are written, the quests it needs are finished.
// Nothing is paid out. The story sync (MistriMultiStory.gml) then carries the new state to every guest, whose games apply
// it the way they apply any story step.

#macro MISTRIMULTI_DEV_DEPTH 6      // how deep nested alias requirements are followed

function __mistrimulti_dev_say(text) {
    try { mmapi_log_info("mistrimulti", "devtools: " + text); mmapi_log_flush("mistrimulti"); } catch (e) {}
    try { create_notification(ANCHOR.wrap_for_local(text)); } catch (e) {}
}

// Collects what a requirement (an array indexed by Requirement id, aliases followed) asks for into `plan`:
// scenes, facts ([name, value] pairs) and quests are things we can bring about; anything else (items, gold, "or" groups,
// dates ...) is listed in `skipped` and left alone, so the command can never hand out items or gold.
function __mistrimulti_dev_collect(req, plan, depth) {
    if (!is_array(req) || depth > MISTRIMULTI_DEV_DEPTH) return;
    for (var i = 0; i < Requirement.LEN; i++) {
        var v = req[i];
        if (v == undefined || (is_bool(v) && !v) || (is_array(v) && array_length(v) == 0)) continue;
        if (requirement_is_alias(i)) {
            __mistrimulti_dev_collect(REQUIREMENT_ALIASES[i], plan, depth + 1);
        } else if (i == Requirement.SeenCutscene && is_array(v)) {
            for (var j = 0; j < array_length(v); j++) {
                if (is_string(v[j]) && CUTSCENES.contains_key(v[j])) array_push(plan.scenes, v[j]);
                else array_push(plan.skipped, "scene");
            }
        } else if (i == Requirement.WorldFactIs && is_array(v)) {
            for (var j = 0; j < array_length(v); j++) {
                if (is_array(v[j]) && array_length(v[j]) == 2 && is_string(v[j][0])) array_push(plan.facts, v[j]);
                else array_push(plan.skipped, "fact");
            }
        } else if (i == Requirement.CompletedQuest && is_array(v)) {
            for (var j = 0; j < array_length(v); j++) {
                if (is_string(v[j]) && QUESTS.get(v[j]) != undefined) array_push(plan.quests, v[j]);
                else array_push(plan.skipped, "quest");
            }
        } else {
            array_push(plan.skipped, requirement_to_string(i));
        }
    }
}

// Why the command cannot run now, or "" when it can. The host check is the one that matters: a guest must never run this,
// because a guest's story steps are claims that the host would accept.
function __mistrimulti_dev_refusal() {
    var r = __mistrimulti_runtime();
    if (!r.enabled || r.mode != "host" || r.id != 0) return "Only the host can use this developer command.";
    if (ARI == undefined) return "Load a world first.";
    if (MIST.is_running() || ARI.end_of_day_status != undefined) return "Not during a cutscene or the end of the day.";
    var st = __mistrimulti_story();
    __mistrimulti_story_data(st);
    if (!st.data_ok || !st.ready) return "The story sync is not ready yet. Try again in a few seconds.";
    return "";
}

// Returns { ok, changed, open, skipped, text }. `text` is what the player is told.
function mistrimulti_devtools_unlock_mines() {
    var out = { ok: false, changed: 0, open: false, skipped: [], text: "" };
    try {
        var why = __mistrimulti_dev_refusal();
        if (why != "") { out.text = why; __mistrimulti_dev_say(why); return out; }
        var plan = { scenes: [], facts: [], quests: [], skipped: [] };
        __mistrimulti_dev_collect(REQUIREMENT_ALIASES[Requirement.OpenedMines], plan, 0);
        out.skipped = plan.skipped;
        for (var i = 0; i < array_length(plan.scenes); i++) {
            if (MIST.scene_history.contains(plan.scenes[i])) continue;
            fulfill_requirement(Requirement.SeenCutscene, [plan.scenes[i]]);
            out.changed++;
        }
        for (var i = 0; i < array_length(plan.facts); i++) {
            if (T2R.read(plan.facts[i][0]) == plan.facts[i][1]) continue;
            fulfill_requirement(Requirement.WorldFactIs, [plan.facts[i]]);
            out.changed++;
        }
        for (var i = 0; i < array_length(plan.quests); i++) {
            if (QUEST_LOG.completed.contains(plan.quests[i])) continue;
            mistrimulti_story_apply_quest(plan.quests[i], MISTRIMULTI_STORY_DONE);
            out.changed++;
        }
        out.open = requirements_pass(Requirement.OpenedMines);
        out.ok = out.open;
        if (out.changed > 0 && CURRENT_LOCATION_ID != LocationId.Dungeon) setup_room();   // the game's own refresh of the room
        if (!out.open) out.text = "The mines still report as locked (" + string(array_length(plan.skipped)) + " parts not handled). See the log.";
        else if (out.changed == 0) out.text = "The mines are already unlocked.";
        else out.text = "Mines unlocked (" + string(out.changed) + " story steps). The other players get it within seconds.";
        __mistrimulti_dev_say(out.text);
        if (array_length(plan.skipped) > 0) mmapi_log_info("mistrimulti", "devtools: not handled: " + json_stringify(plan.skipped));
    } catch (e) {
        out.ok = false;
        out.text = "Unlocking the mines failed.";
        __mistrimulti_dev_say(out.text);
        mmapi_warn_rate_limited("mistrimulti_devtools", "mistrimulti", "Unlock mines failed: " + string(e));
    }
    return out;
}

// CONTROL+F6 (registered in MistriMultiBoot.gml).
function mistrimulti_devtools_hotkey_unlock_mines() {
    mistrimulti_devtools_unlock_mines();
}
