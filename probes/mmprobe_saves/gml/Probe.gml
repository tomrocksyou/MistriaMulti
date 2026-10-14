// Probe E: can a mod redirect the game's save folder from the title screen?
// game.title_entered fires from Setup's create, after the save list is built and before the
// title menu's own start chain runs. At every title entry this probe reports the save list,
// points CONFIG_DIRECTORY at an empty folder, rebuilds the save manager, reports, then restores.
// Only logging is used here (file IO is not safe before the first frame).
function __mmprobe_saves_runtime() {
    if (global[$ "__mmprobe_saves"] == undefined) global.__mmprobe_saves = { registered_hooks: undefined };
    return global.__mmprobe_saves;
}

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

function mmprobe_saves_title_entered(ctx) {
    mmprobe_saves_say("title_entered from_game=" + string(ctx.from_game));
    mmprobe_saves_report("BEFORE");
    var original = CONFIG_DIRECTORY;
    try {
        vault_close_all_vaults();
        CONFIG_DIRECTORY = original + "/mmprobe_alt";
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

function mmprobe_saves_register() {
    var r = __mmprobe_saves_runtime();
    if (r.registered_hooks != undefined) return;
    r.registered_hooks = true;
    mmapi_on("game.title_entered", mmprobe_saves_title_entered);
}

mmapi_mod_declare("mmprobe_saves", "0.0.2");
mmprobe_saves_register();
