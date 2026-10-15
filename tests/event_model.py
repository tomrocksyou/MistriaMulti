"""Reference model of the MistriaMulti event layer.

This is the executable specification of mod/mistrimulti/gml/MistriMultiEvents.gml. Every method mirrors
one GML function, in the same order and with the same control flow:

    GML  mistrimulti_event_x / mistrimulti_events_x   <->  Python method of the same name
    GML  __mistrimulti_ev_x  (internal)               <->  Python method _ev_x

GML structs are modelled by `Struct` (attribute access) for local state and by plain dicts for JSON that
crossed the bridge (GML `value[$ "key"]` <-> `value.get("key")`). GML `undefined` is Python `None`.
Python is only a developer test tool; players run the GML and the native helpers.
"""
import json
import math

MAX_PLAYERS = 8
FRAME_LIMIT = 16384       # the helper's snapshot limit (JSON bytes after the two-byte prefix)
FRAME_MARGIN = 256        # head room for number formatting differences
WINDOW_BYTES = 12288      # at most this many event bytes ride in one frame
EVENT_BYTES = 8192        # largest encoded event; larger payloads use blobs
QUEUE_EVENTS = 512        # unacknowledged events kept by one sender
QUEUE_BYTES = 524288      # and their encoded bytes
BLOB_BYTES = 262144       # largest blob (UTF-8 bytes)
BLOB_JOBS = 8             # outgoing blobs waiting to be chunked
BLOB_META_BYTES = 2048    # encoded size of a blob's meta struct
CHUNK_CHARS = 2048        # first chunk size tried, in characters
CHUNK_BYTES = 6144        # largest encoded chunk text
PENDING_LIMIT = 64        # outstanding requests (guest) or queued local requests (host)
DONE_LIMIT = 64           # results the host keeps per requester stream, to answer a resend after a reconnect
DONE_BYTES = 65536        # and their encoded bytes per requester stream
REQ_STREAMS = 16          # requester streams the host remembers (least recently active forgotten first)
ACK_HOT_TICKS = 90        # game frames a changed ACK keeps the frame on the 100 ms resend timer
FNV_OFFSET = 2166136261


class Struct:
    """A GML struct: attribute access, missing attributes are an error (as in GML)."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def get(self, name, default=None):
        return self.__dict__.get(name, default)

    def __repr__(self):
        return "Struct(" + ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items()) + ")"


class Runtime:
    """The fields of global.__mistrimulti that the event layer reads."""

    def __init__(self, slot, epoch, mode=None):
        self.id = slot
        self.mode = mode or ("host" if slot == 0 else "join")
        self.epoch = epoch
        self.mask = 0
        self.peers = [None] * MAX_PLAYERS
        self.ticks = 0
        self.ev = None


def stringify(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def byte_length(text):
    return len(text.encode("utf-8"))


def is_real(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def gml_string(value):
    """GML string() of a number: integers print without decimals."""
    if is_real(value) and value == math.floor(value):
        return str(int(value))
    return f"{value:.2f}"


def fnv(h, text):
    """FNV-1a over UTF-8 bytes, continued from h. h * 16777619 == (h << 24) + h * 403 keeps GML doubles exact."""
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (((h << 24) & 0xFFFFFFFF) + h * 403) & 0xFFFFFFFF
    return h


class EventLayer:
    def __init__(self, runtime, timer, log=None):
        self.r = runtime
        self.timer = timer
        self.log = log or (lambda key, text: None)

    # ---- lifecycle -------------------------------------------------------------------------------------

    def mistrimulti_events_initialize(self):
        if self.r.ev is None:
            self.r.ev = Struct(handlers={})
        self.mistrimulti_events_reset()

    def mistrimulti_events_reset(self):
        r = self.r
        ev = r.ev
        ev.stream = gml_string(r.id) + "-" + r.epoch[:8] + "-" + gml_string(self.timer())
        ev.next = 1
        ev.out = []
        ev.sizes = []
        ev.out_bytes = 0
        ev.rx = [Struct(s="", x=0, blob=None) for _ in range(MAX_PLAYERS)]
        ev.peer_stream = [""] * MAX_PLAYERS
        ev.host_stream = ""
        ev.blobs = []
        ev.next_blob = 1
        ev.pending = {}
        ev.pending_ids = []
        ev.next_request = 1
        ev.resend = False
        ev.local = []
        ev.req = {}
        ev.req_order = []
        ev.ack_hot = 0
        ev.errors = 0
        ev.stalls = 0
        ev.gaps = 0

    def mistrimulti_event_register(self, kind, handlers):
        if self.r.ev is None:
            self.mistrimulti_events_initialize()
        if not self._ev_valid_kind(kind) or not isinstance(handlers, Struct):
            return False
        self.r.ev.handlers[kind] = handlers
        return True

    # ---- sending ---------------------------------------------------------------------------------------

    def mistrimulti_event_emit(self, kind, data, target=-1):
        r = self.r
        if not self._ev_valid_kind(kind) or not self._ev_valid_target(target):
            return False
        return self._ev_push(kind, data, target, self._ev_stream_of(target) if target >= 0 else "")

    def mistrimulti_event_request(self, kind, data):
        r = self.r
        ev = r.ev
        if not self._ev_valid_kind(kind) or ev.resend:
            return None
        n = ev.next_request
        rid = ev.stream + ":" + gml_string(n)
        d = {"k": kind, "n": n, "i": rid, "d": data}
        if r.id == 0:
            if len(ev.local) >= PENDING_LIMIT:
                return None
            ev.local.append(json.loads(stringify(d)))
        else:
            if len(ev.pending_ids) >= PENDING_LIMIT:
                return None
            # A request is bound to the host session it is made in. Until this guest has seen the host's stream it
            # could not say which session that is, and a request without it would also be applied by a later host
            # session (exactly-once across a host restart).
            host = self._ev_stream_of(0)
            if host == "" or host != ev.host_stream:
                return None
            if not self._ev_push("~q", d, 0, host):
                return None
            ev.pending[rid] = json.loads(stringify(d))
            ev.pending_ids.append(rid)
        ev.next_request += 1
        return rid

    def mistrimulti_event_send_blob(self, kind, text, target=-1, meta=None):
        r = self.r
        ev = r.ev
        if not self._ev_valid_kind(kind) or not isinstance(text, str) or not self._ev_valid_target(target):
            return False
        if meta is not None and (not isinstance(meta, dict) or byte_length(stringify(meta)) > BLOB_META_BYTES):
            return False
        size = byte_length(text)
        if size > BLOB_BYTES or len(ev.blobs) >= BLOB_JOBS:
            return False
        ev.blobs.append(Struct(i=ev.next_blob, k=kind, t=target, ts=self._ev_stream_of(target) if target >= 0 else "",
                               m=None if meta is None else json.loads(stringify(meta)),
                               text=text, len=len(text), l=size, pos=1, n=0, h=FNV_OFFSET))
        ev.next_blob += 1
        return True

    def mistrimulti_event_can_emit(self, count):
        ev = self.r.ev
        return len(ev.out) + count <= QUEUE_EVENTS and ev.out_bytes + count * EVENT_BYTES <= QUEUE_BYTES

    def mistrimulti_event_backlog(self):
        return len(self.r.ev.out)

    def mistrimulti_event_blobs_pending(self):
        return len(self.r.ev.blobs)

    def mistrimulti_event_requests_pending(self):
        ev = self.r.ev
        return len(ev.pending_ids) + len(ev.local)

    # ---- bridge tick -----------------------------------------------------------------------------------

    def mistrimulti_events_receive(self, slot, frame):
        r = self.r
        ev = r.ev
        e = frame.get("ev") if isinstance(frame, dict) else None
        if slot == r.id or not self._ev_valid(e):
            return
        rx = ev.rx[slot]
        if rx.s != e["s"]:
            # First contact or a restarted sender: start at its oldest unacknowledged event.
            rx.s = e["s"]
            rx.x = e["b"]
            rx.blob = None
            ev.ack_hot = r.ticks + ACK_HOT_TICKS
        elif e["b"] > rx.x:
            # The sender retired events this node never received (it was away).
            expected = rx.x
            rx.x = e["b"]
            rx.blob = None
            ev.gaps += 1
            ev.ack_hot = r.ticks + ACK_HOT_TICKS
            if slot == 0 and r.id != 0:
                ev.resend = True
            self._ev_notify("on_gap", slot, e["b"], expected)
        q = e["q"]
        for i in range(len(q)):
            item = q[i]
            if not isinstance(item, dict) or not is_real(item.get("s")) or item["s"] != e["b"] + i \
                    or not isinstance(item.get("k"), str):
                break
            if item["s"] < rx.x:
                continue
            if item["s"] > rx.x:
                break
            if not self._ev_deliver(slot, item, rx):
                ev.stalls += 1
                break
            rx.x += 1
            ev.ack_hot = r.ticks + ACK_HOT_TICKS

    def mistrimulti_events_tick(self):
        ev = self.r.ev
        self._ev_peers()
        self._ev_retire()
        if ev.resend:
            self._ev_resend_pending()
        self._ev_pump_local()
        self._ev_pump_blobs()

    def mistrimulti_events_frame(self, frame):
        r = self.r
        ev = r.ev
        acks = [0] * MAX_PLAYERS
        streams = [""] * MAX_PLAYERS
        for i in range(MAX_PLAYERS):
            rx = ev.rx[i]
            if rx.s != "":
                acks[i] = rx.x - 1
                streams[i] = rx.s
        out = {"s": ev.stream, "b": ev.out[0]["s"] if len(ev.out) > 0 else ev.next, "q": [], "a": acks, "c": streams}
        frame["ev"] = out
        budget = min(WINDOW_BYTES, FRAME_LIMIT - FRAME_MARGIN - byte_length(stringify(frame)))
        used = 0
        for i in range(len(ev.out)):
            size = ev.sizes[i] + (1 if i > 0 else 0)
            if used + size > budget:
                break
            out["q"].append(ev.out[i])
            used += size
        return out

    def mistrimulti_events_encode(self, frame):
        self.mistrimulti_events_frame(frame)
        text = stringify(frame)
        while byte_length(text) > FRAME_LIMIT and len(frame["ev"]["q"]) > 0:
            frame["ev"]["q"].pop()
            text = stringify(frame)
        return text

    def mistrimulti_events_reliable(self):
        ev = self.r.ev
        return len(ev.out) > 0 or self.r.ticks < ev.ack_hot

    def mistrimulti_events_debug(self):
        ev = self.r.ev
        return {"stream": ev.stream, "next": ev.next, "backlog": len(ev.out), "bytes": ev.out_bytes,
                "blobs": len(ev.blobs), "requests": len(ev.pending_ids) + len(ev.local), "errors": ev.errors,
                "stalls": ev.stalls, "gaps": ev.gaps, "acks": [rx.x - 1 for rx in ev.rx]}

    # ---- internals -------------------------------------------------------------------------------------

    def _ev_valid_kind(self, kind):
        return isinstance(kind, str) and 1 <= len(kind) <= 32 and kind[0] != "~"

    def _ev_valid_target(self, target):
        return is_real(target) and target == math.floor(target) and -1 <= target < MAX_PLAYERS and target != self.r.id

    def _ev_valid(self, e):
        if not isinstance(e, dict):
            return False
        s, b, q, a, c = e.get("s"), e.get("b"), e.get("q"), e.get("a"), e.get("c")
        if not isinstance(s, str) or s == "" or len(s) > 64:
            return False
        if not is_real(b) or b < 1 or b != math.floor(b):
            return False
        if not isinstance(q, list) or len(q) > 4096:
            return False
        return isinstance(a, list) and len(a) == MAX_PLAYERS and isinstance(c, list) and len(c) == MAX_PLAYERS

    def _ev_live(self, slot):
        r = self.r
        if slot == r.id or (r.mask & (1 << slot)) == 0:
            return False
        f = r.peers[slot]
        return isinstance(f, dict) and self._ev_valid(f.get("ev"))

    def _ev_stream_of(self, slot):
        return self.r.peers[slot]["ev"]["s"] if self._ev_live(slot) else ""

    def _ev_push(self, kind, data, target, ts):
        ev = self.r.ev
        e = {"s": ev.next, "k": kind, "d": data}
        if target >= 0:
            e["t"] = target
        if ts != "":
            e["ts"] = ts
        text = stringify(e)
        size = byte_length(text)
        if size > EVENT_BYTES:
            self._ev_error("An event is too large; send it as a blob.")
            return False
        if len(ev.out) >= QUEUE_EVENTS or ev.out_bytes + size > QUEUE_BYTES:
            return False
        ev.out.append(json.loads(text))
        ev.sizes.append(size)
        ev.out_bytes += size
        ev.next += 1
        return True

    def _ev_error(self, text):
        self.r.ev.errors += 1
        self.log("mistrimulti_events", text)

    def _ev_invoke(self, fn, a, b, c):
        try:
            return fn(a, b, c)
        except Exception as error:  # a broken handler must not stall the stream
            self._ev_error("An event handler failed: " + str(error))
            return None

    def _ev_notify(self, name, a, b, c):
        ev = self.r.ev
        for kind in list(ev.handlers):
            fn = ev.handlers[kind].get(name)
            if fn is not None:
                self._ev_invoke(fn, a, b, c)

    def _ev_deliver(self, sender, q, rx):
        r = self.r
        ev = r.ev
        t = q.get("t")
        if is_real(t) and t != r.id:
            return True
        ts = q.get("ts")
        if isinstance(ts, str) and ts != ev.stream:
            return True
        d = q.get("d")
        if q["k"] == "~q":
            return self._ev_request_in(sender, d)
        if q["k"] == "~r":
            return self._ev_result_in(sender, d, is_real(t))
        if q["k"] == "~b":
            return self._ev_chunk_in(sender, d, rx)
        h = ev.handlers.get(q["k"])
        fn = h.get("on_event") if h is not None else None
        if fn is None:
            return True
        ok = self._ev_invoke(fn, sender, d, {"kind": q["k"], "seq": q["s"], "to": t if is_real(t) else -1})
        return not (isinstance(ok, bool) and not ok)

    def _ev_request_in(self, sender, d):
        r = self.r
        ev = r.ev
        if r.id != 0:
            return True
        if not isinstance(d, dict) or not isinstance(d.get("k"), str) or not is_real(d.get("n")) \
                or not isinstance(d.get("i"), str) or d["n"] < 1 or d["n"] != math.floor(d["n"]):
            return True
        stream = ev.stream if sender == r.id else ev.rx[sender].s
        if d["i"] != stream + ":" + gml_string(d["n"]):
            return True
        if not self.mistrimulti_event_can_emit(1):
            return False
        ctx = {"kind": d["k"], "id": d["i"], "from": sender, "mine": sender == r.id, "lost": False, "expired": False}
        rec = ev.req.get(stream)
        if rec is not None and d["n"] <= rec.high:
            # Already applied: never apply twice, but give the requester its answer again.
            if sender != r.id:
                res = {"k": d["k"], "i": d["i"], "f": sender}
                old = rec.results.get(d["i"])
                if old is not None:
                    res["d"] = old
                else:
                    res["x"] = True
                self._ev_push("~r", res, sender, stream)
            return True
        h = ev.handlers.get(d["k"])
        fn = h.get("on_request") if h is not None else None
        if fn is None:
            result = {"ok": False, "error": "unsupported"}
        else:
            result = self._ev_invoke(fn, sender, d.get("d"), ctx)
            if isinstance(result, bool) and not result:
                return False
            if not isinstance(result, dict):
                result = {}
        if not self._ev_push("~r", {"k": d["k"], "i": d["i"], "f": sender, "d": result}, -1, ""):
            result = {"ok": False, "error": "result_too_large"}
            self._ev_push("~r", {"k": d["k"], "i": d["i"], "f": sender, "d": result}, -1, "")
        self._ev_remember(stream, d["n"], d["i"], result)
        if sender == r.id:
            self._ev_reply(h, result, ctx)
        return True

    def _ev_remember(self, stream, n, rid, result):
        # Per requester stream: the completed-request watermark (exactly-once) and its newest results.
        ev = self.r.ev
        rec = ev.req.get(stream)
        if rec is None:
            rec = Struct(high=0, ids=[], sizes=[], bytes=0, results={})
            ev.req[stream] = rec
        else:
            ev.req_order.remove(stream)
        ev.req_order.append(stream)
        if len(ev.req_order) > REQ_STREAMS:
            del ev.req[ev.req_order[0]]
            del ev.req_order[0]
        size = byte_length(stringify(result))
        rec.high = n
        rec.results[rid] = result
        rec.ids.append(rid)
        rec.sizes.append(size)
        rec.bytes += size
        while len(rec.ids) > DONE_LIMIT or rec.bytes > DONE_BYTES:
            del rec.results[rec.ids[0]]
            rec.bytes -= rec.sizes[0]
            del rec.ids[0]
            del rec.sizes[0]

    def _ev_result_in(self, sender, d, targeted):
        r = self.r
        ev = r.ev
        if r.id == 0 or sender != 0:
            return True
        if not isinstance(d, dict) or not isinstance(d.get("k"), str) or not isinstance(d.get("i"), str) \
                or not is_real(d.get("f")):
            return True
        mine = d["f"] == r.id
        if targeted and not mine:
            return True
        ctx = {"kind": d["k"], "id": d["i"], "from": d["f"], "mine": mine, "lost": False, "expired": d.get("x") == True}  # noqa: E712 (GML ==)
        h = ev.handlers.get(d["k"])
        if mine:
            if d["i"] not in ev.pending:
                return True
            if ctx["expired"]:
                self._ev_reply(h, None, ctx)
                self._ev_forget(d["i"])
                return True
        fn = h.get("on_result") if h is not None else None
        if fn is not None:
            ok = self._ev_invoke(fn, sender, d.get("d"), ctx)
            if isinstance(ok, bool) and not ok:
                return False
        if mine:
            self._ev_reply(h, d.get("d"), ctx)
            self._ev_forget(d["i"])
        return True

    def _ev_reply(self, h, result, ctx):
        fn = h.get("on_reply") if h is not None else None
        if fn is not None:
            self._ev_invoke(fn, 0, result, ctx)

    def _ev_forget(self, rid):
        ev = self.r.ev
        del ev.pending[rid]
        ev.pending_ids.remove(rid)

    def _ev_chunk_in(self, sender, d, rx):
        ev = self.r.ev
        if not isinstance(d, dict) or not isinstance(d.get("k"), str) or not is_real(d.get("i")) \
                or not is_real(d.get("n")) or not isinstance(d.get("x"), str):
            return True
        b = rx.blob
        if d["n"] == 0 and not (b is not None and b.i == d["i"] and b.done):
            total = d.get("l")
            if not is_real(total) or total < 0 or total > BLOB_BYTES:
                rx.blob = None
                self._ev_error("A blob was rejected: bad length.")
                return True
            m = d.get("m")
            b = Struct(i=d["i"], k=d["k"], n=0, bytes=0, l=total, h=FNV_OFFSET,
                       m=m if isinstance(m, dict) else None, text="", done=False)
            rx.blob = b
        if b is None or b.i != d["i"] or b.k != d["k"]:
            return True
        if not b.done:
            if d["n"] != b.n:
                return True
            size = byte_length(d["x"])
            if b.bytes + size > b.l:
                rx.blob = None
                self._ev_error("A blob was rejected: longer than announced.")
                return True
            b.bytes += size
            b.h = self._ev_hash(b.h, d["x"])
            b.text += d["x"]
            b.n += 1
            if d.get("e") != True:  # noqa: E712 (GML !=)
                return True
            if b.bytes != b.l or d.get("h") != b.h:
                rx.blob = None
                self._ev_error("A blob was rejected: integrity check failed.")
                return True
            b.done = True
        h = ev.handlers.get(b.k)
        fn = h.get("on_blob") if h is not None else None
        if fn is not None:
            ok = self._ev_invoke(fn, sender, b.text, b.m)
            if isinstance(ok, bool) and not ok:
                return False
        rx.blob = None
        return True

    def _ev_peers(self):
        r = self.r
        ev = r.ev
        for p in range(MAX_PLAYERS):
            if p == r.id:
                continue
            s = self._ev_stream_of(p)
            if p == 0 and r.id != 0 and s != "" and s != ev.host_stream:
                if ev.host_stream != "":
                    self._ev_fail_pending()
                ev.host_stream = s
            old = ev.peer_stream[p]
            if s == old:
                continue
            ev.peer_stream[p] = s
            if old != "":
                self._ev_notify("on_peer", p, False, old)
            if s != "":
                self._ev_notify("on_peer", p, True, s)

    def _ev_fail_pending(self):
        # The host restarted: it cannot know whether these were applied before its restart.
        ev = self.r.ev
        ids = ev.pending_ids
        pending = ev.pending
        ev.pending_ids = []
        ev.pending = {}
        ev.resend = False
        for rid in ids:
            p = pending[rid]
            ctx = {"kind": p["k"], "id": rid, "from": self.r.id, "mine": True, "lost": True, "expired": False}
            self._ev_reply(ev.handlers.get(p["k"]), None, ctx)

    def _ev_resend_pending(self):
        ev = self.r.ev
        for rid in ev.pending_ids:
            if not self._ev_push("~q", ev.pending[rid], 0, ev.host_stream):
                return
        ev.resend = False

    def _ev_retire(self):
        r = self.r
        ev = r.ev
        if len(ev.out) == 0:
            return
        acked = ev.next - 1
        for p in range(MAX_PLAYERS):
            if p == r.id or not (self._ev_live(p) or (p == 0 and r.id != 0)):
                continue
            f = r.peers[p]
            e = f.get("ev") if isinstance(f, dict) else None
            if not self._ev_valid(e) or not isinstance(e["c"][r.id], str) or e["c"][r.id] != ev.stream \
                    or not is_real(e["a"][r.id]):
                return
            acked = min(acked, e["a"][r.id])
        count = 0
        while count < len(ev.out) and ev.out[count]["s"] <= acked:
            ev.out_bytes -= ev.sizes[count]
            count += 1
        if count > 0:
            del ev.out[:count]
            del ev.sizes[:count]

    def _ev_pump_local(self):
        ev = self.r.ev
        while len(ev.local) > 0:
            if not self._ev_request_in(self.r.id, ev.local[0]):
                return
            del ev.local[0]

    def _ev_hash(self, h, text):
        return fnv(h, text)

    def _ev_pump_blobs(self):
        r = self.r
        ev = r.ev
        while len(ev.blobs) > 0:
            job = ev.blobs[0]
            if job.t >= 0 and ((r.mask & (1 << job.t)) == 0 or (job.ts != "" and self._ev_stream_of(job.t) != job.ts)):
                del ev.blobs[0]
                continue
            if ev.out_bytes >= WINDOW_BYTES * 2 or not self.mistrimulti_event_can_emit(1):
                return
            chars = CHUNK_CHARS
            part = job.text[job.pos - 1:job.pos - 1 + chars]
            while byte_length(stringify({"x": part})) > CHUNK_BYTES and chars > 16:
                chars //= 2
                part = job.text[job.pos - 1:job.pos - 1 + chars]
            count = len(part)
            last = job.pos + count > job.len
            d = {"k": job.k, "i": job.i, "n": job.n, "x": part}
            if job.n == 0:
                d["l"] = job.l
                if job.m is not None:
                    d["m"] = job.m
            h = self._ev_hash(job.h, part)
            if last:
                d["e"] = True
                d["h"] = h
            if not self._ev_push("~b", d, job.t, job.ts):
                del ev.blobs[0]
                self._ev_error("A blob chunk was rejected.")
                continue
            job.h = h
            job.pos += count
            job.n += 1
            if last:
                del ev.blobs[0]
