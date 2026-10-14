"""Black-box tests of the native Linux launcher (mistrimulti-launcher) with a fake game. Runs natively; no Wine, no display.

  python3 tests/test_launcher_linux.py build/mistrimulti-launcher build/mistrimulti-helper-linux build/fakegame-linux [build/mistrimulti-manager]

Mirrors tests/test_launcher.py (the Windows launcher under Wine). The fake game writes its arguments, one per line, to
ran.txt in its working folder (Steam starts the game command in the game folder, so the tests do the same), sleeps three
seconds, then exits with code 7. The game folder is given to the launcher with MISTRIMULTI_DATA_DIR, HOME is a temporary
folder, and every Steam/XDG variable is removed so the tests never touch the real user's files.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time

launcher, helper, fake = (Path(a).resolve() for a in sys.argv[1:4])
manager = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else None
HELPER_NAME = "mistrimulti-helper-linux"


class Sandbox:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="lchtest-"))
        self.bin = self.root / "bin"
        self.game = self.root / "game"
        self.home = self.root / "home"
        self.data = self.root / "data"          # stands for CONFIG_DIRECTORY (game_save_id)
        for d in (self.bin, self.game, self.home):
            d.mkdir()
        shutil.copy(launcher, self.bin / "mistrimulti-launcher")
        shutil.copy(helper, self.bin / HELPER_NAME)
        shutil.copy(fake, self.game / "FieldsOfMistria")
        shutil.copy(fake, self.game / "FieldsOfMistria.exe")
        shutil.copy(fake, self.game / "OtherGame")
        shutil.copy(fake, self.game / "proton")
        if manager:
            shutil.copy(manager, self.bin / "mistrimulti-manager")
        for f in list(self.bin.iterdir()) + list(self.game.iterdir()):
            f.chmod(0o755)
        self.mod = self.data / "mod_data" / "mistrimulti"
        self.saves = self.data / "saves"
        self.saves.mkdir(parents=True)
        (self.saves / "game-1-autosave.sav").write_bytes(b"solo world")
        self.mod.mkdir(parents=True)
        self.mp = self.data / "multiplayer" / "saves"

    def config(self, text):
        (self.mod / "launcher.cfg").write_text(text)

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("XDG_", "STEAM_", "MISTRIMULTI_", "MM_"))}
        env.update(HOME=str(self.home), MISTRIMULTI_DATA_DIR=str(self.data))
        env.update(extra)
        return env

    def steam(self, extra=(), exe="FieldsOfMistria", game_cmd=None, env=None):
        cmd = game_cmd if game_cmd is not None else [str(self.game / exe), *extra]
        return subprocess.Popen([str(self.bin / "mistrimulti-launcher"), "--steam", *cmd], cwd=self.game,
                                env=env if env is not None else self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def ran(self):
        p = self.game / "ran.txt"
        return p.read_text() if p.exists() else None

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def wait_for(cond, secs=15):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        try:
            if cond():
                return True
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.1)
    return False


def finish(proc):
    proc.communicate(timeout=60)
    return proc.returncode


def assert_standby(sb, name):
    """No valid launcher.cfg: the game started, nothing is hosted or joined, no helper, no bridge, a status the menu can read."""
    ctl = json.loads((sb.mod / "control.json").read_text())
    assert ctl["enabled"] is False and ctl["mode"] == "idle", f"{name}: control.json {ctl}"
    assert not list(sb.mod.glob("bridge_*")), f"{name}: bridge created"
    log = (sb.mod / "launcher.log").read_text()
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
        assert cfg["bridge"] == str(sb.mod / "bridge_0"), cfg
        assert len(cfg["epoch"]) == 32, cfg
        bridge = sb.mod / "bridge_0"
        assert wait_for(lambda: json.loads((bridge / "status.json").read_text())["running"]), "helper did not start"
        code = finish(proc)
        assert code == 7, f"game exit code not passed through: {code}"
        assert json.loads(ctl.read_text())["enabled"] is False, "control.json not disabled afterwards"
        assert "--windowed" in sb.ran().split("\n"), sb.ran()
        backups = list((sb.mod / "solo_backups").iterdir())
        assert len(backups) == 1 and (backups[0] / "game-1-autosave.sav").read_bytes() == b"solo world"
        assert len(backups[0].name) == 15 and backups[0].name[8] == "-", backups[0].name
        assert (sb.saves / "game-1-autosave.sav").read_bytes() == b"solo world", "solo save was changed"
        assert (sb.mod / "local_identity.json").exists()
        assert (bridge / "stop.flag").exists(), "the launcher did not ask the helper to stop"
        print("host: helper started, control.json written and disabled, exit code and args passed, solo saves backed up")
    finally:
        sb.cleanup()


def test_helper_args():
    """The helper gets exactly the arguments the Windows launcher passes (checked with a stand-in helper)."""
    sb = Sandbox()
    try:
        stub = sb.bin / HELPER_NAME
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$(dirname "$0")/helper_args.txt"\nsleep 30\n')
        stub.chmod(0o755)
        sb.config("mode=join\r\nhost=127.0.0.1\r\nport=47801\r\nplayer=3\r\nroom=abcdef12\r\n")
        proc = sb.steam(["--quick"])
        assert wait_for(lambda: (sb.bin / "helper_args.txt").exists())
        time.sleep(0.2)
        args = (sb.bin / "helper_args.txt").read_text().split("\n")[:-1]
        assert args == ["join", "47804", "3", "abcdef12", str(sb.mod / "bridge_3"), "127.0.0.1", "47801"], args
        finish(proc)
        sb.config("mode=host\r\nport=47802\r\n")
        (sb.bin / "helper_args.txt").unlink()
        proc = sb.steam(["--quick"])
        assert wait_for(lambda: (sb.bin / "helper_args.txt").exists())
        time.sleep(0.2)
        args = (sb.bin / "helper_args.txt").read_text().split("\n")[:-1]
        assert args == ["host", "47802", "0", "4d495354", str(sb.mod / "bridge_0")], args
        finish(proc)
        print("helper args: host and join command lines identical to the Windows launcher's")
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
        "port overflow": "mode=join\r\nhost=1.2.3.4\r\nplayer=7\r\nport=65535\r\nroom=abcd1234\r\n",
        "zero player": "mode=join\r\nhost=1.2.3.4\r\nplayer=0\r\n",
    }
    for name, text in cases.items():
        sb = Sandbox()
        try:
            if text is not None:
                sb.config(text)
            proc = sb.steam()
            code = finish(proc)
            assert code == 7, f"{name}: game must still start, exit {code}"
            assert sb.ran() is not None, f"{name}: game did not run"
            assert_standby(sb, name)
        finally:
            sb.cleanup()
    # a config that is a directory, a FIFO nobody writes to (must not hang), or a symlink to nowhere
    sb = Sandbox()
    try:
        (sb.mod / "launcher.cfg").mkdir()
        assert finish(sb.steam()) == 7 and sb.ran() is not None
        assert_standby(sb, "directory as launcher.cfg")
        (sb.mod / "launcher.cfg").rmdir()
        os.mkfifo(sb.mod / "launcher.cfg")
        (sb.game / "ran.txt").unlink()
        t0 = time.time()
        assert finish(sb.steam()) == 7 and sb.ran() is not None and time.time() - t0 < 8, "a FIFO as launcher.cfg hung the launcher"
        (sb.mod / "launcher.cfg").unlink()
        (sb.mod / "launcher.cfg").symlink_to(sb.root / "nowhere")
        (sb.game / "ran.txt").unlink()
        assert finish(sb.steam()) == 7 and sb.ran() is not None
        assert_standby(sb, "dangling symlink as launcher.cfg")
        # stderr is a pipe nobody reads any more (the launcher reports why multiplayer did not start there): no SIGPIPE death
        (sb.mod / "launcher.cfg").unlink()
        (sb.game / "ran.txt").unlink()
        r, w = os.pipe()
        os.close(r)
        proc = subprocess.Popen([str(sb.bin / "mistrimulti-launcher"), "--steam", str(sb.game / "FieldsOfMistria"), "--quick"], cwd=sb.game,
                                env=sb.env(), stdout=subprocess.PIPE, stderr=w)
        os.close(w)
        assert finish(proc) == 7 and sb.ran() is not None, "a closed stderr must not stop the game"
    finally:
        sb.cleanup()
    # the helper is missing, not executable, or cannot be started: control.json is disabled again and the game runs
    for how in ("missing", "not executable", "exits at once"):
        sb = Sandbox()
        try:
            sb.config("mode=host\r\nport=47812\r\nroom=a1b2c3d4\r\n")
            target = sb.bin / HELPER_NAME
            if how == "missing":
                target.unlink()
            elif how == "not executable":
                target.chmod(0o644)
            else:
                target.write_text("#!/bin/sh\nexit 3\n")
                target.chmod(0o755)
            code = finish(sb.steam())
            assert code == 7 and sb.ran() is not None, f"helper {how}: game exit {code}"
            ctl = sb.mod / "control.json"
            assert not ctl.exists() or json.loads(ctl.read_text())["enabled"] is False, f"helper {how}: control.json left enabled"
            assert "network helper could not be started" in (sb.mod / "launcher.log").read_text(), how
        finally:
            sb.cleanup()
    # the game folder cannot be determined: no multiplayer, the game still starts
    sb = Sandbox()
    try:
        env = sb.env()
        del env["MISTRIMULTI_DATA_DIR"]
        env["HOME"] = str(sb.root / "nohome")
        code = finish(sb.steam(env=env))
        assert code == 7 and sb.ran() is not None
        env["MISTRIMULTI_DATA_DIR"] = 'relative/or"bad'
        (sb.game / "ran.txt").unlink()
        code = finish(sb.steam(env=env))
        assert code == 7 and sb.ran() is not None, "an invalid MISTRIMULTI_DATA_DIR must not stop the game"
    finally:
        sb.cleanup()
    print("fallbacks: game always starts, nothing multiplayer is enabled for", ", ".join(cases), "+ bad helper, no game folder")


def test_direct_and_wrong_exe():
    sb = Sandbox()
    try:
        sb.config("mode=host\r\nroom=a1b2c3d4\r\n")
        code = finish(sb.steam(["--mistrimulti-direct"]))
        assert code == 7 and sb.ran() is not None
        assert not (sb.mod / "control.json").exists(), "direct launch must not start multiplayer"
        (sb.game / "ran.txt").unlink()
        code = finish(sb.steam(exe="OtherGame"))
        assert code == 7 and sb.ran() is not None
        assert not (sb.mod / "control.json").exists(), "only FieldsOfMistria may start multiplayer"
        # the game's file name is matched without regard to case
        shutil.copy(fake, sb.game / "FIELDSOFMISTRIA.EXE")
        (sb.game / "FIELDSOFMISTRIA.EXE").chmod(0o755)
        (sb.game / "ran.txt").unlink()
        proc = sb.steam(["--quick"], exe="FIELDSOFMISTRIA.EXE")
        assert wait_for(lambda: json.loads((sb.mod / "control.json").read_text())["enabled"] is True)
        finish(proc)
        # a Proton style command: the wrapper program first, the game executable as an argument
        (sb.game / "ran.txt").unlink()
        proc = sb.steam(game_cmd=[str(sb.game / "proton"), "waitforexitandrun", str(sb.game / "FieldsOfMistria.exe"), "--quick"])
        assert wait_for(lambda: json.loads((sb.mod / "control.json").read_text())["enabled"] is True), "Proton style command did not start multiplayer"
        assert finish(proc) == 7
        assert sb.ran().split("\n")[1:3] == ["waitforexitandrun", str(sb.game / "FieldsOfMistria.exe")], sb.ran()
        # the command is found through PATH when it has no slash
        (sb.game / "ran.txt").unlink()
        env = sb.env(PATH=str(sb.game) + ":" + os.environ["PATH"])
        assert finish(sb.steam(game_cmd=["proton", "--quick", "FieldsOfMistria"], env=env)) == 7
        assert sb.ran().split("\n")[0] == "proton", sb.ran()
        # a missing game command: the launcher fails cleanly instead of hanging
        proc = sb.steam(game_cmd=[str(sb.game / "nonexistent" / "FieldsOfMistria")])
        assert finish(proc) == 127
        print("direct: --mistrimulti-direct and other programs launch plainly; Proton style and PATH commands work")
    finally:
        sb.cleanup()


def test_time_stamps():
    """The backup folder names come from hand written date arithmetic: check it against Python over 100 years, leap days included."""
    if manager is None:
        return
    import calendar
    import random
    rng = random.Random(7)
    epochs = [0, 1, 86399, 86400, 951782400, 951868799, 951868800, 1078012800, 1078099200, 1709164800 - 1, 1709164800, 1709251200,
              4107542400, 4107628800, 4102444799, 4102444800, 1000000000, 2147483647, 2147483648, 4294967295, 7258118400, 253402300799]
    epochs += [calendar.timegm((y, m, d, 23, 59, 59)) for y in (1999, 2000, 2023, 2024, 2100) for m, d in ((2, 28), (2, 29) if calendar.isleap(y) else (2, 28), (3, 1), (12, 31), (1, 1))]
    epochs += [rng.randrange(0, 4_200_000_000) for _ in range(400)]
    for e in epochs:
        out = subprocess.run([str(manager), "--stamp", str(e)], capture_output=True, text=True, timeout=10).stdout.strip()
        want = time.strftime("%Y%m%d-%H%M%S", time.gmtime(e))
        assert out == want, (e, out, want)
    print("time stamps: %d moments from 1970 to 9999 match Python's gmtime (leap days, century years, year 2038)" % len(epochs))


def test_backup_prune():
    sb = Sandbox()
    try:
        sb.config("mode=host\r\nport=47831\r\nroom=a1b2c3d4\r\n")
        (sb.saves / "game-2-3.sav").write_bytes(b"second slot")
        (sb.saves / "sub").mkdir()
        (sb.saves / "sub" / "nested.sav").write_bytes(b"x")
        root = sb.mod / "solo_backups"
        for i in range(12):
            d = root / f"2020010{(i % 9) + 1}-0000{i:02d}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "x.sav").write_bytes(b"old")
        keep = root / "not-a-backup"
        keep.mkdir()
        (keep / "mine.txt").write_text("keep")
        finish(sb.steam("--quick".split()))
        names = sorted(p.name for p in root.iterdir())
        stamps = [n for n in names if n[:8].isdigit()]
        assert len(stamps) == 10, names
        assert (keep / "mine.txt").exists(), "a folder that is not a backup was touched"
        newest = root / stamps[-1]
        assert (newest / "game-1-autosave.sav").read_bytes() == b"solo world" and (newest / "game-2-3.sav").read_bytes() == b"second slot"
        assert not (newest / "sub").exists(), "folders are not copied"
        assert (sb.saves / "sub" / "nested.sav").exists() and (sb.saves / "game-2-3.sav").exists(), "solo saves were touched"
        assert "20200101-000000" not in stamps and "20200102-000001" not in stamps, "the oldest backups should be gone"
        print("prune: 10 newest backups kept, foreign folders untouched, saves copied not moved")
    finally:
        sb.cleanup()


def run_configure(sb, text, args=("--configure",)):
    p = subprocess.run([str(sb.bin / "mistrimulti-launcher"), *args], input=text.encode(), env=sb.env(), capture_output=True, timeout=60)
    return p.stdout.decode(errors="replace"), p.returncode


def test_configure():
    sb = Sandbox()
    try:
        run = lambda text, args=("--configure",): run_configure(sb, text, args)[0]
        out = run("h\n\n\n")
        cfg = (sb.mod / "launcher.cfg").read_bytes().decode()
        assert cfg == "mode=host\r\nhost=\r\nport=7777\r\nplayer=0\r\nroom=4d495354\r\n", repr(cfg)
        assert '--steam %command%' in out and str(sb.bin / "mistrimulti-launcher") in out and "Tailscale" in out, out
        run("h\n\n\n", args=())          # no arguments is the setup too
        assert (sb.mod / "launcher.cfg").exists()
        # a friend joins with only the host's IP: room code and player number are filled in
        run("j\n100.101.102.103\n\n\n\n\n")
        cfg = (sb.mod / "launcher.cfg").read_text()
        assert "mode=join" in cfg and "host=100.101.102.103" in cfg and "port=7777" in cfg and "room=4d495354" in cfg, cfg
        player = int([l for l in cfg.splitlines() if l.startswith("player=")][0][7:])
        assert 1 <= player <= 7, cfg
        run("j\n100.101.102.103\n\n\n\n\n")
        assert f"player={player}" in (sb.mod / "launcher.cfg").read_text(), "Enter must keep the earlier player number"
        run("j\n192.168.1.20\n\n3\nABCDEF12\n\n")
        cfg = (sb.mod / "launcher.cfg").read_text()
        assert "mode=join" in cfg and "host=192.168.1.20" in cfg and "player=3" in cfg and "room=ABCDEF12" in cfg, cfg
        run("j\n300.1.1.1\n192.168.1.9\n8001\n9\n2\nnothex\nabcd1234\n\n")
        cfg = (sb.mod / "launcher.cfg").read_text()
        assert "host=192.168.1.9" in cfg and "port=8001" in cfg and "player=2" in cfg and "room=abcd1234" in cfg, cfg
        before = (sb.mod / "launcher.cfg").read_text()
        out, code = run_configure(sb, "j\nbad\nbad\nbad\nbad\nbad\n")
        assert (sb.mod / "launcher.cfg").read_text() == before, "invalid input must not change the saved setup"
        assert code == 1 and "Setup was not saved" in out, (code, out)
        out, code = run_configure(sb, "")           # end of input at the first question
        assert code == 1 and (sb.mod / "launcher.cfg").read_text() == before
        # a host keeps a custom room code it already had
        sb.config("mode=host\r\nport=7777\r\nroom=a1b2c3d4\r\n")
        run("h\n\n\n")
        assert "room=a1b2c3d4" in (sb.mod / "launcher.cfg").read_text()
        # a config with no room code at all is valid and uses the default; a join with only an IP works end to end
        sb.config("mode=join\r\nhost=127.0.0.1\r\nplayer=2\r\nport=47861\r\n")
        proc = sb.steam()
        assert wait_for(lambda: json.loads((sb.mod / "control.json").read_text())["enabled"] is True), "IP-only join did not start"
        finish(proc)
        print("configure: IP-only join, default room, kept player number, validation, launch option printed")
    finally:
        sb.cleanup()


def query_host(timeout=2.0, payload=None, port=7776):
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
        assert name.decode() == os.uname().nodename[:31], (name, os.uname().nodename)
        assert reply[40:] == b"\x00" * 24 and reply[39] == 0
        assert query_host(0.7, b"MSDQ\x01") is None, "short query must not be answered"
        assert query_host(0.7, b"XXXX\x01" + b"\x00" * 59) is None, "wrong magic must not be answered"
        assert query_host(0.7, b"MSDQ\x09" + b"\x00" * 59) is None, "unknown version must not be answered"
        assert query_host(0.7, b"MSDQ\x01" + b"\x00" * 200) is None, "oversized query must not be answered"
        assert query_host(2.0) is not None, "the responder must survive junk"
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


def scan_with_manager(sb, extra="127.0.0.1", **env):
    out = sb.root / "scan.txt"
    if out.exists():
        out.unlink()
    subprocess.run([str(sb.bin / "mistrimulti-manager"), "--scan", str(out)], env=sb.env(MISTRIMULTI_SCAN_EXTRA=extra, **env),
                   timeout=60, check=True, capture_output=True)
    return out.read_text() if out.exists() else ""


def test_scan():
    if manager is None:
        print("scan: skipped (pass the manager as the fourth argument)")
        return
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
        text = scan_with_manager(sb)
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
    sb = Sandbox()
    try:
        sb.config("mode=host\r\nport=47871\r\n")
        proc = sb.steam()
        assert wait_for(lambda: (sb.mod / "bridge_0" / "status.json").exists())
        found = ""
        for _ in range(6):
            found = scan_with_manager(sb)
            if "127.0.0.1" in found:
                break
        lines = [l for l in found.splitlines() if l.strip()]
        assert lines and lines[0].split(" ")[0] == "127.0.0.1" and lines[0].split(" ")[1] == "47871" and lines[0].split(" ")[2] == "0", found
        finish(proc)
        assert scan_with_manager(sb).strip() == "", "no host should be found after the game closed"
        print("scan: finds the real host, cleans names, ignores junk and duplicates, finds nothing when nobody hosts")
    finally:
        sb.cleanup()


def test_scan_tailscale():
    """Tailscale peers become scan targets: a fake `tailscale status --json` lists peers; only valid 100.64/10 addresses count."""
    if manager is None:
        return
    sb = Sandbox()
    try:
        fake_ts = sb.bin / "tailscale"
        fake_ts.write_text('#!/bin/sh\n[ "$1 $2" = "status --json" ] || exit 2\n'
                           'echo \'{"Self":{"TailscaleIPs":["100.100.1.2","fd7a::1"]},"Peer":{'
                           '"a":{"TailscaleIPs":["100.101.102.103","fd7a::2"]},"b":{"TailscaleIPs":["100.64.0.1"]},'
                           '"c":{"TailscaleIPs":["100.1.2.3"]},"d":{"TailscaleIPs":["100.300.1.1"]},"e":{"TailscaleIPs":["100.127.255.254"]},'
                           '"f":{"TailscaleIPs":["100.128.0.1"]},"g":{"TailscaleIPs":["100.100.1.2"]},"h":{"Note":"100.99.99.99 unquoted"}}}\'\n')
        fake_ts.chmod(0o755)
        out = sb.root / "targets.txt"

        def targets(**env):
            subprocess.run([str(sb.bin / "mistrimulti-manager"), "--targets", str(out)], env=sb.env(**env), timeout=60, check=True, capture_output=True)
            lines = out.read_text().split("\n")
            return [l for l in lines if l.startswith("self ")], [l[7:] for l in lines if l.startswith("target ")]

        selfs, tg = targets(MISTRIMULTI_TAILSCALE=str(fake_ts))
        assert selfs == ["self 100.100.1.2"], selfs
        ts_targets = sorted(t for t in tg if t.startswith("100."))
        assert ts_targets == sorted(["100.100.1.2", "100.101.102.103", "100.64.0.1", "100.127.255.254"]), ts_targets
        # no tailscale at all (missing program, failing program, hanging program): the scan still works without it
        selfs, tg = targets(MISTRIMULTI_TAILSCALE=str(sb.bin / "does-not-exist"))
        assert selfs == [] and not [t for t in tg if t.startswith("100.")]
        fake_ts.write_text("#!/bin/sh\nexit 1\n")
        selfs, tg = targets(MISTRIMULTI_TAILSCALE=str(fake_ts))
        assert selfs == []
        fake_ts.write_text("#!/bin/sh\nsleep 60\n")
        t0 = time.time()
        selfs, tg = targets(MISTRIMULTI_TAILSCALE=str(fake_ts))
        assert selfs == [] and time.time() - t0 < 12, "a hanging tailscale must not stall the scan"
        # the PATH is searched for plain `tailscale`
        fake_ts.write_text('#!/bin/sh\necho \'{"Self":{"TailscaleIPs":["100.70.1.1"]}}\'\n')
        selfs, tg = targets(PATH=str(sb.bin) + ":" + os.environ["PATH"])
        assert selfs == ["self 100.70.1.1"], selfs
        print("tailscale: peers become scan targets (valid 100.64/10 only); missing, failing and hanging tailscale are harmless")
    finally:
        sb.cleanup()


def world_request(payload=None, timeout=10):
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
    sb = Sandbox()
    try:
        sb.mp.mkdir(parents=True)
        old = os.urandom(50_000)
        new = os.urandom(200_000)
        (sb.mp / "game-1-autosave.sav").write_bytes(old)
        (sb.mp / "game-2-autosave.sav").write_bytes(new)
        (sb.mp / "game-3-autosave.old.sav").write_bytes(b"newest but not a valid save name")
        (sb.mp / "notes.txt").write_bytes(b"x")
        (sb.mp / "game-9-7.sav").mkdir()
        os.utime(sb.mp / "game-1-autosave.sav", (1_700_000_000, 1_700_000_000))
        os.utime(sb.mp / "game-2-autosave.sav", (1_700_000_100, 1_700_000_100))
        os.utime(sb.mp / "game-3-autosave.old.sav", (1_700_000_200, 1_700_000_200))
        os.utime(sb.mp / "game-9-7.sav", (1_700_000_300, 1_700_000_300))
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
        # a client that asks for the world and hangs up without reading it (the launcher must survive the broken pipe)
        for _ in range(3):
            quitter = socket.socket()
            quitter.connect(("127.0.0.1", 7775))
            quitter.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")   # reset instead of a clean close
            quitter.sendall(b"MSWQ\x01" + b"\x00" * 11)
            quitter.close()
        time.sleep(0.5)
        again = world_request()
        assert again and again[112:] == new, "the world server died after a client reset the connection"
        assert proc.poll() is None, "the launcher died (SIGPIPE?)"
        # a client that connects and says nothing does not block the game or later clients for long
        silent = socket.socket()
        silent.connect(("127.0.0.1", 7775))
        t0 = time.time()
        again = world_request(timeout=20)
        silent.close()
        assert again and again[112:] == new and time.time() - t0 < 10, time.time() - t0
        # nothing to give: status 1
        for f in sb.mp.iterdir():
            if f.is_dir():
                f.rmdir()
            else:
                f.unlink()
        none = world_request()
        assert none and len(none) == 112 and none[5] == 1, none[:8] if none else none
        finish(proc)
        print("world server: newest valid save is sent with a correct checksum, look-alike files ignored, junk requests dropped, status 1 when there is nothing")
    finally:
        sb.cleanup()


def test_world_round_trip():
    """The manager's download client against the real launcher serving a world (several sizes, in one hosting session)."""
    if manager is None:
        return
    sb = Sandbox()
    try:
        sb.mp.mkdir(parents=True)
        sb.config("mode=host\r\nport=47891\r\n")
        proc = sb.steam(["--slow"])
        assert wait_for(lambda: (sb.mod / "bridge_0" / "status.json").exists())
        dest = sb.root / "guest" / "saves"
        result = sb.root / "result.txt"

        def fetch():
            subprocess.run([str(sb.bin / "mistrimulti-manager"), "--fetch", "127.0.0.1", str(dest), str(result)], env=sb.env(),
                           timeout=60, check=True, capture_output=True)
            return int(result.read_text())
        assert wait_for(lambda: fetch() in (0, 2), 10), "the world server never started"
        for n, size in enumerate((1, 63, 64, 65, 4096, 1_000_003, 5_000_000)):
            for f in sb.mp.iterdir():
                f.unlink()
            data = os.urandom(size)
            (sb.mp / f"game-5-{n + 1}.sav").write_bytes(data)
            code = fetch()
            assert code == 0, (size, code)
            assert (dest / f"game-5-{n + 1}.sav").read_bytes() == data and not list(dest.glob("*.part")), size
        # an existing copy is replaced atomically by a newer one with the same name
        data = os.urandom(777)
        (sb.mp / "game-5-7.sav").write_bytes(data)
        os.utime(sb.mp / "game-5-7.sav", (1_800_000_000, 1_800_000_000))
        for f in sb.mp.iterdir():
            if f.name != "game-5-7.sav":
                f.unlink()
        assert fetch() == 0 and (dest / "game-5-7.sav").read_bytes() == data
        for f in sb.mp.iterdir():
            f.unlink()
        assert fetch() == 2, "no world on the host is reported as such"
        finish(proc)
        print("world round trip: manager downloads what the launcher serves, byte for byte (7 sizes up to 5 MB)")
    finally:
        sb.cleanup()


def test_guest_refreshes_world():
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
            # a host that refuses the connection
            (sb2.game / "ran.txt").unlink()
            sb2.config("mode=join\r\nhost=127.0.0.1\r\nplayer=2\r\nport=47892\r\n")
            code = finish(sb2.steam(["--quick"]))
            assert code == 7 and sb2.ran() is not None
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
              b"a1b2c3d4", b"a1b2c3d45", b'a"b', b"a\\b", b"%s%s%s%n", b"\xff\xfe\xfd", b"7777", b"3", b" 3 ", b"$(touch pwned)", b"../../x"]
    for case in range(40):
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
            assert not (sb.game / "pwned").exists() and not (sb.root / "pwned").exists()
        finally:
            sb.cleanup()
    print("fuzz: 40 malformed configuration files, the game always started and control.json stayed valid")


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
        proc.kill()
        proc.wait()
        time.sleep(3)
        first = json.loads(status.read_text())["heartbeat"]
        time.sleep(2.5)
        second = json.loads(status.read_text())["heartbeat"]
        assert first == second, "helper kept running after the launcher was killed"
        print("pdeathsig: helper stopped when the launcher was killed")
    finally:
        # the fake game of the killed launcher is orphaned and exits by itself after three seconds
        sb.cleanup()


def test_steam_probe_and_identity():
    sb = Sandbox()
    try:
        probe = sb.bin / "mistrimulti-steam-id-linux"
        probe.write_text('#!/bin/sh\n[ -f "$1" ] || exit 1\necho steam:76561198000000001\n')
        probe.chmod(0o755)
        (sb.game / "libsteam_api.so").write_bytes(b"not a real library")
        sb.config("mode=host\r\nport=47813\r\nroom=a1b2c3d4\r\n")
        proc = sb.steam(["--quick"])
        ctl = sb.mod / "control.json"
        assert wait_for(lambda: json.loads(ctl.read_text())["enabled"] is True)
        assert json.loads(ctl.read_text())["uid"] == "steam:76561198000000001", ctl.read_text()
        finish(proc)
        assert not (sb.mod / "steamid.tmp").exists(), "temporary probe output left behind"
        # a probe that prints rubbish, hangs, or fails: fall back to the local identity
        for body in ('echo hello', 'echo steam:1234', 'sleep 30', 'exit 5', 'echo steam:7656119800000000x'):
            probe.write_text(f"#!/bin/sh\n{body}\n")
            t0 = time.time()
            proc = sb.steam(["--quick"])
            assert wait_for(lambda: json.loads(ctl.read_text())["enabled"] is True and json.loads(ctl.read_text())["uid"].startswith("local:"), 15), body
            finish(proc)
            assert time.time() - t0 < 14, f"probe '{body}' delayed the start too long"
        # no library next to the game: the probe is not even run
        (sb.game / "libsteam_api.so").unlink()
        probe.write_text('#!/bin/sh\necho steam:76561198000000001\n')
        proc = sb.steam(["--quick"])
        assert wait_for(lambda: json.loads(ctl.read_text())["uid"].startswith("local:"))
        finish(proc)
        # a damaged identity file is replaced by a fresh local identity
        (sb.mod / "local_identity.json").write_text('{"uid":"local:xyz"}')
        proc = sb.steam(["--quick"])
        assert wait_for(lambda: json.loads(ctl.read_text())["enabled"] is True)
        uid = json.loads(ctl.read_text())["uid"]
        finish(proc)
        assert uid.startswith("local:") and len(uid) == 38 and json.loads((sb.mod / "local_identity.json").read_text())["uid"] == uid
        print("identity: Steam probe used when valid, local identity otherwise (bad output, hang, failure, damaged file)")
    finally:
        sb.cleanup()


def test_data_dir_discovery_and_proton():
    sb = Sandbox()
    try:
        cfg = "mode=host\r\nport=47814\r\nroom=a1b2c3d4\r\n"
        # nothing set: found in ~/.config/FieldsOfMistria
        native = sb.home / ".config" / "FieldsOfMistria"
        (native / "saves").mkdir(parents=True)
        (native / "mod_data" / "mistrimulti").mkdir(parents=True)
        (native / "mod_data" / "mistrimulti" / "launcher.cfg").write_text(cfg)
        env = sb.env()
        del env["MISTRIMULTI_DATA_DIR"]
        proc = sb.steam(["--quick"], env=env)
        assert wait_for(lambda: (native / "mod_data" / "mistrimulti" / "control.json").exists())
        ctl = json.loads((native / "mod_data" / "mistrimulti" / "control.json").read_text())
        assert ctl["bridge"] == str(native / "mod_data" / "mistrimulti" / "bridge_0"), ctl
        finish(proc)
        shutil.rmtree(native)
        # XDG_CONFIG_HOME is honoured
        xdg = sb.root / "xdgconf" / "FieldsOfMistria"
        (xdg / "saves").mkdir(parents=True)
        (xdg / "mod_data" / "mistrimulti").mkdir(parents=True)
        (xdg / "mod_data" / "mistrimulti" / "launcher.cfg").write_text(cfg)
        env2 = dict(env, XDG_CONFIG_HOME=str(sb.root / "xdgconf"))
        finish(sb.steam(["--quick"], env=env2))
        assert (xdg / "mod_data" / "mistrimulti" / "control.json").exists()
        shutil.rmtree(sb.root / "xdgconf")
        # XDG_DATA_HOME is honoured too
        xdgd = sb.root / "xdgdata" / "FieldsOfMistria"
        (xdgd / "saves").mkdir(parents=True)
        (xdgd / "mod_data" / "mistrimulti").mkdir(parents=True)
        (xdgd / "mod_data" / "mistrimulti" / "launcher.cfg").write_text(cfg)
        finish(sb.steam(["--quick"], env=dict(env, XDG_DATA_HOME=str(sb.root / "xdgdata"))))
        assert (xdgd / "mod_data" / "mistrimulti" / "control.json").exists()
        shutil.rmtree(sb.root / "xdgdata")
        # a Steam Deck / Proton layout: found by scanning compatdata, and the bridge is written the way the Windows game sees it
        steam = sb.home / ".local" / "share" / "Steam"
        proton = steam / "steamapps" / "compatdata" / "2142790" / "pfx" / "drive_c" / "users" / "steamuser" / "AppData" / "Local" / "FieldsOfMistria"
        (steam / "steamapps" / "compatdata" / "99999").mkdir(parents=True)
        (proton / "saves").mkdir(parents=True)
        (proton / "saves" / "game-1-autosave.sav").write_bytes(b"deck world")
        (proton / "mod_data" / "mistrimulti").mkdir(parents=True)
        (proton / "mod_data" / "mistrimulti" / "launcher.cfg").write_text(cfg)
        proc = sb.steam(["--quick"], env=env)
        ctl_path = proton / "mod_data" / "mistrimulti" / "control.json"
        assert wait_for(lambda: ctl_path.exists())
        ctl = json.loads(ctl_path.read_text())
        assert ctl["bridge"] == "C:/users/steamuser/AppData/Local/FieldsOfMistria/mod_data/mistrimulti/bridge_0", ctl
        finish(proc)
        assert any((proton / "mod_data" / "mistrimulti" / "solo_backups").iterdir()), "Proton saves were not backed up"
        # STEAM_COMPAT_DATA_PATH (set by Steam) wins and works even before the game created its folders
        shutil.rmtree(steam)
        compat = sb.root / "compat"
        env3 = dict(env, STEAM_COMPAT_DATA_PATH=str(compat))
        finish(sb.steam(["--quick"], env=env3))
        created = compat / "pfx" / "drive_c" / "users" / "steamuser" / "AppData" / "Local" / "FieldsOfMistria" / "mod_data" / "mistrimulti"
        assert created.exists() and (created / "launcher.log").exists(), "no folder created for a fresh Proton prefix"
        print("game folder: found in ~/.config, XDG_CONFIG_HOME, Steam compatdata and STEAM_COMPAT_DATA_PATH; Proton bridge path translated")
    finally:
        sb.cleanup()


def test_exit_codes_and_signals():
    sb = Sandbox()
    try:
        sb.config("mode=host\r\nport=47815\r\nroom=a1b2c3d4\r\n")
        script = sb.game / "FieldsOfMistria"
        script.write_text("#!/bin/sh\nsleep 1\nkill -TERM $$\n")
        script.chmod(0o755)
        code = finish(sb.steam())
        assert code == 128 + 15, f"a game killed by a signal should give 128+signal: {code}"
        assert json.loads((sb.mod / "control.json").read_text())["enabled"] is False
        script.write_text("#!/bin/sh\nexit 42\n")
        assert finish(sb.steam()) == 42
        sb.config("mode=banana\r\n")
        assert finish(sb.steam()) == 42, "exit code must pass through the plain launch too"
        # Steam stops a game with SIGTERM: the launcher passes it on, then cleans up (helper stopped, control.json disabled)
        import signal
        sb.config("mode=host\r\nport=47816\r\nroom=a1b2c3d4\r\n")
        shutil.copy(fake, script)
        script.chmod(0o755)
        (sb.game / "ran.txt").unlink(missing_ok=True)
        proc = sb.steam(["--slow"])
        status = sb.mod / "bridge_0" / "status.json"
        assert wait_for(lambda: status.exists() and (sb.game / "ran.txt").exists())
        proc.send_signal(signal.SIGTERM)
        t0 = time.time()
        code = finish(proc)
        assert code == 128 + 15 and time.time() - t0 < 6, (code, time.time() - t0)
        assert json.loads((sb.mod / "control.json").read_text())["enabled"] is False, "control.json left enabled after SIGTERM"
        assert (sb.mod / "bridge_0" / "stop.flag").exists()
        (sb.game / "ran.txt").unlink()
        status.unlink()
        proc = sb.steam(["--slow"])
        assert wait_for(lambda: status.exists() and (sb.game / "ran.txt").exists())
        proc.send_signal(signal.SIGINT)
        code = finish(proc)
        assert code == 128 + 2, code
        print("exit codes: normal exit, killed-by-signal and plain launch all pass through; SIGTERM/SIGINT reach the game and clean up")
    finally:
        sb.cleanup()


def run_manager(sb, args, text="", **env):
    p = subprocess.run([str(sb.bin / "mistrimulti-manager"), *args], input=text.encode(), env=sb.env(**env), capture_output=True, timeout=60)
    return p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace"), p.returncode


class FakeWorldHost:
    """A host for the manager to join: answers discovery on UDP 7776 and gives a world on TCP 7775."""

    def __init__(self, data=None, flags=0, name=b"Deck", udp=True):
        self.data = data
        self.udp = None
        self.requests = 0
        self.stop = threading.Event()
        self.tcp = socket.socket()
        self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp.bind(("127.0.0.1", 7775))
        self.tcp.listen(4)
        self.tcp.settimeout(0.3)
        self.flags, self.name = flags, name
        threads = [threading.Thread(target=self.serve_tcp, daemon=True)]
        if udp:
            self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp.bind(("127.0.0.1", 7776))
            self.udp.settimeout(0.3)
            threads.append(threading.Thread(target=self.serve_udp, daemon=True))
        for t in threads:
            t.start()

    def serve_udp(self):
        while not self.stop.is_set():
            try:
                data, addr = self.udp.recvfrom(256)
            except OSError:
                continue
            if len(data) == 64 and data[:4] == b"MSDQ":
                self.udp.sendto(b"MSDR\x01" + bytes([self.flags]) + (7777).to_bytes(2, "little") + self.name.ljust(32, b"\x00") + b"\x00" * 24, addr)

    def serve_tcp(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.tcp.accept()
            except OSError:
                continue
            with conn:
                try:
                    conn.settimeout(5)
                    conn.recv(16)
                    self.requests += 1
                    h = bytearray(112)
                    h[0:4] = b"MSWR"
                    h[4] = 1
                    if self.data is None:
                        h[5] = 1
                        conn.sendall(bytes(h))
                        continue
                    h[8:12] = len(self.data).to_bytes(4, "little")
                    h[12:44] = hashlib.sha256(self.data).digest()
                    h[48:48 + 19] = b"game-42-autosave.sav"[:19]
                    h[48:48 + 20] = b"game-42-autosave.sav"
                    conn.sendall(bytes(h) + self.data)
                except OSError:
                    pass

    def close(self):
        self.stop.set()
        time.sleep(0.4)
        self.tcp.close()
        if self.udp:
            self.udp.close()


def test_manager_host_and_steam_setup():
    if manager is None:
        return
    sb = Sandbox()
    try:
        fake_ts = sb.bin / "tailscale"
        fake_ts.write_text('#!/bin/sh\necho \'{"Self":{"TailscaleIPs":["100.70.1.1"]}}\'\n')
        fake_ts.chmod(0o755)
        out, err, rc = run_manager(sb, ["host"], MISTRIMULTI_TAILSCALE=str(fake_ts))
        assert rc == 0, (out, err)
        assert (sb.mod / "launcher.cfg").read_bytes() == b"mode=host\r\nport=7777\r\nplayer=0\r\nroom=\r\n"
        assert "You are set to host" in out and "Tailscale:    100.70.1.1" in out and "Multiplayer" in out, out
        assert "169.254" not in out
        # the saved host setup is accepted by the launcher
        proc = sb.steam(["--quick"])
        assert wait_for(lambda: json.loads((sb.mod / "control.json").read_text())["enabled"] is True), "launcher rejected the manager's host setup"
        finish(proc)
        # Tailscale not installed: still works, just no Tailscale line
        out, err, rc = run_manager(sb, ["host"], MISTRIMULTI_TAILSCALE=str(sb.bin / "nope"))
        assert rc == 0 and "Tailscale:" not in out and "You are set to host" in out, out
        # steam-setup prints the launch line for the launcher next to the manager
        out, err, rc = run_manager(sb, ["steam-setup"])
        assert rc == 0 and f'"{sb.bin}/mistrimulti-launcher" --steam %command%' in out, out
        assert "Warning" not in err
        (sb.bin / "mistrimulti-launcher").unlink()
        out, err, rc = run_manager(sb, ["steam-setup"])
        assert "not found next to the manager" in err
        # help and unknown commands
        out, err, rc = run_manager(sb, ["--help"])
        assert rc == 0 and "save-solo" in out
        out, err, rc = run_manager(sb, ["frobnicate"])
        assert rc == 2 and "mistrimulti-manager" in err
        out, err, rc = run_manager(sb, [])
        assert rc == 2
        # no game folder: a clear message, nothing written
        out, err, rc = run_manager(sb, ["host"], MISTRIMULTI_DATA_DIR="relative/path")
        assert rc == 1 and "Could not find the folder" in err
        print("manager host/steam-setup: host setup saved and accepted by the launcher, addresses shown, launch line printed")
    finally:
        sb.cleanup()


def test_manager_join():
    if manager is None:
        return
    sb = Sandbox()
    host = None
    try:
        data = os.urandom(150_000)
        host = FakeWorldHost(data)
        cfg = sb.mod / "launcher.cfg"
        out, err, rc = run_manager(sb, ["join", "127.0.0.1", "--player", "4", "--room", "abcd1234"])
        assert rc == 0, (out, err)
        assert cfg.read_bytes() == b"mode=join\r\nhost=127.0.0.1\r\nport=7777\r\nplayer=4\r\nroom=abcd1234\r\n", cfg.read_bytes()
        assert (sb.mp / "game-42-autosave.sav").read_bytes() == data and "was downloaded" in out and "Joining: 127.0.0.1" in out, out
        # IP only: automatic player number (kept on the next run), default room
        out, err, rc = run_manager(sb, ["join", "127.0.0.1"])
        assert rc == 0, (out, err)
        text = cfg.read_text()
        assert "room=4d495354" in text and "port=7777" in text, text
        player = int([l for l in text.splitlines() if l.startswith("player=")][0][7:])
        assert 1 <= player <= 7 and f"Your player number is {player}" in out
        run_manager(sb, ["join", "127.0.0.1"])
        assert f"player={player}" in cfg.read_text(), "the earlier player number should be kept"
        # a different port and the launcher accepts what the manager wrote
        run_manager(sb, ["join", "127.0.0.1", "--port", "8000", "--player", "2"])
        assert "port=8000" in cfg.read_text() and "player=2" in cfg.read_text()
        # invalid input changes nothing and exits with 2
        before = cfg.read_bytes()
        for bad in (["join", "999.1.1.1"], ["join", "1.2.3.4", "--player", "8"], ["join", "1.2.3.4", "--player", "0"], ["join", "1.2.3.4", "--room", "xyz"],
                    ["join", "1.2.3.4", "--port", "70000"], ["join", "1.2.3.4", "--port"], ["join", "1.2.3.4", "5.6.7.8"], ["join", "--bogus"]):
            out, err, rc = run_manager(sb, bad)
            assert rc == 2 and cfg.read_bytes() == before, (bad, rc, out, err)
        out, err, rc = run_manager(sb, ["join", "1.2.3.4", "--player", "7", "--port", "65535"])
        assert rc == 1 and cfg.read_bytes() == before, "port + player over 65535 must be refused"
        # the host has no world yet
        host.data = None
        out, err, rc = run_manager(sb, ["join", "127.0.0.1", "--player", "3"])
        assert rc == 0 and "could not be downloaded yet" in out and "player=3" in cfg.read_text(), out
        host.close()
        host = None
        # nobody listening at all: the setup is still saved
        out, err, rc = run_manager(sb, ["join", "127.0.0.1", "--player", "5"])
        assert rc == 0 and "could not be downloaded yet" in out and "player=5" in cfg.read_text()
        print("manager join <ip>: setup saved identical to the Windows format, world downloaded, bad input refused, missing world reported")
    finally:
        if host:
            host.close()
        sb.cleanup()


def test_manager_join_interactive():
    if manager is None:
        return
    sb = Sandbox()
    host = None
    try:
        data = os.urandom(5000)
        host = FakeWorldHost(data, flags=1, name=b"Tom's \x01Deck")
        cfg = sb.mod / "launcher.cfg"
        env = dict(MISTRIMULTI_SCAN_EXTRA="127.0.0.1", MISTRIMULTI_TAILSCALE=str(sb.bin / "nope"))
        # choose host 1 from the list; it needs a room code: a bad one is refused, then a good one is accepted
        out, err, rc = run_manager(sb, ["join"], "1\nnothex\nA1B2C3D4\n", **env)
        assert rc == 0, (out, err)
        assert "1) 127.0.0.1   -   Tom's ?Deck   [needs a room code]" in out, out
        assert "The room code must be 8 characters" in out, out
        text = cfg.read_text()
        assert "host=127.0.0.1" in text and "room=A1B2C3D4" in text and "port=7777" in text, text
        assert (sb.mp / "game-42-autosave.sav").read_bytes() == data
        # a wrong number, then R to scan again, then the number again
        cfg.unlink()
        out, err, rc = run_manager(sb, ["join"], "7\nR\n1\nabcd1234\n", **env)
        assert rc == 0 and "That is not one of the listed hosts" in out and out.count("Looking for hosts") == 2, out
        assert "room=abcd1234" in cfg.read_text()
        # typing an IP at the prompt asks for the room code (Enter = default)
        cfg.unlink()
        out, err, rc = run_manager(sb, ["join"], "127.0.0.1\n\n", **env)
        assert rc == 0 and "room=4d495354" in cfg.read_text(), out
        # Enter alone or the end of the input cancels without writing anything
        cfg.unlink()
        out, err, rc = run_manager(sb, ["join"], "\n", **env)
        assert rc == 1 and not cfg.exists() and "Nothing selected" in err
        out, err, rc = run_manager(sb, ["join"], "", **env)
        assert rc == 1 and not cfg.exists()
        host.close()
        host = None
        # nobody hosting: the list says so and offers to scan again
        out, err, rc = run_manager(sb, ["join"], "R\n", MISTRIMULTI_SCAN_EXTRA="127.0.0.1", MISTRIMULTI_TAILSCALE=str(sb.bin / "nope"))
        assert rc == 1 and "No host found" in out and out.count("Looking for hosts") == 2, out
        # `scan` only lists
        host = FakeWorldHost(None, flags=0, name=b"Solo")
        out, err, rc = run_manager(sb, ["scan"], **env)
        assert rc == 0 and "1) 127.0.0.1   -   Solo" in out and not cfg.exists(), out
        print("manager join (interactive): list, room code prompt and validation, rescan, typed IP, cancel, empty scan")
    finally:
        if host:
            host.close()
        sb.cleanup()


def test_manager_save_solo():
    if manager is None:
        return
    sb = Sandbox()
    try:
        (sb.saves / "game-2-3.sav").write_bytes(b"slot three")
        (sb.saves / "folder").mkdir()
        docs = sb.home / "Documents"
        out, err, rc = run_manager(sb, ["save-solo"])
        assert rc == 0 and "Saved 2 file(s) to:" in out, (out, err)
        backups = list((docs / "MistriMulti Backups").iterdir())
        assert len(backups) == 1 and (backups[0] / "game-1-autosave.sav").read_bytes() == b"solo world", backups
        assert (backups[0] / "game-2-3.sav").read_bytes() == b"slot three" and not (backups[0] / "folder").exists()
        assert str(backups[0]) in out
        assert (sb.saves / "game-1-autosave.sav").exists(), "the solo saves must stay where they are"
        # XDG_DOCUMENTS_DIR from the environment, from user-dirs.dirs ($HOME form and absolute form)
        time.sleep(1.1)
        other = sb.root / "elsewhere"
        out, err, rc = run_manager(sb, ["save-solo"], XDG_DOCUMENTS_DIR=str(other))
        assert rc == 0 and len(list((other / "MistriMulti Backups").iterdir())) == 1, out
        cfgdir = sb.home / ".config"
        cfgdir.mkdir()
        (cfgdir / "user-dirs.dirs").write_text('# comment\nXDG_DESKTOP_DIR="$HOME/Desktop"\nXDG_DOCUMENTS_DIR="$HOME/Papers"\n')
        out, err, rc = run_manager(sb, ["save-solo"])
        assert rc == 0 and len(list((sb.home / "Papers" / "MistriMulti Backups").iterdir())) == 1, out
        (cfgdir / "user-dirs.dirs").write_text('XDG_DOCUMENTS_DIR="%s"\n' % (sb.root / "abs"))
        out, err, rc = run_manager(sb, ["save-solo"])
        assert rc == 0 and len(list((sb.root / "abs" / "MistriMulti Backups").iterdir())) == 1, out
        # a damaged user-dirs.dirs falls back to ~/Documents
        (cfgdir / "user-dirs.dirs").write_bytes(b'XDG_DOCUMENTS_DIR="' + b"x" * 5000)
        time.sleep(1.1)
        out, err, rc = run_manager(sb, ["save-solo"])
        assert rc == 0 and len(list((docs / "MistriMulti Backups").iterdir())) == 2, out
        # nothing to back up
        for f in sb.saves.glob("*.sav"):
            f.unlink()
        out, err, rc = run_manager(sb, ["save-solo"])
        assert rc == 0 and "No solo saves were found" in out
        print("manager save-solo: copies saves to Documents/MistriMulti Backups/<time>, honours XDG_DOCUMENTS_DIR, never touches the originals")
    finally:
        sb.cleanup()


def test_password():
    """launcher.cfg password=: invalid ones stop multiplayer, valid ones reach the real helper (auth.cfg) and discovery."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import mmauth
    for name, text in {"space": "password=two words", "too long": "password=" + "x" * 65, "accent": "password=café",
                       "control": "password=ab\x01"}.items():
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
        s.settimeout(2)
        try:
            s.sendto(guest.hello(), ("127.0.0.1", port))
            challenge = s.recvfrom(256)[0]
            proof = guest.proof(challenge)
            s.sendto(proof, ("127.0.0.1", port))
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
        auth = bridge / "auth.cfg"
        assert auth.read_text().split("\n")[:4] == [f"key={sb.mod}/install.key", f"keys={sb.mod}/trust_keys.txt",
                                                    f"deny={sb.mod}/deny.txt", "pass=s3cret!pw"], auth.read_text()
        assert stat.S_IMODE(auth.stat().st_mode) == 0o600, oct(auth.stat().st_mode)
        assert wait_for(lambda: (sb.mod / "install.key").exists() and (sb.mod / "install.key").stat().st_size == 32), "no install key"
        assert stat.S_IMODE((sb.mod / "install.key").stat().st_mode) == 0o600
        challenge, result = handshake(b"s3cret!pw")
        assert result == "ok", result
        hfp = challenge[32:48]
        assert handshake(b"wrong")[1] == ("reject", 1)
        assert handshake(b"")[1] == ("reject", 1)
        for _ in range(20):
            reply = query_host(0.5)
            if reply:
                break
        assert reply is not None and reply[5] & 2, "the password flag is announced in discovery"
        finish(proc)
        # a second launch: same install key, so the same host fingerprint; no password configured now
        sb.config("mode=host\r\nport=47911\r\nroom=a1b2c3d4\r\n")
        proc = sb.steam(["--quick"])
        assert wait_for(lambda: (bridge / "status.json").exists() and "pass=" not in auth.read_text()), "auth.cfg keeps a removed password"
        time.sleep(0.5)
        challenge, result = handshake(b"")
        assert result == "ok" and challenge[32:48] == hfp, "the host fingerprint must survive a restart"
        for _ in range(20):
            reply = query_host(0.5)
            if reply:
                break
        assert reply is not None and not reply[5] & 2
        finish(proc)
        # --configure keeps a stored password; an unusable one is never written back
        sb.config("mode=host\r\nport=7777\r\nroom=a1b2c3d4\r\npassword=keep!me\r\n")
        run_configure(sb, "h\n\n\n")
        assert "password=keep!me" in (sb.mod / "launcher.cfg").read_text()
        sb.config("mode=host\r\nport=7777\r\nroom=a1b2c3d4\r\npassword=bad pass\r\n")
        run_configure(sb, "h\n\n\n")
        assert "password" not in (sb.mod / "launcher.cfg").read_text()
        print("password: invalid ones stop multiplayer, valid ones reach the helper (auth.cfg 0600), wrong ones are refused, "
              "discovery flag, stable host fingerprint, configure keeps it")
    finally:
        sb.cleanup()


def test_manager_password():
    if manager is None:
        return
    sb = Sandbox()
    try:
        cfg = sb.mod / "launcher.cfg"
        out, err, rc = run_manager(sb, ["host", "--password", "pa$$w0rd!"])
        assert rc == 0 and cfg.read_bytes() == b"mode=host\r\nport=7777\r\nplayer=0\r\nroom=\r\npassword=pa$$w0rd!\r\n", (rc, err, cfg.read_bytes())
        assert stat.S_IMODE(cfg.stat().st_mode) == 0o600
        out, err, rc = run_manager(sb, ["host"])
        assert rc == 0 and cfg.read_bytes() == b"mode=host\r\nport=7777\r\nplayer=0\r\nroom=\r\n", "host without --password drops the old one"
        before = cfg.read_bytes()
        for bad in (["host", "--password", "two words"], ["host", "--password"], ["host", "--password", "x" * 65], ["host", "--bogus"],
                    ["join", "1.2.3.4", "--password", "a b"], ["join", "1.2.3.4", "--password"], ["join", "1.2.3.4", "--password", "é"]):
            out, err, rc = run_manager(sb, bad)
            assert rc == 2 and cfg.read_bytes() == before, (bad, rc, out, err)
        out, err, rc = run_manager(sb, ["join", "127.0.0.1", "--player", "3", "--room", "abcd1234", "--password", "tops3cret"])
        assert rc == 0, (out, err)
        assert cfg.read_bytes() == b"mode=join\r\nhost=127.0.0.1\r\nport=7777\r\nplayer=3\r\nroom=abcd1234\r\npassword=tops3cret\r\n", cfg.read_bytes()
        # the launcher accepts what the manager wrote
        proc = sb.steam(["--quick"])
        assert wait_for(lambda: json.loads((sb.mod / "control.json").read_text())["enabled"] is True), "launcher rejected the password setup"
        assert wait_for(lambda: (sb.mod / "bridge_3" / "auth.cfg").exists())
        assert "pass=tops3cret" in (sb.mod / "bridge_3" / "auth.cfg").read_text()
        finish(proc)
        print("manager: --password for host and join written (0600), invalid ones refused, accepted by the launcher")
    finally:
        sb.cleanup()


# ---------------------------------------------------------------- the in-game menu: standby launcher + commands (linux/menu.inc)
_menu_seq = {}


def menu_cmd(sb, **fields):
    """What the mod does: write cmd.txt atomically (key=value lines), seq counting up per sandbox."""
    seq = _menu_seq[sb.root] = _menu_seq.get(sb.root, 0) + 1
    fields = {"seq": seq, **fields}
    tmp = sb.mod / "menu" / "cmd.tmp"
    tmp.write_text("".join(f"{k}={v}\n" for k, v in fields.items()))
    os.rename(tmp, sb.mod / "menu" / "cmd.txt")
    return seq


def menu_status(sb):
    return json.loads((sb.mod / "menu" / "status.json").read_text())


def menu_wait(sb, seq, states=("idle", "hosting", "ready", "error", "stopped"), secs=30):
    """Waits until the launcher answered command `seq` and is in one of the states; returns the status."""
    got = []

    def done():
        st = menu_status(sb)
        got.append(st)
        return st["seq"] == seq and st["state"] in states

    assert wait_for(done, secs), ("no answer to command", seq, got[-1] if got else None)
    return got[-1]


def start_menu_game(sb, *extra, **env):
    proc = sb.steam(["--slow", *extra], env=sb.env(**env) if env else None)
    assert wait_for(lambda: (sb.mod / "menu" / "status.json").exists()), "the launcher did not publish a menu status"
    return proc


def port_open_tcp(port):
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
        assert st["addrs"] == [] and st["hosts"] == [], st
        ctl = json.loads((sb.mod / "control.json").read_text())
        assert ctl["enabled"] is False and ctl["mode"] == "idle", ctl
        assert not port_open_tcp(7775) and port_free_udp(7776) and port_free_udp(7777), "standby must not listen on any port"
        assert query_host(0.7) is None, "standby must not answer discovery"
        assert not list(sb.mod.glob("bridge_*")), "no helper bridge in standby"
        # the heartbeat moves about once a second
        beats = {menu_status(sb)["hb"]}
        assert wait_for(lambda: beats.add(menu_status(sb)["hb"]) or len(beats) >= 3, 8), "the launcher's heartbeat does not move"
        code = finish(proc)
        assert code == 7
        assert menu_status(sb)["state"] == "stopped", menu_status(sb)
        # a command left over from an earlier run is not applied: the launcher removes it at start
        (sb.mod / "menu" / "cmd.txt").write_text("seq=5\ncmd=host\n")
        proc = start_menu_game(sb)
        time.sleep(1.5)
        assert menu_status(sb)["state"] == "idle" and not (sb.mod / "menu" / "cmd.txt").exists(), "a stale command was applied"
        finish(proc)
        print("menu standby: no launcher.cfg needed, idle status with a moving heartbeat, nothing listens, stale commands dropped, 'stopped' at exit")
    finally:
        sb.cleanup()


def test_menu_host_and_stop():
    sb = Sandbox()
    try:
        fake_ts = sb.bin / "tailscale"
        fake_ts.write_text('#!/bin/sh\necho \'{"Self":{"TailscaleIPs":["100.64.0.7"]}}\'\n')
        fake_ts.chmod(0o755)
        sb.mp.mkdir(parents=True)
        (sb.mp / "game-1-autosave.sav").write_bytes(b"hosted world")
        proc = start_menu_game(sb, MISTRIMULTI_TAILSCALE=str(fake_ts))
        seq = menu_cmd(sb, cmd="host", password="pa$$w0rd!")
        st = menu_wait(sb, seq, ("hosting", "error"))
        assert st["state"] == "hosting" and st["err"] == 0 and st["session"] == "host" and st["port"] == 7777, st
        assert st["addrs"][0] == "100.64.0.7", st                      # the Tailscale address first
        assert not (sb.mod / "menu" / "cmd.txt").exists(), "the command file must be consumed"
        ctl = json.loads((sb.mod / "control.json").read_text())
        assert ctl["enabled"] is True and ctl["mode"] == "host" and ctl["id"] == 0 and ctl["bridge"] == str(sb.mod / "bridge_0"), ctl
        assert wait_for(lambda: json.loads((sb.mod / "bridge_0" / "status.json").read_text())["running"]), "helper did not start"
        reply = None
        for _ in range(10):
            reply = query_host(0.5)
            if reply:
                break
        assert reply and reply[:4] == b"MSDR" and reply[5] == 2 and int.from_bytes(reply[6:8], "little") == 7777, reply and reply[:8]
        assert world_request()[:4] == b"MSWR", "the world server must run while hosting"
        # the password reached the helper (0600) and is nowhere else on disk
        auth = sb.mod / "bridge_0" / "auth.cfg"
        assert "pass=pa$$w0rd!" in auth.read_text() and stat.S_IMODE(auth.stat().st_mode) == 0o600
        leaks = [str(p) for p in sb.mod.rglob("*") if p.is_file() and p != auth and b"pa$$w0rd!" in p.read_bytes()]
        assert not leaks, f"the password leaked into {leaks}"
        # stop: everything closes again, control.json is disabled, the helper is asked to stop
        seq = menu_cmd(sb, cmd="stop")
        st = menu_wait(sb, seq, ("idle",))
        assert st["session"] == "none" and st["addrs"] == [], st
        assert not port_open_tcp(7775) and port_free_udp(7776) and query_host(0.7) is None, "stop must close the discovery answer and world server"
        assert json.loads((sb.mod / "control.json").read_text())["enabled"] is False
        assert (sb.mod / "bridge_0" / "stop.flag").exists()
        # hosting again with other settings and a room code: announced in the discovery flags
        seq = menu_cmd(sb, cmd="host", port="47931", room="A1B2C3D4")
        st = menu_wait(sb, seq, ("hosting", "error"))
        assert st["state"] == "hosting" and st["port"] == 47931, st
        for _ in range(10):
            reply = query_host(0.5)
            if reply:
                break
        assert reply and reply[5] == 1 and int.from_bytes(reply[6:8], "little") == 47931, reply and reply[:8]
        code = finish(proc)
        assert code == 7
        assert menu_status(sb)["state"] == "stopped" and json.loads((sb.mod / "control.json").read_text())["enabled"] is False
        assert not port_open_tcp(7775), "the world server must stop with the game"
        print("menu host: hosting from a command (Tailscale address first, password only in auth.cfg 0600), discovery and world server "
              "only while hosting, stop and game exit close everything")
    finally:
        sb.cleanup()


def test_menu_helper_arguments():
    """The helper started from a command gets the same arguments as from launcher.cfg (a stand-in helper records them)."""
    sb = Sandbox()
    try:
        stub = sb.bin / HELPER_NAME
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$(dirname "$0")/helper_args.txt"\nsleep 30\n')
        stub.chmod(0o755)
        proc = start_menu_game(sb)
        seq = menu_cmd(sb, cmd="host", port="47802", room="abcd1234")
        menu_wait(sb, seq, ("hosting",))
        args = (sb.bin / "helper_args.txt").read_text().split("\n")[:-1]
        assert args == ["host", "47802", "0", "abcd1234", str(sb.mod / "bridge_0")], args
        (sb.bin / "helper_args.txt").unlink()
        seq = menu_cmd(sb, cmd="join", host="127.0.0.1", port="47801")
        menu_wait(sb, seq, ("joining",))
        assert wait_for(lambda: (sb.bin / "helper_args.txt").exists())
        time.sleep(0.2)
        args = (sb.bin / "helper_args.txt").read_text().split("\n")[:-1]
        assert args[0] == "join" and 1 <= int(args[2]) <= 7 and args[3] == "4d495354" and args[5:] == ["127.0.0.1", "47801"], args
        assert int(args[1]) == 47801 + int(args[2]) and args[4] == str(sb.mod / f"bridge_{args[2]}"), args
        assert json.loads((sb.mod / "control.json").read_text())["id"] == int(args[2])
        menu_cmd(sb, cmd="stop")
        finish(proc)
        print("menu helper arguments: host and join command lines identical to launcher.cfg's")
    finally:
        sb.cleanup()


class MenuPair:
    """A host and a guest launcher, each with its own game folder, talking over the loopback interface."""

    def __init__(self, world=True):
        self.host, self.guest = Sandbox(), Sandbox()
        if world:
            self.host.mp.mkdir(parents=True)
            (self.host.mp / "game-7-autosave.sav").write_bytes(b"THE HOSTS WORLD " * 300)
        self.procs = []

    def start(self):
        self.procs.append(start_menu_game(self.host))
        self.procs.append(start_menu_game(self.guest, MISTRIMULTI_SCAN_EXTRA="127.0.0.1"))
        return self

    def close(self):
        for p in self.procs:
            try:
                p.terminate()
                p.communicate(timeout=30)
            except Exception:
                p.kill()
        self.host.cleanup()
        self.guest.cleanup()


def test_menu_scan_and_join():
    pair = MenuPair().start()
    host, guest = pair.host, pair.guest
    try:
        seq = menu_cmd(host, cmd="host", password="tops3cret")
        menu_wait(host, seq, ("hosting",))
        # scan: the host is found, with its password flag; "scan" counts only when finished
        seq = menu_cmd(guest, cmd="scan")
        st = menu_wait(guest, seq, ("idle",))
        assert st["scan"] == 1 and len(st["hosts"]) == 1, st
        found = st["hosts"][0]
        assert found["ip"] == "127.0.0.1" and found["port"] == 7777 and found["flags"] == 2 and found["name"], found
        # no password: refused with "password needed" (26) before anything is downloaded
        seq = menu_cmd(guest, cmd="join", host="127.0.0.1", port="7777")
        st = menu_wait(guest, seq, ("error", "ready"))
        assert st["state"] == "error" and st["err"] == 26, st
        assert not (guest.mp / "game-7-autosave.sav").exists(), "nothing may be downloaded after a refused join"
        assert json.loads((guest.mod / "control.json").read_text())["enabled"] is False
        # wrong password: 21
        seq = menu_cmd(guest, cmd="join", host="127.0.0.1", password="wrong")
        st = menu_wait(guest, seq, ("error", "ready"))
        assert st["state"] == "error" and st["err"] == 21, st
        assert not (guest.mp / "game-7-autosave.sav").exists()
        # right password: joined, world downloaded and verified, control.json says join
        seq = menu_cmd(guest, cmd="join", host="127.0.0.1", password="tops3cret")
        st = menu_wait(guest, seq, ("error", "ready"))
        assert st["state"] == "ready" and st["session"] == "join" and st["err"] == 0, st
        assert (guest.mp / "game-7-autosave.sav").read_bytes() == b"THE HOSTS WORLD " * 300
        ctl = json.loads((guest.mod / "control.json").read_text())
        assert ctl["enabled"] is True and ctl["mode"] == "join" and 1 <= ctl["id"] <= 7, ctl
        assert ctl["bridge"] == str(guest.mod / f"bridge_{ctl['id']}")
        assert wait_for(lambda: json.loads((Path(ctl["bridge"]) / "status.json").read_text())["auth"] == 2), "guest helper not authenticated"
        assert wait_for(lambda: json.loads((host.mod / "bridge_0" / "status.json").read_text())["mask"] != 0, 15), "host does not see the guest"
        # leaving: stop closes the guest's session
        seq = menu_cmd(guest, cmd="stop")
        st = menu_wait(guest, seq, ("idle",))
        assert st["session"] == "none" and json.loads((guest.mod / "control.json").read_text())["enabled"] is False
        print("menu join: scan finds the host (password flag), a missing or wrong password is refused before any download, "
              "the right one joins and downloads the world; stop leaves")
    finally:
        pair.close()


def test_menu_join_failures():
    pair = MenuPair(world=False).start()
    host, guest = pair.host, pair.guest
    try:
        # a host without a saved world: the handshake works, the world is missing -> 42 and the session is stopped again
        seq = menu_cmd(host, cmd="host")
        menu_wait(host, seq, ("hosting",))
        seq = menu_cmd(guest, cmd="join", host="127.0.0.1")
        st = menu_wait(guest, seq, ("error", "ready"))
        assert st["state"] == "error" and st["err"] == 42 and st["session"] == "none", st
        assert json.loads((guest.mod / "control.json").read_text())["enabled"] is False
        # nobody at the address: 4 after the handshake timeout (about 12 s)
        seq = menu_cmd(guest, cmd="join", host="127.0.0.2", port="47999")
        t0 = time.time()
        st = menu_wait(guest, seq, ("error", "ready"), 40)
        assert st["state"] == "error" and st["err"] == 4 and 10 <= time.time() - t0 < 30, (st, time.time() - t0)
        print("menu join failures: no saved world -> 42, nobody there -> 4 after the timeout, sessions stopped again")
    finally:
        pair.close()


def test_menu_command_validation():
    sb = Sandbox()
    try:
        proc = start_menu_game(sb)

        def refused(label, **fields):
            seq = menu_cmd(sb, **fields)
            st = menu_wait(sb, seq, ("error", "hosting", "joining", "ready", "idle"), 20)
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
        refused("port text", cmd="host", port="77x7")
        # an unknown command only moves the sequence number; the same seq twice is answered once; seq 0 and junk are ignored
        seq = menu_cmd(sb, cmd="explode")
        menu_wait(sb, seq, ("error", "idle"))
        (sb.mod / "menu" / "cmd.txt").write_text(f"seq={seq}\ncmd=host\n")           # a repeated sequence number
        time.sleep(1.5)
        st = menu_status(sb)
        assert st["session"] == "none" and not (sb.mod / "menu" / "cmd.txt").exists(), st
        for junk in (b"", b"seq=0\ncmd=host\n", b"cmd=host\n", b"seq=abc\ncmd=host\n", b"\xff\xfe" * 300, b"seq=99999999999\ncmd=host\n"):
            (sb.mod / "menu" / "cmd.txt").write_bytes(junk)
            time.sleep(0.7)
            assert menu_status(sb)["session"] == "none", junk[:20]
            assert not (sb.mod / "menu" / "cmd.txt").exists() or not junk
        # the launcher is still alive and answers a proper command
        seq = menu_cmd(sb, cmd="scan")
        menu_wait(sb, seq, ("idle", "hosting"))
        assert finish(proc) == 7
        print("menu commands: invalid addresses, ports, rooms, passwords and injected lines are refused without side effects; "
              "unknown commands, repeated sequence numbers and junk files are harmless")
    finally:
        sb.cleanup()


def test_menu_helper_missing():
    sb = Sandbox()
    try:
        (sb.bin / HELPER_NAME).unlink()
        proc = start_menu_game(sb)
        st = menu_status(sb)
        assert st["helper"] == 0 and st["state"] == "error" and st["err"] == 1, st
        seq = menu_cmd(sb, cmd="host")
        st = menu_wait(sb, seq, ("error",))
        assert st["err"] == 1 and st["session"] == "none" and not port_open_tcp(7775), st
        # a helper that exits at once: reported, nothing left listening
        stub = sb.bin / HELPER_NAME
        stub.write_text("#!/bin/sh\nexit 3\n")
        stub.chmod(0o755)
        seq = menu_cmd(sb, cmd="host")
        st = menu_wait(sb, seq, ("error",))
        assert st["state"] == "error" and st["session"] == "none" and not port_open_tcp(7775), st
        assert finish(proc) == 7 and sb.ran() is not None, "the game must run whatever happens to the helper"
        print("menu helper missing: reported to the menu (err 1), nothing listens, the game still runs")
    finally:
        sb.cleanup()


def test_menu_overrides_launcher_cfg():
    """An optional launcher.cfg still starts its role by itself (older setups); the menu can replace or end it."""
    sb = Sandbox()
    try:
        sb.config("mode=host\r\nport=47811\r\nroom=a1b2c3d4\r\n")
        proc = start_menu_game(sb)
        st = menu_status(sb)
        assert st["state"] == "hosting" and st["session"] == "host" and st["port"] == 47811, st
        assert json.loads((sb.mod / "control.json").read_text())["mode"] == "host"
        reply = None
        for _ in range(10):
            reply = query_host(0.5)
            if reply:
                break
        assert reply and reply[5] == 1, "the configured room code is announced"
        seq = menu_cmd(sb, cmd="stop")
        menu_wait(sb, seq, ("idle",))
        assert not port_open_tcp(7775) and query_host(0.7) is None
        seq = menu_cmd(sb, cmd="host")                  # menu hosting ignores launcher.cfg: default port and room
        st = menu_wait(sb, seq, ("hosting",))
        assert st["port"] == 7777, st
        for _ in range(10):
            reply = query_host(0.5)
            if reply:
                break
        assert reply and reply[5] == 0 and int.from_bytes(reply[6:8], "little") == 7777
        finish(proc)
        print("menu vs launcher.cfg: a saved role still starts by itself; the menu can stop it and host with the defaults")
    finally:
        sb.cleanup()


ALL = [test_host, test_time_stamps, test_helper_args, test_join_and_identity_reuse, test_fallbacks, test_direct_and_wrong_exe, test_backup_prune,
       test_configure, test_fuzz, test_discovery_responder, test_scan, test_scan_tailscale, test_world_server,
       test_world_round_trip, test_guest_refreshes_world, test_helper_dies_with_launcher, test_steam_probe_and_identity,
       test_data_dir_discovery_and_proton, test_exit_codes_and_signals,
       test_manager_host_and_steam_setup, test_manager_join, test_manager_join_interactive, test_manager_save_solo,
       test_password, test_manager_password,
       test_menu_standby, test_menu_host_and_stop, test_menu_helper_arguments, test_menu_scan_and_join, test_menu_join_failures,
       test_menu_command_validation, test_menu_helper_missing, test_menu_overrides_launcher_cfg]
only = [n for n in os.environ.get("ONLY", "").split(",") if n]       # ONLY=test_host,test_fuzz runs just those
for fn in ALL:
    if not only or fn.__name__ in only:
        fn()
print("PASS")
