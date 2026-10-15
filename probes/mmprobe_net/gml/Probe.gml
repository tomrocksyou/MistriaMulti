// Probe A: do GameMaker sockets work from a mod? Results go to the MMAPI log.
function mmprobe_net_say(text) { mmapi_log_info("mmprobe_net", text); mmapi_log_flush("mmprobe_net"); }

function mmprobe_net_tick() {
    if (global[$ "__mmprobe_net"] == undefined) global.__mmprobe_net = { ticks: 0, sock: -1, sent: 0 };
    var r = global.__mmprobe_net;
    r.ticks++;
    if (r.ticks == 120) {
        try { r.sock = network_create_socket(network_socket_udp); mmprobe_net_say("create_socket OK id=" + string(r.sock)); }
        catch (e) { mmprobe_net_say("create_socket FAIL " + string(e)); }
    }
    if (r.ticks >= 180 && r.ticks mod 60 == 0 && r.sent < 3 && r.sock >= 0) {
        try {
            var b = buffer_create(16, buffer_fixed, 1);
            buffer_write(b, buffer_text, "PING" + string(r.sent));
            var n = network_send_udp_raw(r.sock, "127.0.0.1", 47770, b, 5);
            buffer_delete(b);
            r.sent++;
            mmprobe_net_say("send_udp_raw OK bytes=" + string(n));
        } catch (e) { mmprobe_net_say("send_udp_raw FAIL " + string(e)); r.sent = 99; }
    }
}

mmapi_mod_declare("mmprobe_net", "0.0.2");
mmapi_register(mmprobe_net_tick);
mmapi_log_info("mmprobe_net", "loaded");
mmapi_log_flush("mmprobe_net");
