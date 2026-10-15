#!/bin/sh
# Builds the native Linux programs (nasm + ld only; no libc, no Windows tools):
#   build/mistrimulti-helper-linux      network helper
#   build/mistrimulti-launcher          Steam launch wrapper:  "<folder>/mistrimulti-launcher" --steam %command%
#   build/mistrimulti-manager           console host / join / Steam setup / Save Solo
#   build/mistrimulti-steam-id-linux    Steam identity probe (the only program that needs the system libraries)
#   build/fakegame-linux                stand-in game for tests/test_launcher_linux.py
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$project/build"
nasm -f elf64 -g -F dwarf -I "$project/helper/include/" -I "$project/linux/" "$project/helper/linux.asm" -o "$project/build/helper-linux.o"
ld "$project/build/helper-linux.o" -o "$project/build/mistrimulti-helper-linux"
printf '%s\n' 'Native Linux helper built.'
for program in launcher manager; do
    nasm -f elf64 -g -F dwarf -I "$project/helper/include/" -I "$project/common/" -I "$project/linux/" \
        "$project/linux/$program.asm" -o "$project/build/$program-linux.o"
    ld "$project/build/$program-linux.o" -o "$project/build/mistrimulti-$program"
done
printf '%s\n' 'Native Linux launcher and manager built.'
nasm -f elf64 -g -F dwarf "$project/tests/fakegame/fakegame_linux.asm" -o "$project/build/fakegame-linux.o"
ld "$project/build/fakegame-linux.o" -o "$project/build/fakegame-linux"
nasm -f elf64 -g -F dwarf -I "$project/helper/include/" "$project/helper/steam_linux.asm" -o "$project/build/steam-linux.o"
ld -e steam_identity_start -dynamic-linker /lib64/ld-linux-x86-64.so.2 \
    "$project/build/steam-linux.o" -l:libdl.so.2 -l:libc.so.6 -o "$project/build/mistrimulti-steam-id-linux"
printf '%s\n' 'Linux Steam identity probe built.'
