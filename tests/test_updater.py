"""Runs the assembly manager/updater (under Wine on Linux) against a local HTTP server.

  python3 tests/test_updater.py build/MistriMulti.exe [build/fakegame.exe]

Covers: update check, verified download + install of the mod AND of the tool programs (launcher, helper, probe, the
manager itself), self-update with the running exe, rollback when a replacement fails, version comparison (a newer
installed version is not an update), hostile lists and downloads, the production URLs, "Open MOMI", Save Solo.
Needs wine64 and xvfb-run on Linux. On Windows it runs the exe directly. The exe under test is always run from a COPY
in a temporary folder, because the manager installs tools next to itself.
"""
import hashlib
import http.server
import os
from pathlib import Path
import getpass
import shutil
import subprocess
import sys
import tempfile
import threading
import time

exe = Path(sys.argv[1]).resolve()
fake = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else exe.parent / "fakegame.exe"
on_windows = os.name == "nt"
WINE = "/usr/lib/wine/wine64"
PREFIX = os.environ.get("WINEPREFIX", "/tmp/wp")
# Wine refuses to create a prefix directly in a /tmp it does not own (GitHub runners): create the folder first.
if not on_windows:
    os.makedirs(PREFIX, exist_ok=True)
EXE_BYTES = exe.read_bytes()
TOOLS = ["MistriMulti.exe", "MistriMultiLauncher.exe", "mistrimulti-helper.exe", "mistrimulti-steam-id.exe"]


def wpath(p):
    return str(p) if on_windows else "Z:" + str(p).replace("/", "\\")


def run_checked(cmd, **kw):
    """subprocess.run that shows the program's own output when it fails (a bare exit status says nothing on CI)."""
    res = subprocess.run(cmd, capture_output=True, **kw)
    if res.returncode != 0:
        raise AssertionError(f"{cmd} exited with {res.returncode}\nstdout: {res.stdout.decode(errors='replace')[-2000:]}"
                             f"\nstderr: {res.stderr.decode(errors='replace')[-2000:]}")
    return res


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Env:
    """One sandbox: a web site, a game folder, a folder holding the manager and the tools."""

    def __init__(self, installed="0.1.0"):
        self.tmp = Path(tempfile.mkdtemp(prefix="updtest-"))
        self.site = self.tmp / "site"
        self.game = self.tmp / "game"
        self.tools = self.tmp / "tools"
        self.saves = self.tmp / "saves"
        self.docs = self.tmp / "docs"
        for d in (self.game / "mods" / "mistrimulti", self.tools, self.saves, self.docs, self.site / "p" / "release"):
            d.mkdir(parents=True)
        (self.game / "Maybe.toml").write_text("")
        if installed:
            self.set_installed(installed)
        self.exe = self.tools / "MistriMulti.exe"
        shutil.copy(exe, self.exe)
        self.requests = []
        self.specials = {}
        env = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=str(env.site), **k)

            def log_message(self, *a):
                pass

            def do_GET(self):
                env.requests.append(self.path)
                special = env.specials.get(self.path)
                if special is None:
                    return super().do_GET()
                kind = special[0]
                if kind == "status":
                    self.send_error(special[1])
                elif kind == "big":
                    self.send_response(200)
                    self.send_header("Content-Length", str(special[1]))
                    self.end_headers()
                    try:
                        self.wfile.write(b"A" * special[1])
                    except OSError:
                        pass
                elif kind == "trunc":       # promises `declared` bytes, sends fewer, closes
                    self.send_response(200)
                    self.send_header("Content-Length", str(special[1]))
                    self.end_headers()
                    self.wfile.write(special[2])
                    self.wfile.flush()
                    self.close_connection = True

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]
        self.mod = {
            "mod/mistrimulti/manifest.toml": b'name = "MistriaMulti"\nversion = "0.2.0"\n',
            "mod/mistrimulti/gml/A.gml": b"function a() { return 1; }\n" * 40,
            "mod/mistrimulti/gml/B.gml": b"function b() { return 2; }\n",
        }
        self.bins = {}

    def set_installed(self, version):
        (self.game / "mods" / "mistrimulti" / "manifest.toml").write_text(f'name = "MistriaMulti"\nversion = "{version}"\n')

    def publish(self, version="0.2.0", mod=None, bins=None, footer=True, extra=(), raw=None):
        """Writes the site files and latest.txt. `raw` replaces the whole list text."""
        mod = self.mod if mod is None else mod
        bins = self.bins if bins is None else bins
        lines = [f"version {version}"]
        for rel, data in mod.items():
            self.put(rel, data)
            lines.append(f"{sha(data)} {rel}")
        for name, data in bins.items():
            self.put("bin/" + name, data)
            lines.append(f"{sha(data)} bin/{name}")
        lines += list(extra)
        if footer:
            lines.append(f"end {len(mod) + len(bins)}")
        text = raw if raw is not None else "\n".join(lines) + "\n"
        (self.site / "p" / "release" / "latest.txt").write_bytes(text.encode() if isinstance(text, str) else text)

    def put(self, rel, data):
        path = self.site / "p" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def run(self, steps, extra_env=None, exe_path=None):
        out = self.tmp / f"out{len(list(self.tmp.glob('out*.txt')))}.txt"
        args = [wpath(self.game), "127.0.0.1", str(self.port), "0", "/p", steps, wpath(out)]
        target = exe_path or self.exe
        cmd = [str(target)] if on_windows else ["xvfb-run", "-a", WINE, str(target)]
        env = dict(os.environ, WINEDEBUG="-all", WINEPREFIX=PREFIX,
                   MISTRIMULTI_SAVES_DIR=wpath(self.saves), MISTRIMULTI_DOCS_DIR=wpath(self.docs), **(extra_env or {}))
        run_checked(cmd + args, env=env, timeout=90)
        return out.read_bytes().decode("utf-16-le")

    def snapshot(self):
        files = {}
        for root in (self.game, self.tools):
            for p in sorted(root.rglob("*")):
                files[str(p.relative_to(self.tmp))] = p.read_bytes() if p.is_file() else None
        return files

    def leftovers(self):
        return [str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*") if p.suffix in (".new",)]

    def close(self):
        self.server.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)


def installed_version(env):
    return (env.game / "mods" / "mistrimulti" / "manifest.toml").read_text()


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name}: {detail}")
    print("ok:", name)


def test_basic_flow():
    e = Env()
    try:
        e.publish()
        text = e.run("c")
        check("check: update available", "0.1.0" in text and "0.2.0" in text and "update is available" in text, text)
        text = e.run("cu")
        check("update: mod installed", "Updated to 0.2.0" in text and "Install" in text, text)
        check("update: files verified", 'version = "0.2.0"' in installed_version(e)
              and (e.game / "mods/mistrimulti/gml/A.gml").read_bytes() == e.mod["mod/mistrimulti/gml/A.gml"])
        check("update: no staged files", not e.leftovers(), e.leftovers())
        text = e.run("c")
        check("check: up to date after update", "up to date" in text, text)
        text = e.run("cu")
        check("update: nothing to do when current", "already up to date" in text, text)

        # tamper with one hosted file: nothing may be installed
        e.put("mod/mistrimulti/gml/B.gml", b"evil")
        (e.game / "mods/mistrimulti/gml/B.gml").write_bytes(b"old B")
        e.set_installed("0.1.0")
        before = e.snapshot()
        text = e.run("cu")
        check("update: bad checksum rejected", "checksum" in text, text)
        check("update: nothing changed after bad checksum", e.snapshot() == before and not e.leftovers())

        (e.saves / "game-1-autosave.sav").write_bytes(b"solo world")
        out = e.run("s")
        backups = list((e.docs / "MistriMulti Backups").iterdir())
        check("save solo: backup written to Documents", "Saved 1 file" in out and len(backups) == 1
              and (backups[0] / "game-1-autosave.sav").read_bytes() == b"solo world", out)
    finally:
        e.close()


def test_not_installed():
    e = Env(installed=None)
    try:
        e.publish()
        text = e.run("c")
        check("check: not installed", "Not installed yet" in text, text)
        text = e.run("cu")
        check("update: fresh install", "Updated to 0.2.0" in text and (e.game / "mods/mistrimulti/gml/B.gml").exists(), text)
    finally:
        e.close()


def test_versions():
    cases = [("0.9.0", "0.10.0", "update is available"), ("0.10.0", "0.9.0", "newer"), ("0.2", "0.2.0", "up to date"),
             ("1.0.0", "0.2.0", "newer"), ("0.2.1", "0.2.0", "newer"), ("0.1.0-dev", "0.2.0", "update is available"),
             ("0.2.0", "0.2.0.0", "up to date"), ("0.2.0", "0.2.0.1", "update is available")]
    for installed, published, expect in cases:
        e = Env(installed=installed)
        try:
            e.publish(version=published, mod={**e.mod, "mod/mistrimulti/manifest.toml": f'version = "{published}"\n'.encode()})
            text = e.run("c")
            check(f"version: installed {installed} vs published {published} -> {expect}", expect in text, text)
            if expect == "newer":
                before = e.snapshot()
                text = e.run("cu")
                check(f"version: newer installed {installed} is never replaced", e.snapshot() == before and "newer" in text, text)
        finally:
            e.close()


def tools_env(installed="0.2.0"):
    e = Env(installed=installed)
    # an installed copy of the current mod (so only the tools differ)
    for rel, data in e.mod.items():
        p = e.game / rel.replace("mod/", "mods/", 1)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    e.set_installed(installed)
    e.bins = {
        "MistriMulti.exe": EXE_BYTES + b"\0" * 2048,        # a valid, different build of the manager
        "MistriMultiLauncher.exe": b"MZ new launcher " * 100,
        "mistrimulti-helper.exe": b"MZ new helper " * 100,
        "mistrimulti-steam-id.exe": b"MZ new probe " * 100,
    }
    (e.tools / "MistriMultiLauncher.exe").write_bytes(b"MZ old launcher")
    (e.tools / "readme.txt").write_bytes(b"not ours")
    return e


def test_tools_and_self_update():
    e = tools_env()
    try:
        e.publish()
        text = e.run("c")
        check("tools: stale tools reported with an equal mod version", "newer version" in text and "update available" in text, text)
        text = e.run("cu")
        check("tools: update message", "Updated to 0.2.0" in text and "programs 4" in text and "MistriMulti.exe itself" in text, text)
        check("tools: no MOMI step when the mod did not change", "Open MOMI" not in text, text)
        for name, data in e.bins.items():
            check(f"tools: {name} installed and verified", (e.tools / name).read_bytes() == data)
        check("tools: unrelated files untouched", (e.tools / "readme.txt").read_bytes() == b"not ours")
        check("tools: previous launcher not left behind", not (e.tools / "MistriMultiLauncher.exe.old").exists())
        check("tools: nothing staged", not e.leftovers(), e.leftovers())
        check("self-update: running exe kept as .old", (e.tools / "MistriMulti.exe.old").read_bytes() == EXE_BYTES)
        text = e.run("c")          # the old process is gone; this is the NEW exe
        check("self-update: new exe runs and sees everything current", "up to date" in text and "Tools:           up to date" in text, text)
        check("self-update: .old removed at next start", not (e.tools / "MistriMulti.exe.old").exists())
        # a second update changes nothing
        before = e.snapshot()
        text = e.run("cu")
        check("tools: second update is a no-op", "already up to date" in text and e.snapshot() == before, text)
        # one tool changes upstream; only that one is downloaded
        e.bins["mistrimulti-helper.exe"] = b"MZ newer helper " * 100
        e.publish()
        e.requests.clear()
        text = e.run("cu")
        downloaded = sorted(r for r in e.requests if r != "/p/release/latest.txt")
        check("tools: only the changed tool is downloaded", downloaded == ["/p/bin/mistrimulti-helper.exe"], downloaded)
        check("tools: changed tool installed", (e.tools / "mistrimulti-helper.exe").read_bytes() == e.bins["mistrimulti-helper.exe"], text)
    finally:
        e.close()


def test_mod_and_tools_together():
    e = tools_env(installed="0.1.0")
    try:
        e.mod["mod/mistrimulti/gml/A.gml"] = b"function a() { return 3; }\n"
        e.publish()
        text = e.run("cu")
        check("mixed: mod and tools updated", "Updated to 0.2.0" in text and "Open MOMI" in text and "mod 2" in text
              and 'version = "0.2.0"' in installed_version(e), text)
    finally:
        e.close()


def test_startup_cleanup():
    e = tools_env()
    try:
        e.publish()
        for n in ("MistriMulti.exe.old", "MistriMulti.exe.new", "mistrimulti-helper.exe.new", "MistriMultiLauncher.exe.old", "other.exe.old"):
            (e.tools / n).write_bytes(b"leftover")
        e.run("c")
        left = sorted(p.name for p in e.tools.iterdir())
        check("cleanup: leftovers of our tools removed, foreign files kept", left == ["MistriMulti.exe", "MistriMultiLauncher.exe", "other.exe.old", "readme.txt"], left)
    finally:
        e.close()


def test_failure_paths():
    # --- stage failure: the .new path is blocked (a folder) -> nothing changes
    e = tools_env()
    try:
        e.publish()
        (e.tools / "mistrimulti-helper.exe.new").mkdir()
        before = e.snapshot()
        text = e.run("cu")
        check("failure: stage failure reported", "Nothing was changed" in text, text)
        check("failure: stage failure leaves everything as it was", e.snapshot() == before)
    finally:
        e.close()
    # --- swap failure after the manager itself and the launcher were replaced: everything is put back
    e = tools_env()
    try:
        e.publish()
        (e.tools / "mistrimulti-helper.exe").write_bytes(b"MZ old helper")
        blocker = e.tools / "mistrimulti-helper.exe.old"
        (blocker / "keep").mkdir(parents=True)
        (blocker / "keep" / "x").write_bytes(b"x")
        before = e.snapshot()
        text = e.run("cu")
        check("rollback: reported", "put back" in text, text)
        check("rollback: every file is as before (manager, launcher, helper)", e.snapshot() == before, "\n".join(
            k for k in set(e.snapshot()) | set(before) if e.snapshot().get(k) != before.get(k)))
        text = e.run("c")
        check("rollback: the manager still works afterwards", "update available" in text or "newer version" in text, text)
    finally:
        e.close()
    # --- swap failure on a mod file: manifest.toml (installed last) must still show the old version
    e = tools_env(installed="0.1.0")
    try:
        e.mod["mod/mistrimulti/gml/A.gml"] = b"function a() { return 3; }\n"
        e.mod["mod/mistrimulti/gml/B.gml"] = b"function b() { return 4; }\n"
        e.publish()
        (e.game / "mods/mistrimulti/gml/B.gml").write_bytes(b"old b")
        (e.game / "mods/mistrimulti/gml/B.gml.old" / "keep").mkdir(parents=True)
        (e.game / "mods/mistrimulti/gml/B.gml.old" / "keep" / "x").write_bytes(b"x")
        before = e.snapshot()
        text = e.run("cu")
        check("rollback: mod failure reported", "put back" in text, text)
        check("rollback: mod files and version unchanged", e.snapshot() == before and 'version = "0.1.0"' in installed_version(e))
    finally:
        e.close()


def test_hostile_downloads():
    cases = {}
    e = tools_env()
    try:
        good = dict(e.bins)
        (e.game / "mods/mistrimulti/gml/A.gml").write_bytes(b"old A")      # the mod file differs, so it is downloaded too
        e.publish()
        base = e.snapshot()

        def attempt(label, tweak, expect):
            e.specials.clear()
            e.publish(bins=good)
            tweak()
            e.requests.clear()
            text = e.run("cu")
            check(f"download: {label}", expect in text and e.snapshot() == base and not e.leftovers(), text)

        attempt("wrong content for a tool", lambda: e.put("bin/mistrimulti-helper.exe", b"evil"), "checksum")
        attempt("wrong content for the manager itself", lambda: e.put("bin/MistriMulti.exe", EXE_BYTES + b"1"), "checksum")
        attempt("wrong content for a mod file (after tools were staged)", lambda: e.put("mod/mistrimulti/gml/A.gml", b"evil"), "checksum")
        # a file whose hash is right but that is served truncated
        data = good["MistriMultiLauncher.exe"]
        attempt("truncated download", lambda: e.specials.update({"/p/bin/MistriMultiLauncher.exe": ("trunc", len(data), data[: len(data) // 2])}), "Nothing was changed")
        attempt("huge download (2 MB)", lambda: e.specials.update({"/p/bin/mistrimulti-steam-id.exe": ("big", 2 * 1024 * 1024)}), "Nothing was changed")
        attempt("huge download of exactly the limit + 1", lambda: e.specials.update({"/p/bin/mistrimulti-steam-id.exe": ("big", 1048577)}), "Nothing was changed")
        attempt("missing file (404)", lambda: e.specials.update({"/p/bin/mistrimulti-helper.exe": ("status", 404)}), "Nothing was changed")
        # empty file whose hash is that of an empty file would be legal; an empty body for another hash is not
        attempt("empty body", lambda: e.put("bin/mistrimulti-helper.exe", b""), "checksum")
    finally:
        e.close()


def hostile_list_cases():
    h = "a" * 64
    mf = f"{'b' * 64} mod/mistrimulti/manifest.toml"
    # each entry: a complete list text that must be rejected as a whole
    def lst(*lines, version="0.2.0", footer=True, with_manifest=True):
        body = ([f"version {version}"] if version is not None else []) + ([mf] if with_manifest else []) + list(lines)
        n = len(lines) + (1 if with_manifest else 0)
        return "\n".join(body + ([f"end {n}"] if footer else [])) + "\n"
    cases = {
        "parent folder in a mod path": lst(f"{h} mod/mistrimulti/../../evil.txt"),
        "parent folder at the end": lst(f"{h} mod/mistrimulti/gml/.."),
        "parent folder in a tool path": lst(f"{h} bin/../MistriMulti.exe"),
        "tool in a subfolder": lst(f"{h} bin/sub/MistriMulti.exe"),
        "unknown tool name": lst(f"{h} bin/evil.exe"),
        "tool name in another case": lst(f"{h} bin/mistrimulti.exe"),
        "tool name with a trailing dot": lst(f"{h} bin/MistriMulti.exe."),
        "tool name plus stream": lst(f"{h} bin/MistriMulti.exe:evil"),
        "backslashes": lst(f"{h} mod\\mistrimulti\\gml\\A.gml"),
        "backslash inside": lst(f"{h} mod/mistrimulti/gml\\A.gml"),
        "absolute unix path": lst(f"{h} /etc/passwd"),
        "absolute windows path": lst(f"{h} C:\\Windows\\win.ini"),
        "drive letter in a mod path": lst(f"{h} mod/mistrimulti/C:/evil.gml"),
        "drive-relative name": lst(f"{h} mod/mistrimulti/gml/C:evil"),
        "alternate data stream": lst(f"{h} mod/mistrimulti/gml/A.gml:stream"),
        "another root": lst(f"{h} evil/x.txt"),
        "another mod folder": lst(f"{h} mod/othermod/x.gml"),
        "mod root itself": lst(f"{h} mod/mistrimulti"),
        "mod root with slash": lst(f"{h} mod/mistrimulti/"),
        "prefix look-alike": lst(f"{h} mod/mistrimulti2/x.gml"),
        "hidden file": lst(f"{h} mod/mistrimulti/.hidden"),
        "hidden folder": lst(f"{h} mod/mistrimulti/.git/config"),
        "name ending with a dot": lst(f"{h} mod/mistrimulti/gml/A."),
        "empty component": lst(f"{h} mod/mistrimulti//A.gml"),
        "device name CON": lst(f"{h} mod/mistrimulti/gml/con.gml"),
        "device name NUL upper case": lst(f"{h} mod/mistrimulti/NUL"),
        "device name COM1": lst(f"{h} mod/mistrimulti/com1.txt"),
        "device name LPT9 in a folder": lst(f"{h} mod/mistrimulti/LPT9/x.gml"),
        "space in a name": lst(f"{h} mod/mistrimulti/gml/A B.gml"),
        "short (8.3) name": lst(f"{h} mod/mistrimulti/PROGRA~1/x.gml"),
        "non-ASCII name": lst(f"{h} mod/mistrimulti/gml/\u00e4.gml"),
        "percent encoding": lst(f"{h} mod/mistrimulti/gml/%2e%2e/x"),
        "query string": lst(f"{h} mod/mistrimulti/gml/A.gml?x=1"),
        "path too long": lst(f"{h} mod/mistrimulti/" + "a" * 200),
        "upper case hash": lst(f"{'A' * 64} mod/mistrimulti/gml/A.gml"),
        "non-hex hash": lst(f"{'g' * 64} mod/mistrimulti/gml/A.gml"),
        "short hash": lst(f"{'a' * 63} mod/mistrimulti/gml/A.gml"),
        "long hash": lst(f"{'a' * 65} mod/mistrimulti/gml/A.gml"),
        "two spaces": lst(f"{h}  mod/mistrimulti/gml/A.gml"),
        "duplicate file": lst(f"{h} mod/mistrimulti/gml/A.gml", f"{h} mod/mistrimulti/gml/A.gml"),
        "unknown line": lst("hello world"),
        "no footer (cut at a line)": lst(f"{h} mod/mistrimulti/gml/A.gml", footer=False),
        "footer count too small": lst(f"{h} mod/mistrimulti/gml/A.gml").replace("end 2", "end 1"),
        "footer count too large": lst(f"{h} mod/mistrimulti/gml/A.gml").replace("end 2", "end 3"),
        "footer not a number": lst(f"{h} mod/mistrimulti/gml/A.gml").replace("end 2", "end two"),
        "content after the footer": lst(f"{h} mod/mistrimulti/gml/A.gml") + f"{h} mod/mistrimulti/gml/B.gml\n",
        "cut in the middle of a line": lst(f"{h} mod/mistrimulti/gml/A.gml")[:-12],
        "cut in the middle of the footer": lst(f"{h} mod/mistrimulti/gml/A.gml").replace("end 2\n", "en"),
        "empty list": "",
        "only a version": "version 0.2.0\n",
        "no manifest.toml entry": lst(f"{h} mod/mistrimulti/gml/A.gml", with_manifest=False),
        "no version line": lst(version=None),
        "version not first": "\n".join([mf, "version 0.2.0", "end 1"]) + "\n",
        "version with letters": lst(version="0.2.0-beta"),
        "version with a v": lst(version="v0.2.0"),
        "version with five groups": lst(version="1.2.3.4.5"),
        "version with an empty group": lst(version="1..2"),
        "version with a huge number": lst(version="1.99999999"),
        "version with a path in it": lst(version="0.2.0/../x"),
        "no newline at the end": lst().rstrip("\n"),
        "junk": "\x00\x01\x02" * 50 + "\n",
        "too many files": "\n".join(["version 0.2.0", mf] + [f"{h} mod/mistrimulti/gml/F{i}.gml" for i in range(250)] + ["end 251"]) + "\n",
    }
    return cases


def test_hostile_lists():
    e = tools_env()
    try:
        before = e.snapshot()
        for label, text in hostile_list_cases().items():
            e.publish(raw=text)
            e.requests.clear()
            out = e.run("c")
            check(f"list: {label} is rejected", "not valid" in out, out)
            if e.snapshot() != before or e.leftovers() or e.requests != ["/p/release/latest.txt"]:
                raise AssertionError(f"list: {label}: changed something or downloaded files: {e.requests}")
        # a list far bigger than the limit is not read at all
        e.publish(raw="version 0.2.0\n" + "#" + "x" * 40000 + "\nend 0\n")
        out = e.run("c")
        check("list: oversized list rejected", "not valid" in out, out)
        # a good list with comments, blank lines and CRLF is accepted
        e.bins = {}
        e.publish(raw="# comment\r\n\r\nversion 0.2.0\r\n" + "".join(f"{sha(d)} {r}\r\n" for r, d in e.mod.items()) + "end 3\r\n")
        for rel, data in e.mod.items():
            e.put(rel, data)
        out = e.run("c")
        check("list: comments, blank lines and CRLF are accepted", "not valid" not in out, out)
    finally:
        e.close()


def test_production_urls():
    e = Env()
    try:
        out = e.tmp / "urls.txt"
        cmd = [str(e.exe)] if on_windows else ["xvfb-run", "-a", WINE, str(e.exe)]
        run_checked(cmd + ["--urls", "0.2.0", wpath(out)], env=dict(os.environ, WINEDEBUG="-all", WINEPREFIX=PREFIX),
                    timeout=90)
        lines = out.read_bytes().decode("utf-16-le").split("\r\n")[:3]
        want = ["github.com /tomrocksyou/MistriaMulti/releases/latest/download/latest.txt",
                "raw.githubusercontent.com /tomrocksyou/MistriaMulti/v0.2.0/mod/mistrimulti/gml/A.gml",
                "github.com /tomrocksyou/MistriaMulti/releases/download/v0.2.0/MistriMulti.exe"]
        check("production URLs: list, mod file and tool", lines == want, lines)
    finally:
        e.close()


def local_appdata():
    if on_windows:
        return Path(os.environ["LOCALAPPDATA"])
    return Path(PREFIX) / "drive_c" / "users" / getpass.getuser() / "AppData" / "Local"


def test_momi():
    if not fake.exists():
        print("skip: Open MOMI (build/fakegame.exe not built)")
        return
    cfg_dir = local_appdata() / "FieldsOfMistria" / "mod_data" / "mistrimulti"
    cfg = cfg_dir / "momi.cfg"
    had = cfg.exists() and cfg.read_bytes()
    cfg.unlink(missing_ok=True)
    e = Env()
    try:
        momi = e.tmp / "MOMI folder"
        momi.mkdir()
        shutil.copy(fake, momi / "ModsOfMistriaInstaller.exe")
        shutil.copy(fake, momi / "ModsOfMistriaInstaller-cli.exe")
        text = e.run("m")
        check("momi: not found is explained and nothing is guessed", "MOMI was not found" in text, text)
        text = e.run("m", {"MISTRIMULTI_MOMI_EXE": wpath(momi / "ModsOfMistriaInstaller-cli.exe")})
        time.sleep(1)
        check("momi: the command-line program is refused and not run", "command-line program" in text and not (momi / "ran.txt").exists(), text)
        text = e.run("m", {"MISTRIMULTI_MOMI_EXE": wpath(momi / "ModsOfMistriaInstaller.exe")})
        for _ in range(40):
            if (momi / "ran.txt").exists():
                break
            time.sleep(0.25)
        check("momi: MOMI is opened with instructions", "MOMI was opened" in text and "click Install" in text, text)
        ran = (momi / "ran.txt").read_bytes().decode("utf-16-le") if (momi / "ran.txt").exists() else None
        check("momi: MOMI is started without any arguments", ran is not None and ran.strip().strip('"').endswith("ModsOfMistriaInstaller.exe"), ran)
        # the remembered choice
        (momi / "ran.txt").unlink()
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg.write_bytes(wpath(momi / "ModsOfMistriaInstaller.exe").encode("utf-16-le") + "\r\n".encode("utf-16-le"))
        text = e.run("m")
        for _ in range(40):
            if (momi / "ran.txt").exists():
                break
            time.sleep(0.25)
        check("momi: the saved choice is used", "MOMI was opened" in text and (momi / "ran.txt").exists(), text)
        cfg.write_bytes(wpath(momi / "gone.exe").encode("utf-16-le"))
        text = e.run("m")
        check("momi: a saved path that vanished is treated as not found", "MOMI was not found" in text, text)
    finally:
        e.close()
        cfg.unlink(missing_ok=True)
        if had:
            cfg.write_bytes(had)


def clear_momi_cfg():
    d = local_appdata() / "FieldsOfMistria" / "mod_data" / "mistrimulti"
    saved = {n: (d / n).read_bytes() for n in ("momi.cfg", "momi-cli.cfg") if (d / n).exists()}
    for n in ("momi.cfg", "momi-cli.cfg"):
        (d / n).unlink(missing_ok=True)
    return d, saved


def restore_momi_cfg(d, saved):
    for n in ("momi.cfg", "momi-cli.cfg"):
        (d / n).unlink(missing_ok=True)
    for n, data in saved.items():
        d.mkdir(parents=True, exist_ok=True)
        (d / n).write_bytes(data)


def wait_for(path, seconds=10):
    for _ in range(int(seconds * 4)):
        if path.exists():
            return True
        time.sleep(0.25)
    return False


def test_one_button():
    """'Update MistriMulti': check + update + the MOMI step (command-line installer only with consent)."""
    if not fake.exists():
        print("skip: one button (build/fakegame.exe not built)")
        return
    cfg_dir, saved = clear_momi_cfg()
    e = Env(installed="0.1.0")
    try:
        momi = e.tmp / "MOMI"
        momi.mkdir()
        cli = momi / "ModsOfMistriaInstaller-cli.exe"
        gui = momi / "ModsOfMistriaInstaller.exe"
        for f in (cli, gui, momi / "ModsOfMistriaInstaller-cli-fail.exe", momi / "NotACommandLine.exe"):
            shutil.copy(fake, f)
        ran = e.game / "ran.txt"
        e.publish()
        # 1. nothing chosen: updated, and the plain instruction is shown
        text = e.run("a")
        check("one button: updated without MOMI chosen", "Updated to 0.2.0" in text and "press Open MOMI" in text
              and 'version = "0.2.0"' in installed_version(e) and not ran.exists(), text)
        # 2. already current: nothing to do and MOMI is not run
        text = e.run("a", {"MISTRIMULTI_MOMI_CLI_EXE": wpath(cli), "MISTRIMULTI_MOMI_CONSENT": "yes"})
        check("one button: up to date runs nothing", "up to date" in text and not ran.exists(), text)
        # 3. CLI chosen but no consent: not run, and the instruction says what to do
        e.set_installed("0.1.0")
        text = e.run("a", {"MISTRIMULTI_MOMI_CLI_EXE": wpath(cli)})
        check("one button: no consent, the installer is not run", "was not run" in text and "click Install" in text and not ran.exists(), text)
        check("one button: files were still updated", 'version = "0.2.0"' in installed_version(e))
        # 4. consent given: run in the game folder with EXIT_ON_COMPLETE=true (the fake exits 0 only then), no arguments
        e.set_installed("0.1.0")
        text = e.run("a", {"MISTRIMULTI_MOMI_CLI_EXE": wpath(cli), "MISTRIMULTI_MOMI_CONSENT": "yes"})
        check("one button: consent runs the installer, exit code 0", "installer finished (exit code 0)" in text and ran.exists(), text)
        line = ran.read_bytes().decode("utf-16-le").strip()
        check("one button: started with no arguments", line.strip('"').endswith("ModsOfMistriaInstaller-cli.exe"), line)
        ran.unlink()
        # 5. the installer fails: plain words with the exit code, MOMI window is the fallback text
        e.set_installed("0.1.0")
        text = e.run("a", {"MISTRIMULTI_MOMI_CLI_EXE": wpath(momi / "ModsOfMistriaInstaller-cli-fail.exe"), "MISTRIMULTI_MOMI_CONSENT": "yes"})
        check("one button: failing installer reported with its exit code", "exit code 5" in text and "click Install" in text, text)
        ran.unlink(missing_ok=True)
        # 6. a program without '-cli' in its name is never run as the installer
        e.set_installed("0.1.0")
        text = e.run("a", {"MISTRIMULTI_MOMI_CLI_EXE": wpath(momi / "NotACommandLine.exe"), "MISTRIMULTI_MOMI_CONSENT": "yes"})
        check("one button: a program that is not a -cli build is not run", not ran.exists(), text)
        # 7. CLI declined, MOMI window chosen: the window is opened
        e.set_installed("0.1.0")
        text = e.run("a", {"MISTRIMULTI_MOMI_CLI_EXE": wpath(cli), "MISTRIMULTI_MOMI_EXE": wpath(gui)})
        check("one button: declined CLI falls back to opening MOMI", "MOMI was opened" in text and "Updated to 0.2.0" in text, text)
        wait_for(momi / "ran.txt")
        check("one button: the fallback ran the window program, not the CLI", (momi / "ran.txt").exists() and not ran.exists())
        (momi / "ran.txt").unlink(missing_ok=True)
        # 8. only programs changed: MOMI has nothing to do
        e.bins = {"mistrimulti-helper.exe": b"MZ new helper " * 50}
        e.publish()
        text = e.run("a", {"MISTRIMULTI_MOMI_CLI_EXE": wpath(cli), "MISTRIMULTI_MOMI_CONSENT": "yes"})
        check("one button: program-only update does not run MOMI", "Updated to 0.2.0" in text and not ran.exists(), text)
        # 9. the Open MOMI button never runs a -cli program
        text = e.run("m", {"MISTRIMULTI_MOMI_EXE": wpath(cli)})
        check("one button: Open MOMI never runs the -cli program", not ran.exists() and "command-line" in text, text)
        # 10. the saved -cli choice (momi-cli.cfg) is found
        e.set_installed("0.1.0")
        e.bins = {}
        e.publish()
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "momi-cli.cfg").write_bytes((wpath(cli) + "\r\n").encode("utf-16-le"))
        text = e.run("a", {"MISTRIMULTI_MOMI_CONSENT": "yes"})
        check("one button: the remembered CLI path is used", "installer finished" in text and ran.exists(), text)
        ran.unlink(missing_ok=True)
        # 11. offline: said plainly, nothing run
        e.set_installed("0.1.0")
        e.server.shutdown()
        e.server.server_close()
        text = e.run("a", {"MISTRIMULTI_MOMI_CONSENT": "yes"})
        check("one button: offline is explained", "Could not reach" in text and not ran.exists(), text)
    finally:
        e.close()
        restore_momi_cfg(cfg_dir, saved)


def daily_run(e, moddir, port=None, extra_env=None, secure="0"):
    cmd = [str(e.exe)] if on_windows else ["xvfb-run", "-a", WINE, str(e.exe)]
    args = ["--daily", wpath(moddir), "127.0.0.1", str(port if port is not None else e.port), secure, "/p"]
    start = time.time()
    run_checked(cmd + args, env=dict(os.environ, WINEDEBUG="-all", WINEPREFIX=PREFIX, **(extra_env or {})), timeout=60)
    return time.time() - start


def test_daily_check():
    import json
    e = Env()
    try:
        e.publish(version="0.4.9")
        moddir = e.tmp / "moddata"
        daily_run(e, moddir)
        data = json.loads((moddir / "update.json").read_text())
        check("daily: update.json written", data["v"] == 1 and data["latest"] == "0.4.9" and abs(data["checked"] - time.time()) < 300, data)
        check("daily: no temp file left", not (moddir / "update.json.tmp").exists())
        n = len(e.requests)
        daily_run(e, moddir)
        check("daily: a second start within a day makes no request", len(e.requests) == n, e.requests)
        (moddir / "update.json").write_text(json.dumps({"v": 1, "latest": "0.1.0", "checked": int(time.time()) - 2 * 86400}))
        e.publish(version="0.5.0")
        daily_run(e, moddir)
        check("daily: after a day it checks again", json.loads((moddir / "update.json").read_text())["latest"] == "0.5.0")
        (moddir / "update.json").write_text(json.dumps({"v": 1, "latest": "0.1.0", "checked": int(time.time()) + 5 * 86400}))
        daily_run(e, moddir)
        check("daily: a 'checked' time in the future is ignored", json.loads((moddir / "update.json").read_text())["latest"] == "0.5.0")
        # opt-out
        (moddir / "update.json").unlink()
        (moddir / "update.cfg").write_text("# no checks please\ncheck=off\n")
        n = len(e.requests)
        daily_run(e, moddir)
        check("daily: check=off makes no request and writes nothing", len(e.requests) == n and not (moddir / "update.json").exists())
        (moddir / "update.cfg").write_text("check=on\n")
        daily_run(e, moddir)
        check("daily: any other line keeps the check on", (moddir / "update.json").exists())
        # failures are silent and write nothing
        (moddir / "update.json").unlink()
        for label, tweak in (("404", lambda: e.specials.update({"/p/release/latest.txt": ("status", 404)})),
                             ("invalid list", lambda: e.publish(raw="version 0.5.0\n")),
                             ("truncated", lambda: e.specials.update({"/p/release/latest.txt": ("trunc", 500, b"version 0.5.0\n")}))):
            e.specials.clear()
            e.publish(version="0.5.0")
            tweak()
            daily_run(e, moddir)
            check(f"daily: {label} writes nothing", not (moddir / "update.json").exists())
        # nothing listens: quick and silent
        e.specials.clear()
        e.publish(version="0.5.0")
        took = daily_run(e, moddir, port=1)
        check("daily: a refused connection ends quickly without a file", took < 30 and not (moddir / "update.json").exists(), took)
        # a damaged update.json is replaced
        (moddir / "update.json").write_bytes(b"\x00\x01garbage")
        daily_run(e, moddir)
        check("daily: a damaged file is replaced", json.loads((moddir / "update.json").read_text())["latest"] == "0.5.0")
    finally:
        e.close()


def main():
    for t in (test_basic_flow, test_not_installed, test_versions, test_tools_and_self_update, test_mod_and_tools_together,
              test_startup_cleanup, test_failure_paths, test_hostile_downloads, test_hostile_lists, test_production_urls, test_momi, test_one_button, test_daily_check):
        print(f"--- {t.__name__}")
        t()
    print("PASS")


main()
