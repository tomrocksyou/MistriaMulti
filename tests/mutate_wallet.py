"""Mutation check for MistriMultiWallet.gml and the shipping-bin parts of MistriMultiContainers.gml: each mutation must make
at least one wallet test fail.

    python3 tests/mutate_wallet.py

Breaks one rule of the GML at a time (forgiving a debt, letting the pool go negative, accepting any amount, paying a bin twice,
...), runs the tests that should notice, and restores the files. Exit status 1 if a mutation goes unnoticed.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WALLET = ROOT / "mod/mistrimulti/gml/MistriMultiWallet.gml"
CONTAINERS = ROOT / "mod/mistrimulti/gml/MistriMultiContainers.gml"

MUTATIONS = [
    (WALLET, "spending beyond the pool is forgiven", "w.debt = min(w.debt - d - take, MISTRIMULTI_WALLET_MAX_POOL);",
     "w.debt = 0;", ["test_concurrent_spending"]),
    (WALLET, "income does not pay the debt first", "var pay = min(w.debt, d);", "var pay = 0;", ["test_concurrent_spending"]),
    (WALLET, "the pool can go negative", "var take = min(w.pool, -d);", "var take = -d;", ["test_concurrent_spending"]),
    (WALLET, "an answered delta stays pending", [("if (ctx.mine && struct_exists(w.pending, ctx.id)) struct_remove(w.pending, ctx.id);", ""),
                                                 ("        if (struct_exists(w.pending, ctx.id)) struct_remove(w.pending, ctx.id);\n        if (!is_struct(result))",
                                                  "        if (!is_struct(result))")], None, ["test_mirror_and_basic"]),
    (WALLET, "answers do not carry the balance", "        __mistrimulti_wallet_take(w, result);\n        __mistrimulti_wallet_pull(w);\n    } catch (e) {\n        mmapi_warn_rate_limited(\"mistrimulti_wallet\", \"mistrimulti\", \"A wallet answer",
     "        __mistrimulti_wallet_pull(w);\n    } catch (e) {\n        mmapi_warn_rate_limited(\"mistrimulti_wallet\", \"mistrimulti\", \"A wallet answer", ["test_mirror_and_basic"]),
    (WALLET, "fractional amounts accepted", "return is_real(d) && d == floor(d) && d >=", "return is_real(d) && d >=", ["test_hostile_requests"]),
    (WALLET, "amount range not checked", " && d >= -MISTRIMULTI_WALLET_MAX_DELTA && d <= MISTRIMULTI_WALLET_MAX_DELTA;", ";",
     ["test_hostile_requests"]),
    (WALLET, "a guest pays the bin sale too", "if (payout) return 0;", "if (false) return 0;", ["test_day_end_host_first", "test_day_end_guest_first"]),
    (WALLET, "every change of the sequence is dropped", "w.eod_taken = sequence;", "", ["test_empty_bins_and_payments_around_the_end_of_day"]),
    (WALLET, "host changes not announced", "        w.dirty = true;\n        return w.pool - before;", "        return w.pool - before;",
     ["test_mirror_and_basic"]),
    (WALLET, "no snapshot for a joining guest (nor a request of its own)", [("if (r.mode == \"host\") w.snaps[slot] = joined && slot != 0;",
     "if (r.mode == \"host\") w.snaps[slot] = false;"), ("else if (slot == 0 && joined) w.resync = true;", "")], None, ["test_late_joiner_snapshot"]),
    (WALLET, "the commit's day is not checked", "c[$ \"day\"] == string(CALENDAR.time)", "true", ["test_host_restart"]),
    (WALLET, "the commit is never used", "            pool = commit.gold;", "            pool = pool;", ["test_host_restart"]),
    (WALLET, "the host does not set its gold from the pool", "    if (want != undefined && ARI.get_gold() != want) ARI.set_gold(want);", "",
     ["test_mirror_and_basic", "test_late_joiner_snapshot"]),
    (WALLET, "a lost request stays pending forever", "        if (struct_exists(w.pending, ctx.id)) struct_remove(w.pending, ctx.id);\n        if (!is_struct(result))",
     "        if (!is_struct(result))", ["test_host_restart"]),
    (CONTAINERS, "a guest's emptied bin is not shown again", "if (c.bin) emptied = true;", "", ["test_day_end_guest_first"]),
    (CONTAINERS, "a bin emptied by the day end counts as a player's removal",
     "var ref = c.bin && __mistrimulti_ct_sleeping() ? __mistrimulti_ct_state(c.node.inventory.slot(s.i)) : c.base[s.i];",
     "var ref = c.base[s.i];", ["test_day_end_faults_and_next_day"]),
]

originals = {path: path.read_text() for path in (WALLET, CONTAINERS)}
bad = 0
try:
    for path, name, old, new, tests in MUTATIONS:
        pairs = old if isinstance(old, list) else [(old, new)]
        text = originals[path]
        if any(a not in text for a, _b in pairs):
            print("MISSING PATTERN:", name)
            bad += 1
            continue
        for a, b in pairs:
            text = text.replace(a, b, 1)
        path.write_text(text)
        out = subprocess.run([sys.executable, "test_wallet.py"] + tests, cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
        caught = out.returncode != 0
        print(("caught " if caught else "NOT CAUGHT ") + name)
        bad += 0 if caught else 1
        path.write_text(originals[path])
finally:
    for path, text in originals.items():
        path.write_text(text)
sys.exit(1 if bad else 0)
