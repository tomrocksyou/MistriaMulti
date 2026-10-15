"""Inject packet faults through a real bound host socket into the ASM join helper."""
import argparse
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time
import mmauth
from test_transport import available_port, read_json, wait_until

HEADER = struct.Struct("<4sHHIIIIIHHII")
CODE = 0xA1B2C3D4
KEY = {}    # the session key negotiated with the helper under test (the test plays the host)


def checksum(data):
    result = 2166136261
    for byte in data:
        result = ((result ^ byte) * 16777619) & 0xFFFFFFFF
    return result


def packets(data, seq, epoch=100):
    body = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
    return mmauth.split_snapshot(KEY["sk"], 1, 0, seq, CODE, body, epoch)


def handshake(host, address):
    """Plays the host's half of the join handshake against the helper under test."""
    player = mmauth.Host(CODE)
    deadline = time.monotonic() + 8
    host.settimeout(0.5)
    while time.monotonic() < deadline:
        try:
            packet, source = host.recvfrom(2048)
        except socket.timeout:
            continue
        if packet[4:5] == b"\x01":
            host.sendto(player.challenge(packet, source, int(time.monotonic() * 1000)), source)
        elif packet[4:5] == b"\x03":
            reply, slot = player.proof(packet, source, int(time.monotonic() * 1000))
            host.sendto(reply, source)
            if slot is not None:
                KEY["sk"] = player.sessions[source][1]
                host.settimeout(None)
                return source
    raise AssertionError("the helper never completed the handshake")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("helper", type=Path)
    args = parser.parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as host:
        host.bind(("127.0.0.1", 0))
        with tempfile.TemporaryDirectory(prefix="faults-", dir=Path(__file__).resolve().parent.parent / "build") as tmp:
            bridge = Path(tmp)
            port = available_port()
            destination = ("127.0.0.1", port)
            command = [str(args.helper.resolve()), "join", str(port), "1", "a1b2c3d4", str(bridge),
                       "127.0.0.1", str(host.getsockname()[1])]
            kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen(command, **kwargs)
            try:
                wait_until(lambda: (bridge / "status.json").exists(), label="helper startup")
                destination = handshake(host, destination)
                output = bridge / "rx_0.json"
                data = {"active": True, "value": "é日本", "payload": "a" * 8000}
                fragments = packets(data, 5)
                # Reverse order, duplicate fragments, and hold one fragment back.
                for i in reversed(range(len(fragments))):
                    if i != 2:
                        host.sendto(fragments[i], destination)
                        host.sendto(fragments[i], destination)
                time.sleep(0.2)
                assert not output.exists(), "An incomplete snapshot was published"
                host.sendto(fragments[2], destination)
                wait_until(lambda: read_json(output) == data, label="completion after a missing fragment")
                print("PASS: loss, reordering and duplication never publish a partial frame")

                newer = {"active": True, "value": "newer"}
                for packet in packets(newer, 6):
                    host.sendto(packet, destination)
                wait_until(lambda: read_json(output) == newer, label="new sequence")
                for packet in fragments:
                    host.sendto(packet, destination)
                time.sleep(0.1)
                assert read_json(output) == newer
                print("PASS: older snapshots cannot overwrite newer snapshots")

                final = {"active": True, "value": "checksum-recovered", "payload": "b" * 4000}
                fragments = packets(final, 7)
                for i, packet in enumerate(fragments):
                    if i == 0:
                        packet = packet[:-1] + bytes([packet[-1] ^ 1])
                    host.sendto(packet, destination)
                time.sleep(0.2)
                assert read_json(output) == newer
                for packet in fragments:
                    host.sendto(packet, destination)
                wait_until(lambda: read_json(output) == final, label="checksum retry")
                print("PASS: corruption preserves the last good frame and retransmission recovers")

                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as outsider:
                    for packet in packets({"value": "wrong-source"}, 8):
                        outsider.sendto(packet, destination)
                invalid = HEADER.pack(b"MSMP", 2, 0, 0, 8, CODE, 0, 16385, 0, 15, 100, 0) + b"x"
                host.sendto(invalid + mmauth.tag_data(KEY["sk"], 1, invalid), destination)
                # Correctly signed but impossible: fragment index beyond the count, a zero length, a length over the limit.
                for length, index, count in ((16385, 0, 15), (100, 5, 1), (1, 0, 1), (16384, 15, 15), (16384, 0, 16)):
                    bad = HEADER.pack(b"MSMP", 2, 0, 0, 9, CODE, 0, length, index, count, 100, 0) + b"x" * 100
                    host.sendto(bad + mmauth.tag_data(KEY["sk"], 1, bad), destination)
                time.sleep(0.1)
                assert read_json(output) == final
                print("PASS: wrong source and oversized declared payloads are rejected")

                restarted = {"active": True, "value": "restarted"}
                for packet in packets(restarted, 1, epoch=101):
                    host.sendto(packet, destination)
                wait_until(lambda: read_json(output) == restarted, label="peer restart")
                print("PASS: a new peer epoch accepts a restarted sequence")
                (bridge / "stop.flag").write_text("stop")
                out, err = process.communicate(timeout=5)
                assert process.returncode == 0, (process.returncode, out, err)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
