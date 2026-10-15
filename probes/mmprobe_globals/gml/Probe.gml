// Probe D3: list global variable names (game state).
function mmprobe_globals_tick() {
    if (global[$ "__mmprobe_globals"] == undefined) global.__mmprobe_globals = { ticks: 0 };
    var r = global.__mmprobe_globals;
    r.ticks++;
    if (r.ticks != 120) return;
    try {
        var names = variable_instance_get_names(global);
        for (var i = 0; i < array_length(names); i++) mmapi_log_info("mmprobe_globals", names[i]);
        mmapi_log_info("mmprobe_globals", "DONE " + string(array_length(names)));
    } catch (e) { mmapi_log_info("mmprobe_globals", "FAIL " + string(e)); }
    mmapi_log_flush("mmprobe_globals");
}

mmapi_mod_declare("mmprobe_globals", "0.0.2");
mmapi_register(mmprobe_globals_tick);
