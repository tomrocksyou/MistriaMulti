// Guest saving, leaving and returning. Design, assumptions and checklist: docs/SYNC-GUESTSAVE.md.
//
// A guest's game holds the host's world only transiently; the guest's character lives in the host's per-player records
// (docs/PLAYER-DATA.md, docs/SYNC-PROGRESS.md). So:
//   - a guest's game never saves: every save is vetoed, and the attempt flushes the character to the host instead;
//   - nothing is saved when leaving either (the game's own quit does not save): the settings menu opening is the last
//     moment the mod sees, so it flushes the character then, and a goodbye frame tells everyone else the session ended;
//   - a guest whose host is gone (closed, restarted, crashed, network down) gets a message and is returned to the title.
// Nothing here writes into any save folder. The only files are the goodbye frame in the bridge and the character export.

#macro MISTRIMULTI_GUESTSAVE_GRACE_LOST 20000000
#macro MISTRIMULTI_GUESTSAVE_GRACE_CLOSED 3000000
#macro MISTRIMULTI_GUESTSAVE_GRACE_RESTART 2000000
#macro MISTRIMULTI_GUESTSAVE_WARN 4000000
#macro MISTRIMULTI_GUESTSAVE_NOTICE_GAP 5000000
#macro MISTRIMULTI_GUESTSAVE_RETRY_GAP 3000000
#macro MISTRIMULTI_GUESTSAVE_RETRIES 10
#macro MISTRIMULTI_GUESTSAVE_EXPORT_GAP 60000000
#macro MISTRIMULTI_GUESTSAVE_EXPORT_BYTES 524288
#macro MISTRIMULTI_GUESTSAVE_BUSY "This player identity is already connected."

// State of the current world session (kept on the runtime, dropped at the title screen).
function __mistrimulti_guestsave() {
    var r = __mistrimulti_runtime();
    if (!is_struct(r[$ "guestsave"])) {
        r.guestsave = {
            in_session: false, leaving: false, reason: "", blocked: 0, notified_at: -1,
            host_epoch: "", host_world: "", state: "ok", state_at: 0, warned: false,
            flush_pending: false, retries: 0, retry_at: 0, exported: "", exported_at: -1, export_now: false, export_error: "",
        };
    }
    return r.guestsave;
}

// ---- saving -------------------------------------------------------------------------------------------------------------------

// A joined game, also when the runtime itself failed to start: the game is still in the host's world copy.
function mistrimulti_guestsave_is_guest() {
    var r = __mistrimulti_runtime();
    if (r.enabled && r.mode == "join") return true;
    try { return __mistrimulti_savespace().active && mistrimulti_savespace_mode() == "join"; }
    catch (e) { return false; }
}

// True when the path is inside the SOLO save folder (CONFIG_DIRECTORY was pointed at multiplayer/ when the space was entered).
function mistrimulti_guestsave_solo_path(path) {
    var s = __mistrimulti_savespace();
    if (!is_string(path) || !is_string(s.solo_dir)) return false;
    var solo = string_lower(string_replace_all(s.solo_dir, "\\", "/")) + "/saves/";
    var text = string_lower(string_replace_all(path, "\\", "/"));
    return string_copy(text, 1, string_length(solo)) == solo;
}

// game.save_guard: true = veto this save. A guest never saves; nobody in multiplayer ever writes into the solo save folder.
function mistrimulti_guestsave_blocks(ctx) {
    var r = __mistrimulti_runtime();
    var path = is_struct(ctx) ? ctx[$ "save_path"] : undefined;
    if (mistrimulti_guestsave_is_guest()) {
        mistrimulti_guestsave_blocked();
        return true;
    }
    try {
        if ((r.enabled || __mistrimulti_savespace().active) && mistrimulti_guestsave_solo_path(path)) {
            mmapi_log_error("mistrimulti", "Refused a multiplayer save into the solo save folder: " + path);
            return true;
        }
    } catch (e) { mmapi_warn_rate_limited("mistrimulti_guestsave_path", "mistrimulti", "Save path check failed: " + string(e)); }
    return false;
}

// The guest tried to save: tell them where their character is, and send it to the host now.
function mistrimulti_guestsave_blocked() {
    var g = __mistrimulti_guestsave();
    g.blocked++;
    try {
        mistrimulti_guestsave_flush();
        var now = get_timer();
        if (g.notified_at < 0 || now - g.notified_at >= MISTRIMULTI_GUESTSAVE_NOTICE_GAP) {
            g.notified_at = now;
            create_notification(ANCHOR.wrap_for_local("Guest game: nothing is saved on this computer. Your character is saved on the host's computer."));
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_guestsave_blocked", "mistrimulti", "Guest save notice failed: " + string(e));
    }
}

// Sends the character to the host now instead of at the next checkpoint. An upload sends one record at a time, so while the
// previous one is not acknowledged yet the flush is repeated by the tick as soon as it is (flush_pending).
function mistrimulti_guestsave_flush() {
    var r = __mistrimulti_runtime();
    var g = __mistrimulti_guestsave();
    if (!r.enabled || r.mode != "join" || !r.player_ready) return false;
    r.player_last_checkpoint = 0;
    r.progress_checkpointed = 0;
    if (MIST.is_running()) { g.flush_pending = true; return true; }
    mistrimulti_player_checkpoint();
    mistrimulti_progress_checkpoint();
    g.flush_pending = r.player_revision != r.player_saved_revision || r.progress_revision != r.progress_saved_revision;
    return true;
}

// ---- leaving ------------------------------------------------------------------------------------------------------------------

// ui.menu_opened. The game's quit options (settings: "Return to main menu", "Exit to desktop") do not save and give the mod
// no hook, so opening the settings menu is the last moment to push the character to the host.
function mistrimulti_guestsave_menu_opened(ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || r.mode != "join" || ARI == undefined || !is_struct(ctx) || ctx[$ "kind"] != Menu.Settings) return;
    try {
        __mistrimulti_guestsave().export_now = true;
        mistrimulti_guestsave_flush();
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_guestsave_menu", "mistrimulti", "Final flush failed: " + string(e));
    }
}

// game.title_entered: a session ended. Tell the other games with a final frame (the helper otherwise keeps sending our last
// one, so the host would keep a frozen ghost and the guests would never learn that the host left), then drop session state.
function mistrimulti_guestsave_title_entered(ctx) {
    var r = __mistrimulti_runtime();
    var was = __mistrimulti_guestsave().in_session;
    r.guestsave = undefined;
    if (!was || !is_string(r.bridge) || r.bridge == "") return;
    try {
        var frame = { v: 2, epoch: r.epoch, id: r.id, uid: r.uid, active: false, world: "" };
        save_text_file(r.bridge + "/tx.tmp", "0\n" + json_stringify(frame));
        file_rename(r.bridge + "/tx.tmp", r.bridge + "/tx.frame");
        r.last_frame = "";
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_guestsave_goodbye", "mistrimulti", "Final frame could not be written.");
    }
}

// Called every frame from the main tick while the runtime is enabled.
function mistrimulti_guestsave_tick() {
    var r = __mistrimulti_runtime();
    var g = __mistrimulti_guestsave();
    if (ARI == undefined) return;
    g.in_session = true;
    if (r.ticks mod 15 != 0) return;
    try {
        if (r.mode == "host") mistrimulti_guestsave_forget_departed();
        else if (!g.leaving) {
            if (g.flush_pending && r.player_revision == r.player_saved_revision && r.progress_revision == r.progress_saved_revision) {
                g.flush_pending = false;
                mistrimulti_guestsave_flush();
            }
            mistrimulti_guestsave_watch_host(g);
            mistrimulti_guestsave_retry(g);
            mistrimulti_guestsave_export_tick(g);
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_guestsave_tick", "mistrimulti", "Guest session check failed: " + string(e));
    }
}

// Host: a guest that quit to its title screen left a final frame (world ""). Its helper may keep the slot alive for 10 s or
// more, so forget its record session at once: the same player can come back through another slot without being refused.
function mistrimulti_guestsave_forget_departed() {
    var r = __mistrimulti_runtime();
    for (var i = 1; i < 8; i++) {
        var p = r.peers[i];
        if (is_struct(p) && p[$ "active"] == false && p[$ "world"] == "" && is_struct(r.player_sessions[i])) r.player_sessions[i] = undefined;
    }
}

// Guest: what is the host doing? ok | lost (no frames: closed, crashed or network down) | closed (its final frame) | restarted
// (a new world session or another world). Each non-ok state is given a short grace period; then the guest is sent to the title.
function mistrimulti_guestsave_watch_host(g) {
    var r = __mistrimulti_runtime();
    var host = r.peers[0];
    var state = "lost";
    if ((r.mask & 1) != 0 && is_struct(host) && is_string(host[$ "epoch"]) && is_string(host[$ "world"])) {
        if (host.world == "") state = "closed";
        else if (g.host_epoch == "") {
            g.host_epoch = host.epoch;
            g.host_world = host.world;
            state = "ok";
        } else state = (host.epoch == g.host_epoch && host.world == g.host_world) ? "ok" : "restarted";
    }
    if (g.host_epoch == "") return;   // the host has never been seen in this session: the guest is simply waiting for it
    var now = get_timer();
    if (state != g.state) {
        g.state = state;
        g.state_at = now;
        g.warned = false;
    }
    if (state == "ok") return;
    var grace = state == "lost" ? MISTRIMULTI_GUESTSAVE_GRACE_LOST
        : (state == "closed" ? MISTRIMULTI_GUESTSAVE_GRACE_CLOSED : MISTRIMULTI_GUESTSAVE_GRACE_RESTART);
    if (now - g.state_at >= grace) { mistrimulti_guestsave_leave(state); return; }
    if (state == "lost" && !g.warned && now - g.state_at >= MISTRIMULTI_GUESTSAVE_WARN) {
        g.warned = true;
        create_notification(ANCHOR.wrap_for_local("Connection to the host lost. Waiting for it to come back..."));
    }
}

// Guest: a player returning through another slot while the host still counts the old one is refused ("already connected") until
// the old slot expires (10 s). The handshake asks only once per session, so ask again every few seconds for a while.
function mistrimulti_guestsave_retry(g) {
    var r = __mistrimulti_runtime();
    if (r.player_ready) { g.retries = 0; return; }
    if (r.player_error != MISTRIMULTI_GUESTSAVE_BUSY || g.retries >= MISTRIMULTI_GUESTSAVE_RETRIES) return;
    var now = get_timer();
    if (now - g.retry_at < MISTRIMULTI_GUESTSAVE_RETRY_GAP) return;
    g.retry_at = now;
    g.retries++;
    r.player_request = "";
}

// The host is gone: say so, then go back to the title like the settings menu's "Return to main menu" does. Nothing is saved:
// the character is on the host, up to the last checkpoint.
function mistrimulti_guestsave_leave(reason) {
    var g = __mistrimulti_guestsave();
    if (g.leaving) return;
    g.leaving = true;
    g.reason = reason;
    mmapi_log_info("mistrimulti", "The host is gone (" + reason + "); returning to the title screen.");
    mmapi_log_flush("mistrimulti");
    try {
        var popup = popup_creator("mistrimulti/guest_gone_title",
            reason == "lost" ? "mistrimulti/guest_lost_body" : "mistrimulti/guest_closed_body");
        popup.create_button("misc_local/return_to_main_menu", mistrimulti_guestsave_exit);
        popup.spawn();
    } catch (e) {
        mmapi_log_error("mistrimulti", "Could not show the disconnect message: " + string(e));
        mistrimulti_guestsave_exit();
    }
}

function mistrimulti_guestsave_exit() {
    try { SCREEN_FADER.fade_out(FADE_SPEED_TRANSITION, mistrimulti_guestsave_exit_now); }
    catch (e) { mistrimulti_guestsave_exit_now(); }
}

function mistrimulti_guestsave_exit_now() {
    try { if (instance_exists(Game)) Game.exit_to_menu(); }
    catch (e) { mmapi_log_error("mistrimulti", "Returning to the title screen failed: " + string(e)); }
}

// ---- character export ---------------------------------------------------------------------------------------------------------
// A guest keeps no copy of the world, but a copy of its CHARACTER: exactly what the host acknowledged, as the two record
// envelopes the host stores (players/<id>.json and players/<id>.progress.json). It is a backup, and the input of
// mistrimulti_guestsave_import, which puts the character into a world this player hosts.

function mistrimulti_guestsave_export_dir() {
    return mmapi_mod_data_dir("mistrimulti") + "/exports";
}

function mistrimulti_guestsave_export_name(world_key, uid) {
    return string_replace_all(world_key, ":", "_") + "__" + string_replace_all(uid, ":", "_") + ".json";
}

// The acknowledged state as an export file, or undefined while an upload is in flight or a section has not been uploaded yet.
function mistrimulti_guestsave_export_build() {
    var r = __mistrimulti_runtime();
    if (!r.player_ready || !r.progress_loaded || r.player_signature == "" || r.world_key == "") return undefined;
    if (r.player_revision != r.player_saved_revision || r.progress_revision != r.progress_saved_revision) return undefined;
    var names = mistrimulti_progress_sections();
    for (var i = 0; i < array_length(names); i++) {
        if (r.progress_sigs[$ names[i]] == undefined && r.progress_locked[$ names[i]] != true) return undefined;
    }
    var sections = {};
    for (var i = 0; i < array_length(names); i++) {
        if (r.progress_sigs[$ names[i]] != undefined) sections[$ names[i]] = json_parse(r.progress_sigs[$ names[i]]);
    }
    return { v: 1, kind: "character_export", uid: r.uid, world: r.world_key,
        core: { v: 1, revision: r.player_revision, data: json_parse(r.player_signature) },
        progress: { v: MISTRIMULTI_PROGRESS_VERSION, revision: r.progress_revision,
            data: { v: MISTRIMULTI_PROGRESS_VERSION, uid: r.uid, world: r.world_key, sections: sections } } };
}

// Writes the export when the host holds a newer state than the last export: at most once a minute, or at once after the
// settings menu opened (the guest may be leaving).
function mistrimulti_guestsave_export_tick(g) {
    var r = __mistrimulti_runtime();
    var stamp = string(r.player_revision) + ":" + string(r.progress_revision);
    if (stamp == g.exported) return;
    var now = get_timer();
    if (!g.export_now && g.exported_at >= 0 && now - g.exported_at < MISTRIMULTI_GUESTSAVE_EXPORT_GAP) return;
    var file = mistrimulti_guestsave_export_build();
    if (file == undefined) return;
    var text = json_stringify(file);
    if (string_byte_length(text) > MISTRIMULTI_GUESTSAVE_EXPORT_BYTES) {
        g.export_error = "The character is too large to export.";
        g.exported = stamp;
        return;
    }
    var dir = mistrimulti_guestsave_export_dir();
    var path = dir + "/" + mistrimulti_guestsave_export_name(r.world_key, r.uid);
    g.exported_at = now;
    g.export_now = false;
    directory_create(dir);
    save_text_file(path + ".tmp", text);
    file_rename(path + ".tmp", path);
    g.exported = stamp;
}

// Host, debug console only (mistrimulti.import_character "<file name in the exports folder>"): puts an exported character of
// THIS identity into the world this game hosts. It replaces the host's own character and progress, like a record restore.
function mistrimulti_guestsave_import(name) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || r.mode != "host" || !r.player_ready || ARI == undefined) return "Only the host of a loaded world can import a character.";
    if (!is_string(name) || string_length(name) < 6 || string_length(name) > 160 || string_copy(name, string_length(name) - 4, 5) != ".json"
        || string_pos("/", name) > 0 || string_pos("\\", name) > 0 || string_pos("..", name) > 0 || string_pos(":", name) > 0) {
        return "Give the file name of an export (no folders).";
    }
    var path = mistrimulti_guestsave_export_dir() + "/" + name;
    var file = file_exists(path) ? try_read_json_file(path) : undefined;
    if (!is_struct(file) || file[$ "v"] != 1 || file[$ "kind"] != "character_export" || file[$ "uid"] != r.uid) return "That export is not for this player.";
    var core = is_struct(file[$ "core"]) ? file.core[$ "data"] : undefined;
    var progress = is_struct(file[$ "progress"]) ? file.progress[$ "data"] : undefined;
    if (!is_struct(core) || !is_struct(progress)) return "That export is damaged.";
    core.world = r.world_key;
    progress.world = r.world_key;
    // Validate everything before touching the live character.
    if (!mistrimulti_player_valid(core, r.uid, r.world_key) || !mistrimulti_progress_valid(progress, r.uid, r.world_key)) {
        return "That export does not fit this version of the game.";
    }
    if (!mistrimulti_player_restore(core)) return "The character could not be restored.";
    mistrimulti_progress_restore(progress);
    mistrimulti_player_checkpoint();
    return "Character imported. Save the game to keep it.";
}

// ---- registration, text and diagnostics ---------------------------------------------------------------------------------------

function mistrimulti_guestsave_register_hooks() {
    mmapi_on("ui.menu_opened", mistrimulti_guestsave_menu_opened);
    mmapi_on("game.title_entered", mistrimulti_guestsave_title_entered);
    mmapi_filter("local.missing", mistrimulti_guestsave_local_missing);
}

function mistrimulti_guestsave_local_missing(value, ctx) {
    switch (ctx.key) {
        case "mistrimulti/guest_gone_title": return "Disconnected from the host";
        case "mistrimulti/guest_lost_body": return "The connection to the host was lost. Your character was saved on the host's computer a few seconds ago, and nothing was saved here. Join again from MistriMulti to continue.";
        case "mistrimulti/guest_closed_body": return "The host closed or restarted the world. Your character stays on the host's computer. Join again from MistriMulti to continue.";
    }
    return undefined;
}

function mistrimulti_guestsave_debug() {
    var g = __mistrimulti_guestsave();
    return { guest: mistrimulti_guestsave_is_guest(), blocked: g.blocked, state: g.state, leaving: g.leaving, reason: g.reason,
        exported: g.exported, export_error: g.export_error, retries: g.retries };
}
