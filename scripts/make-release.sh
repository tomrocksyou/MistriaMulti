#!/bin/sh
# Writes release/latest.txt, the list the updater downloads:
#   version <x.y.z>
#   <sha256> mod/mistrimulti/<file>      (one line per mod file)
# Run it whenever the mod changes or its version is bumped. CI fails if the committed list is stale.
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project"
version=$(sed -n 's/^version = "\(.*\)"/\1/p' mod/mistrimulti/manifest.toml | head -n 1)
[ -n "$version" ] || { echo "no version in manifest.toml" >&2; exit 1; }
mkdir -p release
{
    printf 'version %s\n' "$version"
    find mod/mistrimulti -type f | LC_ALL=C sort | while read -r f; do
        printf '%s %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$f"
    done
} > release/latest.txt
echo "release/latest.txt written for version $version"
