function __mistrimulti_runtime() {
    if (global[$ "__mistrimulti"] == undefined) {
        global.__mistrimulti = {
            registered: false, initialized: false, enabled: false,
            ticks: 0, id: 0, epoch: "", mode: "off", bridge: "",
            peers: array_create(8, undefined), ev: undefined,
            peer_epoch: array_create(8, ""),
            mask: 0, last_mask: 0, look_signature: "", watches: [],
            terrain_cursor: -1, snapshot_pending: false,
            dirty_world: false, apply_depth: 0, last_frame: "",
            warning: "", clock: undefined, room: "", status: undefined,
            status_heartbeat: -1, status_seen_at: 0,
            character_owner: undefined, character_pending: false,
            character_ready_ticks: 0, character_menu: undefined,
            character_preset: undefined, character_loaded: false,
        };
    }
    return global.__mistrimulti;
}

function mistrimulti_initialize() {
    var r = __mistrimulti_runtime();
    r.initialized = true;
    r.boot_stage = "control";
    mmapi_log_info("mistrimulti", "Data directory: " + mmapi_mod_data_dir("mistrimulti"));
    mmapi_log_flush("mistrimulti");
    var control = mmapi_mod_data_dir("mistrimulti") + "/control.json";
    if (!file_exists(control)) return;
    var cfg = try_read_json_file(control);
    if (!is_struct(cfg) || cfg[$ "enabled"] != true) return;
    if (cfg[$ "mode"] != "host" && cfg[$ "mode"] != "join") return;
    if (!is_real(cfg[$ "id"]) || cfg.id < 0 || cfg.id > 7 || floor(cfg.id) != cfg.id) return;
    if ((cfg.mode == "host") != (cfg.id == 0)) return;
    if (!is_string(cfg[$ "epoch"]) || !is_string(cfg[$ "bridge"])) return;
    // Bridge paths are confined to this mod's own data folder.
    var native_root = mmapi_mod_data_dir("mistrimulti") + "/bridge_";
    var root = string_replace_all(native_root, "\\", "/");
    var bridge = string_replace_all(cfg.bridge, "\\", "/");
    if (string_lower(bridge) != string_lower(root + string(cfg.id))) return;
    r.boot_stage = "bridge directory";
    r.id = cfg.id;
    r.epoch = cfg.epoch;
    r.mode = cfg.mode;
    r.bridge = native_root + string(cfg.id);
    directory_create(r.bridge);
    mistrimulti_identity_initialize(cfg);
    mistrimulti_trust_initialize();
    mistrimulti_player_data_initialize();
    mistrimulti_events_initialize();
    mistrimulti_register_events();
    r.enabled = true;
    r.boot_stage = "ready";
    // Register diagnostics only when the MMAPI debug agent is enabled.
    var debug_cfg = mmapi_config_load("mmapi");
    global.__mistrimulti_debug_on = debug_cfg[$ "debug_enabled"] == true;
    if (global.__mistrimulti_debug_on) {
        mmapi_debug_register_fn("mistrimulti.inspect", mistrimulti_debug_inspect, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.tile", mistrimulti_debug_tile, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.apply", mistrimulti_apply_terrain, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.guard", mistrimulti_save_guard, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.watch", mistrimulti_tool_targets, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.player_data", mistrimulti_debug_player_data, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.checkpoint", mistrimulti_player_checkpoint, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.player_store", mistrimulti_player_store, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.player_load", mistrimulti_player_load, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.player_restore", mistrimulti_player_restore, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.events", mistrimulti_events_debug, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.progress", mistrimulti_debug_progress, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.farm", mistrimulti_farm_debug, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.character", mistrimulti_debug_character, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.containers", mistrimulti_containers_debug, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.drops", mistrimulti_drops_debug, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.ranch", mistrimulti_ranch_debug, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.guestsave", mistrimulti_guestsave_debug, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.import_character", mistrimulti_guestsave_import, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.wallet", mistrimulti_wallet_debug, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.dungeon", mistrimulti_dungeon_debug, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.story", mistrimulti_story_debug, { mod_name: "mistrimulti" });
        mmapi_debug_register_fn("mistrimulti.trust", mistrimulti_trust_debug, { mod_name: "mistrimulti" });
    }
    mmapi_log_info("mistrimulti", "MistriMulti 0.2.0 loaded: " + r.mode);
    mmapi_log_flush("mistrimulti");
}

// Every synced feature registers its event kinds here (see docs/EVENT-LAYER.md).
function mistrimulti_register_events() {
    mistrimulti_event_register("look", { on_event: mistrimulti_look_event, on_peer: mistrimulti_look_peer });
    mistrimulti_terrain_register_events();
    mistrimulti_farm_register_events();
    mistrimulti_player_register_events();
    mistrimulti_clock_register_events();
    mistrimulti_containers_register_events();
    mistrimulti_drops_register_events();
    mistrimulti_ranch_register_events();
    mistrimulti_dungeon_register_events();
    mistrimulti_progress_register_events();
    mistrimulti_wallet_register_events();
    mistrimulti_story_register_events();
}

function mistrimulti_room_key() {
    if (!instance_exists(obj_ari) || GRID == undefined) return "";
    return location_id_to_string(CURRENT_LOCATION_ID) + ":" + string(GRID.dyn_index) + mistrimulti_dg_room_suffix();
}

function mistrimulti_tick() {
    var r = __mistrimulti_runtime();
    // The Host / Join menu and the badge's watchdog work on the title screen too, before any multiplayer world exists.
    try { mistrimulti_menu_tick(); mistrimulti_badge_watchdog(); }
    catch (e) { mmapi_warn_rate_limited("mistrimulti_menu_tick", "mistrimulti", "Multiplayer menu tick failed: " + string(e)); }
    // Multiplayer starts only after the player picked the multiplayer save space.
    if (!r.initialized && !__mistrimulti_savespace().active) return;
    if (!r.initialized) {
        try { mistrimulti_initialize(); }
        catch (e) {
            r.enabled = false;
            r.warning = "Startup failed at " + r.boot_stage;
            mmapi_log_error("mistrimulti", r.warning + ": " + string(e));
            mmapi_log_flush("mistrimulti");
        }
    }
    if (!r.enabled) return;
    r.ticks++;

    if (r.ticks mod 60 == 1) {
        mistrimulti_flush_roster();
        var status_path = r.bridge + "/status.json";
        if (file_exists(status_path)) {
            var st = try_read_json_file(status_path);
            if (is_struct(st) && st[$ "running"] == true && is_real(st[$ "mask"]) && is_real(st[$ "heartbeat"])) {
                r.status = st;
                if (st.heartbeat != r.status_heartbeat) {
                    r.status_heartbeat = st.heartbeat;
                    r.status_seen_at = get_timer();
                }
                r.mask = get_timer() - r.status_seen_at < 3000000 ? clamp(floor(st.mask), 0, 255) : 0;
            } else { r.mask = 0; }
        } else { r.mask = 0; }
    }
    mistrimulti_player_data_tick();
    mistrimulti_character_tick();
    mistrimulti_guestsave_tick();
    mistrimulti_drops_frame(); // every frame: the game's item pickup is checked against the host's claims
    if (r.ticks mod 3 != 0) return; // 20 Hz bridge; actors animate at the game frame rate.
    if (ARI != undefined && GRID != undefined) mistrimulti_read_peers();
    mistrimulti_events_tick();
    var active = instance_exists(obj_ari) && ARI != undefined && GRID != undefined && r.player_ready && !r.character_pending;
    if (active) {
        mistrimulti_watch_changes();
        if (r.ticks mod 60 == 0 || r.mask != r.last_mask) mistrimulti_update_look();
        if (r.mode == "host" && (r.mask & ~r.last_mask) != 0) r.snapshot_pending = true;
        r.last_mask = r.mask;
        mistrimulti_stream_terrain();
        mistrimulti_containers_tick();
        mistrimulti_drops_tick();
        mistrimulti_ranch_tick();
        mistrimulti_dungeon_tick();
        mistrimulti_farm_tick();
        mistrimulti_wallet_tick();
        mistrimulti_story_tick();
    } else {
        mistrimulti_remove_ghosts();
    }
    var frame = { v: 2, epoch: r.epoch, id: r.id, uid: r.uid, active: active, world: r.world_key };
    if (active) {
        var ari = instance_find(obj_ari, 0);
        frame.room = mistrimulti_room_key();
        frame.x = round(ari.x * 10) / 10;
        frame.y = round(ari.y * 10) / 10;
        frame.z = round(ari.z * 10) / 10;
        frame.c = ari.cardinal;
        frame.ba = ari.par.base_animation() ?? AnimationName.Idle;
        frame.att = ari.par.attachment == undefined ? -1 : ari.par.attachment.name;
        frame.ma = -1;
        for (var i = 0; i < array_length(ari.par.slots); i++) {
            var ma = ari.par.slots[i].modifier.animation_name;
            if (ma != undefined) { frame.ma = ma; break; }
        }
        frame.name = string(ARI.name);
    }
    // The event layer adds as many queued events as fit within the helper's 16 KB frame. A game takes
    // part in events only while a world is loaded: on the title screen it would never acknowledge them.
    var in_world = ARI != undefined;
    var text = in_world ? mistrimulti_events_encode(frame) : json_stringify(frame);
    if (string_byte_length(text) > 16384) {
        r.warning = "A multiplayer update is too large.";
        return;
    }
    if (!mistrimulti_event_can_emit(1)) r.warning = "Multiplayer updates are waiting for a player.";
    else if (r.warning == "Multiplayer updates are waiting for a player.") r.warning = "";
    var reliable = in_world && mistrimulti_events_reliable();
    var framed = (reliable ? "1\n" : "0\n") + text;
    if (framed == r.last_frame) return;
    try {
        save_text_file(r.bridge + "/tx.tmp", framed);
        file_rename(r.bridge + "/tx.tmp", r.bridge + "/tx.frame");
        r.last_frame = framed;
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_tx", "mistrimulti", "Bridge write will retry.");
    }
}

function mistrimulti_read_peers() {
    var r = __mistrimulti_runtime();
    for (var i = 0; i < 8; i++) {
        if (i == r.id) continue;
        if ((r.mask & (1 << i)) == 0) {
            mistrimulti_hide_peer(i);
            r.peer_epoch[i] = "";
            continue;
        }
        var path = r.bridge + "/rx_" + string(i) + ".json";
        if (!file_exists(path)) continue;
        var p = try_read_json_file(path);
        if (!is_struct(p)) { mistrimulti_hide_peer(i); continue; }
        if (p[$ "v"] != 2 || p[$ "id"] != i || !is_string(p[$ "epoch"])) continue;
        if (p[$ "active"] == true) {
            if (!is_string(p[$ "room"]) || !is_real(p[$ "x"]) || !is_real(p[$ "y"])) continue;
            if (!is_real(p[$ "c"]) || p.c < 0 || p.c >= Cardinal.LEN) continue;
            if (!is_real(p[$ "ba"]) || p.ba < 0 || p.ba >= AnimationName.LEN) continue;
            if (abs(p.x) > 100000 || abs(p.y) > 100000) continue;
        }
        var old = r.peers[i];
        if (r.peer_epoch[i] != p.epoch) {
            mistrimulti_hide_peer(i);
            r.peer_epoch[i] = p.epoch;
            old = undefined;
        }
        if (is_struct(old)) {
            p.ghost = old[$ "ghost"];
            p.look = old[$ "look"];
        }
        var remember = !is_struct(old) || old[$ "name"] != p[$ "name"] || old[$ "uid"] != p[$ "uid"];
        r.peers[i] = p;
        // Delivers this peer's new events, in order, to the registered handlers.
        mistrimulti_events_receive(i, p);
        if (remember) mistrimulti_remember_peer(i);
        if (p[$ "active"] == true) mistrimulti_update_peer(i); else mistrimulti_hide_peer(i);
    }
}

function mistrimulti_look_event(player, look, ctx) {
    var r = __mistrimulti_runtime();
    var peer = r.peers[player];
    if (!is_struct(peer) || !mistrimulti_valid_look(look)) return true;
    peer.look = look;
    var ghost = peer[$ "ghost"];
    if (ghost != undefined && instance_exists(ghost)) mistrimulti_apply_peer_look(ghost, look);
    mistrimulti_remember_peer(player);
    return true;
}

// A game that just joined missed earlier appearance events: send ours again (within a second).
function mistrimulti_look_peer(slot, joined, stream) {
    if (joined) __mistrimulti_runtime().look_signature = "";
}

function mistrimulti_update_look() {
    var r = __mistrimulti_runtime();
    var look = ARI.animation_assets().serialize();
    var signature = json_stringify(look);
    if (signature != r.look_signature || r.mask != r.last_mask) {
        if (mistrimulti_event_emit("look", look)) r.look_signature = signature;
    }
}

function mistrimulti_save_guard(ctx) {
    var r = __mistrimulti_runtime();
    // A guest never saves (its character lives on the host) and nobody saves into the solo folder: MistriMultiGuestSave.gml.
    if (mistrimulti_guestsave_blocks(ctx)) return false;
    if (r.enabled && r.mode == "host") {
        mistrimulti_drops_before_save();
        mistrimulti_player_checkpoint();
        mistrimulti_player_checkpoint();
        mistrimulti_progress_flush_request();
    }
    return undefined;
}

function mistrimulti_new_day(ctx) {
    var r = __mistrimulti_runtime();
    if (r.enabled && r.mode == "host") {
        r.snapshot_pending = true;
        // The host saves at the end of the day: have every guest send its latest state first.
        mistrimulti_progress_flush_request();
    }
}

function mistrimulti_room_changed(ctx) {
    var r = __mistrimulti_runtime();
    r.watches = [];
    if (r.enabled && r.mode == "host") r.snapshot_pending = true;
}

function mistrimulti_show_status() {
    var r = __mistrimulti_runtime();
    if (!r.enabled) {
        // No multiplayer session yet: say what the badge says and why (the same words are in the log).
        var n = __mistrimulti_netstatus();
        mistrimulti_netstatus_refresh();
        var shown = mistrimulti_status_text().text;
        var reason = n.why != "" ? n.why : __mistrimulti_menu().why;
        create_notification(ANCHOR.wrap_for_local(shown + (reason != "" ? " (" + reason + ")" : "")));
        return;
    }
    var count = 0;
    for (var i = 0; i < 8; i++) if ((r.mask & (1 << i)) != 0) count++;
    var text = "MistriMulti: " + r.mode + " | " + string(count) + " connected";
    if (r.warning != "") text += " | " + r.warning;
    if (r.player_error != "") text += " | " + r.player_error;
    if (r.mode == "join" && r.player_revision > r.player_saved_revision) text += " | Saving player progress";
    var trust = mistrimulti_trust_status_text();
    if (trust != "") text += " | " + trust;
    create_notification(ANCHOR.wrap_for_local(text));
}

function mistrimulti_debug_tile(x, y) {
    var farm = GRIDS[LocationId.Farm];
    var tile = mistrimulti_terrain_tile(farm, x, y);
    return { tile: tile, occupied: farm.node_object_id[farm.node_index_for_cell(x, y)] != undefined };
}

function mistrimulti_debug_inspect() {
    var r = __mistrimulti_runtime();
    var ghosts = [];
    for (var i = 0; i < 8; i++) {
        var p = r.peers[i];
        if (!is_struct(p)) continue;
        var ghost = p[$ "ghost"];
        if (ghost != undefined && instance_exists(ghost)) {
            array_push(ghosts, { id: i, x: ghost.x, y: ghost.y, c: ghost.par.cardinal,
                ba: ghost.par.base_animation(), draws: ghost.draw_count,
                opacity: ghost.par.alpha, opacity_min: ghost.opacity_min,
                opacity_max: ghost.opacity_max, look: ghost.applied_look });
        }
    }
    var farm = GRIDS[LocationId.Farm];
    return { ghosts: ghosts, room: mistrimulti_room_key(), events: mistrimulti_events_debug(), dims: farm.dims,
        dirt: GroundKind.Dirt, soil: GroundKind.Soil,
        farm_id: LocationId.Farm, terrain_ground: TerrainKind.Ground,
        object_kind: string(global.__mistrimulti_peer_object) };
}

function mistrimulti_register() {
    var r = __mistrimulti_runtime();
    if (r.registered) return;
    r.registered = true;
    mmapi_register(mistrimulti_tick);
    mmapi_filter("tool.targets", mistrimulti_tool_targets);
    mistrimulti_farm_register_hooks();
    mmapi_guard("game.save_guard", mistrimulti_save_guard);
    mmapi_on("game.new_day", mistrimulti_new_day);
    mmapi_on("game.new_day", mistrimulti_drops_new_day);
    mmapi_override("object.interact", mistrimulti_containers_interact);
    mmapi_on("dungeon.treasure_chest", mistrimulti_drops_treasure);
    mmapi_on("resource.node_picked", mistrimulti_drops_rock);
    mmapi_on("game.room_changed", mistrimulti_room_changed);
    mmapi_on("save.game_saving", mistrimulti_progress_game_saving);
    mmapi_on("save.game_loaded", mistrimulti_progress_game_loaded);
    mmapi_on("save.game_saving", mistrimulti_wallet_game_saving);
    mmapi_on("save.game_loaded", mistrimulti_wallet_game_loaded);
    mmapi_filter("player.gold_delta", mistrimulti_wallet_gold_delta);
    mmapi_guard("dialogue.romance_prompt_guard", mistrimulti_romance_prompt_guard);
    mmapi_on("game.title_entered", mistrimulti_title_entered);
    mmapi_on("ui.menu_opened", mistrimulti_menu_opened);
    mmapi_on("ui.draw_gui", mistrimulti_draw_status);
    mmapi_filter("local.missing", mistrimulti_local_missing);
    mistrimulti_clock_register_hooks();
    mistrimulti_guestsave_register_hooks();
    mmapi_hotkey_register(mmapi_hotkey_vk_from_name("F8"), mistrimulti_show_status);
    mmapi_hotkey_register(mmapi_hotkey_vk_from_name("F9"), mistrimulti_drops_give_hotkey);
    // Host: approve / refuse a player identity that needs approval. Guest: accept a changed host identity.
    mmapi_hotkey_register(mmapi_hotkey_vk_from_name("F7"), mistrimulti_trust_hotkey_approve);
    mmapi_hotkey_register_binding(mmapi_hotkey_binding_from_name("SHIFT+F7"), mistrimulti_trust_hotkey_refuse);
    mistrimulti_ranch_register_hooks();
    mistrimulti_dungeon_register_hooks();
}

mmapi_mod_declare("mistrimulti", "0.2.0");
mistrimulti_register();
