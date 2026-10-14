global.__mistrimulti_peer_object = object_create("obj_mistrimulti_peer", undefined, {
    sprite_index: undefined,
    create: function() {
        self.z = 0;
        self.target_x = self.x;
        self.target_y = self.y;
        self.par = new PlayerAnimationRuntime();
        self.par.set_cardinal(Cardinal.South);
        create_default_player_animation_assets().apply_to_par(self.par);
        self.par.set_animation(AnimationName.Idle);
        self.par_offset = fiddle_deserialize_vec2(fiddle_get("player").par.offset);
        self.shadow = self.create_renderable(spr_npc_shadow);
        self.draw_count = 0;
        self.opacity_min = 1;
        self.opacity_max = 1;
        self.applied_look = create_default_player_animation_assets().serialize();
        self.remote_modifier = -1;
    },
    step: function() {
        try {
        if (point_distance(self.x, self.y, self.target_x, self.target_y) > 96) {
            self.x = self.target_x;
            self.y = self.target_y;
        } else {
            self.x = lerp(self.x, self.target_x, 0.35);
            self.y = lerp(self.y, self.target_y, 0.35);
        }
        self.depth = get_instance_depth(self.y);
        self.par.animate();
        self.shadow.x = self.x;
        self.shadow.y = self.y;
        self.shadow.depth = self.depth + 1;
        } catch (e) { mmapi_warn_rate_limited("mistrimulti_ghost_step", "mistrimulti", "Other player's character (step) failed: " + string(e)); }
    },
    draw: function(draw_x, draw_y, frame_alpha) {
        try {
        // frame_alpha controls interpolation; par.alpha must stay at 1.
        if (global[$ "__mistrimulti_debug_on"] == true) {
            self.draw_count++;
            self.opacity_min = min(self.opacity_min, self.par.alpha);
            self.opacity_max = max(self.opacity_max, self.par.alpha);
        }
        self.par.draw(draw_x + self.par_offset.x, draw_y + self.par_offset.y + self.z);
        } catch (e) { mmapi_warn_rate_limited("mistrimulti_ghost_draw", "mistrimulti", "Other player's character (draw) failed: " + string(e)); }
    },
    cleanup: function() {
        try { mistrimulti_trace("ghost", "cleanup " + string(self.id), 200); } catch (e) {}
        try { ds_priority_destroy(self.par.priority); }
        catch (e) { mmapi_warn_rate_limited("mistrimulti_ghost_cleanup", "mistrimulti", "Other player's character (cleanup) failed: " + string(e)); }
    },
});

function mistrimulti_hide_peer(id) {
    var r = __mistrimulti_runtime();
    var p = r.peers[id];
    if (!is_struct(p)) return;
    var ghost = p[$ "ghost"];
    if (ghost != undefined && instance_exists(ghost)) {
        mistrimulti_trace("ghost", "hide player " + string(id) + " instance " + string(ghost), 200);
        instance_destroy(ghost);
    }
    p.ghost = undefined;
}

function mistrimulti_remove_ghosts() {
    for (var i = 0; i < 8; i++) mistrimulti_hide_peer(i);
}

function mistrimulti_update_peer(id) {
    var r = __mistrimulti_runtime();
    var p = r.peers[id];
    if (p.room != mistrimulti_room_key()) { mistrimulti_hide_peer(id); return; }
    var ghost = p[$ "ghost"];
    if (ghost == undefined || !instance_exists(ghost)) {
        // Dynamically registered objects are not compile-time asset identifiers.
        var kind = global.__mistrimulti_peer_object;
        if (kind == undefined) kind = try_string_to_asset("obj_mistrimulti_peer");
        if (kind == undefined) {
            mmapi_warn_rate_limited("mistrimulti_object", "mistrimulti", "Remote character object is unavailable.");
            return;
        }
        mistrimulti_trace("ghost", "create player " + string(id) + " at " + string(p.x) + "," + string(p.y) + " room " + string(p.room), 200);
        ghost = instance_create_depth(p.x, p.y, get_instance_depth(p.y), kind);
        mistrimulti_trace("ghost", "created instance " + string(ghost), 200);
        p.ghost = ghost;
        if (is_struct(p[$ "look"])) mistrimulti_apply_peer_look(ghost, p.look);
    }
    ghost.target_x = p.x;
    ghost.target_y = p.y;
    ghost.z = is_real(p[$ "z"]) ? clamp(p.z, -256, 256) : 0;
    if (ghost.par.cardinal != p.c) ghost.par.set_cardinal(p.c);
    if (ghost.par.base_animation() != p.ba) ghost.par.set_animation(p.ba);
    var modifier = is_real(p[$ "ma"]) && p.ma >= 0 && p.ma < AnimationName.LEN ? p.ma : -1;
    if (ghost.remote_modifier != modifier) {
        ghost.par.unset_all_modifiers();
        if (modifier != -1) ghost.par.set_animation(modifier);
        ghost.remote_modifier = modifier;
    }
    var attachment = p[$ "att"];
    if (attachment != undefined && attachment != -1 && PLAYER_ANIMATION_DATABASE.player_attachments.get(attachment) != undefined) {
        ghost.par.set_attachment(attachment);
    } else { ghost.par.remove_attachment(); }
}

function mistrimulti_apply_peer_look(ghost, look) {
    // Clear previous cosmetic slots, including accessories absent from the new outfit.
    for (var i = 0; i < array_length(ghost.applied_look.assets); i++) {
        ghost.par.remove_asset(ghost.applied_look.assets[i].name);
    }
    player_animation_assets_deserialize(look).apply_to_par(ghost.par);
    ghost.applied_look = look;
}

// ---- the other players on the map (Journal > Map) ----------------------------------------------------------------
// MapMenu.select_location places an icon for the player, villagers, the pet and children on the map's hubs; it has no hook
// for more. ui.menu_opened (Menu.Map) wraps the menu's select_location so that, after the game's own icons, every other
// player in the session gets the player icon (slightly transparent) on the hub the game would pick for that position.
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
        mistrimulti_map_add_peers(menu); // the constructor already showed the first page
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_map", "mistrimulti", "Map markers failed: " + string(e));
    }
}

function mistrimulti_map_add_peers(menu) {
    var r = __mistrimulti_runtime();
    if (!r.enabled) return;
    try {
        var shown = menu.selected_location_id;
        if (shown == undefined || MAP_HUBS == undefined) return;
        var hubs = MAP_HUBS[shown];
        if (!is_array(hubs)) return;
        var queue = ds_priority_create();
        var placed = 0;
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
            ANCHOR.sprite(hub.node)
                .set_sprite(spr_ui_generic_icon_npc_small_player)
                .set_xy(-5 + 11 * placed, -16)
                .set_alpha(0.8)
                .set_speed(1);
            placed++;
        }
        ds_priority_destroy(queue);
    } catch (e) {
        mmapi_warn_rate_limited("mistrimulti_map", "mistrimulti", "Map markers failed: " + string(e));
    }
}
