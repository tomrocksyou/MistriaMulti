#!/bin/sh
# Writes the list the manager (MistriMulti.exe) downloads and verifies.  Format and publishing: docs/RELEASES.md
#   version <x.y.z>
#   <sha256> mod/mistrimulti/<file>      one line per mod file
#   <sha256> bin/<tool>.exe              one line per tool (only with --bin)
#   end <number of file lines>           the manager rejects a list without it (a truncated download)
#
#   sh scripts/make-release.sh                         release/latest.txt, mod files only. Run it whenever the mod changes
#                                                      or its version is bumped; CI fails if the committed list is stale.
#   sh scripts/make-release.sh --bin <dir> <outfile> [<Linux tar.gz>]
#                                                      mod files plus the four tools found in <dir>, and (with the third
#                                                      argument) a comment line "#linux-tar <sha256> <file name>" that
#                                                      ./install.sh --update uses to verify the Linux programs. Used by the
#                                                      release workflow; the result is published as the asset latest.txt.
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project"
bindir=
out=release/latest.txt
linuxtar=
if [ "${1:-}" = "--bin" ]; then
    [ $# -eq 3 ] || [ $# -eq 4 ] || { echo "usage: make-release.sh [--bin <dir> <outfile> [<Linux tar.gz>]]" >&2; exit 2; }
    bindir=$2
    out=$3
    linuxtar=${4:-}
elif [ $# -ne 0 ]; then
    echo "usage: make-release.sh [--bin <dir> <outfile>]" >&2
    exit 2
fi
version=$(sed -n 's/^version = "\(.*\)"/\1/p' mod/mistrimulti/manifest.toml | head -n 1)
[ -n "$version" ] || { echo "no version in manifest.toml" >&2; exit 1; }
case $version in
    *[!0-9.]* | .* | *. | *..*) echo "version '$version' must be digits and dots (like 0.2.0)" >&2; exit 1 ;;
esac
# The names below are the manager's whitelist (updater/release.inc, bin_table). Keep both in step.
tools="MistriMulti.exe MistriMultiLauncher.exe mistrimulti-helper.exe mistrimulti-steam-id.exe"
body=$(mktemp)
trap 'rm -f "$body"' EXIT
find mod/mistrimulti -type f | LC_ALL=C sort | while read -r f; do
    printf '%s %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$f"
done > "$body"
if [ -n "$bindir" ]; then
    for t in $tools; do
        [ -f "$bindir/$t" ] || { echo "missing $bindir/$t" >&2; exit 1; }
        printf '%s bin/%s\n' "$(sha256sum "$bindir/$t" | cut -d' ' -f1)" "$t" >> "$body"
    done
fi
count=$(wc -l < "$body" | tr -d ' ')
mkdir -p "$(dirname -- "$out")"
{
    printf 'version %s\n' "$version"
    if [ -n "$linuxtar" ]; then
        [ "$(basename "$linuxtar")" = "MistriaMulti-$version-Linux.tar.gz" ] || { echo "$linuxtar must be named MistriaMulti-$version-Linux.tar.gz" >&2; exit 1; }
        printf '#linux-tar %s %s\n' "$(sha256sum "$linuxtar" | cut -d' ' -f1)" "$(basename "$linuxtar")"
    fi
    cat "$body"
    printf 'end %s\n' "$count"
} > "$out"
echo "$out written for version $version ($count files)"
