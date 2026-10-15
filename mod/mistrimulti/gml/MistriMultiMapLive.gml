// ---- the other players on the map (Journal > Map), kept live while the map is open ---------------------------------
// MapMenu.select_location places an icon for the player, villagers, the pet and children on the map's hubs; it has no hook
// for more, and the game only calls it when the menu opens or a tab is tapped. ui.menu_opened (Menu.Map) wraps the menu's
// select_location so that, after the game's own icons, every other player in the session gets the player icon (slightly
// transparent) on the hub the game would pick for that position. While the menu stays open, mistrimulti_map_tick (called
// from the mod tick) looks twice a second at which hub each player is on and calls select_location again only when one
// changed, so a walking player costs nothing until the player crosses into another hub. Players in a location that the
// shown page has no hub for are not drawn there (they appear on their own page); the game has no minimap.
#macro MISTRIMULTI_MAP_REFRESH_TICKS 30

function mistrimulti_map_opened(ctx) {
    if (ctx.kind != Menu.Map) return;
    var r = __mistrimulti_runtime();
    if (!r.enabled) return;
    try {
        var menu = ctx.menu;
        var holder = { menu: menu, orig: menu.select_location };
        menu.select_location = method(holder, function(location_id) {
            self.orig(location_id);
            mistrimulti_map_add_peers(self.menu);
        });
        r.map_menu = menu;
        mistrimulti_map_add_peers(menu); // the constructor already showed the first page
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_map", "mistrimulti", "Map markers failed: " + string(e));
    }
}

// The hub of the shown page for each other player the page can show, in player order.
function mistrimulti_map_peer_hubs(menu) {
    var r = __mistrimulti_runtime();
    var out = [];
    var shown = menu.selected_location_id;
    if (shown == undefined || MAP_HUBS == undefined) return out;
    var hubs = MAP_HUBS[shown];
    if (!is_array(hubs)) return out;
    var queue = ds_priority_create();
    for (var i = 0; i < 8; i++) {
        var p = r.peers[i];
        if (i == r.id || !is_struct(p) || p[$ "active"] != true || (r.mask & (1 << i)) == 0 || !is_string(p[$ "room"])) continue;
        if (!is_real(p[$ "x"]) || !is_real(p[$ "y"])) continue;
        var parts = string_split(p.room, ":");
        var loc = undefined;
        try { loc = string_to_location_id(parts[0]); } catch (e) { loc = undefined; }
        if (!is_real(loc) || loc < 0 || loc >= LocationId.LEN) continue;
        var hub = menu.find_hub_for(hubs, new LocationPosition(loc, Vec2(p.x, p.y)), queue, shown);
        if (!is_struct(hub) || hub[$ "node"] == undefined) continue;
        array_push(out, hub);
    }
    ds_priority_destroy(queue);
    return out;
}

// What the markers look like: the shown page and the hub of each marker. Equal text, equal picture.
function mistrimulti_map_signature(menu, hubs) {
    var text = string(menu.selected_location_id);
    for (var i = 0; i < array_length(hubs); i++) text += ";" + string(hubs[i].asset_x) + "," + string(hubs[i].asset_y);
    return text;
}

function mistrimulti_map_add_peers(menu) {
    var r = __mistrimulti_runtime();
    if (!r.enabled) return;
    try {
        var hubs = mistrimulti_map_peer_hubs(menu);
        for (var i = 0; i < array_length(hubs); i++) {
            var slot = 0; // players on the same hub sit side by side
            for (var j = 0; j < i; j++) if (hubs[j] == hubs[i]) slot++;
            ANCHOR.sprite(hubs[i].node)
                .set_sprite(spr_ui_generic_icon_npc_small_player)
                .set_xy(-5 + 11 * slot, -16)
                .set_alpha(0.8)
                .set_speed(1);
        }
        r.map_sig = mistrimulti_map_signature(menu, hubs);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_map", "mistrimulti", "Map markers failed: " + string(e));
    }
}

// Every mod tick (60 Hz): nothing unless a map menu is open, and then work only twice a second.
function mistrimulti_map_tick() {
    var r = __mistrimulti_runtime();
    var menu = r[$ "map_menu"];
    if (menu == undefined || r.ticks mod MISTRIMULTI_MAP_REFRESH_TICKS != 0) return;
    try {
        if (!r.enabled || menu[$ "free_requested"] == true || !ANCHOR.open_menus.contains(menu)) {
            r.map_menu = undefined;
            return;
        }
        if (mistrimulti_map_signature(menu, mistrimulti_map_peer_hubs(menu)) == r[$ "map_sig"]) return;
        menu.select_location(menu.selected_location_id); // the wrapper adds the players again
    } catch (e) {
        r.map_menu = undefined;
        mmapi_warn_rate_limited("mistrimulti_map", "mistrimulti", "Map markers failed: " + string(e));
    }
}
