"""Deterministic simulation of games, helpers and a faulty network for the event-layer tests.

`SimHelper` reproduces the native helper's observable behaviour (helper/include/core.inc): latest-wins
snapshots, a sequence per change, a 100 ms resend while the frame is marked reliable and 1 s otherwise,
replay rejection per original sender, host relay of every accepted guest snapshot (and of heartbeats),
source pinning, 10 s expiry and `{"active":false}` publication on expiry. `SimGame` reproduces the parts
of MistriMultiBoot.gml that drive the event layer: the mask read once a second, `rx_<slot>.json` reads,
receive -> tick -> features -> encode at 20 Hz.

A node is either the Python reference model or MistriMultiEvents.gml run by tests/gml_subset.py.
"""
import hashlib
import json
import math
from pathlib import Path
import random

import event_model as model
from event_model import Struct
import gml_subset as gml

ROOT = Path(__file__).resolve().parent.parent
EVENTS_GML = ROOT / "mod/mistrimulti/gml/MistriMultiEvents.gml"
FRAGMENT = 1152
EXPIRE_MS = 10000


# ---- node implementations ------------------------------------------------------------------------------

class ModelNode:
    kind = "model"

    def __init__(self, slot, epoch, clock, log):
        self.r = model.Runtime(slot, epoch)
        self.layer = model.EventLayer(self.r, timer=clock.micros, log=log)
        self.layer.mistrimulti_events_initialize()

    def call(self, name, *args):
        return getattr(self.layer, name)(*args)

    def handlers(self, **fns):
        return Struct(**fns)

    def data(self, value):
        return value

    def set_peer(self, slot, frame):
        self.r.peers[slot] = frame

    @property
    def mask(self):
        return self.r.mask

    @mask.setter
    def mask(self, value):
        self.r.mask = value

    @property
    def ticks(self):
        return self.r.ticks

    @ticks.setter
    def ticks(self, value):
        self.r.ticks = value

    @property
    def ev(self):
        return self.r.ev


_PROGRAM = None


class GmlNode:
    kind = "gml"
    extra_files = ()            # further mod files to load (feature tests)
    prelude = ()                # GML source loaded first (macros the engine would define, for example)

    def builtins(self):
        """Engine functions and globals a subclass provides to the loaded files."""
        return {}

    def setup(self):
        """Runs after loading, before the event layer is initialised."""

    def __init__(self, slot, epoch, clock, log):
        global _PROGRAM
        self.slot = slot
        self.rt = gml.GStruct(id=slot, mode="host" if slot == 0 else "join", epoch=epoch, mask=0,
                              peers=gml.GArray([None] * 8), ticks=0)
        builtins = {
            "__mistrimulti_runtime": lambda: self.rt,
            "get_timer": clock.micros,
            "mmapi_warn_rate_limited": lambda key, mod, text: log(key, text), "mistrimulti_trace": lambda *a: None,
        }
        builtins.update(self.builtins())
        self.interp = gml.Interpreter(builtins)
        for source in self.prelude:
            self.interp.load(source, "prelude")
        if _PROGRAM is None:
            _PROGRAM = EVENTS_GML.read_text(encoding="utf-8")
        self.interp.load(_PROGRAM, EVENTS_GML.name)
        for name in self.extra_files:
            path = EVENTS_GML.parent / name
            self.interp.load(path.read_text(encoding="utf-8"), name)
        self.setup()
        self.interp.call("mistrimulti_events_initialize")

    def call(self, name, *args):
        return self.interp.call(name, *[self.data(a) for a in args])

    def handlers(self, **fns):
        return gml.GStruct(fns)

    def data(self, value):
        if isinstance(value, (gml.GStruct, gml.GArray)) or callable(value):
            return value
        if isinstance(value, dict):
            return gml.GStruct({k: self.data(v) for k, v in value.items()})
        if isinstance(value, list):
            return gml.GArray(self.data(v) for v in value)
        return value

    def set_peer(self, slot, frame):
        self.rt["peers"][slot] = frame

    @property
    def mask(self):
        return self.rt["mask"]

    @mask.setter
    def mask(self, value):
        self.rt["mask"] = value

    @property
    def ticks(self):
        return self.rt["ticks"]

    @ticks.setter
    def ticks(self, value):
        self.rt["ticks"] = value

    @property
    def ev(self):
        return Struct(**self.rt["ev"])


# ---- clock and network -----------------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.ms = 0
        self.offset = 1000003

    def micros(self):
        self.offset += 1  # get_timer() never returns the same value twice in practice
        return self.ms * 1000 + self.offset


class Net:
    def __init__(self, rng, loss=0.0, dup=0.0, jitter=0, latency=5):
        self.rng = rng
        self.loss, self.dup, self.jitter, self.latency = loss, dup, jitter, latency
        self.queue = []
        self.blocked = set()
        self.helpers = {}
        self.sent = 0

    def send(self, src, dst, packet, now):
        self.sent += 1
        if (src, dst) in self.blocked or dst not in self.helpers:
            return
        fragments = max(1, math.ceil(len(packet[3].encode()) / FRAGMENT))
        if self.rng.random() < 1 - (1 - self.loss) ** fragments:
            return
        copies = 2 if self.rng.random() < self.dup else 1
        for _ in range(copies):
            self.queue.append((now + self.latency + self.rng.randint(0, self.jitter), self.rng.random(), src, dst, packet))

    def deliver(self, now):
        due = [p for p in self.queue if p[0] <= now]
        self.queue = [p for p in self.queue if p[0] > now]
        due.sort(key=lambda p: (p[0], p[1]))
        for _t, _r, src, dst, packet in due:
            helper = self.helpers.get(dst)
            if helper is not None and helper.alive:
                helper.receive(packet, src, now)

    def block(self, src, dst, on=True):
        (self.blocked.add if on else self.blocked.discard)((src, dst))

    def partition(self, a, b, on=True):
        for pair in ((a, b), (b, a)):
            (self.blocked.add if on else self.blocked.discard)(pair)


class SimHelper:
    def __init__(self, net, slot, epoch, now):
        self.net, self.slot, self.epoch = net, slot, epoch
        self.host = slot == 0
        self.cache = '{"active":false}'
        self.seq = 1
        self.reliable = False
        self.last_send = now
        self.seen = {}
        self.accepted = {}
        self.records = {}
        self.rx = {}
        self.version = 0
        self.alive = True
        net.helpers[slot] = self

    def mask(self):
        bits = 0
        for slot in self.seen:
            bits |= 1 << slot
        return bits

    def publish(self, text, reliable, now):
        assert len(text.encode()) <= model.FRAME_LIMIT, "frame exceeds the helper limit"
        self.reliable = reliable
        if text != self.cache:
            self.cache = text
            self.seq += 1
            self.send_local(now)
            self.last_send = now

    def send_local(self, now):
        packet = (self.slot, self.epoch, self.seq, self.cache)
        if self.host:
            for slot in self.seen:
                self.net.send(0, slot, packet, now)
        else:
            self.net.send(self.slot, 0, packet, now)

    def step(self, now):
        if now - self.last_send >= (100 if self.reliable else 1000):
            self.send_local(now)
            self.last_send = now
        for slot, seen in list(self.seen.items()):
            if now - seen >= EXPIRE_MS:
                del self.seen[slot]
                self.accepted.pop(slot, None)
                self.records.pop(slot, None)
                self.version += 1
                self.rx[slot] = (self.version, '{"active":false}')

    def receive(self, packet, src, now):
        orig, epoch, seq, text = packet
        if orig == self.slot:
            return
        if self.host:
            if orig == 0 or src != orig:
                return
        elif src != 0:
            return
        self.seen[orig] = now
        last = self.accepted.get(orig)
        if last is not None and last[0] == epoch:
            if seq < last[1]:
                return
            if seq == last[1]:
                if self.host:
                    self.forward(orig, now)
                return
        self.accepted[orig] = (epoch, seq)
        self.records[orig] = packet
        self.version += 1
        self.rx[orig] = (self.version, text)
        if self.host:
            self.forward(orig, now)

    def forward(self, orig, now):
        for slot in self.seen:
            if slot != orig:
                self.net.send(0, slot, self.records[orig], now)


# ---- the game side (MistriMultiBoot.gml's tick) -----------------------------------------------------------

class SimGame:
    def __init__(self, world, slot, impl, epoch):
        self.world, self.slot, self.epoch = world, slot, epoch
        self.node = impl(slot, epoch, world.clock, self.log)
        self.parsed = {}
        self.max_frame = 0
        self.warnings = []
        self.phase = world.rng.randint(0, 49)
        self.feature = None
        self.trace = hashlib.sha256()

    def log(self, key, text):
        self.warnings.append(text)

    def helper(self):
        return self.world.net.helpers.get(self.slot)

    def bridge_tick(self, now):
        node = self.node
        node.ticks += 3
        helper = self.helper()
        if node.ticks % 60 == 3:
            node.mask = helper.mask() if helper is not None and helper.alive else 0
        for i in range(8):
            if i == self.slot or (node.mask & (1 << i)) == 0 or helper is None:
                continue
            entry = helper.rx.get(i)
            if entry is None:
                continue
            version, text = entry
            cached = self.parsed.get(i)
            if cached is None or cached[0] != version:
                cached = (version, node.data(json.loads(text)))
                self.parsed[i] = cached
            frame = cached[1]
            if frame.get("v") != 2:
                continue
            node.set_peer(i, frame)
            node.call("mistrimulti_events_receive", i, frame)
        node.call("mistrimulti_events_tick")
        if self.feature is not None:
            self.feature.tick(now)
        fields = {"v": 2, "id": self.slot, "epoch": self.epoch, "active": True}
        if hasattr(self.feature, "frame"):
            fields.update(self.feature.frame())
        frame = node.data(fields)
        text = node.call("mistrimulti_events_encode", frame)
        reliable = node.call("mistrimulti_events_reliable")
        self.max_frame = max(self.max_frame, len(text.encode()))
        self.trace.update(text.encode() + (b"1" if reliable else b"0"))
        debug = node.call("mistrimulti_events_debug")
        assert debug["backlog"] <= model.QUEUE_EVENTS and debug["bytes"] <= model.QUEUE_BYTES
        if helper is not None and helper.alive:
            helper.publish(text, reliable, now)


class World:
    def __init__(self, seed, impls, loss=0.0, dup=0.0, jitter=0, latency=5):
        self.rng = random.Random(seed)
        self.clock = Clock()
        self.net = Net(self.rng, loss, dup, jitter, latency)
        self.games = {}
        self.impls = impls
        self.epochs = 0
        for slot, impl in impls.items():
            self.start(slot, impl)

    def new_epoch(self):
        self.epochs += 1
        return f"{self.epochs:08x}" + hashlib.sha1(str(self.epochs).encode()).hexdigest()[:24]

    def start(self, slot, impl=None):
        impl = impl or self.impls[slot]
        SimHelper(self.net, slot, self.epochs + 1000, self.clock.ms)
        game = SimGame(self, slot, impl, self.new_epoch())
        self.games[slot] = game
        return game

    def run(self, ms, check=None):
        end = self.clock.ms + ms
        while self.clock.ms < end:
            self.clock.ms += 10
            now = self.clock.ms
            self.net.deliver(now)
            for helper in list(self.net.helpers.values()):
                if helper.alive:
                    helper.step(now)
            for game in list(self.games.values()):
                if (now + game.phase) % 50 < 10:
                    game.bridge_tick(now)
            if check is not None:
                check()


def random_text(rng, size):
    alphabet = "abcdefghijklmnopqrstuvwxyz \"\\/{}[]:,\n\té日本\U0001F600\x01\x1f"
    weights = [8] * 26 + [6] + [1] * (len(alphabet) - 27)
    return "".join(rng.choices(alphabet, weights, k=size))
