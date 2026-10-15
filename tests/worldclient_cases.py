"""Shared cases for the world-transfer download client (tests/test_world.py runs the Windows client under Wine,
tests/test_world_linux.py the Linux one). A fake host plays the server of docs/PROTOCOL.md: challenge, proof check, signed reply.

The client may download only after proving the key of a join session (the file <bridge>/world_<slot>.key that the helper
writes), and it believes the host only if the host's reply carries a valid tag.
"""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time

import mmauth

SLOT = 3


class FakeHost:
    def __init__(self, handler, wk):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 7775))
        self.sock.listen(1)
        self.sock.settimeout(40)
        self.handler = handler
        self.host = None
        self.connected = False
        self.thread = threading.Thread(target=self.run, args=(wk,), daemon=True)
        self.thread.start()

    def run(self, wk):
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        self.connected = True
        with conn:
            conn.settimeout(20)
            self.host = mmauth.WorldHost(conn, wk)
            try:
                self.handler(conn, self.host)
            except OSError:
                pass

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)   # wakes an accept() nobody connected to (close() alone would not release the port)
        except OSError:
            pass
        self.sock.close()
        self.thread.join(timeout=3)


def run(make_command, unsafe_names, check_unwritable):
    """make_command(dest, result, bridge, slot) -> (argv, env) for the client under test."""
    tmp = Path(tempfile.mkdtemp(prefix="worldtest-"))
    try:
        dest = tmp / "dest" / "saves"
        bridge = tmp / "bridge"
        bridge.mkdir()
        wk = mmauth.world_key(os.urandom(32))
        data = os.urandom(300_000)

        def fetch(dest, handler=None, key=wk, slot=SLOT):
            """Runs the client against a fake host that holds `wk`; the client's key file holds `key` (None: no file)."""
            result = tmp / "result.txt"
            if result.exists():
                result.unlink()
            keyfile = bridge / f"world_{slot}.key"
            if key is None:
                keyfile.unlink(missing_ok=True)
            else:
                keyfile.write_bytes(key)
            host = FakeHost(handler, wk) if handler else None
            argv, env = make_command(dest, result, bridge, slot)
            try:
                subprocess.run(argv, env=env, timeout=90, check=True, capture_output=True)
            finally:
                if host:
                    host.close()
            return int(result.read_text()), host

        def reply(conn, h, status=0, body=None, **fields):
            """The host's answer after a successful proof: signed header, then the file."""
            body = data if body is None else body
            conn.sendall(mmauth.world_sign(mmauth.world_header(status, body, **fields), h.wk, h.slot, h.cnonce, h.hnonce)
                         + (body if status == 0 else b""))

        def serve(status=0, **fields):
            def handler(conn, h):
                if h.handshake():
                    reply(conn, h, status, **fields)
                else:
                    h.refuse()
            return handler

        code, host = fetch(dest, serve())
        assert code == 0, code
        req = host.host.request
        assert req[:6] == b"MSWQ\x02" + bytes([SLOT]) and req[6:16] == bytes(10) and req[32:] == bytes(32), req
        assert (dest / "game-123-autosave.sav").read_bytes() == data, "file differs"
        assert not list(dest.glob("*.part")), "partial file left behind"
        print("fetch: 300 KB world downloaded intact after the proof, checksum verified, no partial file left")

        existing = (dest / "game-123-autosave.sav").read_bytes()

        code, _ = fetch(dest, serve(digest=b"\x00" * 32))
        assert code == 4, code
        assert (dest / "game-123-autosave.sav").read_bytes() == existing and not list(dest.glob("*.part"))
        print("fetch: wrong checksum rejected, the earlier copy is untouched")

        for name in unsafe_names:
            code, _ = fetch(dest, serve(name=name))
            assert code == 3, (name, code)
        assert sorted(p.name for p in dest.iterdir()) == ["game-123-autosave.sav"], "an unsafe name created a file"
        print("fetch: unsafe file names rejected (paths, traversal, wrong pattern)")

        code, _ = fetch(dest, serve(status=1, body=b""))
        assert code == 2, code

        def short(conn, h):
            if h.handshake():
                conn.sendall(mmauth.world_sign(mmauth.world_header(0, data), h.wk, h.slot, h.cnonce, h.hnonce) + data[:1000])
        code, _ = fetch(dest, short)
        assert code == 3 and not list(dest.glob("*.part")), code
        code, _ = fetch(dest, serve(body=b"", length=500_000_000))
        assert code == 3, code
        code, _ = fetch(dest, serve(body=b"", length=0))
        assert code == 3, code
        print("fetch: no-world, truncated, oversized and empty replies handled")

        # ---- authentication ----
        seen = []

        def record(conn, h):
            assert h.handshake()
            seen.append((h.proof, h.hnonce, h.cnonce))
            reply(conn, h)
        assert fetch(dest, record)[0] == 0 and fetch(dest, record)[0] == 0
        (p1, n1, c1), (p2, n2, c2) = seen
        assert n1 != n2 and c1 != c2 and p1 != p2, "the proof must differ for every connection"
        print("fetch: the proof changes with every connection (fresh nonces on both sides)")

        for label, key in (("no key file", None), ("an all-zero key (the helper's no-session marker)", bytes(32)), ("a short key file", wk[:20]),
                           ("an over-long key file", wk + b"x")):
            code, host = fetch(dest, serve(), key=key)
            assert code == 7 and not host.connected, (label, code, host.connected)
        print("fetch: no session key, a zero, short or long key file -> refused (7) without even connecting")

        refused = []

        def strict(conn, h):
            if h.handshake():
                reply(conn, h)
            else:
                refused.append(True)
                h.refuse()
        before = sorted(p.name for p in dest.iterdir())
        code, _ = fetch(dest, strict, key=os.urandom(32))
        assert code == 7 and refused, (code, refused)
        assert sorted(p.name for p in dest.iterdir()) == before
        code, _ = fetch(dest, strict, key=mmauth.world_key(os.urandom(32)))
        assert code == 7
        print("fetch: a client with the wrong session key is refused by the host and writes nothing")

        def forge(tag):
            def handler(conn, h):
                h.handshake()
                conn.sendall(mmauth.world_header(0, data) + tag(h) + data)
            return handler
        for label, tag in (("random tag", lambda h: os.urandom(32)), ("no tag", lambda h: bytes(32)),
                           ("tag of another connection", lambda h: mmauth.world_reply_tag(h.wk, h.slot, h.cnonce, os.urandom(16), mmauth.world_header(0, data))),
                           ("tag for another slot", lambda h: mmauth.world_reply_tag(h.wk, h.slot + 1, h.cnonce, h.hnonce, mmauth.world_header(0, data)))):
            code, _ = fetch(dest, forge(tag))
            assert code == 7, (label, code)

        def flipped(conn, h):                         # "no world" edited into "ok, here is a file" after signing
            h.handshake()
            signed = bytearray(mmauth.world_sign(mmauth.world_header(1), h.wk, h.slot, h.cnonce, h.hnonce))
            signed[5] = 0
            signed[8:12] = len(data).to_bytes(4, "little")
            conn.sendall(bytes(signed) + data)
        code, _ = fetch(dest, flipped)
        assert code == 7, code
        assert (dest / "game-123-autosave.sav").read_bytes() == existing
        print("fetch: a reply without a valid host tag (impostor, unsigned, replayed, wrong slot, edited) is never believed")

        def refusal(conn, h):
            h.handshake()
            h.refuse()
        assert fetch(dest, refusal)[0] == 7

        def old_host(conn, h):                        # an old host: reads 16 bytes, wants version 1, hangs up
            mmauth.recv_exact(conn, 16)
        t0 = time.time()
        code, _ = fetch(dest, old_host)
        assert code == 7 and time.time() - t0 < 10, (code, time.time() - t0)

        def junk(conn, h):
            mmauth.recv_exact(conn, 64)
            conn.sendall(os.urandom(144))
        assert fetch(dest, junk)[0] == 7

        def bad_challenge(conn, h):
            mmauth.recv_exact(conn, 64)
            conn.sendall(b"MSWC\x02\x07" + bytes(26))
        assert fetch(dest, bad_challenge)[0] == 7
        print("fetch: refusals, old hosts, junk and a malformed challenge -> clear refusal (7), no hang")

        if check_unwritable:
            blocker = tmp / "blocker"
            blocker.write_text("a file, not a folder")
            code, _ = fetch(blocker / "saves", serve())
            assert code == 5, code
            print("fetch: unwritable destination -> clean failure")

        code, _ = fetch(dest, None)
        assert code == 1, code
        print("fetch: nobody listening -> clean failure")

        def stall(conn, h):
            if h.handshake():
                conn.sendall(mmauth.world_sign(mmauth.world_header(0, data), h.wk, h.slot, h.cnonce, h.hnonce) + data[:100])
            time.sleep(25)
        t0 = time.time()
        code, _ = fetch(dest, stall)
        assert code == 3 and time.time() - t0 < 40, (code, time.time() - t0)
        print("fetch: a host that stalls is abandoned after the timeout")

        def never_answers(conn, h):
            time.sleep(25)
        t0 = time.time()
        code, _ = fetch(dest, never_answers)
        assert code == 7 and time.time() - t0 < 40, (code, time.time() - t0)
        print("PASS")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
