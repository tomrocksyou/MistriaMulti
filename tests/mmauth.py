"""Reference implementation of the MistriaMulti join handshake and packet tags (docs/SECURITY.md).

This is the executable specification the assembly helper is tested against, in both roles: `Guest` talks to a
real host helper, `Host` plays the host for a real guest helper. It must stay byte-compatible with
helper/include/auth.inc.
"""
import hashlib
import hmac
import os
import struct

PW_ROUNDS = 30000
HEADER = struct.Struct("<4sHHIIIIIHHII")
TAG = 16
WINDOW_MS = 20000

REJECT_AUTH, REJECT_DENIED, REJECT_BUSY, REJECT_FULL, REJECT_RATE, REJECT_PASSWORD = 1, 2, 3, 4, 5, 6


def hm(key, *parts):
    return hmac.new(key, b"".join(parts), hashlib.sha256).digest()


def fingerprint(label, data):
    return hashlib.sha256(label + data).digest()[:16]


def stretch(password, hfp):
    if not password:
        return bytes(32)
    x = bytes(32)
    tail = hfp + password
    for _ in range(PW_ROUNDS):
        x = hashlib.sha256(x + tail).digest()
    return x


def host_fp(install_key):
    return fingerprint(b"MMFP1", install_key)


def guest_key(install_key, hfp):
    return hm(install_key, b"MMBIND1", hfp)


def guest_fp(k):
    return fingerprint(b"MMFP2", k)


def header(kind):
    return b"MSAU" + bytes([kind, 1, 0, 0])


def reject(reason, code):
    return (header(5) + struct.pack("<II", reason, code)).ljust(16, b"\0")


def hello(code, slot, cnonce):
    return (header(1) + struct.pack("<II", code, slot) + cnonce).ljust(128, b"\0")


def tag_data(key, direction, plain):
    return hm(key, bytes([direction]), plain)[:TAG]


def data_packet(key, direction, slot, seq, code, payload, epoch=100, count=None, index=0, total=None, frag=None):
    """One fragment. `payload` is the whole snapshot unless `frag` (bytes) and `total` are given."""
    total = len(payload) if total is None else total
    frag = payload if frag is None else frag
    count = (total + 1151) // 1152 if count is None else count
    csum = 2166136261
    for byte in payload:
        csum = ((csum ^ byte) * 16777619) & 0xFFFFFFFF
    plain = HEADER.pack(b"MSMP", 2, 0, slot, seq, code, csum, total, index, count, epoch, 0) + frag
    return plain + tag_data(key, direction, plain)


def split_snapshot(key, direction, slot, seq, code, payload, epoch=100):
    count = (len(payload) + 1151) // 1152
    return [data_packet(key, direction, slot, seq, code, payload, epoch, count, i, len(payload),
                        payload[i * 1152:(i + 1) * 1152]) for i in range(count)]


def open_data(key, direction, packet):
    """Returns the parsed header tuple and payload fragment if the tag is valid, else None."""
    if len(packet) < 40 + TAG + 1:
        return None
    plain, tag = packet[:-TAG], packet[-TAG:]
    if not hmac.compare_digest(tag_data(key, direction, plain), tag):
        return None
    return HEADER.unpack(plain[:40]), plain[40:]


class Guest:
    """The guest side of the handshake."""

    def __init__(self, code, slot, install_key=None, password=b""):
        self.code, self.slot = code, slot
        self.ik = install_key or os.urandom(32)
        self.password = password
        self.cnonce = os.urandom(16)
        self.sk = None
        self.expect = None
        self.hfp = None

    def hello(self):
        self.cnonce = os.urandom(16)
        return hello(self.code, self.slot, self.cnonce)

    def proof(self, challenge, password=None, cookie=None):
        """Builds the PROOF for a CHALLENGE packet; returns None when it is not one for this guest.
        `cookie` replaces the host's cookie (a test for a guest that never received one)."""
        if len(challenge) != 64 or challenge[:6] != header(2)[:6] or challenge[48:64] != self.cnonce:
            return None
        flags, window = struct.unpack_from("<II", challenge, 8)
        cookie, self.hfp = cookie or challenge[16:32], challenge[32:48]
        pw = self.password if password is None else password
        pwk = stretch(pw, self.hfp) if flags & 1 else bytes(32)
        k = guest_key(self.ik, self.hfp)
        fp = guest_fp(k)
        mask = hm(pwk, b"MMREG1", cookie, self.cnonce)
        reg = bytes(a ^ b for a, b in zip(k, mask))
        ak = hm(pwk, k)
        body = struct.pack("<II", self.code, self.slot) + self.cnonce + struct.pack("<I", window) + cookie + fp + reg
        tag = hm(ak, b"MMPROOF1", body, self.hfp)[:16]
        self.sk = hm(ak, b"MMSK1", self.cnonce, cookie)
        self.expect = hm(ak, b"MMWELCOME1", self.cnonce, cookie, struct.pack("<I", self.slot))[:16]
        self.fp = fp
        return (header(3) + body + tag).ljust(128, b"\0")

    def welcome(self, packet):
        return len(packet) == 48 and packet[:6] == header(4)[:6] and hmac.compare_digest(packet[16:32], self.expect)

    def seal(self, seq, payload, epoch=100):
        return split_snapshot(self.sk, 0, self.slot, seq, self.code, payload, epoch)

    def open(self, packet):
        return open_data(self.sk, 1, packet)


class Host:
    """The host side, for tests that put a real guest helper in front of a script."""

    def __init__(self, code, install_key=None, password=b""):
        self.code = code
        self.ik = install_key or os.urandom(32)
        self.hfp = host_fp(self.ik)
        self.password = password
        self.pwk = stretch(password, self.hfp)
        self.secret = os.urandom(32)
        self.keys = {}          # guest fingerprint -> K
        self.sessions = {}      # address -> (slot, sk)

    def cookie(self, window, addr, slot, cnonce):
        port_ip = struct.pack(">H", addr[1]) + bytes(int(x) for x in addr[0].split("."))
        return hm(self.secret, b"MMCK1", struct.pack("<I", window), port_ip, struct.pack("<I", slot), cnonce)[:16]

    def challenge(self, packet, addr, now_ms):
        slot, cnonce = struct.unpack_from("<I", packet, 12)[0], packet[16:32]
        window = now_ms // WINDOW_MS
        out = header(2) + struct.pack("<II", 1 if self.password else 0, window) + self.cookie(window, addr, slot, cnonce)
        return out + self.hfp + cnonce

    def proof(self, packet, addr, now_ms):
        """Returns (welcome_packet or reject_packet, slot or None)."""
        code, slot = struct.unpack_from("<II", packet, 8)
        cnonce, window = packet[16:32], struct.unpack_from("<I", packet, 32)[0]
        cookie, fp, reg, tag = packet[36:52], packet[52:68], packet[68:100], packet[100:116]
        if code != self.code or not 1 <= slot <= 7:
            return None, None
        if not hmac.compare_digest(cookie, self.cookie(window, addr, slot, cnonce)):
            return None, None
        k = self.keys.get(fp)
        new = k is None
        if new:
            mask = hm(self.pwk, b"MMREG1", cookie, cnonce)
            k = bytes(a ^ b for a, b in zip(reg, mask))
            if guest_fp(k) != fp:
                return reject(REJECT_AUTH, self.code), None
        ak = hm(self.pwk, k)
        if not hmac.compare_digest(hm(ak, b"MMPROOF1", packet[8:100], self.hfp)[:16], tag):
            return reject(REJECT_AUTH, self.code), None
        if new:
            self.keys[fp] = k
        sk = hm(ak, b"MMSK1", cnonce, cookie)
        self.sessions[addr] = (slot, sk)
        wtag = hm(ak, b"MMWELCOME1", cnonce, cookie, struct.pack("<I", slot))[:16]
        return (header(4) + struct.pack("<II", self.code, slot) + wtag + struct.pack("<I", int(new))).ljust(48, b"\0"), slot


# ---------------------------------------------------------------------------------------------------------------------
# World transfer (TCP 7775), docs/PROTOCOL.md. WK = HMAC(SK, "MMWORLD1") is derived from the join session's key, so only a
# party that completed the join handshake can run the challenge and response that releases the world.

WORLD_REQUEST, WORLD_CHALLENGE, WORLD_PROOF, WORLD_HEADER = 64, 32, 48, 144


def world_key(sk):
    return hm(sk, b"MMWORLD1")


def world_proof_tag(wk, slot, cnonce, hnonce):
    return hm(wk, b"MMWORLDQ1", bytes([slot]), cnonce, hnonce)


def world_reply_tag(wk, slot, cnonce, hnonce, header112):
    return hm(wk, b"MMWORLDR1", bytes([slot]), cnonce, hnonce, header112)


def world_request(slot, cnonce, version=2):
    return (b"MSWQ" + bytes([version, slot])).ljust(16, b"\0") + cnonce + bytes(32)


def world_challenge(hnonce):
    return (b"MSWC\x02\x00").ljust(16, b"\0") + hnonce


def world_proof(wk, slot, cnonce, hnonce):
    return (b"MSWP\x02").ljust(16, b"\0") + world_proof_tag(wk, slot, cnonce, hnonce)


def world_header(status, data=b"", name=b"game-123-autosave.sav", digest=None, length=None, version=2, info_flags=0, host_world=0):
    """info_flags (byte 6: bit 0 the host named the world it plays now, bit 1 that world is saved) and host_world (u32 at 44: its game id)
    are the world info extension; hosts that predate it leave both zero."""
    h = bytearray(112)
    h[0:4] = b"MSWR"
    h[4] = version
    h[5] = status
    h[6] = info_flags
    h[44:48] = host_world.to_bytes(4, "little")
    h[8:12] = (len(data) if length is None else length).to_bytes(4, "little")
    h[12:44] = digest if digest is not None else hashlib.sha256(data).digest()
    h[48:48 + len(name)] = name
    return bytes(h)


def world_sign(header112, wk, slot, cnonce, hnonce):
    return header112 + world_reply_tag(wk, slot, cnonce, hnonce, header112)


def recv_exact(sock, n):
    got = b""
    while len(got) < n:
        chunk = sock.recv(n - len(got))
        if not chunk:
            return got
        got += chunk
    return got


class WorldHost:
    """A host answering one connection: runs the challenge and response the way the launcher does."""

    def __init__(self, conn, wk, slots=range(1, 8)):
        """`wk` is the key, or a function slot -> key (None: that slot has no session)."""
        self.conn, self.wk, self.slots = conn, wk, slots
        self.key_for = wk if callable(wk) else None
        self.request = self.proof = None
        self.slot = self.cnonce = self.hnonce = None

    def handshake(self):
        """True if the client proved the key. Reads nothing beyond the proof; sends the challenge."""
        self.request = recv_exact(self.conn, 16)
        if len(self.request) != 16 or self.request[:4] != b"MSWQ" or self.request[4] != 2:
            return False
        self.request += recv_exact(self.conn, 48)
        if len(self.request) != WORLD_REQUEST:
            return False
        self.slot, self.cnonce, self.hnonce = self.request[5], self.request[16:32], os.urandom(16)
        if self.key_for is not None:
            self.wk = self.key_for(self.slot) or os.urandom(32)
        self.conn.sendall(world_challenge(self.hnonce))
        self.proof = recv_exact(self.conn, WORLD_PROOF)
        if len(self.proof) != WORLD_PROOF or self.proof[:5] != b"MSWP\x02":
            return False
        return self.slot in self.slots and hmac.compare_digest(
            self.proof[16:48], world_proof_tag(self.wk, self.slot, self.cnonce, self.hnonce))

    def reply(self, header112):
        self.conn.sendall(world_sign(header112, self.wk, self.slot, self.cnonce, self.hnonce))

    def refuse(self):
        self.conn.sendall(world_header(3) + bytes(32))


def world_download(address, wk, slot, timeout=15):
    """A reference client: returns (header112, body, host_tag_ok), or (None, ...) when the host refused or hung up."""
    import socket
    sock = socket.create_connection(address, timeout=timeout)
    try:
        cnonce = os.urandom(16)
        sock.sendall(world_request(slot, cnonce))
        challenge = recv_exact(sock, WORLD_CHALLENGE)
        if len(challenge) != WORLD_CHALLENGE or challenge[:6] != b"MSWC\x02\x00":
            return None, b"", False
        hnonce = challenge[16:32]
        sock.sendall(world_proof(wk, slot, cnonce, hnonce))
        reply = recv_exact(sock, WORLD_HEADER)
        if len(reply) != WORLD_HEADER:
            return None, b"", False
        ok = hmac.compare_digest(reply[112:], world_reply_tag(wk, slot, cnonce, hnonce, reply[:112]))
        body = b""
        if reply[5] == 0 and ok:
            body = recv_exact(sock, int.from_bytes(reply[8:12], "little"))
        return reply[:112], body, ok
    finally:
        sock.close()
