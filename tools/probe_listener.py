#!/usr/bin/env python3
"""Companion for probes/. Echoes UDP on 47770 and answers file pings.

  python tools/probe_listener.py [--data-dir DIR]

DIR defaults to %LOCALAPPDATA%/FieldsOfMistria/mod_data/mmapi (the folder that
holds mmprobe_* subfolders). Run it, then start the game with the probe mods.
"""
import argparse, os, socket, sys, threading, time

def udp_echo():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 47770))
    while True:
        data, addr = s.recvfrom(2048)
        print(f"[net] got {data!r} from {addr}")
        s.sendto(b"PONG", ("127.0.0.1", 47771))  # tests the reverse path

def file_echo(base):
    d = os.path.join(base, "mmprobe_file")
    n = 0
    while True:
        try:
            for name in os.listdir(d):
                if name.startswith("ping_") and name.endswith(".json"):
                    open(os.path.join(d, "pong_" + name[5:]), "w").write("1")
                    os.remove(os.path.join(d, name)); n += 1
                    if n % 25 == 0: print(f"[file] answered {n}")
        except OSError: pass
        time.sleep(0.001)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    default = os.path.join(os.environ.get("LOCALAPPDATA", "."), "FieldsOfMistria", "mod_data", "mmapi")
    ap.add_argument("--data-dir", default=default)
    a = ap.parse_args()
    threading.Thread(target=udp_echo, daemon=True).start()
    print("listening: UDP 127.0.0.1:47770, file echo in", a.data_dir)
    file_echo(a.data_dir)
