"""Tests scripts/audit-gml-ids.py, the check of every game identifier the mod uses against the game's own scripts.

    python3 tests/test_engine_audit.py
    MISTRIA_GML=<scripts dir>[:<second dir>] python3 tests/test_engine_audit.py     # also audits the real game scripts

The fixture is a tiny made-up game (the real scripts are never copied into the repo). Each mutation below must be reported.
"""
import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("audit", os.path.join(HERE, "..", "scripts", "audit-gml-ids.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

GAME = {
    "scripts/Items.gml": "enum ItemUse { Eat, Drink }\nfunction drop_item(item, xx, yy) { return 1; }\n#macro ARI global.__ari\n"
                         "function find_animal(idx, include_daycare=false) { return idx; }\n",
    "scripts/Ari.gml": "function Ari() constructor { self.gold = 0; self.mana_current = 0; }\n",
    "scripts/mmapi/mmapi.gml": "function mmapi_log_info(mod_name, msg) {}\nfunction mmapi_on(hook_name, handler, opts) {}\n"
                               "function mmapi_filter(hook_name, handler, opts) {}\n",
    "scripts/mmapi/mmapi_hook_catalog.gml": 'function mmapi_hook_catalog() { return [\n"game.new_day", "event",\n'
                                            '"player.gold_delta", "filter",\n]; }\n',
    "scripts/mistriamulti_mistriamulti/Copy.gml": "function ignored_copy_of_the_mod() { not_a_game_function(); }\n",
}
MOD = ("function mistrimulti_new_day(ctx) { drop_item(1, 2, 3); var u = ItemUse.Eat; ARI.gold = 1; mmapi_log_info(\"m\", \"x\"); }\n"
       "function mistrimulti_gold(value, ctx) { return value + ARI.mana_current; }\n"
       "function mistrimulti_register() { mmapi_on(\"game.new_day\", mistrimulti_new_day); "
       "mmapi_filter(\"player.gold_delta\", mistrimulti_gold); }\n")


def write(root, files):
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)


def run(game_files, mod_text, second=None):
    tmp = tempfile.mkdtemp()
    try:
        write(tmp + "/g1", game_files)
        write(tmp + "/mod", {"M.gml": mod_text})
        games = [audit.Game(tmp + "/g1")]
        if second is not None:
            write(tmp + "/g2", second)
            games.append(audit.Game(tmp + "/g2"))
        mod = audit.Mod(tmp + "/mod")
        out = audit.check(mod, games[0])
        if second is not None:
            out += audit.compare(*games)
        return out
    finally:
        shutil.rmtree(tmp)


def expect(label, found, needle):
    hit = [f for f in found if needle in f]
    if needle is None or needle == "":
        ok = not found
    else:
        ok = bool(hit)
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else "  got: %r" % found))
    return ok


def main():
    results = []
    results.append(expect("clean fixture reports nothing", run(GAME, MOD), ""))
    results.append(expect("function the game never mentions", run(GAME, MOD.replace("drop_item(1, 2, 3)", "drop_itm(1, 2, 3)")), "drop_itm"))
    results.append(expect("enum member missing", run(GAME, MOD.replace("ItemUse.Eat", "ItemUse.Gulp")), "ItemUse.Gulp"))
    results.append(expect("field that exists nowhere", run(GAME, MOD.replace("ARI.mana_current", "ARI.mana_curent")), "mana_curent"))
    results.append(expect("MMAPI function not installed", run(GAME, MOD.replace("mmapi_log_info", "mmapi_log_note")), "mmapi_log_note"))
    results.append(expect("hook not in the catalog", run(GAME, MOD.replace('"game.new_day"', '"game.new_night"')), "game.new_night"))
    results.append(expect("hook registered with the wrong kind", run(GAME, MOD.replace("mmapi_filter(", "mmapi_on(")), "hook kind differs"))
    results.append(expect("mod copy inside the game dir is not evidence", run(GAME, MOD + "function x() { not_a_game_function(); }"),
                          "not_a_game_function"))
    changed = dict(GAME)
    changed["scripts/Items.gml"] = GAME["scripts/Items.gml"].replace("xx, yy", "xx, yy, z_offset=0")
    results.append(expect("changed signature between two sets", run(GAME, MOD, changed), "drop_item"))
    removed = dict(GAME)
    removed["scripts/Items.gml"] = GAME["scripts/Items.gml"].replace("function find_animal(idx, include_daycare=false) { return idx; }\n", "")
    results.append(expect("function removed in the second set", run(GAME, MOD, removed), "find_animal"))
    enum2 = dict(GAME)
    enum2["scripts/Items.gml"] = GAME["scripts/Items.gml"].replace("Eat, Drink", "Eat")
    results.append(expect("enum member removed in the second set", run(GAME, MOD, enum2), "enum ItemUse"))
    macro2 = dict(GAME)
    macro2["scripts/Items.gml"] = GAME["scripts/Items.gml"].replace("global.__ari", "global.__player")
    results.append(expect("macro changed in the second set", run(GAME, MOD, macro2), "#ARI"))
    patched = dict(GAME)
    patched["scripts/Items.gml"] = GAME["scripts/Items.gml"] + "static Items = function(ids) { return 1; } // mmapi_recipe_items\n"
    results.append(expect("definition added by an MMAPI patch is ignored", run(GAME, MOD, patched), ""))
    for path in filter(None, os.environ.get("MISTRIA_GML", "").split(os.pathsep)):
        mod = audit.Mod(os.path.join(HERE, "..", "mod", "mistrimulti", "gml"))
        found = audit.check(mod, audit.Game(path))
        results.append(expect("real game scripts " + path, found, ""))
    if not all(results):
        print("FAILED")
        return 1
    print("all %d checks passed" % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
