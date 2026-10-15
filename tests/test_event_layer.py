"""Event-layer protocol tests: Python reference model and the GML source, under simulated faults.

    python3 tests/test_event_layer.py            # everything (a few minutes; the GML runs are interpreted)
    python3 tests/test_event_layer.py --quick    # the Python model only

Every scenario runs against the reference model (tests/event_model.py). The same scenarios then run with
mod/mistrimulti/gml/MistriMultiEvents.gml executed by tests/gml_subset.py, and with a mix of both (proving
that the two speak the same wire format). Python is a developer test tool, not a runtime dependency.
"""
import argparse
import hashlib
import json
import re
import sys
import time

import event_model as model
from event_sim import EVENTS_GML, GmlNode, ModelNode, World, random_text
import gml_subset as gml

GAP = "gap"
JOIN_MS = 3000   # a new stream becomes a participant within the 1 s mask refresh plus a frame round trip


class Ledger:
    """Everything every feature instance sent, applied and received, for the end-of-run checks."""

    def __init__(self):
        self.pings_sent = {}       # sender stream -> [(n, target slot, target stream)]
        self.pings_seen = {}       # (receiver stream, sender stream) -> [n | (GAP, sent count)]
        self.ping_times = {}       # sender stream -> [simulated ms of each ping]
        self.requests = {}         # request id -> {"stream", "add"}
        self.applied = {}          # request id -> times applied by any host instance
        self.replies = {}          # request id -> [reply kinds]
        self.blobs_sent = {}       # blob key -> {"sha", "target", "stream", "slot"}
        self.blobs_seen = {}       # (receiver stream, blob key) -> count
        self.peer_events = []      # (receiver slot, peer slot, joined)
        self.joined_at = {}        # (sender stream, peer stream) -> clock ms when the sender last saw that peer join
        self.born = {}             # stream -> simulated ms when its feature first ran
        self.wrong = []            # misdeliveries


class Feature:
    """A synced test feature exercising every part of the public API, written like a real one would be."""

    def __init__(self, game, ledger, rng, plan):
        self.game, self.ledger, self.rng, self.plan = game, ledger, rng, plan
        node = game.node
        self.slot = game.slot
        self.n = 0
        self.total = 0           # host: authoritative counter; guests: the last broadcast result
        self.defer = plan.get("defer", 0.0)
        self.stall_until = 0
        self.refused = 0
        self.blob_count = 0
        self.last_stream = ""
        assert node.call("mistrimulti_event_register", "ping", node.handlers(on_event=self.on_ping, on_peer=self.on_peer,
                                                                             on_gap=self.on_gap))
        assert node.call("mistrimulti_event_register", "count", node.handlers(on_request=self.on_count,
                                                                              on_result=self.on_total, on_reply=self.on_reply))
        assert node.call("mistrimulti_event_register", "file", node.handlers(on_blob=self.on_file))
        assert not node.call("mistrimulti_event_register", "~bad", node.handlers())

    def stream(self):
        return self.game.node.call("mistrimulti_events_debug")["stream"]

    def peer_stream(self, slot):
        node = self.game.node
        if (node.mask & (1 << slot)) == 0:
            return ""
        cached = self.game.parsed.get(slot)
        ev = cached[1].get("ev") if cached else None
        return ev.get("s", "") if isinstance(ev, dict) else ""

    # -- handlers ----------------------------------------------------------------------------------------
    def on_ping(self, sender, data, ctx):
        if self.game.world.clock.ms < self.stall_until:
            return False
        if ctx["to"] not in (-1, self.slot):
            self.ledger.wrong.append(("ping to", ctx["to"], self.slot))
        key = (self.stream(), data["s"])
        self.ledger.pings_seen.setdefault(key, []).append(data["n"])
        return True

    def on_gap(self, slot, base, expected):
        stream = self.peer_stream(slot) or (self.game.parsed.get(slot) or (0, {}))[1].get("ev", {}).get("s", "")
        # Everything the sender emits from now on must arrive; older events may have been retired.
        self.ledger.pings_seen.setdefault((self.stream(), stream), []).append((GAP, len(self.ledger.pings_sent.get(stream, []))))

    def on_peer(self, slot, joined, stream):
        self.ledger.peer_events.append((self.slot, slot, joined))
        if joined:
            self.ledger.joined_at[(self.stream(), stream)] = self.game.world.clock.ms

    def on_count(self, sender, data, ctx):
        assert self.slot == 0, "on_request ran on a guest"
        if self.rng.random() < self.defer:
            return False
        if not isinstance(data, dict) or not isinstance(data.get("add"), int):
            return {"ok": False}
        self.ledger.applied[ctx["id"]] = self.ledger.applied.get(ctx["id"], 0) + 1
        self.total += data["add"]
        return {"ok": True, "total": self.total, "host": self.stream()}

    def on_total(self, sender, result, ctx):
        assert self.slot != 0 and sender == 0
        if result.get("ok"):
            self.total = result["total"]
        return True

    def on_reply(self, sender, result, ctx):
        if ctx["lost"]:
            kind = "lost"
        elif ctx["expired"]:
            kind = "expired"
        else:
            kind = "ok" if result.get("ok") else "rejected"
        self.ledger.replies.setdefault(ctx["id"], []).append(kind)

    def on_file(self, sender, text, meta):
        if hashlib.sha256(text.encode()).hexdigest() != meta["sha"]:
            self.ledger.wrong.append(("blob content", meta["key"]))
        if meta["target"] not in (-1, self.slot):
            self.ledger.wrong.append(("blob target", meta["key"], self.slot))
        key = (self.stream(), meta["key"])
        self.ledger.blobs_seen[key] = self.ledger.blobs_seen.get(key, 0) + 1
        return True

    # -- traffic -----------------------------------------------------------------------------------------
    def ping(self, target=-1):
        node = self.game.node
        target_stream = self.peer_stream(target) if target >= 0 else ""
        if target >= 0 and target_stream == "":
            return
        data = {"s": self.stream(), "n": self.n + 1, "pad": "p" * self.rng.randint(0, self.plan.get("pad", 64))}
        if node.call("mistrimulti_event_emit", "ping", data, target):
            self.n += 1
            self.ledger.pings_sent.setdefault(data["s"], []).append((self.n, target, target_stream))
            self.ledger.ping_times.setdefault(data["s"], []).append(self.game.world.clock.ms)
        else:
            self.refused += 1

    def tick(self, now):
        stream = self.stream()
        if stream != self.last_stream:
            self.ledger.born[stream] = now
            self.last_stream = stream
        if not self.plan.get("traffic", True) or now > self.plan.get("until", 1 << 60):
            return
        rng = self.rng
        for _ in range(rng.randint(0, self.plan.get("pings", 3))):
            target = rng.randrange(8) if rng.random() < 0.3 else -1
            if target != self.slot:
                self.ping(target)
        if rng.random() < self.plan.get("requests", 0.2):
            self.request(rng.randint(1, 9))
        if self.blob_count < self.plan.get("blobs", 0) and rng.random() < 0.05:
            self.blob(rng.randint(0, self.plan.get("blob_size", 30000)), rng.choice([-1, -1, 0, 1, 2, 3]))

    def request(self, add):
        node = self.game.node
        rid = node.call("mistrimulti_event_request", "count", {"add": add})
        if rid is not None:
            self.ledger.requests[rid] = {"stream": self.stream(), "add": add, "slot": self.slot}
        return rid

    def blob(self, size, target):
        node = self.game.node
        if target == self.slot or (target >= 0 and self.peer_stream(target) == ""):
            return False
        text = random_text(self.rng, size)
        key = f"{self.stream()}#{self.blob_count}"
        sha = hashlib.sha256(text.encode()).hexdigest()
        if node.call("mistrimulti_event_send_blob", "file", text, target, {"key": key, "sha": sha, "target": target}):
            self.blob_count += 1
            self.ledger.blobs_sent[key] = {"target": target, "stream": self.stream(), "slot": self.slot,
                                           "at": self.game.world.clock.ms,
                                           "target_stream": self.peer_stream(target) if target >= 0 else ""}
            return True
        return False


def attach(world, ledger, plans):
    for slot, game in world.games.items():
        if game.feature is None:
            game.feature = Feature(game, ledger, world.rng, plans.get(slot, plans.get("all", {})))


# ---- checks ---------------------------------------------------------------------------------------------

def current_streams(world):
    return {game.slot: game.feature.stream() for game in world.games.values()}


def check_pings(world, ledger, complete=True):
    """In order, no duplicates, nothing skipped except across a reported gap or before a late join."""
    live = current_streams(world)
    live_by_stream = {s: slot for slot, s in live.items()}
    checked = 0
    for (receiver, sender), seen in ledger.pings_seen.items():
        if sender not in ledger.pings_sent:
            continue
        rslot = int(receiver.split("-")[0])
        relevant = [n for n, t, ts in ledger.pings_sent[sender] if t == -1 or (t == rslot and ts == receiver)]
        position = {n: i for i, n in enumerate(relevant)}
        segments = [[]]
        after_gap = 0
        for item in seen:
            if isinstance(item, tuple):
                segments.append([])
                after_gap = item[1]
            else:
                assert item in position, f"{receiver} got ping {item} from {sender} that was not meant for it"
                segments[-1].append(position[item])
        flat = [p for seg in segments for p in seg]
        assert flat == sorted(set(flat)), f"{receiver} saw duplicates or reordering from {sender}"
        for seg in segments:
            assert seg == list(range(seg[0], seg[0] + len(seg))) if seg else True, \
                f"{receiver} skipped pings from {sender} without a gap"
        if complete and receiver in live_by_stream and sender in live_by_stream:
            if after_gap:
                got = set(flat)
                missing = [i for i, n in enumerate(relevant) if n > after_gap and i not in got]
                assert not missing, f"{receiver} is missing {len(missing)} pings from {sender} sent after its last gap"
            else:   # first contact: it may start late, but must then be complete
                assert flat and flat[-1] == len(relevant) - 1, f"{receiver} is missing the last pings from {sender}"
        checked += 1
    # Every pair of live, connected streams exchanged pings (if any were sent after the receiver joined).
    if complete:
        for rslot, rs in live.items():
            for sslot, ss in live.items():
                late = [t for t in ledger.ping_times.get(ss, []) if t >= ledger.born.get(rs, 0) + JOIN_MS]
                if rslot != sslot and late:
                    assert (rs, ss) in ledger.pings_seen, f"{rs} never heard from {ss}"
    return checked


def check_requests(world, ledger, allow_lost=False, complete=True):
    live = set(current_streams(world).values())
    for rid, count in ledger.applied.items():
        assert count == 1, f"request {rid} applied {count} times"
    for rid, info in ledger.requests.items():
        replies = ledger.replies.get(rid, [])
        assert len(replies) <= 1, f"request {rid} answered {len(replies)} times: {replies}"
        if not complete or info["stream"] not in live:
            continue
        assert replies, f"request {rid} never answered"
        if replies[0] == "lost":
            assert allow_lost, f"request {rid} lost without a host restart"
        elif replies[0] in ("ok", "expired"):
            assert ledger.applied.get(rid) == 1, f"request {rid} answered {replies[0]} but applied {ledger.applied.get(rid)}"
    host = world.games[0].feature
    applied_here = sum(info["add"] for rid, info in ledger.requests.items()
                       if ledger.applied.get(rid) and ledger.replies.get(rid, ["?"])[0] != "lost")
    return host.total, applied_here


def check_blobs(world, ledger, complete=True):
    live = current_streams(world)
    for key, info in ledger.blobs_sent.items():
        for slot, stream in live.items():
            if slot == info["slot"]:
                continue
            count = ledger.blobs_seen.get((stream, key), 0)
            assert count <= 1, f"blob {key} delivered {count} times to {stream}"
            wanted = info["target"] == -1 or (info["target"] == slot and info["target_stream"] == stream)
            if not wanted:
                assert count == 0, f"blob {key} delivered to {stream}, which it was not meant for"
            elif complete and info["stream"] in live.values() and info["at"] >= ledger.born.get(stream, 0) + JOIN_MS \
                    and info["at"] >= ledger.joined_at.get((info["stream"], stream), 0) \
                    and not any(isinstance(x, tuple) for x in ledger.pings_seen.get((stream, info["stream"]), [])):
                # Events sent before the receiver became a participant of the sender are not delivered to it
                # (docs/EVENT-LAYER.md, Participants): after a host restart a slow reconnect can take longer than JOIN_MS.
                assert count == 1, f"blob {key} was not delivered to {stream}"


def check_quiet(world, errors_allowed=0):
    for game in world.games.values():
        debug = game.node.call("mistrimulti_events_debug")
        assert debug["backlog"] == 0, f"slot {game.slot} still holds {debug['backlog']} unacknowledged events"
        assert debug["blobs"] == 0 and debug["requests"] == 0, (game.slot, debug)
        assert debug["errors"] <= errors_allowed, (game.slot, debug, game.warnings[:5])
        assert game.max_frame <= model.FRAME_LIMIT


def full_checks(world, ledger, allow_lost=False, errors_allowed=0):
    assert not ledger.wrong, ledger.wrong[:5]
    pairs = check_pings(world, ledger)
    check_requests(world, ledger, allow_lost)
    check_blobs(world, ledger)
    check_quiet(world, errors_allowed)
    host_total = world.games[0].feature.total
    for game in world.games.values():
        if game.slot:
            assert game.feature.total == host_total, f"slot {game.slot} total {game.feature.total} != host {host_total}"
    return pairs


# ---- scenarios -----------------------------------------------------------------------------------------

def impls(kind, count):
    if kind == "model":
        return {i: ModelNode for i in range(count)}
    if kind == "gml":
        return {i: GmlNode for i in range(count)}
    return {i: (GmlNode if i % 2 else ModelNode) for i in range(count)}


def scenario_clean(kind, players, seconds, seed=1):
    world = World(seed, impls(kind, players))
    ledger = Ledger()
    attach(world, ledger, {"all": {"until": seconds * 1000, "blobs": 2, "blob_size": 20000, "requests": 0.3}})
    world.run(seconds * 1000 + 8000)
    pairs = full_checks(world, ledger)
    sent = sum(len(v) for v in ledger.pings_sent.values())
    return f"{players} players, {sent} events, {len(ledger.requests)} requests, {len(ledger.blobs_sent)} blobs, {pairs} ordered streams"


def scenario_lossy(kind, players, seconds, seed=2):
    world = World(seed, impls(kind, players), loss=0.08, dup=0.15, jitter=150, latency=20)
    ledger = Ledger()
    attach(world, ledger, {"all": {"until": seconds * 1000, "blobs": 2, "blob_size": 40000, "requests": 0.3, "defer": 0.2}})
    world.run(seconds * 1000 + 20000)
    full_checks(world, ledger)
    return f"8% fragment loss, 15% duplicates, 150 ms jitter, 20% deferred requests: {world.net.sent} datagrams"


def scenario_disconnect(kind, seed=3):
    """A guest is cut off long enough to expire, with requests, results and a blob in flight, then returns."""
    world = World(seed, impls(kind, 4), loss=0.02, jitter=40)
    ledger = Ledger()
    attach(world, ledger, {"all": {"until": 40000, "requests": 0.3, "blobs": 1, "blob_size": 20000}})
    world.run(6000)
    guest = world.games[2]
    world.net.block(0, 2)                    # results stop reaching the guest; its requests still arrive
    asked = [guest.feature.request(5) for _ in range(5)]
    world.run(1500)
    applied_unanswered = [rid for rid in asked if ledger.applied.get(rid) and rid not in ledger.replies]
    assert applied_unanswered, "the scenario needs requests the host applied but could not answer"
    world.net.partition(2, 0)
    world.run(15000)
    host_saw_leave = any(r == 0 and p == 2 and not j for r, p, j in ledger.peer_events)
    world.net.partition(2, 0, False)
    world.run(45000)
    host_saw_return = [e for e in ledger.peer_events if e[:2] == (0, 2)][-1][2]
    assert host_saw_leave and host_saw_return, "the host did not see the guest leave and return"
    gaps = sum(1 for (r, s), seen in ledger.pings_seen.items() if r.startswith("2-")
               and any(isinstance(item, tuple) for item in seen))
    assert gaps >= 1, "the returning guest did not detect the events it missed"
    for rid in applied_unanswered:
        assert ledger.replies.get(rid) == ["ok"] and ledger.applied[rid] == 1, (rid, ledger.replies.get(rid))
    full_checks(world, ledger)
    return (f"15 s outage: host saw leave/return, guest reported {gaps} gaps, {len(applied_unanswered)} "
            "applied-but-unanswered requests answered once after the resend")


def scenario_host_restart(kind, seed=4):
    world = World(seed, impls(kind, 3), jitter=30)
    ledger = Ledger()
    attach(world, ledger, {"all": {"until": 30000, "requests": 0.4}})
    world.run(8000)
    for slot in (1, 2):
        world.net.partition(slot, 0)       # requests are in flight when the host goes away
        for _ in range(3):
            world.games[slot].feature.request(7)
    world.run(500)
    world.net.helpers[0].alive = False
    del world.net.helpers[0]
    del world.games[0]
    for slot in (1, 2):
        world.net.partition(slot, 0, False)
    world.run(3000)
    world.start(0)
    attach(world, ledger, {"all": {"until": 30000, "requests": 0.4}})
    world.run(40000)
    lost = sum(1 for replies in ledger.replies.values() if replies == ["lost"])
    assert lost >= 1, "no request was reported lost across the host restart"
    full_checks(world, ledger, allow_lost=True)
    return f"host restarted: {lost} in-flight requests reported lost (never silently re-applied), later traffic exact"


def scenario_guest_reset(kind, seed=5):
    """A guest re-enters the world (new stream) in the middle of transfers; old targeted data never reaches it."""
    world = World(seed, impls(kind, 3), jitter=20)
    ledger = Ledger()
    attach(world, ledger, {"all": {"until": 20000, "requests": 0.3}})
    world.run(4000)
    host = world.games[0].feature
    host.blob(60000, 1)
    world.run(100)
    world.games[1].node.call("mistrimulti_events_reset")
    world.run(30000)
    full_checks(world, ledger)
    return "a guest that re-entered mid-transfer starts clean; stale targeted blobs are not delivered to it"


def scenario_backpressure(kind, seed=6):
    world = World(seed, impls(kind, 3))
    ledger = Ledger()
    attach(world, ledger, {"all": {"traffic": False}})
    world.run(3000)
    guest = world.games[1].feature
    for _ in range(model.QUEUE_EVENTS + 100):
        guest.ping()
    accepted = guest.n
    assert accepted == model.QUEUE_EVENTS and guest.refused == 100, (accepted, guest.refused)
    assert not world.games[1].node.call("mistrimulti_event_can_emit", 1)
    big = {"s": guest.stream(), "n": 0, "pad": "x" * model.EVENT_BYTES}
    assert not world.games[1].node.call("mistrimulti_event_emit", "ping", big)
    assert world.games[1].node.call("mistrimulti_events_debug")["errors"] == 1
    world.run(30000)
    full_checks(world, ledger, errors_allowed=1)
    return f"{accepted} queued, 100 refused at the bound, oversized event refused, all {accepted} delivered in order"


def scenario_stall(kind, seed=7):
    """A receiver that cannot handle events yet (returns false) holds the stream; nothing is skipped."""
    world = World(seed, impls(kind, 3))
    ledger = Ledger()
    attach(world, ledger, {"all": {"until": 12000, "requests": 0.3}})
    world.run(2000)
    world.games[2].feature.stall_until = 6000
    world.run(25000)
    assert world.games[2].node.call("mistrimulti_events_debug")["stalls"] > 0
    full_checks(world, ledger)
    return "a handler that defers holds its stream in order; the sender's backlog drains afterwards"


def scenario_big_blob(kind, seed=8):
    world = World(seed, impls(kind, 2), loss=0.05, jitter=60)
    ledger = Ledger()
    attach(world, ledger, {"all": {"traffic": False}})
    world.run(3000)
    started = world.clock.ms
    assert world.games[1].feature.blob(100000, 0)
    assert world.games[0].feature.blob(model.BLOB_BYTES // 4, 1)    # 4-byte characters: exactly the limit
    too_big = "x" * (model.BLOB_BYTES + 1)
    assert not world.games[0].node.call("mistrimulti_event_send_blob", "file", too_big, -1, None)

    def done():
        return len(ledger.blobs_seen) == 2
    while not done() and world.clock.ms < started + 60000:
        world.run(500)
    elapsed = (world.clock.ms - started) / 1000
    full_checks(world, ledger)
    return f"100 KB and 256 KB blobs exact under 5% loss in {elapsed:.1f} s simulated; oversize refused"


def scenario_unbound_request(kind, seed=12):
    """A guest that has not seen the host's stream yet cannot make a request: one without a host session would also
    be applied by a restarted host (the original failure: requests applied twice across a host restart)."""
    world = World(seed, impls(kind, 3))
    ledger = Ledger()
    attach(world, ledger, {"all": {"traffic": False}})
    world.net.block(0, 1)                  # the host's frames do not reach guest 1; its own reach the host
    world.run(3000)
    guest = world.games[1].feature
    assert guest.request(3) is None, "a request was accepted before the host's stream was known"
    assert world.games[1].node.call("mistrimulti_event_requests_pending") == 0
    world.net.block(0, 1, False)
    world.run(3000)
    rid = guest.request(3)
    assert rid is not None, "no request after the host's stream became known"
    world.run(3000)
    assert ledger.applied.get(rid) == 1 and ledger.replies.get(rid) == ["ok"]
    return "a guest that has not seen the host's stream makes no request; with it, requests are bound to that host session"


def scenario_slot_reuse(kind, seed=9):
    world = World(seed, impls(kind, 3))
    ledger = Ledger()
    attach(world, ledger, {"all": {"until": 25000, "requests": 0.3}})
    world.run(5000)
    world.net.helpers[2].alive = False
    del world.net.helpers[2]
    del world.games[2]
    world.run(12000)
    world.start(2)
    attach(world, ledger, {"all": {"until": 25000, "requests": 0.3}})
    world.run(25000)
    full_checks(world, ledger)
    return "a different player in a reused slot starts clean and gets nothing meant for the previous one"


def test_lockstep():
    """The GML and the model publish byte-identical frames, tick by tick, through the same faulty scenarios."""
    digests = {}
    for kind in ("model", "gml"):
        world = World(11, impls(kind, 4), loss=0.05, dup=0.1, jitter=80)
        ledger = Ledger()
        attach(world, ledger, {"all": {"until": 24000, "blobs": 1, "blob_size": 20000, "requests": 0.3, "defer": 0.2}})
        world.run(6000)
        world.net.partition(3, 0)
        world.run(12000)
        world.net.partition(3, 0, False)
        world.games[2].node.call("mistrimulti_events_reset")
        world.run(15000)
        full_checks(world, ledger)
        digests[kind] = {slot: game.trace.hexdigest() for slot, game in world.games.items()}
    assert digests["model"] == digests["gml"], digests
    print("PASS: GML and model frames are byte-identical every tick through loss, outage, expiry and a reset")


def run_scenarios(kind, quick):
    results = []
    plan = [
        ("clean", lambda: scenario_clean(kind, 8, 20)),
        ("lossy", lambda: scenario_lossy(kind, 4, 25)),
        ("disconnect", lambda: scenario_disconnect(kind)),
        ("host restart", lambda: scenario_host_restart(kind)),
        ("guest reset", lambda: scenario_guest_reset(kind)),
        ("back-pressure", lambda: scenario_backpressure(kind)),
        ("stall", lambda: scenario_stall(kind)),
        ("big blob", lambda: scenario_big_blob(kind)),
        ("slot reuse", lambda: scenario_slot_reuse(kind)),
        ("unbound request", lambda: scenario_unbound_request(kind)),
    ]
    for name, fn in plan:
        started = time.monotonic()
        detail = fn()
        results.append(f"[{kind}] {name}: {detail} ({time.monotonic() - started:.1f} s)")
        print("PASS:", results[-1], flush=True)
    return results


# ---- unit tests ----------------------------------------------------------------------------------------

def fnv_reference(data):
    h = 2166136261
    for byte in data:
        h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
    return h


def test_hash():
    import random
    rng = random.Random(10)
    node = GmlNode(1, "abcdef0123", __import__("event_sim").Clock(), lambda *a: None)
    for size in (0, 1, 7, 100, 3000):
        text = random_text(rng, size)
        expected = fnv_reference(text.encode())
        assert model.fnv(model.FNV_OFFSET, text) == expected
        split = len(text) // 3
        assert model.fnv(model.fnv(model.FNV_OFFSET, text[:split]), text[split:]) == expected
        assert node.interp.call("__mistrimulti_ev_hash", model.FNV_OFFSET, text) == expected
    print("PASS: incremental FNV-1a in Python and GML equals the helper's checksum")


def test_parity():
    source = EVENTS_GML.read_text(encoding="utf-8")
    gml_functions = set(re.findall(r"^function\s+([A-Za-z0-9_]+)\s*\(", source, re.M))
    expected = set()
    for name in dir(model.EventLayer):
        if name.startswith("mistrimulti_"):
            expected.add(name)
        elif name.startswith("_ev_"):
            expected.add("__mistrimulti" + name)
    assert gml_functions == expected, f"only in GML: {gml_functions - expected}; only in Python: {expected - gml_functions}"
    macros = dict(re.findall(r"^#macro\s+MISTRIMULTI_EV_([A-Z_]+)\s+(\d+)", source, re.M))
    for name, value in macros.items():
        assert getattr(model, name) == int(value), name
    assert len(macros) == 17
    print(f"PASS: GML and the model define the same {len(gml_functions)} functions and {len(macros)} limits")


def test_syntax():
    files = sorted((EVENTS_GML.parent).glob("*.gml"))
    for path in files:
        gml.parse(path.read_text(encoding="utf-8"), path.name)
    for bad in ("function f() { var a = ; }", "function f() { if (a { } }", "function f() { a + ; }"):
        try:
            gml.parse(bad)
        except gml.GmlSyntaxError:
            continue
        raise AssertionError("the parser accepted " + bad)
    interp = gml.Interpreter()
    interp.load('function f(s) { return s.missing; } function g() { return "a" + 1; } '
                'function h() { undeclared = 1; } function k(a) { return a[3]; }')
    for name, arg in (("f", gml.GStruct()), ("g", None), ("h", None), ("k", gml.GArray([1]))):
        try:
            interp.call(name, *([arg] if arg is not None else []))
        except gml.GmlError:
            continue
        raise AssertionError(f"the interpreter accepted {name}")
    print(f"PASS: all {len(files)} mod GML files parse; the interpreter rejects unset reads, string+number, typos")


class Bench:
    """One node fed hand-made frames from fake senders, for precise protocol checks."""

    def __init__(self, impl, slot):
        self.clock = __import__("event_sim").Clock()
        self.warnings = []
        self.node = impl(slot, "feedbeef00", self.clock, lambda key, text: self.warnings.append(text))
        self.slot = slot
        self.log = []

    def register(self, kind, **fns):
        self.node.call("mistrimulti_event_register", kind, self.node.handlers(**fns))

    def frame(self, sender, stream, base, events, acks=None, streams=None):
        f = {"v": 2, "id": sender, "ev": {"s": stream, "b": base, "q": events,
                                         "a": acks or [0] * 8, "c": streams or [""] * 8}}
        return json.loads(json.dumps(f))

    def feed(self, sender, frame):
        node = self.node
        node.mask |= 1 << sender
        data = node.data(frame)
        node.set_peer(sender, data)
        node.call("mistrimulti_events_receive", sender, data)
        node.ticks += 3
        node.call("mistrimulti_events_tick")

    def out(self):
        f = self.node.data({"v": 2})
        return json.loads(self.node.call("mistrimulti_events_encode", f))["ev"]

    def queued(self):
        """Every unacknowledged event, including those beyond this frame's window."""
        return json.loads(gml.to_json(self.node.ev.out))


def test_requests_exactly_once(impl):
    bench = Bench(impl, 0)
    applied = []
    bench.register("count", on_request=lambda s, d, c: applied.append(c["id"]) or {"ok": True, "n": len(applied)})
    stream = "1-guest000-5"

    def request(seq, n, rid=None):
        rid = rid or f"{stream}:{n}"
        return {"s": seq, "k": "~q", "d": {"k": "count", "n": n, "i": rid, "d": {}}, "t": 0}

    bench.feed(1, bench.frame(1, stream, 1, [request(1, 1), request(2, 2)]))
    assert applied == [f"{stream}:1", f"{stream}:2"]
    bench.feed(1, bench.frame(1, stream, 1, [request(1, 1), request(2, 2), request(3, 1)]))   # resent after a gap
    assert len(applied) == 2, "a resent request was applied twice"
    results = [e for e in bench.queued() if e["k"] == "~r"]
    assert results[-1]["t"] == 1 and results[-1]["d"]["d"]["n"] == 1, "the cached result was not re-sent to the requester"
    bench.feed(1, bench.frame(1, stream, 1, [request(1, 1), request(2, 2), request(3, 1), request(4, 9, "1-other-1:9")]))
    assert len(applied) == 2, "a request with a forged id was applied"
    # Another player's traffic never evicts this requester's results.
    other = "2-guest000-7"
    events = [{"s": i + 1, "k": "~q", "d": {"k": "count", "n": i + 1, "i": f"{other}:{i + 1}", "d": {}}, "t": 0}
              for i in range(300)]
    bench.feed(2, bench.frame(2, other, 1, events))
    assert len(applied) == 302
    sent = [request(1, 1), request(2, 2), request(3, 1), request(4, 9, "1-other-1:9"), request(5, 2)]
    bench.feed(1, bench.frame(1, stream, 1, sent))
    resent = [e for e in bench.queued() if e["k"] == "~r" and e.get("t") == 1]
    assert resent[-1]["d"]["i"] == f"{stream}:2" and resent[-1]["d"]["d"]["n"] == 2, resent[-1]
    # Its own newer results do: the watermark still prevents re-application and the requester learns it expired.
    sent += [request(6 + i, 3 + i) for i in range(model.DONE_LIMIT)]
    sent.append(request(len(sent) + 1, 2))
    bench.feed(1, bench.frame(1, stream, 1, sent))
    assert len(applied) == 302 + model.DONE_LIMIT
    expired = [e for e in bench.queued() if e["k"] == "~r" and e["d"].get("x") is True]
    assert expired and expired[-1]["d"]["i"] == f"{stream}:2" and expired[-1]["t"] == 1
    print(f"PASS: [{impl.kind}] host applies each request id once: resend, forged id, others' traffic, own eviction -> expired")


def test_blob_integrity(impl):
    bench = Bench(impl, 1)
    got = []
    bench.register("file", on_blob=lambda s, text, meta: got.append(text))
    stream = "0-host0000-9"
    text = "hello 日本"
    h = model.fnv(model.FNV_OFFSET, text)
    size = len(text.encode())
    chunk = lambda seq, blob, d: {"s": seq, "k": "~b", "d": dict({"k": "file", "i": blob}, **d)}
    events = [
        chunk(1, 1, {"n": 0, "x": text, "l": size, "e": True, "h": h ^ 1}),             # wrong hash
        chunk(2, 2, {"n": 0, "x": text, "l": size - 1, "e": True, "h": h}),             # longer than announced
        chunk(3, 3, {"n": 0, "x": text, "l": model.BLOB_BYTES + 1}),                    # announced too large
        chunk(4, 4, {"n": 1, "x": text, "e": True, "h": h}),                            # no start seen
        chunk(5, 5, {"n": 0, "x": text[:3], "l": size}), chunk(6, 5, {"n": 1, "x": text[3:], "e": True, "h": h}),
        {"s": 7, "k": "~b", "d": "garbage"}, {"s": 8, "k": "unknown_kind", "d": 1},
    ]
    bench.feed(0, bench.frame(0, stream, 1, events))
    assert got == [text], got
    assert bench.node.call("mistrimulti_events_debug")["acks"][0] == 8, "malformed events must not stall the stream"
    assert bench.node.call("mistrimulti_events_debug")["errors"] == 3
    print(f"PASS: [{impl.kind}] corrupted, overlong and orphaned blob chunks are rejected; the stream continues")


def test_ack_streams(impl):
    """An ACK counts only for the stream it names: a stale ACK from a peer's previous session retires nothing."""
    bench = Bench(impl, 0)
    for i in range(3):
        bench.node.call("mistrimulti_event_emit", "ping", {"i": i}, -1)
    mine = bench.node.call("mistrimulti_events_debug")["stream"]
    bench.feed(1, bench.frame(1, "1-guest-1", 1, [], acks=[50] + [0] * 7, streams=["0-old-1"] + [""] * 7))
    assert bench.node.call("mistrimulti_event_backlog") == 3, "a stale ACK retired events"
    bench.feed(1, bench.frame(1, "1-guest-1", 1, [], acks=[2] + [0] * 7, streams=[mine] + [""] * 7))
    assert bench.node.call("mistrimulti_event_backlog") == 1
    bench.feed(2, bench.frame(2, "2-guest-1", 1, [], acks=[0] * 8, streams=[mine] + [""] * 7))
    bench.feed(1, bench.frame(1, "1-guest-1", 1, [], acks=[3] + [0] * 7, streams=[mine] + [""] * 7))
    assert bench.node.call("mistrimulti_event_backlog") == 1, "retired before every live peer acknowledged"
    bench.feed(2, bench.frame(2, "2-guest-1", 1, [], acks=[3] + [0] * 7, streams=[mine] + [""] * 7))
    assert bench.node.call("mistrimulti_event_backlog") == 0
    print(f"PASS: [{impl.kind}] cumulative ACKs retire only what every live peer acknowledged for this stream")


def test_frames(impl):
    bench = Bench(impl, 1)
    for i in range(300):
        assert bench.node.call("mistrimulti_event_emit", "ping", {"pad": "日" * 500, "i": i}, -1)
    f = bench.node.data({"v": 2, "padding": "z" * 9000})
    text = bench.node.call("mistrimulti_events_encode", f)
    q = json.loads(text)["ev"]["q"]
    assert len(text.encode()) <= model.FRAME_LIMIT and q and [e["s"] for e in q] == list(range(1, len(q) + 1))
    assert not bench.node.call("mistrimulti_event_emit", "~internal", {}, -1)
    assert not bench.node.call("mistrimulti_event_emit", "ping", {}, 1), "a node must not target itself"
    assert not bench.node.call("mistrimulti_event_emit", "ping", {}, 8)
    assert not bench.node.call("mistrimulti_event_emit", "x" * 33, {}, -1)
    print(f"PASS: [{impl.kind}] frames stay within 16 KB with a large head; invalid kinds and targets are refused")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="Python model only")
    parser.add_argument("--only", choices=["model", "gml", "mixed"], help="one implementation")
    args = parser.parse_args()
    test_syntax()
    test_parity()
    test_hash()
    kinds = ["model"] if args.quick else ["model", "gml", "mixed"]
    if args.only:
        kinds = [args.only]
    if not args.quick and args.only is None:
        test_lockstep()
    for kind in kinds:
        if kind != "mixed":
            impl = ModelNode if kind == "model" else GmlNode
            test_requests_exactly_once(impl)
            test_blob_integrity(impl)
            test_ack_streams(impl)
            test_frames(impl)
        run_scenarios(kind, args.quick)


if __name__ == "__main__":
    sys.exit(main())
