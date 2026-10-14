#!/bin/sh
# Builds build/MistriMultiUpdater.exe on Linux (nasm + lld + llvm). No Windows SDK needed.
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$project/build"
sh "$project/scripts/winlibs.sh" "$project/build/winlibs"
cd "$project/build"
nasm -f win64 -I ../helper/include/ ../updater/updater.asm -o updater.obj
lld-link /nologo /machine:x64 /subsystem:windows /entry:start /nodefaultlib /incremental:no \
    /out:MistriMultiUpdater.exe updater.obj /libpath:winlibs \
    kernel32.lib user32.lib shell32.lib gdi32.lib ole32.lib winhttp.lib bcrypt.lib
echo "Updater built: build/MistriMultiUpdater.exe"
