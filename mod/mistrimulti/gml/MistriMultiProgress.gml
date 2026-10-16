// Per-player progress: the personal parts of the game's save (recipes, almanac, seen flags, cosmetics, romance and family, mail,
// personal quests, counters, daily flags) that the core character record (MistriMultiPlayerData.gml) does not carry, plus the
// host's save commit and the one-partner-per-NPC rule. Every field is classified in docs/SYNC-PROGRESS.md.
//
// A player's progress is a record of named SECTIONS. A guest uploads only the sections that changed (a blob, like the core record),
// and the host merges them into its stored copy, so a rarely changing section is not resent with every gold coin. Capture, validate,
// restore and defaults of a section sit side by side below; the game's own (de)serialize helpers and *_to_string functions do the
// conversions, and a name this game version does not know is dropped on restore, so a record can outlive a game update.

#macro MISTRIMULTI_PROGRESS_VERSION 1
#macro MISTRIMULTI_PROGRESS_SECTION_BYTES 98304
#macro MISTRIMULTI_PROGRESS_RECORD_BYTES 245760
#macro MISTRIMULTI_PROGRESS_INTERVAL 5000000
#macro MISTRIMULTI_PROGRESS_MIN_GAP 1000000
#macro MISTRIMULTI_PROGRESS_RETRY 2000000

function mistrimulti_progress_sections() {
    return ["recipes", "almanac", "seen", "cosmetics", "romance", "inbox", "quests", "counters", "misc", "daily", "story_rewards"];
}

function mistrimulti_progress_known(name) {
    var names = mistrimulti_progress_sections();
    for (var i = 0; i < array_length(names); i++) if (names[i] == name) return true;
    return false;
}

function mistrimulti_progress_initialize() {
    var r = __mistrimulti_runtime();
    r.progress_members = {};
    r.progress_load_key = r[$ "progress_load_key"] ?? "";
    r.romance = {};
    r.romance_spouse = {};
    r.romance_view = {};
    r.romance_spouse_view = {};
    r.romance_dirty = false;
    r.romance_scanned = 0;
    mistrimulti_progress_reset_session();
}

// A new world session: nothing of the previous one survives.
function mistrimulti_progress_reset_session() {
    var r = __mistrimulti_runtime();
    r.progress_core_loaded = false;
    r.progress_loaded = false;
    r.progress_request = "";
    r.progress_revision = 0;
    r.progress_saved_revision = 0;
    r.progress_sigs = {};
    r.progress_pending = {};
    r.progress_locked = {};
    r.progress_checkpointed = 0;
    r.progress_sessions = array_create(8, undefined);
    r.romance_view = {};
    r.romance_spouse_view = {};
}

// The core record was applied (PlayerData restore or fresh start). A guest is ready once its progress is applied as well.
function mistrimulti_progress_core_ready() {
    var r = __mistrimulti_runtime();
    r.progress_core_loaded = true;
    r.player_ready = r.mode != "join" || r.progress_loaded;
}

function mistrimulti_progress_applied() {
    var r = __mistrimulti_runtime();
    r.progress_loaded = true;
    r.player_ready = r.progress_core_loaded;
}

// ---- names and counters -------------------------------------------------------------------------------------------------------

function mistrimulti_progress_index_map(count, to_string) {
    var map = {};
    for (var i = 0; i < count; i++) map[$ to_string(i)] = i;
    return map;
}

function mistrimulti_progress_flags(names, count, to_string) {
    var map = mistrimulti_progress_index_map(count, to_string);
    var flags = array_create(count, false);
    for (var i = 0; i < array_length(names); i++) {
        var index = map[$ names[i]];
        if (index != undefined) flags[index] = true;
    }
    return flags;
}

// Non-zero entries of a counter array, by name.
function mistrimulti_progress_counted(values, to_string) {
    var out = {};
    for (var i = 0; i < array_length(values); i++) {
        if (is_real(values[i]) && values[i] > 0) out[$ to_string(i)] = values[i];
    }
    return out;
}

function mistrimulti_progress_counts(saved, count, to_string) {
    var map = mistrimulti_progress_index_map(count, to_string);
    var values = array_create(count, 0);
    var keys = struct_get_names(saved);
    for (var i = 0; i < array_length(keys); i++) {
        var index = map[$ keys[i]];
        if (index != undefined) values[index] = saved[$ keys[i]];
    }
    return values;
}

// ---- validation helpers (network and disk data is untrusted) -------------------------------------------------------------------

function mistrimulti_progress_real_valid(value) {
    return is_real(value) && value >= -1000000000000 && value <= 1000000000000;
}

function mistrimulti_progress_count_valid(value) {
    return is_real(value) && value >= 0 && value <= 1000000000000;
}

function mistrimulti_progress_bool_valid(value) {
    return typeof(value) == "bool";
}

function mistrimulti_progress_text_valid(value, limit) {
    return is_string(value) && string_length(value) >= 1 && string_length(value) <= limit;
}

function mistrimulti_progress_names_valid(values, limit) {
    if (!is_array(values) || array_length(values) > limit) return false;
    for (var i = 0; i < array_length(values); i++) if (!mistrimulti_progress_text_valid(values[i], 96)) return false;
    return true;
}

// A struct of name -> non-negative number.
function mistrimulti_progress_counts_valid(values, limit) {
    if (!is_struct(values)) return false;
    var keys = struct_get_names(values);
    if (array_length(keys) > limit) return false;
    for (var i = 0; i < array_length(keys); i++) {
        if (!mistrimulti_progress_text_valid(keys[i], 96) || !mistrimulti_progress_count_valid(values[$ keys[i]])) return false;
    }
    return true;
}

// A struct of name -> short text.
function mistrimulti_progress_text_map_valid(values, limit) {
    if (!is_struct(values)) return false;
    var keys = struct_get_names(values);
    if (array_length(keys) > limit) return false;
    for (var i = 0; i < array_length(keys); i++) {
        if (!mistrimulti_progress_text_valid(keys[i], 96) || !mistrimulti_progress_text_valid(values[$ keys[i]], 96)) return false;
    }
    return true;
}

// A struct of name -> list of names.
function mistrimulti_progress_name_lists_valid(values, limit, list_limit) {
    if (!is_struct(values)) return false;
    var keys = struct_get_names(values);
    if (array_length(keys) > limit) return false;
    for (var i = 0; i < array_length(keys); i++) {
        if (!mistrimulti_progress_text_valid(keys[i], 96) || !mistrimulti_progress_names_valid(values[$ keys[i]], list_limit)) return false;
    }
    return true;
}

// Plain JSON (nesting, sizes and number ranges bounded) for the few fields whose inner format belongs to the game.
function mistrimulti_progress_plain_valid(value, depth) {
    if (is_nullish(value)) return true;
    if (is_string(value)) return string_length(value) <= 256;
    if (typeof(value) == "bool") return true;
    if (is_real(value)) return mistrimulti_progress_real_valid(value);
    if (depth <= 0) return false;
    if (is_array(value)) {
        if (array_length(value) > 64) return false;
        for (var i = 0; i < array_length(value); i++) if (!mistrimulti_progress_plain_valid(value[i], depth - 1)) return false;
        return true;
    }
    if (is_struct(value)) {
        var keys = struct_get_names(value);
        if (array_length(keys) > 64) return false;
        for (var i = 0; i < array_length(keys); i++) {
            if (string_length(keys[i]) > 96 || !mistrimulti_progress_plain_valid(value[$ keys[i]], depth - 1)) return false;
        }
        return true;
    }
    return false;
}

// ---- section dispatch ---------------------------------------------------------------------------------------------------------

function mistrimulti_progress_capture_section(name) {
    switch (name) {
        case "recipes": return mistrimulti_progress_capture_recipes();
        case "almanac": return mistrimulti_progress_capture_almanac();
        case "seen": return mistrimulti_progress_capture_seen();
        case "cosmetics": return mistrimulti_progress_capture_cosmetics();
        case "romance": return mistrimulti_progress_capture_romance();
        case "inbox": return mistrimulti_progress_capture_inbox();
        case "quests": return mistrimulti_progress_capture_quests();
        case "counters": return mistrimulti_progress_capture_counters();
        case "misc": return mistrimulti_progress_capture_misc();
        case "daily": return mistrimulti_progress_capture_daily();
        case "story_rewards": return mistrimulti_progress_capture_story_rewards();
    }
    return undefined;
}

function mistrimulti_progress_section_valid(name, value) {
    if (!is_struct(value) || string_byte_length(json_stringify(value)) > MISTRIMULTI_PROGRESS_SECTION_BYTES) return false;
    switch (name) {
        case "recipes": return mistrimulti_progress_valid_recipes(value);
        case "almanac": return mistrimulti_progress_valid_almanac(value);
        case "seen": return mistrimulti_progress_valid_seen(value);
        case "cosmetics": return mistrimulti_progress_valid_cosmetics(value);
        case "romance": return mistrimulti_progress_valid_romance(value);
        case "inbox": return mistrimulti_progress_valid_inbox(value);
        case "quests": return mistrimulti_progress_valid_quests(value);
        case "counters": return mistrimulti_progress_valid_counters(value);
        case "misc": return mistrimulti_progress_valid_misc(value);
        case "daily": return mistrimulti_progress_valid_daily(value);
        case "story_rewards": return mistrimulti_progress_valid_story_rewards(value);
    }
    return false;
}

function mistrimulti_progress_restore_section(name, value) {
    switch (name) {
        case "recipes": mistrimulti_progress_restore_recipes(value); break;
        case "almanac": mistrimulti_progress_restore_almanac(value); break;
        case "seen": mistrimulti_progress_restore_seen(value); break;
        case "cosmetics": mistrimulti_progress_restore_cosmetics(value); break;
        case "romance": mistrimulti_progress_restore_romance(value); break;
        case "inbox": mistrimulti_progress_restore_inbox(value); break;
        case "quests": mistrimulti_progress_restore_quests(value); break;
        case "counters": mistrimulti_progress_restore_counters(value); break;
        case "misc": mistrimulti_progress_restore_misc(value); break;
        case "daily": mistrimulti_progress_restore_daily(value); break;
        case "story_rewards": mistrimulti_progress_restore_story_rewards(value); break;
    }
}

// What a new character has (the same values the game's own new-game code produces).
function mistrimulti_progress_defaults_section(name) {
    switch (name) {
        case "recipes": return mistrimulti_progress_defaults_recipes();
        case "almanac": return { acquired: [], sold: {}, killed: {}, legendary: [], bans: [] };
        // A cutscene the host saw before this player arrived has had its effects on the world: a new player does not replay it.
        case "seen": return { tutorials: [], scenes: MIST.scene_history.keys() };
        case "cosmetics": return mistrimulti_progress_defaults_cosmetics();
        case "romance": return { dates: [], history: [], wedding_date: undefined, proposal_date: undefined, no_break_ups: false,
            no_break_up_letters: false, festival_partner: undefined, pending_child: undefined, children: [], met: [], ex: [] };
        case "inbox": return { letters: [] };
        case "quests": return { active: [], done: [], times: {}, manual: [], board_read: [] };
        case "counters": return { stats: {}, spoken: {} };
        case "misc": return { crown_cooldown: undefined, artifacts: {}, pinned: undefined, perks_off: [], renown: [],
            renown_rewards: Inventory(8).serialize(), mount: undefined, mines_level: 0 };
        case "daily": return mistrimulti_progress_defaults_daily();
        case "story_rewards": return { init: false, paid: {} };
    }
    return undefined;
}

// ---- recipes ------------------------------------------------------------------------------------------------------------------

function mistrimulti_progress_capture_recipes() {
    return { unlocks: serialize_array_bool(ARI.recipe_unlocks, item_id_to_string),
        created: serialize_array_bool(ARI.recipes_created, item_id_to_string) };
}

function mistrimulti_progress_valid_recipes(v) {
    return mistrimulti_progress_names_valid(v[$ "unlocks"], 8192) && mistrimulti_progress_names_valid(v[$ "created"], 8192);
}

function mistrimulti_progress_restore_recipes(v) {
    ARI.recipe_unlocks = mistrimulti_progress_flags(v.unlocks, ItemId.LEN, item_id_to_string);
    ARI.recipes_created = mistrimulti_progress_flags(v.created, ItemId.LEN, item_id_to_string);
    // Derived: the game recomputes it at the start of every day.
    ARI.morning_recipe_unlocks = array_create_ext(ItemId.LEN, ari_has_recipe_anywhere);
}

function mistrimulti_progress_defaults_recipes() {
    var unlocks = [];
    for (var i = 0; i < ItemId.LEN; i++) {
        var recipe = ITEM_PROTOTYPES[i].recipe;
        if (recipe != undefined && recipe.is_default) array_push(unlocks, item_id_to_string(i));
    }
    return { unlocks: unlocks, created: [] };
}

// ---- almanac, sales and kills -------------------------------------------------------------------------------------------------

function mistrimulti_progress_capture_almanac() {
    return { acquired: serialize_array_bool(ARI.items_acquired, item_id_to_string),
        sold: mistrimulti_progress_counted(ARI.items_sold, item_id_to_string),
        killed: mistrimulti_progress_counted(ARI.monsters_killed, monster_id_to_string),
        legendary: serialize_array_bool(ARI.legendary_fish_caught, season_to_string),
        bans: serialize_array_bool(ARI.annual_item_purchase_bans, item_id_to_string) };
}

function mistrimulti_progress_valid_almanac(v) {
    return mistrimulti_progress_names_valid(v[$ "acquired"], 8192) && mistrimulti_progress_counts_valid(v[$ "sold"], 8192)
        && mistrimulti_progress_counts_valid(v[$ "killed"], 1024) && mistrimulti_progress_names_valid(v[$ "legendary"], 16)
        && mistrimulti_progress_names_valid(v[$ "bans"], 8192);
}

function mistrimulti_progress_restore_almanac(v) {
    ARI.items_acquired = mistrimulti_progress_flags(v.acquired, ItemId.LEN, item_id_to_string);
    ARI.build_almanac_items_remaining();
    ARI.items_sold = mistrimulti_progress_counts(v.sold, ItemId.LEN, item_id_to_string);
    ARI.monsters_killed = mistrimulti_progress_counts(v.killed, MonsterId.LEN, monster_id_to_string);
    ARI.legendary_fish_caught = mistrimulti_progress_flags(v.legendary, Season.LEN, season_to_string);
    ARI.annual_item_purchase_bans = mistrimulti_progress_flags(v.bans, ItemId.LEN, item_id_to_string);
}

// ---- tutorials and cutscenes seen (romance scene history included) -------------------------------------------------------------

function mistrimulti_progress_capture_seen() {
    return { tutorials: serialize_array_bool(ARI.tutorials_seen, tutorial_to_string), scenes: MIST.scene_history.keys() };
}

function mistrimulti_progress_valid_seen(v) {
    return mistrimulti_progress_names_valid(v[$ "tutorials"], 1024) && mistrimulti_progress_names_valid(v[$ "scenes"], 8192);
}

function mistrimulti_progress_restore_seen(v) {
    ARI.tutorials_seen = mistrimulti_progress_flags(v.tutorials, Tutorial.LEN, tutorial_to_string);
    var old = MIST.scene_history.keys();
    MIST.scene_history = HashSetFromArray(v.scenes);
    // The game derives these world facts from the history once a day and never clears them: drop the ones that no longer hold.
    for (var i = 0; i < array_length(old); i++) {
        if (!MIST.scene_history.contains(old[i])) T2R.write("cutscene_seen_" + old[i], undefined);
    }
    for (var i = 0; i < array_length(v.scenes); i++) T2R.write("cutscene_seen_" + v.scenes[i], 1.0);
}

// ---- cosmetics and music ------------------------------------------------------------------------------------------------------

function mistrimulti_progress_capture_cosmetics() {
    var variants = {};
    var extras = {};
    for (var i = 0; i < AnimalKind.LEN; i++) {
        variants[$ animal_kind_to_string(i)] = ARI.animal_variant_unlocks[i].keys();
        extras[$ animal_kind_to_string(i)] = ARI.animal_cosmetic_unlocks[i].keys();
    }
    var overrides = {};
    for (var i = 0; i < LocationId.LEN; i++) {
        if (is_string(ARI.song_overrides[i])) overrides[$ location_id_to_string(i)] = ARI.song_overrides[i];
    }
    var dynamic = {};
    var keys = struct_get_names(ARI.dyn_song_overrides);
    for (var i = 0; i < array_length(keys); i++) {
        if (is_string(ARI.dyn_song_overrides[$ keys[i]])) dynamic[$ keys[i]] = ARI.dyn_song_overrides[$ keys[i]];
    }
    return { outfits: ARI.cosmetic_unlocks.keys(), seen: ARI.seen_cosmetics.keys(), animal_variants: variants, animal_cosmetics: extras,
        pet_sets: clone_value(ARI.pet_cosmetic_sets_unlocked), pet_skins: clone_value(ARI.pet_skin_unlocks),
        songs: clone_value(ARI.song_unlocks), song_overrides: overrides, dyn_song_overrides: dynamic, bell_sound: string(ARI.bell_sound) };
}

function mistrimulti_progress_valid_cosmetics(v) {
    return mistrimulti_progress_names_valid(v[$ "outfits"], 4096) && mistrimulti_progress_names_valid(v[$ "seen"], 4096)
        && mistrimulti_progress_name_lists_valid(v[$ "animal_variants"], 64, 512)
        && mistrimulti_progress_name_lists_valid(v[$ "animal_cosmetics"], 64, 512)
        && mistrimulti_progress_names_valid(v[$ "pet_sets"], 256) && mistrimulti_progress_names_valid(v[$ "pet_skins"], 256)
        && mistrimulti_progress_names_valid(v[$ "songs"], 512) && mistrimulti_progress_text_map_valid(v[$ "song_overrides"], 128)
        && mistrimulti_progress_text_map_valid(v[$ "dyn_song_overrides"], 64) && mistrimulti_progress_text_valid(v[$ "bell_sound"], 96);
}

function mistrimulti_progress_restore_cosmetics(v) {
    ARI.cosmetic_unlocks = HashSetFromArray(v.outfits);
    ARI.seen_cosmetics = HashSetFromArray(v.seen);
    for (var i = 0; i < AnimalKind.LEN; i++) {
        var kind = animal_kind_to_string(i);
        // A kind this record does not know (a newer game) starts with its defaults.
        ARI.animal_variant_unlocks[i] = is_array(v.animal_variants[$ kind])
            ? HashSetFromArray(v.animal_variants[$ kind]) : mistrimulti_progress_default_variants(i);
        ARI.animal_cosmetic_unlocks[i] = HashSetFromArray(v.animal_cosmetics[$ kind] ?? []);
    }
    ARI.pet_cosmetic_sets_unlocked = clone_value(v.pet_sets);
    ARI.pet_skin_unlocks = clone_value(v.pet_skins);
    ARI.song_unlocks = clone_value(v.songs);
    ARI.song_overrides = array_create(LocationId.LEN, undefined);
    var locations = mistrimulti_progress_index_map(LocationId.LEN, location_id_to_string);
    var keys = struct_get_names(v.song_overrides);
    for (var i = 0; i < array_length(keys); i++) {
        var index = locations[$ keys[i]];
        if (index != undefined) ARI.song_overrides[index] = v.song_overrides[$ keys[i]];
    }
    ARI.dyn_song_overrides = clone_value(v.dyn_song_overrides);
    ARI.bell_sound = v.bell_sound;
}

function mistrimulti_progress_default_variants(kind) {
    var unlocks = HashSet();
    var keys = ANIMAL_PROTOTYPES[kind].variants.keys();
    for (var i = 0; i < array_length(keys); i++) {
        if (ANIMAL_PROTOTYPES[kind].variants.get(keys[i]).default_unlocked) unlocks.insert(keys[i]);
    }
    return unlocks;
}

function mistrimulti_progress_defaults_cosmetics() {
    var variants = {};
    var extras = {};
    for (var i = 0; i < AnimalKind.LEN; i++) {
        variants[$ animal_kind_to_string(i)] = mistrimulti_progress_default_variants(i).keys();
        extras[$ animal_kind_to_string(i)] = [];
    }
    return { outfits: default_cosmetic_unlocks().keys(), seen: default_cosmetic_unlocks().keys(), animal_variants: variants,
        animal_cosmetics: extras, pet_sets: [], pet_skins: [], songs: [], song_overrides: {}, dyn_song_overrides: {}, bell_sound: "default" };
}

// ---- romance: dates, engagement, marriage, children ---------------------------------------------------------------------------
// The relationship status itself is part of the core record (hearts and status per NPC); this section holds the rest of the story.

function mistrimulti_progress_capture_romance() {
    var history = [];
    for (var i = 0; i < array_length(ARI.date_history); i++) {
        var entry = ARI.date_history[i];
        array_push(history, { date: date_to_string(entry.date), npc: npc_id_to_string(entry.npc), timestamp: entry.timestamp });
    }
    var met = [];
    var ex = [];
    for (var i = 0; i < NpcId.LEN; i++) {
        var name = npc_id_to_string(i);
        if (T2R.read(name + "_has_met") == true) array_push(met, name);
        if (T2R.read(name + "_is_ex") == true) array_push(ex, name);
    }
    var children = [];
    for (var i = 0; i < array_length(ARI.children); i++) {
        var child = ARI.children[i];
        array_push(children, { id: child_id_to_string(child.id), name: string(child.name),
            skin_tone: child_skin_tone_to_string(child.skin_tone), location: child_location_to_string(child.location),
            stage: child_stage_to_string(child.stage), birthday: child.birthday });
    }
    var pending = undefined;
    if (ARI.pending_child != undefined) {
        pending = { utero: utero_to_string(ARI.pending_child.utero), due_date: ARI.pending_child.due_date };
    }
    return { dates: serialize_array_bool(ARI.date_unlocks, date_to_string), history: history,
        wedding_date: ARI.wedding_date, proposal_date: ARI.proposal_date,
        no_break_ups: ARI.disable_break_ups == true, no_break_up_letters: ARI.disable_break_up_letters == true,
        festival_partner: opt_and_then(ARI.festival_date_partner, npc_id_to_string),
        pending_child: pending, children: children, met: met, ex: ex };
}

function mistrimulti_progress_valid_romance(v) {
    if (!mistrimulti_progress_names_valid(v[$ "dates"], 64) || !mistrimulti_progress_names_valid(v[$ "met"], 256)
        || !mistrimulti_progress_names_valid(v[$ "ex"], 256)) return false;
    if (!mistrimulti_progress_bool_valid(v[$ "no_break_ups"]) || !mistrimulti_progress_bool_valid(v[$ "no_break_up_letters"])) return false;
    // Optional fields may be null or absent.
    var optional = ["wedding_date", "proposal_date"];
    for (var i = 0; i < array_length(optional); i++) {
        if (!is_nullish(v[$ optional[i]]) && !mistrimulti_progress_real_valid(v[$ optional[i]])) return false;
    }
    var partner = v[$ "festival_partner"];
    if (!is_nullish(partner) && !mistrimulti_progress_text_valid(partner, 96)) return false;
    var history = v[$ "history"];
    if (!is_array(history) || array_length(history) > 256) return false;
    for (var i = 0; i < array_length(history); i++) {
        var h = history[i];
        if (!is_struct(h) || !mistrimulti_progress_text_valid(h[$ "date"], 96) || !mistrimulti_progress_text_valid(h[$ "npc"], 96)
            || !mistrimulti_progress_real_valid(h[$ "timestamp"])) return false;
    }
    var pending = v[$ "pending_child"];
    if (!is_nullish(pending) && (!is_struct(pending) || !mistrimulti_progress_text_valid(pending[$ "utero"], 96)
        || !mistrimulti_progress_real_valid(pending[$ "due_date"]))) return false;
    var children = v[$ "children"];
    if (!is_array(children) || array_length(children) > 4) return false;
    for (var i = 0; i < array_length(children); i++) {
        var c = children[i];
        if (!is_struct(c) || !mistrimulti_progress_text_valid(c[$ "id"], 96) || !is_string(c[$ "name"]) || string_length(c.name) > 64
            || !mistrimulti_progress_text_valid(c[$ "skin_tone"], 96) || !mistrimulti_progress_text_valid(c[$ "location"], 96)
            || !mistrimulti_progress_text_valid(c[$ "stage"], 96) || !mistrimulti_progress_real_valid(c[$ "birthday"])) return false;
    }
    return true;
}

function mistrimulti_progress_restore_romance(v) {
    var npcs = mistrimulti_progress_index_map(NpcId.LEN, npc_id_to_string);
    ARI.date_unlocks = mistrimulti_progress_flags(v.dates, Date.LEN, date_to_string);
    var dates = mistrimulti_progress_index_map(Date.LEN, date_to_string);
    ARI.date_history = [];
    for (var i = 0; i < array_length(v.history); i++) {
        var h = v.history[i];
        if (dates[$ h.date] != undefined && npcs[$ h.npc] != undefined) {
            array_push(ARI.date_history, { date: dates[$ h.date], npc: npcs[$ h.npc], timestamp: h.timestamp });
        }
    }
    ARI.wedding_date = is_nullish(v[$ "wedding_date"]) ? undefined : v.wedding_date;
    ARI.proposal_date = is_nullish(v[$ "proposal_date"]) ? undefined : v.proposal_date;
    ARI.disable_break_ups = v.no_break_ups;
    ARI.disable_break_up_letters = v.no_break_up_letters;
    ARI.festival_date_partner = is_nullish(v[$ "festival_partner"]) ? undefined : npcs[$ v.festival_partner];
    var pending = v[$ "pending_child"];
    var utero = undefined;
    if (!is_nullish(pending)) utero = mistrimulti_progress_index_map(Utero.LEN, utero_to_string)[$ pending.utero];
    ARI.pending_child = utero == undefined ? undefined : { utero: utero, due_date: pending.due_date };
    // Children are rebuilt the way the game's loader does it. Their location needs a spouse (restored with the core record).
    var ids = mistrimulti_progress_index_map(ChildId.LEN, child_id_to_string);
    var tones = mistrimulti_progress_index_map(ChildSkinTone.LEN, child_skin_tone_to_string);
    var stages = mistrimulti_progress_index_map(ChildStage.LEN, child_stage_to_string);
    var places = mistrimulti_progress_index_map(ChildLocation.LEN, child_location_to_string);
    var spouse = ARI.spouse();
    ARI.children = [];
    for (var i = 0; i < array_length(v.children); i++) {
        var c = v.children[i];
        if (ids[$ c.id] == undefined || tones[$ c.skin_tone] == undefined || stages[$ c.stage] == undefined || places[$ c.location] == undefined) continue;
        var child = new Child(ids[$ c.id], c.birthday, tones[$ c.skin_tone]);
        child.name = c.name;
        child.stage = stages[$ c.stage];
        if (spouse != undefined) child.set_location(places[$ c.location]);
        else child.location = places[$ c.location];
        array_push(ARI.children, child);
    }
    // "Met" and "ex" are world facts the game writes only when they become true.
    for (var i = 0; i < NpcId.LEN; i++) {
        var name = npc_id_to_string(i);
        T2R.write(name + "_has_met", mistrimulti_progress_listed(v.met, name) ? true : undefined);
        T2R.write(name + "_is_ex", mistrimulti_progress_listed(v.ex, name) ? true : undefined);
    }
    report_children_facts();
}

function mistrimulti_progress_listed(names, name) {
    for (var i = 0; i < array_length(names); i++) if (names[i] == name) return true;
    return false;
}

// ---- mail ---------------------------------------------------------------------------------------------------------------------

function mistrimulti_progress_capture_inbox() {
    return { letters: ARI.inbox.serialize() };
}

function mistrimulti_progress_valid_inbox(v) {
    var letters = v[$ "letters"];
    if (!is_array(letters) || array_length(letters) > 1024) return false;
    for (var i = 0; i < array_length(letters); i++) {
        var l = letters[i];
        if (!is_struct(l) || !mistrimulti_progress_text_valid(l[$ "path"], 128) || !mistrimulti_progress_bool_valid(l[$ "read"])
            || !mistrimulti_progress_bool_valid(l[$ "items_taken"])) return false;
    }
    return true;
}

function mistrimulti_progress_restore_inbox(v) {
    var letters = [];
    for (var i = 0; i < array_length(v.letters); i++) {
        // The game's deserializer rejects a letter it does not know; keep only the known ones.
        if (LETTERS.contains_key(v.letters[i].path)) array_push(letters, v.letters[i]);
    }
    ARI.inbox.contents.clear();
    ARI.inbox.deserialize(letters);
}

// ---- personal quests ----------------------------------------------------------------------------------------------------------
// Story quests are the world's story and stay with the host. Every other category (crown, challenges, heart, fetch) is personal.

function mistrimulti_progress_quest_personal(name) {
    var quest = QUESTS.get(name);
    return quest != undefined && quest.category != QuestCategory.Story;
}

function mistrimulti_progress_capture_quests() {
    var active = [];
    var keys = QUEST_LOG.active.keys();
    for (var i = 0; i < array_length(keys); i++) {
        if (!mistrimulti_progress_quest_personal(keys[i])) continue;
        var quest = QUEST_LOG.active.get(keys[i]);
        array_push(active, { name: keys[i], task: quest.current_stage, board: clone_value(quest.blackboard.inner) });
    }
    var done = [];
    var times = {};
    keys = QUEST_LOG.completed.keys();
    for (var i = 0; i < array_length(keys); i++) {
        if (!mistrimulti_progress_quest_personal(keys[i])) continue;
        array_push(done, keys[i]);
        times[$ keys[i]] = QUEST_LOG.completion_timestamps.get(keys[i]) ?? 0;
    }
    return { active: active, done: done, times: times, manual: MANUAL_QUEST_UNLOCKS.keys(), board_read: REQUEST_BOARD_READ_ENTRIES.keys() };
}

function mistrimulti_progress_valid_quests(v) {
    if (!mistrimulti_progress_names_valid(v[$ "done"], 2048) || !mistrimulti_progress_counts_valid(v[$ "times"], 2048)
        || !mistrimulti_progress_names_valid(v[$ "manual"], 2048) || !mistrimulti_progress_names_valid(v[$ "board_read"], 2048)) return false;
    var active = v[$ "active"];
    if (!is_array(active) || array_length(active) > 256) return false;
    for (var i = 0; i < array_length(active); i++) {
        var q = active[i];
        if (!is_struct(q) || !mistrimulti_progress_text_valid(q[$ "name"], 128) || !is_real(q[$ "task"]) || q.task < 0
            || q.task != floor(q.task) || q.task > 1000 || !is_struct(q[$ "board"]) || !mistrimulti_progress_plain_valid(q.board, 3)) return false;
    }
    return true;
}

function mistrimulti_progress_restore_quests(v) {
    var touched = [];
    var keys = QUEST_LOG.active.keys();
    for (var i = 0; i < array_length(keys); i++) {
        if (!mistrimulti_progress_quest_personal(keys[i])) continue;
        QUEST_LOG.active.remove(keys[i]);
        array_push(touched, keys[i]);
    }
    keys = QUEST_LOG.completed.keys();
    for (var i = 0; i < array_length(keys); i++) {
        if (!mistrimulti_progress_quest_personal(keys[i])) continue;
        QUEST_LOG.completed.remove(keys[i]);
        QUEST_LOG.completion_timestamps.remove(keys[i]);
        array_push(touched, keys[i]);
    }
    for (var i = 0; i < array_length(v.done); i++) {
        if (!mistrimulti_progress_quest_personal(v.done[i])) continue;
        QUEST_LOG.completed.insert(v.done[i]);
        QUEST_LOG.completion_timestamps.insert(v.done[i], v.times[$ v.done[i]] ?? 0);
        array_push(touched, v.done[i]);
    }
    for (var i = 0; i < array_length(v.active); i++) {
        var entry = v.active[i];
        if (!mistrimulti_progress_quest_personal(entry.name) || QUEST_LOG.completed.contains(entry.name)) continue;
        var quest = QUESTS.get(entry.name);
        if (entry.task >= quest.tasks.count()) continue;
        // Not QUEST_LOG.start: it would also place the quest's turn-in boxes in this game's copy of the host's world.
        var active = new ActiveQuest(quest, entry.name, entry.task);
        active.blackboard.inner = clone_value(entry.board);
        QUEST_LOG.active.insert(entry.name, active);
        array_push(touched, entry.name);
    }
    MANUAL_QUEST_UNLOCKS.clear();
    for (var i = 0; i < array_length(v.manual); i++) MANUAL_QUEST_UNLOCKS.insert(v.manual[i]);
    REQUEST_BOARD_READ_ENTRIES.clear();
    for (var i = 0; i < array_length(v.board_read); i++) REQUEST_BOARD_READ_ENTRIES.insert(v.board_read[i]);
    // The game keeps a world fact per quest; bring the ones this section owns in line (the daily update only ever sets them).
    for (var i = 0; i < array_length(touched); i++) {
        T2R.write("quest_" + touched[i] + "_complete", QUEST_LOG.completed.contains(touched[i]));
        T2R.write("quest_" + touched[i] + "_in_progress", QUEST_LOG.active.contains_key(touched[i]));
    }
}

// ---- counters the achievements read -------------------------------------------------------------------------------------------
// The game's other statistics are unbounded logs (every dish cooked, every purchase); they stay with the local game.

function mistrimulti_progress_counter_names() {
    return ["enemies_killed", "gross_essence", "deaths", "faints", "bathhouse_uses", "bugs_missed", "fish_missed", "cutscenes_skipped"];
}

function mistrimulti_progress_capture_counters() {
    var stats = {};
    var names = mistrimulti_progress_counter_names();
    for (var i = 0; i < array_length(names); i++) {
        if (is_real(GAME_STATS[$ names[i]])) stats[$ names[i]] = GAME_STATS[$ names[i]];
    }
    var spoken = {};
    var heard = GAME_STATS[$ "npcs_spoken_to"];
    if (is_struct(heard)) {
        for (var i = 0; i < NpcId.LEN; i++) {
            var name = npc_id_to_string(i);
            if (is_real(heard[$ name]) && heard[$ name] > 0) spoken[$ name] = heard[$ name];
        }
    }
    return { stats: stats, spoken: spoken };
}

function mistrimulti_progress_valid_counters(v) {
    return mistrimulti_progress_counts_valid(v[$ "stats"], 32) && mistrimulti_progress_counts_valid(v[$ "spoken"], 256);
}

function mistrimulti_progress_restore_counters(v) {
    var names = mistrimulti_progress_counter_names();
    for (var i = 0; i < array_length(names); i++) GAME_STATS[$ names[i]] = v.stats[$ names[i]] ?? 0;
    GAME_STATS.npcs_spoken_to = {};
    for (var i = 0; i < NpcId.LEN; i++) GAME_STATS.npcs_spoken_to[$ npc_id_to_string(i)] = v.spoken[$ npc_id_to_string(i)] ?? 0;
}

// ---- everything else that is personal -----------------------------------------------------------------------------------------

function mistrimulti_progress_capture_misc() {
    var off = [];
    for (var i = 0; i < Perk.LEN; i++) if (ARI.perks_active[i] == false) array_push(off, perk_to_string(i));
    var mount = undefined;
    if (ARI.mount != undefined) {
        // The same fields the game's own save writes (the mirroring flag is saved from the player, loaded onto the mount).
        mount = { kind: animal_kind_to_string(ARI.mount.kind), variant: ARI.mount.variant, sex: sex_to_string(ARI.mount.sex),
            name: ARI.mount.name, cosmetic: ARI.mount.cosmetic, mirroring: ARI.mount_mirroring_animal };
    }
    return { crown_cooldown: ARI.crown_cooldown, artifacts: clone_value(ARI.quest_artifacts.inner),
        pinned: opt_and_then(ARI.pinned_spell, spell_to_string), perks_off: off,
        renown: mistrimulti_progress_capture_renown(),
        renown_rewards: RENOWN_REWARD_INVENTORY.serialize(), mount: mount, mines_level: MAXIMUM_REACHED_DUNGEON_LEVEL };
}

// The town rank is shared (docs/SYNC-RENOWN.md): the total is the host's and each game is brought up to it by "carrier" entries
// in the pending list. Those are derived from the host's total, so the record keeps only this player's own queued gains.
function mistrimulti_progress_capture_renown() {
    var list = ARI.pending_renown_entries;
    var out = [];
    for (var i = 0; i < list.count(); i++) {
        var e = list.get(i);
        if (is_struct(e) && e[$ "mm_carrier"] == true) continue;
        array_push(out, serialize_renown_entry(e));
    }
    return out;
}

function mistrimulti_progress_valid_misc(v) {
    var cooldown = v[$ "crown_cooldown"];
    if (!is_nullish(cooldown) && !mistrimulti_progress_real_valid(cooldown)) return false;
    if (!is_struct(v[$ "artifacts"]) || !mistrimulti_progress_plain_valid(v.artifacts, 4)) return false;
    var pinned = v[$ "pinned"];
    if (!is_nullish(pinned) && !mistrimulti_progress_text_valid(pinned, 96)) return false;
    if (!mistrimulti_progress_names_valid(v[$ "perks_off"], 256)) return false;
    var renown = v[$ "renown"];
    if (!is_array(renown) || array_length(renown) > 256) return false;
    for (var i = 0; i < array_length(renown); i++) {
        if (!is_struct(renown[i]) || !mistrimulti_progress_text_valid(renown[i][$ "type"], 96) || !mistrimulti_progress_plain_valid(renown[i], 2)) return false;
    }
    if (!mistrimulti_player_inventory_valid(v[$ "renown_rewards"], 1, 64)) return false;
    if (!mistrimulti_progress_count_valid(v[$ "mines_level"]) || v.mines_level > 100000) return false;
    var mount = v[$ "mount"];
    if (is_nullish(mount)) return true;
    return is_struct(mount) && mistrimulti_progress_text_valid(mount[$ "kind"], 96) && mistrimulti_progress_text_valid(mount[$ "sex"], 96)
        && is_string(mount[$ "name"]) && string_length(mount.name) <= 64 && mistrimulti_progress_plain_valid(mount, 2);
}

function mistrimulti_progress_restore_misc(v) {
    ARI.crown_cooldown = is_nullish(v[$ "crown_cooldown"]) ? undefined : v.crown_cooldown;
    ARI.quest_artifacts = MapWrap(clone_value(v.artifacts));
    var spell = undefined;
    if (!is_nullish(v[$ "pinned"])) spell = mistrimulti_progress_index_map(Spell.LEN, spell_to_string)[$ v.pinned];
    ARI.set_pinned_spell(spell);
    ARI.perks_active = mistrimulti_progress_flags(v.perks_off, Perk.LEN, perk_to_string);
    for (var i = 0; i < Perk.LEN; i++) ARI.perks_active[i] = !ARI.perks_active[i];
    var entries = List();
    for (var i = 0; i < array_length(v.renown); i++) {
        // The game's deserializer assumes the item still exists; an entry that no longer loads is dropped.
        try { entries.push(deserialize_renown_entry(clone_value(v.renown[i]))); }
        catch (e) { mmapi_log_warn("mistrimulti", "A pending renown entry was dropped: " + string(e)); }
    }
    ARI.pending_renown_entries = entries;
    RENOWN_REWARD_INVENTORY.deserialize(v.renown_rewards);
    MAXIMUM_REACHED_DUNGEON_LEVEL = v.mines_level;
    ARI.mount = undefined;
    var mount = v[$ "mount"];
    var kind = undefined;
    var sex = undefined;
    if (!is_nullish(mount)) {
        kind = mistrimulti_progress_index_map(AnimalKind.LEN, animal_kind_to_string)[$ mount.kind];
        sex = mistrimulti_progress_index_map(Sex.LEN, sex_to_string)[$ mount.sex];
    }
    if (kind != undefined && sex != undefined) {
        ARI.mount = create_default_mount("mistmare");
        ARI.mount.kind = kind;
        ARI.mount.variant = mount[$ "variant"];
        ARI.mount.sex = sex;
        ARI.mount.name = mount.name;
        ARI.mount.cosmetic = mount[$ "cosmetic"];
        ARI.mount.mount_mirroring_animal = mount[$ "mirroring"];
        ARI.mount.prototype = ANIMAL_PROTOTYPES[kind];
        if (ARI.mount.cosmetic != undefined && !ARI.mount.prototype.cosmetics.contains_key(ARI.mount.cosmetic)) ARI.mount.cosmetic = undefined;
    }
}

// ---- daily flags (valid for the day they were saved on) ------------------------------------------------------------------------

function mistrimulti_progress_capture_daily() {
    return { day: string(CALENDAR.time), treasure: ARI.has_seen_treasure_level_today == true, ritual: ARI.has_seen_ritual_level_today == true,
        arena: ARI.has_seen_arena_level_today == true, gossiped: ARI.has_gossiped_today == true, left_house: ARI.has_left_house_today == true,
        soup: ARI.ate_perpetual_soup_today == true, objects: serialize_array_bool(ARI.used_object_today, object_id_to_string),
        scenes: MIST.scenes_played_today.keys() };
}

function mistrimulti_progress_defaults_daily() {
    return { day: string(CALENDAR.time), treasure: false, ritual: false, arena: false, gossiped: false, left_house: false, soup: false,
        objects: [], scenes: [] };
}

function mistrimulti_progress_valid_daily(v) {
    var flags = ["treasure", "ritual", "arena", "gossiped", "left_house", "soup"];
    for (var i = 0; i < array_length(flags); i++) if (!mistrimulti_progress_bool_valid(v[$ flags[i]])) return false;
    return mistrimulti_progress_text_valid(v[$ "day"], 24) && mistrimulti_progress_names_valid(v[$ "objects"], 512)
        && mistrimulti_progress_names_valid(v[$ "scenes"], 512);
}

function mistrimulti_progress_restore_daily(v) {
    // Yesterday's flags are not today's: a record from another day restores the new-day state.
    if (v.day != string(CALENDAR.time)) v = mistrimulti_progress_defaults_daily();
    ARI.has_seen_treasure_level_today = v.treasure;
    ARI.has_seen_ritual_level_today = v.ritual;
    ARI.has_seen_arena_level_today = v.arena;
    ARI.has_gossiped_today = v.gossiped;
    ARI.has_left_house_today = v.left_house;
    ARI.ate_perpetual_soup_today = v.soup;
    ARI.used_object_today = mistrimulti_progress_flags(v.objects, ObjectId.LEN, object_id_to_string);
    MIST.scenes_played_today = HashSetFromArray(v.scenes);
}

// ---- story rewards already received (MistriMultiStory.gml pays the rewards of story steps the player did not do) ----------------
// Per story quest, the level whose rewards this player has been given: by doing the step, or by the story sync. The ledger is kept
// as world facts ("mm_paid_<quest>", "mm_paid_init"), so on the host it is saved with the host's world, next to its inventory, and
// on a guest it travels in this section, next to the guest's record. `init` is false until the story sync has seeded the ledger
// (a new character, or a record from before this section): nothing is paid for steps that were already over by then.

function mistrimulti_progress_story_quests() {
    var out = [];
    var keys = QUESTS.keys();
    for (var i = 0; i < array_length(keys); i++) {
        var quest = QUESTS.get(keys[i]);
        if (quest != undefined && quest.category == QuestCategory.Story) array_push(out, keys[i]);
    }
    return out;
}

function mistrimulti_progress_capture_story_rewards() {
    var paid = {};
    var quests = mistrimulti_progress_story_quests();
    for (var i = 0; i < array_length(quests); i++) {
        var level = T2R.read("mm_paid_" + quests[i]);
        if (is_real(level) && level > 0) paid[$ quests[i]] = level;
    }
    var out = { init: T2R.read("mm_paid_init") == true, paid: paid };
    var view = mistrimulti_progress_story_view();
    if (array_length(struct_get_names(view)) > 0) out.view = view;
    return out;
}

// The world cutscenes this player has been given the effects of but not watched yet ("mm_view": scene -> game day, text in
// the world facts; MistriMultiStory.gml). Missing in older records: nothing is held.
function mistrimulti_progress_story_view() {
    var text = T2R.read("mm_view");
    var data = undefined;
    if (is_string(text)) {
        try { data = json_parse(text); }
        catch (e) { data = undefined; }
    }
    return is_struct(data) ? data : {};
}

function mistrimulti_progress_valid_story_rewards(v) {
    if (!mistrimulti_progress_bool_valid(v[$ "init"]) || !is_struct(v[$ "paid"])) return false;
    var view = v[$ "view"];
    if (view != undefined) {
        if (!is_struct(view)) return false;
        var held = struct_get_names(view);
        if (array_length(held) > 64) return false;
        for (var i = 0; i < array_length(held); i++) {
            var day = view[$ held[i]];
            if (!mistrimulti_progress_text_valid(held[i], 96) || !is_real(day) || day != floor(day) || day < 0 || day > 1000000) return false;
        }
    }
    var keys = struct_get_names(v.paid);
    if (array_length(keys) > 2048) return false;
    for (var i = 0; i < array_length(keys); i++) {
        var level = v.paid[$ keys[i]];
        if (!mistrimulti_progress_text_valid(keys[i], 96) || !is_real(level) || level != floor(level) || level < 1 || level > 1000000) return false;
    }
    return true;
}

// Replaces the ledger of the game it is restored into: a guest starts from a copy of the host's world, which holds the host's ledger.
function mistrimulti_progress_restore_story_rewards(v) {
    var quests = mistrimulti_progress_story_quests();
    for (var i = 0; i < array_length(quests); i++) T2R.write("mm_paid_" + quests[i], v.paid[$ quests[i]]);
    T2R.write("mm_paid_init", v.init ? true : undefined);
    var view = v[$ "view"];
    T2R.write("mm_view", is_struct(view) && array_length(struct_get_names(view)) > 0 ? json_stringify(view) : undefined);
}

// ---- records ------------------------------------------------------------------------------------------------------------------

function mistrimulti_progress_size(sections) {
    var total = 0;
    var names = struct_get_names(sections);
    for (var i = 0; i < array_length(names); i++) total += string_byte_length(json_stringify(sections[$ names[i]]));
    return total;
}

function mistrimulti_progress_sections_valid(sections, allow_unknown) {
    if (!is_struct(sections)) return false;
    var names = struct_get_names(sections);
    for (var i = 0; i < array_length(names); i++) {
        if (!mistrimulti_progress_known(names[i])) { if (allow_unknown) continue; return false; }
        if (!mistrimulti_progress_section_valid(names[i], sections[$ names[i]])) return false;
    }
    return mistrimulti_progress_size(sections) <= MISTRIMULTI_PROGRESS_RECORD_BYTES;
}

function mistrimulti_progress_valid(data, uid, world) {
    if (!is_struct(data) || !is_real(data[$ "v"]) || data.v != MISTRIMULTI_PROGRESS_VERSION) return false;
    if (!is_string(data[$ "uid"]) || data.uid != uid || !is_string(data[$ "world"]) || data.world != world) return false;
    return mistrimulti_progress_sections_valid(data[$ "sections"], false);
}

// A full record from the sections a game reports (used by tests and the debug call).
function mistrimulti_progress_capture() {
    var r = __mistrimulti_runtime();
    var sections = {};
    var names = mistrimulti_progress_sections();
    for (var i = 0; i < array_length(names); i++) sections[$ names[i]] = mistrimulti_progress_capture_section(names[i]);
    return { v: MISTRIMULTI_PROGRESS_VERSION, uid: r.uid, world: r.world_key, sections: sections };
}

// Brings a stored envelope up to the current schema, or returns undefined (damaged, or written by a newer MistriaMulti).
// Sections this version does not know are dropped; a missing section restores as a new character's.
function mistrimulti_progress_migrate(saved) {
    if (!is_struct(saved) || !is_real(saved[$ "v"]) || saved.v < 1 || saved.v > MISTRIMULTI_PROGRESS_VERSION) return undefined;
    var data = saved[$ "data"];
    if (!is_real(saved[$ "revision"]) || saved.revision < 0 || saved.revision != floor(saved.revision)) return undefined;
    if (!is_struct(data) || !is_struct(data[$ "sections"])) return undefined;
    // Version 1 is the first: a later one converts the older sections here, one version at a time.
    var kept = {};
    var names = struct_get_names(data.sections);
    for (var i = 0; i < array_length(names); i++) {
        if (mistrimulti_progress_known(names[i])) kept[$ names[i]] = data.sections[$ names[i]];
    }
    return { v: MISTRIMULTI_PROGRESS_VERSION, revision: saved.revision,
        data: { v: data[$ "v"], uid: data[$ "uid"], world: data[$ "world"], sections: kept } };
}

// Applies a validated record to this game. A section that fails halfway is left out of later uploads, so the host keeps its copy.
function mistrimulti_progress_restore(data) {
    var r = __mistrimulti_runtime();
    var names = mistrimulti_progress_sections();
    var failed = 0;
    for (var i = 0; i < array_length(names); i++) {
        var section = data.sections[$ names[i]] ?? mistrimulti_progress_defaults_section(names[i]);
        try { mistrimulti_progress_restore_section(names[i], section); }
        catch (e) {
            r.progress_locked[$ names[i]] = true;
            failed++;
            mmapi_warn_rate_limited("mistrimulti_progress_restore", "mistrimulti", "Progress section " + names[i] + " could not be restored: " + string(e));
        }
    }
    try { T2R.update_daily(); }
    catch (e) { mmapi_warn_rate_limited("mistrimulti_progress_facts", "mistrimulti", "World facts could not be refreshed: " + string(e)); }
    if (failed > 0) r.player_error = "Some player progress could not be restored; it will not be overwritten.";
    mistrimulti_progress_baseline();
}

// Remember what the host holds, so only later changes are sent.
function mistrimulti_progress_baseline() {
    var r = __mistrimulti_runtime();
    r.progress_sigs = {};
    var names = mistrimulti_progress_sections();
    for (var i = 0; i < array_length(names); i++) {
        if (r.progress_locked[$ names[i]] == true) continue;
        r.progress_sigs[$ names[i]] = json_stringify(mistrimulti_progress_capture_section(names[i]));
    }
}

// A new character's progress.
function mistrimulti_progress_fresh() {
    var r = __mistrimulti_runtime();
    var sections = {};
    var names = mistrimulti_progress_sections();
    for (var i = 0; i < array_length(names); i++) sections[$ names[i]] = mistrimulti_progress_defaults_section(names[i]);
    mistrimulti_progress_restore({ sections: sections });
    // Like a new game, deliver the first letters. The host has none of this player's sections yet: nothing is baselined.
    try { ARI.inbox.on_new_day(); }
    catch (e) { mmapi_warn_rate_limited("mistrimulti_progress_mail", "mistrimulti", "First letters could not be delivered: " + string(e)); }
    r.progress_sigs = {};
}

// ---- host storage -------------------------------------------------------------------------------------------------------------

function mistrimulti_progress_path(uid) {
    var path = mistrimulti_player_path(uid);
    return string_copy(path, 1, string_length(path) - 5) + ".progress.json";
}

function mistrimulti_progress_load(uid) {
    var r = __mistrimulti_runtime();
    if (!mistrimulti_valid_uid(uid) || r.world_path == "") return undefined;
    var path = mistrimulti_progress_path(uid);
    for (var i = 0; i < 2; i++) {
        var file = path + (i == 0 ? "" : ".bak");
        if (!file_exists(file)) continue;
        var saved = mistrimulti_progress_migrate(try_read_json_file(file));
        if (saved != undefined && mistrimulti_progress_valid(saved.data, uid, r.world_key)) return saved;
    }
    return undefined;
}

function mistrimulti_progress_store(uid, revision, data) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || !mistrimulti_valid_uid(uid) || r.world_path == "") return false;
    if (!mistrimulti_progress_valid(data, uid, r.world_key)) return false;
    var path = mistrimulti_progress_path(uid);
    try {
        var old = mistrimulti_progress_load(uid);
        if (old != undefined) save_text_file(path + ".bak", json_stringify(old));
        save_text_file(path + ".tmp", json_stringify({ v: MISTRIMULTI_PROGRESS_VERSION, revision: revision, data: data }));
        file_rename(path + ".tmp", path);
        mistrimulti_progress_member(uid);
        return true;
    } catch (e) {
        r.player_error = "Player progress could not be saved on the host.";
        mmapi_warn_rate_limited("mistrimulti_progress_save", "mistrimulti", r.player_error + " " + string(e));
        return false;
    }
}

// The players this world has records for (the host cannot list a folder, so it keeps the list itself).
function mistrimulti_progress_member(uid) {
    var r = __mistrimulti_runtime();
    if (r.progress_members[$ uid] == true || array_length(struct_get_names(r.progress_members)) >= 256) return;
    r.progress_members[$ uid] = true;
    var path = r.world_path + "/members.json";
    try {
        save_text_file(path + ".tmp", json_stringify({ v: 1, players: struct_get_names(r.progress_members) }));
        file_rename(path + ".tmp", path);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_members", "mistrimulti", "The player list could not be saved on the host.");
    }
}

function mistrimulti_progress_members_load() {
    var r = __mistrimulti_runtime();
    var members = {};
    var path = r.world_path + "/members.json";
    var saved = file_exists(path) ? try_read_json_file(path) : undefined;
    if (is_struct(saved) && is_array(saved[$ "players"]) && array_length(saved.players) <= 256) {
        for (var i = 0; i < array_length(saved.players); i++) {
            if (mistrimulti_valid_uid(saved.players[i])) members[$ saved.players[i]] = true;
        }
    }
    return members;
}

function mistrimulti_progress_merge(uid, sections, ignore_saved) {
    var r = __mistrimulti_runtime();
    var base = ignore_saved ? undefined : mistrimulti_progress_load(uid);
    var merged = {};
    if (base != undefined) {
        var kept = struct_get_names(base.data.sections);
        for (var i = 0; i < array_length(kept); i++) merged[$ kept[i]] = base.data.sections[$ kept[i]];
    }
    var names = struct_get_names(sections);
    for (var i = 0; i < array_length(names); i++) merged[$ names[i]] = sections[$ names[i]];
    return { v: MISTRIMULTI_PROGRESS_VERSION, uid: uid, world: r.world_key, sections: merged };
}

// ---- events -------------------------------------------------------------------------------------------------------------------

function mistrimulti_progress_register_events() {
    var plain = { on_event: mistrimulti_progress_event };
    mistrimulti_event_register("progress_request", plain);
    mistrimulti_event_register("progress_start", plain);
    mistrimulti_event_register("progress_error", plain);
    mistrimulti_event_register("progress_saved", plain);
    mistrimulti_event_register("progress_flush", plain);
    mistrimulti_event_register("progress_update", { on_blob: mistrimulti_progress_upload });
    mistrimulti_event_register("progress_record", { on_blob: mistrimulti_progress_download });
    mistrimulti_event_register("romance_claims", { on_event: mistrimulti_romance_event, on_peer: mistrimulti_romance_peer });
    mistrimulti_event_register("romance_revoke", { on_event: mistrimulti_romance_event });
}

function mistrimulti_progress_send(kind, target, peer_epoch, revision, data) {
    var r = __mistrimulti_runtime();
    var text = json_stringify(data);
    if (string_byte_length(text) > MISTRIMULTI_PROGRESS_RECORD_BYTES + 1024) return false;
    return mistrimulti_event_send_blob(kind, text, target,
        { world: r.world_key, uid: data.uid, peer_epoch: peer_epoch, revision: revision });
}

// Host: a guest whose core record is in asks for its progress. Answered with a record, or with "none yet".
function mistrimulti_progress_request(player, data) {
    var r = __mistrimulti_runtime();
    var peer = r.peers[player];
    var core = r.player_sessions[player];
    if (r.mode != "host" || !r.player_ready || player == 0 || !is_struct(peer)) return true;
    if (data[$ "world"] != r.world_key || data[$ "uid"] != peer[$ "uid"] || !mistrimulti_valid_uid(data[$ "uid"])) return true;
    // Only the player the core handshake admitted (it refuses duplicate identities and the host's own).
    if (!is_struct(core) || core.uid != data.uid || core.epoch != peer.epoch) return true;
    var session = r.progress_sessions[player];
    if (is_struct(session) && session.epoch == peer.epoch && session.uid == data.uid) return true;
    // A player who started a new character in this world (profile_choice) gets no progress of the old one; it stays on disk.
    var replaced = core[$ "replaced"] == true;
    var saved = replaced ? undefined : mistrimulti_progress_load(data.uid);
    var path = mistrimulti_progress_path(data.uid);
    if (!replaced && saved == undefined && (file_exists(path) || file_exists(path + ".bak"))) {
        return mistrimulti_event_emit("progress_error", { peer_epoch: peer.epoch, message: "The host progress record needs recovery." }, player);
    }
    var success = saved == undefined
        ? mistrimulti_event_emit("progress_start", { peer_epoch: peer.epoch, uid: data.uid, world: r.world_key }, player)
        : mistrimulti_progress_send("progress_record", player, peer.epoch, saved.revision, saved.data);
    if (success) {
        r.progress_sessions[player] = { uid: data.uid, epoch: peer.epoch, revision: saved == undefined ? 0 : saved.revision,
            not_before: 0, replaced: replaced };
        mistrimulti_progress_member(data.uid);
    }
    return success;
}

function mistrimulti_progress_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (!is_struct(data)) return true;
    try {
        var kind = ctx.kind;
        if (kind == "progress_request") return mistrimulti_progress_request(player, data);
        if (r.mode != "join" || player != 0) return true;
        // The host asks everyone to send their latest state now (it is about to save, or a new day began).
        if (kind == "progress_flush") {
            r.player_last_checkpoint = 0;
            r.progress_checkpointed = 0;
            return true;
        }
        if (data[$ "peer_epoch"] != r.epoch) return true;
        if (kind == "progress_start" && data[$ "uid"] == r.uid && data[$ "world"] == r.world_key) {
            if (!r.progress_loaded) {
                if (MIST.is_running() || ARI == undefined) return false;
                mistrimulti_progress_fresh();
                mistrimulti_progress_applied();
            }
            r.player_error = "";
        } else if (kind == "progress_error") {
            r.player_error = string(data[$ "message"]);
            // The host refused an update: stop sending the section it names (it would be refused again), or everything in
            // the update when it names none. The other sections keep being sent.
            if (r.progress_revision != r.progress_saved_revision) {
                var refused = data[$ "section"];
                var blocked = mistrimulti_progress_known(refused) ? [refused] : struct_get_names(r.progress_pending);
                for (var i = 0; i < array_length(blocked); i++) r.progress_locked[$ blocked[i]] = true;
                r.progress_revision = r.progress_saved_revision;
                r.progress_pending = {};
            }
        } else if (kind == "progress_saved" && data[$ "world"] == r.world_key && data[$ "revision"] == r.progress_revision) {
            var names = struct_get_names(r.progress_pending);
            for (var i = 0; i < array_length(names); i++) r.progress_sigs[$ names[i]] = r.progress_pending[$ names[i]];
            r.progress_pending = {};
            r.progress_saved_revision = r.progress_revision;
            r.player_error = "";
        }
        return true;
    } catch (e) {
        r.player_error = "A progress message could not be processed.";
        mmapi_warn_rate_limited("mistrimulti_progress_event", "mistrimulti", r.player_error + " " + string(e));
        return false;
    }
}

// Host: the guest's changed sections arrive as one blob.
function mistrimulti_progress_upload(player, text, meta) {
    var r = __mistrimulti_runtime();
    try {
        if (r.mode != "host" || player == 0 || !is_struct(meta)) return true;
        var peer = r.peers[player];
        var session = r.progress_sessions[player];
        if (!is_struct(peer) || !is_struct(session) || session.epoch != peer[$ "epoch"] || session.uid != peer[$ "uid"]) return true;
        if (meta[$ "peer_epoch"] != session.epoch || meta[$ "uid"] != session.uid || meta[$ "world"] != r.world_key) return true;
        var revision = meta[$ "revision"];
        if (!is_real(revision) || revision < 0 || revision != floor(revision)) return true;
        var ack = { peer_epoch: session.epoch, world: r.world_key, revision: revision };
        if (revision == session.revision) return mistrimulti_event_emit("progress_saved", ack, player);
        if (revision != session.revision + 1) return true;
        // At most one write a second per player (and a pause after a failed one): a record is large, a disk can be slow.
        if (get_timer() < session.not_before) return false;
        var update;
        try { update = json_parse(text); }
        catch (e) { return true; }
        var refusal = mistrimulti_progress_refusal(update, session.uid);
        if (refusal != undefined) {
            return mistrimulti_event_emit("progress_error", { peer_epoch: session.epoch, message: "A progress update was rejected.", section: refusal }, player);
        }
        var merged = mistrimulti_progress_merge(session.uid, update.sections, session[$ "replaced"] == true && session.revision == 0);
        if (mistrimulti_progress_size(merged.sections) > MISTRIMULTI_PROGRESS_RECORD_BYTES) {
            return mistrimulti_event_emit("progress_error", { peer_epoch: session.epoch, message: "Player progress exceeds the save limit." }, player);
        }
        if (!mistrimulti_progress_store(session.uid, revision, merged)) {
            session.not_before = get_timer() + MISTRIMULTI_PROGRESS_RETRY;
            return false;
        }
        session.revision = revision;
        session.not_before = get_timer() + MISTRIMULTI_PROGRESS_MIN_GAP;
        return mistrimulti_event_emit("progress_saved", ack, player);
    } catch (e) {
        r.player_error = "A progress update could not be processed.";
        mmapi_warn_rate_limited("mistrimulti_progress_upload", "mistrimulti", r.player_error + " " + string(e));
        return false;
    }
}

// undefined when the update is acceptable, else the name of the first bad section ("" when the update itself is malformed).
function mistrimulti_progress_refusal(update, uid) {
    var r = __mistrimulti_runtime();
    if (!is_struct(update) || !is_real(update[$ "v"]) || update.v != MISTRIMULTI_PROGRESS_VERSION) return "";
    if (!is_string(update[$ "uid"]) || update.uid != uid || !is_string(update[$ "world"]) || update.world != r.world_key) return "";
    if (!is_struct(update[$ "sections"])) return "";
    var names = struct_get_names(update.sections);
    if (array_length(names) == 0) return "";
    for (var i = 0; i < array_length(names); i++) {
        if (!mistrimulti_progress_known(names[i]) || !mistrimulti_progress_section_valid(names[i], update.sections[$ names[i]])) return names[i];
    }
    return undefined;
}

// Guest: the host's saved progress arrives as one blob.
function mistrimulti_progress_download(player, text, meta) {
    var r = __mistrimulti_runtime();
    try {
        if (r.mode != "join" || player != 0 || !is_struct(meta)) return true;
        if (meta[$ "peer_epoch"] != r.epoch || meta[$ "uid"] != r.uid || meta[$ "world"] != r.world_key) return true;
        var revision = meta[$ "revision"];
        if (!is_real(revision) || revision < 0 || revision != floor(revision)) return true;
        if (r.progress_loaded) return true;
        var record;
        try { record = json_parse(text); }
        catch (e) { r.player_error = "The host sent an invalid progress record."; return true; }
        if (!mistrimulti_progress_valid(record, r.uid, r.world_key)) {
            r.player_error = "The host sent an invalid progress record.";
            return true;
        }
        if (MIST.is_running() || ARI == undefined) return false;
        mistrimulti_progress_restore(record);
        r.progress_revision = revision;
        r.progress_saved_revision = revision;
        mistrimulti_progress_applied();
        return true;
    } catch (e) {
        r.player_error = "The progress record could not be processed.";
        mmapi_warn_rate_limited("mistrimulti_progress_download", "mistrimulti", r.player_error + " " + string(e));
        return false;
    }
}

// ---- guest checkpoint ---------------------------------------------------------------------------------------------------------

function mistrimulti_progress_checkpoint() {
    var r = __mistrimulti_runtime();
    if (r.mode != "join" || !r.player_ready || !r.progress_loaded || ARI == undefined || r.character_pending) return false;
    // One upload at a time, so the host always applies them in order.
    if (r.progress_revision != r.progress_saved_revision) return false;
    var changed = {};
    var pending = {};
    var count = 0;
    var total = 0;
    var names = mistrimulti_progress_sections();
    for (var i = 0; i < array_length(names); i++) {
        if (r.progress_locked[$ names[i]] == true) continue;
        var value = mistrimulti_progress_capture_section(names[i]);
        var text = json_stringify(value);
        if (string_byte_length(text) > MISTRIMULTI_PROGRESS_SECTION_BYTES) {
            r.progress_locked[$ names[i]] = true;
            r.player_error = "Player progress exceeds the current save limit.";
            continue;
        }
        if (r.progress_sigs[$ names[i]] == text) continue;
        changed[$ names[i]] = value;
        pending[$ names[i]] = text;
        total += string_byte_length(text);
        count++;
    }
    if (count == 0) return true;
    if (total > MISTRIMULTI_PROGRESS_RECORD_BYTES) {
        r.player_error = "Player progress exceeds the current save limit.";
        return false;
    }
    var update = { v: MISTRIMULTI_PROGRESS_VERSION, uid: r.uid, world: r.world_key, sections: changed };
    if (!mistrimulti_progress_send("progress_update", 0, r.epoch, r.progress_revision + 1, update)) return false;
    r.progress_revision++;
    r.progress_pending = pending;
    return true;
}

// Called every frame from the player-data tick.
function mistrimulti_progress_tick() {
    var r = __mistrimulti_runtime();
    try {
        if (r.mode == "join") {
            if (r.progress_core_loaded && r.progress_request == "" && mistrimulti_event_can_emit(1)) {
                if (mistrimulti_event_emit("progress_request", { world: r.world_key, uid: r.uid }, 0)) r.progress_request = r.epoch;
            }
            if (!r.player_ready || r.character_pending || MIST.is_running()) return;
            if (get_timer() - r.progress_checkpointed >= MISTRIMULTI_PROGRESS_INTERVAL && mistrimulti_event_blobs_pending() == 0) {
                r.progress_checkpointed = get_timer();
                mistrimulti_progress_checkpoint();
            }
        } else if (r.mode == "host" && r.player_ready) {
            if (get_timer() - r.romance_scanned >= 1000000) {
                r.romance_scanned = get_timer();
                mistrimulti_romance_scan_host();
            }
            mistrimulti_romance_publish();
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_progress_tick", "mistrimulti", "Player progress will retry: " + string(e));
    }
}

// Host: ask every guest to send its latest state now (the host is about to save, or a day just ended).
function mistrimulti_progress_flush_request() {
    var r = __mistrimulti_runtime();
    if (r.enabled && r.mode == "host" && r.mask != 0 && mistrimulti_event_can_emit(1)) mistrimulti_event_emit("progress_flush", {});
}

// ---- host save commit ---------------------------------------------------------------------------------------------------------
// The host's world is saved only when the game saves, but player records are written every few seconds. If a record could be newer
// than the save that is later reloaded, a player would keep items the reloaded world never gave out. So each host save also commits a
// copy of every player's record (commits/<save name>.json, two generations), and loading that save restores that copy first.

function mistrimulti_commit_key(save_path) {
    if (!is_string(save_path)) return "";
    var text = string_replace_all(save_path, "\\", "/");
    var start = 1;
    for (var i = string_length(text); i >= 1; i--) {
        if (string_char_at(text, i) == "/") { start = i + 1; break; }
    }
    var name = string_copy(text, start, 100);
    var key = "";
    for (var i = 1; i <= string_length(name); i++) {
        var c = string_char_at(name, i);
        var o = ord(c);
        var plain = (o >= 48 && o <= 57) || (o >= 65 && o <= 90) || (o >= 97 && o <= 122) || c == "-" || c == "_";
        key += plain ? c : "_";
    }
    return key;
}

function mistrimulti_commit_path(key) {
    return __mistrimulti_runtime().world_path + "/commits/" + key + ".json";
}

function mistrimulti_commit_snapshot(key) {
    var r = __mistrimulti_runtime();
    var players = {};
    var uids = struct_get_names(r.progress_members);
    for (var i = 0; i < array_length(uids); i++) {
        var core = mistrimulti_player_load(uids[i]);
        var progress = mistrimulti_progress_load(uids[i]);
        if (core != undefined || progress != undefined) players[$ uids[i]] = { core: core, progress: progress };
    }
    return { v: 1, key: key, world: r.world_key, day: string(CALENDAR.time), players: players };
}

function mistrimulti_commit_write(path, commit) {
    var old = file_exists(path) ? try_read_json_file(path) : undefined;
    if (is_struct(old) && is_real(old[$ "v"]) && old.v == 1) save_text_file(path + ".bak", json_stringify(old));
    save_text_file(path + ".tmp", json_stringify(commit));
    file_rename(path + ".tmp", path);
}

function mistrimulti_commit_valid(commit) {
    var r = __mistrimulti_runtime();
    return is_struct(commit) && is_real(commit[$ "v"]) && commit.v == 1 && is_string(commit[$ "world"]) && commit.world == r.world_key
        && is_string(commit[$ "day"]) && is_struct(commit[$ "players"]);
}

// save.game_saving (the host's world is about to be written): commit the players' records that belong to it.
function mistrimulti_progress_game_saving(ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || r.mode != "host" || !r.player_ready || r.world_path == "") return;
    var key = mistrimulti_commit_key(ctx[$ "save_path"]);
    if (key == "") return;
    try { mistrimulti_commit_write(mistrimulti_commit_path(key), mistrimulti_commit_snapshot(key)); }
    catch (e) {
        r.player_error = "Player records could not be committed with the save.";
        mmapi_warn_rate_limited("mistrimulti_commit", "mistrimulti", r.player_error + " " + string(e));
    }
}

// save.game_loaded: remember which save is being loaded; the host's world session restores its commit.
function mistrimulti_progress_game_loaded(ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode == "join") return;
    r.progress_load_key = mistrimulti_commit_key(ctx[$ "save_path"]);
}

// The newest commit of this save whose in-game day matches the loaded world (the previous generation covers a save that
// was interrupted after its commit was written).
function mistrimulti_commit_pick(key) {
    var path = mistrimulti_commit_path(key);
    for (var i = 0; i < 2; i++) {
        var file = path + (i == 0 ? "" : ".bak");
        if (!file_exists(file)) continue;
        var commit = try_read_json_file(file);
        if (mistrimulti_commit_valid(commit) && commit.day == string(CALENDAR.time)) return commit;
    }
    return undefined;
}

// Replaces the players' working records with the ones committed with the save that was just loaded. What it replaces is kept in
// commits/discarded.json. Players who joined after that save have nothing to restore and keep their records.
function mistrimulti_commit_restore(key) {
    var r = __mistrimulti_runtime();
    var commit = mistrimulti_commit_pick(key);
    if (commit == undefined) {
        if (file_exists(mistrimulti_commit_path(key)) || file_exists(mistrimulti_commit_path(key) + ".bak")) {
            r.player_error = "Player records may be newer than this save.";
        }
        return false;
    }
    mistrimulti_commit_write(r.world_path + "/commits/discarded.json", mistrimulti_commit_snapshot(key));
    var uids = struct_get_names(commit.players);
    for (var i = 0; i < array_length(uids); i++) {
        var entry = commit.players[$ uids[i]];
        if (!mistrimulti_valid_uid(uids[i]) || !is_struct(entry)) continue;
        var core = entry[$ "core"];
        if (is_struct(core) && is_real(core[$ "revision"]) && !mistrimulti_player_store(uids[i], core.revision, core[$ "data"])) {
            mmapi_warn_rate_limited("mistrimulti_commit", "mistrimulti", "A committed player record was not restored.");
        }
        var progress = entry[$ "progress"];
        if (is_struct(progress) && is_real(progress[$ "revision"]) && !mistrimulti_progress_store(uids[i], progress.revision, progress[$ "data"])) {
            mmapi_warn_rate_limited("mistrimulti_commit", "mistrimulti", "A committed progress record was not restored.");
        }
        mistrimulti_progress_member(uids[i]);
    }
    return true;
}

// The host's world session starts: restore the loaded save's commit, then rebuild the one-partner registry from the records.
function mistrimulti_progress_host_session() {
    var r = __mistrimulti_runtime();
    directory_create(r.world_path + "/commits");
    r.progress_members = mistrimulti_progress_members_load();
    var key = r.progress_load_key;
    r.progress_load_key = "";
    if (key != "") {
        try { mistrimulti_commit_restore(key); }
        catch (e) {
            r.player_error = "Player records could not be restored for this save.";
            mmapi_warn_rate_limited("mistrimulti_commit", "mistrimulti", r.player_error + " " + string(e));
        }
    }
    r.romance = {};
    r.romance_spouse = {};
    r.romance_dirty = true;
    mistrimulti_romance_scan_host();
    var uids = struct_get_names(r.progress_members);
    for (var i = 0; i < array_length(uids); i++) {
        var saved = mistrimulti_player_load(uids[i]);
        if (saved != undefined) mistrimulti_romance_apply(uids[i], saved.data.relations);
    }
}

// ---- one partner per NPC ------------------------------------------------------------------------------------------------------
// An NPC can be dating, engaged to or married to one player at a time. The host keeps the claims (NPC -> player), derived from the
// records; guests lock the romance prompts of an NPC someone else holds. Friendship and "best friend" stay open to everyone.

function mistrimulti_romance_romantic(status) {
    return status == "dating" || status == "fiance" || status == "spouse";
}

// A player has one spouse (the game's ARI.spouse() is one villager): the first one a record names keeps it.
function mistrimulti_romance_spouse_free(uid, name) {
    var r = __mistrimulti_runtime();
    var names = struct_get_names(r.romance_spouse);
    for (var i = 0; i < array_length(names); i++) if (r.romance_spouse[$ names[i]] == uid && names[i] != name) return false;
    return true;
}

// Registers the claims in a player's relations and returns the NPC indexes whose claim belongs to another player.
function mistrimulti_romance_apply(uid, relations) {
    var r = __mistrimulti_runtime();
    var lost = [];
    if (!is_array(relations)) return lost;
    for (var i = 0; i < array_length(relations); i++) {
        var name = npc_id_to_string(i);
        var holder = r.romance[$ name];
        if (mistrimulti_romance_romantic(relations[i].status)) {
            if (holder == undefined) { r.romance[$ name] = uid; r.romance_dirty = true; }
            else if (holder != uid) array_push(lost, i);
        } else if (holder == uid) {
            struct_remove(r.romance, name);
            r.romance_dirty = true;
        }
        // A married player's spouse lives at the farm in every game (MistriMultiStory.gml), even while that player is away.
        var married = relations[i].status == "spouse" && r.romance[$ name] == uid && mistrimulti_romance_spouse_free(uid, name);
        if (married && r.romance_spouse[$ name] != uid) { r.romance_spouse[$ name] = uid; r.romance_dirty = true; }
        else if (!married && r.romance_spouse[$ name] == uid) { struct_remove(r.romance_spouse, name); r.romance_dirty = true; }
    }
    return lost;
}

// A stored core record may not claim an NPC another player holds: the later claim is downgraded to "best friend" before it is
// saved. Returns the NPC names, which the host sends to that player so the game state follows.
function mistrimulti_romance_arbitrate(uid, profile) {
    var lost = mistrimulti_romance_apply(uid, profile[$ "relations"]);
    var names = [];
    for (var i = 0; i < array_length(lost); i++) {
        profile.relations[lost[i]].status = "best_friend";
        array_push(names, npc_id_to_string(lost[i]));
    }
    return names;
}

// The host's own relationships claim NPCs too.
function mistrimulti_romance_scan_host() {
    var r = __mistrimulti_runtime();
    var relations = [];
    for (var i = 0; i < NpcId.LEN; i++) array_push(relations, { status: T2R.read(npc_id_to_string(i) + "_status") ?? "undefined" });
    var lost = mistrimulti_romance_apply(r.uid, relations);
    var names = [];
    for (var i = 0; i < array_length(lost); i++) array_push(names, npc_id_to_string(lost[i]));
    if (array_length(names) > 0) mistrimulti_romance_revoke(names);
}

// Sets an NPC back to "best friend" in this game when another player holds them.
function mistrimulti_romance_revoke(names) {
    for (var i = 0; i < array_length(names); i++) {
        var npc = try_string_to_npc_id(names[i]);
        if (npc == undefined || T2R.read(names[i] + "_status") != "dating") continue;
        T2R.write(names[i] + "_status", "best_friend");
        NPCS[npc].report_relationship();
    }
}

function mistrimulti_romance_publish() {
    var r = __mistrimulti_runtime();
    if (!r.romance_dirty || !mistrimulti_event_can_emit(1)) return;
    if (mistrimulti_event_emit("romance_claims", { claims: r.romance, spouses: r.romance_spouse })) r.romance_dirty = false;
}

// Host: a game just joined; it missed the earlier claim events.
function mistrimulti_romance_peer(slot, joined, stream) {
    var r = __mistrimulti_runtime();
    if (joined && r.mode == "host" && r.player_ready) mistrimulti_event_emit("romance_claims", { claims: r.romance, spouses: r.romance_spouse }, slot);
}

function mistrimulti_romance_event(player, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "join" || player != 0 || !is_struct(data)) return true;
    try {
        if (ctx.kind == "romance_claims") {
            var claims = data[$ "claims"];
            if (!is_struct(claims)) return true;
            var names = struct_get_names(claims);
            if (array_length(names) > 256) return true;
            var view = {};
            for (var i = 0; i < array_length(names); i++) {
                if (mistrimulti_progress_text_valid(names[i], 96) && mistrimulti_valid_uid(claims[$ names[i]])) view[$ names[i]] = claims[$ names[i]];
            }
            r.romance_view = view;
            r.romance_spouse_view = mistrimulti_romance_spouse_view(data[$ "spouses"], view);
        } else if (ctx.kind == "romance_revoke" && data[$ "peer_epoch"] == r.epoch && mistrimulti_progress_names_valid(data[$ "npcs"], 64)) {
            mistrimulti_romance_revoke(data.npcs);
        }
        return true;
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_romance", "mistrimulti", "A relationship update could not be applied: " + string(e));
        return false;
    }
}

// The married players' spouses as a guest accepts them from the host: only an NPC that the same player also holds in the claims.
function mistrimulti_romance_spouse_view(spouses, claims) {
    var view = {};
    if (!is_struct(spouses)) return view;
    var names = struct_get_names(spouses);
    if (array_length(names) > 256) return view;
    for (var i = 0; i < array_length(names); i++) {
        if (mistrimulti_progress_text_valid(names[i], 96) && claims[$ names[i]] != undefined && claims[$ names[i]] == spouses[$ names[i]]) {
            view[$ names[i]] = spouses[$ names[i]];
        }
    }
    return view;
}

// dialogue.romance_prompt_guard: grey out the romance prompts of an NPC another player is with.
function mistrimulti_romance_prompt_guard(ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || !is_real(ctx[$ "npc_id"])) return undefined;
    var claims = r.mode == "host" ? r.romance : r.romance_view;
    var holder = claims[$ npc_id_to_string(ctx.npc_id)];
    if (holder != undefined && holder != r.uid) return false;
    return undefined;
}

function mistrimulti_debug_progress() {
    var r = __mistrimulti_runtime();
    var sizes = {};
    var names = mistrimulti_progress_sections();
    for (var i = 0; i < array_length(names); i++) sizes[$ names[i]] = string_byte_length(json_stringify(mistrimulti_progress_capture_section(names[i])));
    return { loaded: r.progress_loaded, revision: r.progress_revision, saved_revision: r.progress_saved_revision,
        locked: struct_get_names(r.progress_locked), sizes: sizes, romance: r.romance, members: struct_get_names(r.progress_members),
        spouses: r.mode == "host" ? r.romance_spouse : r.romance_spouse_view };
}
