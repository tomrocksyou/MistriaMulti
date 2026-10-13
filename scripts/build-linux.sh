#!/bin/sh
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$project/build"
nasm -f elf64 -g -F dwarf -I "$project/helper/include/" "$project/helper/linux.asm" -o "$project/build/helper-linux.o"
ld "$project/build/helper-linux.o" -o "$project/build/mistrimulti-helper-linux"
printf '%s\n' 'Native Linux helper built.'
