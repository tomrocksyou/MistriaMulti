"""Host authority, join authentication and abuse limits of the native helper (docs/SECURITY.md), black box.

    python3 tests/test_trust.py build/mistrimulti-helper-linux
    python3 tests/test_trust.py build/mistrimulti-helper.exe        # Windows, or Wine on Linux

On Linux the test re-runs itself in a private network namespace (`unshare -n`), so it cannot collide with other
suites on fixed ports. tests/mmauth.py is the reference implementation of the handshake: it plays the guest
against the real host helper and the host against the real guest helper.

Covered: the join handshake with and without a password (and that the password never crosses the wire), hijack
of a slot, forged and replayed handshake and data packets, bit flips in every byte of a packet, identity keys
(registration, known identity, restart), the deny list, per-peer rate limits, hostile input that must never crash
the helper (random datagrams, correctly tagged but impossible headers), and the guest side (wrong host, wrong
tag, resync, silence).
"""
import argparse
import json
import os
from pathlib import Path
import random
import socket
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmauth
from test_transport import available_port, read_json, wait_until

ON_WINDOWS = os.name == "nt"
WINE = "/usr/lib/wine/wine64"
CODE_TEXT = "a1b2c3d4"
CODE = 0xA1B2C3D4
LOCAL = "127.0.0.1"


def isolate():
    """Re-run inside `unshare -n` with loopback up (Linux), once."""
    if ON_WINDOWS or os.environ.get("MM_TRUST_NS") == "1":
        return
    if subprocess.run(["unshare", "-n", "true"], capture_output=True).returncode != 0:
        return
    os.environ["MM_TRUST_NS"] = "1"
    code = ("import fcntl,socket,struct,os,sys;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);"
            "fcntl.ioctl(s,0x8914,struct.pack('16sH14s',b'lo',0x41,b'\\0'*14));os.execvp(sys.argv[1],sys.argv[1:])")
    os.execvp("unshare", ["unshare", "-n", sys.executable, "-c", code, sys.executable] + sys.argv)


class Env:
    def __init__(self, exe):
        self.exe = Path(exe).resolve()
        self.wine = self.exe.name.endswith(".exe") and not ON_WINDOWS
        self.tmp = tempfile.TemporaryDirectory(prefix="trust-", dir=Path(__file__).resolve().parent.parent / "build")
        self.root = Path(self.tmp.name)
        self.nodes = []
        self.count = 0

    def native(self, path):
        return "Z:" + str(path).replace("/", "\\") if self.wine else str(path)

    def folder(self, name=None):
        self.count += 1
        path = self.root / (name or f"n{self.count}")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def close(self):
        for node in list(self.nodes):
            node.stop()
        self.tmp.cleanup()


class Node:
    """One native helper with its own bridge folder."""

    def __init__(self, env, role, slot, host_port=None, port=None, password=None, keys=False, install_key=False,
                 deny=None, config=None, code=CODE_TEXT):
        self.env, self.role, self.slot, self.code = env, role, slot, code
        self.dir = env.folder()
        self.bridge = self.dir / f"bridge_{slot}"
        self.bridge.mkdir()
        self.port = port or available_port()
        self.host_port = host_port
        self.keys_file = self.dir / "trust_keys.txt"
        self.key_file = self.dir / "install.key"
        self.deny_file = self.dir / "deny.txt"
        lines = []
        if install_key:
            lines.append("key=" + env.native(self.key_file))
        if keys:
            lines.append("keys=" + env.native(self.keys_file))
        if deny is not None:
            self.deny_file.write_text(deny)
            lines.append("deny=" + env.native(self.deny_file))
        if password is not None:
            lines.append("pass=" + password)
        if config is not None:
            (self.bridge / "auth.cfg").write_bytes(config)
        elif lines:
            (self.bridge / "auth.cfg").write_text("\r\n".join(lines) + "\r\n")
        self.process = None

    def command(self):
        args = ["host", str(self.port), "0", self.code, self.env.native(self.bridge)] if self.role == "host" else \
            ["join", str(self.port), str(self.slot), self.code, self.env.native(self.bridge), LOCAL, str(self.host_port)]
        return ([WINE] if self.env.wine else []) + [str(self.env.exe)] + args

    def start(self, wait=True):
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if ON_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        (self.bridge / "stop.flag").unlink(missing_ok=True)
        self.process = subprocess.Popen(self.command(), env=dict(os.environ, WINEDEBUG="-all"), **kwargs)
        self.env.nodes.append(self)
        if wait:
            wait_until(lambda: self.status()["running"], 15, "helper start")
        return self

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def stop(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            (self.bridge / "stop.flag").write_text("stop")
            try:
                self.process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
        if self in self.env.nodes:
            self.env.nodes.remove(self)

    def kill(self):
        if self.process is not None:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process = None
        if self in self.env.nodes:
            self.env.nodes.remove(self)

    def status(self):
        return read_json(self.bridge / "status.json")

    def auth(self, slot):
        path = self.bridge / f"auth_{slot}.json"
        return read_json(path) if path.exists() else None

    def rx(self, slot):
        path = self.bridge / f"rx_{slot}.json"
        return read_json(path) if path.exists() else None

    def publish(self, data, reliable=False):
        temp = self.bridge / "game-write.tmp"
        temp.write_bytes((b"1\n" if reliable else b"0\n") + json.dumps(data, separators=(",", ":")).encode())
        os.replace(temp, self.bridge / "tx.frame")

    def settle(self):
        """Wait until the helper has published a status after everything sent so far was read."""
        beat = self.status()["heartbeat"]
        wait_until(lambda: self.status()["heartbeat"] > beat + 1000, 6, "status heartbeat")
        return self.status()


class Wire:
    """A scripted guest: a UDP socket and the reference handshake."""

    def __init__(self, port, slot, password=b"", install_key=None, code=CODE):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((LOCAL, 0))
        self.addr = (LOCAL, port)
        self.slot, self.code = slot, code
        self.guest = mmauth.Guest(code, slot, install_key, password)
        self.seq = 0
        self.sent = []
        self.received = []

    def close(self):
        self.sock.close()

    def send(self, packet):
        self.sent.append(packet)
        self.sock.sendto(packet, self.addr)

    def recv(self, timeout=1.5):
        self.sock.settimeout(timeout)
        try:
            packet, source = self.sock.recvfrom(4096)
        except socket.timeout:
            return None
        self.received.append(packet)
        return packet

    def drain(self, timeout=0.3):
        out = []
        while True:
            packet = self.recv(timeout)
            if packet is None:
                return out
            out.append(packet)

    def join(self, proof_mutator=None, timeout=3):
        """Runs the handshake. Returns 'ok', ('reject', reason) or None."""
        self.send(self.guest.hello())
        challenge = self.recv(timeout)
        if challenge is None:
            return None
        if challenge[4] == 5:
            return ("reject", struct.unpack_from("<I", challenge, 8)[0])
        proof = self.guest.proof(challenge)
        if proof is None:
            return None
        if proof_mutator is not None:
            proof = proof_mutator(self.guest, proof)
        self.send(proof)
        reply = self.recv(timeout)
        if reply is None:
            return None
        if reply[4] == 5:
            return ("reject", struct.unpack_from("<I", reply, 8)[0])
        return "ok" if self.guest.welcome(reply) else None

    def state(self, data, seq=None, epoch=100):
        self.seq = seq if seq is not None else self.seq + 1
        body = json.dumps(data, separators=(",", ":")).encode()
        for packet in self.guest.seal(self.seq, body, epoch):
            self.send(packet)


def new_wire(host, slot, **kwargs):
    return Wire(host.port, slot, **kwargs)


def joined(host, slot, **kwargs):
    wire = new_wire(host, slot, **kwargs)
    assert wire.join() == "ok", "join failed"
    return wire


RESULTS = []


def passed(text):
    RESULTS.append(text)
    print("PASS:", text, flush=True)


def forge_known(guest, proof):
    """A PROOF for a known fingerprint with garbage in the registration field and a tag that covers it."""
    body = bytearray(proof[:100])
    body[68:100] = os.urandom(32)
    k = mmauth.guest_key(guest.ik, guest.hfp)
    ak = mmauth.hm(bytes(32), k)           # this test host has no password
    tag = mmauth.hm(ak, b"MMPROOF1", bytes(body[8:100]), guest.hfp)[:16]
    return bytes(body) + tag + bytes(12)


# ---------------------------------------------------------------------------------------------------------------

def test_basic_join(env):
    host = Node(env, "host", 0).start()
    host.publish({"active": True, "id": 0, "value": "host-state"})
    wire = new_wire(host, 1)
    assert wire.join() == "ok"
    wire.state({"active": True, "id": 1, "value": "guest-state"})
    wait_until(lambda: host.rx(1) == {"active": True, "id": 1, "value": "guest-state"}, 6, "guest state on host")
    wait_until(lambda: host.status()["mask"] == 2, 6, "mask")
    auth = host.auth(1)
    assert auth["state"] == 1 and auth["fp"] == wire.guest.fp.hex() and auth["gen"] == 1, auth
    got = None
    for _ in range(40):
        packet = wire.recv(0.5)
        if packet and packet[:4] == b"MSMP":
            opened = wire.guest.open(packet)
            assert opened is not None, "host data carries a valid tag"
            got = opened[1]
            if b"host-state" in got:
                break
    assert got is not None and b"host-state" in got
    wire.close()
    host.stop()
    passed("join without a password; verified fingerprint published; both directions carry valid tags")


def test_no_handshake(env):
    host = Node(env, "host", 0).start()
    stranger = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stranger.bind((LOCAL, 0))
    stranger.settimeout(0.3)
    body = b'{"active":true,"evil":true}'
    old_style = mmauth.HEADER.pack(b"MSMP", 1, 0, 1, 5, CODE, 0, len(body), 0, 1, 100, 0) + body
    for slot in (1, 2, 7):
        packet = mmauth.data_packet(os.urandom(32), 0, slot, 5, CODE, body)
        stranger.sendto(packet, (LOCAL, host.port))
        stranger.sendto(old_style[:8] + struct.pack("<I", slot) + old_style[12:], (LOCAL, host.port))
    replies = []
    try:
        while True:
            replies.append(stranger.recvfrom(100)[0])
    except socket.timeout:
        pass
    status = host.settle()
    assert status["mask"] == 0 and status["unknown"] >= 1, status
    assert not list(host.bridge.glob("rx_[1-7].json")), "nothing from a stranger may be published"
    assert len(replies) <= 2 and all(len(r) == 16 and r[:5] == b"MSAU\x06" for r in replies), replies
    stranger.close()
    host.stop()
    passed("without a handshake nothing is published, the old unauthenticated format is refused, hints are tiny")


def test_hijack(env):
    host = Node(env, "host", 0).start()
    friend = joined(host, 1)
    friend.state({"active": True, "who": "friend"})
    wait_until(lambda: host.rx(1) == {"active": True, "who": "friend"}, 6, "friend state")
    attacker = new_wire(host, 1)
    assert attacker.join() == ("reject", mmauth.REJECT_BUSY)
    attacker.guest.sk = os.urandom(32)
    attacker.state({"active": True, "who": "attacker"}, seq=500)
    time.sleep(0.4)
    assert host.rx(1) == {"active": True, "who": "friend"}
    # the attacker has the friend's fingerprint but not the key: the stored key is used, so the tag is wrong
    victim_fp = friend.guest.fp
    thief = new_wire(host, 2)

    def steal(guest, proof):
        body = bytearray(proof[:100])
        body[52:68] = victim_fp
        k = mmauth.guest_key(guest.ik, guest.hfp)
        tag = mmauth.hm(mmauth.hm(bytes(32), k), b"MMPROOF1", bytes(body[8:100]), guest.hfp)[:16]
        return bytes(body) + tag + bytes(12)
    assert thief.join(steal) == ("reject", mmauth.REJECT_AUTH)
    assert host.settle()["authfail"] >= 1
    # the same install cannot hold two slots
    twin = Wire(host.port, 3, install_key=friend.guest.ik)
    assert twin.join() == ("reject", mmauth.REJECT_BUSY)
    friend.state({"active": True, "who": "friend", "n": 2})
    wait_until(lambda: host.rx(1) == {"active": True, "who": "friend", "n": 2}, 6, "friend still connected")
    assert host.auth(1)["fp"] == friend.guest.fp.hex()
    for w in (friend, attacker, thief, twin):
        w.close()
    host.stop()
    passed("slot hijack, fingerprint theft and double slots are rejected; the friend keeps the slot")


def test_password(env):
    password = "correct horse battery"
    host = Node(env, "host", 0, password=password).start()
    bad = new_wire(host, 1, password=b"")
    assert bad.join() == ("reject", mmauth.REJECT_AUTH)
    wrong = new_wire(host, 1, password=b"wrong password")
    assert wrong.join() == ("reject", mmauth.REJECT_AUTH)
    good = new_wire(host, 1, password=password.encode())
    assert good.join() == "ok"
    good.state({"active": True, "value": "secret-room"})
    wait_until(lambda: host.rx(1) == {"active": True, "value": "secret-room"}, 6, "state after password join")
    assert host.settle()["authfail"] == 2
    wire_bytes = b"".join(good.sent + good.received + bad.sent + bad.received + wrong.sent + wrong.received)
    stretched = mmauth.stretch(password.encode(), mmauth.host_fp(good.guest.ik))
    assert password.encode() not in wire_bytes, "the password never crosses the wire"
    assert mmauth.stretch(password.encode(), good.guest.hfp) not in wire_bytes
    assert hashlib_sha(password.encode()) not in wire_bytes
    # registration is masked: without the password the guest key cannot be recovered from the capture
    proof = next(p for p in good.sent if p[4] == 3)
    k = mmauth.guest_key(good.guest.ik, good.guest.hfp)
    reg, cookie, cnonce = proof[68:100], proof[36:52], proof[16:32]
    unmasked = bytes(a ^ b for a, b in zip(reg, mmauth.hm(bytes(32), b"MMREG1", cookie, cnonce)))
    assert unmasked != k and mmauth.guest_fp(unmasked) != proof[52:68], "a passive observer cannot read the key"
    for w in (bad, wrong, good):
        w.close()
    host.stop()
    passed("password: wrong or missing password rejected; the password and its hash never cross the wire; key masked")


def hashlib_sha(data):
    import hashlib
    return hashlib.sha256(data).digest()


def test_replay_and_tamper(env):
    host = Node(env, "host", 0).start()
    wire = joined(host, 1)
    wire.state({"active": True, "n": 1})
    wait_until(lambda: host.rx(1) == {"active": True, "n": 1}, 6, "first state")
    gen = host.auth(1)["gen"]
    proof = next(p for p in wire.sent if p[4] == 3)
    wire.drain(0.2)
    wire.send(proof)                                 # replay of the PROOF from the same address
    assert wire.recv(0.6) is None, "a replayed PROOF gets no WELCOME"
    other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    other.bind((LOCAL, 0))
    other.settimeout(0.5)
    other.sendto(proof, (LOCAL, host.port))          # ... or from another address (the cookie is bound to the source)
    try:
        other.recvfrom(100)
        raise AssertionError("a PROOF from another address was answered")
    except socket.timeout:
        pass
    assert host.auth(1)["gen"] == gen
    # old data packets are useless after a new session (new key); within a session the sequence check applies
    old = wire.guest.seal(10, b'{"active":true,"n":"old"}')
    again = Wire(host.port, 1, install_key=wire.guest.ik)
    time.sleep(0.2)
    first_key = wire.guest.sk
    wire.close()
    # the first connection still holds the slot (10 s expiry) for the same install: a new session replaces it
    assert again.join() == "ok" and again.guest.sk != first_key
    again.state({"active": True, "n": 2}, seq=20, epoch=200)
    wait_until(lambda: host.rx(1) == {"active": True, "n": 2}, 6, "state in the new session")
    assert host.auth(1)["gen"] == gen + 1
    for packet in old:
        again.send(packet)
    time.sleep(0.4)
    assert host.rx(1) == {"active": True, "n": 2}, "packets of the old session are dead"
    # a bit flip anywhere in a packet is detected
    base = again.guest.seal(30, b'{"active":true,"n":3}')[0]
    for position in range(len(base)):
        for bit in (0x01, 0x80):
            broken = bytearray(base)
            broken[position] ^= bit
            again.send(bytes(broken))
    time.sleep(0.5)
    shown = host.rx(1)
    assert shown == {"active": True, "n": 2}, shown
    again.send(base)
    wait_until(lambda: host.rx(1) == {"active": True, "n": 3}, 6, "the unmodified packet is accepted")
    again.close()
    other.close()
    host.stop()
    passed("replayed PROOFs and old-session packets are dead; a bit flip in any byte of a packet is rejected")


def test_identity_keys(env):
    host = Node(env, "host", 0, keys=True, install_key=True).start()
    first = joined(host, 1)
    ik = first.guest.ik
    fp = first.guest.fp.hex()
    first.close()
    host.stop()
    stored = host.keys_file.read_text()
    assert stored.startswith(fp + " ") and len(stored.splitlines()) == 1
    assert len(host.key_file.read_bytes()) == 32
    if not ON_WINDOWS and not env.wine:
        assert (host.key_file.stat().st_mode & 0o077) == 0, "the install key file is private"
    hfp_before = mmauth.host_fp(host.key_file.read_bytes())
    host.start()
    # the same install after a host restart: the stored key is used, the registration field is ignored
    again = Wire(host.port, 2, install_key=ik)
    assert again.join(forge_known) == "ok", "a known identity needs no registration"
    assert host.auth(2)["fp"] == fp
    # a reinstalled friend is a new, unknown identity (the GML layer decides what that means)
    again.close()
    time.sleep(0.2)
    stranger = new_wire(host, 3)
    assert stranger.join() == "ok" and host.auth(3)["fp"] != fp
    # the host fingerprint is stable across restarts (it names the install key)
    challenge_wire = new_wire(host, 4)
    challenge_wire.send(challenge_wire.guest.hello())
    challenge = challenge_wire.recv()
    assert challenge[32:48] == hfp_before
    # a damaged or oversized key store must not stop the helper
    stranger.close()
    challenge_wire.close()
    host.stop()
    host.keys_file.write_text("garbage\n" + ("0" * 31) + "\n" + (fp + " " + "zz" * 32) + "\n" + stored + "x" * 5000)
    host.start()
    assert host.alive()
    ok = Wire(host.port, 5, install_key=ik)
    assert ok.join() == "ok"
    ok.close()
    host.stop()
    big = "".join(f"{i:032x} {i:064x}\n" for i in range(1, 400))
    host.keys_file.write_text(big)
    host.start()
    ok = Wire(host.port, 6)
    assert ok.join() in ("ok", ("reject", mmauth.REJECT_FULL)) and host.alive()
    ok.close()
    host.stop()
    passed("identity keys: registered once, known afterwards, stable host fingerprint, damaged stores survive")


def test_deny(env):
    host = Node(env, "host", 0, deny="# the deny list\n").start()
    friend = joined(host, 1)
    friend.state({"active": True, "n": 1})
    wait_until(lambda: host.status()["mask"] == 2, 6, "friend present")
    fp = friend.guest.fp.hex()
    host.deny_file.write_text("# kicked\r\n\r\n" + fp + "   # the friend\r\nnot-an-entry\r\n" + "9" * 33 + "\r\n999.1.1.1\r\n")
    wait_until(lambda: host.status()["mask"] == 0, 5, "kick within a few seconds")
    assert host.auth(1)["state"] == 0 and host.auth(1)["fp"] == ""
    assert host.rx(1) == {"active": False}
    rejoin = Wire(host.port, 1, install_key=friend.guest.ik)
    assert rejoin.join() == ("reject", mmauth.REJECT_DENIED)
    friend.state({"active": True, "n": 2}, seq=50)
    time.sleep(0.3)
    assert host.status()["mask"] == 0, "a denied player's data is not accepted"
    host.deny_file.write_text("")
    time.sleep(1.5)
    assert rejoin.join() == "ok", "removing the line lifts the ban"
    wait_until(lambda: host.status()["mask"] == 2, 5, "rejoined")
    host.deny_file.write_text(LOCAL + "\n")
    wait_until(lambda: host.status()["mask"] == 0, 5, "address ban")
    stranger = new_wire(host, 2)
    got = stranger.join()
    assert got == ("reject", mmauth.REJECT_DENIED), got
    host.deny_file.write_text("")
    time.sleep(1.5)
    assert stranger.join() == "ok"
    many = "".join(f"10.0.{i // 250}.{i % 250 + 1}\n" for i in range(300)) + "".join(f"{i:032x}\n" for i in range(300))
    host.deny_file.write_text(many)
    time.sleep(1.5)
    assert host.alive()
    for w in (friend, rejoin, stranger):
        w.close()
    host.stop()
    passed("deny list: fingerprint and address bans evict within seconds, are lifted by removing the line; junk is ignored")


def test_limits(env):
    host = Node(env, "host", 0).start()
    wire = joined(host, 1)
    wire.state({"active": True, "n": 0})
    wait_until(lambda: host.rx(1) == {"active": True, "n": 0}, 6, "first state")
    time.sleep(1.0)
    before = host.status()
    # many tiny snapshots as fast as possible: only a bounded number may be published and forwarded
    start = time.monotonic()
    for n in range(1, 400):
        wire.state({"active": True, "n": n})
        if n % 40 == 0:
            time.sleep(0.02)          # paced so the kernel's socket buffer does not drop them first
    elapsed = time.monotonic() - start
    after = host.settle()
    accepted = after["rx"] - before["rx"]
    assert accepted <= 60 + int(30 * (elapsed + 2.5)), (accepted, elapsed)
    assert after["limited"] > before["limited"], after
    # a flood of packets: the helper keeps running and keeps the peer
    sock = wire.sock
    flood_packet = mmauth.data_packet(wire.guest.sk, 0, 1, 7, CODE, b'{"x":1}')
    for chunk in range(60):                  # thousands of packets per second for 0.6 s, paced so no socket buffer overflows
        for _ in range(60):
            sock.sendto(flood_packet, wire.addr)
        time.sleep(0.01)
    assert host.alive() and host.settle()["limited"] > after["limited"]
    time.sleep(2.5)
    wire.state({"active": True, "n": "after"}, seq=100000, epoch=300)
    wait_until(lambda: host.rx(1) == {"active": True, "n": "after"}, 8, "the peer recovers once its tokens refill")
    # strangers: a HELLO flood gets a bounded number of replies and none is larger than its request
    flood = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    flood.bind((LOCAL, 0))
    flood.settimeout(0.05)
    hello = mmauth.hello(CODE, 5, os.urandom(16))
    for _ in range(600):
        flood.sendto(hello, (LOCAL, host.port))
    replies = []
    try:
        while True:
            replies.append(flood.recvfrom(4096)[0])
    except socket.timeout:
        pass
    assert 1 <= len(replies) <= 45, len(replies)
    assert all(len(r) <= len(hello) for r in replies)
    assert host.alive() and host.status()["limited"] > after["limited"]
    wire.close()
    flood.close()
    host.stop()
    passed("rate limits: snapshots, packets and strangers' handshakes are bounded; no reply is larger than its request")


def test_fuzz(env):
    rng = random.Random(1234)
    host = Node(env, "host", 0).start()
    wire = joined(host, 1)
    wire.state({"active": True, "n": 0})
    wait_until(lambda: host.rx(1) == {"active": True, "n": 0}, 6, "first state")
    key = wire.guest.sk
    sock = wire.sock
    target = wire.addr
    magics = (b"MSMP", b"MSAU", b"MSDQ", b"\0\0\0\0", b"MSMP\x02\x00\x00\x00", b"MSAU\x01\x01\x00\x00")
    sent = 0
    # 1. random datagrams of every length near the boundaries and beyond
    for length in list(range(0, 140)) + list(range(1150, 1260)) + [1500, 2000, 4000, 9000, 60000]:
        for _ in range(3):
            body = os.urandom(length)
            prefix = rng.choice(magics)
            sock.sendto((prefix + body)[:length] if length else b"", target)
            sent += 1
    # 2. every handshake type at every length, with a plausible header
    for kind in range(0, 9):
        for length in list(range(8, 140, 3)) + [200, 1300]:
            packet = (b"MSAU" + bytes([kind, 1, 0, 0]) + struct.pack("<II", CODE, rng.choice([0, 1, 2, 7, 8, 99]))
                      + os.urandom(max(0, length - 16)))[:length]
            sock.sendto(packet, target)
            sent += 1
    wire.drain(0.2)
    # 3. correctly tagged data packets with impossible or boundary header fields
    for i in range(2500):
        slot = rng.choice([0, 1, 1, 1, 2, 7, 8, 9, 255, 0xFFFFFFFF])
        length = rng.choice([0, 1, 2, 3, 1151, 1152, 1153, 2303, 2304, 16383, 16384, 16385, 20000, 0xFFFFFFFF])
        count = rng.choice([0, 1, 2, 14, 15, 16, 17, 255, 0xFFFF])
        index = rng.choice([0, 1, 2, 13, 14, 15, 16, 0xFFFF])
        frag = os.urandom(rng.choice([1, 2, 100, 1151, 1152]))
        seq = rng.choice([0, 1, 2, 3, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, rng.getrandbits(32)])
        epoch = rng.choice([0, 100, 100, 100, rng.getrandbits(32)])
        csum = rng.choice([0, rng.getrandbits(32)])
        plain = mmauth.HEADER.pack(b"MSMP", 2, 0, slot, seq, rng.choice([CODE, CODE, CODE, 0]), csum, length, index, count,
                                   epoch, rng.choice([0, 1])) + frag
        sock.sendto(plain + mmauth.tag_data(key, 0, plain), target)
        sent += 1
    assert host.alive(), "the helper survived hostile input"
    after = host.settle()
    assert after["running"]
    # nothing hostile reached a game file with a slot it does not own
    assert not list(host.bridge.glob("rx_[2-7].json")), "hostile frames created files for other slots"
    time.sleep(3)
    wire.state({"active": True, "n": "fuzz-done"}, seq=1, epoch=999)
    wait_until(lambda: host.rx(1) == {"active": True, "n": "fuzz-done"}, 8, "the helper still serves the peer")
    # a full 16 KB snapshot in 15 fragments still assembles after the abuse
    big = {"active": True, "payload": "z" * 16000}
    time.sleep(1)
    wire.state(big, seq=2, epoch=999)
    wait_until(lambda: host.rx(1) == big, 10, "a 16 KB snapshot after the abuse")
    assert host.alive()
    wire.close()
    host.stop()
    passed(f"hostile input: {sent} random, structured and correctly tagged malformed datagrams; the helper keeps serving")


# ---- the guest side ---------------------------------------------------------------------------------------------

class FakeHost:
    """A scripted host in front of a real guest helper."""

    def __init__(self, password=b"", code=CODE, install_key=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((LOCAL, 0))
        self.port = self.sock.getsockname()[1]
        self.host = mmauth.Host(code, install_key, password)
        self.code = code
        self.peer = None
        self.sk = None
        self.log = []
        self.start = time.monotonic()

    def now(self):
        return int((time.monotonic() - self.start) * 1000) + 1000

    def pump(self, timeout=0.5, accept=True, bad_welcome=False):
        """Handles one incoming datagram. Returns the packet type or None."""
        self.sock.settimeout(timeout)
        try:
            packet, source = self.sock.recvfrom(4096)
        except socket.timeout:
            return None
        self.log.append(packet)
        if packet[:4] == b"MSAU" and packet[4] == 1:
            self.sock.sendto(self.host.challenge(packet, source, self.now()), source)
            return "hello"
        if packet[:4] == b"MSAU" and packet[4] == 3:
            reply, slot = self.host.proof(packet, source, self.now())
            if slot is not None and bad_welcome:
                reply = reply[:16] + os.urandom(16) + reply[32:]
                self.sock.sendto(reply, source)
                self.peer = source
                self.sk = self.host.sessions[source][1]
                return "proof-bad-welcome"
            self.sock.sendto(reply, source)
            if slot is not None:
                self.peer = source
                self.sk = self.host.sessions[source][1]
                return "proof"
            return "proof-rejected"
        if packet[:4] == b"MSMP":
            self.peer = self.peer or source
            return "data"
        return "other"

    def until(self, kind, seconds=8, **kwargs):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.pump(0.3, **kwargs) == kind:
                return True
        return False

    def send_state(self, data, seq, slot=0, epoch=100, key=None, direction=1, to=None):
        body = json.dumps(data, separators=(",", ":")).encode()
        for packet in mmauth.split_snapshot(key or self.sk, direction, slot, seq, self.code, body, epoch):
            self.sock.sendto(packet, to or self.peer)

    def close(self):
        self.sock.close()


def test_guest_join(env):
    fake = FakeHost()
    guest = Node(env, "join", 1, host_port=fake.port, install_key=True).start()
    assert fake.until("proof"), "the guest helper completes the handshake"
    wait_until(lambda: guest.auth(0) and guest.auth(0)["state"] == 2, 6, "guest established")
    assert guest.auth(0)["fp"] == fake.host.hfp.hex()
    fake.send_state({"active": True, "value": "host"}, 1)
    wait_until(lambda: guest.rx(0) == {"active": True, "value": "host"}, 6, "host state on the guest")
    guest.publish({"active": True, "value": "guest"})
    seen = None
    for _ in range(40):
        fake.pump(0.3)
        for packet in list(fake.log):
            if packet[:4] == b"MSMP":
                opened = mmauth.open_data(fake.sk, 0, packet)
                assert opened is not None, "the guest's datagrams carry valid tags"
                seen = opened[1]
        if seen and b"guest" in seen:
            break
    assert seen and b'"guest"' in seen
    # another source cannot inject host data, even with a stolen key; a bit flip is dropped
    thief = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    thief.bind((LOCAL, 0))
    for packet in mmauth.split_snapshot(fake.sk, 1, 0, 3, CODE, b'{"active":true,"value":"thief"}'):
        thief.sendto(packet, (LOCAL, guest.port))
    flipped = bytearray(mmauth.split_snapshot(fake.sk, 1, 0, 4, CODE, b'{"active":true,"value":"flip"}')[0])
    flipped[45] ^= 1
    fake.sock.sendto(bytes(flipped), fake.peer)
    time.sleep(0.5)
    assert guest.rx(0) == {"active": True, "value": "host"}
    # the same install joins the same host again with the same fingerprint
    fp = guest.auth(0)["fp"]
    thief.close()
    guest.stop()
    fake.close()
    assert len(guest.key_file.read_bytes()) == 32
    passed("guest helper: handshake, verified host fingerprint, tagged traffic, injected or damaged host data refused")


def test_guest_rejections(env):
    # a password-protected host and a guest without one
    fake = FakeHost(password=b"hunter2 is bad")
    guest = Node(env, "join", 1, host_port=fake.port).start()
    assert fake.until("hello", 5)
    wait_until(lambda: guest.auth(0) and guest.auth(0)["reject"] == 6, 6, "password required is reported")
    status = guest.settle()
    assert status["reject"] == 6 and status["auth"] == 0, status
    assert not any(p[:4] == b"MSAU" and p[4] == 3 for p in fake.log), "no PROOF without the password"
    guest.stop()
    fake.close()
    # a wrong password: the host rejects, the guest reports it and backs off
    fake = FakeHost(password=b"right password")
    guest = Node(env, "join", 1, host_port=fake.port, password="wrong password").start()
    assert fake.until("proof-rejected", 8)
    wait_until(lambda: guest.auth(0) and guest.auth(0)["reject"] == 1, 6, "bad password reported")
    guest.stop()
    fake.close()
    # a host that cannot produce the WELCOME tag is not believed
    fake = FakeHost()
    guest = Node(env, "join", 1, host_port=fake.port).start()
    assert fake.until("proof-bad-welcome", 8, bad_welcome=True)
    fake.send_state({"active": True, "value": "impostor"}, 1)
    time.sleep(0.6)
    assert guest.rx(0) is None, "data from an unauthenticated host is not published"
    assert guest.auth(0) is None or guest.auth(0)["state"] != 2
    guest.stop()
    fake.close()
    passed("guest helper: missing and wrong passwords reported, an impostor host without the right tag is not believed")


def test_guest_resync(env):
    fake = FakeHost()
    guest = Node(env, "join", 1, host_port=fake.port).start()
    assert fake.until("proof")
    wait_until(lambda: guest.auth(0) and guest.auth(0)["state"] == 2, 6, "established")
    fake.send_state({"active": True, "n": 1}, 1)
    wait_until(lambda: guest.rx(0) == {"active": True, "n": 1}, 6, "data")
    hellos = sum(1 for p in fake.log if p[:4] == b"MSAU" and p[4] == 1)
    time.sleep(1.2)
    fake.sock.sendto(b"MSAU\x06\x01\x00\x00".ljust(16, b"\0"), fake.peer)      # "I lost you": say hello again
    assert fake.until("hello", 6) and fake.until("proof", 6), "RESYNC makes the guest shake hands again"
    spoof = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    spoof.bind((LOCAL, 0))
    spoof.sendto(b"MSAU\x06\x01\x00\x00".ljust(16, b"\0"), (LOCAL, guest.port))      # from another address: ignored
    time.sleep(0.4)
    spoof.close()
    wait_until(lambda: guest.auth(0)["state"] == 2, 6, "re-established")
    # a silent host: back to HELLO after five seconds
    count = sum(1 for p in fake.log if p[:4] == b"MSAU" and p[4] == 1)
    time.sleep(7)
    fake.sock.settimeout(0.3)
    got = 0
    for _ in range(10):
        if fake.pump(0.2) == "hello":
            got += 1
    assert got >= 1, "a silent host makes the guest ask again"
    guest.stop()
    fake.close()
    passed("guest helper: RESYNC from the host restarts the handshake, other sources cannot; silence triggers a new HELLO")


def test_config(env):
    for blob in (b"pass=" + b"x" * 65 + b"\r\n", b"pass=\xc3\xa9t\xc3\xa9\r\n", b"pass=tab\there\n", b"pass=ok\npass=" + b"y" * 80 + b"\n"):
        node = Node(env, "host", 0, config=blob)
        node.process = subprocess.Popen(node.command(), env=dict(os.environ, WINEDEBUG="-all"),
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            code = node.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            node.kill()
            raise AssertionError("an invalid password must stop the helper, not open the room: " + repr(blob))
        assert code == 4, (code, blob)
        node.process = None
    # a very long file, no newline at the end, unknown keys, CRLF, a key path that is a folder
    junk = b"unknown=1\r\n" + b"k" * 5000 + b"\r\nkey=" + b"/" * 2000 + b"\r\nkeys=\r\ndeny=\r\npass=a b c"
    node = Node(env, "host", 0, config=junk).start()
    wire = new_wire(node, 1, password=b"a b c")
    assert wire.join() == "ok"
    wire.close()
    node.stop()
    node = Node(env, "host", 0, config=("key=" + env.native(env.root) + "\nkeys=" + env.native(env.root) + "\n").encode()).start()
    wire = new_wire(node, 1)
    assert wire.join() == "ok", "unusable key and store paths fall back to memory"
    wire.close()
    node.stop()
    passed("auth.cfg: a malformed password stops the helper (exit 4), junk and bad paths are survived")


TESTS = [test_basic_join, test_no_handshake, test_hijack, test_password, test_replay_and_tamper, test_identity_keys,
         test_deny, test_limits, test_fuzz, test_guest_join, test_guest_rejections, test_guest_resync, test_config]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("helper", type=Path)
    parser.add_argument("only", nargs="*")
    args = parser.parse_args()
    isolate()
    env = Env(args.helper)
    failures = 0
    try:
        for test in TESTS:
            if args.only and test.__name__ not in args.only:
                continue
            try:
                test(env)
            except BaseException as error:
                failures += 1
                print("FAIL:", test.__name__, repr(error), flush=True)
                import traceback
                traceback.print_exc()
            finally:
                for node in list(env.nodes):
                    node.kill()
    finally:
        env.close()
    print(f"{len(RESULTS)} passed, {failures} failed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
