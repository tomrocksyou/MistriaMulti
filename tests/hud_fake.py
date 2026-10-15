"""A stand-in for the part of the game's ANCHOR UI that MistriMultiHudText.gml uses: screen_canvas and text(parent, z, layer)
returning chainable nodes (set_align, set_xy, set_color, set_text, set_alpha), plus the Align / AnchorLayer enums.

Like the real game it lets the test free every node and rebuild ANCHOR (`rebuild`), and it can make a call throw (`broken`).
What it cannot tell: that the real nodes render, where they land on screen, or that the colours look right (docs/SYNC-MENU.md,
in-game checklist)."""
from gml_subset import GStruct, GmlError

ALIGN = GStruct(LeftIn=0, RightIn=1, Center=2, TopIn=3, BottomIn=4, Middle=5)
LAYERS = GStruct(WorldSpace=0, Hud=1, Standard=2, ScreenFader=3, AboveFader=4, Popup=5)


class FakeAnchor:
    def __init__(self, interp=None, extras=None):
        self.extras = extras or {}      # more ANCHOR fields the test's game needs (kept across rebuilds)
        self.interp = interp            # the interpreter whose ANCHOR builtin is replaced by `rebuild`
        self.nodes = []
        self.broken = False
        self.struct = None
        self.rebuild()

    def rebuild(self, free=True):
        """The game shut ANCHOR down and built a new one (free=True: and freed every old node)."""
        for n in self.nodes:
            n["freed"] = n["freed"] or free
            n["stale"] = True               # belongs to the old ANCHOR: no longer drawn either way
        fields = dict(screen_canvas=GStruct(freed=False), text=self.text, wrap_for_local=lambda t: t,
                      get_text_font=lambda: 0, popup_is_open=lambda: False)
        fields.update(self.extras)
        self.struct = GStruct(**fields)
        if self.interp is not None:
            self.interp.builtins["ANCHOR"] = self.struct

    def text(self, parent, z, layer):
        if self.broken:
            raise GmlError("ANCHOR.text failed")
        node = GStruct(freed=False, stale=False, text="", color=16777215, alpha=1, x=0, y=0, z=z, layer=layer, align=None)

        def setter(field, make=lambda *a: a[0]):
            def f(*a):
                node[field] = make(*a)
                return node
            return f
        node["set_text"] = setter("text")
        node["set_color"] = setter("color")
        node["set_alpha"] = setter("alpha")
        node["set_align"] = setter("align", lambda h, v: (h, v))
        node["set_xy"] = setter("pos", lambda x, y: (x, y))
        self.nodes.append(node)
        return node

    def live(self, color=None):
        """Visible (alpha 1, not freed) coloured nodes' texts, outline copies (black, z 901) left out."""
        return [n["text"] for n in self.nodes if not n["freed"] and n["alpha"] == 1 and n["z"] == 900]

    def main(self, text):
        found = [n for n in self.nodes if not n["freed"] and n["z"] == 900 and n["text"] == text]
        return found[-1] if found else None
