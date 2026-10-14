#!/bin/sh
# Builds the two downloads for players (no git, no build tools needed):
#   MistriMulti-<version>-Windows.zip     the four Windows programs, Install-Mod.bat, the mod, HOW-TO-PLAY.txt
#   MistriMulti-<version>-Linux.tar.gz    the four Linux programs, install.sh, the mod, HOW-TO-PLAY.txt
# Each unpacks to one folder MistriMulti/ (no version in the name, so an update unpacks over it and the Steam launch line
# stays valid), laid out like the repository, so Install-Mod.bat and install.sh work unchanged (they look for
# mod/mistrimulti and the programs next to themselves).
#   sh scripts/make-player-packages.sh <windows programs dir> <linux programs dir> <output dir>
# Used by .github/workflows/release.yml; works locally after scripts/build-*.sh (programs in build/).
set -eu
[ $# -eq 3 ] || { echo "usage: make-player-packages.sh <windows bin dir> <linux bin dir> <out dir>" >&2; exit 2; }
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
winbin=$1
linbin=$2
mkdir -p "$3"
out=$(CDPATH= cd -- "$3" && pwd)
version=$(sed -n 's/^version = "\(.*\)"/\1/p' "$project/mod/mistrimulti/manifest.toml" | head -n 1)
[ -n "$version" ] || { echo "no version in manifest.toml" >&2; exit 1; }
name=MistriMulti
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

common() {    # $1: staging folder
    mkdir -p "$1/mod"
    cp -R "$project/mod/mistrimulti" "$1/mod/"
    cp "$project/LICENSE" "$project/CONTACT.md" "$1/"
}

# Windows
w=$stage/win/$name
mkdir -p "$w/scripts"
common "$w"
for f in MistriMulti.exe MistriMultiLauncher.exe mistrimulti-helper.exe mistrimulti-steam-id.exe; do
    [ -f "$winbin/$f" ] || { echo "missing $winbin/$f" >&2; exit 1; }
    cp "$winbin/$f" "$w/"
done
cp "$project/Install-Mod.bat" "$w/"
cp "$project/scripts/Install-Mod.ps1" "$project/scripts/Find-Game.ps1" "$w/scripts/"
sed 's/$/\r/' "$project/docs/HOW-TO-PLAY.md" > "$w/HOW-TO-PLAY.txt"
rm -f "$out/MistriMulti-$version-Windows.zip"
(cd "$stage/win" && zip -q -r -X "$out/MistriMulti-$version-Windows.zip" "$name")

# Linux
l=$stage/lin/$name
mkdir -p "$l"
common "$l"
for f in mistrimulti-launcher mistrimulti-manager mistrimulti-helper-linux mistrimulti-steam-id-linux; do
    [ -f "$linbin/$f" ] || { echo "missing $linbin/$f" >&2; exit 1; }
    cp "$linbin/$f" "$l/"
    chmod 755 "$l/$f"
done
cp "$project/install.sh" "$l/"
chmod 755 "$l/install.sh"
cp "$project/docs/HOW-TO-PLAY.md" "$l/HOW-TO-PLAY.txt"
tar -C "$stage/lin" -czf "$out/MistriMulti-$version-Linux.tar.gz" "$name"

echo "$out/MistriMulti-$version-Windows.zip"
echo "$out/MistriMulti-$version-Linux.tar.gz"
