"""Tests the world-transfer download client (MistriMulti.exe --fetch) against a fake host.

  python3 tests/test_world.py build/MistriMulti.exe
"""
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

on_windows = os.name == "nt"
WINE = "/usr/lib/wine/wine64"
exe = Path(sys.argv[1]).resolve()


def wpath(p):
    return str(p) if on_windows else "Z:" + str(p).replace("/", "\\")


def header(status, data=b"", name=b"game-123-autosave.sav", digest=None, length=None):
    h = bytearray(112)
    h[0:4] = b"MSWR"
    h[4] = 1
    h[5] = status
    h[8:12] = (len(data) if length is None else length).to_bytes(4, "little")
    h[12:44] = digest if digest is not None else hashlib.sha256(data).digest()
    h[48:48 + len(name)] = name
    return bytes(h)


class FakeHost:
    def __init__(self, handler):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 7775))
        self.sock.listen(1)
        self.sock.settimeout(40)
        self.handler = handler
        self.request = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(20)
            try:
                self.request = conn.recv(16)
                self.handler(conn)
            except OSError:
                pass

    def close(self):
        self.sock.close()
        self.thread.join(timeout=3)


def fetch(dest, handler=None):
    tmp = dest.parent.parent
    result = tmp / "result.txt"
    if result.exists():
        result.unlink()
    host = FakeHost(handler) if handler else None
    cmd = ([str(exe)] if on_windows else ["xvfb-run", "-a", WINE, str(exe)]) + ["--fetch", "127.0.0.1", wpath(dest), wpath(result)]
    env = dict(os.environ, WINEDEBUG="-all", WINEPREFIX=os.environ.get("WINEPREFIX", "/tmp/wp"))
    try:
        subprocess.run(cmd, env=env, timeout=90, check=True, capture_output=True)
    finally:
        if host:
            host.close()
    return int(result.read_text()), host


def main():
    tmp = Path(tempfile.mkdtemp(prefix="worldtest-"))
    try:
        dest = tmp / "dest" / "saves"
        data = os.urandom(300_000)

        def good(conn):
            conn.sendall(header(0, data) + data)
        code, host = fetch(dest, good)
        assert code == 0, code
        assert host.request[:4] == b"MSWQ" and host.request[4] == 1 and host.request[5:] == b"\0" * 11, host.request
        assert (dest / "game-123-autosave.sav").read_bytes() == data, "file differs"
        assert not list(dest.glob("*.part")), "partial file left behind"
        print("fetch: 300 KB world downloaded intact, checksum verified, no partial file left")

        existing = (dest / "game-123-autosave.sav").read_bytes()

        def bad_sum(conn):
            conn.sendall(header(0, data, digest=b"\x00" * 32) + data)
        code, _ = fetch(dest, bad_sum)
        assert code == 4, code
        assert (dest / "game-123-autosave.sav").read_bytes() == existing and not list(dest.glob("*.part"))
        print("fetch: wrong checksum rejected, the earlier copy is untouched")

        for name in (b"../evil.sav", b"game-1-x.sav", b"game-1-autosave.old.sav", b"C:\\evil.sav", b"game-1-autosave.sav\\x", b"evil.sav", b"game--autosave.sav"):
            def evil(conn, name=name):
                conn.sendall(header(0, data, name=name) + data)
            code, _ = fetch(dest, evil)
            assert code == 3, (name, code)
        assert sorted(p.name for p in dest.iterdir()) == ["game-123-autosave.sav"], "an unsafe name created a file"
        print("fetch: unsafe file names rejected (paths, traversal, wrong pattern)")

        def none(conn):
            conn.sendall(header(1))
        code, _ = fetch(dest, none)
        assert code == 2, code

        def short(conn):
            conn.sendall(header(0, data) + data[:1000])
        code, _ = fetch(dest, short)
        assert code == 3 and not list(dest.glob("*.part")), code

        def huge(conn):
            conn.sendall(header(0, b"", length=500_000_000))
        code, _ = fetch(dest, huge)
        assert code == 3, code

        def zero(conn):
            conn.sendall(header(0, b"", length=0))
        code, _ = fetch(dest, zero)
        assert code == 3, code

        def junk(conn):
            conn.sendall(os.urandom(112))
        code, _ = fetch(dest, junk)
        assert code == 3, code
        print("fetch: no-world, truncated, oversized, empty and junk replies handled")

        code, _ = fetch(dest, None)
        assert code == 1, code
        print("fetch: nobody listening -> clean failure")

        def stall(conn):
            conn.sendall(header(0, data) + data[:100])
            time.sleep(25)
        t0 = time.time()
        code, _ = fetch(dest, stall)
        assert code == 3 and time.time() - t0 < 40, (code, time.time() - t0)
        print("fetch: a host that stalls is abandoned after the timeout")
        print("PASS")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


main()
