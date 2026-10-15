// Probe C: file-bridge round-trip baseline. Uses only functions the real mod uses.
// Writes ping_N.json; tools/probe_listener.py answers with pong_N.json.
function mmprobe_file_tick() {
    if (global[$ "__mmprobe_file"] == undefined) global.__mmprobe_file = { ticks: 0, n: 0, sent_at: 0, total: 0, worst: 0, waiting: false };
    var r = global.__mmprobe_file;
    r.ticks++;
    var dir = mmapi_mod_data_dir("mmprobe_file");
    if (r.ticks < 180 || r.n >= 100) return;
    if (!r.waiting) {
        save_text_file(dir + "/ping_" + string(r.n) + ".json", string(r.n));
        r.sent_at = get_timer();
        r.waiting = true;
    } else if (file_exists(dir + "/pong_" + string(r.n) + ".json")) {
        var rtt = get_timer() - r.sent_at;
        r.total += rtt; r.worst = max(r.worst, rtt);
        r.waiting = false;
        r.n++;
        if (r.n == 100) {
            mmapi_log_info("mmprobe_file", "100 round trips: mean " + string(r.total / 100) + " us, worst " + string(r.worst) + " us (ticks of 16666us expected)");
            mmapi_log_flush("mmprobe_file");
        }
    }
}

mmapi_mod_declare("mmprobe_file", "0.0.2");
mmapi_register(mmprobe_file_tick);
mmapi_log_info("mmprobe_file", "loaded; data dir " + mmapi_mod_data_dir("mmprobe_file"));
mmapi_log_flush("mmprobe_file");
