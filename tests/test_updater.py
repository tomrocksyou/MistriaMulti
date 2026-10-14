"""Runs the assembly updater (under Wine on Linux) against a local HTTP server.

  python3 tests/test_updater.py build/MistriMultiUpdater.exe

Covers: update check, verified download + install, checksum mismatch rejection, Save Solo backup.
Needs wine64 and xvfb-run on Linux. On Windows it runs the exe directly.
"""
import hashlib
import http.server
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

exe = Path(sys.argv[1]).resolve()
on_windows = os.name == "nt"
WINE = "/usr/lib/wine/wine64"


def wpath(p):
    return str(p) if on_windows else "Z:" + str(p).replace("/", "\\")


def run(args, env):
    cmd = [str(exe)] if on_windows else ["xvfb-run", "-a", WINE, str(exe)]
    full_env = dict(os.environ, WINEDEBUG="-all", WINEPREFIX=os.environ.get("WINEPREFIX", "/tmp/wp"), **env)
    subprocess.run(cmd + args, env=full_env, timeout=90, check=True, capture_output=True)


def status(path):
    return Path(path).read_bytes().decode("utf-16-le")


def make_server(root):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    tmp = Path(tempfile.mkdtemp(prefix="updtest-"))
    try:
        site = tmp / "site"
        files = {
            "mod/mistrimulti/manifest.toml": b'name = "MistriMulti"\nversion = "0.2.0"\n',
            "mod/mistrimulti/gml/A.gml": b"function a() { return 1; }\n" * 40,
            "mod/mistrimulti/gml/B.gml": b"function b() { return 2; }\n",
        }
        for rel, data in files.items():
            (site / "p" / rel).parent.mkdir(parents=True, exist_ok=True)
            (site / "p" / rel).write_bytes(data)
        lines = ["version 0.2.0"] + [f"{hashlib.sha256(d).hexdigest()} {rel}" for rel, d in files.items()]
        (site / "p" / "release").mkdir(parents=True, exist_ok=True)
        (site / "p" / "release" / "latest.txt").write_text("\n".join(lines) + "\n")
        server = make_server(site)
        port = server.server_address[1]

        game = tmp / "game"
        (game / "mods" / "mistrimulti").mkdir(parents=True)
        (game / "Maybe.toml").write_text("")
        (game / "mods" / "mistrimulti" / "manifest.toml").write_text('name = "MistriMulti"\nversion = "0.1.0"\n')
        saves = tmp / "saves"
        saves.mkdir()
        (saves / "game-1-autosave.sav").write_bytes(b"solo world")
        docs = tmp / "docs"
        docs.mkdir()
        env = {"MISTRIMULTI_SAVES_DIR": wpath(saves), "MISTRIMULTI_DOCS_DIR": wpath(docs)}
        base = [wpath(game), "127.0.0.1", str(port), "0", "/p"]

        out = tmp / "out1.txt"
        run(base + ["c", wpath(out)], env)
        text = status(out)
        assert "0.1.0" in text and "0.2.0" in text and "update is available" in text, text
        print("check: update available detected")

        out = tmp / "out2.txt"
        run(base + ["cu", wpath(out)], env)
        text = status(out)
        assert "Updated to 0.2.0" in text, text
        installed = (game / "mods" / "mistrimulti" / "manifest.toml").read_text()
        assert 'version = "0.2.0"' in installed
        assert (game / "mods" / "mistrimulti" / "gml" / "A.gml").read_bytes() == files["mod/mistrimulti/gml/A.gml"]
        assert not list(game.rglob("*.new")), "staged files left behind"
        print("update: files installed and verified")

        out = tmp / "out3.txt"
        run(base + ["c", wpath(out)], env)
        assert "up to date" in status(out)
        print("check: up to date after update")

        # tamper with one hosted file: nothing may be installed
        (site / "p" / "mod/mistrimulti/gml/B.gml").write_bytes(b"evil")
        (game / "mods" / "mistrimulti" / "manifest.toml").write_text('name = "MistriMulti"\nversion = "0.1.0"\n')
        before = (game / "mods" / "mistrimulti" / "gml" / "A.gml").read_bytes()
        out = tmp / "out4.txt"
        run(base + ["cu", wpath(out)], env)
        assert "checksum" in status(out), status(out)
        assert 'version = "0.1.0"' in (game / "mods" / "mistrimulti" / "manifest.toml").read_text()
        assert not list(game.rglob("*.new")), "staged files left behind after failure"
        print("update: bad checksum rejected, nothing changed")

        out = tmp / "out5.txt"
        run(base + ["s", wpath(out)], env)
        assert "Saved 1 file" in status(out), status(out)
        backups = list((docs / "MistriMulti Backups").iterdir())
        assert len(backups) == 1 and (backups[0] / "game-1-autosave.sav").read_bytes() == b"solo world"
        print("save solo: backup written to Documents")
        server.shutdown()
        print("PASS")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


main()
