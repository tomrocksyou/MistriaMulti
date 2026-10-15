// Probe B: can a mod call native code? Results go to the MMAPI log.
function mmprobe_native_say(text) { mmapi_log_info("mmprobe_native", text); mmapi_log_flush("mmprobe_native"); }

function mmprobe_native_tick() {
    if (global[$ "__mmprobe_native"] == undefined) global.__mmprobe_native = { ticks: 0 };
    var r = global.__mmprobe_native;
    r.ticks++;
    if (r.ticks != 120) return;
    try {
        var fn = external_define("kernel32.dll", "GetTickCount", dll_stdcall, ty_real, 0);
        mmprobe_native_say("external_define OK id=" + string(fn));
        mmprobe_native_say("external_call OK GetTickCount=" + string(external_call(fn)));
    } catch (e) { mmprobe_native_say("external_define FAIL " + string(e)); }
}

mmapi_mod_declare("mmprobe_native", "0.0.2");
mmapi_register(mmprobe_native_tick);
mmapi_log_info("mmprobe_native", "loaded");
mmapi_log_flush("mmprobe_native");
