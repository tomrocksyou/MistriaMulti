"""A guest's character per world, the character editor flow and its log (MistriMultiCharacter.gml).

    python3 tests/test_guestchar.py            # about 10 seconds; name tests to run only those

MistriMultiCharacter.gml runs unmodified in tests/gml_subset.py together with the real player-sync, progress and identity files, on
the event layer, over the simulated helpers and network of tests/event_sim.py. The game is faked as in tests/test_progress.py (its
engine, file system and record stand-ins are reused); on top of that this file fakes what the editor flow touches: the game's
character editor (start_character_creation and the menu it returns, with a fade-in that can be stopped), the menu list, popups
(MultipleChoicePopup), the default look and name. The player-record capture/restore stand-ins carry the character's name and
look so that the host's file shows which character was stored.

It checks logic and wiring. It does not prove that the real editor opens, is visible or can be finished: docs/PLAYER-DATA.md has
the in-game checklist, and the "Character editor:" lines in the game's log say what happened.
"""
import json
import re
import sys
from pathlib import Path

import gml_subset as gml
from gml_subset import GArray, GStruct
from event_sim import World
import test_progress as P
from test_progress import ALICE, WORLD, core_file, stored, no_errors

ROOT = Path(__file__).resolve().parent.parent
GML_DIR = ROOT / "mod/mistrimulti/gml"
CUSTOMIZATION, POPUP = 5, 6
OLD_LOOK = {"assets": [], "skin_tone": 3, "eyes": 2, "tag": "old install look"}

OVERRIDES = """
function mistrimulti_valid_character(profile) {
    return is_struct(profile) && profile[$ "v"] == 1 && is_string(profile[$ "name"]);
}

function mistrimulti_player_capture() {
    var r = __mistrimulti_runtime();
    var relations = [];
    for (var i = 0; i < NpcId.LEN; i++) {
        array_push(relations, { hearts: NPCS[i].heart_points, status: T2R.read(npc_id_to_string(i) + "_status") ?? "undefined" });
    }
    return { v: 1, uid: r.uid, world: r.world_key, day: string(CALENDAR.time), gold: ARI.gold, relations: relations,
        character: { name: string(ARI.name), look: ARI.animation_assets().serialize() } };
}

function mistrimulti_player_restore(data) {
    var r = __mistrimulti_runtime();
    if (!mistrimulti_player_valid(data, r.uid, r.world_key)) return false;
    ARI.gold = data.gold;
    ARI.name = data.character.name;
    for (var i = 0; i < NpcId.LEN; i++) {
        NPCS[i].heart_points = data.relations[i].hearts;
        T2R.write(npc_id_to_string(i) + "_status", data.relations[i].status);
    }
    r.character_owner = ARI;
    r.character_pending = false;
    r.character_phase = "done";
    r.character_loaded = true;
    mistrimulti_progress_core_ready();
    return true;
}
"""


class Preset:
    """The game's PlayerAnimationAssets as far as the character code uses it."""

    def __init__(self, tag):
        self.tag = tag
        self.struct = GStruct(tag=tag, serialize=lambda: GStruct(assets=GArray(), skin_tone=0, eyes=0, tag=tag),
                              clone=lambda: Preset(tag + " (clone)").struct)


class Menu:
    """The character editor the game would build: it fades in from alpha 0 unless the test stops the fade."""

    def __init__(self, node, preset, callback):
        self.node, self.callback, self.preset = node, callback, preset
        self.alpha = 0.0
        self.labels = []
        self.locked = []
        self.struct = GStruct(
            type=CUSTOMIZATION, data=GStruct(pause=0), hide_requests=0, close_requested=False, internal_chain=None,
            canvas=GStruct(get_alpha=lambda: self.alpha), listen_for_exit_flag=True,
            continue_button=GStruct(text_label=GStruct(set_key=self.labels.append)),
            farm_field=GStruct(set_unlocked=self.locked.append), request_show=self.request_show, close=self.close)

    def request_show(self, frames):
        self.node.shows.append(frames)
        self.alpha = 1.0

    def close(self):
        if self.struct in self.node.menus:
            self.node.menus.remove(self.struct)

    def tap_continue(self):
        """What the game's Continue button does: the callback, then the menu closes."""
        self.node.interp.call_value(self.callback, [], 0)
        self.close()


class CharNode(P.ProgressNode):
    extra_files = P.ProgressNode.extra_files + ("MistriMultiCharacter.gml",)

    def builtins(self):
        b = super().builtins()
        self.menus, self.mcps, self.editors, self.shows, self.updates = [], [], [], [], 0
        self.fade = True              # the editor fades in; a test sets it False to keep the editor invisible
        self.open_fails = 0           # start_character_creation throws this many times
        self.build_fails = False      # build_obj_ari_par_from throws
        self.popups_open = 0
        self.presets = [Preset("host look")]
        ari = self.engine.ari
        ari.update(name="Host", pronouns=GStruct(eng="they"), birthday=111, end_of_day_status=None, preset_index_selected=0,
                   presets=GStruct(set=self.set_preset, get=lambda i: self.presets[int(i)]),
                   animation_assets=lambda: self.presets[0].struct if isinstance(self.presets[0], Preset) else self.presets[0],
                   deserialize_pronouns=lambda p: ari.__setitem__("pronouns", p))
        self.presets[0] = self.presets[0].struct
        b.update({
            "ANCHOR": GStruct(open_menus=GStruct(count=lambda: len(self.menus), get=lambda i: self.menus[int(i)]),
                              get_menu=self.get_menu, popup_is_open=lambda: self.popups_open > 0),
            "Menu": GStruct(Customization=CUSTOMIZATION), "PauseStatus": GStruct(EMPTY=0),
            "start_character_creation": self.start_editor, "MultipleChoicePopup": self.mcp,
            "mistrimulti_menu_t": lambda text: text, "create_default_player_animation_assets": lambda: Preset("default").struct,
            "default_pronouns": lambda: GStruct(eng="default"), "local_set_pronouns": lambda p: None, "DEFAULT_ARI_BIRTHDAY": 42,
            "build_obj_ari_par_from": self.build_par, "mistrimulti_update_look": self.count_update,
            "string_copy": lambda s, start, n: s[int(start) - 1:int(start) - 1 + int(n)], "PAUSE_STATUS": 0,
            "LOAD_SEQUENCE": GStruct(is_active=lambda: False), "mmapi_log_flush": lambda m: None,
            "mistrimulti_event_blobs_pending": lambda: 0,
        })
        return b

    def count_update(self):
        self.updates += 1

    def build_par(self, preset):
        if self.build_fails:
            raise gml.GmlError("no outfit")

    def set_preset(self, index, preset):
        self.presets[int(index)] = preset

    def get_menu(self, kind):
        return next((m for m in self.menus if m["type"] == kind), None)

    def start_editor(self, preset, callback, creation):
        if self.open_fails > 0:
            self.open_fails -= 1
            raise gml.GmlError("canvas missing")
        menu = Menu(self, preset, callback)
        self.editors.append(menu)
        self.menus.append(menu.struct)
        return menu.struct

    def mcp(self, title):
        popup = Choice(self, title)
        self.mcps.append(popup)
        self.popups_open += 1
        return popup.struct

    def setup(self):
        super().setup()
        self.interp.load(OVERRIDES, "overrides")
        self.rt.update(character_phase="", character_ask=None, character_entry="load", character_menu=None, character_preset=None,
                       character_ready_ticks=0, character_path="data/characters/" + self.rt["uid"].replace(":", "_") + ".json")

    # -- what the tests look at ---------------------------------------------------------------------------------------------------
    def log(self, needle=""):
        return [w for w in self.warnings if isinstance(w, str) and w.startswith("Character editor:") and needle in w]

    @property
    def editor(self):
        return self.editors[-1] if self.editors and self.editors[-1].struct in self.menus else None

    def question(self):
        return next((m for m in self.mcps if m.open), None)


class Choice:
    """MultipleChoicePopup: a title and options; tapping one closes the popup and runs its callback."""

    def __init__(self, node, title):
        self.node, self.title, self.options, self.open = node, title, [], True
        self.struct = GStruct(option=self.option)

    def option(self, label, callback, args):
        self.options.append((label, callback, args))
        return self.struct

    def tap(self, label):
        for name, callback, args in self.options:
            if name == label:
                self.open = False
                self.node.popups_open -= 1
                self.node.interp.call_value(callback, list(args), 0)
                return
        raise AssertionError(f"no option {label} in {[o[0] for o in self.options]}")

    def close_unanswered(self):
        self.open = False
        self.node.popups_open -= 1


class CharDriver(P.Driver):
    """P.Driver plus what MistriMultiBoot.gml's tick does for the character: three 60 Hz ticks per 20 Hz step."""

    def tick(self, now):
        super().tick(now)
        if not self.running:
            return
        node = self.node
        for _ in range(3):
            node.interp.call("mistrimulti_character_tick")
            editor = node.editor
            if editor is not None and node.fade and editor.alpha < 1:
                editor.alpha = min(1.0, editor.alpha + 1 / 30)


def make_world(seed, guests=1, **faults):
    P.FILESYSTEMS.clear()
    P.ENGINES.clear()
    P.UIDS.clear()
    P.UIDS[1], P.UIDS[2], P.UIDS[3] = ALICE, P.BOB, P.CAROL
    world = World(seed, {i: CharNode for i in range(guests + 1)}, **faults)
    for game in world.games.values():
        game.feature = CharDriver(game)
    return world


def restart(world, slot, entry):
    """The game of one player is closed and started again (its files stay), entering through New Game or Load Game."""
    P.ENGINES.pop(slot, None)
    game = world.start(slot)
    game.feature = CharDriver(game)
    game.node.rt["character_entry"] = entry
    return game.node


def run_until(world, condition, limit_ms, what):
    start = world.clock.ms
    while not condition():
        if world.clock.ms - start > limit_ms:
            raise AssertionError(f"timed out after {limit_ms} ms: {what}")
        world.run(100)


def finish(world, guest, name="Alice the second"):
    """The guest edits the name and taps Continue; the checkpoint reaches the host."""
    run_until(world, lambda: guest.editor is not None and guest.editor.alpha >= 1, 20000, "the editor is shown")
    guest.engine.ari["name"] = name
    guest.editor.tap_continue()
    run_until(world, lambda: guest.rt["player_revision"] == guest.rt["player_saved_revision"] > 0 and guest.rt["progress_revision"] == guest.rt["progress_saved_revision"] > 0,
              20000, "the new character is stored on the host")


def first_world(seed, entry="new", **faults):
    """A host and a guest who joins a world it has no character in, and makes one (named 'Alice the first')."""
    world = make_world(seed, **faults)
    host, alice = world.games[0].node, world.games[1].node
    alice.rt["character_entry"] = entry
    # This install made another character in another world before: its local file must not decide anything.
    alice.fs.files[alice.rt["character_path"]] = json.dumps({"v": 1, "uid": ALICE, "name": "Old install name", "look": OLD_LOOK})
    run_until(world, lambda: alice.rt["player_ready"], 30000, "the guest's records are in")
    finish(world, alice, "Alice the first")
    return world, host, alice


def host_name(host):
    return core_file(host, ALICE)["data"]["character"]["name"]


def host_file(host, name):
    return P.plain(host, "players/" + ALICE.replace(":", "_") + name)


# ---- tests --------------------------------------------------------------------------------------------------------------------

def test_new_world_starts_fresh():
    for entry in ("new", "load"):
        world = make_world(1)
        host, alice = world.games[0].node, world.games[1].node
        alice.rt["character_entry"] = entry
        alice.fs.files[alice.rt["character_path"]] = json.dumps({"v": 1, "uid": ALICE, "name": "Old install name", "look": OLD_LOOK})
        # The game loaded the host's save: the guest's ARI starts as the host's character.
        assert alice.engine.ari["name"] == "Host"
        run_until(world, lambda: alice.editor is not None, 30000, f"the editor opens ({entry})")
        editor = alice.editor
        assert editor.preset["tag"] == "default", "the game's default look, not the host's and not the install's old character"
        assert alice.engine.ari["name"] == "Guest" and alice.engine.ari["birthday"] == 42 and alice.engine.ari["pronouns"]["eng"] == "default"
        assert alice.rt["character_pending"] is True and editor.labels == ["misc_local/continue"] and editor.locked == [False]
        assert alice.rt["character_phase"] == "edit" and alice.question() is None, "no question: the world has no record of this identity"
        assert core_file(host, ALICE) is None, "nothing is stored before the editor is finished"
        world.run(3000)
        assert alice.rt["character_pending"] is True and core_file(host, ALICE) is None and len(alice.editors) == 1
        finish(world, alice, "Alice the first")
        assert alice.rt["character_pending"] is False and alice.rt["character_phase"] == "done" and alice.editor is None
        assert host_name(host) == "Alice the first" and alice.updates == 1
        local = json.loads(alice.fs.files[alice.rt["character_path"]])
        assert local["name"] == "Alice the first", "the install's last-character copy follows the newest character"
        steps = [s for s in ("opening", "opened", "shown", "Continue tapped", "complete") if alice.log(s)]
        assert steps == ["opening", "opened", "shown", "Continue tapped", "complete"], alice.log()
        no_errors(world)
    print("PASS: a world that is new to the guest: the editor opens from the game's defaults (never the install's old character), nothing is stored until Continue, then the host has the new character")


def test_same_world_again_has_no_editor():
    world, host, alice = first_world(2)
    alice = restart(world, 1, "load")                 # Load Game > Multiplayer
    alice.fs.files.pop(alice.rt["character_path"], None)
    run_until(world, lambda: alice.rt["player_ready"], 30000, "the guest is ready again")
    world.run(3000)
    assert alice.editors == [] and alice.question() is None, "a returning guest sees neither the editor nor a question"
    assert alice.engine.ari["name"] == "Alice the first" and alice.rt["character_pending"] is False
    assert alice.rt["character_phase"] == "done" and alice.log() == []
    no_errors(world)
    print("PASS: Load Game into a world the guest has a character in: the host's record is restored, no editor, no question")


def test_new_game_into_a_world_with_a_character_asks():
    world, host, alice = first_world(3)
    # The old character has something the new one must not inherit.
    path = "data/worlds/" + WORLD + "/players/" + ALICE.replace(":", "_") + ".progress.json"
    record = json.loads(host.fs.files[path])
    record["data"]["sections"]["almanac"]["sold"]["carrot"] = 7
    host.fs.files[path] = json.dumps(record)
    old_core, old_progress = host_file(host, ".json"), host_file(host, ".progress.json")
    # Keep mine.
    alice = restart(world, 1, "new")
    run_until(world, lambda: alice.question() is not None, 30000, "the question")
    q = alice.question()
    assert [o[0] for o in q.options] == ["Keep mine", "New character"] and all(len(o[0]) <= 18 for o in q.options)
    assert alice.rt["character_pending"] is True and alice.editors == [] and alice.rt["player_ready"] is False
    world.run(3000)
    assert alice.question() is q and len(alice.mcps) == 1, "asked once"
    assert host_file(host, ".json") == old_core, "nothing on the host changes before the answer"
    q.tap("Keep mine")
    run_until(world, lambda: alice.rt["player_ready"], 30000, "the old character is restored")
    world.run(2000)
    assert alice.editors == [] and alice.engine.ari["name"] == "Alice the first" and alice.rt["character_pending"] is False
    assert alice.state["almanac"]["sold"]["carrot"] == 7, "Keep mine restores everything of the old character"
    assert host_file(host, ".replaced.json") is None and host_name(host) == "Alice the first"
    assert alice.log("keep the existing") and not alice.log("opening")
    # New character: the old record stays until the new one is saved, and a copy is kept next to it.
    alice = restart(world, 1, "new")
    run_until(world, lambda: alice.question() is not None, 30000, "the question again")
    alice.question().tap("New character")
    run_until(world, lambda: alice.editor is not None, 30000, "the editor")
    assert alice.editor.preset["tag"] == "default" and alice.engine.ari["name"] == "Guest", "a new character starts from the defaults"
    assert alice.rt["player_ready"] is True and alice.rt["character_phase"] == "edit"
    assert host_file(host, ".json") == old_core and host_file(host, ".progress.json") == old_progress, "still the old records while the editor is open"
    assert host_file(host, ".replaced.json") == old_core and host_file(host, ".progress.replaced.json") == old_progress
    world.run(8000)
    assert host_file(host, ".json") == old_core and alice.rt["character_pending"] is True, "waiting for the editor changes nothing"
    finish(world, alice, "Alice the third")
    assert host_name(host) == "Alice the third" and host_file(host, ".json.bak")["data"]["character"]["name"] == "Alice the first"
    assert host_file(host, ".replaced.json") == old_core, "the replaced record is kept"
    new_progress = host_file(host, ".progress.json")
    assert new_progress["revision"] == 1 and new_progress["data"]["sections"]["almanac"]["sold"].get("carrot") != 7
    assert alice.state["almanac"]["sold"].get("carrot") != 7, "the new character has none of the old character's progress"
    assert host_file(host, ".progress.replaced.json")["data"]["sections"]["almanac"]["sold"]["carrot"] == 7
    # ... and from now on the new character is the one that comes back.
    alice = restart(world, 1, "load")
    run_until(world, lambda: alice.rt["player_ready"], 30000, "ready")
    world.run(2000)
    assert alice.engine.ari["name"] == "Alice the third" and alice.editors == []
    no_errors(world)
    print("PASS: New Game into a world with a character asks (Keep mine / New character, labels under 18 characters); the old records stay until the new ones are saved and a copy is kept")


def test_new_game_without_a_character_has_no_question():
    world = make_world(4)
    alice = world.games[1].node
    alice.rt["character_entry"] = "new"
    run_until(world, lambda: alice.editor is not None, 30000, "the editor")
    assert alice.mcps == [] and alice.rt["character_phase"] == "edit"
    print("PASS: New Game into a world without a character of the guest: straight to the editor, no question")


def test_question_closed_without_answer_is_asked_again():
    world, host, alice = first_world(5)
    alice = restart(world, 1, "new")
    run_until(world, lambda: alice.question() is not None, 30000, "the question")
    alice.question().close_unanswered()
    run_until(world, lambda: alice.question() is not None, 10000, "asked again")
    assert len(alice.mcps) == 2 and alice.log("closed without an answer") and alice.rt["character_pending"] is True
    alice.question().tap("Keep mine")
    run_until(world, lambda: alice.rt["player_ready"], 30000, "restored")
    # An answer to a question of an earlier session is ignored.
    stale = restart(world, 1, "new")
    run_until(world, lambda: stale.question() is not None, 30000, "question")
    old = stale.question()
    stale.rt["epoch"] = "other"
    old.tap("New character")
    assert stale.log("old question") and stale.rt["character_phase"] == "ask"
    print("PASS: a question closed without an answer is asked again; an answer to an old question is ignored")


def test_editor_closed_without_continue_opens_again():
    world = make_world(6)
    alice, host = world.games[1].node, world.games[0].node
    run_until(world, lambda: alice.editor is not None, 30000, "the editor")
    run_until(world, lambda: alice.log("shown"), 10000, "shown")
    first = alice.editor
    first.close()                                    # a menu shutdown, not Continue
    run_until(world, lambda: alice.editor is not None and alice.editor is not first, 10000, "the editor opens again")
    assert alice.log("closed without Continue") and len(alice.log("opening")) == 2
    assert alice.rt["character_pending"] is True and alice.engine.ari["name"] == "Guest"
    # The guest does not take part in the world meanwhile: pending withholds presence and checkpoints.
    assert core_file(host, ALICE) is None
    edited = alice.editor.preset
    alice.editor.close()
    run_until(world, lambda: len(alice.editors) == 3, 10000, "and again")
    assert alice.editors[2].preset is edited, "the look being made is kept when the editor reopens"
    finish(world, alice)
    assert alice.rt["character_pending"] is False and host_name(host) == "Alice the second"
    print("PASS: an editor closed without Continue is logged and opens again with the same look; a guest cannot finish without it")


def test_invisible_editor_is_shown_and_logged():
    world = make_world(7)
    alice = world.games[1].node
    alice.fade = False                               # the fade-in never runs
    run_until(world, lambda: alice.editor is not None, 30000, "the editor")
    world.run(2000)
    assert alice.shows == [] and alice.log("still not visible") == []
    world.run(3000)
    assert alice.shows == [0], "after 3 seconds it is shown at once, once"
    line = alice.log("still not visible")[0]
    assert "alpha=0" in line and "hide_requests=0" in line and "pause_status=0" in line and "load_sequence=0" in line, line
    run_until(world, lambda: alice.log("shown after"), 3000, "then it counts as shown")
    world.run(5000)
    assert alice.shows == [0] and len(alice.log("not visible")) == 1
    print("PASS: an editor that stays invisible is logged with its state and shown at once after 3 seconds")


def test_failures_are_logged_and_retried():
    world = make_world(8)
    alice, host = world.games[1].node, world.games[0].node
    alice.open_fails = 2
    run_until(world, lambda: alice.log("could not be opened"), 30000, "first failure")
    assert "canvas missing" in alice.log("could not be opened")[0] and alice.editors == []
    start = world.clock.ms
    run_until(world, lambda: alice.editor is not None, 40000, "opened after the failures")
    assert len(alice.log("could not be opened")) == 2 and world.clock.ms - start >= 5000, "a failed open waits 5 seconds"
    assert alice.rt["character_pending"] is True
    # Completing fails: the guest stays pending and the editor comes back.
    alice.build_fails = True
    alice.editor.tap_continue()
    assert alice.log("completing failed") and "no outfit" in alice.log("completing failed")[0]
    assert alice.rt["character_pending"] is True and alice.rt["character_phase"] == "edit"
    run_until(world, lambda: alice.editor is not None, 10000, "the editor again")
    alice.build_fails = False
    finish(world, alice)
    assert host_name(host) == "Alice the second"
    # A step that throws is logged with its reason and the next tick tries again.
    alice.rt["character_owner"] = None
    alice.engine.ari["end_of_day_status"] = 1
    alice.interp.builtins["MIST"] = GStruct(is_running=lambda: (_ for _ in ()).throw(gml.GmlError("mist broke")))
    alice.rt["character_pending"] = True
    alice.call("mistrimulti_character_tick")
    assert any("mist broke" in str(w) for w in alice.warnings + world.games[1].warnings), "the reason is logged"
    print("PASS: a failing editor open or completion is logged with its reason, the guest stays pending, the editor opens again")


def test_record_during_editing_is_ignored():
    world, host, alice = first_world(9)
    alice = restart(world, 1, "new")
    run_until(world, lambda: alice.question() is not None, 30000, "question")
    alice.question().tap("New character")
    run_until(world, lambda: alice.editor is not None, 30000, "editor")
    saved = host.call("mistrimulti_player_load", ALICE)
    meta = {"peer_epoch": alice.rt["epoch"], "uid": ALICE, "world": WORLD, "revision": saved["revision"]}
    assert alice.call("mistrimulti_player_receive_record", 0, False, json.dumps(gml.to_python(saved["data"]) if hasattr(gml, "to_python") else json.loads(gml.to_json(saved["data"]))), meta) is True
    assert alice.engine.ari["name"] == "Guest" and alice.rt["character_pending"] is True and alice.log() and any("is ignored" in str(w) for w in alice.warnings)
    print("PASS: a saved record that arrives while the new character is being made is ignored")


def test_forged_choices_are_ignored():
    world, host, alice = first_world(10)
    bob_slot = None
    before = (host_file(host, ".json"), host_file(host, ".progress.json"))
    alice = restart(world, 1, "load")
    run_until(world, lambda: alice.rt["player_ready"], 30000, "ready")
    # A choice without a question, with a wrong world, a wrong identity or a bad value: nothing happens.
    for data in ({"world": WORLD, "uid": ALICE, "keep": 0}, {"world": "w", "uid": ALICE, "keep": 0},
                 {"world": WORLD, "uid": P.BOB, "keep": 0}, {"world": WORLD, "uid": ALICE, "keep": "0"}, {"world": WORLD, "uid": ALICE}):
        alice.call("mistrimulti_event_emit", "profile_choice", data, 0)
    world.run(4000)
    assert host_file(host, ".replaced.json") is None and (host_file(host, ".json"), host_file(host, ".progress.json")) == before
    assert host.rt["player_sessions"][1]["replaced"] is False
    no_errors(world)
    print("PASS: a choice that was not asked for, or is malformed or forged, changes nothing on the host")


# ---- the entry path (MistriMultiSaveSpace.gml, MistriMultiBoot.gml) ------------------------------------------------------------

def test_entry_path():
    save = (GML_DIR / "MistriMultiSaveSpace.gml").read_text(encoding="utf-8")
    boot = (GML_DIR / "MistriMultiBoot.gml").read_text(encoding="utf-8")
    sent = []
    builtins = {"mmapi_log_info": lambda *a: None, "mmapi_log_error": lambda *a: None, "mmapi_log_flush": lambda *a: None,
                "mistrimulti_data_dir": lambda: "data", "file_exists": lambda p: False}
    interp = gml.Interpreter(builtins)
    interp.load(save, "MistriMultiSaveSpace.gml")
    for name, fn in (("mistrimulti_savespace_try_set", lambda multiplayer: True), ("mistrimulti_savespace_mode", lambda: "join"),
                     ("mistrimulti_savespace_enter_multiplayer", lambda arg: sent.append(("new", arg))),
                     ("mistrimulti_menu_title_entered", lambda: None), ("mistrimulti_savespace_rebuild_menu", lambda: None),
                     ("mistrimulti_menu_send", lambda *a: None)):
        interp.functions[name] = fn
    space = interp.call("__mistrimulti_savespace")
    space.update(orig_transition_to=lambda target: sent.append(("load", target)), solo_dir="solo")
    assert space["entry"] == ""
    interp.builtins["Menu"] = GStruct(Load=9)
    interp.call("mistrimulti_savespace_enter", "new", "state")
    assert space["entry"] == "new" and space["mode"] == "join" and sent == [("new", "state")]
    interp.call("mistrimulti_savespace_enter", "load", None)
    assert space["entry"] == "load" and sent[-1] == ("load", 9), sent
    interp.builtins["__mistrimulti_runtime"] = lambda: GStruct(enabled=True, initialized=True)
    interp.call("mistrimulti_title_entered", GStruct())
    assert space["entry"] == "" and space["mode"] == "", "a session that ended forgets how it was entered"
    # The runtime reads the entry once, before the session starts, and sends it with the profile request.
    assert re.search(r'r\.character_entry = __mistrimulti_savespace\(\)\[\$ "entry"\] == "new" \? "new" : "load";', boot)
    sync = (GML_DIR / "MistriMultiPlayerSync.gml").read_text(encoding="utf-8")
    assert 'intent: r[$ "character_entry"] ?? "load"' in sync
    print("PASS: the entry path: New Game and Load Game record how the multiplayer world was entered; it is cleared when the session ends and sent to the host")


def test_no_ghosts_while_the_guest_is_not_playing():
    """The real log showed the host's ghost created, hidden and destroyed on every read while the guest loaded (an editor or records pending)."""
    boot = (GML_DIR / "MistriMultiBoot.gml").read_text(encoding="utf-8")
    peers = []
    files = {"bridge/rx_0.json": json.dumps({"v": 2, "id": 0, "epoch": "e", "active": True, "room": "farm", "x": 1, "y": 1, "c": 0, "ba": 0, "uid": "x"})}
    builtins = {"instance_exists": lambda o: True, "obj_ari": 1, "ARI": GStruct(), "GRID": GStruct(),
                "file_exists": lambda p: p in files, "try_read_json_file": lambda p: gml.from_json(json.loads(files[p])),
                "Cardinal": GStruct(LEN=4), "AnimationName": GStruct(LEN=20), "abs": abs}
    interp = gml.Interpreter(builtins)
    interp.load(boot, "MistriMultiBoot.gml")
    rt = interp.call("__mistrimulti_runtime")
    rt.update(id=1, mask=1, peer_epoch=GArray([""] * 8), peers=GArray([None] * 8), bridge="bridge")
    for name, tag in (("mistrimulti_update_peer", "show"), ("mistrimulti_hide_peer", "hide"), ("mistrimulti_events_receive", None),
                      ("mistrimulti_remember_peer", None)):
        interp.functions[name] = (lambda tag: lambda *a: peers.append((tag, a[0])) if tag else None)(tag)
    for pending, ready, settled, expect in ((True, True, True, "hide"), (False, False, True, "hide"), (False, True, False, "hide"), (False, True, True, "show")):
        del peers[:]
        rt.update(character_pending=pending, player_ready=ready, room_settled=settled)
        interp.call("mistrimulti_read_peers")
        assert ("show" in [p[0] for p in peers]) == (expect == "show"), (pending, ready, settled, peers)
    print("PASS: the other players' characters are created only once this guest is playing (not while its editor or records are pending)")


def test_wiring():
    boot = (GML_DIR / "MistriMultiBoot.gml").read_text(encoding="utf-8")
    manifest = (ROOT / "mod/mistrimulti/manifest.toml").read_text(encoding="utf-8")
    declared = set(re.findall(r'"([a-z_]+\.[a-z_]+)"', re.search(r"requires_hooks = \[(.*?)\]", manifest, re.S).group(1)))
    used = set()
    for path in ("MistriMultiCharacter.gml", "MistriMultiPlayerSync.gml"):
        used |= set(re.findall(r'mmapi_(?:on|guard|filter|override)\("([a-z_]+\.[a-z_]+)"', (GML_DIR / path).read_text(encoding="utf-8")))
    assert used <= declared
    assert "mistrimulti_character_tick();" in boot and 'mmapi_debug_register_fn("mistrimulti.character"' in boot
    sync = (GML_DIR / "MistriMultiPlayerSync.gml").read_text(encoding="utf-8")
    for kind in ("profile_exists", "profile_choice"):
        assert f'mistrimulti_event_register("{kind}", plain);' in sync
    print("PASS: wiring: events registered, character tick and debug call present, no new hooks")


TESTS = [test_new_world_starts_fresh, test_same_world_again_has_no_editor, test_new_game_into_a_world_with_a_character_asks,
         test_new_game_without_a_character_has_no_question, test_question_closed_without_answer_is_asked_again,
         test_editor_closed_without_continue_opens_again, test_invisible_editor_is_shown_and_logged,
         test_failures_are_logged_and_retried, test_record_during_editing_is_ignored, test_forged_choices_are_ignored,
         test_entry_path, test_no_ghosts_while_the_guest_is_not_playing, test_wiring]

if __name__ == "__main__":
    wanted = sys.argv[1:]
    for test in TESTS:
        if wanted and test.__name__ not in wanted and test.__name__[5:] not in wanted:
            continue
        test()
    print("ALL PASS")
