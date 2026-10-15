// MistriaMulti shared town rank (renown): one total for everyone in a hosted world. Design, assumptions and the in-game
// checklist: docs/SYNC-RENOWN.md.
//
// The game queues renown gains as pending entries during the day (the shipping gold, quest completions, museum donations) and
// drains them at the day rollover, one Ari.modify_renown() per entry, which the MMAPI hook `player.renown_delta` filters.
// set_renown() then raises the level, gives the crossed levels' rewards and starts the rank quests; the end-of-day menu plays
// the level-up popups from `renown + pending entries`.
//
// The host owns the total (`pool`); a guest's game mirrors it:
//   host:   a drained entry is added to the pool at once; the pool is announced to the guests (`renown_state`).
//   guest:  a drained entry that is this player's own gain is sent to the host as a `renown_tx` request (applied exactly once);
//           the host answers with the pool. The shipping gold and the story quests are NOT sent: the host sells the shared
//           bins and the host's game pays the mirrored story quest, so those are counted once, from the host.
// Every game then brings its own renown up to the pool the way the game does it itself. What a game has not applied yet
// (`pool - (renown + carriers)`) is put into its pending list as one "carrier" entry: a gold entry worth exactly the missing
// renown, marked `mm_carrier`. The end-of-day menu shows it like any gain, the day rollover drains it through the game's own
// modify_renown/set_renown, so every player gets the level-up popup, the rank rewards and the rank quests from the game itself,
// once, on their own end of day. A carrier is never counted again (the filter recognises it) and never saved: it is stripped
// before every save and from the progress record and is recomputed from the pool.
//
// Kinds: renown_tx (request {d}), renown_state (host event {p}, to everyone or to one joining guest).

#macro MISTRIMULTI_RENOWN_MAX_DELTA 10000000
#macro MISTRIMULTI_RENOWN_QUEUE 64
#macro MISTRIMULTI_RENOWN_SEND 4

function mistrimulti_renown_register_events() {
    mistrimulti_event_register("renown_tx", { on_request: mistrimulti_renown_tx_request, on_result: mistrimulti_renown_tx_result,
        on_reply: mistrimulti_renown_tx_reply });
    mistrimulti_event_register("renown_state", { on_event: mistrimulti_renown_state_event, on_peer: mistrimulti_renown_peer,
        on_gap: mistrimulti_renown_gap });
}

// Per world session (the event stream changes when the game enters a world).
function __mistrimulti_renown() {
    var r = __mistrimulti_runtime();
    var w = r[$ "renown"];
    if (!is_struct(w) || w.stream != r.ev.stream) {
        w = { stream: r.ev.stream, pool: undefined, dirty: false, snaps: array_create(8, false), known: undefined, queue: [],
            pending: {}, resync: false, based: false };
        r.renown = w;
    }
    return w;
}

// The most renown the game can hold (the clamp of its own set_renown).
function __mistrimulti_renown_max() {
    return renown_level_total_cost(MAX_RENOWN_LEVEL);
}

function __mistrimulti_renown_clamp(v) {
    return max(0, min(v, __mistrimulti_renown_max()));
}

function __mistrimulti_renown_amount(d) {
    return is_real(d) && d == floor(d) && d >= -MISTRIMULTI_RENOWN_MAX_DELTA && d <= MISTRIMULTI_RENOWN_MAX_DELTA;
}

function __mistrimulti_renown_total(p) {
    return is_real(p) && p == floor(p) && p >= 0 && p <= __mistrimulti_renown_max();
}

// ---- pending entries -----------------------------------------------------------------------------------------------------

function __mistrimulti_renown_is_carrier(e) {
    return is_struct(e) && e[$ "mm_carrier"] == true;
}

// The renown this game has been given but not applied yet through carriers.
function __mistrimulti_renown_carried() {
    var list = ARI.pending_renown_entries;
    var sum = 0;
    for (var i = 0; i < list.count(); i++) {
        var e = list.get(i);
        if (__mistrimulti_renown_is_carrier(e)) sum += renown_entry_value(e);
    }
    return sum;
}

// Carriers are derived state: they leave the pending list before a save (the game would load them back as ordinary gold) and
// the next tick makes them again from the pool.
function __mistrimulti_renown_strip() {
    var list = ARI.pending_renown_entries;
    for (var i = list.count() - 1; i >= 0; i--) {
        if (__mistrimulti_renown_is_carrier(list.get(i))) list.remove(i);
    }
}

// The entry being drained: Ari.on_new_day() calls modify_renown from List.drain, which keeps the entry in the list (as the
// first one, the earlier ones are already gone) until the call returns.
function __mistrimulti_renown_current() {
    var list = ARI.pending_renown_entries;
    if (list == undefined || list.count() < 1) return undefined;
    var e = list.get(0);
    return is_struct(e) ? e : undefined;
}

// "carrier", "gold" (the shipping sale), "story" (a story quest, which every game pays), or "own" (everything else, including a
// call that is not a drain at all).
function __mistrimulti_renown_kind(e, value) {
    if (e == undefined) return "own";
    if (__mistrimulti_renown_is_carrier(e)) return "carrier";
    if (renown_entry_value(e) != value) return "own";
    var t = e[$ "type"];
    if (t == RenownEntryType.Gold) return "gold";
    if (t == RenownEntryType.Quest) {
        var quest = QUESTS.get(e[$ "quest_key"]);
        return (quest != undefined && quest.category == QuestCategory.Story) ? "story" : "own";
    }
    return "own";
}

// ---- host: the pool ------------------------------------------------------------------------------------------------------

// The pool starts from the host's own renown in the loaded save, or from the commit of that save if it is higher (the save does
// not hold the carriers). Guests' personal renown is never added (docs/SYNC-RENOWN.md, "Migration").
function __mistrimulti_renown_open(w) {
    var r = __mistrimulti_runtime();
    if (w.pool != undefined) return true;
    if (r.mode != "host" || ARI == undefined || !r.player_ready || r.world_path == "") return false;
    var pool = __mistrimulti_renown_clamp(floor(ARI.renown));
    var key = r[$ "renown_load_key"];
    r.renown_load_key = "";
    if (is_string(key) && key != "") {
        var commit = __mistrimulti_renown_commit_pick(key);
        if (commit != undefined) pool = max(pool, commit.renown);
    }
    w.pool = pool;
    w.dirty = true;
    return true;
}

// Host only, once per request id. The result is the authoritative total (self-describing, so applying it is idempotent).
function mistrimulti_renown_tx_request(from, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || !is_struct(data) || !__mistrimulti_renown_amount(data[$ "d"])) return { ok: false };
    var w = __mistrimulti_renown();
    if (!__mistrimulti_renown_open(w)) return false; // the host's world is not ready: retried on a later tick
    w.pool = __mistrimulti_renown_clamp(w.pool + data.d);
    return { ok: true, p: w.pool };
}

// ---- the funnel: player.renown_delta -------------------------------------------------------------------------------------

// A filter: returns the delta the game should apply. It never changes what the game applies to this player (the player's own
// gain is applied as the game does it); it only reports the gain, or drops a payment that another game counts.
function mistrimulti_renown_delta(value, ctx) {
    var r = __mistrimulti_runtime();
    try {
        if (!r.enabled || !is_real(value) || !is_struct(ctx) || ARI == undefined || ctx[$ "player"] != ARI) return undefined;
        if (!r.player_ready || r.character_pending) return undefined;
        var w = __mistrimulti_renown();
        var kind = __mistrimulti_renown_kind(__mistrimulti_renown_current(), value);
        if (kind == "carrier") return undefined; // already part of the pool
        var d = floor(value);
        if (r.mode == "join") {
            if (kind == "gold" || kind == "story") return 0; // the host's sale and the host's story payment count
            if (d != 0) {
                d = max(-MISTRIMULTI_RENOWN_MAX_DELTA, min(d, MISTRIMULTI_RENOWN_MAX_DELTA));
                // A day rollover drains many entries in one frame: those not sent yet travel as one request.
                var last = array_length(w.queue) - 1;
                if (last >= 0 && __mistrimulti_renown_amount(w.queue[last] + d)) w.queue[last] = w.queue[last] + d;
                else if (last + 1 >= MISTRIMULTI_RENOWN_QUEUE) w.queue[last] = max(-MISTRIMULTI_RENOWN_MAX_DELTA, min(w.queue[last] + d, MISTRIMULTI_RENOWN_MAX_DELTA));
                else array_push(w.queue, d);
                __mistrimulti_renown_flush(w);
            }
            return undefined;
        }
        if (!__mistrimulti_renown_open(w)) return undefined;
        if (d != 0) {
            w.pool = __mistrimulti_renown_clamp(w.pool + d);
            w.dirty = true;
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_renown", "mistrimulti", "A renown gain could not be shared: " + string(e));
    }
    return undefined;
}

// ---- every game: bring renown up to the pool -------------------------------------------------------------------------------

// What this game's renown should add up to: the pool as the host last said, plus what this guest has applied since and the host
// has not answered yet. The host's stream is ordered, so the total in any host message includes exactly the answered deltas.
function __mistrimulti_renown_target(w) {
    var r = __mistrimulti_runtime();
    if (r.mode == "host") return w.pool;
    if (w.known == undefined) return undefined;
    var sum = w.known;
    for (var i = 0; i < array_length(w.queue); i++) sum += w.queue[i];
    var ids = struct_get_names(w.pending);
    for (var j = 0; j < array_length(ids); j++) sum += w.pending[$ ids[j]];
    return __mistrimulti_renown_clamp(sum);
}

// A game that is behind the pool gets the difference as one carrier. A game that is ahead keeps its level (rewards are never
// taken back or given twice). The first time a guest sees the pool with no renown of its own it simply starts at the pool
// without back rewards (docs/SYNC-RENOWN.md, "Migration").
function __mistrimulti_renown_sync(w) {
    var r = __mistrimulti_runtime();
    if (ARI == undefined || !r.player_ready || r.character_pending) return;
    var want = __mistrimulti_renown_target(w);
    if (want == undefined) return;
    var carried = __mistrimulti_renown_carried();
    if (r.mode == "join" && !w.based) {
        w.based = true;
        if (ARI.renown == 0 && carried == 0) {
            ARI.renown = want;
            return;
        }
    }
    var gap = want - (ARI.renown + carried);
    if (gap < 1) return;
    // One carrier per game: a later gain grows it. A gold entry of 100 * k - 50 is worth ceil(0.01 * gold) = k renown.
    var list = ARI.pending_renown_entries;
    for (var i = list.count() - 1; i >= 0; i--) {
        var e = list.get(i);
        if (__mistrimulti_renown_is_carrier(e)) {
            e.gold = (renown_entry_value(e) + gap) * 100 - 50;
            return;
        }
    }
    var entry = RenownEntry.Gold(gap * 100 - 50);
    entry.mm_carrier = true;
    list.push(entry);
}

// ---- guest: requests --------------------------------------------------------------------------------------------------------

function __mistrimulti_renown_flush(w) {
    var sent = 0;
    while (array_length(w.queue) > 0 && sent < MISTRIMULTI_RENOWN_SEND) {
        var rid = mistrimulti_event_request("renown_tx", { d: w.queue[0] });
        if (rid == undefined) return;
        w.pending[$ rid] = w.queue[0];
        array_delete(w.queue, 0, 1);
        sent++;
    }
    if (w.resync && array_length(w.queue) == 0 && sent < MISTRIMULTI_RENOWN_SEND) {
        var ask = mistrimulti_event_request("renown_tx", { d: 0 });
        if (ask != undefined) {
            w.pending[$ ask] = 0;
            w.resync = false;
        }
    }
}

function __mistrimulti_renown_take(w, result) {
    if (is_struct(result) && result[$ "ok"] == true && __mistrimulti_renown_total(result[$ "p"])) w.known = result.p;
}

// Every guest: somebody's change (this guest's own answer included, which settles that delta).
function mistrimulti_renown_tx_result(from, result, ctx) {
    if (__mistrimulti_runtime().mode != "join") return true;
    try {
        var w = __mistrimulti_renown();
        if (ctx.mine && struct_exists(w.pending, ctx.id)) struct_remove(w.pending, ctx.id);
        __mistrimulti_renown_take(w, result);
        __mistrimulti_renown_sync(w);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_renown", "mistrimulti", "A renown answer could not be applied: " + string(e));
    }
    return true;
}

// The requester only: the host restarted (lost: the delta may or may not have been applied; the new host's snapshot is the
// truth) or its answer expired (applied, total unknown: ask again).
function mistrimulti_renown_tx_reply(from, result, ctx) {
    if (__mistrimulti_runtime().mode != "join") return true;
    try {
        var w = __mistrimulti_renown();
        if (struct_exists(w.pending, ctx.id)) struct_remove(w.pending, ctx.id);
        if (!is_struct(result)) w.resync = true;
        __mistrimulti_renown_sync(w);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_renown", "mistrimulti", "A renown request could not be settled: " + string(e));
    }
    return true;
}

function mistrimulti_renown_state_event(from, data, ctx) {
    if (__mistrimulti_runtime().mode != "join" || from != 0) return true;
    try {
        var w = __mistrimulti_renown();
        if (is_struct(data) && __mistrimulti_renown_total(data[$ "p"])) {
            w.known = data.p;
            __mistrimulti_renown_sync(w);
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_renown", "mistrimulti", "The renown total could not be applied: " + string(e));
    }
    return true;
}

// Host: a joining guest is told the pool. Guest: the host (re)appeared; its snapshot follows.
function mistrimulti_renown_peer(slot, joined, stream) {
    var r = __mistrimulti_runtime();
    var w = __mistrimulti_renown();
    if (r.mode == "host") w.snaps[slot] = joined && slot != 0;
    else if (slot == 0 && joined) w.resync = true;
}

function mistrimulti_renown_gap(slot, base, expected) {
    if (slot == 0 && __mistrimulti_runtime().mode == "join") __mistrimulti_renown().resync = true;
}

// ---- tick, persistence, diagnostics ------------------------------------------------------------------------------------------

// Bridge tick (20 Hz) while a world is loaded.
function mistrimulti_renown_tick() {
    var r = __mistrimulti_runtime();
    if (!r.enabled || ARI == undefined || !r.player_ready || r.character_pending) return;
    try {
        var w = __mistrimulti_renown();
        if (r.mode == "host") {
            if (!__mistrimulti_renown_open(w)) return;
            for (var slot = 1; slot < 8; slot++) {
                if (w.snaps[slot] && mistrimulti_event_emit("renown_state", { p: w.pool }, slot)) w.snaps[slot] = false;
            }
            if (w.dirty && (r.mask == 0 || mistrimulti_event_emit("renown_state", { p: w.pool }))) w.dirty = false;
        } else {
            __mistrimulti_renown_flush(w);
        }
        __mistrimulti_renown_sync(w);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_renown", "mistrimulti", "Renown sync failed: " + string(e));
    }
}

function __mistrimulti_renown_commit_path(key) {
    return __mistrimulti_runtime().world_path + "/commits/" + key + ".renown.json";
}

// save.game_saving: carriers leave the pending list (the next tick makes them again). On the host a commit file next to the save
// records the pool for that save (same naming and two generations as the player records' commit), because the save itself holds
// only what the host's game has applied.
function mistrimulti_renown_game_saving(ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || ARI == undefined) return;
    try {
        __mistrimulti_renown_strip();
        if (r.mode != "host" || !r.player_ready || r.world_path == "") return;
        var w = __mistrimulti_renown();
        if (!__mistrimulti_renown_open(w)) return;
        var key = mistrimulti_commit_key(ctx[$ "save_path"]);
        if (key == "") return;
        mistrimulti_commit_write(__mistrimulti_renown_commit_path(key), { v: 1, key: key, world: r.world_key,
            day: string(CALENDAR.time), renown: w.pool });
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_renown", "mistrimulti", "The shared renown could not be committed with the save: " + string(e));
    }
}

// save.game_loaded: remember which save is coming in; the pool is restored when the host's world session opens.
function mistrimulti_renown_game_loaded(ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode == "join") return;
    r.renown_load_key = mistrimulti_commit_key(ctx[$ "save_path"]);
}

function __mistrimulti_renown_commit_pick(key) {
    var r = __mistrimulti_runtime();
    var path = __mistrimulti_renown_commit_path(key);
    for (var i = 0; i < 2; i++) {
        var file = path + (i == 0 ? "" : ".bak");
        if (!file_exists(file)) continue;
        var c = try_read_json_file(file);
        if (is_struct(c) && c[$ "v"] == 1 && c[$ "world"] == r.world_key && c[$ "day"] == string(CALENDAR.time)
            && __mistrimulti_renown_total(c[$ "renown"])) return c;
    }
    return undefined;
}

function mistrimulti_renown_debug() {
    var w = __mistrimulti_renown();
    return { pool: w.pool, known: w.known, queued: array_length(w.queue), pending: array_length(struct_get_names(w.pending)),
        renown: ARI == undefined ? undefined : ARI.renown, carried: ARI == undefined ? undefined : __mistrimulti_renown_carried() };
}
