"""Black-box tests of the assembly launcher (MistriMultiLauncher.exe) with a fake game.

  python3 tests/test_launcher.py build/MistriMultiLauncher.exe build/mistrimulti-helper.exe build/fakegame.exe

Runs under Wine + xvfb on Linux, directly on Windows. The fake game records its command line and working
folder in ran.txt, sleeps three seconds, then exits with code 7.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

on_windows = os.name == "nt"
WINE = "/usr/lib/wine/wine64"
launcher, helper, fake = (Path(a).resolve() for a in sys.argv[1:4])
updater_exe = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else None


def wpath(p):
    return str(p) if on_windows else "Z:" + str(p).replace("/", "\\")


class Sandbox:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="lchtest-"))
        self.bin = self.root / "bin"
        self.game = self.root / "game"
        if on_windows:
            self.local = self.root / "local"
        else:
            # Wine ignores a LOCALAPPDATA override, so use the prefix's own AppData\\Local and keep it clean.
            import getpass
            self.local = Path(os.environ.get("WINEPREFIX", "/tmp/wp")) / "drive_c" / "users" / getpass.getuser() / "AppData" / "Local"
            shutil.rmtree(self.local / "FieldsOfMistria", ignore_errors=True)
            self.local.mkdir(parents=True, exist_ok=True)
        for d in (self.bin, self.game):
            d.mkdir()
        self.local.mkdir(exist_ok=True)
        shutil.copy(launcher, self.bin / "MistriMultiLauncher.exe")
        shutil.copy(helper, self.bin / "mistrimulti-helper.exe")
        shutil.copy(fake, self.game / "FieldsOfMistria.exe")
        shutil.copy(fake, self.game / "OtherGame.exe")
        if updater_exe is not None:
            shutil.copy(updater_exe, self.bin / "MistriMulti.exe")      # the launcher asks it to scan and to list addresses
        self.mod = self.local / "FieldsOfMistria" / "mod_data" / "mistrimulti"
        self.saves = self.local / "FieldsOfMistria" / "saves"
        self.saves.mkdir(parents=True)
        (self.saves / "game-1-autosave.sav").write_bytes(b"solo world")
        self.mod.mkdir(parents=True)
        self.mp = self.local / "FieldsOfMistria" / "multiplayer" / "saves"

    def config(self, text):
        (self.mod / "launcher.cfg").write_text(text)

    def env(self):
        extra = {"LOCALAPPDATA": str(self.local)} if on_windows else {}
        return dict(os.environ, WINEDEBUG="-all", WINEPREFIX=os.environ.get("WINEPREFIX", "/tmp/wp"), **extra)

    def cmd(self, args):
        exe = str(self.bin / "MistriMultiLauncher.exe")
        return ([exe] if on_windows else ["xvfb-run", "-a", WINE, exe]) + args

    def steam(self, extra=(), exe="FieldsOfMistria.exe", env=None):
        return subprocess.Popen(self.cmd(["--steam", wpath(self.game / exe), *extra]), env=env if env is not None else self.env(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def ran(self):
        p = self.game / "ran.txt"
        return p.read_bytes().decode("utf-16-le") if p.exists() else None

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.local / "FieldsOfMistria", ignore_errors=True)


def wait_for(cond, secs=15):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        try:
            if cond():
                return True
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    return False


def finish(proc):
    out, err = proc.communicate(timeout=60)
    return proc.returncode


def assert_standby(sb, name):
    """No valid launcher.cfg: the game started, nothing is hosted or joined, no helper, no bridge, a status the menu can read."""
    ctl = json.loads((sb.mod / "control.json").read_text())
    assert ctl["enabled"] is False and ctl["mode"] == "idle", f"{name}: control.json {ctl}"
    assert not list(sb.mod.glob("bridge_*")), f"{name}: bridge created"
    log = (sb.mod / "launcher.log").read_bytes().decode(errors="replace")
    assert "Waiting for Host or Join" in log, (name, log)
    st = json.loads((sb.mod / "menu" / "status.json").read_text())
    assert st["state"] in ("idle", "stopped") and st["session"] == "none" and st["helper"] == 1, (name, st)


def test_host():
    sb = Sandbox()
    try:
        sb.config("mode=host\r\nport=47811\r\nroom=a1b2c3d4\r\n")
        proc = sb.steam(["--windowed"])
        ctl = sb.mod / "control.json"
        assert wait_for(lambda: json.loads(ctl.read_text())["enabled"] is True), "control.json never enabled"
        cfg = json.loads(ctl.read_text())
        assert cfg["mode"] == "host" and cfg["id"] == 0, cfg
        assert cfg["uid"].startswith("local:") and len(cfg["uid"]) == 38, cfg
        assert cfg["bridge"].endswith("/FieldsOfMistria/mod_data/mistrimulti/bridge_0") and "\\" not in cfg["bridge"], cfg
        bridge = sb.mod / "bridge_0"
        assert wait_for(lambda: json.loads((bridge / "status.json").read_text())["running"]), "helper did not start"
        code = finish(proc)
        assert code == 7, f"game exit code not passed through: {code}"
        assert json.loads(ctl.read_text())["enabled"] is False, "control.json not disabled afterwards"
        assert "--windowed" in sb.ran(), sb.ran()
        assert (sb.game / "ran.txt").exists()
        backups = list((sb.mod / "solo_backups").iterdir())
        assert len(backups) == 1 and (backups[0] / "game-1-autosave.sav").read_bytes() == b"solo world"
        assert (sb.saves / "game-1-autosave.sav").read_bytes() == b"solo world", "solo save was changed"
        assert (sb.mod / "local_identity.json").exists()
        print("host: helper started, control.json written and disabled, exit code and args passed, solo saves backed up")
    finally:
        sb.cleanup()


def test_join_and_identity_reuse():
    sb = Sandbox()
    try:
        sb.config("mode=join\r\nhost=127.0.0.1\r\nport=47821\r\nplayer=3\r\nroom=abcdef12\r\n")
        proc = sb.steam()
        ctl = sb.mod / "control.json"
        assert wait_for(lambda: json.loads(ctl.read_text())["enabled"] is True)
        first = json.loads(ctl.read_text())
        assert first["mode"] == "join" and first["id"] == 3, first
        assert wait_for(lambda: (sb.mod / "bridge_3" / "status.json").exists()), "join helper did not start"
        finish(proc)
        proc = sb.steam()
        assert wait_for(lambda: json.loads(ctl.read_text())["enabled"] is True)
        second = json.loads(ctl.read_text())
        assert second["uid"] == first["uid"], "identity changed between sessions"
        assert second["epoch"] != first["epoch"], "epoch should be fresh each session"
        finish(proc)
        print("join: helper started as player 3, identity stable across sessions")
    finally:
        sb.cleanup()


def test_fallbacks():
    cases = {
        "no config": None,
        "bad room": "mode=host\r\nroom=zzzz\r\n",
        "injection in room": 'mode=host\r\nroom=abcd1234" evil\r\n',
        "bad ip": "mode=join\r\nhost=999.1.1.1\r\nplayer=1\r\nroom=abcd1234\r\n",
        "bad player": "mode=join\r\nhost=1.2.3.4\r\nplayer=9\r\nroom=abcd1234\r\n",
        "bad port": "mode=host\r\nport=70000\r\nroom=abcd1234\r\n",
        "bad mode": "mode=banana\r\nroom=abcd1234\r\n",
    }
    for name, text in cases.items():
        sb = Sandbox()
        try:
            if text is not None:
                sb.config(text)
            code = finish(sb.steam())
            assert code == 7, f"{name}: game must still start, exit {code}"
            assert sb.ran() is not None, f"{name}: game did not run"
            assert_standby(sb, name)
        finally:
            sb.cleanup()
    print("fallbacks: game always starts, nothing multiplayer is enabled for", ", ".join(cases))


def test_direct_and_wrong_exe():
    sb = Sandbox()
    try:
        sb.config("mode=host\r\nroom=a1b2c3d4\r\n")
        code = finish(sb.steam(["--mistrimulti-direct"]))
        assert code == 7 and sb.ran() is not None
        assert not (sb.mod / "control.json").exists(), "direct launch must not start multiplayer"
        (sb.game / "ran.txt").unlink()
        code = finish(sb.steam(exe="OtherGame.exe"))
        assert code == 7 and sb.ran() is not None
        assert not (sb.mod / "control.json").exists(), "only FieldsOfMistria.exe may start multiplayer"
        print("direct: --mistrimulti-direct and other executables launch plainly")
    finally:
        sb.cleanup()


def test_backup_prune():
    sb = Sandbox()
    try:
        sb.config("mode=host\r\nport=47831\r\nroom=a1b2c3d4\r\n")
        root = sb.mod / "solo_backups"
        for i in range(12):
            d = root / f"2020010{(i % 9) + 1}-0000{i:02d}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "x.sav").write_bytes(b"old")
        keep = root / "not-a-backup"
        keep.mkdir()
        (keep / "mine.txt").write_text("keep")
        finish(sb.steam())
        names = sorted(p.name for p in root.iterdir())
        stamps = [n for n in names if n[:8].isdigit()]
        assert len(stamps) == 10, names
        assert (keep / "mine.txt").exists(), "a folder that is not a backup was touched"
        print("prune: 10 newest backups kept, foreign folders untouched")
    finally:
        sb.cleanup()


def test_configure():
    def run(sb, text, args=("--configure",)):
        p = subprocess.run(sb.cmd(list(args)), input=text.encode(), env=sb.env(), capture_output=True, timeout=60)
        return p.stdout.decode(errors="replace")

    sb = Sandbox()
    try:
        out = run(sb, "h\r\n\r\n\r\n")
        cfg = (sb.mod / "launcher.cfg").read_text()
        assert "mode=host" in cfg and "port=7777" in cfg and "player=0" in cfg and "room=4d495354" in cfg, cfg
        assert "--steam %command%" in out and "MistriMultiLauncher.exe" in out and "Tailscale" in out, out
        out2 = run(sb, "h\r\n\r\n\r\n", args=())          # double-clicking the exe (no arguments) is the setup too
        assert "already copied to your clipboard" in out2, out2
        # a friend joins with only the host's IP: room code and player number are filled in
        run(sb, "j\r\n100.101.102.103\r\n\r\n\r\n\r\n\r\n")
        cfg = (sb.mod / "launcher.cfg").read_text()
        assert "mode=join" in cfg and "host=100.101.102.103" in cfg and "port=7777" in cfg and "room=4d495354" in cfg, cfg
        player = int([l for l in cfg.splitlines() if l.startswith("player=")][0][7:])
        assert 1 <= player <= 7, cfg
        run(sb, "j\r\n100.101.102.103\r\n\r\n\r\n\r\n\r\n")
        assert f"player={player}" in (sb.mod / "launcher.cfg").read_text(), "Enter must keep the earlier player number"
        run(sb, "j\r\n192.168.1.20\r\n\r\n3\r\nABCDEF12\r\n\r\n")
        cfg = (sb.mod / "launcher.cfg").read_text()
        assert "mode=join" in cfg and "host=192.168.1.20" in cfg and "player=3" in cfg and "room=ABCDEF12" in cfg, cfg
        run(sb, "j\r\n300.1.1.1\r\n192.168.1.9\r\n8001\r\n9\r\n2\r\nnothex\r\nabcd1234\r\n\r\n")
        cfg = (sb.mod / "launcher.cfg").read_text()
        assert "host=192.168.1.9" in cfg and "port=8001" in cfg and "player=2" in cfg and "room=abcd1234" in cfg, cfg
        before = (sb.mod / "launcher.cfg").read_text()
        run(sb, "j\r\nbad\r\nbad\r\nbad\r\nbad\r\nbad\r\n")
        assert (sb.mod / "launcher.cfg").read_text() == before, "invalid input must not change the saved setup"
        # a config with no room code at all is valid and uses the default; a join with only an IP works end to end
        sb.config("mode=join\r\nhost=127.0.0.1\r\nplayer=2\r\n")
        proc = sb.steam()
        assert wait_for(lambda: json.loads((sb.mod / "control.json").read_text())["enabled"] is True), "IP-only join did not start"
        finish(proc)
        print("configure: IP-only join, default room, kept player number, validation, launch option printed")
    finally:
        sb.cleanup()


def query_host(timeout=2.0, payload=None, port=7776):
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(payload if payload is not None else b"MSDQ\x01" + b"\x00" * 59, ("127.0.0.1", port))
        return sock.recvfrom(256)[0]
    except OSError:
        return None
    finally:
        sock.close()


def test_discovery_responder():
    sb = Sandbox()
    try:
        sb.config("mode=host\r\nport=47851\r\n")
        proc = sb.steam()
        assert wait_for(lambda: (sb.mod / "bridge_0" / "status.json").exists())
        reply = None
        for _ in range(20):
            reply = query_host(0.5)
            if reply:
                break
        assert reply is not None and len(reply) == 64, "host did not answer a discovery query"
        assert reply[:4] == b"MSDR" and reply[4] == 1 and reply[5] == 0, reply[:8]
        assert int.from_bytes(reply[6:8], "little") == 47851, reply[:8]
        name = reply[8:40].split(b"\x00")[0]
        assert len(name) > 0, "computer name missing"
        assert query_host(0.7, b"MSDQ\x01") is None, "short query must not be answered"
        assert query_host(0.7, b"XXXX\x01" + b"\x00" * 59) is None, "wrong magic must not be answered"
        assert query_host(0.7, b"MSDQ\x09" + b"\x00" * 59) is None, "unknown version must not be answered"
        assert query_host(0.7, b"MSDQ\x01" + b"\x00" * 200) is None, "oversized query must not be answered"
        finish(proc)
        assert query_host(0.7) is None, "responder must stop with the game"
        # a custom room code is announced, a joining player never answers
        sb.config("mode=host\r\nport=47851\r\nroom=a1b2c3d4\r\n")
        proc = sb.steam()
        assert wait_for(lambda: (sb.mod / "bridge_0" / "status.json").exists())
        for _ in range(20):
            reply = query_host(0.5)
            if reply:
                break
        assert reply is not None and reply[5] == 1, "custom room flag missing"
        finish(proc)
        sb.config("mode=join\r\nhost=127.0.0.1\r\nplayer=2\r\nport=47861\r\n")
        proc = sb.steam()
        assert wait_for(lambda: (sb.mod / "bridge_2" / "status.json").exists())
        assert query_host(1.0) is None, "a joining player must not answer discovery"
        finish(proc)
        print("discovery: host answers valid 64-byte queries only, flags custom rooms, stops with the game")
    finally:
        sb.cleanup()


def scan_with_updater(sb, extra="127.0.0.1"):
    out = sb.root / "scan.txt"
    if out.exists():
        out.unlink()
    exe = str(updater_exe)
    cmd = ([exe] if on_windows else ["xvfb-run", "-a", WINE, exe]) + ["--scan", wpath(out)]
    env = dict(sb.env(), MISTRIMULTI_SCAN_EXTRA=extra)
    subprocess.run(cmd, env=env, timeout=60, check=True, capture_output=True)
    return out.read_text() if out.exists() else ""


def test_scan():
    import socket
    import threading
    if updater_exe is None:
        print("scan: skipped (pass the updater exe as the fourth argument)")
        return
    # 1. a fake host: names are cleaned, ports and the custom-room flag are read, duplicates are collapsed
    sb = Sandbox()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 7776))
        sock.settimeout(0.3)
        stop = threading.Event()

        def serve():
            while not stop.is_set():
                try:
                    data, addr = sock.recvfrom(256)
                except OSError:
                    continue
                if len(data) == 64 and data[:4] == b"MSDQ":
                    name = b"Tom\x01\x7f PC\xe9" + b"x" * 40
                    reply = b"MSDR\x01\x01" + (4242).to_bytes(2, "little") + name[:31].ljust(32, b"\x00") + b"\x00" * 24
                    sock.sendto(reply, addr)
                    sock.sendto(reply, addr)          # duplicate answer
                    sock.sendto(b"garbage", addr)
                    sock.sendto(b"MSDR\x01" + b"\x00" * 10, addr)   # wrong length
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        text = scan_with_updater(sb)
        stop.set()
        lines = [l for l in text.splitlines() if l.strip()]
        assert len(lines) == 1, text
        ip, port, flags, name = lines[0].split(" ", 3)
        assert ip == "127.0.0.1" and port == "4242" and flags == "1", lines[0]
        assert name.startswith("Tom") and all(32 <= ord(c) < 127 for c in name), repr(name)
        sock.close()
        t.join(timeout=2)
    finally:
        sb.cleanup()
    # 2. the real launcher hosting
    sb = Sandbox()
    try:
        sb.config("mode=host\r\nport=47871\r\n")
        proc = sb.steam()
        assert wait_for(lambda: (sb.mod / "bridge_0" / "status.json").exists())
        found = ""
        for _ in range(6):
            found = scan_with_updater(sb)
            if "127.0.0.1" in found:
                break
        lines = [l for l in found.splitlines() if l.strip()]
        assert lines and lines[0].split(" ")[0] == "127.0.0.1" and lines[0].split(" ")[1] == "47871" and lines[0].split(" ")[2] == "0", found
        finish(proc)
        assert scan_with_updater(sb).strip() == "", "no host should be found after the game closed"
        print("scan: finds the real host, cleans names, ignores junk and duplicates, finds nothing when nobody hosts")
    finally:
        sb.cleanup()


def world_request(payload=None, timeout=10):
    import hashlib
    import socket
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect(("127.0.0.1", 7775))
        sock.sendall(payload if payload is not None else b"MSWQ\x01" + b"\x00" * 11)
        got = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            got += chunk
        return got
    except OSError:
        return None
    finally:
        sock.close()


def test_world_server():
    import hashlib
    sb = Sandbox()
    try:
        sb.mp.mkdir(parents=True)
        old = os.urandom(50_000)
        new = os.urandom(200_000)
        (sb.mp / "game-1-autosave.sav").write_bytes(old)
        (sb.mp / "game-2-autosave.sav").write_bytes(new)
        (sb.mp / "game-3-autosave.old.sav").write_bytes(b"newest but not a valid save name")
        (sb.mp / "notes.txt").write_bytes(b"x")
        os.utime(sb.mp / "game-1-autosave.sav", (1_700_000_000, 1_700_000_000))
        os.utime(sb.mp / "game-2-autosave.sav", (1_700_000_100, 1_700_000_100))
        os.utime(sb.mp / "game-3-autosave.old.sav", (1_700_000_200, 1_700_000_200))
        sb.config("mode=host\r\nport=47881\r\n")
        proc = sb.steam(["--slow"])
        assert wait_for(lambda: (sb.mod / "bridge_0" / "status.json").exists())
        got = None
        for _ in range(20):
            got = world_request()
            if got:
                break
            time.sleep(0.3)
        assert got and len(got) == 112 + len(new), (None if got is None else len(got))
        hdr, body = got[:112], got[112:]
        assert hdr[:4] == b"MSWR" and hdr[4] == 1 and hdr[5] == 0, hdr[:8]
        assert int.from_bytes(hdr[8:12], "little") == len(new)
        assert hdr[12:44] == hashlib.sha256(new).digest() and body == new
        assert hdr[48:112].split(b"\x00")[0] == b"game-2-autosave.sav", hdr[48:80]
        # bad requests get nothing
        assert world_request(b"MSWQ\x09" + b"\x00" * 11) in (b"", None)
        assert world_request(b"XXXX\x01" + b"\x00" * 11) in (b"", None)
        assert world_request(b"short") in (b"", None)
        # the host still serves after the junk
        again = world_request()
        assert again and again[112:] == new
        # nothing to give: status 1
        for f in sb.mp.iterdir():
            f.unlink()
        none = world_request()
        assert none and len(none) == 112 and none[5] == 1, none[:8] if none else none
        finish(proc)
        print("world server: newest valid save is sent with a correct checksum, look-alike files ignored, junk requests dropped, status 1 when there is nothing")
    finally:
        sb.cleanup()


def test_guest_refreshes_world():
    import hashlib
    import socket
    import threading
    sb = Sandbox()
    try:
        data = os.urandom(120_000)
        name = b"game-77-autosave.sav"
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 7775))
        server.listen(2)
        server.settimeout(20)

        def serve():
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                conn.recv(16)
                h = bytearray(112)
                h[0:4] = b"MSWR"
                h[4] = 1
                h[8:12] = len(data).to_bytes(4, "little")
                h[12:44] = hashlib.sha256(data).digest()
                h[48:48 + len(name)] = name
                conn.sendall(bytes(h) + data)
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        sb.config("mode=join\r\nhost=127.0.0.1\r\nplayer=2\r\nport=47891\r\n")
        proc = sb.steam()
        assert wait_for(lambda: (sb.mp / "game-77-autosave.sav").exists(), 20), "world was not downloaded at game start"
        assert (sb.mp / "game-77-autosave.sav").read_bytes() == data
        finish(proc)
        server.close()
        # an unreachable host must not delay or break the game start
        sb2 = Sandbox()
        try:
            sb2.config("mode=join\r\nhost=10.255.255.1\r\nplayer=2\r\nport=47891\r\n")
            t0 = time.time()
            code = finish(sb2.steam(["--quick"]))
            assert code == 7 and sb2.ran() is not None
            assert time.time() - t0 < 25, "an unreachable host delayed the game too long"
        finally:
            sb2.cleanup()
        print("guest: the host's world is downloaded as the game starts; an unreachable host does not block the game")
    finally:
        sb.cleanup()


def test_fuzz():
    import random
    rng = random.Random(1234)
    keys = [b"mode=", b"host=", b"port=", b"player=", b"room=", b"x=", b""]
    values = [b"host", b"join", b"A" * 5000, b"0", b"-1", b"99999999999", b"1.2.3.4", b"1.2.3.4.5", b"::1", b"\x00" * 50,
              b"a1b2c3d4", b"a1b2c3d45", b'a"b', b"a\\b", b"%s%s%s%n", b"\xff\xfe\xfd", b"7777", b"3", b" 3 "]
    for case in range(24):
        sb = Sandbox()
        try:
            if case % 3 == 0:
                data = bytes(rng.randrange(256) for _ in range(rng.choice([0, 1, 40, 4000, 9000])))
            else:
                parts = []
                for _ in range(rng.randrange(1, 9)):
                    parts.append(rng.choice(keys) + rng.choice(values) + rng.choice([b"\r\n", b"\n", b"\r", b""]))
                data = b"".join(parts)
            (sb.mod / "launcher.cfg").write_bytes(data)
            code = finish(sb.steam(["--quick"]))
            assert code == 7, f"fuzz case {case}: game exit {code}"
            assert sb.ran() is not None, f"fuzz case {case}: game did not run"
            ctl = sb.mod / "control.json"
            if ctl.exists():
                cfg = json.loads(ctl.read_text())
                assert cfg["mode"] in ("host", "join", "idle") and 0 <= cfg["id"] <= 7, (case, cfg)
                assert cfg["mode"] != "idle" or cfg["enabled"] is False, (case, cfg)
        finally:
            sb.cleanup()
    print("fuzz: 24 malformed configuration files, the game always started and control.json stayed valid")


def test_password():
    """launcher.cfg password=: unusable ones stop multiplayer, valid ones reach the real helper through auth.cfg."""
    import socket
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import mmauth
    for name, text in {"space": "password=two words", "too long": "password=" + "x" * 65, "control": "password=ab\x01"}.items():
        sb = Sandbox()
        try:
            sb.config("mode=host\r\nport=47911\r\nroom=a1b2c3d4\r\n" + text + "\r\n")
            code = finish(sb.steam())
            assert code == 7 and sb.ran() is not None, f"{name}: game must still start"
            assert_standby(sb, f"{name}: bad password in launcher.cfg")       # the room is never opened with an unusable password
        finally:
            sb.cleanup()

    def handshake(password, slot=1, port=47911):
        guest = mmauth.Guest(0xA1B2C3D4, slot, password=password)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(3)
        try:
            s.sendto(guest.hello(), ("127.0.0.1", port))
            challenge = s.recvfrom(256)[0]
            s.sendto(guest.proof(challenge), ("127.0.0.1", port))
            reply = s.recvfrom(256)[0]
            return challenge, ("ok" if guest.welcome(reply) else ("reject", reply[8]))
        finally:
            s.close()

    sb = Sandbox()
    try:
        sb.config("mode=host\r\nport=47911\r\nroom=a1b2c3d4\r\npassword=s3cret!pw\r\n")
        proc = sb.steam(["--quick"])
        bridge = sb.mod / "bridge_0"
        assert wait_for(lambda: (bridge / "auth.cfg").exists() and (bridge / "status.json").exists()), "helper did not start"
        lines = (bridge / "auth.cfg").read_bytes().decode().split("\r\n")
        assert lines[0].startswith("key=") and lines[0].endswith("mistrimulti\\install.key"), lines
        assert lines[1].endswith("mistrimulti\\trust_keys.txt") and lines[2].endswith("mistrimulti\\deny.txt"), lines
        assert lines[3] == "pass=s3cret!pw", lines
        assert wait_for(lambda: (sb.mod / "install.key").exists() and (sb.mod / "install.key").stat().st_size == 32), "no install key"
        challenge, result = handshake(b"s3cret!pw")
        assert result == "ok", result
        hfp = challenge[32:48]
        assert handshake(b"wrong")[1] == ("reject", 1)
        assert handshake(b"")[1] == ("reject", 1)
        finish(proc)
        sb.config("mode=host\r\nport=47911\r\nroom=a1b2c3d4\r\n")
        proc = sb.steam(["--quick"])
        assert wait_for(lambda: (bridge / "status.json").exists() and "pass=" not in (bridge / "auth.cfg").read_bytes().decode()), "stale password"
        assert wait_for(lambda: json.loads((bridge / "status.json").read_text())["running"]), "second helper did not start"
        challenge = result = None
        for _ in range(30):                  # Wine starts slowly: the first datagrams may find nobody listening yet
            try:
                challenge, result = handshake(b"")
                break
            except socket.timeout:
                time.sleep(0.5)
        assert result == "ok" and challenge[32:48] == hfp, ("the host fingerprint must survive a restart", result)
        finish(proc)
        print("password: unusable ones stop multiplayer, valid ones reach the helper (auth.cfg), wrong ones are refused, stable host fingerprint")
    finally:
        sb.cleanup()


def test_helper_dies_with_launcher():
    sb = Sandbox()
    try:
        sb.config("mode=host\r\nport=47841\r\nroom=a1b2c3d4\r\n")
        proc = sb.steam()
        status = sb.mod / "bridge_0" / "status.json"
        assert wait_for(lambda: status.exists())
        beat = [None]

        def beating():
            hb = json.loads(status.read_text())["heartbeat"]
            changed = beat[0] is not None and hb != beat[0]
            beat[0] = hb
            return changed
        assert wait_for(beating, 10), "helper heartbeat not advancing"
        if on_windows:
            subprocess.run(["taskkill", "/F", "/IM", "MistriMultiLauncher.exe"], check=False, capture_output=True)
        else:
            pids = subprocess.run(["pgrep", "-f", "MistriMultiLauncher.exe.*--steam"], capture_output=True, text=True).stdout.split()
            for pid in pids:
                if int(pid) != os.getpid():
                    subprocess.run(["kill", "-9", pid], check=False)
        proc.kill()
        time.sleep(3)
        first = json.loads(status.read_text())["heartbeat"]
        time.sleep(2.5)
        second = json.loads(status.read_text())["heartbeat"]
        assert first == second, "helper kept running after the launcher was killed"
        print("job: helper stopped when the launcher was killed")
    finally:
        sb.cleanup()


# ---------------------------------------------------------------- the in-game menu: standby launcher + commands (launcher/menu.inc)
_menu_seq = {}


def menu_cmd(sb, **fields):
    """What the mod does: write cmd.txt atomically (key=value lines), seq counting up per sandbox."""
    seq = _menu_seq[sb.root] = _menu_seq.get(sb.root, 0) + 1
    fields = {"seq": seq, **fields}
    tmp = sb.mod / "menu" / "cmd.tmp"
    tmp.write_text("".join(f"{k}={v}\n" for k, v in fields.items()))
    os.replace(tmp, sb.mod / "menu" / "cmd.txt")
    return seq


def menu_status(sb):
    return json.loads((sb.mod / "menu" / "status.json").read_text())


def menu_wait(sb, seq, states=("idle", "hosting", "ready", "error", "stopped"), secs=40):
    got = []

    def done():
        st = menu_status(sb)
        got.append(st)
        return st["seq"] == seq and st["state"] in states

    assert wait_for(done, secs), ("no answer to command", seq, got[-1] if got else None)
    return got[-1]


def start_menu_game(sb, env=None):
    proc = sb.steam(["--slow"], env=env)
    assert wait_for(lambda: (sb.mod / "menu" / "status.json").exists(), 30), "the launcher did not publish a menu status"
    return proc


def port_open_tcp(port):
    import socket
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def port_free_udp(port):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def test_menu_standby():
    """No launcher.cfg: nothing hosted or joined and nothing listening until the player picks Host or Join."""
    sb = Sandbox()
    try:
        proc = start_menu_game(sb)
        st = menu_status(sb)
        assert st["v"] == 1 and st["state"] == "idle" and st["session"] == "none" and st["helper"] == 1 and st["seq"] == 0, st
        assert st["hosts"] == [], st
        ctl = json.loads((sb.mod / "control.json").read_text())
        assert ctl["enabled"] is False and ctl["mode"] == "idle", ctl
        assert not port_open_tcp(7775) and port_free_udp(7776) and port_free_udp(7777), "standby must not listen on any port"
        assert query_host(0.7) is None, "standby must not answer discovery"
        assert not list(sb.mod.glob("bridge_*")), "no helper bridge in standby"
        beats = {menu_status(sb)["hb"]}
        assert wait_for(lambda: beats.add(menu_status(sb)["hb"]) or len(beats) >= 3, 8), "the launcher's heartbeat does not move"
        assert finish(proc) == 7
        assert menu_status(sb)["state"] == "stopped", menu_status(sb)
        (sb.mod / "menu" / "cmd.txt").write_text("seq=5\ncmd=host\n")
        proc = start_menu_game(sb)
        time.sleep(2)
        assert menu_status(sb)["state"] == "idle" and not (sb.mod / "menu" / "cmd.txt").exists(), "a stale command was applied"
        finish(proc)
        print("menu standby: no launcher.cfg needed, idle status with a moving heartbeat, nothing listens, stale commands dropped, 'stopped' at exit")
    finally:
        sb.cleanup()


def test_menu_host_and_stop():
    import socket
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import mmauth
    sb = Sandbox()
    try:
        sb.mp.mkdir(parents=True)
        (sb.mp / "game-1-autosave.sav").write_bytes(b"hosted world")
        proc = start_menu_game(sb)
        seq = menu_cmd(sb, cmd="host", password="pa$$w0rd!")
        st = menu_wait(sb, seq, ("hosting", "error"))
        assert st["state"] == "hosting" and st["err"] == 0 and st["session"] == "host" and st["port"] == 7777, st
        assert not (sb.mod / "menu" / "cmd.txt").exists(), "the command file must be consumed"
        ctl = json.loads((sb.mod / "control.json").read_text())
        assert ctl["enabled"] is True and ctl["mode"] == "host" and ctl["id"] == 0 and ctl["bridge"].endswith("/mod_data/mistrimulti/bridge_0"), ctl
        bridge = sb.mod / "bridge_0"
        assert wait_for(lambda: json.loads((bridge / "status.json").read_text())["running"], 30), "helper did not start"
        reply = None
        for _ in range(10):
            reply = query_host(0.5)
            if reply:
                break
        assert reply and reply[:4] == b"MSDR" and reply[5] == 2 and int.from_bytes(reply[6:8], "little") == 7777, reply and reply[:8]
        assert world_request()[:4] == b"MSWR", "the world server must run while hosting"
        # the password applies: the real helper accepts it and refuses a wrong one
        assert "pass=pa$$w0rd!" in (bridge / "auth.cfg").read_bytes().decode()
        leaks = [str(p) for p in sb.mod.rglob("*") if p.is_file() and p.name != "auth.cfg" and b"pa$$w0rd!" in p.read_bytes()]
        assert not leaks, f"the password leaked into {leaks}"

        def handshake(password, slot=1, port=7777):
            guest = mmauth.Guest(0x4D495354, slot, password=password)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(3)
            try:
                s.sendto(guest.hello(), ("127.0.0.1", port))
                challenge = s.recvfrom(256)[0]
                s.sendto(guest.proof(challenge), ("127.0.0.1", port))
                return "ok" if guest.welcome(s.recvfrom(256)[0]) else "refused"
            finally:
                s.close()
        assert handshake(b"wrong") == "refused" and handshake(b"pa$$w0rd!") == "ok"
        seq = menu_cmd(sb, cmd="stop")
        st = menu_wait(sb, seq, ("idle",))
        assert st["session"] == "none" and st["addrs"] == [], st
        assert not port_open_tcp(7775) and port_free_udp(7776) and query_host(0.7) is None, "stop must close the discovery answer and world server"
        assert json.loads((sb.mod / "control.json").read_text())["enabled"] is False
        assert (bridge / "stop.flag").exists()
        seq = menu_cmd(sb, cmd="host", port="47931", room="A1B2C3D4")
        st = menu_wait(sb, seq, ("hosting", "error"))
        assert st["state"] == "hosting" and st["port"] == 47931, st
        for _ in range(10):
            reply = query_host(0.5)
            if reply:
                break
        assert reply and reply[5] == 1 and int.from_bytes(reply[6:8], "little") == 47931, reply and reply[:8]
        assert finish(proc) == 7
        assert menu_status(sb)["state"] == "stopped" and json.loads((sb.mod / "control.json").read_text())["enabled"] is False
        assert not port_open_tcp(7775), "the world server must stop with the game"
        print("menu host: hosting from a command (password enforced by the helper and only in auth.cfg), discovery and world server "
              "only while hosting, stop and game exit close everything")
    finally:
        sb.cleanup()


def test_menu_scan_and_addresses():
    """scan runs MistriMulti.exe --scan (the manager's own code); a fake host on UDP 7776 is listed with a cleaned name."""
    import socket
    import threading
    if updater_exe is None:
        print("menu scan: skipped (pass the updater exe as the fourth argument)")
        return
    sb = Sandbox()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stop = threading.Event()
    try:
        sock.bind(("127.0.0.1", 7776))
        sock.settimeout(0.3)

        def serve():
            while not stop.is_set():
                try:
                    data, addr = sock.recvfrom(256)
                except OSError:
                    continue
                if len(data) == 64 and data[:4] == b"MSDQ":
                    name = b'Tom "the" \\PC\x01'
                    sock.sendto(b"MSDR\x01\x03" + (4242).to_bytes(2, "little") + name.ljust(32, b"\x00") + b"\x00" * 24, addr)
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        proc = start_menu_game(sb, env=dict(sb.env(), MISTRIMULTI_SCAN_EXTRA="127.0.0.1"))
        seq = menu_cmd(sb, cmd="scan")
        st = menu_wait(sb, seq, ("idle", "error"), 60)
        assert st["state"] == "idle" and st["scan"] == 1 and len(st["hosts"]) == 1, st
        h = st["hosts"][0]
        assert h["ip"] == "127.0.0.1" and h["port"] == 4242 and h["flags"] == 3 and h["name"] == "Tom _the_ _PC?", h
        stop.set()
        seq = menu_cmd(sb, cmd="scan")
        st = menu_wait(sb, seq, ("idle", "error"), 60)
        assert st["scan"] == 2 and st["hosts"] == [], st
        finish(proc)
        # this computer's addresses (MistriMulti.exe --addrs): valid dotted addresses only, one per line
        out = sb.root / "addrs.txt"
        exe = str(updater_exe)
        subprocess.run(([exe] if on_windows else ["xvfb-run", "-a", WINE, exe]) + ["--addrs", wpath(out)], env=sb.env(), timeout=60, check=True, capture_output=True)
        assert out.exists()
        for line in out.read_text().splitlines():
            parts = line.split(".")
            assert len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts) and not line.startswith("169.254."), line
        print("menu scan: the launcher lists hosts found by MistriMulti.exe --scan (names cleaned), counts finished scans, --addrs writes valid addresses")
    finally:
        stop.set()
        sock.close()
        sb.cleanup()


def test_menu_join():
    """A real helper hosts with a password (started like a friend's computer would), a fake world server gives the world."""
    import hashlib
    import socket
    import threading
    sb = Sandbox()
    host_helper = None
    server = socket.socket()
    try:
        data = os.urandom(120_000)
        name = b"game-77-autosave.sav"
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 7775))
        server.listen(4)
        server.settimeout(1)
        stop = threading.Event()

        def serve():
            while not stop.is_set():
                try:
                    conn, _ = server.accept()
                except OSError:
                    continue
                with conn:
                    conn.recv(16)
                    h = bytearray(112)
                    h[0:4] = b"MSWR"
                    h[4] = 1
                    h[8:12] = len(data).to_bytes(4, "little")
                    h[12:44] = hashlib.sha256(data).digest()
                    h[48:48 + len(name)] = name
                    conn.sendall(bytes(h) + data)
        threading.Thread(target=serve, daemon=True).start()
        hostdir = sb.root / "hostbridge"
        hostdir.mkdir()
        (hostdir / "auth.cfg").write_bytes(b"pass=tops3cret\r\n")
        exe = str(sb.bin / "mistrimulti-helper.exe")
        host_helper = subprocess.Popen(([exe] if on_windows else ["xvfb-run", "-a", WINE, exe]) + ["host", "7777", "0", "4d495354", wpath(hostdir)],
                                       env=sb.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert wait_for(lambda: (hostdir / "status.json").exists(), 30), "the host helper did not start"
        proc = start_menu_game(sb)
        seq = menu_cmd(sb, cmd="join", host="127.0.0.1", port="7777")
        st = menu_wait(sb, seq, ("error", "ready"), 60)
        assert st["state"] == "error" and st["err"] == 26, st                      # the host needs a password
        assert not (sb.mp / "game-77-autosave.sav").exists()
        seq = menu_cmd(sb, cmd="join", host="127.0.0.1", password="wrong")
        st = menu_wait(sb, seq, ("error", "ready"), 60)
        assert st["state"] == "error" and st["err"] == 21, st
        assert not (sb.mp / "game-77-autosave.sav").exists(), "nothing may be downloaded after a refused join"
        seq = menu_cmd(sb, cmd="join", host="127.0.0.1", password="tops3cret")
        st = menu_wait(sb, seq, ("error", "ready"), 60)
        assert st["state"] == "ready" and st["session"] == "join" and st["err"] == 0, st
        assert (sb.mp / "game-77-autosave.sav").read_bytes() == data, "world not downloaded intact"
        ctl = json.loads((sb.mod / "control.json").read_text())
        assert ctl["enabled"] is True and ctl["mode"] == "join" and 1 <= ctl["id"] <= 7, ctl
        assert wait_for(lambda: json.loads((sb.mod / f"bridge_{ctl['id']}" / "status.json").read_text())["auth"] == 2, 30), "guest helper not authenticated"
        seq = menu_cmd(sb, cmd="stop")
        st = menu_wait(sb, seq, ("idle",))
        assert st["session"] == "none" and json.loads((sb.mod / "control.json").read_text())["enabled"] is False
        finish(proc)
        stop.set()
        print("menu join: a missing or wrong password is refused before any download, the right one joins and downloads the world; stop leaves")
    finally:
        if host_helper:
            (hostdir / "stop.flag").write_bytes(b"stop")
            try:
                host_helper.communicate(timeout=20)
            except Exception:
                host_helper.kill()
        server.close()
        sb.cleanup()


def test_menu_command_validation():
    sb = Sandbox()
    try:
        proc = start_menu_game(sb)

        def refused(label, **fields):
            seq = menu_cmd(sb, **fields)
            st = menu_wait(sb, seq, ("error", "hosting", "joining", "ready", "idle"), 30)
            assert st["state"] == "error" and st["err"] == 3 and st["session"] == "none", (label, st)
            assert not list(sb.mod.glob("bridge_*")), f"{label}: a helper bridge was created"
            assert json.loads((sb.mod / "control.json").read_text())["enabled"] is False, label

        refused("bad ip", cmd="join", host="999.1.1.1")
        refused("short ip", cmd="join", host="1.2.3")
        refused("no ip", cmd="join")
        refused("ip with text", cmd="join", host="1.2.3.4 evil")
        refused("password with a space", cmd="host", password="a b")
        refused("password too long", cmd="host", password="x" * 65)
        refused("bad room", cmd="join", host="1.2.3.4", room="zzzz")
        refused("room injection", cmd="host", room='abcd1234" evil')
        refused("port zero", cmd="host", port="0")
        refused("port too big", cmd="join", host="1.2.3.4", port="70000")
        refused("host port too big", cmd="host", port="70000")
        seq = menu_cmd(sb, cmd="explode")
        menu_wait(sb, seq, ("error", "idle"))
        (sb.mod / "menu" / "cmd.txt").write_text(f"seq={seq}\ncmd=host\n")           # a repeated sequence number
        time.sleep(2)
        assert menu_status(sb)["session"] == "none" and not (sb.mod / "menu" / "cmd.txt").exists()
        for junk in (b"", b"seq=0\ncmd=host\n", b"cmd=host\n", b"seq=abc\ncmd=host\n", b"\xff\xfe" * 300, b"seq=99999999999\ncmd=host\n"):
            (sb.mod / "menu" / "cmd.txt").write_bytes(junk)
            time.sleep(1)
            assert menu_status(sb)["session"] == "none", junk[:20]
        assert finish(proc) == 7
        print("menu commands: invalid addresses, ports, rooms, passwords and injected lines are refused without side effects; "
              "unknown commands, repeated sequence numbers and junk files are harmless")
    finally:
        sb.cleanup()


def test_menu_helper_missing():
    sb = Sandbox()
    try:
        (sb.bin / "mistrimulti-helper.exe").unlink()
        proc = start_menu_game(sb)
        st = menu_status(sb)
        assert st["helper"] == 0 and st["state"] == "error" and st["err"] == 1, st
        seq = menu_cmd(sb, cmd="host")
        st = menu_wait(sb, seq, ("error",))
        assert st["err"] == 1 and st["session"] == "none" and not port_open_tcp(7775), st
        assert finish(proc) == 7 and sb.ran() is not None, "the game must run whatever happens to the helper"
        print("menu helper missing: reported to the menu (err 1), nothing listens, the game still runs")
    finally:
        sb.cleanup()


def test_menu_overrides_launcher_cfg():
    """An optional launcher.cfg still starts its role by itself (older setups); the menu can stop it and host with the defaults."""
    sb = Sandbox()
    try:
        sb.config("mode=host\r\nport=47811\r\nroom=a1b2c3d4\r\n")
        proc = start_menu_game(sb)
        st = menu_status(sb)
        assert st["state"] == "hosting" and st["session"] == "host" and st["port"] == 47811, st
        seq = menu_cmd(sb, cmd="stop")
        menu_wait(sb, seq, ("idle",))
        assert not port_open_tcp(7775) and query_host(0.7) is None
        seq = menu_cmd(sb, cmd="host")
        st = menu_wait(sb, seq, ("hosting",))
        assert st["port"] == 7777, st
        finish(proc)
        print("menu vs launcher.cfg: a saved role still starts by itself; the menu can stop it and host with the defaults")
    finally:
        sb.cleanup()


ALL = [test_host, test_join_and_identity_reuse, test_fallbacks, test_direct_and_wrong_exe, test_backup_prune, test_configure, test_fuzz,
       test_discovery_responder, test_scan, test_world_server, test_guest_refreshes_world, test_helper_dies_with_launcher, test_password,
       test_menu_standby, test_menu_host_and_stop, test_menu_scan_and_addresses, test_menu_join, test_menu_command_validation,
       test_menu_helper_missing, test_menu_overrides_launcher_cfg]
only = [n for n in os.environ.get("ONLY", "").split(",") if n]       # ONLY=test_password runs just those
for fn in ALL:
    if not only or fn.__name__ in only:
        fn()
print("PASS")
