// MistriaMulti shared wallet: one gold pool for everyone in a hosted world. Design, assumptions and the in-game checklist:
// docs/SYNC-WALLET.md.
//
// The host owns the pool. Every gold change of the game goes through Ari.modify_gold(), which the MMAPI hook
// `player.gold_delta` filters, so this file sees all of them in one place (sales, rewards, shop baskets, fees, craft costs,
// the end-of-day shipping payout). Absolute sets (save load, new game, debug) do not pass through it.
//   host:   the change is applied to the pool at once; the host's own gold is set to the pool; a `wallet_state` event tells
//           the guests.
//   guest:  the change becomes a signed delta, sent to the host as a `wallet_tx` request (applied exactly once). The host
//           answers with the new balance, broadcast to everyone. Until the answer arrives the guest shows
//           balance + its own unanswered deltas, so the HUD moves at once and never double counts.
// The pool never goes negative. A guest spends against its mirror of the pool; if two players spend the same gold at the
// same moment the host takes the pool to 0 and remembers the shortfall as a debt that future income pays off first, so
// no gold is created from nothing.
//
// Kinds: wallet_tx (request), wallet_state (host event: {g: pool, s: debt}, to everyone or to one joining guest).

#macro MISTRIMULTI_WALLET_MAX_DELTA 100000000
#macro MISTRIMULTI_WALLET_MAX_POOL 999999999
#macro MISTRIMULTI_WALLET_QUEUE 64
#macro MISTRIMULTI_WALLET_SEND 4

function mistrimulti_wallet_register_events() {
    mistrimulti_event_register("wallet_tx", { on_request: mistrimulti_wallet_tx_request, on_result: mistrimulti_wallet_tx_result,
        on_reply: mistrimulti_wallet_tx_reply });
    mistrimulti_event_register("wallet_state", { on_event: mistrimulti_wallet_state_event, on_peer: mistrimulti_wallet_peer,
        on_gap: mistrimulti_wallet_gap });
}

// Per world session (the event stream changes when the game enters a world).
function __mistrimulti_wallet() {
    var r = __mistrimulti_runtime();
    var w = r[$ "wallet"];
    if (!is_struct(w) || w.stream != r.ev.stream) {
        w = { stream: r.ev.stream, pool: undefined, debt: 0, dirty: false, snaps: array_create(8, false),
            known: undefined, queue: [], pending: {}, resync: false, eod_taken: false };
        r.wallet = w;
    }
    return w;
}

function __mistrimulti_wallet_amount(d) {
    return is_real(d) && d == floor(d) && d >= -MISTRIMULTI_WALLET_MAX_DELTA && d <= MISTRIMULTI_WALLET_MAX_DELTA;
}

function __mistrimulti_wallet_balance(g) {
    return is_real(g) && g == floor(g) && g >= 0 && g <= MISTRIMULTI_WALLET_MAX_POOL;
}

// ---- host: the pool ------------------------------------------------------------------------------------------------

// The pool starts from the host's own gold in the loaded save (which holds the pool, see mistrimulti_wallet_game_saving),
// or from the commit of that save. Guests' personal gold is never added (docs/SYNC-WALLET.md, "Migration").
function __mistrimulti_wallet_open(w) {
    var r = __mistrimulti_runtime();
    if (w.pool != undefined) return true;
    if (r.mode != "host" || ARI == undefined || !r.player_ready || r.world_path == "") return false;
    var pool = __mistrimulti_wallet_clamp(floor(ARI.get_gold()));
    var debt = 0;
    var key = r[$ "wallet_load_key"];
    r.wallet_load_key = "";
    if (is_string(key) && key != "") {
        var commit = __mistrimulti_wallet_commit_pick(key);
        if (commit != undefined) {
            pool = commit.gold;
            debt = commit.debt;
        }
    }
    w.pool = pool;
    w.debt = debt;
    w.dirty = true;
    return true;
}

function __mistrimulti_wallet_clamp(v) {
    return max(0, min(v, MISTRIMULTI_WALLET_MAX_POOL));
}

// Income pays the debt first; a spend beyond the pool takes it to 0 and the rest becomes debt.
function __mistrimulti_wallet_apply(w, d) {
    if (d >= 0) {
        var pay = min(w.debt, d);
        w.debt -= pay;
        w.pool = __mistrimulti_wallet_clamp(w.pool + d - pay);
    } else {
        var take = min(w.pool, -d);
        w.pool -= take;
        w.debt = min(w.debt - d - take, MISTRIMULTI_WALLET_MAX_POOL);
    }
}

// Host only, once per request id. The result is the authoritative balance (self-describing, so applying it is idempotent).
function mistrimulti_wallet_tx_request(from, data, ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode != "host" || !is_struct(data) || !__mistrimulti_wallet_amount(data[$ "d"])) return { ok: false };
    var w = __mistrimulti_wallet();
    if (!__mistrimulti_wallet_open(w)) return false; // the host's world is not ready: retried on a later tick
    __mistrimulti_wallet_apply(w, data.d);
    __mistrimulti_wallet_pull(w);
    return { ok: true, g: w.pool, s: w.debt };
}

// ---- the funnel: player.gold_delta ----------------------------------------------------------------------------------

// A filter: returns the delta the game should apply. Fails soft (any error leaves the game's own delta).
function mistrimulti_wallet_gold_delta(value, ctx) {
    var r = __mistrimulti_runtime();
    try {
        if (!r.enabled || !is_real(value) || !is_struct(ctx) || ARI == undefined || ctx[$ "player"] != ARI) return undefined;
        if (!r.player_ready || r.character_pending) return undefined;
        var w = __mistrimulti_wallet();
        var gold = ARI.get_gold();
        var eff = max(floor(gold + value), 0) - gold; // what the game's own set_gold will make of it
        // The first gold change of an end-of-day sequence is the shipping payout (sell_shipping_bin_items runs right after
        // end_of_day_sequence is set). The host sells the shared bins once; a guest's copy of the same sale is dropped.
        var sequence = ARI.end_of_day_sequence == true;
        var payout = sequence && !w.eod_taken;
        w.eod_taken = sequence;
        if (r.mode == "join") {
            if (payout) return 0;
            if (eff != 0) {
                var last = array_length(w.queue) - 1;
                if (last + 1 >= MISTRIMULTI_WALLET_QUEUE) w.queue[last] = w.queue[last] + eff; // a long outage: merge the newest
                else array_push(w.queue, eff);
                __mistrimulti_wallet_flush(w);
            }
            return eff;
        }
        if (!__mistrimulti_wallet_open(w)) return undefined;
        var before = w.pool;
        __mistrimulti_wallet_apply(w, eff);
        w.dirty = true;
        return w.pool - before; // the game ends up exactly at the pool, debt payments included
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_wallet", "mistrimulti", "A gold change could not be shared: " + string(e));
    }
    return undefined;
}

// ---- guest: the mirror -----------------------------------------------------------------------------------------------

// What this guest's gold should be: the pool as the host last said, plus what this guest did since and the host has not
// answered yet. The host's stream is ordered, so the balance in any host message includes exactly the answered deltas.
function __mistrimulti_wallet_expected(w) {
    var r = __mistrimulti_runtime();
    if (r.mode == "host") return w.pool;
    if (w.known == undefined) return undefined;
    var sum = w.known;
    for (var i = 0; i < array_length(w.queue); i++) sum += w.queue[i];
    var ids = struct_get_names(w.pending);
    for (var j = 0; j < array_length(ids); j++) sum += w.pending[$ ids[j]];
    return __mistrimulti_wallet_clamp(sum);
}

// Sets the game's gold to the expected value (set_gold is absolute: it does not go through the filter again).
function __mistrimulti_wallet_pull(w) {
    var r = __mistrimulti_runtime();
    if (ARI == undefined || !r.player_ready || r.character_pending) return;
    var want = __mistrimulti_wallet_expected(w);
    if (want != undefined && ARI.get_gold() != want) ARI.set_gold(want);
}

function __mistrimulti_wallet_flush(w) {
    var sent = 0;
    while (array_length(w.queue) > 0 && sent < MISTRIMULTI_WALLET_SEND) {
        var rid = mistrimulti_event_request("wallet_tx", { d: w.queue[0] });
        if (rid == undefined) return;
        w.pending[$ rid] = w.queue[0];
        array_delete(w.queue, 0, 1);
        sent++;
    }
    if (w.resync && array_length(w.queue) == 0 && sent < MISTRIMULTI_WALLET_SEND) {
        var ask = mistrimulti_event_request("wallet_tx", { d: 0 });
        if (ask != undefined) {
            w.pending[$ ask] = 0;
            w.resync = false;
        }
    }
}

function __mistrimulti_wallet_take(w, result) {
    if (is_struct(result) && result[$ "ok"] == true && __mistrimulti_wallet_balance(result[$ "g"])) {
        w.known = result.g;
        w.debt = is_real(result[$ "s"]) ? result.s : 0;
    }
}

// Every guest: somebody's change (this guest's own answer included, which settles that delta).
function mistrimulti_wallet_tx_result(from, result, ctx) {
    if (__mistrimulti_runtime().mode != "join") return true;
    try {
        var w = __mistrimulti_wallet();
        if (ctx.mine && struct_exists(w.pending, ctx.id)) struct_remove(w.pending, ctx.id);
        __mistrimulti_wallet_take(w, result);
        __mistrimulti_wallet_pull(w);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_wallet", "mistrimulti", "A wallet answer could not be applied: " + string(e));
    }
    return true;
}

// The requester only: the host restarted (lost: the delta may or may not have been applied; the new host's snapshot is the
// truth) or its answer expired (applied, balance unknown: ask again).
function mistrimulti_wallet_tx_reply(from, result, ctx) {
    if (__mistrimulti_runtime().mode != "join") return true;
    try {
        var w = __mistrimulti_wallet();
        if (struct_exists(w.pending, ctx.id)) struct_remove(w.pending, ctx.id);
        if (!is_struct(result)) w.resync = true;
        __mistrimulti_wallet_pull(w);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_wallet", "mistrimulti", "A wallet request could not be settled: " + string(e));
    }
    return true;
}

function mistrimulti_wallet_state_event(from, data, ctx) {
    if (__mistrimulti_runtime().mode != "join" || from != 0) return true;
    try {
        var w = __mistrimulti_wallet();
        if (is_struct(data) && __mistrimulti_wallet_balance(data[$ "g"])) {
            w.known = data.g;
            w.debt = is_real(data[$ "s"]) ? data.s : 0;
            __mistrimulti_wallet_pull(w);
        }
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_wallet", "mistrimulti", "The wallet state could not be applied: " + string(e));
    }
    return true;
}

// Host: a joining guest is told the pool. Guest: the host (re)appeared; its snapshot follows.
function mistrimulti_wallet_peer(slot, joined, stream) {
    var r = __mistrimulti_runtime();
    var w = __mistrimulti_wallet();
    if (r.mode == "host") w.snaps[slot] = joined && slot != 0;
    else if (slot == 0 && joined) w.resync = true;
}

function mistrimulti_wallet_gap(slot, base, expected) {
    if (slot == 0 && __mistrimulti_runtime().mode == "join") __mistrimulti_wallet().resync = true;
}

// ---- tick, persistence, diagnostics -----------------------------------------------------------------------------------

// Bridge tick (20 Hz) while a world is loaded.
function mistrimulti_wallet_tick() {
    var r = __mistrimulti_runtime();
    if (!r.enabled || ARI == undefined || !r.player_ready || r.character_pending) return;
    try {
        var w = __mistrimulti_wallet();
        if (ARI.end_of_day_sequence != true) w.eod_taken = false;
        if (r.mode == "host") {
            if (!__mistrimulti_wallet_open(w)) return;
            for (var slot = 1; slot < 8; slot++) {
                if (w.snaps[slot] && mistrimulti_event_emit("wallet_state", { g: w.pool, s: w.debt }, slot)) w.snaps[slot] = false;
            }
            if (w.dirty && (r.mask == 0 || mistrimulti_event_emit("wallet_state", { g: w.pool, s: w.debt }))) w.dirty = false;
        } else {
            __mistrimulti_wallet_flush(w);
        }
        __mistrimulti_wallet_pull(w);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_wallet", "mistrimulti", "Wallet sync failed: " + string(e));
    }
}

function __mistrimulti_wallet_commit_path(key) {
    return __mistrimulti_runtime().world_path + "/commits/" + key + ".wallet.json";
}

// save.game_saving (host): the save holds the pool as the host's own gold, and a commit file next to it records the pool and
// the debt for that save (same naming and two generations as the player records' commit).
function mistrimulti_wallet_game_saving(ctx) {
    var r = __mistrimulti_runtime();
    if (!r.enabled || r.mode != "host" || !r.player_ready || r.world_path == "") return;
    try {
        var w = __mistrimulti_wallet();
        if (!__mistrimulti_wallet_open(w)) return;
        __mistrimulti_wallet_pull(w);
        var key = mistrimulti_commit_key(ctx[$ "save_path"]);
        if (key == "") return;
        mistrimulti_commit_write(__mistrimulti_wallet_commit_path(key), { v: 1, key: key, world: r.world_key,
            day: string(CALENDAR.time), gold: w.pool, debt: w.debt });
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_wallet", "mistrimulti", "The shared gold could not be committed with the save: " + string(e));
    }
}

// save.game_loaded: remember which save is coming in; the pool is restored when the host's world session opens.
function mistrimulti_wallet_game_loaded(ctx) {
    var r = __mistrimulti_runtime();
    if (r.mode == "join") return;
    r.wallet_load_key = mistrimulti_commit_key(ctx[$ "save_path"]);
}

function __mistrimulti_wallet_commit_pick(key) {
    var r = __mistrimulti_runtime();
    var path = __mistrimulti_wallet_commit_path(key);
    for (var i = 0; i < 2; i++) {
        var file = path + (i == 0 ? "" : ".bak");
        if (!file_exists(file)) continue;
        var c = try_read_json_file(file);
        if (is_struct(c) && c[$ "v"] == 1 && c[$ "world"] == r.world_key && c[$ "day"] == string(CALENDAR.time)
            && __mistrimulti_wallet_balance(c[$ "gold"]) && __mistrimulti_wallet_balance(c[$ "debt"])) return c;
    }
    return undefined;
}

function mistrimulti_wallet_debug() {
    var w = __mistrimulti_wallet();
    return { pool: w.pool, debt: w.debt, known: w.known, queued: array_length(w.queue),
        pending: array_length(struct_get_names(w.pending)), gold: ARI == undefined ? undefined : ARI.get_gold() };
}
