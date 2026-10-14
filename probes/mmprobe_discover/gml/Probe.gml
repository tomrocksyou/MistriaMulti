// Probe D: discover how the game stores saves, so multiplayer worlds can be kept apart.
// Writes into mod_data/mmprobe_discover/: info.json, scripts.txt, objects.txt, globals.txt, savefiles.txt
function mmprobe_discover_out(name, text) {
    var f = file_text_open_write(mmapi_mod_data_dir("mmprobe_discover") + "/" + name);
    file_text_write_string(f, text);
    file_text_close(f);
}

function mmprobe_discover_match(name) {
    var n = string_lower(name);
    var words = ["save", "slot", "load", "world", "profile", "title", "mainmenu", "main_menu", "newgame", "new_game",
                 "continue", "sleep", "newday", "new_day", "mmapi", "momi", "guard", "hook", "file", "persist"];
    for (var i = 0; i < array_length(words); i++) if (string_pos(words[i], n) > 0) return true;
    return false;
}

function mmprobe_discover_walk(dir, depth, out) {
    if (depth > 4) return;
    var names = [];
    var f = file_find_first(dir + "/*", fa_directory);
    while (f != "") { array_push(names, f); f = file_find_next(); }
    file_find_close();
    for (var i = 0; i < array_length(names); i++) {
        var p = dir + "/" + names[i];
        if (directory_exists(p)) { array_push(out, "[dir]  " + p); mmprobe_discover_walk(p, depth + 1, out); }
        else array_push(out, "[file] " + p);
    }
}

function mmprobe_discover_tick() {
    if (global[$ "__mmprobe_discover"] == undefined)
        global.__mmprobe_discover = { ticks: 0, next: 0, scripts: [], objects: [], done: false };
    var r = global.__mmprobe_discover;
    if (r.done) return;
    r.ticks++;
    if (r.ticks < 120) return;
    if (r.ticks == 120) {
        var info = { game_save_id: game_save_id, working_directory: working_directory, program_directory: program_directory,
                     os_type: os_type, game_display_name: game_display_name, room: room_get_name(room) };
        mmprobe_discover_out("info.json", json_stringify(info));
        var files = [];
        try { mmprobe_discover_walk(game_save_id, 0, files); } catch (e) { array_push(files, "walk failed: " + string(e)); }
        var text = "";
        for (var i = 0; i < array_length(files); i++) text += files[i] + "\n";
        mmprobe_discover_out("savefiles.txt", text);
        var g = "";
        try {
            var names = variable_instance_get_names(global);
            for (var j = 0; j < array_length(names); j++) g += names[j] + "\n";
        } catch (e) { g = "variable_instance_get_names(global) failed: " + string(e); }
        mmprobe_discover_out("globals.txt", g);
    }
    // Scan asset indices in slices so the game never stalls.
    var limit = min(r.next + 20000, 400000);
    for (var i = r.next; i < limit; i++) {
        if (script_exists(i)) { var sn = script_get_name(i); if (mmprobe_discover_match(sn)) array_push(r.scripts, sn); }
        if (object_exists(i)) { var on = object_get_name(i); if (mmprobe_discover_match(on)) array_push(r.objects, on); }
    }
    r.next = limit;
    if (r.next >= 400000) {
        array_sort(r.scripts, true); array_sort(r.objects, true);
        var s = "", o = "";
        for (var a = 0; a < array_length(r.scripts); a++) s += r.scripts[a] + "\n";
        for (var b = 0; b < array_length(r.objects); b++) o += r.objects[b] + "\n";
        mmprobe_discover_out("scripts.txt", s);
        mmprobe_discover_out("objects.txt", o);
        mmprobe_discover_out("DONE.txt", "complete");
        r.done = true;
    }
}

mmapi_mod_declare("mmprobe_discover", "0.0.1");
mmapi_register(mmprobe_discover_tick);
