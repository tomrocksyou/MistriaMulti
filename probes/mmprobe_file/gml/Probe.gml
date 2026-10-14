// Probe C: baseline latency of the file bridge (what the current design pays).
// Writes ping_N.json; tools/probe_listener.py answers with pong_N.json.
function mmprobe_file_tick() {
    if (global[$ "__mmprobe_file"] == undefined) global.__mmprobe_file = { ticks: 0, n: 0, sent_at: 0, rtts: [], waiting: false };
    var r = global.__mmprobe_file;
    r.ticks++;
    var dir = mmapi_mod_data_dir("mmprobe_file");
    if (r.ticks < 180 || r.n >= 200) return;
    if (!r.waiting) {
        var tmp = dir + "/ping.tmp", f = file_text_open_write(tmp);
        file_text_write_string(f, string(r.n));
        file_text_close(f);
        if (file_exists(dir + "/ping.json")) file_delete(dir + "/ping.json");
        file_rename(tmp, dir + "/ping.json");
        r.sent_at = get_timer();
        r.waiting = true;
    } else if (file_exists(dir + "/pong.json")) {
        array_push(r.rtts, get_timer() - r.sent_at);
        file_delete(dir + "/pong.json");
        r.waiting = false;
        r.n++;
        if (r.n == 200) {
            var sum = 0, worst = 0;
            for (var i = 0; i < 200; i++) { sum += r.rtts[i]; worst = max(worst, r.rtts[i]); }
            var f2 = file_text_open_write(dir + "/results.json");
            file_text_write_string(f2, json_stringify({ round_trips: 200, mean_us: sum / 200, worst_us: worst }));
            file_text_close(f2);
        }
    }
}

mmapi_mod_declare("mmprobe_file", "0.0.1");
mmapi_register(mmprobe_file_tick);
