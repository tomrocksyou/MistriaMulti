#!/bin/sh
# Usage: play-linux.sh host CODE | play-linux.sh join HOST_IP PLAYER_ID CODE
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mode=${1:-host}
port=${MISTRIMULTI_PORT:-7777}
if [ "$mode" = host ]; then
    id=0
    code=${2:-}
    local_port=$port
    host=127.0.0.1
elif [ "$mode" = join ]; then
    host=${2:?Host IPv4 address required}
    id=${3:?Player number 1-7 required}
    code=${4:?Eight-digit room code required}
    local_port=$((port + id))
else
    printf '%s\n' 'Choose host or join.' >&2
    exit 2
fi
case "$id" in 0|1|2|3|4|5|6|7) ;; *) printf '%s\n' 'Invalid player number.' >&2; exit 2;; esac
if [ "$mode" = join ] && [ "$id" = 0 ]; then exit 2; fi
if [ -z "$code" ]; then code=$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n'); fi
if [ "${#code}" -ne 8 ]; then printf '%s\n' 'Room code needs eight hex digits.' >&2; exit 2; fi
case "$code" in *[!a-fA-F0-9]*) exit 2;; esac
data=${MISTRIMULTI_DATA_DIR:-}
if [ -z "$data" ]; then
    for candidate in "${XDG_DATA_HOME:-$HOME/.local/share}/FieldsOfMistria" "${XDG_CONFIG_HOME:-$HOME/.config}/FieldsOfMistria"; do
        if [ -d "$candidate/saves" ]; then data=$candidate; break; fi
    done
fi
if [ -z "$data" ]; then
    printf '%s\n' 'Set MISTRIMULTI_DATA_DIR to the actual game configuration folder containing saves.' >&2
    exit 2
fi
# Reject paths that cannot be encoded by the control-file writer.
case "$data" in *'"'*|*'\'*) printf '%s\n' 'Unsupported configuration path.' >&2; exit 2;; esac
mod_data="$data/mod_data/mistrimulti"
bridge="$mod_data/bridge_$id"
mkdir -p "$bridge"
# Only exact, helper-owned transient filenames in the selected bridge.
rm -f -- "$bridge/stop.flag" "$bridge/status.json" "$bridge/tx.frame"
for peer in 0 1 2 3 4 5 6 7; do rm -f -- "$bridge/rx_$peer.json"; done
epoch=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
uid=''
probe="$project/build/mistrimulti-steam-id-linux"
steam_api=${MISTRIMULTI_STEAM_API:-}
if [ -z "$steam_api" ]; then
    for candidate in "$HOME/.local/share/Steam/steamapps/common/Fields of Mistria/libsteam_api.so" "$HOME/.steam/steam/steamapps/common/Fields of Mistria/libsteam_api.so"; do
        if [ -f "$candidate" ]; then steam_api=$candidate; break; fi
    done
fi
if [ -x "$probe" ] && [ -n "$steam_api" ]; then
    uid=$("$probe" "$steam_api" 2>/dev/null | sed -n '/^steam:[0-9][0-9]*$/p' | tail -n 1) || uid=''
    if [ "${#uid}" -ne 23 ]; then uid=''; fi
fi
if [ -z "$uid" ]; then
    identity_file="$mod_data/local_identity_linux.txt"
    if [ -f "$identity_file" ]; then uid=$(cat "$identity_file"); fi
    suffix=${uid#local:}
    case "$suffix" in *[!a-f0-9]*) uid='';; esac
    if [ "${#uid}" -ne 38 ] || [ "${#suffix}" -ne 32 ]; then uid="local:$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"; fi
    printf '%s\n' "$uid" > "$identity_file"
    printf '%s\n' 'Steam identity unavailable; using the saved local device identity.'
fi
printf '{"enabled":true,"mode":"%s","id":%s,"uid":"%s","epoch":"%s","bridge":"%s"}\n' "$mode" "$id" "$uid" "$epoch" "$bridge" > "$mod_data/control.json"
helper="$project/build/mistrimulti-helper-linux"
chmod +x "$helper"
if [ "$mode" = host ]; then
    "$helper" host "$local_port" "$id" "$code" "$bridge" &
else
    "$helper" join "$local_port" "$id" "$code" "$bridge" "$host" "$port" &
fi
helper_pid=$!
finish() {
    printf '%s\n' stop > "$bridge/stop.flag"
    wait "$helper_pid" || true
    printf '%s\n' '{"enabled":false}' > "$mod_data/control.json"
}
trap finish EXIT HUP INT TERM
printf 'MistriMulti %s | player %s | room %s | UDP %s\n' "$mode" "$id" "$code" "$local_port"
printf '%s\n' 'Start Fields of Mistria in Steam, load a save, and keep this launcher open.'
printf '%s\n' 'Press Enter here after closing the game.'
read -r answer
