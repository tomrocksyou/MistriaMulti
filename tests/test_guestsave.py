"""Guest saving, leaving and returning (MistriMultiGuestSave.gml).

    python3 tests/test_guestsave.py            # about 1 minute; name tests to run only those

MistriMultiGuestSave.gml runs unmodified in tests/gml_subset.py together with the real player-sync, player-data (storage),
progress and identity files, on the event layer, over the simulated helpers and network of tests/event_sim.py. The game is
faked exactly as in tests/test_progress.py (its engine, file system and record stand-ins are reused); on top of that this file
fakes the pieces the guest-save code touches: the save-space state, notifications, popups, the screen fader and
Game.exit_to_menu. MistriMultiBoot.gml is loaded in a separate interpreter to check how the save guard and the hooks are wired.
It checks logic and wiring; it does not prove how the real game behaves: docs/SYNC-GUESTSAVE.md has the in-game checklist.
"""
import json
import re
import sys
from pathlib import Path

import gml_subset as gml
from gml_subset import GStruct
from event_sim import World
from test_event_features import Popup
import test_progress as P
from test_progress import ALICE, BOB, WORLD, wait_ready, stored, core_file, no_errors, engine_state

ROOT = Path(__file__).resolve().parent.parent
GML_DIR = ROOT / "mod/mistrimulti/gml"
SOLO_DIR = "C:/Users/me/AppData/Local/FieldsOfMistria"
SOLO_SAVE = SOLO_DIR + "/saves/game-777-autosave.sav"
MP_SAVE = SOLO_DIR + "/multiplayer/saves/game-777-autosave.sav"
SETTINGS, OTHER_MENU = 7, 3
BUSY = "This player identity is already connected."


# ---- the fake game around the guest-save code ---------------------------------------------------------------------------------

class GuestNode(P.ProgressNode):
    extra_files = P.ProgressNode.extra_files + ("MistriMultiGuestSave.gml",)

    def builtins(self):
        b = super().builtins()
        self.notes, self.popups, self.fades, self.exits = [], [], [], []
        self.space = GStruct(active=True, solo_dir=SOLO_DIR)
        b.update({
            "__mistrimulti_savespace": lambda: self.space,
            "mistrimulti_savespace_mode": lambda: "host" if self.slot == 0 else "join",
            "create_notification": self.notes.append,
            "ANCHOR": GStruct(wrap_for_local=lambda text: text),
            "Menu": GStruct(Settings=SETTINGS, Title=1),
            "popup_creator": self.popup_creator,
            "SCREEN_FADER": GStruct(fade_out=lambda speed, fn: self.fades.append(fn)),
            "FADE_SPEED_TRANSITION": 30,
            "Game": GStruct(unique_identifier=777, exit_to_menu=lambda: self.exits.append(1)),
            "string_lower": str.lower, "mmapi_log_flush": lambda mod: None,
        })
        return b

    def popup_creator(self, title, body):
        popup = Popup(self, title)
        popup.body = body
        return popup.struct

    def setup(self):
        super().setup()
        self.rt.update(bridge="bridge", last_frame="")


class GDriver(P.Driver):
    """P.Driver plus what MistriMultiBoot.gml's tick does for this file."""

    def tick(self, now):
        super().tick(now)
        if self.running:
            self.node.interp.call("mistrimulti_guestsave_tick")


def make_world(seed, guests=1, host_uid=None, **faults):
    P.FILESYSTEMS.clear()
    P.ENGINES.clear()
    P.UIDS.clear()
    P.UIDS[1], P.UIDS[2], P.UIDS[3] = ALICE, BOB, P.CAROL
    if host_uid:
        P.UIDS[0] = host_uid
    world = World(seed, {i: GuestNode for i in range(guests + 1)}, **faults)
    for game in world.games.values():
        game.feature = GDriver(game)
    return world


def restart(world, slot, uid=None):
    """The game of one player is closed and started again (its files stay, the process does not)."""
    if uid is not None:
        P.UIDS[slot] = uid
    P.ENGINES.pop(slot, None)
    game = world.start(slot)
    game.feature = GDriver(game)
    return game.node


def quit_game(world, slot):
    """'Return to main menu': the game goes to its title screen (the helper process keeps running)."""
    game = world.games.pop(slot)
    game.node.call("mistrimulti_guestsave_title_entered", {"from_game": True})
    text = game.node.fs.files.get("bridge/tx.frame")
    if text is not None:
        world.net.helpers[slot].publish(text.split("\n", 1)[1], False, world.clock.ms)
    return game.node


def crash_game(world, slot):
    """The game and its helper vanish without a word (alt-F4 with the helper killed, power cut)."""
    world.games.pop(slot)
    world.net.helpers[slot].alive = False
    del world.net.helpers[slot]


def run_until(world, condition, limit_ms, what):
    start = world.clock.ms
    while not condition():
        if world.clock.ms - start > limit_ms:
            raise AssertionError(f"timed out after {limit_ms} ms: {what}")
        world.run(100)
    return world.clock.ms - start


def ready_pair(seed, play=True, guests=2, **faults):
    world = make_world(seed, guests=guests, **faults)
    host, alice = world.games[0].node, world.games[1].node
    world.run(4000)
    wait_ready(world, alice)
    if play:
        alice.engine.play()
    world.run(12000)
    return world, host, alice


def guard_ctx(node, path):
    return node.data({"save_path": path})


# ---- saving -------------------------------------------------------------------------------------------------------------------

def test_guest_save_is_vetoed():
    world, host, alice = ready_pair(1)
    files = set(alice.fs.files)
    assert alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, MP_SAVE)) is True, "a guest's save in the multiplayer folder"
    assert alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, SOLO_SAVE)) is True, "a guest's save in the solo folder"
    assert alice.call("mistrimulti_guestsave_blocks", None) is True and alice.call("mistrimulti_guestsave_blocks", gml.GStruct()) is True
    assert set(alice.fs.files) == files, "a vetoed save writes nothing"
    # The game's own "Save complete" notice is reworded into the one guest line; the mod adds no second notice of its own.
    TEXT = "Guests do not save: the host keeps your progress."
    assert alice.call("mistrimulti_guestsave_local_get", "x", "misc_local/save_complete") == TEXT
    assert alice.call("mistrimulti_guestsave_local_get", "x", "misc_local/saving") is None, "other texts are the game's"
    assert alice.call("mistrimulti_guestsave_local_get", "x", GStruct(key="misc_local/save_complete")) is None, "no struct keys"
    assert host.call("mistrimulti_guestsave_local_get", "x", "misc_local/save_complete") is None, "the host's notice stays 'Save complete'"
    world.run(6000)
    assert alice.notes == [], "no second line while the game's (reworded) notice is the one shown"
    assert "saved on the host" not in TEXT and "host's computer" not in TEXT
    # The reworded notice did not appear (the filter never ran): the mod says the same line itself, once.
    world.run(6000)
    alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, MP_SAVE))
    alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, MP_SAVE))
    assert alice.notes == [], "not before the game had its chance"
    world.run(3000)
    assert alice.notes == [TEXT], alice.notes
    alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, MP_SAVE))
    world.run(1500)
    assert alice.notes == [TEXT], "no repeat inside the notice gap"
    world.run(6000)
    alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, MP_SAVE))
    world.run(3000)
    assert alice.notes == [TEXT, TEXT], "the fallback returns after a pause"
    del alice.notes[:]
    alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, MP_SAVE))
    assert alice.call("mistrimulti_guestsave_local_get", "x", "misc_local/save_complete") == TEXT
    world.run(3000)
    assert alice.notes == [], "the game showed its notice: no fallback"
    # The host saves its own world, but never into the solo folder.
    assert host.call("mistrimulti_guestsave_blocks", guard_ctx(host, MP_SAVE)) is False
    assert host.call("mistrimulti_guestsave_blocks", guard_ctx(host, SOLO_SAVE.replace("/", "\\"))) is True, "also with backslashes"
    assert host.call("mistrimulti_guestsave_blocks", guard_ctx(host, SOLO_SAVE.upper())) is True, "also with other letter case"
    assert host.call("mistrimulti_guestsave_blocks", None) is False and host.notes == []
    # A guest whose runtime failed to start is still in the host's world copy: still no save. Singleplayer is never touched.
    alice.rt["enabled"] = False
    assert alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, MP_SAVE)) is True
    alice.space["active"] = False
    assert alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, SOLO_SAVE)) is False, "singleplayer saves are not ours to veto"
    assert alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, MP_SAVE)) is False
    host.space["solo_dir"] = None
    assert host.call("mistrimulti_guestsave_blocks", guard_ctx(host, SOLO_SAVE)) is False, "no solo folder known yet: nothing to compare"
    print("PASS: save guard: a guest never saves (no files written, one notice), nobody saves into the solo folder, singleplayer is untouched")


def test_save_attempt_sends_character():
    world, host, alice = ready_pair(2)
    base = core_file(host, ALICE)["data"]["gold"]
    revision = stored(host, ALICE)["revision"]
    alice.engine.ari["gold"] = base + 55
    alice.engine.ari["items_sold"] = gml.GArray([0, 0, 8, 0, 0, 0])
    alice.rt["player_last_checkpoint"] = alice.rt["progress_checkpointed"] = world.clock.micros()
    world.run(1800)
    assert core_file(host, ALICE)["data"]["gold"] == base, "without a flush the guest waits for its next checkpoint"
    alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, MP_SAVE))
    world.run(1800)
    assert core_file(host, ALICE)["data"]["gold"] == base + 55, "the save attempt sent the character at once"
    assert stored(host, ALICE)["revision"] == revision + 1 and alice.rt["player_saved_revision"] == alice.rt["player_revision"]
    # An upload already in flight is not doubled: the flush waits for the acknowledgement, then sends the rest.
    alice.engine.ari["gold"] = base + 60
    alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, MP_SAVE))
    alice.engine.ari["gold"] = base + 61
    alice.call("mistrimulti_guestsave_blocks", guard_ctx(alice, MP_SAVE))
    world.run(4000)
    assert core_file(host, ALICE)["data"]["gold"] == base + 61
    # Before the character is loaded there is nothing to flush.
    alice.rt["player_ready"] = False
    assert alice.call("mistrimulti_guestsave_flush") is False
    no_errors(world)
    print("PASS: a guest's save attempt flushes the character to the host at once (and coalesces repeated attempts)")


# ---- leaving ------------------------------------------------------------------------------------------------------------------

def test_final_flush_on_quit_and_return():
    world, host, alice = ready_pair(3)
    base = core_file(host, ALICE)["data"]["gold"]
    alice.engine.ari["gold"] = base + 99
    alice.engine.ari["items_sold"] = gml.GArray([0, 0, 4, 0, 0, 0])
    alice.rt["player_last_checkpoint"] = alice.rt["progress_checkpointed"] = world.clock.micros()
    # Other menus do nothing; the title screen's settings menu (no world) and the host's neither.
    alice.call("mistrimulti_guestsave_menu_opened", {"menu": None, "kind": OTHER_MENU})
    world.run(1800)
    assert core_file(host, ALICE)["data"]["gold"] == base, "an inventory or map menu is not a flush"
    host.call("mistrimulti_guestsave_menu_opened", {"menu": None, "kind": SETTINGS})
    alice.call("mistrimulti_guestsave_menu_opened", None)
    world.run(500)
    # Opening the settings menu (the way to every quit option) pushes the character to the host.
    alice.call("mistrimulti_guestsave_menu_opened", {"menu": None, "kind": SETTINGS})
    world.run(1800)
    assert core_file(host, ALICE)["data"]["gold"] == base + 99
    assert stored(host, ALICE)["data"]["sections"]["almanac"]["sold"]["carrot"] == 4, "the progress record too"
    # ... and quits. The host keeps exactly that; the same player returns later and resumes without a new character.
    quit_game(world, 1)
    world.run(3000)
    again = restart(world, 1)
    world.run(2000)
    assert wait_ready(world, again) is False, "a returning guest does not create a character again"
    assert again.engine.ari["gold"] == base + 99 and again.state["almanac"]["sold"]["carrot"] == 4
    assert alice.fs.files.get("bridge/tx.frame") is not None
    no_errors(world)
    print("PASS: leaving: opening the settings menu flushes the character; the host keeps it and the guest resumes on return")


def test_goodbye_frame():
    world, host, alice = ready_pair(4, play=False)
    alice.call("mistrimulti_guestsave_title_entered", {"from_game": True})
    frame_text = alice.fs.files["bridge/tx.frame"]
    assert frame_text.startswith("0\n") and "bridge/tx.tmp" not in alice.fs.files
    frame = json.loads(frame_text[2:])
    assert frame == {"v": 2, "epoch": alice.rt["epoch"], "id": 1, "uid": ALICE, "active": False, "world": ""}, frame
    assert alice.rt["last_frame"] == "" and alice.rt["guestsave"] is None, "the session state is dropped"
    # A game that never entered a world (the title screen at boot) writes nothing.
    fresh = restart(world, 2)
    assert "bridge/tx.frame" not in fresh.fs.files
    fresh.call("mistrimulti_guestsave_title_entered", {"from_game": False})
    assert "bridge/tx.frame" not in fresh.fs.files
    print("PASS: leaving a world writes one final inactive frame; a title screen that never had a world writes nothing")


def test_host_forgets_a_departed_guest():
    """A guest quits to its title (helper stays alive, still sending its last frame). The same player joins through another
    slot at once: not refused as 'already connected'."""
    world, host, alice = ready_pair(5)
    quit_game(world, 1)
    world.run(2000)
    peer = host.rt["peers"][1]
    assert peer["active"] is False and peer["world"] == "", peer
    assert host.rt["player_sessions"][1] is None, "the host forgot the record session of the guest that left"
    other = restart(world, 2, ALICE)
    assert wait_ready(world, other, 8000) is False, f"refused: {other.rt['player_error']!r}"
    assert other.rt["guestsave"]["retries"] == 0 and other.engine.ari["gold"] == 120
    no_errors(world)
    print("PASS: a guest that quit to the title can rejoin through another slot immediately, with its record")


def test_returning_through_another_slot_retries():
    """The game vanished (crash, alt-F4, network drop): the host counts the old slot for ~10 s. The returning player is refused
    at first, asks again every few seconds and is let in as soon as the old slot expires."""
    world, host, alice = ready_pair(6)
    crash_game(world, 1)
    other = restart(world, 2, ALICE)
    seen_busy = False
    for _ in range(300):
        world.run(100)
        seen_busy = seen_busy or other.rt["player_error"] == BUSY
        if other.rt["player_ready"]:
            break
    assert seen_busy, "the old slot was still counted when the player came back"
    assert other.rt["player_ready"] and other.rt["guestsave"]["retries"] >= 1, other.rt["player_error"]
    assert other.engine.ari["gold"] == 120 and other.state["almanac"]["sold"] == {"bread": 7, "egg": 3}
    world.run(12000)
    assert other.rt["player_error"] == "" and stored(host, ALICE)["data"]["uid"] == ALICE
    print("PASS: returning through another slot while the old one is still counted: refused, asked again, admitted at expiry")


def popup_of(node):
    return node.popups[0] if node.popups else None


def host_gone_fixture(seed):
    world, host, alice = ready_pair(seed, play=True)
    return world, host, alice, core_file(host, ALICE)


def tap_return(world, node):
    popup = popup_of(node)
    popup.tap("misc_local/return_to_main_menu")
    assert node.exits == [] and len(node.fades) == 1, "the game fades out first, like its own menu"
    node.interp.call_value(node.fades[0], [], 0)
    assert node.exits == [1], "Game.exit_to_menu runs once"


def test_host_crash_returns_guest_to_title():
    world, host, alice, record = host_gone_fixture(7)
    files = set(alice.fs.files)
    crash_game(world, 0)
    start = world.clock.ms
    world.run(9000)
    assert alice.popups == [] and alice.notes == [], "a short silence is not an alarm"
    run_until(world, lambda: alice.notes, 25000, "the waiting notice")
    assert "Connection to the host lost" in alice.notes[0] and alice.popups == []
    took = run_until(world, lambda: alice.popups, 40000, "the disconnect message")
    elapsed = world.clock.ms - start
    assert 28000 <= elapsed <= 33000, f"10 s helper expiry + 20 s grace, got {elapsed} ms"
    popup = popup_of(alice)
    assert popup.title == "mistrimulti/guest_gone_title" and popup.body == "mistrimulti/guest_lost_body"
    assert alice.exits == [] and alice.fades == [], "the message waits for the player"
    world.run(30000)
    assert len(alice.popups) == 1 and len(alice.notes) == 1, "one message and one notice, not one per frame"
    tap_return(world, alice)
    # Nothing was written by the guest while all this happened; the host's last acknowledged record is intact.
    assert all(f.startswith("data/exports/") for f in set(alice.fs.files) - files), set(alice.fs.files) - files
    assert record["data"]["gold"] == 120
    print("PASS: host crash: after the helper expiry and a 20 s grace the guest sees a message and returns to the title; nothing is written")


def test_host_closes_or_restarts_the_world():
    world, host, alice, _ = host_gone_fixture(8)
    quit_game(world, 0)                                   # the host goes back to its title screen; its helper keeps running
    took = run_until(world, lambda: alice.popups, 15000, "the host closed the world")
    assert took <= 5000, f"an announced close is noticed within seconds, took {took} ms"
    assert popup_of(alice).body == "mistrimulti/guest_closed_body" and alice.notes == []
    tap_return(world, alice)
    # The host loads a world again (a restart): a guest still in the old copy is sent back as well.
    world, host, alice, _ = host_gone_fixture(9)
    restart(world, 0)
    took = run_until(world, lambda: alice.popups, 15000, "the host restarted the world")
    assert took <= 6000, took
    assert popup_of(alice).body == "mistrimulti/guest_closed_body"
    print("PASS: host quits to its title or restarts the world: the guest is told within seconds and returned to the title")


def test_short_outage_and_waiting_guest_stay():
    world, host, alice, _ = host_gone_fixture(10)
    # A cut shorter than expiry + grace (host and guest keep their worlds): nothing happens afterwards.
    world.net.partition(0, 1)
    world.run(18000)
    assert alice.rt["mask"] & 1 == 0, "the helper expired the host"
    world.net.partition(0, 1, False)
    world.run(40000)
    assert alice.popups == [] and alice.rt["guestsave"]["state"] == "ok" and alice.exits == []
    assert alice.rt["mask"] & 1 == 1
    # A guest that has never seen the host (it started first) waits; it is not sent away.
    P.FILESYSTEMS.clear()
    P.ENGINES.clear()
    P.UIDS.clear()
    P.UIDS[1] = ALICE
    world = World(11, {1: GuestNode})
    world.games[1].feature = GDriver(world.games[1])
    lonely = world.games[1].node
    world.run(70000)
    assert lonely.popups == [] and lonely.notes == [] and lonely.rt["guestsave"]["state"] == "ok"
    print("PASS: an outage shorter than the grace is survived; a guest that never saw its host keeps waiting")


def test_leave_is_safe():
    world, host, alice, _ = host_gone_fixture(12)
    alice.call("mistrimulti_guestsave_leave", "lost")
    alice.call("mistrimulti_guestsave_leave", "closed")
    assert len(alice.popups) == 1, "leaving twice shows one message"
    # If the popup cannot be built the guest still leaves.
    world2, host2, bob, _ = host_gone_fixture(13)
    bob.interp.builtins["popup_creator"] = lambda t, b: (_ for _ in ()).throw(gml.GmlError("no popup menu"))
    bob.call("mistrimulti_guestsave_leave", "lost")
    assert len(bob.fades) == 1, "no message: straight to the fade"
    print("PASS: the disconnect message is shown once, and a failing popup still returns the guest to the title")


# ---- character export and import ----------------------------------------------------------------------------------------------

def export_files(node):
    return {k: v for k, v in node.fs.files.items() if k.startswith("data/exports/")}


def test_export_and_import():
    world, host, alice = ready_pair(14)
    saved = alice.state
    assert len(export_files(alice)) == 1, "the first acknowledged state was exported"
    # More play, flushed by opening the settings menu: the export follows at once (otherwise at most once a minute).
    alice.engine.ari["gold"] = 321
    alice.engine.ari["items_sold"] = gml.GArray([0, 5, 0, 0, 3, 0])
    alice.call("mistrimulti_guestsave_menu_opened", {"menu": None, "kind": SETTINGS})
    world.run(2500)
    ((path, text),) = export_files(alice).items()
    name = path.split("/")[-1]
    export = json.loads(text)
    assert name.endswith(".json") and export["kind"] == "character_export" and export["uid"] == ALICE and export["world"] == WORLD
    assert export["core"] == core_file(host, ALICE) and export["core"]["data"]["gold"] == 321, "the core envelope the host stored"
    host_progress = stored(host, ALICE)
    assert export["progress"]["revision"] == host_progress["revision"]
    assert export["progress"]["data"]["sections"] == host_progress["data"]["sections"], "the progress envelope the host stored"
    # An unacknowledged state is never exported: freeze the host, change something, nothing new is written.
    world.net.partition(0, 1)
    alice.engine.ari["gold"] = 400
    alice.call("mistrimulti_guestsave_menu_opened", {"menu": None, "kind": SETTINGS})
    world.run(3000)
    assert export_files(alice) == {path: text}, "only what the host acknowledged"
    world.net.partition(0, 1, False)
    # Alice becomes the host of her own world: the export goes into it.
    saved = alice.state
    world2 = make_world(15, guests=0, host_uid=ALICE)
    mine = world2.games[0].node
    world2.run(3000)
    assert mine.rt["uid"] == ALICE and mine.rt["world_key"] != WORLD
    mine.fs.files["data/exports/" + name] = text
    before = mine.engine.ari["gold"]
    for bad in ("../" + name, "sub/" + name, "sub\\" + name, "x.txt", "", name + "x", "a..b.json", "c:x.json", None, 5):
        assert mine.call("mistrimulti_guestsave_import", bad) == "Give the file name of an export (no folders).", bad
    assert mine.call("mistrimulti_guestsave_import", "missing.json") == "That export is not for this player."
    assert mine.engine.ari["gold"] == before
    assert mine.call("mistrimulti_guestsave_import", name) == "Character imported. Save the game to keep it."
    assert mine.engine.ari["gold"] == 321
    own = json.loads(mine.fs.files["data/worlds/" + mine.rt["world_key"] + "/players/" + ALICE.replace(":", "_") + ".json"])
    assert own["data"]["world"] == mine.rt["world_key"] and own["data"]["gold"] == 321, "stored under this world's key"
    # Not for somebody else's world, a guest, or a damaged or foreign export.
    world3 = make_world(16, guests=0, host_uid=BOB)
    other = world3.games[0].node
    world3.run(3000)
    other.fs.files["data/exports/" + name] = text
    assert other.call("mistrimulti_guestsave_import", name) == "That export is not for this player."
    assert alice.call("mistrimulti_guestsave_import", name) == "Only the host of a loaded world can import a character."
    broken = json.loads(text)
    broken["core"]["data"]["gold"] = -5
    mine.fs.files["data/exports/broken.json"] = json.dumps(broken)
    gold = mine.engine.ari["gold"]
    assert mine.call("mistrimulti_guestsave_import", "broken.json") == "That export does not fit this version of the game."
    mine.fs.files["data/exports/cut.json"] = text[:200]
    assert mine.call("mistrimulti_guestsave_import", "cut.json") == "That export is not for this player."
    assert mine.engine.ari["gold"] == gold, "a refused import changes nothing"
    print("PASS: export: the acknowledged records as a file (never an unacknowledged state); import: only the host, only the same player, validated first")


def test_import_restores_the_whole_character():
    world, host, alice = ready_pair(17)
    alice.call("mistrimulti_guestsave_menu_opened", {"menu": None, "kind": SETTINGS})
    world.run(2500)
    ((path, text),) = export_files(alice).items()
    name = path.split("/")[-1]
    saved = alice.state
    world2 = make_world(18, guests=0, host_uid=ALICE)
    mine = world2.games[0].node
    world2.run(3000)
    assert mine.state != saved, "a new host world starts with the host's own values"
    mine.fs.files["data/exports/" + name] = text
    assert mine.call("mistrimulti_guestsave_import", name).startswith("Character imported")
    assert mine.state == saved and mine.engine.ari["gold"] == 120 and mine.engine.facts["bob_status"] == "dating"
    print("PASS: import restores the same progress sections and relationships the guest had")


# ---- wiring in MistriMultiBoot.gml ------------------------------------------------------------------------------------------------

def test_wiring():
    boot_text = (GML_DIR / "MistriMultiBoot.gml").read_text(encoding="utf-8")
    guest_text = (GML_DIR / "MistriMultiGuestSave.gml").read_text(encoding="utf-8")
    manifest = (ROOT / "mod/mistrimulti/manifest.toml").read_text(encoding="utf-8")
    declared = set(re.findall(r'"([a-z_]+\.[a-z_]+)"', re.search(r"requires_hooks = \[(.*?)\]", manifest, re.S).group(1)))
    used = set(re.findall(r'mmapi_(?:on|guard|filter|override)\("([a-z_]+\.[a-z_]+)"', guest_text))
    assert used == {"ui.menu_opened", "game.title_entered", "local.missing", "local.get"} and used <= declared, (used - declared)
    for debug in ("mistrimulti.guestsave", "mistrimulti.import_character"):
        assert debug in boot_text
    assert boot_text.count("mistrimulti_guestsave_tick();") == 1 and "mistrimulti_guestsave_register_hooks();" in boot_text
    assert boot_text.index("mistrimulti_character_tick();") < boot_text.index("mistrimulti_guestsave_tick();")
    # The real registrations and the real guard of MistriMultiBoot.gml.
    regs, calls = [], []
    rec = lambda kind: (lambda hook, fn, *a: regs.append((kind, hook, fn.name)))
    notes = []
    state = {"r": None}
    builtins = {
        "mmapi_register": lambda fn: None, "mmapi_filter": rec("filter"), "mmapi_guard": rec("guard"), "mmapi_on": rec("on"),
        "mmapi_override": rec("override"), "mmapi_hotkey_register": lambda *a: None, "mmapi_hotkey_vk_from_name": lambda n: 0,
        "mmapi_hotkey_register_binding": lambda *a: None, "mmapi_mod_data_dir": lambda name: "mod", "mmapi_hotkey_binding_from_name": lambda n: 0,
                "create_notification": notes.append,
        "ANCHOR": GStruct(wrap_for_local=lambda t: t), "MIST": GStruct(is_running=lambda: False), "string_lower": str.lower,
    }
    state.update(mode="join")
    interp = gml.Interpreter(builtins)
    for path in sorted(GML_DIR.glob("*.gml")):
        interp.load(path.read_text(encoding="utf-8"), path.name)
    for name, tag in (("mistrimulti_drops_before_save", "drops"), ("mistrimulti_player_checkpoint", "core"),
                      ("mistrimulti_progress_checkpoint", "progress"), ("mistrimulti_progress_flush_request", "flush_request")):
        interp.functions[name] = (lambda tag: lambda *a: calls.append(tag))(tag)       # record, instead of running the features
    interp.functions["mistrimulti_savespace_mode"] = lambda: state["mode"]              # instead of reading control.json
    space = interp.call("__mistrimulti_savespace")
    space.update(active=True, solo_dir=SOLO_DIR)
    interp.call("mistrimulti_register")
    names = {(kind, hook, fn) for kind, hook, fn in regs}
    for expected in (("guard", "game.save_guard", "mistrimulti_save_guard"),
                     ("on", "ui.menu_opened", "mistrimulti_guestsave_menu_opened"),
                     ("on", "ui.menu_opened", "mistrimulti_menu_opened"),
                     ("on", "game.title_entered", "mistrimulti_guestsave_title_entered"),
                     ("on", "game.title_entered", "mistrimulti_title_entered"),
                     ("filter", "local.missing", "mistrimulti_guestsave_local_missing"),
                     ("filter", "local.get", "mistrimulti_guestsave_local_get"),
                     ("filter", "local.missing", "mistrimulti_local_missing")):
        assert expected in names, expected
    assert {hook for _k, hook, _f in regs} <= declared, {hook for _k, hook, _f in regs} - declared
    rt = interp.call("__mistrimulti_runtime")
    rt.update(enabled=True, mode="join", player_ready=True, player_last_checkpoint=5, progress_checkpointed=5)
    ctx = GStruct(save_path=MP_SAVE)
    assert interp.call("mistrimulti_save_guard", ctx) is False and calls == ["core", "progress"], calls
    assert interp.call("mistrimulti_save_guard", None) is False, "the debug call passes no ctx: still blocked"
    del calls[:]
    rt.update(mode="host")
    state["mode"] = "host"
    assert interp.call("mistrimulti_save_guard", ctx) is None and calls == ["drops", "core", "core", "flush_request"], calls
    assert interp.call("mistrimulti_save_guard", GStruct(save_path=SOLO_SAVE)) is False, "a host never writes the solo folder"
    del calls[:]
    rt.update(enabled=False)
    space["active"] = False
    assert interp.call("mistrimulti_save_guard", GStruct(save_path=SOLO_SAVE)) is None and calls == [], "solo play is untouched"
    # Every user-visible key the file uses has text.
    for key in ("mistrimulti/guest_gone_title", "mistrimulti/guest_lost_body", "mistrimulti/guest_closed_body"):
        assert re.search(r"[a-z]{5}", interp.call("mistrimulti_guestsave_local_missing", None, GStruct(key=key)) or ""), key
        assert key in guest_text
    assert interp.call("mistrimulti_guestsave_local_missing", None, GStruct(key="other/key")) is None
    print("PASS: wiring: the real save guard blocks guests (also without a ctx) and host solo-folder saves; hooks are declared in the manifest")


TESTS = [test_guest_save_is_vetoed, test_save_attempt_sends_character, test_final_flush_on_quit_and_return, test_goodbye_frame,
         test_host_forgets_a_departed_guest, test_returning_through_another_slot_retries,
         test_host_crash_returns_guest_to_title, test_host_closes_or_restarts_the_world, test_short_outage_and_waiting_guest_stay,
         test_leave_is_safe, test_export_and_import, test_import_restores_the_whole_character, test_wiring]


def main():
    wanted = sys.argv[1:]
    for test in TESTS:
        if not wanted or test.__name__ in wanted:
            test()
    print("ALL PASS")


if __name__ == "__main__":
    main()
