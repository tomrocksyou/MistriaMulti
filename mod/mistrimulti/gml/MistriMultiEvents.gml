// MistriMulti event layer: batched, ordered, acknowledged events between game instances, blobs larger
// than one bridge frame, and host-authoritative requests. Design and feature guide: docs/EVENT-LAYER.md.
//
// tests/event_model.py is the executable specification; every function below mirrors the Python method
// of the same name (internal __mistrimulti_ev_x <-> _ev_x). Change both together. The tests run this file
// through tests/gml_subset.py as well as the Python model.
//
// Public API (other files call only these):
//   mistrimulti_event_register(kind, handlers)       handlers: { on_event, on_request, on_result, on_reply,
//                                                     on_blob, on_peer, on_gap }, each function(a, b, c)
//   mistrimulti_event_emit(kind, data, target)       ordered reliable event; target -1 = everyone
//   mistrimulti_event_request(kind, data)            host-authoritative request; returns its id or undefined
//   mistrimulti_event_send_blob(kind, text, target, meta)   a string up to 256 KB, delivered whole or not at all
//   mistrimulti_event_can_emit(count) / _backlog() / _blobs_pending() / _requests_pending()
// Boot calls mistrimulti_events_initialize/reset/receive/tick/encode/reliable.

#macro MISTRIMULTI_EV_FRAME_LIMIT 16384
#macro MISTRIMULTI_EV_FRAME_MARGIN 256
#macro MISTRIMULTI_EV_WINDOW_BYTES 12288
#macro MISTRIMULTI_EV_EVENT_BYTES 8192
#macro MISTRIMULTI_EV_QUEUE_EVENTS 512
#macro MISTRIMULTI_EV_QUEUE_BYTES 524288
#macro MISTRIMULTI_EV_BLOB_BYTES 262144
#macro MISTRIMULTI_EV_BLOB_JOBS 8
#macro MISTRIMULTI_EV_BLOB_META_BYTES 2048
#macro MISTRIMULTI_EV_CHUNK_CHARS 2048
#macro MISTRIMULTI_EV_CHUNK_BYTES 6144
#macro MISTRIMULTI_EV_PENDING_LIMIT 64
#macro MISTRIMULTI_EV_DONE_LIMIT 64
#macro MISTRIMULTI_EV_DONE_BYTES 65536
#macro MISTRIMULTI_EV_REQ_STREAMS 16
#macro MISTRIMULTI_EV_ACK_HOT_TICKS 90
#macro MISTRIMULTI_EV_FNV_OFFSET 2166136261

// ---- lifecycle ---------------------------------------------------------------------------------------

function mistrimulti_events_initialize() {
    var r = __mistrimulti_runtime();
    if (!is_struct(r[$ "ev"])) r.ev = { handlers: {} };
    mistrimulti_events_reset();
}

// A new stream: everything queued or half-received belongs to the previous world session.
function mistrimulti_events_reset() {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    ev.stream = string(r.id) + "-" + string_copy(r.epoch, 1, 8) + "-" + string(get_timer());
    ev.next = 1;
    ev.out = [];
    ev.sizes = [];
    ev.out_bytes = 0;
    ev.rx = array_create(8, undefined);
    for (var i = 0; i < 8; i++) ev.rx[i] = { s: "", x: 0, blob: undefined };
    ev.peer_stream = array_create(8, "");
    ev.host_stream = "";
    ev.blobs = [];
    ev.next_blob = 1;
    ev.pending = {};
    ev.pending_ids = [];
    ev.next_request = 1;
    ev.resend = false;
    ev.local = [];
    ev.req = {};
    ev.req_order = [];
    ev.ack_hot = 0;
    ev.errors = 0;
    ev.stalls = 0;
    ev.gaps = 0;
}

function mistrimulti_event_register(kind, handlers) {
    var r = __mistrimulti_runtime();
    if (!is_struct(r[$ "ev"])) mistrimulti_events_initialize();
    if (!__mistrimulti_ev_valid_kind(kind) || !is_struct(handlers)) return false;
    var ev = r.ev;
    ev.handlers[$ kind] = handlers;
    return true;
}

// ---- sending -----------------------------------------------------------------------------------------

function mistrimulti_event_emit(kind, data, target = -1) {
    if (!__mistrimulti_ev_valid_kind(kind) || !__mistrimulti_ev_valid_target(target)) return false;
    return __mistrimulti_ev_push(kind, data, target, target >= 0 ? __mistrimulti_ev_stream_of(target) : "");
}

function mistrimulti_event_request(kind, data) {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    if (!__mistrimulti_ev_valid_kind(kind) || ev.resend) return undefined;
    var n = ev.next_request;
    var rid = ev.stream + ":" + string(n);
    var d = { k: kind, n: n, i: rid, d: data };
    if (r.id == 0) {
        if (array_length(ev.local) >= MISTRIMULTI_EV_PENDING_LIMIT) return undefined;
        array_push(ev.local, json_parse(json_stringify(d)));
    } else {
        if (array_length(ev.pending_ids) >= MISTRIMULTI_EV_PENDING_LIMIT) return undefined;
        if (!__mistrimulti_ev_push("~q", d, 0, ev.host_stream)) return undefined;
        ev.pending[$ rid] = json_parse(json_stringify(d));
        array_push(ev.pending_ids, rid);
    }
    ev.next_request++;
    return rid;
}

function mistrimulti_event_send_blob(kind, text, target = -1, meta = undefined) {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    if (!__mistrimulti_ev_valid_kind(kind) || !is_string(text) || !__mistrimulti_ev_valid_target(target)) return false;
    if (meta != undefined && (!is_struct(meta) || string_byte_length(json_stringify(meta)) > MISTRIMULTI_EV_BLOB_META_BYTES)) return false;
    var size = string_byte_length(text);
    if (size > MISTRIMULTI_EV_BLOB_BYTES || array_length(ev.blobs) >= MISTRIMULTI_EV_BLOB_JOBS) return false;
    array_push(ev.blobs, { i: ev.next_blob, k: kind, t: target, ts: target >= 0 ? __mistrimulti_ev_stream_of(target) : "",
        m: meta == undefined ? undefined : json_parse(json_stringify(meta)),
        text: text, len: string_length(text), l: size, pos: 1, n: 0, h: MISTRIMULTI_EV_FNV_OFFSET });
    ev.next_blob++;
    return true;
}

function mistrimulti_event_can_emit(count) {
    var ev = __mistrimulti_runtime().ev;
    return array_length(ev.out) + count <= MISTRIMULTI_EV_QUEUE_EVENTS
        && ev.out_bytes + count * MISTRIMULTI_EV_EVENT_BYTES <= MISTRIMULTI_EV_QUEUE_BYTES;
}

function mistrimulti_event_backlog() {
    return array_length(__mistrimulti_runtime().ev.out);
}

function mistrimulti_event_blobs_pending() {
    return array_length(__mistrimulti_runtime().ev.blobs);
}

function mistrimulti_event_requests_pending() {
    var ev = __mistrimulti_runtime().ev;
    return array_length(ev.pending_ids) + array_length(ev.local);
}

// ---- bridge tick -------------------------------------------------------------------------------------

function mistrimulti_events_receive(slot, frame) {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    var e = is_struct(frame) ? frame[$ "ev"] : undefined;
    if (slot == r.id || !__mistrimulti_ev_valid(e)) return;
    var rx = ev.rx[slot];
    // The host's abuse limits for guests (MistriMultiTrust.gml); absent elsewhere, so a guest never throttles the host.
    var gate = r[$ "trust_gate"];
    if (rx.s != e.s) {
        // A guest that keeps announcing new streams is ignored (each one re-runs every on_peer snapshot).
        if (gate != undefined && !gate(slot, undefined)) return;
        // First contact or a restarted sender: start at its oldest unacknowledged event.
        rx.s = e.s;
        rx.x = e.b;
        rx.blob = undefined;
        ev.ack_hot = r.ticks + MISTRIMULTI_EV_ACK_HOT_TICKS;
    } else if (e.b > rx.x) {
        // The sender retired events this game never received (it was away).
        var expected = rx.x;
        rx.x = e.b;
        rx.blob = undefined;
        ev.gaps++;
        ev.ack_hot = r.ticks + MISTRIMULTI_EV_ACK_HOT_TICKS;
        if (slot == 0 && r.id != 0) ev.resend = true;
        __mistrimulti_ev_notify("on_gap", slot, e.b, expected);
    }
    var q = e.q;
    for (var i = 0; i < array_length(q); i++) {
        var item = q[i];
        if (!is_struct(item) || !is_real(item[$ "s"]) || item.s != e.b + i || !is_string(item[$ "k"])) break;
        if (item.s < rx.x) continue;
        if (item.s > rx.x) break;
        // Over its rate: wait, the event stays unacknowledged and the sender keeps it queued.
        if (gate != undefined && !gate(slot, item)) {
            ev.stalls++;
            break;
        }
        if (!__mistrimulti_ev_deliver(slot, item, rx)) {
            ev.stalls++;
            break;
        }
        rx.x++;
        ev.ack_hot = r.ticks + MISTRIMULTI_EV_ACK_HOT_TICKS;
    }
}

function mistrimulti_events_tick() {
    var ev = __mistrimulti_runtime().ev;
    __mistrimulti_ev_peers();
    __mistrimulti_ev_retire();
    if (ev.resend) __mistrimulti_ev_resend_pending();
    __mistrimulti_ev_pump_local();
    __mistrimulti_ev_pump_blobs();
}

function mistrimulti_events_frame(frame) {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    var acks = array_create(8, 0);
    var streams = array_create(8, "");
    for (var i = 0; i < 8; i++) {
        var rx = ev.rx[i];
        if (rx.s != "") {
            acks[i] = rx.x - 1;
            streams[i] = rx.s;
        }
    }
    var out = { s: ev.stream, b: array_length(ev.out) > 0 ? ev.out[0].s : ev.next, q: [], a: acks, c: streams };
    frame.ev = out;
    var budget = min(MISTRIMULTI_EV_WINDOW_BYTES,
        MISTRIMULTI_EV_FRAME_LIMIT - MISTRIMULTI_EV_FRAME_MARGIN - string_byte_length(json_stringify(frame)));
    var used = 0;
    for (var j = 0; j < array_length(ev.out); j++) {
        var size = ev.sizes[j] + (j > 0 ? 1 : 0);
        if (used + size > budget) break;
        array_push(out.q, ev.out[j]);
        used += size;
    }
    return out;
}

function mistrimulti_events_encode(frame) {
    mistrimulti_events_frame(frame);
    var text = json_stringify(frame);
    while (string_byte_length(text) > MISTRIMULTI_EV_FRAME_LIMIT && array_length(frame.ev.q) > 0) {
        array_pop(frame.ev.q);
        text = json_stringify(frame);
    }
    return text;
}

// While true the helper re-sends the frame every 100 ms instead of once a second.
function mistrimulti_events_reliable() {
    var r = __mistrimulti_runtime();
    return array_length(r.ev.out) > 0 || r.ticks < r.ev.ack_hot;
}

function mistrimulti_events_debug() {
    var ev = __mistrimulti_runtime().ev;
    var acks = array_create(8, 0);
    for (var i = 0; i < 8; i++) acks[i] = ev.rx[i].x - 1;
    return { stream: ev.stream, next: ev.next, backlog: array_length(ev.out), bytes: ev.out_bytes,
        blobs: array_length(ev.blobs), requests: array_length(ev.pending_ids) + array_length(ev.local),
        errors: ev.errors, stalls: ev.stalls, gaps: ev.gaps, acks: acks };
}

// ---- internals ---------------------------------------------------------------------------------------

function __mistrimulti_ev_valid_kind(kind) {
    return is_string(kind) && string_length(kind) >= 1 && string_length(kind) <= 32 && string_char_at(kind, 1) != "~";
}

function __mistrimulti_ev_valid_target(target) {
    return is_real(target) && target == floor(target) && target >= -1 && target < 8 && target != __mistrimulti_runtime().id;
}

function __mistrimulti_ev_valid(e) {
    if (!is_struct(e)) return false;
    var s = e[$ "s"];
    var b = e[$ "b"];
    if (!is_string(s) || s == "" || string_length(s) > 64) return false;
    if (!is_real(b) || b < 1 || b != floor(b)) return false;
    if (!is_array(e[$ "q"]) || array_length(e.q) > 4096) return false;
    return is_array(e[$ "a"]) && array_length(e.a) == 8 && is_array(e[$ "c"]) && array_length(e.c) == 8;
}

function __mistrimulti_ev_live(slot) {
    var r = __mistrimulti_runtime();
    if (slot == r.id || (r.mask & (1 << slot)) == 0) return false;
    var f = r.peers[slot];
    return is_struct(f) && __mistrimulti_ev_valid(f[$ "ev"]);
}

function __mistrimulti_ev_stream_of(slot) {
    return __mistrimulti_ev_live(slot) ? __mistrimulti_runtime().peers[slot].ev.s : "";
}

function __mistrimulti_ev_push(kind, data, target, ts) {
    var ev = __mistrimulti_runtime().ev;
    var e = { s: ev.next, k: kind, d: data };
    if (target >= 0) e.t = target;
    if (ts != "") e.ts = ts;
    var text = json_stringify(e);
    var size = string_byte_length(text);
    if (size > MISTRIMULTI_EV_EVENT_BYTES) {
        __mistrimulti_ev_error("An event is too large; send it as a blob.");
        return false;
    }
    if (array_length(ev.out) >= MISTRIMULTI_EV_QUEUE_EVENTS || ev.out_bytes + size > MISTRIMULTI_EV_QUEUE_BYTES) return false;
    // Queue a parsed copy: later changes to the caller's struct must not change a sent event.
    array_push(ev.out, json_parse(text));
    array_push(ev.sizes, size);
    ev.out_bytes += size;
    ev.next++;
    return true;
}

function __mistrimulti_ev_error(text) {
    var ev = __mistrimulti_runtime().ev;
    ev.errors++;
    mmapi_warn_rate_limited("mistrimulti_events", "mistrimulti", text);
}

// A failing handler must not stall its stream forever; the event counts as handled.
function __mistrimulti_ev_invoke(fn, a, b, c) {
    try {
        return fn(a, b, c);
    } catch (e) {
        __mistrimulti_ev_error("An event handler failed: " + string(e));
        return undefined;
    }
}

function __mistrimulti_ev_notify(name, a, b, c) {
    var ev = __mistrimulti_runtime().ev;
    var kinds = struct_get_names(ev.handlers);
    for (var i = 0; i < array_length(kinds); i++) {
        var h = ev.handlers[$ kinds[i]];
        var fn = h[$ name];
        if (fn != undefined) __mistrimulti_ev_invoke(fn, a, b, c);
    }
}

function __mistrimulti_ev_deliver(sender, q, rx) {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    var t = q[$ "t"];
    if (is_real(t) && t != r.id) return true;
    var ts = q[$ "ts"];
    if (is_string(ts) && ts != ev.stream) return true;
    var d = q[$ "d"];
    if (q.k == "~q") return __mistrimulti_ev_request_in(sender, d);
    if (q.k == "~r") return __mistrimulti_ev_result_in(sender, d, is_real(t));
    if (q.k == "~b") return __mistrimulti_ev_chunk_in(sender, d, rx);
    var h = ev.handlers[$ q.k];
    var fn = is_struct(h) ? h[$ "on_event"] : undefined;
    if (fn == undefined) return true;
    var ok = __mistrimulti_ev_invoke(fn, sender, d, { kind: q.k, seq: q.s, to: is_real(t) ? t : -1 });
    return !(typeof(ok) == "bool" && !ok);
}

function __mistrimulti_ev_request_in(sender, d) {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    if (r.id != 0) return true;
    if (!is_struct(d) || !is_string(d[$ "k"]) || !is_real(d[$ "n"]) || !is_string(d[$ "i"]) || d.n < 1 || d.n != floor(d.n)) return true;
    var stream = sender == r.id ? ev.stream : ev.rx[sender].s;
    if (d.i != stream + ":" + string(d.n)) return true;
    if (!mistrimulti_event_can_emit(1)) return false;
    var ctx = { kind: d.k, id: d.i, from: sender, mine: sender == r.id, lost: false, expired: false };
    var rec = ev.req[$ stream];
    if (is_struct(rec) && d.n <= rec.high) {
        // Already applied: never apply twice, but give the requester its answer again.
        if (sender != r.id) {
            var res = { k: d.k, i: d.i, f: sender };
            var old = rec.results[$ d.i];
            if (old != undefined) res.d = old; else res.x = true;
            __mistrimulti_ev_push("~r", res, sender, stream);
        }
        return true;
    }
    var h = ev.handlers[$ d.k];
    var fn = is_struct(h) ? h[$ "on_request"] : undefined;
    var result;
    if (fn == undefined) {
        result = { ok: false, error: "unsupported" };
    } else {
        result = __mistrimulti_ev_invoke(fn, sender, d[$ "d"], ctx);
        if (typeof(result) == "bool" && !result) return false;
        if (!is_struct(result)) result = {};
    }
    if (!__mistrimulti_ev_push("~r", { k: d.k, i: d.i, f: sender, d: result }, -1, "")) {
        result = { ok: false, error: "result_too_large" };
        __mistrimulti_ev_push("~r", { k: d.k, i: d.i, f: sender, d: result }, -1, "");
    }
    __mistrimulti_ev_remember(stream, d.n, d.i, result);
    if (sender == r.id) __mistrimulti_ev_reply(h, result, ctx);
    return true;
}

// Per requester stream: the completed-request watermark (exactly-once) and its newest results.
function __mistrimulti_ev_remember(stream, n, rid, result) {
    var ev = __mistrimulti_runtime().ev;
    var rec = ev.req[$ stream];
    if (!is_struct(rec)) {
        rec = { high: 0, ids: [], sizes: [], bytes: 0, results: {} };
        ev.req[$ stream] = rec;
    } else {
        for (var i = 0; i < array_length(ev.req_order); i++) {
            if (ev.req_order[i] == stream) {
                array_delete(ev.req_order, i, 1);
                break;
            }
        }
    }
    array_push(ev.req_order, stream);
    if (array_length(ev.req_order) > MISTRIMULTI_EV_REQ_STREAMS) {
        struct_remove(ev.req, ev.req_order[0]);
        array_delete(ev.req_order, 0, 1);
    }
    var size = string_byte_length(json_stringify(result));
    rec.high = n;
    rec.results[$ rid] = result;
    array_push(rec.ids, rid);
    array_push(rec.sizes, size);
    rec.bytes += size;
    while (array_length(rec.ids) > MISTRIMULTI_EV_DONE_LIMIT || rec.bytes > MISTRIMULTI_EV_DONE_BYTES) {
        struct_remove(rec.results, rec.ids[0]);
        rec.bytes -= rec.sizes[0];
        array_delete(rec.ids, 0, 1);
        array_delete(rec.sizes, 0, 1);
    }
}

function __mistrimulti_ev_result_in(sender, d, targeted) {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    if (r.id == 0 || sender != 0) return true;
    if (!is_struct(d) || !is_string(d[$ "k"]) || !is_string(d[$ "i"]) || !is_real(d[$ "f"])) return true;
    var mine = d.f == r.id;
    if (targeted && !mine) return true;
    var ctx = { kind: d.k, id: d.i, from: d.f, mine: mine, lost: false, expired: d[$ "x"] == true };
    var h = ev.handlers[$ d.k];
    if (mine) {
        if (!struct_exists(ev.pending, d.i)) return true;
        if (ctx.expired) {
            __mistrimulti_ev_reply(h, undefined, ctx);
            __mistrimulti_ev_forget(d.i);
            return true;
        }
    }
    var fn = is_struct(h) ? h[$ "on_result"] : undefined;
    if (fn != undefined) {
        var ok = __mistrimulti_ev_invoke(fn, sender, d[$ "d"], ctx);
        if (typeof(ok) == "bool" && !ok) return false;
    }
    if (mine) {
        __mistrimulti_ev_reply(h, d[$ "d"], ctx);
        __mistrimulti_ev_forget(d.i);
    }
    return true;
}

function __mistrimulti_ev_reply(h, result, ctx) {
    var fn = is_struct(h) ? h[$ "on_reply"] : undefined;
    if (fn != undefined) __mistrimulti_ev_invoke(fn, 0, result, ctx);
}

function __mistrimulti_ev_forget(rid) {
    var ev = __mistrimulti_runtime().ev;
    struct_remove(ev.pending, rid);
    for (var i = 0; i < array_length(ev.pending_ids); i++) {
        if (ev.pending_ids[i] == rid) {
            array_delete(ev.pending_ids, i, 1);
            break;
        }
    }
}

function __mistrimulti_ev_chunk_in(sender, d, rx) {
    var ev = __mistrimulti_runtime().ev;
    if (!is_struct(d) || !is_string(d[$ "k"]) || !is_real(d[$ "i"]) || !is_real(d[$ "n"]) || !is_string(d[$ "x"])) return true;
    var b = rx.blob;
    if (d.n == 0 && !(is_struct(b) && b.i == d.i && b.done)) {
        var total = d[$ "l"];
        if (!is_real(total) || total < 0 || total > MISTRIMULTI_EV_BLOB_BYTES) {
            rx.blob = undefined;
            __mistrimulti_ev_error("A blob was rejected: bad length.");
            return true;
        }
        var m = d[$ "m"];
        b = { i: d.i, k: d.k, n: 0, bytes: 0, l: total, h: MISTRIMULTI_EV_FNV_OFFSET,
            m: is_struct(m) ? m : undefined, text: "", done: false };
        rx.blob = b;
    }
    if (!is_struct(b) || b.i != d.i || b.k != d.k) return true;
    if (!b.done) {
        if (d.n != b.n) return true;
        var size = string_byte_length(d.x);
        if (b.bytes + size > b.l) {
            rx.blob = undefined;
            __mistrimulti_ev_error("A blob was rejected: longer than announced.");
            return true;
        }
        b.bytes += size;
        b.h = __mistrimulti_ev_hash(b.h, d.x);
        b.text += d.x;
        b.n++;
        if (d[$ "e"] != true) return true;
        if (b.bytes != b.l || d[$ "h"] != b.h) {
            rx.blob = undefined;
            __mistrimulti_ev_error("A blob was rejected: integrity check failed.");
            return true;
        }
        b.done = true;
    }
    var h = ev.handlers[$ b.k];
    var fn = is_struct(h) ? h[$ "on_blob"] : undefined;
    if (fn != undefined) {
        var ok = __mistrimulti_ev_invoke(fn, sender, b.text, b.m);
        if (typeof(ok) == "bool" && !ok) return false;
    }
    rx.blob = undefined;
    return true;
}

function __mistrimulti_ev_peers() {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    for (var p = 0; p < 8; p++) {
        if (p == r.id) continue;
        var s = __mistrimulti_ev_stream_of(p);
        if (p == 0 && r.id != 0 && s != "" && s != ev.host_stream) {
            if (ev.host_stream != "") __mistrimulti_ev_fail_pending();
            ev.host_stream = s;
        }
        var old = ev.peer_stream[p];
        if (s == old) continue;
        // A stream the host's limits refused (mistrimulti_events_receive ignored it) is not announced either.
        if (s != "" && r[$ "trust_gate"] != undefined && ev.rx[p].s != s) continue;
        ev.peer_stream[p] = s;
        if (old != "") __mistrimulti_ev_notify("on_peer", p, false, old);
        if (s != "") __mistrimulti_ev_notify("on_peer", p, true, s);
    }
}

// The host restarted: it cannot know whether these requests were applied before its restart.
function __mistrimulti_ev_fail_pending() {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    var ids = ev.pending_ids;
    var pending = ev.pending;
    ev.pending_ids = [];
    ev.pending = {};
    ev.resend = false;
    for (var i = 0; i < array_length(ids); i++) {
        var p = pending[$ ids[i]];
        var ctx = { kind: p.k, id: ids[i], from: r.id, mine: true, lost: true, expired: false };
        __mistrimulti_ev_reply(ev.handlers[$ p.k], undefined, ctx);
    }
}

function __mistrimulti_ev_resend_pending() {
    var ev = __mistrimulti_runtime().ev;
    for (var i = 0; i < array_length(ev.pending_ids); i++) {
        if (!__mistrimulti_ev_push("~q", ev.pending[$ ev.pending_ids[i]], 0, ev.host_stream)) return;
    }
    ev.resend = false;
}

function __mistrimulti_ev_retire() {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    if (array_length(ev.out) == 0) return;
    var acked = ev.next - 1;
    for (var p = 0; p < 8; p++) {
        if (p == r.id || !(__mistrimulti_ev_live(p) || (p == 0 && r.id != 0))) continue;
        var f = r.peers[p];
        var e = is_struct(f) ? f[$ "ev"] : undefined;
        if (!__mistrimulti_ev_valid(e) || !is_string(e.c[r.id]) || e.c[r.id] != ev.stream || !is_real(e.a[r.id])) return;
        acked = min(acked, e.a[r.id]);
    }
    var count = 0;
    while (count < array_length(ev.out) && ev.out[count].s <= acked) {
        ev.out_bytes -= ev.sizes[count];
        count++;
    }
    if (count > 0) {
        array_delete(ev.out, 0, count);
        array_delete(ev.sizes, 0, count);
    }
}

function __mistrimulti_ev_pump_local() {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    while (array_length(ev.local) > 0) {
        if (!__mistrimulti_ev_request_in(r.id, ev.local[0])) return;
        array_delete(ev.local, 0, 1);
    }
}

// FNV-1a over UTF-8 bytes, continued from h. h * 16777619 == (h << 24) + h * 403 keeps doubles exact.
function __mistrimulti_ev_hash(h, text) {
    var size = string_byte_length(text);
    if (size == 0) return h;
    var buf = buffer_create(size, buffer_fixed, 1);
    buffer_write(buf, buffer_text, text);
    buffer_seek(buf, buffer_seek_start, 0);
    for (var i = 0; i < size; i++) {
        h = h ^ buffer_read(buf, buffer_u8);
        h = (((h << 24) & 0xFFFFFFFF) + h * 403) & 0xFFFFFFFF;
    }
    buffer_delete(buf);
    return h;
}

function __mistrimulti_ev_pump_blobs() {
    var r = __mistrimulti_runtime();
    var ev = r.ev;
    while (array_length(ev.blobs) > 0) {
        var job = ev.blobs[0];
        if (job.t >= 0 && ((r.mask & (1 << job.t)) == 0 || (job.ts != "" && __mistrimulti_ev_stream_of(job.t) != job.ts))) {
            array_delete(ev.blobs, 0, 1);
            continue;
        }
        if (ev.out_bytes >= MISTRIMULTI_EV_WINDOW_BYTES * 2 || !mistrimulti_event_can_emit(1)) return;
        var chars = MISTRIMULTI_EV_CHUNK_CHARS;
        var part = string_copy(job.text, job.pos, chars);
        while (string_byte_length(json_stringify({ x: part })) > MISTRIMULTI_EV_CHUNK_BYTES && chars > 16) {
            chars = chars div 2;
            part = string_copy(job.text, job.pos, chars);
        }
        var count = string_length(part);
        var last = job.pos + count > job.len;
        var d = { k: job.k, i: job.i, n: job.n, x: part };
        if (job.n == 0) {
            d.l = job.l;
            if (job.m != undefined) d.m = job.m;
        }
        var h = __mistrimulti_ev_hash(job.h, part);
        if (last) {
            d.e = true;
            d.h = h;
        }
        if (!__mistrimulti_ev_push("~b", d, job.t, job.ts)) {
            array_delete(ev.blobs, 0, 1);
            __mistrimulti_ev_error("A blob chunk was rejected.");
            continue;
        }
        job.h = h;
        job.pos += count;
        job.n++;
        if (last) array_delete(ev.blobs, 0, 1);
    }
}
