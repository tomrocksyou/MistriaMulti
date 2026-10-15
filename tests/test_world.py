"""Tests the world-transfer download client (MistriMulti.exe --fetch, under Wine unless run on Windows) against a fake host.
Twin of tests/test_world_linux.py; the same cases, the same expected results (tests/worldclient_cases.py).

  python3 tests/test_world.py build/MistriMulti.exe
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worldclient_cases

exe = Path(sys.argv[1]).resolve()
on_windows = os.name == "nt"
WINE = "/usr/lib/wine/wine64"


def wpath(p):
    return str(p) if on_windows else "Z:" + str(p).replace("/", "\\")


def command(dest, result, bridge, slot):
    prefix = os.environ.get("WINEPREFIX", "/tmp/wp")
    if not on_windows:
        os.makedirs(prefix, exist_ok=True)   # Wine will not create a prefix directly in a /tmp it does not own
    env = dict(os.environ, WINEDEBUG="-all", WINEPREFIX=prefix)
    argv = ([str(exe)] if on_windows else ["xvfb-run", "-a", WINE, str(exe)]) + [
        "--fetch", "127.0.0.1", wpath(dest), wpath(result), wpath(bridge), str(slot)]
    return argv, env


names = (b"../evil.sav", b"game-1-x.sav", b"game-1-autosave.old.sav", b"C:\\evil.sav", b"game-1-autosave.sav\\x", b"evil.sav",
         b"game--autosave.sav")
worldclient_cases.run(command, names, False)
