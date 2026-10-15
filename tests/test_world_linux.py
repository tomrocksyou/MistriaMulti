"""Tests the Linux world-transfer download client (mistrimulti-manager --fetch) against a fake host.
Native twin of tests/test_world.py (which runs the Windows client under Wine); the same cases, the same expected results
(tests/worldclient_cases.py).

  python3 tests/test_world_linux.py build/mistrimulti-manager
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worldclient_cases

exe = Path(sys.argv[1]).resolve()


def command(dest, result, bridge, slot):
    return [str(exe), "--fetch", "127.0.0.1", str(dest), str(result), str(bridge), str(slot)], None


names = (b"../evil.sav", b"game-1-x.sav", b"game-1-autosave.old.sav", b"C:\\evil.sav", b"game-1-autosave.sav\\x", b"/etc/evil.sav",
         b"game-1-autosave.sav/x", b"evil.sav", b"game--autosave.sav")
worldclient_cases.run(command, names, True)
