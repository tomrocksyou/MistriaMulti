// Clock, calendar, weather and the all-player sleep vote. Design and in-game checklist: docs/SYNC-CLOCK.md.
//
// World time (W) belongs to the host. It advances at the host's day speed while at least one in-session
// player's own clock runs, so it stops only when every player is paused, in a cutscene or asleep. Every game,
// the host's included, steers its own clock towards W through clock.time_advance: up to twice as fast when
// behind, slower down to stopped when ahead (never backwards), and CLOCK.jump when far behind.
//
// The day ends when every in-session player is asleep: in bed (cancellable) or in the end-of-day sequence
// (bed after the vote, 2 am pass-out, day-ending cutscenes). Each game holds its own EodMenu.end_sequence
// (new_day, the save, waking up) until the host has ended the day, then runs it once. Only the host saves.
//
// Event kinds: "clock" (host W sample), "clock_report" (guest -> host: own clock running / awake / time),
// "weather" (host forecast), "sleep" (guest request: its sleep state; result = vote), "sleep_vote" (host vote).

#macro MISTRIMULTI_CLOCK_DAWN 21600          // hours(6): a new day's Clock
#macro MISTRIMULTI_CLOCK_LAST 93600          // hours(26): 2 am, when the game makes everyone pass out
#macro MISTRIMULTI_CLOCK_SMOOTH 120          // game seconds of error that double (or stop) a clock
#macro MISTRIMULTI_CLOCK_JUMP 300            // further behind than 5 game minutes (back from a menu): jump
#macro MISTRIMULTI_CLOCK_SYNC 2000000        // host W sample interval while W runs (microseconds)
#macro MISTRIMULTI_CLOCK_REPORT 3000000      // guest report interval while its clock is ahead of W
#macro MISTRIMULTI_CLOCK_FORCE 60000000      // at 2 am the host ends the day this long after it got there

function mistrimulti_clock_fresh() {
    var day = total_days();
    return { owner: ARI, frames: 0, others: 0, local_run: false, step: 86400 / (MINUTES_PER_DAY * 3600),
        day: day, w: CLOCK.time, run: false, cap_at: 0, sent_sig: "", sent_at: 0, weather_sig: "",
        reports: array_create(8, undefined), votes: array_create(8, undefined), seen: array_create(8, ""),
        joined: array_create(8, false), adv: day - 1, vote: undefined, vote_sig: "",
        hd: 0, ht: 0, hr: 0, hm: 1, hat: 0, hs: "", weather: undefined, alone_at: 0,
        state_sent: "", report_sig: "", report_at: 0, eod_day: 0, bed_day: 0, bed_popup: undefined,
        hold: undefined, holding: false, forced_day: 0, warn: "" };
}

// The clock state of the current world session (a new world, a new state).
function __mistrimulti_clock() {
    var r = __mistrimulti_runtime();
    if (!is_struct(r.clock) || r.clock.owner != ARI) r.clock = mistrimulti_clock_fresh();
    return r.clock;
}

function mistrimulti_clock_int(v, lo, hi) {
    return is_real(v) && v == floor(v) && v >= lo && v <= hi;
}

function mistrimulti_clock_register_events() {
    mistrimulti_event_register("clock", { on_event: mistrimulti_clock_event, on_peer: mistrimulti_clock_peer });
    mistrimulti_event_register("clock_report", { on_event: mistrimulti_clock_report });
    mistrimulti_event_register("weather", { on_event: mistrimulti_clock_weather_event });
    mistrimulti_event_register("sleep", { on_request: mistrimulti_clock_sleep_request,
        on_result: mistrimulti_clock_vote_event, on_reply: mistrimulti_clock_sleep_reply });
    mistrimulti_event_register("sleep_vote", { on_event: mistrimulti_clock_vote_event });
}

function mistrimulti_clock_register_hooks() {
    mmapi_filter("clock.time_advance", mistrimulti_clock_time_advance);
    mmapi_on("game.clock_tick", mistrimulti_clock_frame);
    mmapi_on("game.new_day", mistrimulti_clock_new_day);
    mmapi_on("player.pass_out", mistrimulti_clock_pass_out);
    mmapi_on("ui.menu_opened", mistrimulti_clock_menu_opened);
    mmapi_override("object.interact", mistrimulti_clock_bed_interact);
    mmapi_on("ui.draw_gui", mistrimulti_clock_draw);
    mmapi_filter("local.missing", mistrimulti_clock_local_missing);
}

// ---- this game's state -----------------------------------------------------------------------------------

// "eod": committed to ending today (passed out, end-of-day menu, or sleeping after the vote); "bed": lying in
// bed waiting for the others (can still get up); "awake".
function mistrimulti_clock_state() {
    var c = __mistrimulti_runtime().clock;
    var day = total_days();
    if (c.eod_day == day) return "eod";
    if (c.bed_day == day) return "bed";
    return "awake";
}

// Whether the host has ended `day` (everyone slept, or the 2 am timeout), or is already past it.
function mistrimulti_clock_day_done(day) {
    var v = __mistrimulti_runtime().clock.vote;
    return is_struct(v) && day <= max(v.a, v.d - 1);
}

// Free to start an end of day or a clock jump: no menu, cutscene, end of day or wake-up in progress.
function mistrimulti_clock_free() {
    return !game_paused() && !MIST.is_running() && !CLOCK.time_stopped && instance_exists(obj_ari)
        && ARI.end_of_day_sequence != true && ANCHOR.get_menu(Menu.Eod) == undefined;
}

// The world time this game steers to, or undefined (another day, no host time yet, ending the day).
function mistrimulti_clock_target() {
    var r = __mistrimulti_runtime();
    var c = r.clock;
    var day = total_days();
    if (c.eod_day == day) return undefined;
    if (r.mode == "host") return c.w;
    if (c.hat == 0) return undefined;
    if (c.hd == day) return mistrimulti_clock_estimate();
    // Awake before the host: wait at dawn, where the host's new day starts.
    if (day == c.hd + 1 && mistrimulti_clock_day_done(c.hd)) return MISTRIMULTI_CLOCK_DAWN;
    return undefined;
}

// The host's world time now, extrapolated from its last sample.
function mistrimulti_clock_estimate() {
    var c = __mistrimulti_runtime().clock;
    return min(c.ht + c.hr * (get_timer() - c.hat) / 1000000, MISTRIMULTI_CLOCK_LAST);
}

// ---- hooks -----------------------------------------------------------------------------------------------

// clock.time_advance, every frame: the game-seconds this frame adds (0 while paused or time is stopped).
function mistrimulti_clock_time_advance(value, clock) {
    if (value == undefined) return undefined;
    var r = __mistrimulti_runtime();
    if (!r.enabled || ARI == undefined || !is_struct(r.clock) || r.clock.owner != ARI) return undefined;
    var c = r.clock;
    c.local_run = value > 0;
    if (c.local_run) c.step = value; // GAME_SECONDS_PER_FRAME, also needed while this game is paused
    if (r.mode == "host") {
        if (c.others == 0) return undefined; // alone: the host's own clock is the world clock
        if (c.run) c.w = min(c.w + c.step, MISTRIMULTI_CLOCK_LAST);
    }
    if (value <= 0) return undefined;
    var target = mistrimulti_clock_target();
    if (target == undefined) return undefined;
    // A guest runs at the host's day speed, whatever its own setting.
    var base = r.mode == "host" ? value : value * MINUTES_PER_DAY / c.hm;
    var error = target - (clock.time + clock.side_buffer);
    return base * (1 + max(-1, min(1, error / MISTRIMULTI_CLOCK_SMOOTH)));
}

// game.clock_tick, every frame (also while paused): the bridge-rate work, every third frame.
function mistrimulti_clock_frame(clock) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || ARI == undefined || !is_struct(r[$ "ev"])) return;
    var c = __mistrimulti_clock();
    c.frames++;
    if (c.frames mod 3 != 0) return;
    try {
        mistrimulti_clock_tick();
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_clock", "mistrimulti", "Clock sync failed: " + string(e));
    }
}

function mistrimulti_clock_new_day(ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || ARI == undefined) return;
    var c = __mistrimulti_clock();
    c.bed_day = 0;
    if (r.mode == "host") mistrimulti_clock_host_day();
}

function mistrimulti_clock_pass_out(ctx) {
    var r = __mistrimulti_runtime();
    if (r.enabled && ARI != undefined) __mistrimulti_clock().eod_day = total_days();
}

// The end-of-day menu: this player is asleep. Its end_sequence waits for the host's decision.
function mistrimulti_clock_menu_opened(ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || ARI == undefined || ctx.kind != Menu.Eod) return;
    try {
        var c = __mistrimulti_clock();
        c.eod_day = total_days();
        c.hold = ctx.menu.end_sequence;
        c.holding = false;
        ctx.menu.end_sequence = mistrimulti_clock_end_sequence;
    } catch (e) {
        mmapi_log_error("mistrimulti", "End-of-day wrap failed (the day ends without waiting): " + string(e));
    }
}

// Installed over EodMenu.end_sequence (new_day, the save, waking up).
function mistrimulti_clock_end_sequence() {
    var r = __mistrimulti_runtime();
    var c = r.clock;
    try {
        if (r.enabled && is_struct(c) && c.hold != undefined) {
            if (r.mode == "host") mistrimulti_clock_evaluate(total_days());
            if (!mistrimulti_clock_day_done(total_days())) {
                c.holding = true;
                return;
            }
        }
    } catch (e) {
        mmapi_log_error("mistrimulti", "End-of-day wait failed: " + string(e));
    }
    mistrimulti_clock_release();
}

function mistrimulti_clock_release() {
    var c = __mistrimulti_runtime().clock;
    var fn = c.hold;
    c.hold = undefined;
    c.holding = false;
    if (fn != undefined) fn();
}

// object.interact: with other players in the world, a bed asks to wait for them instead of ending the day.
function mistrimulti_clock_bed_interact(node) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || ARI == undefined || !is_struct(r.clock) || r.clock.others == 0) return undefined;
    if (object_id_to_object_category(node.object_id) != ObjectCategory.Furniture) return undefined;
    if (node.prototype[$ "bed_kind"] == undefined || !requirements_pass(Requirement.Sleep)) return undefined;
    // Outside home, or the others already slept: the game's own bed.
    if (!is_home_location(CURRENT_LOCATION_ID) || mistrimulti_clock_day_done(total_days())) return undefined;
    ARI.used_object_today[node.object_id] = true;
    var popup = popup_creator("misc_local/bed", "mistrimulti/sleep_body");
    popup.create_button("misc_local/cancel");
    popup.create_button("misc_local/sleep", mistrimulti_clock_go_to_bed, [node]);
    popup.spawn();
    return true;
}

// The game's own steps before its "sleep" scene; the scene itself starts when everyone is in bed.
function mistrimulti_clock_go_to_bed(node) {
    var c = __mistrimulti_runtime().clock;
    if (TAXI.is_traveling()) return;
    if (CLOCK.time >= MISTRIMULTI_CLOCK_LAST - 600) T2R.write("slept_last_minute", true);
    ARI.last_bed_used = { location_id: CURRENT_LOCATION_ID,
        ni: GRID.node_index_for_cell(node.top_left_x, node.top_left_y) };
    c.bed_day = total_days();
    c.bed_popup = undefined; // the waiting popup opens once this one has closed
}

function mistrimulti_clock_bed_popup() {
    var c = __mistrimulti_runtime().clock;
    var popup = popup_creator("mistrimulti/sleep_wait_title", "mistrimulti/sleep_wait_body");
    popup.create_button("mistrimulti/get_up");
    popup.close_callback = mistrimulti_clock_bed_closed;
    popup.spawn();
    c.bed_popup = popup;
}

// The waiting popup closed by the player (button or back): out of bed.
function mistrimulti_clock_bed_closed() {
    var c = __mistrimulti_runtime().clock;
    if (c.bed_popup == undefined) return;
    c.bed_popup = undefined;
    c.bed_day = 0;
}

// Everyone is in bed: the game's own sleep scene, which ends the day (end_day, end-of-day menu).
function mistrimulti_clock_start_sleep() {
    var c = __mistrimulti_runtime().clock;
    c.eod_day = total_days();
    c.bed_day = 0;
    if (c.bed_popup != undefined) {
        var popup = c.bed_popup;
        c.bed_popup = undefined;
        popup.close();
    }
    var spouse = undefined;
    for (var i = 0; i < instance_number(par_NPC); i++) {
        var npc = instance_find(par_NPC, i);
        if (npc.me.is_spouse()) {
            spouse = npc_id_to_string(npc.npc_id);
            break;
        }
    }
    MIST.blackboard.insert("spouse", spouse);
    MIST.blackboard.insert("spouse_is_present", spouse != undefined);
    MIST.request_scene("sleep");
}

// ---- bridge-rate work ------------------------------------------------------------------------------------

// A guest counts for the vote and for world time once it has been in the world in this session, so a player
// still in the character creator does not hold the others back but one walking through a door does.
function mistrimulti_clock_member(slot) {
    var r = __mistrimulti_runtime();
    var c = r.clock;
    var stream = mistrimulti_clock_stream(slot);
    if (slot == r.id || (r.mask & (1 << slot)) == 0 || stream == "") return false;
    if (r.peers[slot][$ "active"] == true) c.seen[slot] = stream;
    return c.seen[slot] == stream;
}

// The event stream (game session) of a player, or "". Votes and reports belong to one session.
function mistrimulti_clock_stream(slot) {
    var peer = __mistrimulti_runtime().peers[slot];
    if (!is_struct(peer) || !is_struct(peer[$ "ev"]) || !is_string(peer.ev[$ "s"])) return "";
    return peer.ev.s;
}

function mistrimulti_clock_tick() {
    var r = __mistrimulti_runtime();
    var c = r.clock;
    var day = total_days();
    if (r.mode == "host") {
        c.others = 0;
        for (var i = 1; i < 8; i++) if (mistrimulti_clock_member(i)) c.others++;
        mistrimulti_clock_host_tick(day);
    } else {
        c.others = (r.mask & 1) != 0 ? 1 : 0;
        if (c.others > 0) {
            c.alone_at = 0;
            mistrimulti_clock_guest_tick(day);
        } else if (c.alone_at == 0) {
            c.alone_at = get_timer();
        }
    }
    mistrimulti_clock_sleep_tick(day);
}

function mistrimulti_clock_sleep_tick(day) {
    var c = __mistrimulti_runtime().clock;
    var done = mistrimulti_clock_day_done(day);
    if (c.bed_day == day) {
        if (done) mistrimulti_clock_start_sleep();
        else if (c.bed_popup == undefined && !ANCHOR.popup_is_open()) mistrimulti_clock_bed_popup();
    }
    // A guest whose host has been gone for a while is not kept on the black end-of-day screen.
    var abandoned = c.alone_at != 0 && get_timer() - c.alone_at >= MISTRIMULTI_CLOCK_FORCE / 2;
    if (c.holding && (done || abandoned)) mistrimulti_clock_release();
    // One day behind the host (away, in a menu or cutscene while the others slept, or the 2 am timeout).
    if (done && c.eod_day != day && c.bed_day != day && c.forced_day != day && day >= c.vote.d - 1
        && mistrimulti_clock_free()) {
        c.forced_day = day;
        c.eod_day = day;
        if (ARI.end_of_day_status == undefined) ARI.end_of_day_status = EndOfDayStatus.Normal;
        create_notification("mistrimulti/day_ended");
        end_day();
        return;
    }
    // Far behind world time (back from a menu or cutscene, or just joined): jump.
    var target = mistrimulti_clock_target();
    if (target != undefined && target - CLOCK.time > MISTRIMULTI_CLOCK_JUMP && mistrimulti_clock_free()) {
        CLOCK.jump(floor(target));
    }
}

// ---- host ------------------------------------------------------------------------------------------------

function mistrimulti_clock_host_day() {
    var c = __mistrimulti_runtime().clock;
    var day = total_days();
    c.day = day;
    c.w = CLOCK.time;
    c.run = false;
    c.cap_at = 0;
    c.adv = max(c.adv, day - 1);
}

function mistrimulti_clock_sample() {
    var c = __mistrimulti_runtime().clock;
    var rate = c.run && c.w < MISTRIMULTI_CLOCK_LAST ? 86400 / (MINUTES_PER_DAY * 60) : 0;
    return { d: c.day, t: floor(c.w), r: rate, m: MINUTES_PER_DAY };
}

function mistrimulti_clock_weather() {
    return { d: total_days(), f: WEATHER.forecast };
}

function mistrimulti_clock_host_tick(day) {
    var c = __mistrimulti_runtime().clock;
    if (c.day != day) mistrimulti_clock_host_day();
    var awake = mistrimulti_clock_state() == "awake";
    if (c.others == 0) {
        if (awake) c.w = CLOCK.time;
        c.run = false;
    } else {
        // W runs while anyone's own clock runs. It follows a forward jump (a cutscene everyone saw)
        // only once every awake player is past it; one player's jump (oversleeping) is that player's.
        var run = awake && c.local_run;
        var low = awake ? CLOCK.time : MISTRIMULTI_CLOCK_LAST + 1;
        var known = true;
        for (var i = 1; i < 8; i++) {
            if (!mistrimulti_clock_member(i)) continue;
            var rep = c.reports[i];
            if (!is_struct(rep) || rep.d != day || rep.st != mistrimulti_clock_stream(i)) {
                known = false;
                continue;
            }
            if (rep.a) {
                run = run || rep.run;
                low = min(low, rep.t);
            }
        }
        c.run = run;
        if (known && low <= MISTRIMULTI_CLOCK_LAST && low > c.w + 60) {
            c.w = low;
            c.sent_sig = "";
        }
    }
    mistrimulti_clock_evaluate(day);
    if (c.others == 0) {
        c.sent_sig = "";
        c.vote_sig = "";
        c.weather_sig = "";
        return;
    }
    var now = get_timer();
    var sig = string(day) + (c.run ? "r" : "s");
    if (sig != c.sent_sig || (c.run && now - c.sent_at >= MISTRIMULTI_CLOCK_SYNC)) {
        if (mistrimulti_event_emit("clock", mistrimulti_clock_sample())) {
            c.sent_sig = sig;
            c.sent_at = now;
        }
    }
    var vsig = json_stringify(c.vote);
    if (vsig != c.vote_sig && mistrimulti_event_emit("sleep_vote", c.vote)) c.vote_sig = vsig;
    if (c.frames mod 60 == 0 || c.weather_sig == "") {
        var weather = mistrimulti_clock_weather();
        var wsig = json_stringify(weather);
        if (wsig != c.weather_sig && mistrimulti_event_emit("weather", weather)) c.weather_sig = wsig;
    }
    // A player who just arrived gets the current state.
    for (var j = 1; j < 8; j++) {
        if (!c.joined[j] || !mistrimulti_event_can_emit(3)) continue;
        mistrimulti_event_emit("clock", mistrimulti_clock_sample(), j);
        mistrimulti_event_emit("sleep_vote", c.vote, j);
        mistrimulti_event_emit("weather", mistrimulti_clock_weather(), j);
        c.joined[j] = false;
    }
}

// The vote: the host plus every member; ready = in bed or ending the day.
function mistrimulti_clock_evaluate(day) {
    var c = __mistrimulti_runtime().clock;
    var need = 1;
    var ready = mistrimulti_clock_state() == "awake" ? 0 : 1;
    for (var i = 1; i < 8; i++) {
        if (!mistrimulti_clock_member(i)) continue;
        need++;
        var v = c.votes[i];
        if (is_struct(v) && v.d == day && v.s != "awake" && v.st == mistrimulti_clock_stream(i)) ready++;
    }
    // At 2 am everyone awake passes out; someone still in a menu or cutscene cannot hold the day forever.
    if (c.w < MISTRIMULTI_CLOCK_LAST || ready == 0) c.cap_at = 0;
    else if (c.cap_at == 0) c.cap_at = get_timer();
    var late = c.cap_at != 0 && get_timer() - c.cap_at >= MISTRIMULTI_CLOCK_FORCE;
    if (c.adv < day && (ready == need || late)) c.adv = day;
    c.vote = { d: day, n: ready, m: need, a: c.adv };
}

function mistrimulti_clock_sleep_request(from, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || ARI == undefined || from == 0 || !is_struct(data)) return { ok: false };
    var c = __mistrimulti_clock();
    var day = total_days();
    var d = data[$ "d"];
    var s = data[$ "s"];
    if (mistrimulti_clock_int(d, 1, 1000000) && is_string(s) && (s == "awake" || s == "bed" || s == "eod")) {
        var old = c.votes[from];
        var stream = mistrimulti_clock_stream(from);
        // A guest that woke into the host's day ran its own new_day: resend the farm (MistriMultiTerrain).
        if (d == day && is_struct(old) && old.st == stream && old.d < day) r.snapshot_pending = true;
        c.votes[from] = { d: d, s: s, st: stream };
    }
    mistrimulti_clock_evaluate(day);
    c.vote_sig = json_stringify(c.vote);
    return c.vote;
}

function mistrimulti_clock_report(from, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || ARI == undefined || from == 0 || !is_struct(data)) return true;
    var run = data[$ "run"];
    var awake = data[$ "a"];
    var t = data[$ "t"];
    if (typeof(run) != "bool" || typeof(awake) != "bool" || !mistrimulti_clock_int(data[$ "d"], 1, 1000000)) return true;
    if (!is_real(t) || t < 0 || t > MISTRIMULTI_CLOCK_LAST) return true;
    __mistrimulti_clock().reports[from] = { run: run, a: awake, d: data.d, t: t, st: mistrimulti_clock_stream(from) };
    return true;
}

function mistrimulti_clock_peer(slot, joined, stream) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || ARI == undefined) return;
    var c = __mistrimulti_clock();
    // Events of a new session can arrive just before its on_peer: state is keyed by session, not cleared here.
    if (r.mode == "host") {
        c.joined[slot] = joined;
    } else if (slot == 0 && joined) {
        c.state_sent = ""; // tell a new (or restarted) host our state
        c.report_sig = "";
    } else if (slot == 0 && stream == c.hs) {
        c.vote = undefined; // the host this state came from has gone
        c.hat = 0;
    }
}

// ---- guest -----------------------------------------------------------------------------------------------

function mistrimulti_clock_guest_tick(day) {
    var c = __mistrimulti_runtime().clock;
    var state = mistrimulti_clock_state();
    var sig = string(day) + ":" + state;
    if (sig != c.state_sent && mistrimulti_event_request("sleep", { d: day, s: state }) != undefined) c.state_sent = sig;
    var now = get_timer();
    var target = mistrimulti_clock_target();
    var ahead = target != undefined && CLOCK.time > target + MISTRIMULTI_CLOCK_SMOOTH;
    var awake = state == "awake";
    var rsig = sig + (c.local_run ? "r" : "s");
    if (rsig != c.report_sig || (ahead && now - c.report_at >= MISTRIMULTI_CLOCK_REPORT)) {
        var report = { run: c.local_run && awake, a: awake, d: day, t: min(floor(CLOCK.time), MISTRIMULTI_CLOCK_LAST) };
        if (mistrimulti_event_emit("clock_report", report, 0)) {
            c.report_sig = rsig;
            c.report_at = now;
        }
    }
    var w = c.weather;
    if (is_struct(w) && w.d < day) c.weather = undefined;
    else if (is_struct(w) && w.d == day && !MIST.is_running()) {
        c.weather = undefined;
        WEATHER.forecast = w.f;
        var today = CALENDAR.day();
        if (today < array_length(w.f) && !WEATHER.under_spell && WEATHER.weather != w.f[today]) WEATHER.set_weather(w.f[today]);
    }
    c.warn = "";
    if (c.hat != 0 && is_struct(c.vote)) {
        if (day > max(c.hd, c.vote.a + 1)) c.warn = "Your day is ahead of the host's world: rejoin to load it again.";
        else if (day < c.hd - 1) c.warn = "Your day is behind the host's world: rejoin to load it again.";
    }
}

function mistrimulti_clock_event(from, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "join" || from != 0 || ARI == undefined || !is_struct(data)) return true;
    var t = data[$ "t"];
    var rate = data[$ "r"];
    var m = data[$ "m"];
    if (!mistrimulti_clock_int(data[$ "d"], 1, 1000000) || !is_real(t) || t < 0 || t > MISTRIMULTI_CLOCK_LAST) return true;
    if (!is_real(rate) || rate < 0 || rate > 100000 || !is_real(m) || m <= 0 || m > 100000) return true;
    var c = __mistrimulti_clock();
    var stream = mistrimulti_clock_stream(0);
    // A sample can arrive late (queued behind a loss); it never moves the estimate of the same day back.
    if (c.hat != 0 && c.hs == stream && c.hd == data.d) t = max(t, mistrimulti_clock_estimate());
    c.hs = stream;
    c.hd = data.d;
    c.ht = t;
    c.hr = rate;
    c.hm = m;
    c.hat = get_timer();
    return true;
}

function mistrimulti_clock_weather_event(from, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "join" || from != 0 || ARI == undefined || !is_struct(data)) return true;
    var f = data[$ "f"];
    if (!mistrimulti_clock_int(data[$ "d"], 1, 1000000) || !is_array(f) || array_length(f) < 1 || array_length(f) > 64) return true;
    for (var i = 0; i < array_length(f); i++) if (!mistrimulti_clock_int(f[i], 0, Weather.LEN - 1)) return true;
    __mistrimulti_clock().weather = { d: data.d, f: f };
    return true;
}

// A host vote (event or request result): { d: host day, n: ready, m: needed, a: last day the host ended }.
function mistrimulti_clock_vote_event(from, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "join" || from != 0 || ARI == undefined || !is_struct(data)) return true;
    var d = data[$ "d"];
    if (!mistrimulti_clock_int(d, 1, 1000000) || !mistrimulti_clock_int(data[$ "a"], 0, d)) return true;
    if (!mistrimulti_clock_int(data[$ "m"], 1, 8) || !mistrimulti_clock_int(data[$ "n"], 0, data.m)) return true;
    var c = __mistrimulti_clock();
    c.hs = mistrimulti_clock_stream(0);
    c.vote = { d: d, n: data.n, m: data.m, a: data.a };
    return true;
}

// The host restarted (or the answer expired): tell the host our state again.
function mistrimulti_clock_sleep_reply(from, result, ctx) {
    var r = __mistrimulti_runtime();
    if ((ctx.lost || ctx.expired) && ARI != undefined) __mistrimulti_clock().state_sent = "";
}

// ---- display ---------------------------------------------------------------------------------------------

function mistrimulti_clock_lines() {
    var c = __mistrimulti_runtime().clock;
    var v = c.vote;
    var lines = [];
    if (is_struct(v) && v.m > 1 && v.n > 0 && v.d == total_days()) {
        array_push(lines, string(v.n) + "/" + string(v.m) + " sleeping");
    }
    if (c.warn != "") array_push(lines, c.warn);
    return lines;
}

// "1/2 sleeping" under the HUD clock (top right), and a waiting line on the black end-of-day screen. Both are ANCHOR text
// nodes (MistriMultiHudText.gml: the mod runtime has no draw_* functions); a slot with an empty text is hidden.
#macro MISTRIMULTI_CLOCK_LINE_SLOTS 2
function mistrimulti_clock_draw(resize) {
    var r = __mistrimulti_runtime();
    var lines = [];
    var holding = false;
    try {
        if (r.enabled && ARI != undefined && is_struct(r.clock) && r.clock.owner == ARI) {
            lines = mistrimulti_clock_lines();
            holding = r.clock.holding == true;
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_clock_draw", "mistrimulti", "Sleep counter failed: " + string(e));
    }
    for (var i = 0; i < MISTRIMULTI_CLOCK_LINE_SLOTS; i++) {
        var text = i < array_length(lines) ? lines[i] : "";
        mistrimulti_hudtext_set("clock" + string(i), text, 16777215, "hud", "right", "top", -8, 62 + 12 * i);
    }
    var wait = holding ? "Waiting for the other players to sleep" : "";
    mistrimulti_hudtext_set("clock_wait", wait, 16777215, "above_fader", "center", "middle", 0, 0);
}

function mistrimulti_clock_local_missing(value, ctx) {
    switch (ctx.key) {
        case "mistrimulti/sleep_body": return "Go to sleep? The day ends when every player is asleep.";
        case "mistrimulti/sleep_wait_title": return "Sleeping";
        case "mistrimulti/sleep_wait_body": return "Waiting for the other players to go to bed.";
        case "mistrimulti/get_up": return "Get up";
        case "mistrimulti/day_ended": return "The others went to sleep: the day is over.";
    }
    return undefined;
}
