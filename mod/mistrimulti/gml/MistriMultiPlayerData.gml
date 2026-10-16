function mistrimulti_player_data_initialize() {
    var r = __mistrimulti_runtime();
    r.world_key = "";
    r.world_path = "";
    r.player_owner = undefined;
    r.player_ready = false;
    r.player_revision = 0;
    r.player_saved_revision = 0;
    r.player_signature = "";
    r.player_last_checkpoint = 0;
    r.player_request = "";
    r.player_host_epoch = "";
    r.player_sessions = array_create(8, undefined);
    r.player_error = "";
    mistrimulti_progress_initialize();
}

function mistrimulti_player_capture() {
    var r = __mistrimulti_runtime();
    var stats = {};
    var fields = mistrimulti_player_stat_fields();
    for (var i = 0; i < array_length(fields); i++) stats[$ fields[i]] = ARI[$ fields[i]];
    var relations = [];
    for (var i = 0; i < NpcId.LEN; i++) {
        var npc = NPCS[i];
        array_push(relations, { hearts: npc.heart_points,
            status: T2R.read(npc_id_to_string(i) + "_status") ?? "undefined",
            gift: npc.gift_flag, talk: npc.talk_flag, spoken: npc.times_spoken_today,
            gifts: npc.gifts_given.keys(), preferences: npc.known_gift_preferences.keys() });
    }
    return { v: 1, uid: r.uid, world: r.world_key, day: string(CALENDAR.time),
        character: { v: 1, uid: r.uid, name: string(ARI.name), birthday: ARI.birthday,
            pronouns: clone_value(ARI.pronouns), look: ARI.animation_assets().serialize() },
        stats: stats, inventory: ARI.inventory.serialize(), armor: ARI.armor.serialize(),
        xp: clone_value(ARI.skill_xp), perks: clone_value(ARI.perks), spells: clone_value(ARI.spells_learned),
        relations: relations };
}

function mistrimulti_player_stat_fields() {
    return ["gold", "essence", "renown", "mana_current", "mana_max", "health_current",
        "base_health", "stamina_current", "base_stamina", "free_baths"];
}

function mistrimulti_player_inventory_valid(slots, minimum, maximum) {
    if (!is_array(slots) || array_length(slots) < minimum || array_length(slots) > maximum) return false;
    for (var i = 0; i < array_length(slots); i++) {
        var s = slots[i];
        if (!is_struct(s) || !is_array(s[$ "required_tags"]) || array_length(s.required_tags) > 16) return false;
        for (var t = 0; t < array_length(s.required_tags); t++) if (!is_string(s.required_tags[t])) return false;
        if (!is_real(s[$ "count"]) || s.count < 0 || s.count != floor(s.count)) return false;
        if (is_nullish(s[$ "item"])) { if (s.count != 0) return false; continue; }
        if (!is_struct(s.item) || !is_string(s.item[$ "item_id"])) return false;
        var id = try_string_to_item_id(s.item.item_id);
        if (id == undefined || s.count < 1 || s.count > ITEM_PROTOTYPES[id].max_stack) return false;
    }
    return true;
}

function mistrimulti_player_valid(data, uid, world) {
    if (!is_struct(data) || data[$ "v"] != 1 || data[$ "uid"] != uid || data[$ "world"] != world) return false;
    if (!mistrimulti_valid_character(data[$ "character"]) || data.character[$ "uid"] != uid) return false;
    if (!is_string(data[$ "day"]) || !is_struct(data[$ "stats"])) return false;
    var fields = mistrimulti_player_stat_fields();
    for (var i = 0; i < array_length(fields); i++) {
        var value = data.stats[$ fields[i]];
        if (!is_real(value) || value < 0 || value > 1000000000) return false;
    }
    if (!mistrimulti_player_inventory_valid(data[$ "inventory"], 10, 100)) return false;
    if (!mistrimulti_player_inventory_valid(data[$ "armor"], ArmorSlot.LEN, ArmorSlot.LEN)) return false;
    if (!is_array(data[$ "xp"]) || array_length(data.xp) != Skill.LEN) return false;
    for (var i = 0; i < Skill.LEN; i++) if (!is_real(data.xp[i]) || data.xp[i] < 0 || data.xp[i] > MAX_SKILL_LEVEL_COSTS[i]) return false;
    if (!mistrimulti_player_flags_valid(data[$ "perks"], Perk.LEN) || !mistrimulti_player_flags_valid(data[$ "spells"], Spell.LEN)) return false;
    if (!is_array(data[$ "relations"]) || array_length(data.relations) != NpcId.LEN) return false;
    for (var i = 0; i < NpcId.LEN; i++) {
        var p = data.relations[i];
        if (!is_struct(p) || !is_real(p[$ "hearts"]) || p.hearts < 0 || p.hearts > 1000000) return false;
        if (!is_string(p[$ "status"]) || string_pos("|" + p.status + "|", "|undefined|best_friend|dating|fiance|spouse|") == 0) return false;
        if (!mistrimulti_player_bool_valid(p[$ "gift"]) || !mistrimulti_player_bool_valid(p[$ "talk"]) || !is_real(p[$ "spoken"]) || p.spoken < 0 || p.spoken > 10000) return false;
        if (!mistrimulti_player_item_keys_valid(p[$ "gifts"]) || !mistrimulti_player_item_keys_valid(p[$ "preferences"])) return false;
    }
    // Parse equipment before changing the live character.
    try { var inv = Inventory(); inv.deserialize(data.inventory); inv.deserialize(data.armor); }
    catch (e) { return false; }
    return true;
}

function mistrimulti_player_flags_valid(values, count) {
    if (!is_array(values) || array_length(values) != count) return false;
    for (var i = 0; i < count; i++) if (!mistrimulti_player_bool_valid(values[i])) return false;
    return true;
}

function mistrimulti_player_bool_valid(value) {
    return typeof(value) == "bool";
}

function mistrimulti_player_item_keys_valid(values) {
    if (!is_array(values) || array_length(values) > ItemId.LEN) return false;
    for (var i = 0; i < array_length(values); i++) {
        if (!is_string(values[i]) && !is_real(values[i])) return false;
        var number = real(values[i]);
        if (number < 0 || number >= ItemId.LEN || number != floor(number)) return false;
    }
    return true;
}

function mistrimulti_player_restore(data) {
    var r = __mistrimulti_runtime();
    if (!mistrimulti_player_valid(data, r.uid, r.world_key)) return false;
    var c = data.character;
    var preset = player_animation_assets_deserialize(c.look);
    build_obj_ari_par_from(preset);
    ARI.presets.set(ARI.preset_index_selected, preset);
    ARI.name = c.name;
    ARI.birthday = int64(c.birthday);
    ARI.deserialize_pronouns(clone_value(c.pronouns));
    local_set_pronouns(ARI.pronouns);
    var fields = mistrimulti_player_stat_fields();
    for (var i = 0; i < array_length(fields); i++) ARI[$ fields[i]] = data.stats[$ fields[i]];
    ARI.mana_current = int64(data.stats.mana_current);
    ARI.mana_max = int64(data.stats.mana_max);
    ARI.inventory.deserialize(data.inventory);
    ARI.armor.deserialize(data.armor);
    mistrimulti_player_touch_inventory();
    ARI.held_item_index = 0;
    ARI.skill_xp = clone_value(data.xp);
    ARI.perks = clone_value(data.perks);
    ARI.spells_learned = clone_value(data.spells);
    for (var i = 0; i < NpcId.LEN; i++) {
        var p = data.relations[i];
        var npc = NPCS[i];
        if (!mistrimulti_hearts_shared()) npc.heart_points = p.hearts;   // shared hearts: the host's value stays
        npc.known_gift_preferences = HashSetFromArray(p.preferences);
        npc.gifts_given = HashSetFromArray(p.gifts);
        var same_day = data.day == string(CALENDAR.time);
        npc.gift_flag = same_day ? p.gift : true;
        npc.talk_flag = same_day ? p.talk : true;
        npc.times_spoken_today = same_day ? p.spoken : 0;
        T2R.write(npc_id_to_string(i) + "_status", p.status);
        npc.report_hearts();
    }
    for (var i = 0; i < NpcId.LEN; i++) NPCS[i].report_relationship();
    r.character_owner = ARI;
    r.character_pending = false;
    r.character_phase = "done";
    r.character_loaded = true;
    mistrimulti_progress_core_ready();
    r.look_signature = "";
    return true;
}

function mistrimulti_player_fresh() {
    var r = __mistrimulti_runtime();
    r.kit_owed = true;    // the new character's progress start gives the starter kit (MistriMultiStory.gml), this once
    ARI.inventory.deserialize(Inventory(10).serialize());
    var items = fiddle_get("misc/ari_stats/starting_inventory");
    for (var i = 0; i < array_length(items); i++) ARI.inventory.add(string_to_item_id(items[i]));
    mistrimulti_player_touch_inventory();
    var armor = fiddle_get("misc/ari_stats/starting_armor");
    var tags = ["head", "chest", "legs", "boots", "accessory"];
    for (var i = 0; i < ArmorSlot.LEN; i++) {
        var slot = ARI.armor.slot(i);
        slot.item = undefined;
        slot.count = 0;
        slot.add(string_to_item_id(armor[$ tags[i]]));
    }
    ARI.gold = 0;
    ARI.renown = 0;
    ARI.essence = fiddle_get("misc/ari_stats/starting_essence");
    ARI.mana_max = fiddle_get("misc/ari_stats/base_mana");
    ARI.mana_current = ARI.mana_max;
    ARI.base_health = fiddle_get("misc/ari_stats/base_health");
    ARI.base_stamina = fiddle_get("misc/ari_stats/base_stamina");
    ARI.health_current = ARI.base_health;
    ARI.stamina_current = ARI.base_stamina;
    ARI.free_baths = 0;
    ARI.skill_xp = array_create(Skill.LEN, 0);
    ARI.perks = array_create(Perk.LEN, false);
    ARI.spells_learned = array_create(Spell.LEN, false);
    var spells = fiddle_get("misc/ari_stats/starting_spells");
    for (var i = 0; i < array_length(spells); i++) ARI.spells_learned[string_to_spell(spells[i])] = true;
    for (var i = 0; i < NpcId.LEN; i++) {
        if (!mistrimulti_hearts_shared()) NPCS[i].heart_points = 0;
        NPCS[i].gift_flag = true;
        NPCS[i].talk_flag = true;
        NPCS[i].times_spoken_today = 0;
        NPCS[i].gifts_given = HashSet();
        NPCS[i].known_gift_preferences = HashSet();
        T2R.write(npc_id_to_string(i) + "_status", "undefined");
        NPCS[i].report_hearts();
    }
    for (var i = 0; i < NpcId.LEN; i++) NPCS[i].report_relationship();
    mistrimulti_progress_core_ready();
}

function mistrimulti_player_path(uid) {
    return __mistrimulti_runtime().world_path + "/players/" + string_replace_all(uid, ":", "_") + ".json";
}

function mistrimulti_player_load(uid) {
    var r = __mistrimulti_runtime();
    if (!mistrimulti_valid_uid(uid) || r.world_path == "") return undefined;
    var path = mistrimulti_player_path(uid);
    for (var i = 0; i < 2; i++) {
        var file = path + (i == 0 ? "" : ".bak");
        if (!file_exists(file)) continue;
        var saved = try_read_json_file(file);
        if (is_struct(saved) && saved[$ "v"] == 1 && is_real(saved[$ "revision"])
            && saved.revision >= 0 && saved.revision == floor(saved.revision)
            && mistrimulti_player_valid(saved[$ "data"], uid, r.world_key)) return saved;
    }
    return undefined;
}

function mistrimulti_player_store(uid, revision, data) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || !mistrimulti_valid_uid(uid) || r.world_path == "") return false;
    if (!mistrimulti_player_valid(data, uid, r.world_key)) return false;
    var path = mistrimulti_player_path(uid);
    try {
        var old = mistrimulti_player_load(uid);
        if (old != undefined) save_text_file(path + ".bak", json_stringify(old));
        save_text_file(path + ".tmp", json_stringify({ v: 1, revision: revision, data: data }));
        file_rename(path + ".tmp", path);
        return true;
    } catch (e) {
        r.player_error = "Player progress could not be saved on the host.";
        mmapi_warn_rate_limited("mistrimulti_player_save", "mistrimulti", r.player_error);
        return false;
    }
}

// Inventory.deserialize sets the slots without counting an update, so the toolbar (an InventorySubscriber that redraws on
// changed `updates`) kept showing the host's items after a guest's own inventory was restored. Count one update per slot.
function mistrimulti_player_touch_inventory() {
    var invs = [ARI.inventory, ARI.armor];
    for (var k = 0; k < array_length(invs); k++) {
        for (var i = 0; i < invs[k].size(); i++) invs[k].slot(i).updates += 1;
    }
}
