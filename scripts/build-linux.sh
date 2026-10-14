#!/bin/sh
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$project/build"
nasm -f elf64 -g -F dwarf -I "$project/helper/include/" "$project/helper/linux.asm" -o "$project/build/helper-linux.o"
ld "$project/build/helper-linux.o" -o "$project/build/mistrimulti-helper-linux"
printf '%s\n' 'Native Linux helper built.'
nasm -f elf64 -g -F dwarf -I "$project/helper/include/" "$project/helper/steam_linux.asm" -o "$project/build/steam-linux.o"
ld -e steam_identity_start -dynamic-linker /lib64/ld-linux-x86-64.so.2 \
    "$project/build/steam-linux.o" -l:libdl.so.2 -l:libc.so.6 -o "$project/build/mistrimulti-steam-id-linux"
printf '%s\n' 'Linux Steam identity probe built.'
