#!/usr/bin/env python3
"""Fails on 64-bit address expressions that mix a data label with a register, e.g. [table+rcx] or [buf+8+rcx].

With `default rel` NASM cannot make those RIP-relative, so it emits a 32-bit absolute address. That is wrong for a
64-bit Windows image (the program crashes). Load the label with LEA first: lea r8,[table] / mov al,[r8+rcx].
`name_len equ ...` constants are fine and are ignored.
"""
import glob
import re
import sys

regs = re.compile(r'^(r?[abcd]x|r?[sd]i|r?[sb]p|r\d+[dwb]?|e[abcd]x|e[sd]i|[abcd][lh]|[sd]il|rip)$')
bad = 0
root = sys.argv[1] if len(sys.argv) > 1 else "."
files = []
for pattern in ("updater/*.asm", "updater/*.inc", "launcher/*.asm", "common/*.inc", "linux/*.asm", "linux/*.inc", "tests/fakegame/*.asm", "helper/*.asm", "helper/include/*.inc"):
    files += glob.glob(f"{root}/{pattern}")
consts = set()
for f in files:
    for line in open(f, encoding="utf-8"):
        m = re.match(r"\s*([A-Za-z_.][A-Za-z0-9_.]*)\s*(?::\s*)?equ\b", line) or re.match(r"\s*%(?:x?define|assign)\s+([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            consts.add(m.group(1))
for f in sorted(files):
    for n, line in enumerate(open(f, encoding="utf-8"), 1):
        code = line.split(";")[0]
        for m in re.finditer(r"\[([^\]]+)\]", code):
            toks = re.findall(r"[A-Za-z_.][A-Za-z0-9_.]*", m.group(1))
            labels = [t for t in toks if not regs.match(t) and not t.startswith(".") and not t.endswith("_len")
                      and not t.startswith("wrt") and t != "rel" and t not in consts]
            if labels and any(regs.match(t) for t in toks) and "wrt" not in m.group(1):
                print(f"{f}:{n}: label mixed with a register: {line.strip()}")
                bad += 1
sys.exit(1 if bad else 0)
