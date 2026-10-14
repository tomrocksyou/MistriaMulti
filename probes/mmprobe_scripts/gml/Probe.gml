// Probe D1: list game scripts/objects whose names suggest saving, loading, menus or sleeping.
function mmprobe_scripts_match(name) {
    var n = string_lower(name);
    var words = ["save", "slot", "load", "world", "profile", "title", "mainmenu", "main_menu", "newgame", "new_game",
                 "continue", "sleep", "newday", "new_day", "persist", "mmapi_"];
    for (var i = 0; i < array_length(words); i++) if (string_pos(words[i], n) > 0) return true;
    return false;
}

function mmprobe_scripts_tick() {
    if (global[$ "__mmprobe_scripts"] == undefined) global.__mmprobe_scripts = { ticks: 0, next: 0, done: false };
    var r = global.__mmprobe_scripts;
    if (r.done) return;
    r.ticks++;
    if (r.ticks < 120) return;
    var limit = min(r.next + 20000, 400000);
    for (var i = r.next; i < limit; i++) {
        if (script_exists(i)) { var sn = script_get_name(i); if (mmprobe_scripts_match(sn)) mmapi_log_info("mmprobe_scripts", "script " + sn); }
        if (object_exists(i)) { var on = object_get_name(i); if (mmprobe_scripts_match(on)) mmapi_log_info("mmprobe_scripts", "object " + on); }
    }
    r.next = limit;
    if (r.next >= 400000) { mmapi_log_info("mmprobe_scripts", "DONE"); r.done = true; }
    mmapi_log_flush("mmprobe_scripts");
}

mmapi_mod_declare("mmprobe_scripts", "0.0.2");
mmapi_register(mmprobe_scripts_tick);
