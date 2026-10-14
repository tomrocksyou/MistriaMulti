// "Multiplayer: Offline / Idle / Online" badge (bottom right) and the game-version check.
//   Offline = the game was updated past the tested versions, or the MistriMulti launcher / helper is not running
//             (the text says which, in plain words).
//   Idle    = the launcher runs, nothing is hosted or joined: pick Multiplayer in New Game / Load Game.
//   Online  = a host or join session runs and the network helper's heartbeat is moving.
// The launcher's menu/status.json (MistriMultiMenu.gml) is the source for the first two; the helper's own status.json (found
// through control.json, written by the launcher for the session) decides Online. The badge draws on the title screen and in
// multiplayer worlds, and it logs every change of its text with the reason, so a missing or wrong badge can be diagnosed
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
            frames: 0, armed: false, alive: false, hb: -1, hb_at: 0, warned: false, mode: "", last_text: "", why: "",
            draws: 0, ticks: 0, drawn: false,
        };
    }
    return global.__mistrimulti_netstatus;
}

// Reads control.json and the helper's status.json (about once a second; never every frame), and the launcher's menu status.
function mistrimulti_netstatus_refresh() {
    var n = __mistrimulti_netstatus();
    n.armed = false;
    n.alive = false;
    n.mode = "";
    n.why = "";
    mistrimulti_menu_poll();
    var control = mmapi_mod_data_dir("mistrimulti") + "/control.json";
    if (!file_exists(control)) { n.why = "no control.json"; return; }
    var cfg = try_read_json_file(control);
    if (!is_struct(cfg) || cfg[$ "enabled"] != true || !is_string(cfg[$ "bridge"])) { n.why = "no session is enabled"; return; }
    n.armed = true;
    n.mode = is_string(cfg[$ "mode"]) ? cfg.mode : "";
    var path = cfg.bridge + "/status.json";
    if (!file_exists(path)) { n.why = "the helper has not written " + path; return; }
    var st = try_read_json_file(path);
    if (!is_struct(st) || st[$ "running"] != true || !is_real(st[$ "heartbeat"])) { n.why = "the helper's status is not valid"; return; }
    if (st.heartbeat != n.hb) { n.hb = st.heartbeat; n.hb_at = get_timer(); }
    n.alive = get_timer() - n.hb_at < 3000000;
    if (!n.alive) n.why = "the helper's heartbeat stopped";
}

// level: "offline" (red), "idle" (amber), "online" (green)
function mistrimulti_status_text() {
    var n = __mistrimulti_netstatus();
    var m = __mistrimulti_menu();
    if (!mistrimulti_game_supported()) return { online: false, level: "offline", text: "Multiplayer: Offline - game updated, mod needs an update" };
    if (n.armed && n.alive) return { online: true, level: "online", text: "Multiplayer: Online" + (n.mode == "host" ? " (hosting)" : (n.mode == "join" ? " (joined)" : "")) };
    var st = m.status;
    if (st == undefined && !n.armed) return { online: false, level: "offline", text: "Multiplayer: Offline - launcher not running (start the game from Steam)" };
    if (st != undefined && !m.alive) return { online: false, level: "offline", text: "Multiplayer: Offline - launcher stopped" };
    if (st != undefined && !st.helper) return { online: false, level: "offline", text: "Multiplayer: Offline - helper program missing" };
    if (n.armed) return { online: false, level: "offline", text: "Multiplayer: Offline - helper not running" };
    return { online: false, level: "idle", text: "Multiplayer: Idle - choose Multiplayer in New Game" };
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

function mistrimulti_draw_status(resize) {
    var n = __mistrimulti_netstatus();
    n.frames++;
    n.draws++;
    var on_title = true;
    try { on_title = instance_exists(Setup); } catch (e) {}    // if even this fails, draw rather than hide
    var in_world = false;
    try { in_world = __mistrimulti_savespace().active; } catch (e) {}
    if (!on_title && !in_world) return;
    var status;
    try {
        if (n.frames mod 60 == 1) mistrimulti_netstatus_refresh();
        status = mistrimulti_status_text();
    } catch (e) {
        status = { online: false, level: "offline", text: "Multiplayer: Offline - status unavailable" };
        if (!n.warned) { n.warned = true; mmapi_log_error("mistrimulti", "Status badge could not read its status: " + string(e)); }
    }
    if (status.text != n.last_text) {
        n.last_text = status.text;
        mmapi_log_info("mistrimulti", "Badge: " + status.text + " [" + n.why + " | " + __mistrimulti_menu().why + "]");
        mmapi_log_flush("mistrimulti");
    }
    try {
        var scale = is_real(resize) ? resize : 1;
        var gui_w = 480;
        var gui_h = 270;
        try { gui_w = NORMAL_MINSPEC_WIDTH; gui_h = NORMAL_MINSPEC_HEIGHT; } catch (e) {}
        try { draw_set_font(ANCHOR.get_text_font()); } catch (e) {}
        var x = gui_w * scale - string_width(status.text) * scale - 8 * scale;
        var y = gui_h * scale - string_height(status.text) * scale - 6 * scale;
        try { draw_set_color(c_white); } catch (e) {}    // missing in the game's mod runtime: plain text then
        for (var dx = -1; dx <= 1; dx++) for (var dy = -1; dy <= 1; dy++) {
            if (dx != 0 || dy != 0) draw_text_transformed(x + dx * scale, y + dy * scale, status.text, scale, scale, 0);
        }
        try { draw_set_color(mistrimulti_status_color(status.level)); } catch (e) {}    // missing in the game's mod runtime: plain text then
        draw_text_transformed(x, y, status.text, scale, scale, 0);
        try { draw_set_color(c_white); } catch (e) {}    // missing in the game's mod runtime: plain text then
        if (!n.drawn) { n.drawn = true; mmapi_log_info("mistrimulti", "Status badge: drawn for the first time at " + string(x) + "," + string(y) + " scale " + string(scale)); mmapi_log_flush("mistrimulti"); }
    } catch (e) {
        if (!n.warned) { n.warned = true; mmapi_log_error("mistrimulti", "Status badge failed: " + string(e)); }
    }
}
