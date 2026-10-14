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
        self.mod = self.local / "FieldsOfMistria" / "mod_data" / "mistrimulti"
        self.saves = self.local / "FieldsOfMistria" / "saves"
        self.saves.mkdir(parents=True)
        (self.saves / "game-1-autosave.sav").write_bytes(b"solo world")
        self.mod.mkdir(parents=True)

    def config(self, text):
        (self.mod / "launcher.cfg").write_text(text)

    def env(self):
        extra = {"LOCALAPPDATA": str(self.local)} if on_windows else {}
        return dict(os.environ, WINEDEBUG="-all", WINEPREFIX=os.environ.get("WINEPREFIX", "/tmp/wp"), **extra)

    def cmd(self, args):
        exe = str(self.bin / "MistriMultiLauncher.exe")
        return ([exe] if on_windows else ["xvfb-run", "-a", WINE, exe]) + args

    def steam(self, extra=(), exe="FieldsOfMistria.exe"):
        return subprocess.Popen(self.cmd(["--steam", wpath(self.game / exe), *extra]), env=self.env(),
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
            assert not (sb.mod / "control.json").exists(), f"{name}: control.json written"
            assert not list(sb.mod.glob("bridge_*")), f"{name}: bridge created"
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
                assert cfg["mode"] in ("host", "join") and 0 <= cfg["id"] <= 7, (case, cfg)
        finally:
            sb.cleanup()
    print("fuzz: 24 malformed configuration files, the game always started and control.json stayed valid")


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


test_host()
test_join_and_identity_reuse()
test_fallbacks()
test_direct_and_wrong_exe()
test_backup_prune()
test_configure()
test_fuzz()
test_discovery_responder()
test_helper_dies_with_launcher()
print("PASS")
