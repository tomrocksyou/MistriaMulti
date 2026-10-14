// Probe A: can mod code use GameMaker's built-in sockets?
function mmprobe_net_log(r, key, value) {
    r.results[$ key] = value;
    var f = file_text_open_write(mmapi_mod_data_dir("mmprobe_net") + "/results.json");
    file_text_write_string(f, json_stringify(r.results));
    file_text_close(f);
}

function mmprobe_net_tick() {
    if (global[$ "__mmprobe_net"] == undefined) global.__mmprobe_net = { ticks: 0, results: {}, sock: -1, server: -1, sent: 0 };
    var r = global.__mmprobe_net;
    r.ticks++;
    if (r.ticks == 120) {
        try { r.sock = network_create_socket(network_socket_udp); mmprobe_net_log(r, "create_socket", string(r.sock)); }
        catch (e) { mmprobe_net_log(r, "create_socket", "FAIL " + string(e)); }
        try { r.server = network_create_server_raw(network_socket_udp, 47771, 8); mmprobe_net_log(r, "create_server_raw", string(r.server)); }
        catch (e) { mmprobe_net_log(r, "create_server_raw", "FAIL " + string(e)); }
    }
    if (r.ticks >= 180 && r.ticks mod 60 == 0 && r.sent < 5 && r.sock >= 0) {
        try {
            var b = buffer_create(16, buffer_fixed, 1);
            buffer_write(b, buffer_text, "PING" + string(r.sent));
            var n = network_send_udp_raw(r.sock, "127.0.0.1", 47770, b, 5);
            buffer_delete(b);
            r.sent++;
            mmprobe_net_log(r, "send_udp_raw", "bytes=" + string(n));
        } catch (e) { mmprobe_net_log(r, "send_udp_raw", "FAIL " + string(e)); r.sent = 99; }
    }
    // Replies arrive via the Async Networking event; check if any receive path is visible to mod code.
    try { mmprobe_net_log(r, "async_load_visible", string(variable_global_exists("async_load")) + " / " + string(async_load)); }
    catch (e) { r.results[$ "async_load_visible"] = "not accessible: " + string(e); }
}

mmapi_mod_declare("mmprobe_net", "0.0.1");
mmapi_register(mmprobe_net_tick);
