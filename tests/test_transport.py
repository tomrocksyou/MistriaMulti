"""Black-box transport checks. Python is a developer test tool, not a runtime dependency."""
import argparse
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time


def wait_until(check, seconds=8, label="condition"):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.03)
    raise AssertionError(f"Timed out waiting for {label}")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def publish(directory, data, reliable=False):
    target = directory / "tx.frame"
    temp = directory / "game-write.tmp"
    temp.write_bytes((b"1\n" if reliable else b"0\n") + json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode())
    os.replace(temp, target)


def available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("helper", type=Path)
    args = parser.parse_args()
    exe = str(args.helper.resolve())
    processes = []
    results = []
    with tempfile.TemporaryDirectory(prefix="transport-", dir=Path(__file__).resolve().parent.parent / "build") as tmp:
        root = Path(tmp)
        bridges = [root / f"bridge_{i}_é_日本" for i in range(3)]
        ports = [available_port() for _ in bridges]
        try:
            for i, bridge in enumerate(bridges):
                bridge.mkdir()
                cmd = [exe, "host" if i == 0 else "join", str(ports[i]), str(i), "a1b2c3d4", str(bridge)]
                if i:
                    cmd += ["127.0.0.1", str(ports[0])]
                kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
                if os.name == "nt":
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                processes.append(subprocess.Popen(cmd, **kwargs))
                publish(bridge, {"active": True, "id": i, "value": f"player-{i}"})
            wait_until(lambda: read_json(bridges[0] / "status.json")["mask"] == 6, label="three-player admission")
            wait_until(lambda: read_json(bridges[2] / "rx_1.json")["value"] == "player-1", label="host forwarding and idle peer discovery")
            wait_until(lambda: read_json(bridges[1] / "rx_0.json")["value"] == "player-0", label="host state")
            results.append("Three-player forwarding and Unicode bridge paths")

            large = {"active": True, "id": 1, "value": "fragmented", "payload": "x" * 15000}
            publish(bridges[1], large, reliable=True)
            wait_until(lambda: read_json(bridges[0] / "rx_1.json") == large, label="large reassembly on host")
            wait_until(lambda: read_json(bridges[2] / "rx_1.json") == large, label="large forwarding")
            results.append("15 KB fragmented snapshots reassemble exactly")

            # Invalid data must not overwrite the last good publication.
            before = (bridges[2] / "rx_1.json").read_bytes()
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(b"invalid" * 200, ("127.0.0.1", ports[2]))
                header = struct.pack("<4sHHIIIIIIHHII", b"MSMP", 1, 0, 1, 999999, 0, 0, 0, 0, 0, 0, 0, 0)
                s.sendto(header, ("127.0.0.1", ports[2]))
            time.sleep(0.25)
            assert (bridges[2] / "rx_1.json").read_bytes() == before
            results.append("Malformed, oversize, wrong-session packets are rejected")

            publish(bridges[1], {"active": True, "id": 1, "value": "final"})
            wait_until(lambda: read_json(bridges[2] / "rx_1.json")["value"] == "final", label="new state replaces fragmented state")
            time.sleep(1.2)
            first_status = read_json(bridges[1] / "status.json")
            first = first_status["tx"]
            time.sleep(2.2)
            second_status = read_json(bridges[1] / "status.json")
            second = second_status["tx"]
            assert second - first <= 5, (first, second)
            assert second_status["heartbeat"] > first_status["heartbeat"]
            results.append("Idle traffic falls to approximately one snapshot per second")
            results.append("Local helper heartbeat advances even while game state is unchanged")

            for bridge in bridges:
                (bridge / "stop.flag").write_text("stop")
            for process in processes:
                stdout, stderr = process.communicate(timeout=5)
                assert process.returncode == 0, (process.returncode, stdout, stderr)
            assert all(read_json(p / "status.json")["running"] is False for p in bridges)
            results.append("Graceful shutdown of each owned helper")
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
    for result in results:
        print("PASS:", result)


if __name__ == "__main__":
    main()
