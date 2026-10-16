"""Shared cases for the launcher's world server (TCP 7775), used by tests/test_launcher.py (Windows launcher under Wine) and
tests/test_launcher_linux.py (native). The launcher releases the world only to a client that proves the key of a join session
the host's helper authenticated (the file <bridge>/world_<slot>.key); everything else gets a refusal and not one byte of the world.

The tests play both the helper (they write the key files) and the client (tests/mmauth.py holds the reference protocol).
The real helper-to-launcher link is covered end to end by tests/test_menu.py and test_guest_refreshes_world.
"""
import hashlib
import os
import socket
import time

import mmauth

ADDRESS = ("127.0.0.1", 7775)


def talk(slot, key, request=None, proof=None, send_proof=True, mutate=None, timeout=15):
    """The client side by hand. Returns (challenge, answer, cnonce, proof_sent): answer = everything the host sent after the
    proof (or after the request when no proof is sent) until it closed the connection, None if it could not connect."""
    try:
        sock = socket.create_connection(ADDRESS, timeout=timeout)
    except OSError:
        return None, None, None, None
    try:
        cnonce = os.urandom(16)
        sock.sendall(request if request is not None else mmauth.world_request(slot, cnonce))
        challenge = mmauth.recv_exact(sock, mmauth.WORLD_CHALLENGE)
        if len(challenge) != mmauth.WORLD_CHALLENGE:
            return challenge, b"", cnonce, None
        if request is not None:
            cnonce = request[16:32]
        if proof is None:
            proof = mmauth.world_proof(key, slot, cnonce, challenge[16:32])
        if mutate is not None:
            proof = mutate(proof)
        if send_proof:
            sock.sendall(proof)
        answer = b""
        while True:
            try:
                chunk = sock.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            answer += chunk
        return challenge, answer, cnonce, proof
    except OSError:
        return None, b"", None, None
    finally:
        sock.close()


def probe(timeout=10):
    """Is the world server up? Sends an old-style request and returns the answer (a version-1 refusal, 112 bytes), or b""."""
    try:
        sock = socket.create_connection(ADDRESS, timeout=timeout)
    except OSError:
        return b""
    try:
        sock.sendall(b"MSWQ\x01" + b"\x00" * 11)
        return mmauth.recv_exact(sock, 112)
    except OSError:
        return b""
    finally:
        sock.close()


def download(slot, key):
    challenge, answer, cnonce, _ = talk(slot, key)
    return challenge, answer, cnonce


def is_world(answer, wk, slot, cnonce, hnonce, body):
    """True if `answer` is a correctly signed status-0 reply followed by exactly `body`."""
    return (len(answer) == 144 + len(body) and answer[:4] == b"MSWR" and answer[4] == 2 and answer[5] == 0
            and answer[144:] == body
            and answer[112:144] == mmauth.world_reply_tag(wk, slot, cnonce, hnonce, answer[:112]))


def refused(answer):
    """A refusal: exactly one 144-byte header, status 3, nothing else (no tag, no file bytes)."""
    return answer is not None and len(answer) == 144 and answer[:5] == b"MSWR\x02" and answer[5] == 3 and answer[112:] == bytes(32)


def prepare(mp, bridge, linux):
    """Saves for the host to serve and the session keys the helper would hold for guests 2 and 6 -> (world bytes, wk2, wk6)."""
    mp.mkdir(parents=True, exist_ok=True)
    old = os.urandom(50_000)
    new = os.urandom(200_000)
    (mp / "game-1-autosave.sav").write_bytes(old)
    (mp / "game-2-autosave.sav").write_bytes(new)
    (mp / "game-3-autosave.old.sav").write_bytes(b"newest but not a valid save name")
    (mp / "notes.txt").write_bytes(b"x")
    os.utime(mp / "game-1-autosave.sav", (1_700_000_000, 1_700_000_000))
    os.utime(mp / "game-2-autosave.sav", (1_700_000_100, 1_700_000_100))
    os.utime(mp / "game-3-autosave.old.sav", (1_700_000_200, 1_700_000_200))
    if linux:
        (mp / "game-9-7.sav").mkdir()
        os.utime(mp / "game-9-7.sav", (1_700_000_300, 1_700_000_300))
    # what the helper does when it authenticates guests 2 and 6: one session key each
    sk2, sk6 = os.urandom(32), os.urandom(32)
    wk2, wk6 = mmauth.world_key(sk2), mmauth.world_key(sk6)
    (bridge / "world_2.key").write_bytes(wk2)
    (bridge / "world_6.key").write_bytes(wk6)
    return new, wk2, wk6


def served(new, wk2):
    challenge, answer, cnonce = download(2, wk2)
    return answer is not None and len(challenge or b"") == 32 and is_world(answer, wk2, 2, cnonce, challenge[16:32], new)


def must_refuse(label, slot, key, **kw):
    _, answer, _, _ = talk(slot, key, **kw)
    assert refused(answer), (label, None if answer is None else (len(answer), answer[:8]))


def check_server(mp, bridge, wait_for, linux):
    """The launcher is hosting (its bridge folder is `bridge`, its saves folder `mp`). Runs the quick server cases (a game
    started with --slow lives 12 seconds; the cases that wait for a timeout are in check_server_slow)."""
    new, wk2, wk6 = prepare(mp, bridge, linux)
    assert wait_for(lambda: served(new, wk2), 10), "the world server never served an authenticated client"
    challenge, answer, cnonce = download(2, wk2)
    assert challenge[:6] == b"MSWC\x02\x00" and challenge[6:16] == bytes(10), challenge
    assert answer[:4] == b"MSWR" and answer[4] == 2 and answer[5] == 0, answer[:8]
    assert int.from_bytes(answer[8:12], "little") == len(new)
    assert answer[12:44] == hashlib.sha256(new).digest()
    assert answer[48:112].split(b"\x00")[0] == b"game-2-autosave.sav", answer[48:80]
    assert is_world(answer, wk2, 2, cnonce, challenge[16:32], new)
    challenge6, answer6, cnonce6 = download(6, wk6)
    assert is_world(answer6, wk6, 6, cnonce6, challenge6[16:32], new), "a second joined player gets the world with its own key"
    print("world server: newest valid save is sent to a client that proved its session key (two players, two keys), reply signed, look-alikes ignored")

    # ---- credentials: wrong, missing, someone else's, malformed -> nothing ----
    must_refuse("wrong key", 2, os.urandom(32))
    must_refuse("another player's key", 2, wk6)
    must_refuse("right key, wrong slot", 6, wk2)
    must_refuse("no key file for this slot", 5, wk2)
    must_refuse("slot 0 (the host itself)", 0, wk2)
    (bridge / "world_0.key").write_bytes(wk2)
    must_refuse("slot 0 even with a key file", 0, wk2)
    must_refuse("slot 8", 8, wk2)
    must_refuse("slot 255", 255, wk2)
    (bridge / "world_4.key").write_bytes(bytes(32))
    must_refuse("an all-zero key file (the helper's no-session marker) with the zero key", 4, bytes(32))
    (bridge / "world_4.key").write_bytes(wk2[:31])
    must_refuse("a short key file", 4, wk2[:31])
    (bridge / "world_4.key").write_bytes(b"")
    must_refuse("an empty key file", 4, bytes(32))
    (bridge / "world_4.key").unlink()
    must_refuse("a flipped tag bit", 2, wk2, mutate=lambda p: p[:20] + bytes([p[20] ^ 1]) + p[21:])
    must_refuse("a flipped last tag bit", 2, wk2, mutate=lambda p: p[:47] + bytes([p[47] ^ 0x80]))
    print("world server: wrong, foreign, missing, zero, short and malformed credentials get a refusal and not one byte of the world")

    # ---- replay: a recorded exchange is useless on a new connection ----
    challenge, answer, cn, proof = talk(2, wk2)
    assert is_world(answer, wk2, 2, cn, challenge[16:32], new)
    recorded_request = mmauth.world_request(2, cn)
    _, answer, _, _ = talk(2, wk2, request=recorded_request, proof=proof)
    assert refused(answer), "a recorded request and proof must not work again (the host nonce is new every time)"
    _, answer, _, _ = talk(2, wk2, request=recorded_request, proof=proof)
    assert refused(answer)
    print("world server: replaying a recorded request and proof is refused (fresh host nonce per connection)")

    # ---- nothing before the proof ----
    sock = socket.create_connection(ADDRESS, timeout=10)
    sock.sendall(mmauth.world_request(2, os.urandom(16)))
    got = mmauth.recv_exact(sock, 32)
    assert len(got) == 32 and got[:4] == b"MSWC"
    sock.settimeout(1.5)
    try:
        extra = sock.recv(10)
    except socket.timeout:
        extra = b""
    assert extra == b"", "the host must send nothing but the challenge before the proof"
    sock.close()
    print("world server: only the challenge is sent before the proof")

    # ---- old and malformed clients ----
    t0 = time.time()
    old_style = None
    sock = socket.create_connection(ADDRESS, timeout=10)
    sock.sendall(b"MSWQ\x01" + b"\x00" * 11)
    old_style = b""
    sock.settimeout(10)
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        old_style += chunk
    sock.close()
    assert time.time() - t0 < 3, "an old client must be refused at once, not left waiting"
    assert len(old_style) == 112 and old_style[:5] == b"MSWR\x01" and old_style[5] == 3 and old_style[8:12] == bytes(4), old_style[:16]
    assert old_style[12:48] == bytes(36)
    print("world server: an old (unauthenticated, version 1) request is refused at once with a version-1 status-3 header and no world data")

    # a well-formed request, a proof with the wrong magic or version
    for mangle in (lambda p: b"XXXX" + p[4:], lambda p: p[:4] + b"\x01" + p[5:], lambda p: p[:4] + b"\x03" + p[5:]):
        must_refuse("a proof with the wrong magic or version", 2, wk2, mutate=mangle)
    assert served(new, wk2)
    print("world server: wrong magic or version in the proof is refused; the server keeps serving")

    # ---- the helper rotates the key (the guest rejoined): the old key stops working ----
    wk2b = mmauth.world_key(os.urandom(32))
    (bridge / "world_2.key").write_bytes(wk2b)
    must_refuse("the previous session's key", 2, wk2)
    challenge, answer, cn = download(2, wk2b)
    assert is_world(answer, wk2b, 2, cn, challenge[16:32], new)
    (bridge / "world_2.key").write_bytes(bytes(32))                                       # the guest left
    must_refuse("a session that ended", 2, wk2b)
    (bridge / "world_2.key").write_bytes(wk2)
    print("world server: a rotated or ended session key stops working at once")

    # ---- a client that hangs up, a client that is silent ----
    if linux:
        for _ in range(3):
            quitter = socket.socket()
            quitter.connect(ADDRESS)
            quitter.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")   # reset instead of a clean close
            quitter.sendall(mmauth.world_request(2, os.urandom(16)))
            quitter.close()
        time.sleep(0.5)
        assert served(new, wk2), "the world server died after a client reset the connection"
    # ---- nothing to give: a signed status 1, after the proof ----
    for f in mp.iterdir():
        if f.is_dir():
            f.rmdir()
        else:
            f.unlink()
    challenge, answer, cn = download(2, wk2)
    assert len(answer) == 144 and answer[5] == 1, answer[:8]
    assert answer[112:] == mmauth.world_reply_tag(wk2, 2, cn, challenge[16:32], answer[:112]), "'no world yet' is signed too"
    must_refuse("no world and no credentials", 2, os.urandom(32))
    print("world server: with nothing to give the answer is a signed status 1; credentials are checked first")


class JoinedHost:
    """A scripted host in front of a real guest helper: answers the UDP join handshake (tests/mmauth.py) on `port` and then
    serves the world over TCP 7775 to the one client that proves the session key, exactly as the real host would."""

    def __init__(self, port, data, name=b"game-77-autosave.sav", code=0x4D495354, password=b""):
        import threading
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", port))
        self.tcp = socket.socket()
        self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp.bind(ADDRESS)
        self.tcp.listen(4)
        self.data, self.name = data, name
        self.host = mmauth.Host(code, password=password)
        self.sk = None
        self.slot = None
        self.served = 0
        self.refused = 0
        self.stop = False
        self.t_udp = threading.Thread(target=self.run_udp, daemon=True)
        self.t_tcp = threading.Thread(target=self.run_tcp, daemon=True)
        self.t_udp.start()
        self.t_tcp.start()
        self.start = time.monotonic()

    def now(self):
        return int((time.monotonic() - self.start) * 1000) + 1000

    def run_udp(self):
        self.udp.settimeout(0.3)
        while not self.stop:
            try:
                packet, source = self.udp.recvfrom(4096)
            except OSError:
                continue
            if packet[:4] != b"MSAU":
                continue
            if packet[4] == 1:
                self.udp.sendto(self.host.challenge(packet, source, self.now()), source)
            elif packet[4] == 3:
                reply, slot = self.host.proof(packet, source, self.now())
                if reply:
                    self.udp.sendto(reply, source)
                if slot is not None:
                    self.slot, self.sk = slot, self.host.sessions[source][1]

    def run_tcp(self):
        self.tcp.settimeout(0.3)
        while not self.stop:
            try:
                conn, _ = self.tcp.accept()
            except OSError:
                continue
            with conn:
                conn.settimeout(10)
                try:
                    if self.sk is None:
                        continue
                    host = mmauth.WorldHost(conn, mmauth.world_key(self.sk), slots=[self.slot])
                    if host.handshake():
                        host.reply(mmauth.world_header(0, self.data, name=self.name))
                        conn.sendall(self.data)
                        self.served += 1
                    else:
                        host.refuse()
                        self.refused += 1
                except OSError:
                    pass

    def close(self):
        self.stop = True
        self.t_udp.join(timeout=3)
        self.t_tcp.join(timeout=3)
        self.udp.close()
        self.tcp.close()


def check_server_slow(mp, bridge, wait_for, linux):
    """The cases that wait for the server's 3 second read timeouts, in a second hosting session."""
    new, wk2, wk6 = prepare(mp, bridge, linux)
    assert wait_for(lambda: served(new, wk2), 10), "the world server never served an authenticated client"
    # a proof that never comes, or comes cut short: the host gives up on the connection, sends nothing, and serves the next client
    sock = socket.create_connection(ADDRESS, timeout=10)
    sock.sendall(mmauth.world_request(2, os.urandom(16)))
    mmauth.recv_exact(sock, 32)
    t0 = time.time()
    sock.settimeout(15)
    rest = sock.recv(10)
    assert rest == b"" and time.time() - t0 < 8, (rest, time.time() - t0)
    sock.close()
    _, answer, _, _ = talk(2, wk2, mutate=lambda p: p[:47])
    assert answer == b"", answer[:16]
    assert served(new, wk2)
    print("world server: a client that never answers the challenge, or cuts its proof short, is dropped without a byte of the world")

    silent = socket.socket()
    silent.connect(ADDRESS)
    t0 = time.time()
    challenge, answer, cn = download(2, wk2)
    silent.close()
    assert is_world(answer, wk2, 2, cn, challenge[16:32], new) and time.time() - t0 < 10, time.time() - t0
    print("world server: a client that connects and says nothing does not block later clients for long")



def check_server_junk(mp, bridge, wait_for, linux):
    """Truncated and wrong requests (each waits for the server's 3 second read timeout), in a third hosting session."""
    new, wk2, wk6 = prepare(mp, bridge, linux)
    assert wait_for(lambda: served(new, wk2), 10), "the world server never served an authenticated client"
    def silent_ok(payload):
        s = socket.create_connection(ADDRESS, timeout=10)
        try:
            s.sendall(payload)
            s.settimeout(10)
            got = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                got += chunk
            return got
        except OSError:
            return b""
        finally:
            s.close()
    assert silent_ok(b"MSWQ\x09" + b"\x00" * 11) == b""
    assert silent_ok(b"XXXX\x02" + b"\x00" * 11) == b""
    assert silent_ok(b"short") == b""
    assert silent_ok(b"MSWQ\x02" + b"\x02" + b"\x00" * 10 + b"junk") == b""      # a truncated version-2 request
    wrong = bytearray(mmauth.world_request(2, os.urandom(16)))
    assert silent_ok(bytes(wrong[:20])) == b""
    assert served(new, wk2)
    print("world server: junk, truncated and wrong-version requests get nothing; the server keeps serving")


class KeyFileWorldServer:
    """A world server in front of a REAL host helper: it holds no key of its own and reads `<bridge>/world_<slot>.key` that the
    helper wrote for each authenticated guest, exactly as the real launcher does."""

    def __init__(self, bridge, data, name=b"game-77-autosave.sav", status=0, info_flags=0, host_world=0):
        import threading
        self.bridge, self.data, self.name = bridge, data, name
        self.status, self.info_flags, self.host_world = status, info_flags, host_world      # what the header says (the world info extension)
        self.tcp = socket.socket()
        self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp.bind(ADDRESS)
        self.tcp.listen(4)
        self.tcp.settimeout(0.3)
        self.stop = False
        self.served = []
        self.refused = 0
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def key_for(self, slot):
        try:
            key = (self.bridge / f"world_{slot}.key").read_bytes()
        except OSError:
            return None
        return key if len(key) == 32 and key != bytes(32) else None

    def run(self):
        while not self.stop:
            try:
                conn, _ = self.tcp.accept()
            except OSError:
                continue
            with conn:
                conn.settimeout(10)
                try:
                    host = mmauth.WorldHost(conn, self.key_for)
                    if host.handshake():
                        if self.status == 0:
                            host.reply(mmauth.world_header(0, self.data, name=self.name, info_flags=self.info_flags, host_world=self.host_world))
                            conn.sendall(self.data)
                        else:
                            host.reply(mmauth.world_header(self.status, info_flags=self.info_flags, host_world=self.host_world))
                        self.served.append(host.slot)
                    else:
                        host.refuse()
                        self.refused += 1
                except OSError:
                    pass

    def close(self):
        self.stop = True
        self.thread.join(timeout=3)
        self.tcp.close()


def query_flags(port=7776):
    """The discovery answer's flags byte of the host on this computer, or None."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    try:
        sock.sendto(b"MSDQ\x01" + b"\x00" * 59, ("127.0.0.1", port))
        reply = sock.recvfrom(256)[0]
        return reply[5] if len(reply) == 64 and reply[:4] == b"MSDR" else None
    except OSError:
        return None
    finally:
        sock.close()


def check_world_info(mp, bridge, note, wait_for, linux):
    """The world info extension (docs/PROTOCOL.md, "World info"): `note` is the host's menu/world.txt, written by the mod. Without it the
    server behaves as before (newest save, no info). With it only that world's saves count, the signed header names the world and says
    whether it is saved (byte 6, u32 at 44), a world that was never saved gets a signed status 4, and discovery says the same in flags
    bits 2 and 3."""
    new, wk2, wk6 = prepare(mp, bridge, linux)                      # game-1 (older), game-2 (newest), look-alikes
    (mp / "game-1-5.sav").write_bytes(b"one-five " * 50)
    os.utime(mp / "game-1-5.sav", (1_700_000_050, 1_700_000_050))   # a manual save of world 1, newer than its autosave

    def header():
        challenge, answer, cnonce = download(2, wk2)
        assert answer is not None and len(challenge or b"") == 32 and len(answer) >= 144, answer
        assert answer[112:144] == mmauth.world_reply_tag(wk2, 2, cnonce, challenge[16:32], answer[:112]), "the world info must be signed"
        return answer[5], answer[6], int.from_bytes(answer[44:48], "little"), answer[48:112].split(b"\x00")[0], answer[144:]

    assert wait_for(lambda: served(new, wk2), 10), "the world server never served"
    note.unlink(missing_ok=True)
    assert header() == (0, 0, 0, b"game-2-autosave.sav", new), "no world.txt: the newest save, no world info (the old behaviour)"
    assert wait_for(lambda: query_flags() == 0, 5), query_flags()
    note.write_text("id=1\n")
    status, flags, hid, name, body = header()
    assert (status, flags, hid, name, body) == (0, 3, 1, b"game-1-5.sav", b"one-five " * 50), (status, flags, hid, name)
    assert wait_for(lambda: query_flags() == 12, 5), ("discovery: a named, saved world is flags 4 + 8", query_flags())
    note.write_text("id=424242\n")                                   # the host plays a world it never saved
    assert wait_for(lambda: header()[:3] == (4, 1, 424242), 5), header()[:3]
    status, flags, hid, name, body = header()
    assert body == b"" and name == b"", "an unsaved world sends no file, not even someone else's"
    assert wait_for(lambda: query_flags() == 4, 5), ("discovery: a named, unsaved world is flags 4", query_flags())
    note.write_text("id=2\n")
    assert wait_for(lambda: header() == (0, 3, 2, b"game-2-autosave.sav", new), 5), header()[:4]
    for junk in (b"id=abc", b"id=0\n", b"id=99999999999\n", b"id=2147483648\n", b"xx id=2\n", b"", b"id=-3", b"id=" + b"9" * 500, bytes(range(1, 60))):
        note.write_bytes(junk)
        assert header() == (0, 0, 0, b"game-2-autosave.sav", new), ("unusable note -> the old behaviour", junk[:20], header()[:4])
    note.write_text("id=2 trailing words\n")
    assert header()[:3] == (0, 3, 2), "the id is the digits after id="
    note.unlink()
    assert header()[:3] == (0, 0, 0)
    print("world info: no note = newest save; a note limits the server to that world's newest save (manual or auto) and signs its id and saved flag; "
          "an unsaved world gets a signed status 4 and no file; discovery flags 4/8; junk notes change nothing")
