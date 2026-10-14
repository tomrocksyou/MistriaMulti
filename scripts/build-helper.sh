#!/bin/sh
# Builds build/mistrimulti-helper.exe and build/mistrimulti-steam-id.exe on Linux (nasm + lld + llvm). No Windows SDK needed.
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$project/build"
sh "$project/scripts/winlibs.sh" "$project/build/winlibs"
cd "$project/build"
nasm -f win64 -I ../helper/include/ -I ../linux/ ../helper/windows.asm -o helper-win.obj
lld-link /nologo /machine:x64 /subsystem:console /entry:mistria_main /nodefaultlib /incremental:no \
    /out:mistrimulti-helper.exe helper-win.obj /libpath:winlibs kernel32.lib ws2_32.lib shell32.lib bcrypt.lib
nasm -f win64 -I ../helper/include/ ../helper/steam_windows.asm -o steam-win.obj
lld-link /nologo /machine:x64 /subsystem:console /entry:steam_identity_main /nodefaultlib /incremental:no \
    /out:mistrimulti-steam-id.exe steam-win.obj /libpath:winlibs kernel32.lib shell32.lib
echo "Helper built: build/mistrimulti-helper.exe, build/mistrimulti-steam-id.exe"
