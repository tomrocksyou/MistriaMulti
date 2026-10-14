// Probe B: can mod code load native code (a DLL / .so)?
function mmprobe_native_log(r, key, value) {
    r.results[$ key] = value;
    var f = file_text_open_write(mmapi_mod_data_dir("mmprobe_native") + "/results.json");
    file_text_write_string(f, json_stringify(r.results));
    file_text_close(f);
}

function mmprobe_native_tick() {
    if (global[$ "__mmprobe_native"] == undefined) global.__mmprobe_native = { ticks: 0, results: {} };
    var r = global.__mmprobe_native;
    r.ticks++;
    if (r.ticks != 120) return;
    mmprobe_native_log(r, "os_type", string(os_type));
    try {
        var fn = external_define("kernel32.dll", "GetTickCount", dll_stdcall, ty_real, 0);
        mmprobe_native_log(r, "external_define", "ok id=" + string(fn));
        mmprobe_native_log(r, "external_call", "GetTickCount=" + string(external_call(fn)));
    } catch (e) { mmprobe_native_log(r, "external_define", "FAIL " + string(e)); }
    try {
        var mem = buffer_create(64, buffer_fixed, 1);
        mmprobe_native_log(r, "buffer_get_address", string(buffer_get_address(mem)));
        buffer_delete(mem);
    } catch (e) { mmprobe_native_log(r, "buffer_get_address", "FAIL " + string(e)); }
}

mmapi_mod_declare("mmprobe_native", "0.0.1");
mmapi_register(mmprobe_native_tick);
