// Title-screen version label and "Update" button (docs/SYNC-UPDATE.md is the launcher side; docs/SYNC-MENU.md has the file bridge).
//
// Bottom left of the title screen, right of the game's own "v1.0.8 (modified)" text (TitleMenu.sha_text), the mod shows
// "MistriMulti 0.4.6", always. When the launcher's daily release check found a newer release, an "Update" button sits next to it.
// Clicking it sends the `update` command to the launcher, which runs the update program and relays its progress in
// menu/status.json (fields update, us, uv, um, ue, ur: see mistrimulti_update_fields). The label then shows plain words
// ("Downloading 0.4.7...", "Updated. Close the game and press Install in MOMI", "Installed. Restart the game", or the error).
//
// Nodes: the label is a text node that is a CHILD of the game's version text (Align.RightOut, like the game's own checkbox
// next to its "tools" text), so it sits right after it whatever its width; the button is a nine-slice child of the label with a
// text child. If the game's node cannot be found, a plain text slot (MistriMultiHudText.gml) at a fixed place shows the label
// without a button. Everything is guarded: a failure drops the nodes, logs once and the game goes on.
function mistrimulti_mod_version() { return "0.4.6"; }

// Fixed place of the fallback label (GUI pixels from the left edge), used only when the game's version text node is missing.
function mistrimulti_updateui_fallback_x() { return 112; }

function __mistrimulti_updateui() {
    if (global[$ "__mistrimulti_updateui"] == undefined) {
        global.__mistrimulti_updateui = {
            frames: 0, anchor: undefined, parent: undefined, label: undefined, button: undefined, caption: undefined,
            text: undefined, color: undefined, button_on: undefined, fallback: false, title_since: 0, warned: false,
            pending: false, sent_at: 0, base_run: 0, local_error: "", last_log: "", presses: 0, builds: 0,
        };
    }
    return global.__mistrimulti_updateui;
}

// ---------------------------------------------------------------- versions ("0.4.7": one to four numbers of 1 to 5 digits)

// The numbers of a version text as an array of four reals, or undefined when it is not a version.
function mistrimulti_version_parts(text) {
    if (!is_string(text) || string_length(text) < 1 || string_length(text) > 23) return undefined;
    var parts = [0, 0, 0, 0];
    var group = 0;
    var digits = 0;
    var value = 0;
    for (var i = 1; i <= string_length(text); i++) {
        var c = ord(string_char_at(text, i));
        if (c >= 48 && c <= 57) {
            digits++;
            if (digits > 5) return undefined;
            value = value * 10 + (c - 48);
        } else if (c == 46) {
            if (digits == 0 || group >= 3) return undefined;
            parts[group] = value;
            group++;
            digits = 0;
            value = 0;
        } else return undefined;
    }
    if (digits == 0) return undefined;
    parts[group] = value;
    return parts;
}

function mistrimulti_version_valid(text) { return mistrimulti_version_parts(text) != undefined; }

// true when version a is higher than version b (false if either is not a version).
function mistrimulti_version_newer(a, b) {
    var pa = mistrimulti_version_parts(a);
    var pb = mistrimulti_version_parts(b);
    if (pa == undefined || pb == undefined) return false;
    for (var i = 0; i < 4; i++) {
        if (pa[i] > pb[i]) return true;
        if (pa[i] < pb[i]) return false;
    }
    return false;
}

// ---------------------------------------------------------------- what the launcher says (status.json)

// Printable ASCII only, at most 90 characters; anything else is dropped to "".
function mistrimulti_update_clean_text(text) {
    if (!is_string(text) || string_length(text) > 90) return "";
    for (var i = 1; i <= string_length(text); i++) {
        var c = ord(string_char_at(text, i));
        if (c < 32 || c > 126) return "";
    }
    return text;
}

// The update fields of a status.json as a struct of known-good values. A launcher without them (older, or the check is off) gives
// update "none" and state "none". state: none | checking | downloading | installing | done | failed | needs_momi.
function mistrimulti_update_fields(raw) {
    var u = { latest: "", state: "none", ver: "", msg: "", err: 0, run: 0 };
    if (!is_struct(raw)) return u;
    var latest = raw[$ "update"];
    if (mistrimulti_version_valid(latest)) u.latest = latest;
    var s = raw[$ "us"];
    if (is_string(s) && (s == "checking" || s == "downloading" || s == "installing" || s == "done" || s == "failed" || s == "needs_momi")) u.state = s;
    var ver = raw[$ "uv"];
    if (mistrimulti_version_valid(ver)) u.ver = ver;
    u.msg = mistrimulti_update_clean_text(raw[$ "um"]);
    var err = raw[$ "ue"];
    if (is_real(err) && err >= 0 && err <= 999) u.err = floor(err);
    var run = raw[$ "ur"];
    if (is_real(run) && run >= 0 && run <= 1000000) u.run = floor(run);
    return u;
}

function mistrimulti_update_active(u) {
    return u.state == "checking" || u.state == "downloading" || u.state == "installing";
}

// The newer release the launcher found, or "" (also "" when the launcher is not answering or the release is not newer than this mod).
function mistrimulti_update_available() {
    try {
        var m = __mistrimulti_menu();
        if (m.status == undefined || !m.alive) return "";
        var u = m.status[$ "upd"];
        if (!is_struct(u)) return "";
        if (mistrimulti_version_newer(u.latest, mistrimulti_mod_version())) return u.latest;
    } catch (e) {}
    return "";
}

// " - update available (0.4.7)" for the in-world badge and the F8 note, or "".
function mistrimulti_update_note() {
    var v = mistrimulti_update_available();
    return v == "" ? "" : " - update available (" + v + ")";
}

function mistrimulti_update_error_text(code, msg) {
    if (msg != "") return "Update failed: " + msg;
    switch (code) {
        case 61: return "Update: stop hosting or joining first, then try again";
        case 62: return "Update failed: the update program is missing. Run the installer again";
        case 63: return "Update failed: the update program gave no answer";
        case 66: return "Update failed: it took too long";
    }
    return "Update failed. Try again later (code " + string(code) + ")";
}

function mistrimulti_update_color(kind) {
    if (kind == "good") return 40 + 200 * 256 + 70 * 65536;
    if (kind == "busy") return 20 + 170 * 256 + 230 * 65536;
    if (kind == "bad") return 50 + 60 * 256 + 220 * 65536;
    return 235 + 235 * 256 + 235 * 65536;
}

// What the label and button show now: { text, color, button }.
function mistrimulti_updateui_view() {
    var u = __mistrimulti_updateui();
    var base = { text: "MistriMulti " + mistrimulti_mod_version(), color: mistrimulti_update_color("plain"), button: false };
    var m = __mistrimulti_menu();
    var st = m.status;
    var up = (st != undefined) ? st[$ "upd"] : undefined;
    if (!is_struct(up) || !m.alive) {
        if (u.pending) { base.text = "Starting the update..."; base.color = mistrimulti_update_color("busy"); }
        return base;
    }
    var v = up.ver != "" ? up.ver : up.latest;
    var vtext = v != "" ? " " + v : "";
    // A run the launcher has not started yet (the command is on its way): do not show the answer of an earlier run.
    if (u.pending && up.run <= u.base_run && !mistrimulti_update_active(up)) {
        if (get_timer() - u.sent_at < 10000000) return { text: "Starting the update...", color: mistrimulti_update_color("busy"), button: false };
        u.pending = false;
        u.local_error = "The launcher did not answer. Close the game and start it again from Steam";
    }
    if (u.pending && (up.run > u.base_run || mistrimulti_update_active(up))) { u.pending = false; u.local_error = ""; }
    switch (up.state) {
        case "checking": return { text: "Checking for updates...", color: mistrimulti_update_color("busy"), button: false };
        case "downloading": return { text: "Downloading" + vtext + "...", color: mistrimulti_update_color("busy"), button: false };
        case "installing": return { text: "Installing" + vtext + "...", color: mistrimulti_update_color("busy"), button: false };
        case "done": return { text: "Installed. Restart the game", color: mistrimulti_update_color("good"), button: false };
        case "needs_momi": return { text: "Updated. Close the game and press Install in MOMI", color: mistrimulti_update_color("good"), button: false };
        case "failed":
            return { text: mistrimulti_update_error_text(up.err, up.msg), color: mistrimulti_update_color("bad"), button: mistrimulti_update_available() != "" };
    }
    if (u.local_error != "") return { text: u.local_error, color: mistrimulti_update_color("bad"), button: mistrimulti_update_available() != "" };
    base.button = mistrimulti_update_available() != "";
    return base;
}

// ---------------------------------------------------------------- the click

// The button's tap callback. One command per click; nothing while a run is going or the last command is still unanswered.
function mistrimulti_updateui_press() {
    var u = __mistrimulti_updateui();
    try {
        var m = __mistrimulti_menu();
        if (u.pending || m.status == undefined || !m.alive) return;
        var up = m.status[$ "upd"];
        if (!is_struct(up) || mistrimulti_update_active(up) || mistrimulti_update_available() == "") return;
        u.presses++;
        u.pending = true;
        u.sent_at = get_timer();
        u.base_run = up.run;
        u.local_error = "";
        mistrimulti_menu_send("update", undefined);
        mmapi_log_info("mistrimulti", "Update button pressed: asked the launcher to update to " + up.latest);
        mmapi_log_flush("mistrimulti");
    } catch (e) {
        u.pending = false;
        mmapi_warn_rate_limited("mistrimulti_updateui_press", "mistrimulti", "Update button failed: " + string(e));
    }
}

// ---------------------------------------------------------------- the nodes

function mistrimulti_updateui_node_live(node) {
    return node != undefined && is_struct(node) && node[$ "freed"] != true && node[$ "marked_for_death"] != true;
}

// The game's version text node on the title screen, or undefined.
function mistrimulti_updateui_game_text() {
    try {
        var menu = __mistrimulti_savespace().title_menu;
        if (!is_struct(menu)) return undefined;
        var node = menu[$ "sha_text"];
        if (mistrimulti_updateui_node_live(node)) return node;
    } catch (e) {}
    return undefined;
}

function mistrimulti_updateui_alive(u, parent) {
    return u.anchor == ANCHOR && u.parent == parent && mistrimulti_updateui_node_live(u.label)
        && mistrimulti_updateui_node_live(u.button) && mistrimulti_updateui_node_live(u.caption);
}

function mistrimulti_updateui_drop(u) {
    u.label = undefined;
    u.button = undefined;
    u.caption = undefined;
    u.parent = undefined;
    u.anchor = undefined;
    u.text = undefined;
    u.color = undefined;
    u.button_on = undefined;
}

function mistrimulti_updateui_build(u, parent) {
    u.label = ANCHOR.text(parent).set_align(Align.RightOut, Align.Middle).set_x(6);
    u.button = ANCHOR.nine_slice(u.label).set_sprites_from_key("spr_ui_button").set_size(46, 16).set_align(Align.RightOut, Align.Middle).set_x(6);
    u.button.set_tap_callback(mistrimulti_updateui_press);
    u.caption = ANCHOR.text(u.button).set_align(Align.Center, Align.Middle);
    u.caption.set_text("Update");
    u.button.set_enabled(false);
    u.parent = parent;
    u.anchor = ANCHOR;
    u.text = undefined;
    u.color = undefined;
    u.button_on = false;
    u.builds++;
}

function mistrimulti_updateui_log(u, text) {
    if (u.last_log == text) return;
    u.last_log = text;
    mmapi_log_info("mistrimulti", "Title label: " + text);
    mmapi_log_flush("mistrimulti");
}

// Puts `view` on screen. Called about every 10th frame and whenever the title appears.
function mistrimulti_updateui_apply(u, view) {
    var parent = mistrimulti_updateui_game_text();
    if (parent == undefined) {
        // The game's text is not there (yet, or in this game version): after 5 seconds a plain text slot stands in, without a button.
        if (mistrimulti_updateui_node_live(u.label)) mistrimulti_updateui_drop(u);
        u.title_since += 10;
        if (u.title_since < 300) return;
        u.fallback = true;
        var extra = view.button ? " (update " + mistrimulti_update_available() + " available)" : "";
        mistrimulti_hudtext_set("title_version", view.text + extra, view.color, "popup", "left", "bottom", mistrimulti_updateui_fallback_x(), 0);
        return;
    }
    if (u.fallback) {
        u.fallback = false;
        mistrimulti_hudtext_set("title_version", "", 0, "popup", "left", "bottom", mistrimulti_updateui_fallback_x(), 0);
    }
    u.title_since = 0;
    if (!mistrimulti_updateui_alive(u, parent)) {
        mistrimulti_updateui_drop(u);
        mistrimulti_updateui_build(u, parent);
        mistrimulti_updateui_log(u, "built next to the game's version text (" + string(u.builds) + " in all)");
    }
    if (u.text != view.text) { u.label.set_text(view.text); u.text = view.text; mistrimulti_updateui_log(u, view.text); }
    if (u.color != view.color) { u.label.set_color(view.color); u.color = view.color; }
    if (u.button_on != view.button) { u.button.set_enabled(view.button); u.button_on = view.button; }
}

// Hides everything (not on the title screen).
function mistrimulti_updateui_hide(u) {
    if (u.fallback) {
        u.fallback = false;
        mistrimulti_hudtext_set("title_version", "", 0, "popup", "left", "bottom", mistrimulti_updateui_fallback_x(), 0);
    }
    u.title_since = 0;
    if (mistrimulti_updateui_node_live(u.label) && u.anchor == ANCHOR) {
        if (u.button_on) { u.button.set_enabled(false); u.button_on = false; }
    } else if (u.label != undefined) mistrimulti_updateui_drop(u);
}

// Called every frame from mistrimulti_tick (inside its own guard); works about every 10th frame.
function mistrimulti_updateui_tick() {
    var u = __mistrimulti_updateui();
    u.frames++;
    if (u.frames mod 10 != 3) return;
    try {
        var on_title = true;
        try { on_title = instance_exists(Setup) && !instance_exists(obj_ari); } catch (e) {}
        if (!on_title) { mistrimulti_updateui_hide(u); return; }
        mistrimulti_updateui_apply(u, mistrimulti_updateui_view());
    } catch (e) {
        mistrimulti_updateui_drop(u);
        u.fallback = false;
        if (!u.warned) { u.warned = true; mmapi_log_error("mistrimulti", "Title version label failed (the game goes on): " + string(e)); }
        else mmapi_warn_rate_limited("mistrimulti_updateui", "mistrimulti", "Title version label failed: " + string(e));
    }
}
