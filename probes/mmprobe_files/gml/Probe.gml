// Probe D2: where are saves stored? Lists the game's save folder.
function mmprobe_files_walk(dir, depth) {
    if (depth > 4) return;
    var names = [];
    var f = file_find_first(dir + "/*", fa_directory);
    while (f != "") { array_push(names, f); f = file_find_next(); }
    file_find_close();
    for (var i = 0; i < array_length(names); i++) {
        var p = dir + "/" + names[i];
        if (directory_exists(p)) { mmapi_log_info("mmprobe_files", "[dir]  " + p); mmprobe_files_walk(p, depth + 1); }
        else mmapi_log_info("mmprobe_files", "[file] " + p);
    }
}

function mmprobe_files_tick() {
    if (global[$ "__mmprobe_files"] == undefined) global.__mmprobe_files = { ticks: 0 };
    var r = global.__mmprobe_files;
    r.ticks++;
    if (r.ticks != 120) return;
    mmapi_log_info("mmprobe_files", "game_save_id=" + string(game_save_id) + " working_directory=" + string(working_directory));
    try { mmprobe_files_walk(game_save_id, 0); mmapi_log_info("mmprobe_files", "DONE"); }
    catch (e) { mmapi_log_info("mmprobe_files", "walk FAIL " + string(e)); }
    mmapi_log_flush("mmprobe_files");
}

mmapi_mod_declare("mmprobe_files", "0.0.2");
mmapi_register(mmprobe_files_tick);
