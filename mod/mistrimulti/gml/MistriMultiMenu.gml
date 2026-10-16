// In-game Multiplayer menu: "Host a game" / "Join a game" (docs/SYNC-MENU.md).
//
// A mod cannot start programs or open sockets, so the launcher (started by Steam, see the README) does the work. This file only
// shows the choices and talks to the launcher through two small files in <mod data>/menu/, the same file bridge the game and the
// helper already use:
//   cmd.txt      we write "seq=N / cmd=host|join|scan|stop / host= / port= / password= / room=" lines (atomically); the
//                launcher deletes the file when it has read it and answers each new seq once
//   status.json  the launcher writes it about once a second: heartbeat, the last seq it applied, state, err code, this
//                computer's addresses, the hosts its last scan found and, after a join, which world the host plays (hw/hf) and which
//                one was downloaded (dw). We only read it.
//   world.txt    a host's note to its launcher: "id=<Game.unique_identifier>", written once the world is loaded (docs/SYNC-MENU.md,
//                "Which world does a guest get?"). The launcher serves THAT world's newest save and says whether one exists.
// Screens (all of them the game's own popups): [Singleplayer / Multiplayer] -> [Host a game / Join a game]
//   host: [Start hosting / Set a password] -> "starting..." -> addresses to give to friends -> [Start playing]
//   join: "looking for hosts..." -> [host list / Type an address / Refresh] -> (password, room code) -> "connecting...",
//         "downloading the world..." -> the world opens.  Every failure is shown in plain words with a way back.
// Nothing here runs in singleplayer. Every failure of the popups themselves is caught: the game continues, the cause is logged.
function __mistrimulti_menu() {
    if (global[$ "__mistrimulti_menu"] == undefined) {
        global.__mistrimulti_menu = {
            frames: 0, seq: 0, status: undefined, hb: -1, hb_at: 0, alive: false, why: "", logged_why: "",
            texts: {}, text_n: 0, flow: undefined, warned: false, outbox: [],
            published: "", publish_at: 0, save_tried: false, save_next: 0, save_since: 0, save_told: false,
        };
    }
    return global.__mistrimulti_menu;
}

// ---------------------------------------------------------------- the launcher's status file

function mistrimulti_menu_dir() { return mistrimulti_data_dir() + "/menu"; }

function mistrimulti_menu_valid_ip(text) {
    if (!is_string(text) || string_length(text) < 7 || string_length(text) > 15) return false;
    var parts = 1;
    var digits = 0;
    var value = 0;
    for (var i = 1; i <= string_length(text); i++) {
        var c = ord(string_char_at(text, i));
        if (c == 46) {
            if (digits == 0) return false;
            parts++;
            digits = 0;
            value = 0;
        } else if (c >= 48 && c <= 57) {
            digits++;
            value = value * 10 + (c - 48);
            if (digits > 3 || value > 255) return false;
        } else return false;
    }
    return parts == 4 && digits > 0;
}

function mistrimulti_menu_valid_room(text) {
    if (!is_string(text) || string_length(text) != 8) return false;
    for (var i = 1; i <= 8; i++) {
        var c = ord(string_lower(string_char_at(text, i)));
        if (!((c >= 48 && c <= 57) || (c >= 97 && c <= 102))) return false;
    }
    return true;
}

// A password is 1 to 64 printable ASCII characters without spaces (the same rule as the launcher and the helper).
function mistrimulti_menu_valid_password(text) {
    if (!is_string(text) || string_length(text) < 1 || string_length(text) > 64) return false;
    for (var i = 1; i <= string_length(text); i++) {
        var c = ord(string_char_at(text, i));
        if (c < 33 || c > 126) return false;
    }
    return true;
}

// Copies a status.json into a struct of known-good fields, or returns undefined. The file is local but nothing is trusted.
function mistrimulti_menu_clean(raw) {
    if (!is_struct(raw) || raw[$ "v"] != 1) return undefined;
    if (!is_real(raw[$ "hb"]) || !is_real(raw[$ "seq"]) || !is_string(raw[$ "state"]) || !is_real(raw[$ "err"])) return undefined;
    var st = {
        hb: raw.hb, seq: raw.seq, state: raw.state, err: raw.err, session: "none", helper: raw[$ "helper"] == 1,
        scan: is_real(raw[$ "scan"]) ? raw.scan : 0, port: is_real(raw[$ "port"]) ? raw.port : 7777, addrs: [], hosts: [],
        hw: is_real(raw[$ "hw"]) ? floor(raw.hw) : 0, hf: is_real(raw[$ "hf"]) ? floor(raw.hf) : 0, dw: is_real(raw[$ "dw"]) ? floor(raw.dw) : 0,
    };
    if (is_string(raw[$ "session"])) st.session = raw.session;
    if (is_array(raw[$ "addrs"])) {
        for (var i = 0; i < array_length(raw.addrs) && i < 8; i++) {
            if (mistrimulti_menu_valid_ip(raw.addrs[i])) array_push(st.addrs, raw.addrs[i]);
        }
    }
    if (is_array(raw[$ "hosts"])) {
        for (var j = 0; j < array_length(raw.hosts) && j < 12; j++) {
            var h = raw.hosts[j];
            if (!is_struct(h) || !mistrimulti_menu_valid_ip(h[$ "ip"]) || !is_real(h[$ "port"]) || !is_real(h[$ "flags"])) continue;
            if (h.port < 1 || h.port > 65535) continue;
            var name = is_string(h[$ "name"]) ? h.name : "";
            if (string_length(name) > 31) name = string_copy(name, 1, 31);
            array_push(st.hosts, { ip: h.ip, port: floor(h.port), flags: floor(h.flags), name: name });
        }
    }
    return st;
}

// Reads status.json (the caller decides how often). Keeps the last good status when one read fails: on Windows a file that is
// being replaced can be unreadable for a moment. m.alive: the launcher's heartbeat moved lately (it can be busy for a while
// scanning or downloading, so those states are given more time).
function mistrimulti_menu_poll() {
    var m = __mistrimulti_menu();
    var path = mistrimulti_menu_dir() + "/status.json";
    if (!file_exists(path)) {
        m.status = undefined;
        m.alive = false;
        m.why = "the launcher's status file does not exist (" + path + "): the game was not started through the MistriaMulti launcher";
        return;
    }
    var st = mistrimulti_menu_clean(try_read_json_file(path));
    if (st == undefined) {
        if (m.status == undefined) m.why = "the launcher's status file cannot be read (" + path + ")";
        return;
    }
    if (st.hb != m.hb) { m.hb = st.hb; m.hb_at = get_timer(); }
    m.status = st;
    var busy = st.state == "scanning" || st.state == "downloading";
    m.alive = st.state != "stopped" && get_timer() - m.hb_at < (busy ? 40000000 : 4000000);
    m.why = m.alive ? "" : (st.state == "stopped" ? "the launcher has ended" : "the launcher's heartbeat stopped");
}

// Queues a command for the launcher and returns its sequence number. fields: struct of strings (already validated).
// Commands go out one at a time, in order: a new cmd.txt is written only after the launcher has consumed (deleted) the last one,
// so a "stop" right after a "join" cannot replace it (and a rename onto an existing file is never needed).
function mistrimulti_menu_send(cmd, fields) {
    var m = __mistrimulti_menu();
    // The first number is spread by the clock, so a command can never look like one the launcher already answered.
    if (m.seq == 0) m.seq = floor(get_timer() / 1000000) mod 90000 + 1;
    m.seq++;
    var text = "seq=" + string(m.seq) + "\ncmd=" + cmd + "\n";
    if (is_struct(fields)) {
        var names = struct_get_names(fields);
        for (var i = 0; i < array_length(names); i++) text += names[i] + "=" + string(fields[$ names[i]]) + "\n";
    }
    array_push(m.outbox, text);
    mistrimulti_menu_flush();
    return m.seq;
}

// Writes the oldest queued command if the launcher has taken the previous one. A write that fails is dropped and logged.
function mistrimulti_menu_flush() {
    var m = __mistrimulti_menu();
    if (array_length(m.outbox) == 0) return;
    var dir = mistrimulti_menu_dir();
    if (file_exists(dir + "/cmd.txt")) return;
    var text = m.outbox[0];
    array_delete(m.outbox, 0, 1);
    try {
        save_text_file(dir + "/cmd.tmp", text);
        file_rename(dir + "/cmd.tmp", dir + "/cmd.txt");
    } catch (e) {
        mmapi_log_error("mistrimulti", "Menu: could not write a command for the launcher: " + string(e));
        throw e;
    }
}

// ---------------------------------------------------------------- words

function mistrimulti_menu_error_text(code) {
    switch (code) {
        case 1: return "The MistriaMulti network helper program is missing. Run the MistriaMulti installer again.";
        case 2: return "The network helper could not start. Another program (or a second copy of the game) may be using the multiplayer port. Close it and try again. Details: helper.log in the MistriaMulti data folder.";
        case 3: return "That address or setting is not valid. An address looks like 100.101.102.103.";
        case 4: return "The host did not answer. Check the address, that the host is playing and chose Host a game, and that you are on the same network or on Tailscale. If your host uses a room code, ask for it.";
        case 5: return "That password cannot be used. It must be 1 to 64 letters, digits or punctuation marks, without spaces.";
        case 6: return "MistriaMulti could not write its settings file.";
        case 7: return "Searching for hosts is not available on this computer. Choose Type an address instead.";
        case 21: return "Wrong password. Ask your host for the password and try again.";
        case 22: return "The host has blocked this computer.";
        case 23: return "That player slot is already in use on the host. Try again.";
        case 24: return "The host's game is full.";
        case 26: return "This host needs a password. Type it in.";
        case 41: return "Could not reach the host's world download. The host's firewall may block port 7775.";
        case 42: return "The host has no saved world yet. Ask the host to sleep in bed once (this saves the game), then try again.";
        case 43: return "The host sent a world that could not be understood. Try again.";
        case 44: return "The downloaded world was damaged on the way. Try again.";
        case 45: return "The downloaded world could not be saved on this computer. The disk may be full.";
        case 46: return "There is not enough memory to download the world.";
        case 47: return "The host refused to send the world. Join again; if it keeps happening, both players should update MistriaMulti.";
        case 48: return "The host has started a new world but has not saved it yet. Ask them to sleep or save once, then press Join again.";
        case 49: return "The host is playing a different world than the one that was downloaded (it started another world meanwhile). Press Try again to download the host's world again.";
    }
    return "Something went wrong (code " + string(code) + "). Try again.";
}

// Why Multiplayer is not available right now, in plain words, or "" when the launcher answers and its helper exists.
function mistrimulti_menu_unavailable() {
    var m = __mistrimulti_menu();
    if (m.status == undefined) return "MistriaMulti is not running. Start the game from Steam with the MistriaMulti launch option (the installer sets it; see the README).";
    if (!m.alive) return "The MistriaMulti launcher stopped answering. Close the game and start it again from Steam.";
    if (!m.status.helper) return mistrimulti_menu_error_text(1);
    return "";
}

// Text for the game's popups. The game looks keys up with local_get, so every text gets its own key ("mistrimulti/t/N") and
// mistrimulti_local_missing hands it back; a popup that is already on screen can never change when a later text is made.
function mistrimulti_menu_t(text) {
    var m = __mistrimulti_menu();
    m.text_n++;
    var key = "mistrimulti/t/" + string(m.text_n);
    m.texts[$ key] = text;
    if (m.text_n > 80) struct_remove(m.texts, "mistrimulti/t/" + string(m.text_n - 80));
    return key;
}

function mistrimulti_menu_text_for_key(key) {
    var m = __mistrimulti_menu();
    return m.texts[$ key];
}

// ---------------------------------------------------------------- the flow

function mistrimulti_menu_log(text) {
    try { mmapi_log_info("mistrimulti", "Menu: " + text); mmapi_log_flush("mistrimulti"); } catch (e) {}
}

function mistrimulti_menu_close_popup(popup) {
    if (popup == undefined || popup[$ "close_requested"] == true) return;     // already closing (Escape): the game closes a popup once
    try { popup.close(); } catch (e) { mmapi_log_error("mistrimulti", "Menu: closing a popup failed: " + string(e)); }
}

// Is the flow really on screen (or about to be)? A flow whose popup the game closed by itself, with nothing coming, is a dead one.
function mistrimulti_menu_flow_alive() {
    var f = __mistrimulti_menu().flow;
    if (f == undefined) return false;
    if (f.next != "" || f.pause > 0 || f.stage == "input") return true;     // a closed text box is handled by the tick (back to the list)
    if (f.popup != undefined && f.popup[$ "close_requested"] != true) return true;
    if (f.input != undefined && f.input[$ "close_requested"] != true) return true;
    return false;
}

// Closes whatever is on screen and drops the flow. stop: also tell the launcher to stop hosting / joining.
function mistrimulti_menu_reset(stop) {
    var m = __mistrimulti_menu();
    var f = m.flow;
    m.flow = undefined;
    __mistrimulti_savespace().choosing = false;
    if (f != undefined) {
        mistrimulti_menu_close_popup(f.popup);
        mistrimulti_menu_close_popup(f.input);
    }
    if (stop) {
        try { mistrimulti_menu_send("stop", undefined); } catch (e) { mmapi_log_error("mistrimulti", "Menu: stop command failed: " + string(e)); }
    }
}

// Starts the flow once the player chose Multiplayer. kind: "new" or "load" (what the player was doing), arg: the game's own
// argument for it (the new-game state).
function mistrimulti_menu_begin(kind, arg) {
    var m = __mistrimulti_menu();
    if (m.flow != undefined) mistrimulti_menu_reset(true);      // a flow that was left behind: close its popups, stop its session
    mistrimulti_menu_poll();
    var why = mistrimulti_menu_unavailable();
    if (why != "") {
        mistrimulti_menu_log("Multiplayer unavailable: " + why + " [" + m.why + "]");
        mistrimulti_savespace_popup(mistrimulti_menu_t("Multiplayer is offline"), mistrimulti_menu_t(why));
        return;
    }
    m.flow = {
        kind: kind, arg: arg, role: "", stage: "", next: "", next_arg: "", pause: 0, since: get_timer(), seq: 0, popup: undefined,
        input: undefined, input_kind: "", input_got: false, input_closed: 0, hosts: [], pass: "", room: "", ip: "", port: 7777,
        scan_before: 0, wait_text: "", err: 0, note: "", idle: 0,
    };
    __mistrimulti_savespace().choosing = true;
    mistrimulti_menu_ui("choose");
}

// Shows the screen "name" now. Every builder is guarded: a failure resets the flow and the game goes on.
function mistrimulti_menu_ui(name) {
    var m = __mistrimulti_menu();
    var f = m.flow;
    if (f == undefined) return;
    f.next = "";
    try {
        switch (name) {
            case "choose": mistrimulti_menu_ui_choose(); break;
            case "host": mistrimulti_menu_ui_host(); break;
            case "wait": mistrimulti_menu_ui_wait(); break;
            case "hosting": mistrimulti_menu_ui_hosting(); break;
            case "list": mistrimulti_menu_ui_list(); break;
            case "error": mistrimulti_menu_ui_error(); break;
            case "input": mistrimulti_menu_ui_input(); break;
            case "play": mistrimulti_menu_play(); break;
        }
    } catch (e) {
        mmapi_log_error("mistrimulti", "Menu screen " + name + " failed: " + string(e));
        mistrimulti_menu_reset(true);
    }
}

// Shows a screen after the previous popup had time to close (its closing animation must finish first).
function mistrimulti_menu_show_later(name, close_old) {
    var f = __mistrimulti_menu().flow;
    if (f == undefined) return;
    if (close_old && f.popup != undefined) { mistrimulti_menu_close_popup(f.popup); f.popup = undefined; }
    f.next = name;
    f.pause = 12;
}

function mistrimulti_menu_ui_choose() {
    var f = __mistrimulti_menu().flow;
    f.stage = "choose";
    var mcp = new MultipleChoicePopup(mistrimulti_menu_t("Multiplayer"));
    f.popup = mcp.popup;
    mcp.option(mistrimulti_menu_t("Host a game"), mistrimulti_menu_pick, ["host"]);
    mcp.option(mistrimulti_menu_t("Join a game"), mistrimulti_menu_pick, ["join"]);
    mcp.option(mistrimulti_menu_t("Cancel"), mistrimulti_menu_cancel, []);
}

function mistrimulti_menu_ui_host() {
    var f = __mistrimulti_menu().flow;
    f.stage = "host";
    var mcp = new MultipleChoicePopup(mistrimulti_menu_t("Host a game"));
    f.popup = mcp.popup;
    mcp.option(mistrimulti_menu_t("Start hosting"), mistrimulti_menu_host_go, []);
    mcp.option(mistrimulti_menu_t(f.pass == "" ? "Set a password (optional)" : "Change the password"), mistrimulti_menu_ask, ["host_pass"]);
    mcp.option(mistrimulti_menu_t("Back"), mistrimulti_menu_back, []);
    mistrimulti_widen_choices(mcp);
}

function mistrimulti_menu_ui_wait() {
    var f = __mistrimulti_menu().flow;
    var popup = popup_creator(mistrimulti_menu_t("Multiplayer"), mistrimulti_menu_t(f.wait_text));
    popup.create_button(mistrimulti_menu_t("Cancel"), mistrimulti_menu_cancel, []);
    f.popup = popup.spawn();
}

function mistrimulti_menu_address_lines(st) {
    var text = "";
    for (var i = 0; i < array_length(st.addrs); i++) {
        var a = st.addrs[i];
        var kind = "This network";
            if (string_copy(a, 1, 4) == "100.") kind = "Tailscale";
        text += (i > 0 ? "\n" : "") + kind + ": " + a;
    }
    if (text == "") text = "(no network address found - is this computer online?)";
    return text;
}

function mistrimulti_menu_ui_hosting() {
    var m = __mistrimulti_menu();
    var f = m.flow;
    f.stage = "hosting";
    var body = "Give one of these addresses to your friends:\n" + mistrimulti_menu_address_lines(m.status)
        + "\nThey choose Join a game. Your world is shared as of your last save.";
    var popup = popup_creator(mistrimulti_menu_t("You are hosting"), mistrimulti_menu_t(body));
    popup.create_button(mistrimulti_menu_t("Stop hosting"), mistrimulti_menu_cancel, []);
    popup.create_button(mistrimulti_menu_t("Start playing"), mistrimulti_menu_play, []);
    f.popup = popup.spawn();
}

function mistrimulti_menu_host_label(h) {
    var text = h.name == "" ? h.ip : (h.name + "  " + h.ip);
    if ((h.flags & 2) != 0) text += "  [password]";
    if ((h.flags & 4) != 0 && (h.flags & 8) == 0) text += "  [new world, not saved]";     // the host named the world it plays; nothing is saved for it
    return text;
}

function mistrimulti_menu_ui_list() {
    var m = __mistrimulti_menu();
    var f = m.flow;
    f.stage = "list";
    var title = array_length(f.hosts) > 0 ? "Join a game: pick a host" : "Join a game: no host found";
    if (f.note != "") title = f.note;
    var mcp = new MultipleChoicePopup(mistrimulti_menu_t(title));
    f.popup = mcp.popup;
    for (var i = 0; i < array_length(f.hosts) && i < 4; i++) {
        mcp.option(mistrimulti_menu_t(mistrimulti_menu_host_label(f.hosts[i])), mistrimulti_menu_pick_host, [i]);
    }
    mcp.option(mistrimulti_menu_t("Type an address"), mistrimulti_menu_ask, ["ip"]);
    mcp.option(mistrimulti_menu_t("Refresh"), mistrimulti_menu_scan, []);
    mcp.option(mistrimulti_menu_t("Cancel"), mistrimulti_menu_cancel, []);
    mistrimulti_widen_choices(mcp);
}

function mistrimulti_menu_ui_error() {
    var f = __mistrimulti_menu().flow;
    f.stage = "error";
    var popup = popup_creator(mistrimulti_menu_t("Multiplayer"), mistrimulti_menu_t(mistrimulti_menu_error_text(f.err)));
    popup.create_button(mistrimulti_menu_t("Close"), mistrimulti_menu_cancel, []);
    popup.create_button(mistrimulti_menu_t("Try again"), mistrimulti_menu_retry, []);
    f.popup = popup.spawn();
}

// Text entry with the game's own text box. kind: "ip", "password", "room", "host_pass".
function mistrimulti_menu_ui_input() {
    var f = __mistrimulti_menu().flow;
    var kind = f.input_kind;
    f.stage = "input";
    f.input_got = false;
    f.input_closed = 0;
    var title = "Type the host's address (like 100.101.102.103)";
    if (kind == "password") title = "Type the host's password";
    if (kind == "host_pass") title = "Choose a password for your game (1 to 64 characters, no spaces)";
    if (kind == "room") title = "Type the room code (8 letters or digits)";
    f.input = text_input_popup(mistrimulti_menu_t(title), "", 110, mistrimulti_menu_input_done, [kind]);
}

// ---- button callbacks (each one is wrapped: a failure never reaches the game)
// The game closes a popup before it runs the callback of its button, so the popup must not be closed a second time.
function mistrimulti_menu_popup_gone() {
    var f = __mistrimulti_menu().flow;
    if (f != undefined) f.popup = undefined;
    return f;
}

function mistrimulti_menu_pick(role) {
    try {
        var f = mistrimulti_menu_popup_gone();
        if (f == undefined) return;
        f.role = role;
        if (role == "host") mistrimulti_menu_show_later("host", false);
        else mistrimulti_menu_scan();
    } catch (e) { mmapi_log_error("mistrimulti", "Menu pick failed: " + string(e)); mistrimulti_menu_reset(true); }
}

function mistrimulti_menu_back() {
    try {
        if (mistrimulti_menu_popup_gone() == undefined) return;
        mistrimulti_menu_show_later("choose", false);
    } catch (e) { mistrimulti_menu_reset(true); }
}

// Does the launcher have (or is it starting) a session that a cancel must end? A screen that only chooses never started one; the
// status file is asked as well, so a session that is running for any other reason is stopped too.
function mistrimulti_menu_session_running(f) {
    var m = __mistrimulti_menu();
    if (f != undefined && f.stage != "choose" && f.stage != "host" && f.stage != "list" && f.stage != "input") return true;
    var st = m.status;
    if (st == undefined) return false;
    return st.session != "none" || st.state == "hosting" || st.state == "joining" || st.state == "downloading" || st.state == "ready";
}

// Every way out of the flow (Cancel, Close, Escape, a click outside the popup, the title screen coming back) ends here: nothing of the
// flow stays behind (popups, text box, choosing flag), and a session that was started is stopped.
function mistrimulti_menu_cancel() {
    var stop = true;
    try {
        var f = mistrimulti_menu_popup_gone();
        stop = mistrimulti_menu_session_running(f);
    } catch (e) { mmapi_log_error("mistrimulti", "Menu cancel failed: " + string(e)); }
    mistrimulti_menu_reset(stop);
}

function mistrimulti_menu_ask(kind) {
    try {
        var f = mistrimulti_menu_popup_gone();
        if (f == undefined) return;
        f.input_kind = kind;
        mistrimulti_menu_show_later("input", false);
    } catch (e) { mistrimulti_menu_reset(true); }
}

function mistrimulti_menu_wait(text, stage) {
    var f = __mistrimulti_menu().flow;
    f.wait_text = text;
    f.stage = stage;
    f.since = get_timer();
    mistrimulti_menu_show_later("wait", true);
    f.stage = stage;
}

function mistrimulti_menu_host_go() {
    try {
        var f = mistrimulti_menu_popup_gone();
        if (f == undefined) return;
        var fields = {};
        if (f.pass != "") fields.password = f.pass;
        f.seq = mistrimulti_menu_send("host", fields);
        mistrimulti_menu_wait("Starting your game for friends...", "wait_host");
    } catch (e) { mmapi_log_error("mistrimulti", "Menu host failed: " + string(e)); mistrimulti_menu_reset(true); }
}

function mistrimulti_menu_scan() {
    try {
        var m = __mistrimulti_menu();
        var f = mistrimulti_menu_popup_gone();
        if (f == undefined) return;
        f.scan_before = m.status == undefined ? 0 : m.status.scan;
        f.seq = mistrimulti_menu_send("scan", undefined);
        mistrimulti_menu_wait("Looking for hosts on your network and on Tailscale...", "wait_scan");
    } catch (e) { mmapi_log_error("mistrimulti", "Menu scan failed: " + string(e)); mistrimulti_menu_reset(true); }
}

function mistrimulti_menu_join(ip, port) {
    var f = __mistrimulti_menu().flow;
    f.ip = ip;
    f.port = port;
    var fields = { host: ip, port: string(port) };
    if (f.pass != "") fields.password = f.pass;
    if (f.room != "") fields.room = f.room;
    f.seq = mistrimulti_menu_send("join", fields);
    mistrimulti_menu_wait("Connecting to " + ip + "...", "wait_join");
}

function mistrimulti_menu_pick_host(index) {
    try {
        var f = mistrimulti_menu_popup_gone();
        if (f == undefined || index < 0 || index >= array_length(f.hosts)) return;
        var h = f.hosts[index];
        f.ip = h.ip;
        f.port = h.port;
        f.pass = "";
        f.room = "";
        if ((h.flags & 1) != 0) mistrimulti_menu_ask("room");
        else if ((h.flags & 2) != 0) mistrimulti_menu_ask("password");
        else mistrimulti_menu_join(h.ip, h.port);
    } catch (e) { mmapi_log_error("mistrimulti", "Menu host pick failed: " + string(e)); mistrimulti_menu_reset(true); }
}

// The text box was confirmed. kind says which question it answered.
function mistrimulti_menu_input_done(text, kind) {
    try {
        var f = __mistrimulti_menu().flow;
        if (f == undefined) return;
        f.input_got = true;
        f.input = undefined;
        if (kind == "ip" || kind == "room") text = string_replace_all(text, " ", "");     // a password is taken exactly as typed
        if (kind == "ip") {
            if (!mistrimulti_menu_valid_ip(text)) { f.err = 3; mistrimulti_menu_show_later("error", false); return; }
            f.ip = text;
            f.port = 7777;
            f.pass = "";
            f.room = "";
            mistrimulti_menu_join(text, 7777);
        } else if (kind == "password") {
            if (!mistrimulti_menu_valid_password(text)) { f.err = 5; mistrimulti_menu_show_later("error", false); return; }
            f.pass = text;
            mistrimulti_menu_join(f.ip, f.port);
        } else if (kind == "room") {
            if (!mistrimulti_menu_valid_room(text)) { f.err = 3; mistrimulti_menu_show_later("error", false); return; }
            f.room = string_lower(text);
            var host_needs_password = false;
            for (var i = 0; i < array_length(f.hosts); i++) if (f.hosts[i].ip == f.ip && (f.hosts[i].flags & 2) != 0) host_needs_password = true;
            if (host_needs_password) mistrimulti_menu_ask("password");
            else mistrimulti_menu_join(f.ip, f.port);
        } else if (kind == "host_pass") {
            if (!mistrimulti_menu_valid_password(text)) { f.err = 5; mistrimulti_menu_show_later("error", false); return; }
            f.pass = text;
            mistrimulti_menu_show_later("host", false);
        }
    } catch (e) { mmapi_log_error("mistrimulti", "Menu input failed: " + string(e)); mistrimulti_menu_reset(true); }
}

// "Try again" on the error screen: back to the screen that fits the failure.
function mistrimulti_menu_retry() {
    try {
        var f = mistrimulti_menu_popup_gone();
        if (f == undefined) return;
        if (f.err == 26 || f.err == 21) { f.input_kind = "password"; mistrimulti_menu_show_later("input", false); return; }
        if ((f.err == 48 || f.err == 49) && f.role == "join" && mistrimulti_menu_valid_ip(f.ip)) { mistrimulti_menu_join(f.ip, f.port); return; }   // press Join again
        if (f.role == "host") { mistrimulti_menu_show_later("host", false); return; }
        if (f.err == 3 || f.err == 5) { f.input_kind = f.input_kind == "" ? "ip" : f.input_kind; mistrimulti_menu_show_later("input", false); return; }
        mistrimulti_menu_scan();
    } catch (e) { mistrimulti_menu_reset(true); }
}

// "Start playing": the launcher already hosts (or the world was downloaded); enter the multiplayer world.
function mistrimulti_menu_play() {
    try {
        var m = __mistrimulti_menu();
        var f = mistrimulti_menu_popup_gone();
        if (f == undefined) return;
        var kind = f.kind;
        var arg = f.arg;
        m.flow = undefined;
        __mistrimulti_savespace().choosing = false;
        mistrimulti_savespace_enter(kind, arg);
    } catch (e) {
        mmapi_log_error("mistrimulti", "Starting the multiplayer world failed: " + string(e));
        mistrimulti_menu_reset(true);
    }
}

// ---------------------------------------------------------------- per-frame work

function mistrimulti_menu_fail(code) {
    var f = __mistrimulti_menu().flow;
    f.err = code;
    mistrimulti_menu_show_later("error", true);
    f.stage = "error_pending";
}

// Called every frame (cheap). Polls the launcher's status and moves the flow along.
function mistrimulti_menu_tick() {
    var m = __mistrimulti_menu();
    m.frames++;
    var f = m.flow;
    if (array_length(m.outbox) > 0) {
        try { mistrimulti_menu_flush(); }
        catch (e) { mmapi_log_error("mistrimulti", "Menu: a command could not be sent: " + string(e)); }
    }
    if (m.frames mod (f == undefined ? 60 : 10) == 1) mistrimulti_menu_poll();
    try { mistrimulti_menu_world_tick(); }
    catch (e) { mmapi_warn_rate_limited("mistrimulti_menu_world", "mistrimulti", "World note / early save failed: " + string(e)); }
    if (f == undefined) return;
    try {
        if (f.pause > 0) { f.pause--; return; }
        if (f.next != "") { mistrimulti_menu_ui(f.next); return; }
        var now = get_timer();
        // A popup the game closed by itself (Escape, a click outside it) never calls a button: that is a Cancel.
        if (f.stage != "input" && f.popup != undefined && f.popup[$ "close_requested"] == true) {
            mistrimulti_menu_log("a popup was dismissed on screen " + f.stage + ": cancelled");
            mistrimulti_menu_cancel();
            return;
        }
        // Nothing on screen, nothing coming, and still a flow for 3 seconds: something went wrong. Never leave the player stuck.
        if (f.popup == undefined && f.input == undefined) {
            f.idle++;
            if (f.idle > 180) { mistrimulti_menu_log("the flow had nothing on screen (" + f.stage + "): reset"); mistrimulti_menu_reset(true); return; }
        } else f.idle = 0;
        // The player closed the text box without confirming: back to where he was.
        if (f.stage == "input" && !f.input_got && f.input != undefined && f.input[$ "close_requested"] == true) {
            f.input_closed++;
            if (f.input_closed > 20) {
                f.input = undefined;
                mistrimulti_menu_show_later(f.role == "host" ? "host" : "list", false);
            }
            return;
        }
        // Waiting screens
        if (f.stage != "wait_host" && f.stage != "wait_scan" && f.stage != "wait_join") return;
        var st = m.status;
        if (st == undefined || !m.alive) {
            if (now - f.since > 6000000) { mistrimulti_menu_log("launcher gone: " + m.why); mistrimulti_menu_fail(4); }
            return;
        }
        if (st.seq != f.seq) {
            if (now - f.since > 8000000) { mistrimulti_menu_log("launcher did not answer command " + string(f.seq)); mistrimulti_menu_fail(4); }
            return;
        }
        if (f.stage == "wait_host") {
            if (st.state == "hosting") { f.stage = "hosting"; mistrimulti_menu_show_later("hosting", true); }
            else if (st.state == "error") mistrimulti_menu_fail(st.err);
        } else if (f.stage == "wait_scan") {
            if (st.state == "scanning") return;
            if (st.scan > f.scan_before || st.state == "error") {
                f.hosts = st.hosts;
                f.note = st.err == 7 ? "Searching is not available here: type an address" : "";
                f.stage = "list_pending";
                if (st.state == "error" && st.err != 7) { mistrimulti_menu_fail(st.err); return; }
                mistrimulti_menu_show_later("list", true);
            }
        } else if (f.stage == "wait_join") {
            if (st.state == "downloading" && f.wait_text != "Downloading the host's world...") {
                f.wait_text = "Downloading the host's world...";
                mistrimulti_menu_show_later("wait", true);
                f.stage = "wait_join";
            } else if (st.state == "ready") {
                // The world that arrived must be the world the host plays now (both are game ids; 0 = not told: an older launcher or host).
                if (st.hw != 0 && st.dw != 0 && st.hw != st.dw) {
                    mistrimulti_menu_log("joined " + f.ip + " but the host plays world " + string(st.hw) + " and world " + string(st.dw) + " arrived");
                    try { mistrimulti_menu_send("stop", undefined); } catch (e) { mmapi_log_error("mistrimulti", "Menu: stop failed: " + string(e)); }
                    mistrimulti_menu_fail(49);
                    return;
                }
                mistrimulti_menu_log("joined " + f.ip + ", world downloaded (host world " + string(st.hw) + ", downloaded " + string(st.dw) + ")");
                mistrimulti_menu_close_popup(f.popup);
                f.popup = undefined;
                f.stage = "entering";
                f.pause = 12;
                f.next = "play";
            } else if (st.state == "error") {
                if (st.err == 26 || st.err == 21) f.input_kind = "password";
                mistrimulti_menu_fail(st.err);
            } else if (now - f.since > 90000000) {
                mistrimulti_menu_fail(4);
            }
        }
    } catch (e) {
        mmapi_log_error("mistrimulti", "Menu tick failed: " + string(e));
        mistrimulti_menu_reset(true);
    }
}

// The title screen is back (or the game started): a session that is still running is stopped, so nobody stays connected.
function mistrimulti_menu_title_entered() {
    var m = __mistrimulti_menu();
    m.published = "";                       // the launcher deletes the note when the session stops; the next world publishes its own
    m.save_tried = false;
    m.save_since = 0;
    m.save_told = false;
    if (m.flow != undefined) mistrimulti_menu_reset(false);
    mistrimulti_menu_poll();
    if (m.status != undefined && m.alive && m.status.session != "none") {
        try { mistrimulti_menu_send("stop", undefined); } catch (e) { mmapi_log_error("mistrimulti", "Menu: stop failed: " + string(e)); }
    }
}

// ---------------------------------------------------------------- which world is the host playing? (docs/SYNC-MENU.md)

// "<digits>" of a world key ("<identity>_<Game.unique_identifier>"): what follows the last underscore, or "".
function mistrimulti_world_key_id(key) {
    if (!is_string(key)) return "";
    for (var i = string_length(key); i >= 1; i--) {
        if (string_char_at(key, i) == "_") return string_copy(key, i + 1, string_length(key) - i);
    }
    return "";
}

// Every tick. Host: tell the launcher which world is being played (once per world), and save a NEW world early so guests can join it.
// Guest: note whether the host plays another world than the one this game loaded (r.world_mismatch; MistriMultiGuestSave.gml and
// MistriMultiPlayerSync.gml act on it).
function mistrimulti_menu_world_tick() {
    var r = __mistrimulti_runtime();
    var m = __mistrimulti_menu();
    if (r.enabled != true) { r.world_mismatch = false; return; }
    if (r.mode == "join") { mistrimulti_menu_guest_world_check(r); return; }
    if (r.mode != "host" || r[$ "player_ready"] != true || !is_string(r[$ "world_key"]) || r.world_key == "") return;
    var id = Game.unique_identifier;
    if (!is_real(id) || id < 1 || id > 2147483647) return;
    var key = string(floor(id));
    if (m.published != key && get_timer() >= m.publish_at) {
        m.publish_at = get_timer() + 2000000;
        try {
            var dir = mistrimulti_menu_dir();
            save_text_file(dir + "/world.tmp", "id=" + key + "\n");
            file_rename(dir + "/world.tmp", dir + "/world.txt");
            m.published = key;
            mistrimulti_menu_log("told the launcher this host plays world " + key);
        } catch (e) {
            mmapi_warn_rate_limited("mistrimulti_menu_world_note", "mistrimulti", "Could not tell the launcher which world is played: " + string(e));
        }
    }
    if (m.published == key) mistrimulti_menu_early_save(r, m);
}

// Guest: the host's world key ends in the host's Game.unique_identifier; this game loaded a world with its own. They differ when the
// host plays another world than the downloaded one (for example a new world that was never saved). Never hand a character to such a host.
function mistrimulti_menu_guest_world_check(r) {
    var host = r.peers[0];
    r.world_mismatch = false;
    if ((r.mask & 1) == 0 || !is_struct(host) || !is_string(host[$ "world"]) || host.world == "") return;
    var theirs = mistrimulti_world_key_id(host.world);
    if (theirs == "" || string_digits(theirs) != theirs) return;
    if (string(Game.unique_identifier) != theirs) {
        r.world_mismatch = true;
        mmapi_warn_rate_limited("mistrimulti_world_mismatch", "mistrimulti", "The host plays world " + theirs + " but this game loaded world " + string(Game.unique_identifier) + ".");
    }
}

// A host that starts a NEW world has no save of it, so a friend could not join it. Once the new world is loaded and the player is in
// control (at home, no cutscene, no popup), save it the way the journal does (the game's own save, through its own guards), then say so.
function mistrimulti_menu_early_save(r, m) {
    if (__mistrimulti_savespace()[$ "new_world"] != true || m.save_tried) return;
    var now = get_timer();
    if (m.save_since == 0) m.save_since = now;
    if (now < m.save_next) return;
    m.save_next = now + 1000000;
    if (ARI == undefined || !instance_exists(obj_ari) || LOAD_SEQUENCE == undefined || LOAD_SEQUENCE.is_active() || MIST.is_running() || ANCHOR.popup_is_open()
        || obj_ari.fsm.current_state_id() != PlayerState.Default || !is_home_location(CURRENT_LOCATION_ID)) {
        if (!m.save_told && now - m.save_since > 120000000) {
            m.save_told = true;
            create_notification(ANCHOR.wrap_for_local("MistriaMulti: your new world is not saved yet, so friends cannot join it. Sleep or save at the journal once."));
        }
        return;
    }
    m.save_tried = true;
    mistrimulti_menu_log("saving the new world so friends can join it");
    CLOCK.time_stopped = false;
    obj_ari.fsm.change_state(PlayerState.Dummy);
    LOAD_SEQUENCE.start("misc_local/saving", mistrimulti_menu_early_save_run, [], FADE_SPEED_TRANSITION);
}

// Runs inside the game's loading sequence (the same one the journal's save uses). Always finishes the sequence.
function mistrimulti_menu_early_save_run() {
    var done = false;
    try {
        ARI.save_position = new LocationPosition(CURRENT_LOCATION_ID, Vec2(obj_ari.x, obj_ari.y));
        save_game(exact_save_path(Game.unique_identifier, false));
        done = true;
    } catch (e) {
        mmapi_log_error("mistrimulti", "Saving the new world failed: " + string(e));
    }
    try { obj_ari.fsm.change_state(PlayerState.Default); } catch (e) {}
    try {
        create_notification(ANCHOR.wrap_for_local(done
            ? "MistriaMulti: your new world is saved. Friends can join now."
            : "MistriaMulti: your new world could not be saved. Sleep or save at the journal once so friends can join."));
    } catch (e) {}
    return true;
}
