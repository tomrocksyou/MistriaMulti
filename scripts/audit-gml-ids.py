#!/usr/bin/env python3
"""Checks every game identifier the mod's GML uses against the game's own scripts (read-only; nothing is copied).

    python3 scripts/audit-gml-ids.py --game <scripts dir> [--game <second scripts dir>] [--mod mod/mistrimulti/gml]

Per game directory it reports: functions called by the mod that no game or MMAPI script mentions; Enum.Member uses whose
member is missing; `.field` reads the mod never assigns that no game script mentions; mmapi_* functions the installed
MMAPI does not define; hooks missing from, or registered with another kind than, the installed hook catalog.
With two --game directories it also lists functions, enums and macros that were added, removed or changed between them
(definitions that MMAPI's own patches add, on lines marked `mmapi`, are ignored). Exit status 1 when anything is reported.
A name appearing in some script is only evidence that it exists: it does not prove a field exists on that object.
"""
import argparse
import glob
import os
import re
import sys

KEYWORDS = set("if for while switch return function with repeat until do else catch try throw new var static global self other "
               "and or not div mod true false undefined infinity pi noone all break continue case default then begin end enum "
               "globalvar finally exit".split())
# Fields of the helper's status file (read through the bridge), not of the game.
BRIDGE_FIELDS = {"heartbeat"}
DEF = re.compile(r"\b(?:function\s+(\w+)|(\w+)\s*=\s*function)\s*\(([^)]*)\)")
ENUM = re.compile(r"\benum\s+(\w+)\s*\{([^}]*)\}")


def strip(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r'"(\\.|[^"\\\n])*"', '""', text)
    return re.sub(r"//[^\n]*", "", text)


def gml_files(root):
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            if name.endswith(".gml"):
                yield os.path.join(dirpath, name)


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


class Mod:
    def __init__(self, directory):
        raw = [read(p) for p in glob.glob(os.path.join(directory, "*.gml"))]
        self.code = "\n".join(strip(t) for t in raw)
        self.raw = "\n".join(re.sub(r"/\*.*?\*/", "", t, flags=re.S) for t in raw)
        self.defined = set(re.findall(r"\bfunction\s+(\w+)", self.code)) | set(re.findall(r"\b(?:var|static)\s+(\w+)", self.code))
        self.defined |= set(re.findall(r"^\s*#macro\s+(\w+)", self.code, flags=re.M))
        for params in re.findall(r"\bfunction\s*\w*\s*\(([^)]*)\)", self.code):
            self.defined |= {p.split("=")[0].strip() for p in params.split(",")}
        self.assigned = set(re.findall(r"\.([A-Za-z_]\w*)\s*(?:=(?!=)|\+=|-=|\+\+|--)", self.code))
        self.assigned |= set(re.findall(r'\[\$\s*"([A-Za-z_]\w*)"\s*\]\s*(?:=(?!=)|\+=|-=)', self.raw))
        self.assigned |= set(re.findall(r"[{,]\s*([A-Za-z_]\w*)\s*:", self.raw))
        self.calls = set(re.findall(r"(?<![\w.])([A-Za-z_]\w*)\s*\(", self.code))
        self.members = set(re.findall(r"\.([A-Za-z_]\w*)", self.code))
        self.hooks = set(re.findall(r'mmapi_(on|filter|guard|override)\(\s*"([\w.]+)"', self.raw))
        self.mmapi = set(re.findall(r"\b(mmapi_\w+)", self.code))


class Game:
    def __init__(self, directory):
        self.dir = directory
        self.tokens, self.enums, self.sigs, self.mm_added = set(), {}, {}, set()
        self.mm_defs, self.catalog = set(), {}
        for path in gml_files(directory):
            rel = os.path.relpath(path, directory).lower()
            if "mistriamulti" in rel or "mistrimulti" in rel:   # the installed copy of this mod is not the game
                continue
            text = read(path)
            lines = text.splitlines()
            code = strip(text)
            self.tokens |= set(re.findall(r"[A-Za-z_]\w*", code))
            if os.sep + "mmapi" + os.sep in os.sep + rel:
                self.mm_defs |= set(re.findall(r"\bfunction\s+(\w+)", code))
                if rel.endswith("mmapi_hook_catalog.gml"):
                    self.catalog = {n: k for n, k in re.findall(r'"([a-z_.]+)",\s*"([a-z-]+)"', text)
                                    if k in ("event", "filter", "guard", "override")}
                continue
            for m in ENUM.finditer(code):
                self.enums[m.group(1)] = [x.split("=")[0].strip() for x in m.group(2).split(",") if x.strip()]
                self.sigs["enum " + m.group(1)] = re.sub(r"\s+", " ", m.group(2))
            for m in DEF.finditer(code):
                name = m.group(1) or m.group(2)
                self.sigs.setdefault(name, re.sub(r"\s+", "", m.group(3)))
                if name.startswith("__mmapi") or "mmapi" in lines[min(code.count("\n", 0, m.start()), len(lines) - 1)]:
                    self.mm_added.add(name)   # added by an MMAPI patch, not by the game
            for m in re.finditer(r"^\s*#macro\s+(\w+)\s+(.*)$", code, flags=re.M):
                self.sigs["#" + m.group(1)] = m.group(2).strip()


def check(mod, game):
    out = []
    for name in sorted(mod.calls):
        if name in KEYWORDS or name in mod.defined or name.startswith(("mmapi_", "mistrimulti", "__mistrimulti")):
            continue
        if name not in game.tokens:
            out.append("function never mentioned by the game: " + name)
    for enum, member in sorted(set(re.findall(r"\b([A-Z]\w*)\.(\w+)", mod.code))):
        if enum in game.enums and member != "LEN" and member not in game.enums[enum]:
            out.append("enum member missing: %s.%s" % (enum, member))
    for name in sorted(mod.members - BRIDGE_FIELDS):
        if name not in game.tokens and name not in mod.assigned and name not in game.mm_defs:
            out.append("field never assigned by the mod nor mentioned by the game: ." + name)
    if game.mm_defs:
        for name in sorted(mod.mmapi - game.mm_defs):
            out.append("MMAPI function not defined by the installed MMAPI: " + name)
    for kind, hook in sorted(mod.hooks):
        want = {"on": "event"}.get(kind, kind)
        have = game.catalog.get(hook)
        if game.catalog and have is None:
            out.append("hook not in the installed catalog: " + hook)
        elif have is not None and have != want and not (hook == "object.interact" and kind == "override"):
            out.append("hook kind differs: %s registered as %s, catalog says %s" % (hook, kind, have))
    return out


def compare(a, b):
    out = []
    for key in sorted(set(a.sigs) | set(b.sigs)):
        if key not in a.mm_added and key not in b.mm_added and a.sigs.get(key) != b.sigs.get(key):
            out.append("%s: %r -> %r" % (key, a.sigs.get(key), b.sigs.get(key)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", action="append", required=True)
    ap.add_argument("--mod", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mod", "mistrimulti", "gml"))
    args = ap.parse_args()
    mod = Mod(args.mod)
    games = [Game(d) for d in args.game]
    bad = 0
    for g in games:
        found = check(mod, g)
        print("%s: %d finding(s)" % (g.dir, len(found)))
        for line in found:
            print("  " + line)
        bad += len(found)
    if len(games) == 2:
        diff = compare(*games)
        print("definitions changed between the two sets: %d" % len(diff))
        for line in diff:
            print("  " + line)
        bad += len(diff)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
