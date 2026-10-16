"""Load test of the real network helper (assembly): CPU, memory and traffic of a host and its guests.

    python3 tests/loadtest_helper.py build/mistrimulti-helper-linux [--guests 7] [--seconds 60] [--blob-kb 100]
    python3 tests/loadtest_helper.py build/mistrimulti-helper-linux --matrix --seconds 60   # 1, 3 and 7 guests, then 3 behind a lossy proxy
    python3 tests/loadtest_helper.py build/mistrimulti-helper.exe --guests 3                  # Windows helper under Wine (or on Windows)

Runs itself in a private network namespace (`unshare -n`, lo up). One host helper and N guest helpers run on
loopback; the game side of every player is the Python reference model (tests/event_model.py) driven by the
harness of tests/test_event_bridge.py: status.json once a second, rx_<slot>.json at 20 Hz, tx.frame written at
20 Hz. Every game sends a changing frame of about 3 KB at 20 Hz (like the real game's player state) plus a few
small events and requests; the host sends one blob (default 100 KB) to everybody every 5 s and every guest sends
a 10 KB record to the host every 6 s. A world download (TCP 7775) is NOT part of this test: the helper does not
serve it (the launcher/manager does), see tests/test_world.py.

The numbers are a LOOPBACK SIMULATION on whatever machine runs it. They are not a real network and not the real
game. CPU is the helper PROCESS's own utime+stime (from /proc/<pid>/stat, or GetProcessTimes on Windows), so
other jobs on the machine do not distort it. The Python harness (8 games in one thread) is not measured.
"""
import argparse
import fcntl
import os
from pathlib import Path
import random
import socket
import struct
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

ON_WINDOWS = os.name == "nt"
CLK = os.sysconf("SC_CLK_TCK") if not ON_WINDOWS else 0


def lo_up():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    fcntl.ioctl(s, 0x8914, struct.pack("16sH14s", b"lo", 0x41, b"\0" * 14))   # SIOCSIFFLAGS: IFF_UP | IFF_RUNNING


# ---- process measurements ---------------------------------------------------------------------------------

def proc_cpu(pid):
    """utime+stime in seconds, or None when the process is gone."""
    if ON_WINDOWS:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        handle = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        t = [wintypes.FILETIME() for _ in range(4)]
        ok = k.GetProcessTimes(handle, *[ctypes.byref(x) for x in t])
        k.CloseHandle(handle)
        if not ok:
            return None
        return sum(((x.dwHighDateTime << 32) | x.dwLowDateTime) for x in t[2:]) / 1e7
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except OSError:
        return None
    return (int(fields[11]) + int(fields[12])) / CLK        # utime, stime are fields 14 and 15


def proc_split(pid):
    """(utime, stime) seconds on Linux, None elsewhere."""
    if ON_WINDOWS:
        return None
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except OSError:
        return None
    return int(fields[11]) / CLK, int(fields[12]) / CLK


def proc_mem(pid):
    """(VmRSS, VmHWM) in KB; on Windows (WorkingSetSize, PeakWorkingSetSize)."""
    if ON_WINDOWS:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t)] + \
                       [(n, ctypes.c_size_t) for n in ("a", "b", "c", "d", "e")]
        k = ctypes.windll.kernel32
        handle = k.OpenProcess(0x1000, False, pid)
        c = Counters()
        c.cb = ctypes.sizeof(c)
        ok = handle and ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(c), c.cb)
        if handle:
            k.CloseHandle(handle)
        return (c.WorkingSetSize // 1024, c.PeakWorkingSetSize // 1024) if ok else (None, None)
    values = {}
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                values[line.split(":")[0]] = int(line.split()[1])
    except OSError:
        pass
    return values.get("VmRSS"), values.get("VmHWM")


def lo_counters():
    """(packets, bytes) the namespace's loopback has carried (each datagram counted once)."""
    for line in Path("/proc/net/dev").read_text().splitlines():
        if line.strip().startswith("lo:"):
            f = line.split(":")[1].split()
            return int(f[1]), int(f[0])
    return 0, 0


def status_counts(bridge):
    import json
    try:
        s = json.loads((bridge / "status.json").read_text())
        return s.get("rx", 0), s.get("tx", 0)
    except (OSError, ValueError):
        return None


# ---- the run ---------------------------------------------------------------------------------------------

def stats(values):
    return (sum(values) / len(values), max(values)) if values else (0.0, 0.0)


def run(helper, guests, seconds, blob_kb, lossy, seed=1):
    import test_event_bridge as bridge
    import test_event_layer as layer

    world = bridge.World(helper, guests, seed)
    # Every game also sends player-state-like data: about 3 KB that changes on every one of its 20 Hz ticks.
    rng = random.Random(seed + 7)
    ticks = {}

    def wrap(game):
        call = game.node.call
        ticks[game.slot] = 0

        def patched(name, *args):
            if name == "mistrimulti_events_encode":
                ticks[game.slot] += 1
                args[0]["pl"] = {"x": rng.random() * 1000, "y": rng.random() * 1000, "room": "farm", "f": ticks[game.slot],
                                 "inv": "".join(rng.choice("0123456789abcdef") for _ in range(3000))}
            return call(name, *args)
        game.node.call = patched

    traffic = {"pings": 1, "requests": 0.05, "blobs": 0, "defer": 0.0, "pad": 64, "until": 1 << 60}
    try:
        if lossy:
            world.proxy = bridge.Proxy(world.ports[0], random.Random(seed + 1))
            world.proxy.start()
        for slot in range(guests + 1):
            world.start_helper(slot)
            wrap(world.start_game(slot, dict(traffic)))
        assert world.run(30, lambda: bridge.everyone_connected(world, guests)), f"admission: {world.masks()}"
        world.run(5)                                       # warm up: first blobs, buffers, caches

        pids = {slot: p.pid for slot, p in world.processes.items()}
        start_mem = {s: proc_mem(p) for s, p in pids.items()}
        samples = {s: {"cpu": [], "rx": [], "tx": []} for s in pids}
        last_cpu = {s: proc_cpu(p) for s, p in pids.items()}
        last_cnt = {s: status_counts(world.bridge(s)) for s in pids}
        lo_last = lo_counters()
        lo_samples = []
        tick0 = dict(ticks)
        cpu0 = dict(last_cpu)
        split0 = {s: proc_split(p) for s, p in pids.items()}
        series = {s: [] for s in pids}                     # RSS (KB) every 10 s, to tell a leak from a plateau
        cnt0 = dict(last_cnt)
        lo0 = lo_last
        wall0 = last_t = time.monotonic()
        state = {"host_blob": wall0, "guest_blob": wall0 + 3, "blobs": 0, "refused": 0}
        peak = {s: start_mem[s][1] or 0 for s in pids}

        def tick():
            nonlocal last_t, lo_last
            now = time.monotonic()
            if state.get("stop"):
                return False
            game0 = world.games[0].feature
            if now - state["host_blob"] >= 5:
                state["host_blob"] = now
                state["blobs"] += 1
                if not game0.blob(blob_kb * 1000, -1):
                    state["refused"] += 1
            if now - state["guest_blob"] >= 6:
                state["guest_blob"] = now
                for slot in range(1, guests + 1):
                    state["blobs"] += 1
                    if not world.games[slot].feature.blob(10000, 0):
                        state["refused"] += 1
            if now - last_t >= 1.0:
                dt = now - last_t
                last_t = now
                for s, p in pids.items():
                    cpu = proc_cpu(p)
                    if cpu is not None and last_cpu[s] is not None:
                        samples[s]["cpu"].append((cpu - last_cpu[s]) / dt)
                    last_cpu[s] = cpu
                    cnt = status_counts(world.bridge(s))
                    if cnt and last_cnt[s]:
                        samples[s]["rx"].append((cnt[0] - last_cnt[s][0]) / dt)
                        samples[s]["tx"].append((cnt[1] - last_cnt[s][1]) / dt)
                    if cnt:
                        last_cnt[s] = cnt
                    rss, hwm = proc_mem(p)
                    peak[s] = max(peak[s], hwm or 0)
                    if len(lo_samples) % 10 == 9:
                        series[s].append(rss)
                now_lo = lo_counters()
                lo_samples.append(((now_lo[0] - lo_last[0]) / dt, (now_lo[1] - lo_last[1]) / dt))
                lo_last = now_lo
            return False
        world.run(seconds, tick)
        wall = time.monotonic() - wall0
        end_mem = {s: proc_mem(p) for s, p in pids.items()}
        cpu1 = {s: proc_cpu(p) for s, p in pids.items()}
        split1 = {s: proc_split(p) for s, p in pids.items()}
        lo1 = lo_counters()
        cnt1 = {s: status_counts(world.bridge(s)) for s in pids}
        tick_rate = {s: (ticks[s] - tick0[s]) / wall for s in ticks}

        # Delivery check: every blob sent during the run (but the last few seconds) must have arrived.
        for game in world.games.values():
            game.feature.plan["until"] = 0
        state["stop"] = True
        seen = layer_blobs_seen(world, guests)       # stop the traffic, give the queues 30 s to drain, then count
        result = {"guests": guests, "lossy": lossy, "seconds": wall, "blob_kb": blob_kb, "blobs_sent": state["blobs"],
                  "blobs_refused": state["refused"], "blobs_seen": seen, "tick_rate": tick_rate,
                  "lo_pps": stats([p for p, _ in lo_samples])[0], "lo_Bps": (lo1[1] - lo0[1]) / wall,
                  "lo_pkts": lo1[0] - lo0[0], "proxy": dict(world.proxy.counts) if world.proxy else None, "procs": {}}
        for s in pids:
            avg, mx = stats(samples[s]["cpu"])
            result["procs"][s] = {
                "cpu_avg": (cpu1[s] - cpu0[s]) / wall * 100 if cpu1[s] is not None and cpu0[s] is not None else None,
                "cpu_max": mx * 100, "rss_series": series[s],
                "user_share": (split1[s][0] - split0[s][0]) / max(cpu1[s] - cpu0[s], 1e-9) if split1[s] and split0[s] else None, "rss_start": start_mem[s][0], "rss_end": end_mem[s][0],
                "hwm": max(peak[s], end_mem[s][1] or 0),
                "rx_pps": (cnt1[s][0] - cnt0[s][0]) / wall if cnt1[s] and cnt0[s] else None,
                "tx_pps": (cnt1[s][1] - cnt0[s][1]) / wall if cnt1[s] and cnt0[s] else None,
                "rx_max": stats(samples[s]["rx"])[1], "tx_max": stats(samples[s]["tx"])[1]}
        return result
    finally:
        world.close()


def layer_blobs_seen(world, guests):
    """(blob deliveries received, deliveries expected): a host blob goes to every guest, a guest blob to the host."""
    expected = sum(guests if b["target"] == -1 else 1 for b in world.ledger.blobs_sent.values())
    world.run(30, lambda: sum(world.ledger.blobs_seen.values()) >= expected)
    return sum(world.ledger.blobs_seen.values()), expected


def report(results, label_cols=True):
    lines = []
    head = ("run", "role", "CPU% avg", "CPU% max1s", "RSS start KB", "RSS end KB", "growth KB", "peak KB",
            "snap/s in", "dgram/s out", "dgram/s in", "KB/s in*", "KB/s out*")
    lines.append(" | ".join(head))
    for r in results:
        name = f"{r['guests']} guests" + (" lossy" if r["lossy"] else "")
        avg_size = r["lo_Bps"] / r["lo_pps"] if r["lo_pps"] else 0       # mean datagram size on lo
        slots = [0, 1] + ([2] if r["lossy"] else [])
        for s in slots:
            p = r["procs"][s]
            others = sum(r["procs"][g]["tx_pps"] for g in range(1, r["guests"] + 1))
            dgram_in = others if s == 0 else r["procs"][0]["tx_pps"] / r["guests"]    # host: exact; guest: host's output / guests
            role = "host" if s == 0 else f"guest {s}" + (" (proxy)" if r["lossy"] and s == 2 else "")
            if p["cpu_avg"] is None:
                continue
            lines.append(" | ".join([
                name, role, f"{p['cpu_avg']:.2f}", f"{p['cpu_max']:.2f}", str(p["rss_start"]), str(p["rss_end"]),
                f"{p['rss_end'] - p['rss_start']:+d}", str(p["hwm"]),
                f"{p['rx_pps']:.0f}", f"{p['tx_pps']:.0f}", ("" if s == 0 else "~") + f"{dgram_in:.0f}",
                f"{dgram_in * avg_size / 1024:.1f}", f"{p['tx_pps'] * avg_size / 1024:.1f}"]))
    lines.append("")
    lines.append("snap/s in = the helper's status.json `rx`: complete snapshots (frames) accepted per second, not datagrams. A frame of "
                 "3 KB is 3 datagrams of up to 1152 bytes payload. dgram/s out = `tx`: datagrams sent (fragments, handshake, heartbeats).")
    lines.append("dgram/s in: host = sum of the guests' `tx` (exact on a lossless path); guest = host `tx` / guests (an estimate, ~).")
    lines.append("* KB/s = datagrams/s x the mean datagram size on lo (/proc/net/dev, includes 28 bytes IP+UDP per datagram); the helper "
                 "does not count bytes itself.")
    for r in results:
        name = f"{r['guests']} guests" + (" lossy" if r["lossy"] else "")
        seen, sent = r["blobs_seen"]
        lines.append(f"{name}: {r['seconds']:.0f} s; whole namespace {r['lo_pps']:.0f} datagrams/s, {r['lo_Bps'] / 1024:.0f} KB/s "
                     f"(mean {r['lo_Bps'] / max(r['lo_pps'], 1):.0f} B); blobs sent in the run {r['blobs_sent']} (refused {r['blobs_refused']}), "
                     f"blob deliveries received {seen} of {sent} expected, after a 30 s drain; game ticks/s of the harness "
                     f"{min(r['tick_rate'].values()):.1f}-{max(r['tick_rate'].values()):.1f} (target 20)"
                     + (f"; proxy {r['proxy']}" if r["proxy"] else ""))
    for r in results:
        for sl, p in r["procs"].items():
            if sl in (0, 1):
                lines.append(f"{r['guests']} guests{' lossy' if r['lossy'] else ''} slot {sl}: RSS KB every 10 s {p['rss_series']}"
                             + (f"; user-mode share of its CPU {p['user_share'] * 100:.0f}%" if p["user_share"] is not None else ""))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("helper", type=Path)
    parser.add_argument("--guests", type=int, default=7)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--blob-kb", type=int, default=100)
    parser.add_argument("--lossy", action="store_true", help="guest 2 reaches the host through the 10%% loss / 10%% duplication proxy")
    parser.add_argument("--matrix", action="store_true", help="1, 3 and 7 guests, then 3 guests with the lossy proxy")
    args = parser.parse_args()
    if not ON_WINDOWS and os.environ.get("LOADTEST_NS") != "1":
        os.environ["LOADTEST_NS"] = "1"
        os.execvp("unshare", ["unshare", "-n", sys.executable, os.path.abspath(__file__)] + sys.argv[1:])
    if not ON_WINDOWS:
        lo_up()
    assert 1 <= args.guests <= 7
    helper = args.helper.resolve()
    if helper.name.endswith(".exe") and not ON_WINDOWS:
        print("Windows helper under Wine: CPU and memory are those of the Wine process that hosts it "
              "(wineserver is a separate process and not included).", flush=True)
    plan = [(1, False), (3, False), (7, False), (3, True)] if args.matrix else [(args.guests, args.lossy)]
    results = []
    for guests, lossy in plan:
        print(f"-- {guests} guests{' lossy' if lossy else ''}, {args.seconds} s ...", flush=True)
        results.append(run(helper, guests, args.seconds, args.blob_kb, lossy))
    print()
    print(report(results))


if __name__ == "__main__":
    main()
