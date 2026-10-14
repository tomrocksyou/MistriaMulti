// Probe E: can a mod see the game's save list, and can it redirect the save folder?
// Phase 1 (always): read-only report of CONFIG_DIRECTORY and the save manifest, at the title screen.
// Phase 2 (automatic, right after the first report): point CONFIG_DIRECTORY at an empty
// folder, rebuild the save list, report, then ALWAYS restore.
function mmprobe_saves_say(text) { mmapi_log_info("mmprobe_saves", text); mmapi_log_flush("mmprobe_saves"); }

function mmprobe_saves_report(tag) {
    try { mmprobe_saves_say(tag + " CONFIG_DIRECTORY=" + string(CONFIG_DIRECTORY)); }
    catch (e) { mmprobe_saves_say(tag + " CONFIG_DIRECTORY FAIL " + string(e)); }
    try {
        var keys = Setup.save_manager.manifest.keys();
        mmprobe_saves_say(tag + " manifest entries=" + string(array_length(keys)));
        for (var i = 0; i < array_length(keys); i++) mmprobe_saves_say(tag + "   " + string(keys[i]));
    } catch (e) { mmprobe_saves_say(tag + " manifest FAIL " + string(e)); }
}

function mmprobe_saves_tick() {
    if (global[$ "__mmprobe_saves"] == undefined) global.__mmprobe_saves = { ticks: 0, reports: 0, swapped: false };
    var r = global.__mmprobe_saves;
    r.ticks++;
    if (r.ticks mod 600 != 0 || r.reports >= 3) return;
    r.reports++;
    mmprobe_saves_report("report" + string(r.reports));
    if (r.swapped) return;
    r.swapped = true;
    var original = CONFIG_DIRECTORY;
    try {
        vault_close_all_vaults();
        CONFIG_DIRECTORY = mmapi_mod_data_dir("mmprobe_saves") + "/alt_config";
        Setup.save_manager = new SaveManager();
        mmprobe_saves_report("SWAPPED");
    } catch (e) { mmprobe_saves_say("swap FAIL " + string(e)); }
    try {
        CONFIG_DIRECTORY = original;
        vault_close_all_vaults();
        Setup.save_manager = new SaveManager();
        mmprobe_saves_report("RESTORED");
    } catch (e) { mmprobe_saves_say("RESTORE FAIL " + string(e)); }
}

mmapi_mod_declare("mmprobe_saves", "0.0.1");
mmapi_register(mmprobe_saves_tick);
mmapi_log_info("mmprobe_saves", "loaded");
mmapi_log_flush("mmprobe_saves");
