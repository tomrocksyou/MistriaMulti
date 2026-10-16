#!/usr/bin/env python3
"""Tests install.sh against a fake HOME with a fake Steam tree. No build tools, no real Steam, no network.

    python3 tests/test_install_linux.py
"""
import hashlib, http.server, io, json, os, re, shutil, subprocess, sys, tarfile, tempfile, threading, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPID = "2142790"
BINS = ["mistrimulti-launcher", "mistrimulti-manager", "mistrimulti-helper-linux", "mistrimulti-steam-id-linux"]

VDF_PLAIN = '''"UserLocalConfigStore"
{
\t"Software"
\t{
\t\t"Valve"
\t\t{
\t\t\t"Steam"
\t\t\t{
\t\t\t\t"apps"
\t\t\t\t{
\t\t\t\t\t"220"
\t\t\t\t\t{
\t\t\t\t\t\t"LaunchOptions"\t\t"-novid"
\t\t\t\t\t}
\t\t\t\t}
\t\t\t}
\t\t}
\t}
\t"friends"
\t{
\t\t"PersonaName"\t\t"Tester"
\t}
}
'''
VDF_NO_OPTION = VDF_PLAIN.replace('"220"', '"%s"' % APPID).replace('\t\t\t\t\t\t"LaunchOptions"\t\t"-novid"\n',
                                                                    '\t\t\t\t\t\t"LastPlayed"\t\t"1700000000"\n')
VDF_OLD_OPTION = VDF_PLAIN.replace('"220"', '"%s"' % APPID).replace("-novid", "gamemoderun %command%")


def make_env(tmp, vdfs=None, manifest=True, library_extra=False):
    """Returns (home, repo). vdfs maps Steam user id -> localconfig.vdf text."""
    home = tmp / "home"
    repo = tmp / "repo"
    home.mkdir()
    shutil.copytree(ROOT / "mod" / "mistrimulti", repo / "mod" / "mistrimulti")
    shutil.copy(ROOT / "install.sh", repo / "install.sh")
    for n in ("LICENSE", "CONTACT.md"):
        shutil.copy(ROOT / n, repo / n)
    (repo / "build").mkdir()
    for b in BINS:
        (repo / "build" / b).write_text("#!/bin/sh\necho %s\n" % b)
    steam = home / ".local/share/Steam"
    (steam / "steamapps/common").mkdir(parents=True)
    (home / ".steam").mkdir()
    (home / ".steam/steam").symlink_to(steam)       # the usual symlink: must not be processed twice
    libs = [steam]
    if library_extra:
        libs.append(tmp / "games")
    vdf = '"libraryfolders"\n{\n' + "".join(
        '\t"%d"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n' % (i, p) for i, p in enumerate(libs)) + "}\n"
    (steam / "steamapps/libraryfolders.vdf").write_text(vdf)
    gamelib = libs[-1]
    if manifest:
        (gamelib / "steamapps/common/Fields of Mistria").mkdir(parents=True, exist_ok=True)
        (gamelib / ("steamapps/appmanifest_%s.acf" % APPID)).write_text(
            '"AppState"\n{\n\t"appid"\t\t"%s"\n\t"name"\t\t"Fields of Mistria"\n\t"installdir"\t\t"Fields of Mistria"\n}\n' % APPID)
    for uid, text in (vdfs or {}).items():
        d = steam / "userdata" / uid / "config"
        d.mkdir(parents=True)
        (d / "localconfig.vdf").write_text(text)
    return home, repo


def run(home, repo, *args, running=False, stdin="", path=None, extra=None):
    env = {"HOME": str(home), "PATH": path or os.environ["PATH"], "MISTRIMULTI_STEAM_RUNNING": "1" if running else "0",
           "TMPDIR": str(home.parent)}
    env.update(extra or {})
    return subprocess.run(["sh", str(repo / "install.sh"), *args], env=env, input=stdin, capture_output=True,
                          text=True, timeout=60, cwd=str(home))


def vdf_path(home, uid):
    return home / ".local/share/Steam/userdata" / uid / "config/localconfig.vdf"


def balanced(text):
    return len(re.findall(r"^\s*\{\s*$", text, re.M)) == len(re.findall(r"^\s*\}\s*$", text, re.M))


class InstallTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.dir = None

    def tearDown(self):
        self._t.cleanup()

    def line(self, home):
        return '"%s/.local/share/mistrimulti/mistrimulti-launcher" --steam %%command%%' % home

    def test_fresh_install_adds_option_programs_and_mod(self):
        home, repo = make_env(self.tmp, {"1001": VDF_PLAIN.replace('"220"', '"999"')})
        r = run(home, repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = home / ".local/share/mistrimulti"
        for b in BINS:
            self.assertTrue(os.access(d / b, os.X_OK), b)
        text = vdf_path(home, "1001").read_text()
        self.assertIn('"LaunchOptions"\t\t"%s"' % self.line(home).replace('"', '\\"'), text)
        self.assertIn('"%s"' % APPID, text)
        self.assertIn('"-novid"', text)                       # other apps untouched
        self.assertIn('"PersonaName"', text)
        self.assertTrue(balanced(text))
        self.assertTrue(vdf_path(home, "1001").with_name("localconfig.vdf.mistrimulti-backup").exists())
        mod = home / ".local/share/Steam/steamapps/common/Fields of Mistria/mods/mistrimulti"
        self.assertTrue((mod / "manifest.toml").exists())
        self.assertTrue((mod / "gml").is_dir())
        self.assertIn("choose New Game or Load Game, then Multiplayer", r.stdout)     # the whole story: nothing to run before the game
        self.assertIn("Host a game", r.stdout)
        self.assertIn("Join a game", r.stdout)
        self.assertNotIn("To host run", r.stdout)
        self.assertIn("MOMI", r.stdout)

    def test_no_existing_option_in_app_block(self):
        home, repo = make_env(self.tmp, {"1001": VDF_NO_OPTION})
        self.assertEqual(run(home, repo).returncode, 0)
        text = vdf_path(home, "1001").read_text()
        self.assertEqual(text.count("LaunchOptions"), 1)
        self.assertIn('"LastPlayed"', text)
        self.assertTrue(balanced(text))

    def test_idempotent(self):
        home, repo = make_env(self.tmp, {"1001": VDF_NO_OPTION})
        run(home, repo)
        first = vdf_path(home, "1001").read_text()
        backup = vdf_path(home, "1001").with_name("localconfig.vdf.mistrimulti-backup").read_text()
        r = run(home, repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already set", r.stdout)
        self.assertEqual(vdf_path(home, "1001").read_text(), first)
        self.assertEqual(vdf_path(home, "1001").with_name("localconfig.vdf.mistrimulti-backup").read_text(), backup)
        self.assertEqual(backup, VDF_NO_OPTION)

    def test_existing_option_kept_when_declined_replaced_when_accepted(self):
        home, repo = make_env(self.tmp, {"1001": VDF_OLD_OPTION})
        r = run(home, repo, stdin="n\n")
        self.assertEqual(vdf_path(home, "1001").read_text(), VDF_OLD_OPTION)
        self.assertIn("gamemoderun %command%", r.stdout)
        self.assertIn(self.line(home), r.stdout)              # printed for manual use
        r = run(home, repo, stdin="")                         # no answer at all = no
        self.assertEqual(vdf_path(home, "1001").read_text(), VDF_OLD_OPTION)
        r = run(home, repo, stdin="y\n")
        text = vdf_path(home, "1001").read_text()
        self.assertNotIn("gamemoderun", text)
        self.assertIn("mistrimulti-launcher", text)
        self.assertTrue(balanced(text))
        self.assertEqual(vdf_path(home, "1001").with_name("localconfig.vdf.mistrimulti-backup").read_text(), VDF_OLD_OPTION)

    def test_steam_running_does_not_edit(self):
        home, repo = make_env(self.tmp, {"1001": VDF_NO_OPTION})
        r = run(home, repo, running=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(vdf_path(home, "1001").read_text(), VDF_NO_OPTION)
        self.assertFalse(vdf_path(home, "1001").with_name("localconfig.vdf.mistrimulti-backup").exists())
        self.assertIn(self.line(home), r.stdout)
        self.assertIn("close steam", r.stdout.lower())
        self.assertTrue((home / ".local/share/mistrimulti/mistrimulti-launcher").exists())   # programs still installed

    def test_missing_appmanifest(self):
        home, repo = make_env(self.tmp, {"1001": VDF_NO_OPTION}, manifest=False)
        r = run(home, repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(vdf_path(home, "1001").read_text(), VDF_NO_OPTION)
        self.assertIn("not installed", r.stdout)
        self.assertIn(self.line(home), r.stdout)
        self.assertIn("MOMI", r.stdout)

    def test_two_users_and_second_library(self):
        home, repo = make_env(self.tmp, {"1001": VDF_NO_OPTION, "2002": VDF_PLAIN}, library_extra=True)
        r = run(home, repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for uid in ("1001", "2002"):
            text = vdf_path(home, uid).read_text()
            self.assertEqual(text.count("mistrimulti-launcher"), 1, uid)
            self.assertTrue(balanced(text), uid)
        # app-missing user got a fresh block
        self.assertIn('"%s"' % APPID, vdf_path(home, "2002").read_text())
        self.assertTrue((self.tmp / "games/steamapps/common/Fields of Mistria/mods/mistrimulti/manifest.toml").exists())

    def test_uninstall_restores_backup_and_removes_folder(self):
        home, repo = make_env(self.tmp, {"1001": VDF_NO_OPTION, "2002": VDF_PLAIN})
        run(home, repo)
        r = run(home, repo, "--uninstall", running=True)
        self.assertNotEqual(r.returncode, 0)                  # refuses while Steam runs
        self.assertTrue((home / ".local/share/mistrimulti").exists())
        r = run(home, repo, "--uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(vdf_path(home, "1001").read_text(), VDF_NO_OPTION)
        self.assertEqual(vdf_path(home, "2002").read_text(), VDF_PLAIN)
        self.assertFalse((home / ".local/share/mistrimulti").exists())
        self.assertEqual(run(home, repo, "--uninstall").returncode, 0)   # twice is fine

    def test_uninstall_after_steam_changed_the_file(self):
        home, repo = make_env(self.tmp, {"1001": VDF_NO_OPTION})
        run(home, repo)
        p = vdf_path(home, "1001")
        p.write_text(p.read_text().replace('"Tester"', '"Renamed"'))
        r = run(home, repo, "--uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = p.read_text()
        self.assertIn('"Renamed"', text)                      # Steam's own change survives
        self.assertNotIn("mistrimulti-launcher", text)
        self.assertTrue(balanced(text))

    def test_dry_run_changes_nothing(self):
        home, repo = make_env(self.tmp, {"1001": VDF_NO_OPTION})
        r = run(home, repo, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("dry run", r.stdout)
        self.assertEqual(vdf_path(home, "1001").read_text(), VDF_NO_OPTION)
        self.assertFalse((home / ".local/share/mistrimulti").exists())
        self.assertFalse((home / ".local/share/Steam/steamapps/common/Fields of Mistria/mods").exists())
        self.assertEqual(sorted(p.name for p in vdf_path(home, "1001").parent.iterdir()), ["localconfig.vdf"])

    def test_custom_dir(self):
        home, repo = make_env(self.tmp, {"1001": VDF_NO_OPTION})
        custom = self.tmp / "my folder"
        r = run(home, repo, extra={"MISTRIMULTI_DIR": str(custom)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((custom / "mistrimulti-launcher").exists())
        self.assertIn('\\"%s/mistrimulti-launcher\\" --steam' % custom, vdf_path(home, "1001").read_text())

    def test_missing_build_tools_prints_one_apt_command(self):
        home, repo = make_env(self.tmp, {"1001": VDF_NO_OPTION})
        shutil.rmtree(repo / "build")
        (repo / "scripts").mkdir()
        (repo / "scripts/build-linux.sh").write_text("exit 1\n")
        bindir = self.tmp / "bin"
        bindir.mkdir()
        for tool in "sh awk sed grep cp mv mkdir rm ln cat cmp cksum mktemp dirname basename chmod head sort readlink printf cut tr date".split():
            w = shutil.which(tool)
            if w:
                (bindir / tool).symlink_to(w)
        r = run(home, repo, path=str(bindir))
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout.count("sudo apt-get install"), 1, r.stdout)
        self.assertIn("sudo apt-get install -y nasm binutils", r.stdout)
        self.assertEqual(vdf_path(home, "1001").read_text(), VDF_NO_OPTION)

    def test_foreign_mod_not_overwritten(self):
        home, repo = make_env(self.tmp, {"1001": VDF_NO_OPTION})
        other = home / ".local/share/Steam/steamapps/common/Fields of Mistria/mods/mistrimulti"
        other.mkdir(parents=True)
        (other / "manifest.toml").write_text('name = "SomethingElse"\n')
        run(home, repo)
        self.assertIn("SomethingElse", (other / "manifest.toml").read_text())


# ---------------------------------------------------------------- update from a (fake) release server
def sha(data):
    return hashlib.sha256(data).hexdigest()


class Site:
    """A local web server that mimics the release layout (docs/RELEASES.md): /release/latest.txt, /mod/mistrimulti/<file>, /dl/<tar.gz>."""

    def __init__(self):
        self.files = {}
        self.requests = []
        self.fail = {}
        site = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                site.requests.append(self.path)
                if self.path in site.fail:
                    self.send_error(site.fail[self.path])
                    return
                data = site.files.get(self.path)
                if data is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def publish(self, version, mod, progs=None, raw=None, tar_hash=None, bad_tar=False):
        """mod: {relative path under mod/mistrimulti: bytes}; progs: {program name: bytes} (default: new versions of all four), False = no tar."""
        lines = ["version " + version]
        for rel, data in mod.items():
            self.files["/mod/mistrimulti/" + rel] = data
            lines.append("%s mod/mistrimulti/%s" % (sha(data), rel))
        count = len(mod)
        if progs is not False:
            progs = progs or {b: ("#!/bin/sh\necho %s %s\n" % (b, version)).encode() for b in BINS}
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tf:
                for name, data in dict(progs, **{"install.sh": (ROOT / "install.sh").read_bytes()}).items():
                    ti = tarfile.TarInfo("MistriaMulti/" + name)
                    ti.size = len(data)
                    ti.mode = 0o755
                    tf.addfile(ti, io.BytesIO(data))
            tar_bytes = buf.getvalue()
            name = "MistriaMulti-%s-Linux.tar.gz" % version
            self.files["/dl/" + name] = tar_bytes if not bad_tar else tar_bytes + b"x"
            lines.insert(1, "#linux-tar %s %s" % (tar_hash or sha(tar_bytes), name))
        lines.append("end %d" % count)
        self.files["/release/latest.txt"] = (raw if raw is not None else "\n".join(lines) + "\n").encode()


MOD_V1 = {"manifest.toml": b'name = "MistriaMulti"\nversion = "0.4.6"\n', "gml/A.gml": b"function a() { return 1; }\n", "gml/Old.gml": b"old\n"}
MOD_V2 = {"manifest.toml": b'name = "MistriaMulti"\nversion = "0.9.0"\n', "gml/A.gml": b"function a() { return 2; }\n", "gml/B.gml": b"function b() {}\n"}


def tree(path):
    return {str(p.relative_to(path)): (p.read_bytes() if p.is_file() else None) for p in sorted(path.rglob("*"))}


FAKE_CLI = "#!/bin/sh\necho \"cwd=$(pwd) exit_on_complete=$EXIT_ON_COMPLETE args=$#\" > \"$MOMI_PROOF\"\necho 'Installed 1 mod'\nexit ${FAKE_MOMI_RC:-0}\n"


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.home, self.repo = make_env(self.tmp, {"1001": VDF_NO_OPTION})
        self.site = Site()
        self.dir = self.home / ".local/share/mistrimulti"
        self.mod = self.home / ".local/share/Steam/steamapps/common/Fields of Mistria/mods/mistrimulti"
        self.game = self.mod.parent.parent
        # an installed 0.4.6 (the mod files of the old release, programs of the old build)
        shutil.rmtree(self.repo / "mod" / "mistrimulti")
        for rel, data in MOD_V1.items():
            (self.repo / "mod/mistrimulti" / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / "mod/mistrimulti" / rel).write_bytes(data)
        r = run(self.home, self.repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.extra = {"MISTRIMULTI_RELEASE_BASE": self.site.base}

    def tearDown(self):
        self.site.close()
        self._t.cleanup()

    def upd(self, *args, stdin="", extra=None, path=None):
        return run(self.home, self.repo, *args, stdin=stdin, extra=dict(self.extra, **(extra or {})), path=path)

    def snapshot(self):
        return tree(self.dir), tree(self.mod)

    def test_install_keeps_the_update_script(self):
        self.assertTrue(os.access(self.dir / "mistrimulti-update.sh", os.X_OK))
        self.assertEqual((self.dir / "mistrimulti-update.sh").read_bytes(), (ROOT / "install.sh").read_bytes())

    def test_update_programs_and_mod_files(self):
        self.site.publish("0.9.0", MOD_V2)
        r = self.upd("--update")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Latest release: 0.9.0", r.stdout)
        self.assertEqual((self.mod / "gml/A.gml").read_bytes(), MOD_V2["gml/A.gml"])
        self.assertEqual((self.mod / "gml/B.gml").read_bytes(), MOD_V2["gml/B.gml"])
        self.assertFalse((self.mod / "gml/Old.gml").exists(), "a file that left the release is removed")
        self.assertIn("0.9.0", (self.mod / "manifest.toml").read_text())
        self.assertTrue((self.mod / "LICENSE").exists(), "LICENSE/CONTACT.md of the install are kept")
        for b in BINS:
            self.assertIn("0.9.0", (self.dir / b).read_text())
            self.assertTrue(os.access(self.dir / b, os.X_OK))
        self.assertFalse(list(self.dir.glob("*.new")) or list(self.mod.parent.glob("*.new")) or list(self.mod.parent.glob("*.old")))
        self.assertIn("click Install", r.stdout)
        self.assertIn("--momi-cli", r.stdout)
        # idempotent: the second run changes nothing and asks for no MOMI step
        before = self.snapshot()
        n = len(self.site.requests)
        r = self.upd("--update")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("Mod files: already up to date", r.stdout)
        self.assertIn("nothing to do", r.stdout)
        # only the list and the program archive are fetched when the mod files already match
        self.assertEqual(sorted(set(self.site.requests[n:])), ["/dl/MistriaMulti-0.9.0-Linux.tar.gz", "/release/latest.txt"])

    def test_only_changed_mod_files_are_downloaded(self):
        self.site.publish("0.9.0", MOD_V2)
        self.upd("--update")
        mod3 = dict(MOD_V2, **{"gml/A.gml": b"function a() { return 3; }\n"})
        self.site.publish("0.9.1", mod3)
        n = len(self.site.requests)
        r = self.upd("--update")
        self.assertEqual(r.returncode, 0, r.stdout)
        got = [x for x in self.site.requests[n:] if x.startswith("/mod/")]
        self.assertEqual(got, ["/mod/mistrimulti/gml/A.gml"])

    def test_no_network_changes_nothing_and_says_so(self):
        before = self.snapshot()
        r = self.upd("--update", extra={"MISTRIMULTI_RELEASE_BASE": "http://127.0.0.1:1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("Could not reach", r.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_bad_downloads_change_nothing(self):
        before = self.snapshot()
        self.site.publish("0.9.0", MOD_V2)
        self.site.files["/mod/mistrimulti/gml/B.gml"] = b"evil"
        r = self.upd("--update")
        self.assertEqual(r.returncode, 1)
        self.assertIn("checksum", r.stdout)
        self.assertEqual(self.snapshot(), before)
        self.site.publish("0.9.0", MOD_V2, bad_tar=True)
        r = self.upd("--update")
        self.assertEqual(r.returncode, 1)
        self.assertIn("checksum", r.stdout)
        self.assertEqual(self.snapshot(), before)
        self.site.publish("0.9.0", MOD_V2)
        self.site.fail["/mod/mistrimulti/gml/B.gml"] = 404
        r = self.upd("--update")
        self.assertEqual(r.returncode, 1)
        self.assertIn("download failed", r.stdout)
        self.assertEqual(self.snapshot(), before)
        self.site.fail.clear()
        h = "a" * 64
        m = "%s mod/mistrimulti/manifest.toml" % sha(MOD_V2["manifest.toml"])
        hostile = {
            "path traversal": f"version 0.9.0\n{h} mod/mistrimulti/../../evil\n{m}\nend 2\n",
            "absolute path": f"version 0.9.0\n{h} /etc/passwd\n{m}\nend 2\n",
            "hidden file": f"version 0.9.0\n{h} mod/mistrimulti/.x\n{m}\nend 2\n",
            "unknown tool": f"version 0.9.0\n{h} bin/evil.exe\n{m}\nend 2\n",
            "no footer": f"version 0.9.0\n{m}\n",
            "cut": f"version 0.9.0\n{m}\nend 1",
            "wrong count": f"version 0.9.0\n{m}\nend 5\n",
            "no manifest": f"version 0.9.0\n{h} mod/mistrimulti/gml/A.gml\nend 1\n",
            "bad version": f"version 0.9.0/../x\n{m}\nend 1\n",
            "upper hash": f"version 0.9.0\n{'A' * 64} mod/mistrimulti/manifest.toml\nend 1\n",
            "duplicate": f"version 0.9.0\n{h} mod/mistrimulti/manifest.toml\n{h} mod/mistrimulti/manifest.toml\nend 2\n",
            "content after footer": f"version 0.9.0\n{m}\nend 1\n{h} mod/mistrimulti/x\n",
            "tar for another version": f"version 0.9.0\n#linux-tar {h} MistriaMulti-0.1.0-Linux.tar.gz\n{m}\nend 1\n",
            "tar with a path": f"version 0.9.0\n#linux-tar {h} ../x-Linux.tar.gz\n{m}\nend 1\n",
            "oversized": "version 0.9.0\n" + "#" + "x" * 40000 + "\nend 0\n",
            "junk": "\x00\x01\x02" * 50 + "\n",
            "empty": "",
        }
        for label, text in hostile.items():
            self.site.publish("0.9.0", MOD_V2, raw=text)
            self.site.requests.clear()
            r = self.upd("--update")
            self.assertEqual(r.returncode, 1, label + r.stdout)
            self.assertIn("Nothing was changed", r.stdout, label)
            if label != "oversized":
                self.assertIn("not valid", r.stdout, label)
            self.assertEqual(self.snapshot(), before, label)
            self.assertEqual(self.site.requests, ["/release/latest.txt"], label)

    def test_newer_installed_mod_is_not_replaced(self):
        newer = dict(MOD_V2, **{"manifest.toml": b'name = "MistriaMulti"\nversion = "0.2.0"\n'})
        (self.mod / "manifest.toml").write_text('name = "MistriaMulti"\nversion = "0.10.0"\n')
        self.site.publish("0.2.0", newer)
        r = self.upd("--update")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("newer", r.stdout)
        self.assertIn("0.10.0", (self.mod / "manifest.toml").read_text())
        self.assertEqual((self.mod / "gml/A.gml").read_bytes(), MOD_V1["gml/A.gml"])

    def test_foreign_mod_and_missing_game(self):
        self.site.publish("0.9.0", MOD_V2)
        (self.mod / "manifest.toml").write_text('name = "SomethingElse"\n')
        r = self.upd("--update")
        self.assertIn("Another mod", r.stdout)
        self.assertIn("SomethingElse", (self.mod / "manifest.toml").read_text())
        shutil.rmtree(self.game)
        r = self.upd("--update")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("Game folder not found", r.stdout)
        self.assertIn("0.9.0", (self.dir / "mistrimulti-launcher").read_text(), "programs are still updated")

    def test_release_without_linux_programs(self):
        self.site.publish("0.9.0", MOD_V2, progs=False)
        r = self.upd("--update")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("lists no Linux programs", r.stdout)
        self.assertIn("0.9.0", (self.mod / "manifest.toml").read_text())

    def test_dry_run_changes_nothing(self):
        self.site.publish("0.9.0", MOD_V2)
        before = self.snapshot()
        r = self.upd("--update", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("[dry run]", r.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_not_installed_yet(self):
        shutil.rmtree(self.dir)
        r = self.upd("--update")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Run ./install.sh first", r.stdout)

    def test_wget_fallback_and_no_downloader(self):
        wget = shutil.which("wget")
        bindir = self.tmp / "bin2"
        bindir.mkdir()
        for tool in "sh awk sed grep cp mv mkdir rm ln cat cmp cksum mktemp dirname basename chmod head tail sort readlink printf cut tr date od wc find tar gzip sha256sum timeout id".split():
            w = shutil.which(tool)
            if w:
                (bindir / tool).symlink_to(w)
        r = self.upd("--update", path=str(bindir))
        self.assertEqual(r.returncode, 1)
        self.assertIn("Neither curl nor wget", r.stdout)
        if wget:
            (bindir / "wget").symlink_to(wget)
            self.site.publish("0.9.0", MOD_V2)
            r = self.upd("--update", path=str(bindir))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual((self.mod / "gml/A.gml").read_bytes(), MOD_V2["gml/A.gml"])

    def cli(self, name="ModsOfMistriaInstaller-cli-linux", rc=0):
        p = self.tmp / name
        p.write_text(FAKE_CLI)
        p.chmod(0o755)
        proof = self.tmp / "proof.txt"
        self.extra.update({"MOMI_PROOF": str(proof), "FAKE_MOMI_RC": str(rc)})
        return p, proof

    def test_momi_cli_is_run_only_after_consent(self):
        p, proof = self.cli()
        r = self.upd("--momi-cli", str(p))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual((self.dir / "momi-cli.path").read_text().strip(), str(p))
        self.site.publish("0.9.0", MOD_V2)
        r = self.upd("--update", stdin="n\n")
        self.assertFalse(proof.exists(), "declined: not run")
        self.assertIn("Not run", r.stdout)
        self.assertIn("click Install", r.stdout)
        self.assertEqual(self.upd("--update", stdin="").returncode, 0)       # a pipe that ends: also a no
        self.assertFalse(proof.exists())
        # changed again, consent given
        self.site.publish("0.9.1", dict(MOD_V2, **{"gml/B.gml": b"function b() { return 1; }\n"}))
        r = self.upd("--update", stdin="y\n")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(proof.exists(), r.stdout)
        line = proof.read_text()
        self.assertIn("cwd=%s " % self.game, line)
        self.assertIn("exit_on_complete=true", line)
        self.assertIn("args=0", line)
        self.assertIn("Installed 1 mod", r.stdout)
        self.assertIn("exit code 0", r.stdout)
        self.assertNotIn("click Install", r.stdout)
        self.assertTrue((self.dir / "momi.log").exists())

    def test_momi_cli_failure_and_validation(self):
        p, proof = self.cli(rc=3)
        self.upd("--momi-cli", str(p))
        self.site.publish("0.9.0", MOD_V2)
        r = self.upd("--update", stdin="y\n")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("exit code 3", r.stdout)
        self.assertIn("click Install", r.stdout)
        bad = self.tmp / "ModsOfMistriaInstaller"
        bad.write_text(FAKE_CLI)
        bad.chmod(0o755)
        r = self.upd("--momi-cli", str(bad))
        self.assertEqual(r.returncode, 1)
        self.assertIn("-cli", r.stdout)
        notexec = self.tmp / "x-cli"
        notexec.write_text(FAKE_CLI)
        self.assertEqual(self.upd("--momi-cli", str(notexec)).returncode, 1)
        self.assertEqual(self.upd("--momi-cli", str(self.tmp / "missing-cli")).returncode, 1)
        link = self.tmp / "link-cli"
        link.symlink_to(p)
        self.assertEqual(self.upd("--momi-cli", str(link)).returncode, 1)
        self.assertEqual((self.dir / "momi-cli.path").read_text().strip(), str(p))
        self.assertEqual(self.upd("--momi-cli", "none").returncode, 0)
        self.assertFalse((self.dir / "momi-cli.path").exists())
        # a saved path that is not a -cli program is not run
        (self.dir / "momi-cli.path").write_text(str(bad) + "\n")
        self.site.publish("0.9.1", dict(MOD_V2, **{"gml/B.gml": b"x\n"}))
        proof.unlink(missing_ok=True)
        self.upd("--update", stdin="y\n")
        self.assertFalse(proof.exists())

    def result(self, *args, extra=None, stdin=""):
        out = self.tmp / "result.txt"
        out.unlink(missing_ok=True)
        r = self.upd("--update", "--result", str(out), *args, extra=extra, stdin=stdin)
        fields = {}
        if out.exists():
            for line in out.read_text().splitlines():
                k, _, v = line.partition("=")
                fields[k] = v
        self.assertFalse((self.tmp / "result.txt.tmp").exists())
        return r, fields

    def test_result_file_needs_momi_then_done_with_standing_permission(self):
        p, proof = self.cli()
        self.upd("--momi-cli", str(p))                                  # remembered, but no standing permission
        self.site.publish("0.9.0", MOD_V2)
        r, f = self.result(stdin="y\n")                                 # an answer on stdin is never read
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((f["state"], f["version"], f["error"]), ("needs_momi", "0.9.0", "0"), f)
        self.assertIn("Install in MOMI", f["message"])
        self.assertFalse(proof.exists())
        self.assertTrue((self.dir / "momi-pending").exists())
        self.assertEqual((self.mod / "gml/A.gml").read_bytes(), MOD_V2["gml/A.gml"])
        # standing permission, but the caller forbids it (the game is open)
        r, f = self.result(extra={"MISTRIMULTI_NO_MOMI": "1"})
        self.upd("--momi-cli", str(p), "--always")
        r, f = self.result(extra={"MISTRIMULTI_NO_MOMI": "1"})
        self.assertEqual(f["state"], "needs_momi", f)
        self.assertFalse(proof.exists())
        # standing permission: the pending step runs although the files are current
        r, f = self.result()
        self.assertEqual((r.returncode, f["state"], f["error"]), (0, "done", "0"), (r.stdout, f))
        self.assertTrue(proof.exists())
        self.assertIn("exit_on_complete=true", proof.read_text())
        self.assertFalse((self.dir / "momi-pending").exists())
        # nothing new now
        r, f = self.result()
        self.assertEqual((r.returncode, f["state"]), (0, "done"), f)
        self.assertIn("up to date", f["message"])

    def test_result_file_failing_installer_and_programs_only(self):
        p, proof = self.cli(rc=4)
        self.upd("--momi-cli", str(p), "--always")
        self.site.publish("0.9.0", MOD_V2)
        r, f = self.result()
        self.assertEqual((r.returncode, f["state"], f["error"]), (0, "needs_momi", "30"), f)
        self.assertIn("exit code 4", f["message"])
        (self.dir / "momi-pending").unlink()
        self.site.publish("0.9.1", MOD_V2, progs={b: b"#!/bin/sh\necho newer\n" for b in BINS})
        r, f = self.result()
        self.assertEqual((r.returncode, f["state"]), (0, "done"), f)
        self.assertIn("programs", f["message"])
        self.assertFalse((self.dir / "momi-pending").exists())

    def test_result_file_failures(self):
        r, f = self.result(extra={"MISTRIMULTI_RELEASE_BASE": "http://127.0.0.1:1"})
        self.assertEqual((r.returncode, f["state"], f["error"]), (20, "failed", "20"), f)
        self.assertIn("Could not reach", f["message"])
        self.site.publish("0.9.0", MOD_V2, raw="junk\n")
        r, f = self.result()
        self.assertEqual((r.returncode, f["state"]), (21, "failed"), f)
        self.site.publish("0.9.0", MOD_V2)
        self.site.files["/mod/mistrimulti/gml/B.gml"] = b"evil"
        before = self.snapshot()
        r, f = self.result()
        self.assertEqual((r.returncode, f["state"], f["error"]), (22, "failed", "22"), f)
        self.assertEqual(self.snapshot(), before)
        self.site.publish("0.9.0", MOD_V2, progs=False)
        (self.mod / "manifest.toml").write_text('name = "MistriaMulti"\nversion = "0.10.0"\n')
        r, f = self.result()
        self.assertEqual((r.returncode, f["state"]), (0, "done"), f)
        self.assertIn("newer", f["message"])
        shutil.rmtree(self.dir)
        r, f = self.result()
        self.assertEqual((r.returncode, f["state"], f["error"]), (13, "failed", "13"), f)

    def test_manager_update_result(self):
        manager = ROOT / "build" / "mistrimulti-manager"
        if not manager.exists():
            self.skipTest("build/mistrimulti-manager is not built")
        shutil.copy(manager, self.dir / "mistrimulti-manager")
        self.site.publish("0.9.0", MOD_V2)
        out = self.tmp / "res.txt"
        env = dict(os.environ, HOME=str(self.home), MISTRIMULTI_STEAM_RUNNING="0", TMPDIR=str(self.tmp), **self.extra)
        r = subprocess.run([str(self.dir / "mistrimulti-manager"), "update", "--result", str(out)], env=env, capture_output=True, text=True, timeout=60, cwd=str(self.home))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("state=needs_momi", out.read_text())
        self.assertEqual((self.mod / "gml/A.gml").read_bytes(), MOD_V2["gml/A.gml"])
        self.site.publish("0.9.1", dict(MOD_V2, **{"gml/B.gml": b"x\n"}))
        shutil.copy(manager, self.dir / "mistrimulti-manager")
        r = subprocess.run([str(self.dir / "mistrimulti-manager"), "update"], env=env, input="n\n", capture_output=True, text=True, timeout=60, cwd=str(self.home))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Latest release: 0.9.1", r.stdout)
        (self.dir / "mistrimulti-update.sh").unlink()
        shutil.copy(manager, self.dir / "mistrimulti-manager")
        r = subprocess.run([str(self.dir / "mistrimulti-manager"), "update"], env=env, capture_output=True, text=True, timeout=60, cwd=str(self.home))
        self.assertEqual(r.returncode, 1)
        self.assertIn("mistrimulti-update.sh", r.stderr)

    def test_daily_check(self):
        md = self.tmp / "moddata"
        md.mkdir()
        self.site.publish("0.9.0", MOD_V2)
        r = self.upd("--daily", str(md))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        data = json.loads((md / "update.json").read_text())
        self.assertEqual((data["v"], data["latest"]), (1, "0.9.0"))
        self.assertLess(abs(data["checked"] - time.time()), 300)
        n = len(self.site.requests)
        self.upd("--daily", str(md))
        self.assertEqual(len(self.site.requests), n, "once a day")
        (md / "update.json").write_text(json.dumps({"v": 1, "latest": "0.1.0", "checked": int(time.time()) - 2 * 86400}))
        self.upd("--daily", str(md))
        self.assertEqual(json.loads((md / "update.json").read_text())["latest"], "0.9.0")
        (md / "update.json").write_text(json.dumps({"v": 1, "latest": "0.1.0", "checked": int(time.time()) + 9 * 86400}))
        self.upd("--daily", str(md))
        self.assertEqual(json.loads((md / "update.json").read_text())["latest"], "0.9.0", "a future time is ignored")
        (md / "update.json").unlink()
        (md / "update.cfg").write_text("check=off\n")
        n = len(self.site.requests)
        self.upd("--daily", str(md))
        self.assertEqual(len(self.site.requests), n)
        self.assertFalse((md / "update.json").exists())
        (md / "update.cfg").write_text("check=on\n")
        for label, base, setup in (("unreachable", "http://127.0.0.1:1", None),
                                   ("404", self.site.base, lambda: self.site.fail.update({"/release/latest.txt": 404})),
                                   ("invalid", self.site.base, lambda: (self.site.fail.clear(), self.site.publish("0.9.0", MOD_V2, raw="version 0.9.0\n")))):
            if setup:
                setup()
            t = time.time()
            r = self.upd("--daily", str(md), extra={"MISTRIMULTI_RELEASE_BASE": base})
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), label)
            self.assertFalse((md / "update.json").exists(), label)
            self.assertLess(time.time() - t, 15, label)
        self.assertFalse(list(md.glob("*.tmp")))
        # a missing folder is not created and not an error
        self.assertEqual(self.upd("--daily", str(self.tmp / "nope")).returncode, 0)
        self.assertFalse((self.tmp / "nope").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
