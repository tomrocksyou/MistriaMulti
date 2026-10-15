"""The other players' markers on the Journal map, kept live while the map is open (MistriMultiMapLive.gml).

    python3 tests/test_maplive.py [test_name ...]

MistriMultiMapLive.gml runs unmodified in tests/gml_subset.py. Only the engine is stubbed: `Map` models MapMenu.gml (the tabs, the
hubs of each page, find_hub_for with the game's own rules, select_location rebuilding every icon and hub node), ANCHOR's list of
open menus and the sprite nodes the markers are made of. The test drives mistrimulti_map_tick the way the mod tick does (60 times
a second) and counts how often the map is rebuilt and the peers are looked at, so that "live" and "cheap" are both checked.
This checks the logic and the wiring; whether the real game draws the markers, and the hook order, is for the in-game
checklist (docs/SYNC-MAPLIVE.md).
"""
import sys
import types
from pathlib import Path

from event_sim import Clock, GmlNode
import gml_subset as gml
from gml_subset import GArray, GStruct as S, GmlError

ROOT = Path(__file__).resolve().parent.parent
FARM, TOWN, BEACH, DUNGEON, LEN = 0, 1, 2, 3, 4
NAMES = {"farm": FARM, "town": TOWN, "beach": BEACH, "dungeon": DUNGEON}
POSITION, LOCATIONS = 0, 1
MENU_MAP, MENU_OTHER = 9, 3
PLAYER_ICON, NPC_ICON = "player_icon", "npc_icon"


def hub(kind, x, y, ax, ay, locations=()):
    return S(type=kind, x=x, y=y, asset_x=ax, asset_y=ay, locations=GArray(locations), node=None)


def make_hubs():
    return GArray([
        GArray([hub(POSITION, 100, 100, 10, 10), hub(POSITION, 400, 100, 50, 10)]),         # the farm page: two places
        GArray([hub(LOCATIONS, 0, 0, 20, 20, [TOWN]), hub(POSITION, 0, 0, 70, 70)]),        # town: one hub for the whole town
        GArray([hub(LOCATIONS, 0, 0, 30, 30, [BEACH])]),
        None,                                                                                # the dungeon has no page
    ])


class Sprite:
    """ANCHOR.sprite(parent): chainable setters that record what the marker looks like."""

    def __init__(self, parent):
        self.s = S(sprite=None, x=0, y=0, alpha=1)
        parent["children"].append(self.s)
        for name, fields in (("set_sprite", ("sprite",)), ("set_xy", ("x", "y")), ("set_alpha", ("alpha",)),
                             ("set_speed", ("speed",))):
            self.s[name] = self.setter(fields)

    def setter(self, fields):
        def f(*a):
            for k, v in zip(fields, a):
                self.s[k] = v
            return self.s
        return f


class Map:
    """MapMenu.gml's menu: select_location rebuilds everything and puts the game's own icon on the first hub."""

    def __init__(self, world, start=FARM):
        self.world = world
        self.rebuilds = 0
        self.find_calls = 0
        self.broken = False
        self.menu = S(type=MENU_MAP, free_requested=False, selected_location_id=None, find_hub_for=self.find_hub_for)
        self.menu["select_location"] = self.select_location
        self.select_location(start)

    def select_location(self, loc):
        if self.broken:
            raise GmlError("select_location failed")
        self.rebuilds += 1
        self.menu["selected_location_id"] = loc
        for h in self.world.hubs[loc]:
            h["node"] = S(children=GArray())
        # the game's own icon (Ari) on the first hub
        Sprite(self.world.hubs[loc][0]["node"]).s["set_sprite"](NPC_ICON)

    def find_hub_for(self, hubs, lp, queue, shown):
        self.find_calls += 1
        for h in hubs:
            if h["type"] == POSITION:
                if lp["location_id"] == shown:
                    queue.append((h, -((h["x"] - lp["pos"]["x"]) ** 2 + (h["y"] - lp["pos"]["y"]) ** 2) ** 0.5))
            elif lp["location_id"] in h["locations"]:
                queue.append((h, 0))
        if not queue:
            return 0
        best = max(queue, key=lambda t: t[1])[0]
        queue.clear()
        return best


class MapNode(GmlNode):
    extra_files = ("MistriMultiMapLive.gml",)

    def builtins(self):
        self.world = types.SimpleNamespace(hubs=make_hubs())
        self.open_menus = []
        self.maps = []
        w = self

        def string_to_location_id(text):
            if text not in NAMES:
                raise GmlError("unknown location " + text)
            return NAMES[text]

        def priority_create():
            return []

        return {
            "Menu": S(Map=MENU_MAP), "MAP_HUBS": self.world.hubs, "LocationId": S(Farm=FARM, Town=TOWN, Beach=BEACH, Dungeon=DUNGEON, LEN=LEN),
            "string_to_location_id": string_to_location_id,
            "string_split": lambda s, sep: GArray(s.split(sep)),
            "LocationPosition": lambda loc, pos: S(location_id=loc, pos=pos),
            "Vec2": lambda x, y: S(x=x, y=y),
            "ds_priority_create": priority_create, "ds_priority_destroy": lambda q: None,
            "spr_ui_generic_icon_npc_small_player": PLAYER_ICON,
            "ANCHOR": S(sprite=lambda parent: Sprite(parent).s,
                        open_menus=S(contains=lambda m: any(m is o for o in w.open_menus))),
        }

    def setup(self):
        self.rt.update(enabled=True, mask=0b111)

    # -- helpers --
    def open_map(self, start=FARM):
        m = Map(self.world, start)
        self.maps.append(m)
        self.open_menus.append(m.menu)
        self.call("mistrimulti_map_opened", S(kind=MENU_MAP, menu=m.menu))
        return m

    def close(self, m, how="list"):
        if how == "list":
            self.open_menus[:] = [o for o in self.open_menus if o is not m.menu]
        else:
            m.menu["free_requested"] = True

    def peer(self, slot, room="farm:undefined", x=100, y=100, **extra):
        p = S(active=True, room=room, x=x, y=y)
        p.update(extra)
        self.rt["peers"][slot] = p
        return p

    def ticks(self, n):
        for _ in range(n):
            self.rt["ticks"] += 1
            self.call("mistrimulti_map_tick")

    def markers(self, loc=None):
        """{hub (asset_x, asset_y): [marker x offsets]} of the player icons on the shown page."""
        out = {}
        for h in self.world.hubs[loc if loc is not None else self.maps[-1].menu["selected_location_id"]]:
            xs = [c["x"] for c in h["node"]["children"] if c["sprite"] == PLAYER_ICON]
            if xs:
                out[(h["asset_x"], h["asset_y"])] = xs
        return out


def new_node():
    log = []
    node = MapNode(0, "abcdef0123", Clock(), lambda *a: log.append(a))
    node.log = log
    return node


FIELD, HOUSE = (10, 10), (50, 10)


# ---- scenarios --------------------------------------------------------------------------------------------------

def test_markers_on_open():
    n = new_node()
    n.peer(1, x=110, y=90)                          # next to the first hub
    n.peer(2, x=390, y=100, alpha=1)                # next to the second
    m = n.open_map()
    assert n.markers() == {FIELD: [-5], HOUSE: [-5]}, n.markers()
    icon = [c for c in n.world.hubs[FARM][0]["node"]["children"] if c["sprite"] == PLAYER_ICON][0]
    assert icon["alpha"] == 0.8 and icon["y"] == -16
    # the game's own icon is still there (the wrapper runs the original first)
    assert any(c["sprite"] == NPC_ICON for c in n.world.hubs[FARM][0]["node"]["children"])
    # two players on one hub sit side by side
    n.peer(2, x=120, y=100)
    m.menu["select_location"](FARM)
    assert n.markers() == {FIELD: [-5, 6]}, n.markers()
    # not in the session mask, inactive, ourselves: no marker
    n.rt["mask"] = 0b011
    n.peer(0, x=100, y=100)
    m.menu["select_location"](FARM)
    assert n.markers() == {FIELD: [-5]}, n.markers()
    n.peer(1, active=False)
    m.menu["select_location"](FARM)
    assert n.markers() == {}
    print("PASS: markers: placed on the nearest hub when the map opens and on every tab change, side by side, "
          "own icon kept, masked / inactive / own slot left out")


def test_live_update():
    n = new_node()
    n.peer(1, x=100, y=100)
    m = n.open_map()
    assert n.markers() == {FIELD: [-5]}
    # Walking inside one hub: the picture is the same, so the map is not rebuilt.
    base = m.rebuilds
    for i in range(10):
        n.peer(1, x=100 + 12 * i, y=100)
        n.ticks(30)
    assert m.rebuilds == base, "rebuilt for a move that changes nothing"
    # Crossing to the other hub: the marker follows within half a second.
    n.peer(1, x=400, y=100)
    n.ticks(29)
    assert n.markers() == {FIELD: [-5]}, "updated off the refresh beat"
    n.ticks(1)
    assert n.markers() == {HOUSE: [-5]} and m.rebuilds == base + 1, (n.markers(), m.rebuilds)
    # And the game's own icon survives the rebuild.
    assert any(c["sprite"] == NPC_ICON for c in n.world.hubs[FARM][0]["node"]["children"])
    # A second player arrives and leaves.
    n.peer(2, x=100, y=100)
    n.ticks(30)
    assert n.markers() == {FIELD: [-5], HOUSE: [-5]}
    n.peer(2, active=False)
    n.ticks(30)
    assert n.markers() == {HOUSE: [-5]}
    # The mask drops a player.
    n.rt["mask"] = 0b001
    n.ticks(30)
    assert n.markers() == {}
    assert not n.log, n.log
    print("PASS: live: a marker follows its player to another hub within 30 ticks, players joining / leaving / "
          "masked update, no rebuild while the picture is unchanged")


def test_other_locations():
    n = new_node()
    n.peer(1, x=100, y=100)
    m = n.open_map(FARM)
    # The player walks into town: gone from the farm page, shown on the town page.
    n.peer(1, room="town:undefined", x=5, y=5)
    n.ticks(30)
    assert n.markers() == {}, n.markers()
    m.menu["select_location"](TOWN)
    assert n.markers() == {(20, 20): [-5]}, n.markers()
    base = m.rebuilds
    n.ticks(300)
    assert m.rebuilds == base, "a stable town page was rebuilt"
    # Then to the dungeon (no page, no hub): nowhere. The page switched by the tab keeps working.
    n.peer(1, room="dungeon:3", x=5, y=5)
    n.ticks(30)
    assert n.markers() == {}
    # Back on the farm while the town page is shown: appears on the farm page after a tab tap, and the tick keeps the town page right.
    n.peer(1, room="farm:undefined", x=400, y=100)
    n.ticks(30)
    assert n.markers() == {}
    m.menu["select_location"](FARM)
    assert n.markers() == {HOUSE: [-5]}
    # The beach is its own page.
    n.peer(1, room="beach:undefined", x=1, y=1)
    n.ticks(30)
    assert n.markers() == {}
    m.menu["select_location"](BEACH)
    assert n.markers() == {(30, 30): [-5]}
    assert not n.log, n.log
    print("PASS: other locations: a player in another location leaves this page and appears on its own, the dungeon "
          "shows nowhere, a tab change re-places, no rebuilds while stable")


def test_cost():
    n = new_node()
    n.peer(1)
    # No map open: the tick does nothing at all, however long.
    n.ticks(600)
    assert n.maps == [] and n.rt.get("map_menu") is None
    m = n.open_map()
    base_find, base_rebuild = m.find_calls, m.rebuilds
    n.ticks(600)
    # 20 looks in 10 seconds, one hub lookup per visible player each; nothing rebuilt.
    assert m.find_calls - base_find == 20, m.find_calls - base_find
    assert m.rebuilds == base_rebuild
    # Seven players: one lookup each per beat, and a single rebuild when something changed.
    for i in range(1, 8):
        n.peer(i)
    n.rt["mask"] = 0xFF
    before, rebuilt = m.find_calls, m.rebuilds
    n.ticks(30)
    assert m.rebuilds == rebuilt + 1 and m.find_calls - before == 7 * 2, (m.rebuilds, m.find_calls - before)
    before = m.find_calls
    n.ticks(30)
    assert m.find_calls - before == 7 and m.rebuilds == rebuilt + 1
    print("PASS: cost: nothing without an open map, one cheap look per half second with one, a rebuild only on change")


def test_closing():
    n = new_node()
    n.peer(1)
    m = n.open_map()
    n.close(m)
    find = m.find_calls
    n.peer(1, x=400)
    n.ticks(120)
    assert m.find_calls == find and n.rt.get("map_menu") is None, "kept working on a closed menu"
    # Reopening works, the new menu is the one followed; a stale first menu is not.
    m2 = n.open_map()
    assert n.markers() == {HOUSE: [-5]}
    n.peer(1, x=100)
    n.ticks(30)
    assert n.markers() == {FIELD: [-5]} and m.rebuilds == 1
    # A menu the game is freeing (not yet removed from the list) is dropped as well.
    n.close(m2, "free")
    n.peer(1, x=400)
    before = m2.rebuilds
    n.ticks(60)
    assert m2.rebuilds == before and n.rt.get("map_menu") is None
    # Opening any other menu changes nothing.
    n.call("mistrimulti_map_opened", S(kind=MENU_OTHER, menu=S(type=MENU_OTHER)))
    assert n.rt.get("map_menu") is None
    print("PASS: closing: the tick stops on a closed or freed menu, reopening follows the new menu, other menus ignored")


def test_failures():
    n = new_node()
    n.peer(1)
    m = n.open_map()
    # A rebuild that throws: caught, logged once, the map is left alone from then on.
    m.broken = True
    n.peer(1, x=400)
    n.ticks(30)
    assert n.rt.get("map_menu") is None and len(n.log) == 1, n.log
    m.broken = False
    n.ticks(120)
    assert m.rebuilds == 1
    # Hostile or odd peer data never reaches the map: wrong types, unknown or out-of-range locations.
    m = n.open_map()
    n.peer(1, room=7)
    n.peer(2, room="nowhere:1")
    n.peer(3, x="far")
    n.peer(4, room="")
    n.peer(5, active="yes")
    n.rt["peers"][6] = None
    n.rt["peers"][7] = S(active=True, room="farm:undefined")
    n.rt["mask"] = 0xFF
    m.menu["select_location"](FARM)
    n.ticks(60)
    assert n.markers() == {}, n.markers()
    # The game before the map hubs exist, or the runtime off: no work, no error.
    n.rt["enabled"] = False
    n.peer(1, x=400)
    n.ticks(60)
    assert n.markers() == {} and n.rt.get("map_menu") is None
    n2 = new_node()
    n2.rt["enabled"] = False
    n2.open_map()
    assert n2.rt.get("map_menu") is None and n2.markers() == {}
    n3 = new_node()
    n3.interp.builtins["MAP_HUBS"] = None
    n3.peer(1)
    n3.open_map()
    n3.ticks(60)
    assert not n3.log and n3.rt.get("map_sig") == "0", (n3.log, n3.rt.get("map_sig"))
    print("PASS: failures: a throwing rebuild stops quietly, hostile peer data ignored, disabled or hub-less game safe")


def test_wiring():
    """MistriMultiBoot.gml cannot run here, so its two lines are checked as text."""
    boot = (ROOT / "mod/mistrimulti/gml/MistriMultiBoot.gml").read_text(encoding="utf-8")
    assert 'mmapi_on("ui.menu_opened", mistrimulti_map_opened);' in boot
    tick = boot[boot.index("function mistrimulti_tick()"):boot.index("function mistrimulti_look_event")]
    # before the 20 Hz gate, so it runs every tick, and only the rate limit inside it decides when to look
    assert tick.index("mistrimulti_map_tick();") < tick.index("if (r.ticks mod 3 != 0) return;")
    manifest = (ROOT / "mod/mistrimulti/manifest.toml").read_text(encoding="utf-8")
    assert '"ui.menu_opened"' in manifest and '"ui.draw_gui"' in manifest
    print("PASS: wiring: the open hook is registered and the tick calls the map tick every tick; hooks are required")


TESTS = [test_wiring, test_markers_on_open, test_live_update, test_other_locations, test_cost, test_closing, test_failures]


def main():
    names = sys.argv[1:]
    for test in TESTS:
        if not names or test.__name__ in names:
            test()
    print("all map tests passed")


if __name__ == "__main__":
    main()
