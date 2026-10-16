#!/bin/sh
# Runs the whole test matrix in a private network namespace: unshare -n sh scripts/runall.sh  (needs nasm, lld, llvm, wine64, xvfb)
set -u
cd "$(dirname "$0")/.."
python3 - <<'PY'
import fcntl, socket, struct
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
fcntl.ioctl(s, 0x8914, struct.pack('16sH14s', b'lo', 0x41, b'\0' * 14))   # SIOCSIFFLAGS: IFF_UP | IFF_RUNNING
PY
export WINEPREFIX=/tmp/wp_main WINEDEBUG=-all
rc=0
step() { name=$1; shift; if "$@" > /tmp/step.out 2>&1; then echo "PASS  $name"; else echo "FAIL  $name"; tail -15 /tmp/step.out; rc=1; fi; }
step lint python3 scripts/lint-asm.py .
step build-win sh -c 'sh scripts/build-launcher.sh && sh scripts/build-updater.sh && sh scripts/build-helper.sh'
step build-linux sh scripts/build-linux.sh
step win-updater python3 -I tests/test_updater.py build/MistriMulti.exe
step win-world python3 -I tests/test_world.py build/MistriMulti.exe
step win-launcher python3 -I tests/test_launcher.py build/MistriMultiLauncher.exe build/mistrimulti-helper.exe build/fakegame.exe build/MistriMulti.exe build/fakeupdate.exe build/fakecurl.exe
step linux-transport python3 -I tests/test_transport.py build/mistrimulti-helper-linux
step linux-faults python3 tests/test_packet_faults.py build/mistrimulti-helper-linux
step linux-launcher python3 -I tests/test_launcher_linux.py build/mistrimulti-launcher build/mistrimulti-helper-linux build/fakegame-linux build/mistrimulti-manager
step linux-world python3 -I tests/test_world_linux.py build/mistrimulti-manager
step event-layer python3 tests/test_event_layer.py
step event-features python3 tests/test_event_features.py
step event-bridge python3 tests/test_event_bridge.py build/mistrimulti-helper-linux
step trust-linux python3 tests/test_trust.py build/mistrimulti-helper-linux
step trust-gml python3 tests/test_trust_gml.py
step updateui python3 tests/test_updateui.py
step menu python3 tests/test_menu.py build/mistrimulti-launcher build/mistrimulti-helper-linux build/fakegame-linux
step install-linux python3 tests/test_install_linux.py
exit $rc
