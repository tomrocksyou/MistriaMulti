#!/usr/bin/env python3
"""Tests install.sh against a fake HOME with a fake Steam tree. No build tools, no real Steam, no network.

    python3 tests/test_install_linux.py
"""
import os, re, shutil, subprocess, sys, tempfile, unittest
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
        for tool in "sh awk sed grep cp mv mkdir rm ln cat cmp cksum mktemp dirname chmod head sort readlink printf cut tr date".split():
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
