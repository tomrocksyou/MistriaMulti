"""Mutation check for MistriMultiRanch.gml: each mutation must make at least one ranch test fail.

    python3 tests/mutate_ranch.py

Breaks one rule of the GML at a time (charging twice, skipping a refund, accepting any number, ...), runs the tests that
should notice, and restores the file. Exit status 1 if a mutation goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GML = ROOT / "mod/mistrimulti/gml/MistriMultiRanch.gml"

MUTATIONS = [
    ("charge twice", '''        if (!__mistrimulti_ranch_charge(result.pay)) __mistrimulti_ranch_say("You no longer had everything for that.");''',
     '''        __mistrimulti_ranch_charge(result.pay); __mistrimulti_ranch_charge(result.pay);''', ["test_feed_pays_once"]),
    ("no sale clawback", '''        if (p.a == "sell") ARI.modify_gold(-p.g);
        else if''', '''        if (p.a == "sell") ARI.modify_gold(0);
        else if''', ["test_adopt_and_sell"]),
    ("no refund of a purchase", '''        else if (is_struct(p[$ "give"])) __mistrimulti_ranch_give(p.give);''', '''        else if (false) __mistrimulti_ranch_give(p.give);''', ["test_expansion_race"]),
    ("feed not vetoed", '''    __mistrimulti_ranch_ask_paid(rc, { a: treat ? "treat" : "feed", i: me.idx, it: item.item_id }, {});
    return false;''', '''    __mistrimulti_ranch_ask_paid(rc, { a: treat ? "treat" : "feed", i: me.idx, it: item.item_id }, {});
    return undefined;''', ["test_feed_pays_once"]),
    ("unresolved sale ignored", '''        if (struct_exists(rc.known, string(u.i))) {
            ARI.modify_gold(-u.g);''', '''        if (false) {
            ARI.modify_gold(-u.g);''', ["test_sale_with_lost_answer"]),
    ("guest runs production", '''    if (__mistrimulti_ranch_on("join")) return false;
    return undefined;''', '''    return undefined;''', ["test_solo_and_hooks"]),
    ("pool not emptied", '''    rc.pool[$ d.b] = [];
    __mistrimulti_ranch_publish(rc, b, -1, 0);''', '''    __mistrimulti_ranch_publish(rc, b, -1, 0);''', ["test_products_pool"]),
    ("no price check on adopt", '''    var cost = animal.pricing.buy_price * animal.pricing.tier_sell_price_multipliers[variant.tier];''', '''    var cost = 1;''', ["test_adopt_and_sell"]),
    ("placement not vetoed", '''                o: ctx.proto.object_id, r: ctx.rotation, it: use.item.item_id, inf: inf }, {});
            return false;''', '''                o: ctx.proto.object_id, r: ctx.rotation, it: use.item.item_id, inf: inf }, {});
            return undefined;''', ["test_furniture"]),
    ("hostile ids accepted", '''function __mistrimulti_ranch_int(v, lo, hi) {
    return is_real(v) && v == floor(v) && v >= lo && v <= hi;''', '''function __mistrimulti_ranch_int(v, lo, hi) {
    return is_real(v);''', ["test_hostile_input"]),
    ("snapshot not sent to joiner", '''    if (r.enabled && r.mode == "host" && joined) __mistrimulti_ranch_want_snapshot(__mistrimulti_ranch(), slot);''', '''    if (false) __mistrimulti_ranch_want_snapshot(__mistrimulti_ranch(), slot);''', ["test_furniture"]),
    ("room not checked", '''    return is_struct(peer) && peer[$ "room"] == room;''', '''    return true;''', ["test_room_rules"]),
]

original = GML.read_text()
bad = 0
try:
    for name, old, new, tests in MUTATIONS:
        if old not in original:
            print("MISSING PATTERN:", name)
            bad += 1
            continue
        GML.write_text(original.replace(old, new, 1))
        out = subprocess.run([sys.executable, "test_ranch.py"] + tests, cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
        caught = out.returncode != 0
        print(("caught " if caught else "NOT CAUGHT ") + name)
        bad += 0 if caught else 1
finally:
    GML.write_text(original)
sys.exit(1 if bad else 0)
