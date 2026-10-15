// On-screen text for the mod, made of the game's own ANCHOR UI nodes. The mod runtime has no draw_* functions ("no such field"),
// so a line of text is a persistent ANCHOR text node (plus a black copy one pixel behind it as an outline) on the screen canvas.
// A slot is a named line: mistrimulti_hudtext_set("badge", "text", colour, ...) creates it on first use, updates it when the text
// or colour changes, and hides it when the text is "". ANCHOR is shut down and rebuilt by the game at some state changes, which
// frees every node: a slot notices (its ANCHOR or node is gone) and builds its nodes again. Nothing is created while the
// multiplayer runtime says a room change is not settled. Every call is guarded: it returns false instead of throwing.
function __mistrimulti_hudtext() {
    if (global[$ "__mistrimulti_hudtext"] == undefined) global.__mistrimulti_hudtext = { slots: {}, created: 0 };
    return global.__mistrimulti_hudtext;
}

function mistrimulti_hudtext_align_x(name) {
    if (name == "right") return Align.RightIn;
    if (name == "center") return Align.Center;
    return Align.LeftIn;
}

function mistrimulti_hudtext_align_y(name) {
    if (name == "bottom") return Align.BottomIn;
    if (name == "middle") return Align.Middle;
    return Align.TopIn;
}

function mistrimulti_hudtext_layer(name) {
    if (name == "above_fader") return AnchorLayer.AboveFader;
    if (name == "popup") return AnchorLayer.Popup;
    return AnchorLayer.Hud;
}

// A slot's nodes are usable while the ANCHOR they were made on is still the live one and neither node was freed.
function mistrimulti_hudtext_alive(slot) {
    if (slot.main == undefined || slot.shadow == undefined) return false;
    if (slot.anchor != ANCHOR) return false;
    return slot.main[$ "freed"] != true && slot.shadow[$ "freed"] != true;
}

function mistrimulti_hudtext_build(slot, layer, ax, ay, x, y) {
    var parent = ANCHOR.screen_canvas;
    var lay = mistrimulti_hudtext_layer(layer);
    var halign = mistrimulti_hudtext_align_x(ax);
    var valign = mistrimulti_hudtext_align_y(ay);
    // a lower z is nearer the viewer in ANCHOR: the outline copy sits behind the coloured text
    slot.shadow = ANCHOR.text(parent, 901, lay).set_align(halign, valign).set_xy(x + 1, y + 1).set_color(0);
    slot.main = ANCHOR.text(parent, 900, lay).set_align(halign, valign).set_xy(x, y);
    slot.anchor = ANCHOR;
    slot.x = x;
    slot.y = y;
    slot.text = undefined;
    slot.color = undefined;
    slot.shown = undefined;
    __mistrimulti_hudtext().created++;
}

// layer: "hud" | "above_fader" | "popup"; ax: "left" | "center" | "right"; ay: "top" | "middle" | "bottom".
// x, y: offset in GUI pixels from that edge (negative moves inward from the right / bottom, as in the game's HUD).
function mistrimulti_hudtext_set(key, text, color, layer, ax, ay, x, y) {
    var h = __mistrimulti_hudtext();
    try {
        var slot = h.slots[$ key];
        if (slot == undefined) {
            if (text == "") return true;
            slot = { anchor: undefined, main: undefined, shadow: undefined, x: x, y: y, text: undefined, color: undefined, shown: undefined };
            h.slots[$ key] = slot;
        }
        var alive = mistrimulti_hudtext_alive(slot);
        if (text == "" && !alive) return true;
        if (!alive) {
            if (ANCHOR == undefined || ANCHOR[$ "screen_canvas"] == undefined) return false;
            var r = __mistrimulti_runtime();
            var in_room = false;
            try { in_room = instance_exists(obj_ari); } catch (e) {}    // on the title screen there is no room change to wait for
            if (in_room && r[$ "room_settled"] == false) return false;
            mistrimulti_hudtext_build(slot, layer, ax, ay, x, y);
            mistrimulti_trace("hudtext", "created the '" + key + "' text node (" + string(h.created) + " in all)", 60);
        }
        var visible = text != "";
        if (visible && (slot.x != x || slot.y != y)) {    // e.g. the badge moves up on the title screen, above the copyright line
            slot.main.set_xy(x, y);
            slot.shadow.set_xy(x + 1, y + 1);
            slot.x = x;
            slot.y = y;
        }
        if (visible && slot.text != text) {
            slot.main.set_text(text);
            slot.shadow.set_text(text);
            slot.text = text;
        }
        if (visible && slot.color != color) {
            slot.main.set_color(color);
            slot.color = color;
        }
        if (slot.shown != visible) {
            slot.main.set_alpha(visible ? 1 : 0);
            slot.shadow.set_alpha(visible ? 1 : 0);
            slot.shown = visible;
        }
        return true;
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_hudtext_" + key, "mistrimulti", "On-screen text '" + key + "' failed: " + string(e));
        h.slots[$ key] = undefined;    // drop the slot: the next call builds fresh nodes
        return false;
    }
}
