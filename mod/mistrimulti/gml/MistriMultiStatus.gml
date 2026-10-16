// "Multiplayer: Offline / Idle / Online (hosting|joined)" badge (bottom right) and the game-version check.
//   Offline = the game was updated past the tested versions, or the MistriaMulti launcher / helper is not running
//             (the text says which, in plain words).
//   Idle    = the launcher runs, nothing is hosted or joined: pick Multiplayer in New Game / Load Game.
//   Online  = a host or join session runs and the network helper's heartbeat is moving. In a multiplayer world this is read from
//             the very signals the event layer lives on (MistriMultiBoot.gml tick: the helper's status.json heartbeat, and the
//             peer mask built from it), so the badge cannot say "helper not running" while the game is playing; on the title
//             screen the control.json / status.json read below decides.
// The launcher's menu/status.json (MistriMultiMenu.gml) is the source for the first two; the helper's own status.json (found
// through control.json, written by the launcher for the session) decides Online. The badge shows on the title screen and in
// multiplayer worlds (as an ANCHOR text node, see MistriMultiHudText.gml), and it logs every change of its text with the reason, so a missing or wrong badge can be diagnosed
// from the game's log (mod_data/mistrimulti log) instead of guessed.
// Add a version here only after testing the mod against it.
function mistrimulti_supported_versions() { return ["1.0.6", "1.0.8"]; }

function mistrimulti_game_version_text() {
    try { return version_to_string(GAME_VERSION); } catch (e) { return ""; }
}

function mistrimulti_game_supported() {
    var v = mistrimulti_game_version_text();
    var list = mistrimulti_supported_versions();
    for (var i = 0; i < array_length(list); i++) if (list[i] == v) return true;
    return false;
}

function __mistrimulti_netstatus() {
    if (global[$ "__mistrimulti_netstatus"] == undefined) {
        global.__mistrimulti_netstatus = {
            frames: 0, armed: false, armed_at: 0, alive: false, hb: -1, hb_at: 0, warned: false, mode: "", last_text: "", why: "",
            draws: 0, ticks: 0, drawn: false,
        };
    }
    return global.__mistrimulti_netstatus;
}

// Reads control.json and the helper's status.json (about once a second; never every frame), and the launcher's menu status.
function mistrimulti_netstatus_refresh() {
    var n = __mistrimulti_netstatus();
    var was_armed = n.armed;
    n.armed = false;
    n.alive = false;
    n.mode = "";
    n.why = "";
    mistrimulti_menu_poll();
    var control = mistrimulti_data_dir() + "/control.json";
    if (!file_exists(control)) { n.why = "no control.json"; return; }
    var cfg = try_read_json_file(control);
    if (!is_struct(cfg) || cfg[$ "enabled"] != true || !is_string(cfg[$ "bridge"])) { n.why = "no session is enabled"; return; }
    n.armed = true;
    if (!was_armed) n.armed_at = get_timer();
    n.mode = is_string(cfg[$ "mode"]) ? cfg.mode : "";
    var path = cfg.bridge + "/status.json";
    if (!file_exists(path)) { n.why = "the helper has not written " + path; return; }
    var st = try_read_json_file(path);
    if (!is_struct(st) || st[$ "running"] != true || !is_real(st[$ "heartbeat"])) { n.why = "the helper's status is not valid"; return; }
    if (st.heartbeat != n.hb) { n.hb = st.heartbeat; n.hb_at = get_timer(); }
    n.alive = get_timer() - n.hb_at < 3000000;
    if (!n.alive) n.why = "the helper's heartbeat stopped";
}

// The multiplayer world's own view: the runtime's helper status (r.status, r.mask, r.status_seen_at, kept by MistriMultiBoot.gml)
// or undefined when no multiplayer runtime runs. fresh = the helper's heartbeat moved within the last 3 seconds.
function __mistrimulti_world_link() {
    var r = __mistrimulti_runtime();
    if (r[$ "enabled"] != true || (r[$ "mode"] != "host" && r[$ "mode"] != "join")) return undefined;
    var seen = r[$ "status_seen_at"];
    var fresh = is_struct(r[$ "status"]) && is_real(seen) && get_timer() - seen < 3000000;
    var mask = is_real(r[$ "mask"]) ? r.mask : 0;
    return { mode: r.mode, fresh: fresh, mask: mask, hb: r[$ "status_heartbeat"], has_status: is_struct(r[$ "status"]) };
}

// level: "offline" (red), "idle" (amber), "online" (green). why: the reason of this text, for the log.
function mistrimulti_status_text() {
    var n = __mistrimulti_netstatus();
    var m = __mistrimulti_menu();
    if (!mistrimulti_game_supported()) return { online: false, level: "offline", why: "game version not supported", text: "Multiplayer: Offline - game updated, mod needs an update" };
    var w = __mistrimulti_world_link();
    var mode = (w != undefined) ? w.mode : n.mode;
    var tag = mode == "host" ? " (hosting)" : (mode == "join" ? " (joined)" : "");
    if (w != undefined) {
        // in a multiplayer world: the heartbeat the event layer reads decides, and the peer mask says who is there
        var info = "world " + w.mode + ", heartbeat " + string(w.hb) + ", mask " + string(w.mask);
        if (w.fresh && (w.mode == "host" || (w.mask & 1) != 0)) return { online: true, level: "online", why: info, text: "Multiplayer: Online" + tag };
        if (w.fresh) return { online: false, level: "idle", why: info + ", host not seen yet", text: "Multiplayer: Joining the host..." };
        if (n.armed && n.alive) return { online: true, level: "online", why: info + ", helper status.json alive", text: "Multiplayer: Online" + tag };
        if (!w.has_status) return { online: false, level: "idle", why: info + ", no helper status yet", text: "Multiplayer: Connecting..." };
        return { online: false, level: "offline", why: info + ", heartbeat stopped", text: "Multiplayer: Offline - connection lost" };
    }
    if (n.armed && n.alive) return { online: true, level: "online", why: "helper heartbeat moving", text: "Multiplayer: Online" + tag };
    var st = m.status;
    if (st == undefined && !n.armed) return { online: false, level: "offline", why: "launcher status missing", text: "Multiplayer: Offline - launcher not running (start the game from Steam)" };
    if (st != undefined && !m.alive) return { online: false, level: "offline", why: "launcher status stale", text: "Multiplayer: Offline - launcher stopped" };
    if (st != undefined && !st.helper) return { online: false, level: "offline", why: "launcher reports no helper program", text: "Multiplayer: Offline - helper program missing" };
    // a session was just started: the helper has not written its first heartbeat yet (about the first 10 seconds)
    if (n.armed && n.hb_at < n.armed_at && get_timer() - n.armed_at < 10000000) return { online: false, level: "idle", why: "session starting", text: "Multiplayer: Starting..." };
    if (n.armed) return { online: false, level: "offline", why: "session enabled, helper heartbeat missing", text: "Multiplayer: Offline - helper stopped" };
    return { online: false, level: "idle", why: "launcher ready, no session", text: "Multiplayer: Idle - ready" };
}

function mistrimulti_status_color(level) {
    if (level == "online") return 40 + 200 * 256 + 70 * 65536;
    if (level == "idle") return 20 + 170 * 256 + 230 * 65536;
    return 50 + 60 * 256 + 220 * 65536;
}

// Called every frame from mistrimulti_tick: if ui.draw_gui never fires the badge cannot show, and the log says so.
function mistrimulti_badge_watchdog() {
    var n = __mistrimulti_netstatus();
    n.ticks++;
    if (n.ticks == 900 && n.draws == 0) {
        mmapi_log_error("mistrimulti", "Status badge: the ui.draw_gui hook has not fired after 900 frames, so no badge can be drawn.");
        mmapi_log_flush("mistrimulti");
    }
}

// Called from the ui.draw_gui hook: it only proves the hook fires (the watchdog above). The text itself is an ANCHOR node,
// updated from the tick by mistrimulti_badge_tick.
function mistrimulti_draw_status(resize) {
    __mistrimulti_netstatus().draws++;
}

// Called every tick (60 Hz): re-reads the status about once a second and puts the badge text on screen, bottom right, in the
// level's colour (an ANCHOR text node, see MistriMultiHudText.gml). It shows on the title screen and in multiplayer worlds.
function mistrimulti_badge_tick() {
    var n = __mistrimulti_netstatus();
    n.frames++;
    var on_title = true;
    try { on_title = instance_exists(Setup); } catch (e) {}    // if even this fails, show rather than hide
    var in_world = false;
    try { in_world = __mistrimulti_savespace().active; } catch (e) {}
    if (!on_title && !in_world) { mistrimulti_hudtext_set("badge", "", 0, "popup", "right", "bottom", 0, 0); return; }
    // On the title screen the game draws its copyright line at the bottom right corner: sit above it. In a world nothing else is
    // in the corner. The Popup layer is the one the game's toolbar and menus use, so the badge is not hidden behind them.
    var title = true;
    try { title = !instance_exists(obj_ari); } catch (e) {}
    var status;
    try {
        if (n.frames mod 60 == 1 || n.last_text == "") mistrimulti_netstatus_refresh();
        status = mistrimulti_status_text();
    } catch (e) {
        status = { online: false, level: "offline", why: "status read failed", text: "Multiplayer: Offline - status unavailable" };
        if (!n.warned) { n.warned = true; mmapi_log_error("mistrimulti", "Status badge could not read its status: " + string(e)); }
    }
    if (status.text != n.last_text) {
        n.last_text = status.text;
        mmapi_log_info("mistrimulti", "Badge: " + status.text + " (" + status.why + ") [" + n.why + " | " + __mistrimulti_menu().why + "]");
        mmapi_log_flush("mistrimulti");
    }
    // In a world the badge also names a newer release (on the title screen the Update button next to the version says it).
    var shown_text = title ? status.text : status.text + mistrimulti_update_note();
    var ok = mistrimulti_hudtext_set("badge", shown_text, mistrimulti_status_color(status.level), "popup", "right", "bottom", -6, title ? -16 : -4);
    if (ok && !n.drawn) {
        n.drawn = true;
        mmapi_log_info("mistrimulti", "Status badge: on screen for the first time (ANCHOR text node)");
        mmapi_log_flush("mistrimulti");
    }
}
