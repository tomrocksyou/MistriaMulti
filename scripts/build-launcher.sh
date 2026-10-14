#!/bin/sh
# Builds build/MistriMultiLauncher.exe and the test game on Linux (nasm + lld + llvm). No Windows SDK needed.
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$project/build"
sh "$project/scripts/winlibs.sh" "$project/build/winlibs"
cd "$project/build"
nasm -f win64 -I ../helper/include/ -I ../common/ -I ../launcher/ ../launcher/launcher.asm -o launcher.obj
lld-link /nologo /machine:x64 /subsystem:windows /entry:start /nodefaultlib /incremental:no \
    /out:MistriMultiLauncher.exe launcher.obj /libpath:winlibs kernel32.lib user32.lib shell32.lib ole32.lib ws2_32.lib bcrypt.lib
nasm -f win64 ../tests/fakegame/fakegame.asm -o fakegame.obj
lld-link /nologo /machine:x64 /subsystem:console /entry:start /nodefaultlib /out:fakegame.exe fakegame.obj \
    /libpath:winlibs kernel32.lib
echo "Launcher built: build/MistriMultiLauncher.exe"
