#!/bin/sh
# Runs the GML feature suites (no game, no build needed) in a private network namespace: sh scripts/run-features.sh
# The real-game-scripts part of test_engine_audit.py is skipped (MISTRIA_GML is cleared); test_menu.py runs its GML parts only.
set -u
cd "$(dirname "$0")/.."
if [ -z "${MISTRIMULTI_NETNS:-}" ]; then
    MISTRIMULTI_NETNS=1 exec unshare -n sh "$0" "$@"
fi
python3 - <<'PY'
import fcntl, socket, struct
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
fcntl.ioctl(s, 0x8914, struct.pack('16sH14s', b'lo', 0x41, b'\0' * 14))   # SIOCSIFFLAGS: IFF_UP | IFF_RUNNING
PY
export MISTRIA_GML=
rc=0
out=$(mktemp)
for t in containers ranch progress farm_sync wallet dungeon story buildings guestsave devtools renown maplive menu trust_gml event_features event_layer engine_audit; do
    start=$(date +%s)
    if python3 "tests/test_$t.py" > "$out" 2>&1; then r=PASS; else r=FAIL; rc=1; fi
    echo "$r  $t ($(( $(date +%s) - start )) s)"
    [ "$r" = FAIL ] && tail -15 "$out"
done
rm -f "$out"
# Optional: GAME_SCRIPTS=<folder with the game's gml> also checks every function, enum and field the mod uses against it.
if [ -n "${GAME_SCRIPTS:-}" ]; then
    if python3 scripts/audit-gml-ids.py --game "$GAME_SCRIPTS"; then echo "PASS  engine identifiers"; else echo "FAIL  engine identifiers"; rc=1; fi
fi
exit $rc
