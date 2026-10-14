// "Multiplayer Online / Offline" badge (bottom right) and the game-version check.
// Online  = this game version has been tested with the mod AND the network helper is running.
// Offline = the game was updated past the tested versions, or the helper is not running.
// Add a version here only after testing the mod against it.
function mistrimulti_supported_versions() { return ["1.0.6"]; }

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
        global.__mistrimulti_netstatus = { frames: 0, armed: false, alive: false, hb: -1, hb_at: 0, warned: false };
    }
    return global.__mistrimulti_netstatus;
}

// Reads control.json and the helper's status.json (about once a second; never every frame).
function mistrimulti_netstatus_refresh() {
    var n = __mistrimulti_netstatus();
    n.armed = false;
    n.alive = false;
    var control = mmapi_mod_data_dir("mistrimulti") + "/control.json";
    if (!file_exists(control)) return;
    var cfg = try_read_json_file(control);
    if (!is_struct(cfg) || cfg[$ "enabled"] != true || !is_string(cfg[$ "bridge"])) return;
    n.armed = true;
    var path = cfg.bridge + "/status.json";
    if (!file_exists(path)) return;
    var st = try_read_json_file(path);
    if (!is_struct(st) || st[$ "running"] != true || !is_real(st[$ "heartbeat"])) return;
    if (st.heartbeat != n.hb) { n.hb = st.heartbeat; n.hb_at = get_timer(); }
    n.alive = get_timer() - n.hb_at < 3000000;
}

function mistrimulti_status_text() {
    var n = __mistrimulti_netstatus();
    if (!mistrimulti_game_supported()) return { online: false, text: "Multiplayer Offline - game updated, mod needs an update" };
    if (!n.armed) return { online: false, text: "Multiplayer Offline - run Play.bat once to set up" };
    if (!n.alive) return { online: false, text: "Multiplayer Offline - helper not running" };
    return { online: true, text: "Multiplayer Online" };
}

function mistrimulti_draw_status(resize) {
    var n = __mistrimulti_netstatus();
    n.frames++;
    var on_title = false;
    try { on_title = instance_exists(Setup); } catch (e) {}
    if (!on_title && !__mistrimulti_savespace().active) return;
    try {
        if (n.frames mod 60 == 1) mistrimulti_netstatus_refresh();
        var status = mistrimulti_status_text();
        var scale = is_real(resize) ? resize : 1;
        draw_set_font(ANCHOR.get_text_font());
        draw_set_alpha(1);
        var x = NORMAL_MINSPEC_WIDTH * scale - string_width(status.text) * scale - 8 * scale;
        var y = NORMAL_MINSPEC_HEIGHT * scale - string_height(status.text) * scale - 6 * scale;
        draw_set_color(c_white);
        for (var dx = -1; dx <= 1; dx++) for (var dy = -1; dy <= 1; dy++) {
            if (dx != 0 || dy != 0) draw_text_transformed(x + dx * scale, y + dy * scale, status.text, scale, scale, 0);
        }
        draw_set_color(status.online ? (40 + 200 * 256 + 70 * 65536) : (50 + 60 * 256 + 220 * 65536));
        draw_text_transformed(x, y, status.text, scale, scale, 0);
        draw_set_color(c_white);
    } catch (e) {
        if (!n.warned) { n.warned = true; mmapi_log_error("mistrimulti", "Status badge failed: " + string(e)); }
    }
}
