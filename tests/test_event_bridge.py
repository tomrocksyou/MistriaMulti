"""The event layer over the real native helpers and the real file bridge.

    python3 tests/test_event_bridge.py build/mistrimulti-helper-linux [--guests 3]
    python3 tests/test_event_bridge.py build/mistrimulti-helper.exe            # Windows, or Wine on Linux

One host and several guests each run the real assembly helper on loopback. The game side of every player is
the Python reference model (tests/event_model.py) driven exactly like MistriMultiBoot.gml drives the GML:
`status.json` once a second (with the 3 s heartbeat rule), `rx_<slot>.json` at 20 Hz, and `tx.frame`
written atomically with its `0\\n`/`1\\n` prefix. One guest talks to the host through a UDP proxy that drops,
duplicates and reorders datagrams. The run covers steady traffic with 100 KB blobs, a guest whose helper dies
long enough to expire and then comes back, and a host restart.
"""
import argparse
import heapq
import json
import os
from pathlib import Path
import random
import select
import socket
import subprocess
import tempfile
import threading
import time

from event_sim import ModelNode
import test_event_layer as checks
from test_transport import available_port

ON_WINDOWS = os.name == "nt"
WINE = "/usr/lib/wine/wine64"
CODE = "a1b2c3d4"


class Clock:
    def __init__(self):
        self.start = time.monotonic()

    @property
    def ms(self):
        return int((time.monotonic() - self.start) * 1000)

    def micros(self):
        return int((time.monotonic() - self.start) * 1e6) + 1000003


class Proxy(threading.Thread):
    """A lossy UDP hop between one guest helper and the host helper."""

    def __init__(self, host_port, rng, loss=0.1, dup=0.1, delay=60):
        super().__init__(daemon=True)
        self.host = ("127.0.0.1", host_port)
        self.front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.front.bind(("127.0.0.1", 0))
        self.back = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.back.bind(("127.0.0.1", 0))
        self.port = self.front.getsockname()[1]
        self.rng, self.loss, self.dup, self.delay = rng, loss, dup, delay
        self.guest = None
        self.queue = []
        self.stop = threading.Event()
        self.counts = {"forwarded": 0, "dropped": 0, "duplicated": 0}

    def schedule(self, sock, data, address):
        if self.rng.random() < self.loss:
            self.counts["dropped"] += 1
            return
        copies = 2 if self.rng.random() < self.dup else 1
        self.counts["duplicated"] += copies - 1
        for _ in range(copies):
            heapq.heappush(self.queue, (time.monotonic() + self.rng.random() * self.delay / 1000,
                                        self.rng.random(), sock, data, address))

    def run(self):
        while not self.stop.is_set():
            timeout = 0.01 if not self.queue else max(0.0, min(0.01, self.queue[0][0] - time.monotonic()))
            ready, _, _ = select.select([self.front, self.back], [], [], timeout)
            for sock in ready:
                data, address = sock.recvfrom(4096)
                if sock is self.front:
                    self.guest = address
                    self.schedule(self.back, data, self.host)
                elif self.guest is not None:
                    self.schedule(self.front, data, self.guest)
            while self.queue and self.queue[0][0] <= time.monotonic():
                _, _, sock, data, address = heapq.heappop(self.queue)
                sock.sendto(data, address)
                self.counts["forwarded"] += 1


class BridgeGame:
    """The game side of one player: MistriMultiBoot.gml's bridge tick, with the reference model."""

    def __init__(self, world, slot, bridge):
        self.world, self.slot, self.bridge = world, slot, bridge
        self.epoch = world.new_epoch()
        self.node = ModelNode(slot, self.epoch, world.clock, self.log)
        self.parsed = {}
        self.warnings = []
        self.max_frame = 0
        self.last_frame = None
        self.heartbeat = None
        self.heartbeat_at = 0
        self.feature = None

    def log(self, key, text):
        self.warnings.append(text)

    def read_json(self, path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def bridge_tick(self):
        node = self.node
        node.ticks += 3
        now = self.world.clock.ms
        if node.ticks % 60 == 3:
            status = self.read_json(self.bridge / "status.json")
            if isinstance(status, dict) and status.get("running") is True:
                if status.get("heartbeat") != self.heartbeat:
                    self.heartbeat = status.get("heartbeat")
                    self.heartbeat_at = now
                node.mask = status["mask"] if now - self.heartbeat_at < 3000 else 0
            else:
                node.mask = 0
        for i in range(8):
            if i == self.slot or (node.mask & (1 << i)) == 0:
                continue
            path = self.bridge / f"rx_{i}.json"
            try:
                stamp = path.stat().st_mtime_ns
            except OSError:
                continue
            cached = self.parsed.get(i)
            if cached is None or cached[0] != stamp:
                frame = self.read_json(path)
                if frame is None:
                    continue
                cached = (stamp, frame)
                self.parsed[i] = cached
            frame = cached[1]
            if frame.get("v") != 2:
                continue
            node.set_peer(i, frame)
            node.call("mistrimulti_events_receive", i, frame)
        node.call("mistrimulti_events_tick")
        if self.feature is not None:
            self.feature.tick(now)
        frame = {"v": 2, "id": self.slot, "epoch": self.epoch, "active": True}
        text = node.call("mistrimulti_events_encode", frame)
        framed = ("1\n" if node.call("mistrimulti_events_reliable") else "0\n") + text
        self.max_frame = max(self.max_frame, len(text.encode()))
        assert len(text.encode()) <= 16384
        if framed != self.last_frame:
            temp = self.bridge / "tx.tmp"
            temp.write_bytes(framed.encode("utf-8"))
            os.replace(temp, self.bridge / "tx.frame")
            self.last_frame = framed


class World:
    def __init__(self, helper, guests, seed):
        self.helper = helper
        self.clock = Clock()
        self.rng = random.Random(seed)
        self.tmp = tempfile.TemporaryDirectory(prefix="events-", dir=Path(__file__).resolve().parent.parent / "build")
        self.root = Path(self.tmp.name)
        self.ports = {slot: available_port() for slot in range(guests + 1)}
        self.processes = {}
        self.games = {}
        self.epochs = 0
        self.proxy = None
        self.ledger = checks.Ledger()

    def new_epoch(self):
        self.epochs += 1
        return f"{self.epochs:08x}{self.rng.getrandbits(96):024x}"

    def bridge(self, slot):
        path = self.root / f"bridge_{slot}"
        path.mkdir(exist_ok=True)
        return path

    def native(self, path):
        return str(path) if ON_WINDOWS or not self.helper.name.endswith(".exe") else "Z:" + str(path).replace("/", "\\")

    def start_helper(self, slot):
        bridge = self.bridge(slot)
        (bridge / "stop.flag").unlink(missing_ok=True)
        host_port = self.ports[0]
        if slot == 2 and self.proxy is not None:
            host_port = self.proxy.port
        args = ["host", str(self.ports[slot]), "0", CODE, self.native(bridge)] if slot == 0 else \
            ["join", str(self.ports[slot]), str(slot), CODE, self.native(bridge), "127.0.0.1", str(host_port)]
        command = [str(self.helper)] + args
        if self.helper.name.endswith(".exe") and not ON_WINDOWS:
            command = [WINE] + command
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if ON_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        env = dict(os.environ, WINEDEBUG="-all")
        self.processes[slot] = subprocess.Popen(command, env=env, **kwargs)

    def kill_helper(self, slot):
        process = self.processes.pop(slot)
        if self.helper.name.endswith(".exe") and not ON_WINDOWS:
            # Under Wine a SIGKILLed process leaves its UDP port bound inside wineserver (for 30 s and more under load),
            # so the restarted helper cannot bind it, exits with code 3 and the new game runs on the dead helper's
            # stale files. Ask for the normal exit, which closes the socket; the game side sees the same silence.
            (self.bridge(slot) / "stop.flag").write_text("stop")
            try:
                process.wait(timeout=10)
                return
            except subprocess.TimeoutExpired:
                pass
        process.kill()
        process.wait(timeout=10)

    def start_game(self, slot, plan):
        game = BridgeGame(self, slot, self.bridge(slot))
        self.games[slot] = game
        game.feature = checks.Feature(game, self.ledger, self.rng, plan)
        return game

    def run(self, seconds, until=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            started = time.monotonic()
            for slot, process in self.processes.items():
                assert process.poll() is None, f"the helper of slot {slot} exited with code {process.returncode}"
            for game in list(self.games.values()):
                game.bridge_tick()
            if until is not None and until():
                return True
            time.sleep(max(0.0, 0.05 - (time.monotonic() - started)))
        return until is None

    def masks(self):
        return {slot: game.node.mask for slot, game in self.games.items()}

    def close(self):
        for slot, process in list(self.processes.items()):
            (self.bridge(slot) / "stop.flag").write_text("stop")
        for process in self.processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        if self.proxy is not None:
            self.proxy.stop.set()
        self.tmp.cleanup()


def everyone_connected(world, count):
    full = (1 << (count + 1)) - 1
    return all(mask | (1 << slot) == full for slot, mask in world.masks().items())


def settle(world, seconds, what):
    """Run without new traffic until every queue, blob and request has drained."""
    for game in world.games.values():
        game.feature.plan["until"] = 0

    def drained():
        for game in world.games.values():
            debug = game.node.call("mistrimulti_events_debug")
            if debug["backlog"] or debug["blobs"] or debug["requests"]:
                return False
        return True
    assert world.run(seconds, drained), f"{what}: queues did not drain: " + \
        str({s: g.node.call("mistrimulti_events_debug") for s, g in world.games.items()})
    world.run(1.5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("helper", type=Path)
    parser.add_argument("--guests", type=int, default=3)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    assert 2 <= args.guests <= 7
    world = World(args.helper.resolve(), args.guests, args.seed)
    traffic = {"pings": 3, "requests": 0.3, "blobs": 1, "blob_size": 30000, "defer": 0.1}
    results = []
    try:
        world.proxy = Proxy(world.ports[0], random.Random(args.seed + 1))
        world.proxy.start()
        for slot in range(args.guests + 1):
            world.start_helper(slot)
            world.start_game(slot, dict(traffic, until=1 << 60))
        assert world.run(20, lambda: everyone_connected(world, args.guests)), f"admission: {world.masks()}"

        # Steady traffic, including a 100 KB blob each way between a guest and the host.
        world.run(1)
        assert world.games[1].feature.blob(100000, 0) and world.games[0].feature.blob(100000, -1)
        started = time.monotonic()
        big = list(world.ledger.blobs_sent)[-2:]
        wanted = 1 + args.guests          # guest 1 -> host, and host -> every guest
        assert world.run(60, lambda: sum(1 for k in world.ledger.blobs_seen if k[1] in big) == wanted), \
            "the 100 KB blobs did not arrive"
        elapsed = time.monotonic() - started
        world.run(6)
        settle(world, 30, "steady traffic")
        checks.full_checks(world, world.ledger)
        sent = sum(len(v) for v in world.ledger.pings_sent.values())
        results.append(f"{args.guests + 1} players over real helpers, one behind a lossy proxy: {sent} events, "
                       f"{len(world.ledger.requests)} requests, {len(world.ledger.blobs_sent)} blobs exact and in "
                       f"order; 100 KB blobs to {wanted} receivers under concurrent traffic in {elapsed:.1f} s; frames <= "
                       f"{max(g.max_frame for g in world.games.values())} bytes; proxy {world.proxy.counts}")
        print("PASS:", results[-1], flush=True)

        # A guest's helper dies for longer than the 10 s expiry; its game keeps running, then the helper returns.
        for game in world.games.values():
            game.feature.plan["until"] = 1 << 60
        world.run(2)
        world.kill_helper(3)
        asked = [world.games[3].feature.request(4) for _ in range(3)]
        # The host expires a silent peer after 10 s; wait until it has (up to 25 s: a slow runner under Wine can take longer).
        world.run(25, lambda: any(r == 0 and p == 3 and not j for r, p, j in world.ledger.peer_events))
        host_left = any(r == 0 and p == 3 and not j for r, p, j in world.ledger.peer_events)
        world.start_helper(3)
        assert world.run(20, lambda: everyone_connected(world, args.guests)), f"rejoin: {world.masks()}"
        world.run(5)
        settle(world, 40, "reconnect")
        checks.full_checks(world, world.ledger)
        assert host_left and all(world.ledger.replies.get(rid) == ["ok"] for rid in asked if rid), \
            (host_left, [world.ledger.replies.get(rid) for rid in asked])
        results.append("a guest helper killed until the host expired it: the host saw it leave and return, requests made while it "
                       "was away were applied once and answered, nothing was duplicated or reordered")
        print("PASS:", results[-1], flush=True)

        # The host restarts (helper and game). In-flight requests are reported lost, never applied twice.
        for game in world.games.values():
            game.feature.plan["until"] = 1 << 60
        world.run(2)
        world.kill_helper(0)
        del world.games[0]
        stranded = [world.games[1].feature.request(6) for _ in range(3)]
        world.run(4)
        world.start_helper(0)
        world.start_game(0, dict(traffic, until=1 << 60))
        assert world.run(25, lambda: everyone_connected(world, args.guests)), f"host restart: {world.masks()}"
        world.run(6)
        settle(world, 40, "host restart")
        checks.full_checks(world, world.ledger, allow_lost=True)
        lost = [rid for rid in stranded if rid and world.ledger.replies.get(rid) == ["lost"]]
        assert lost, [world.ledger.replies.get(rid) for rid in stranded]
        results.append(f"host restart: {len(lost)} stranded requests reported lost to the guest, traffic resumed "
                       "with the new host session")
        print("PASS:", results[-1], flush=True)
    finally:
        world.close()


if __name__ == "__main__":
    main()
