"""Identity binding and abuse limits of the mod (MistriMultiTrust.gml) on the event layer, engine stubbed.

    python3 tests/test_trust_gml.py

MistriMultiTrust.gml, MistriMultiPlayerSync.gml, MistriMultiIdentity.gml, MistriMultiProgress.gml and the terrain feature
run unmodified in tests/gml_subset.py over the simulated helpers and network (tests/event_sim.py). The stubs are the
FeatureNode of test_event_features.py plus a fake file system and the helper's auth_<slot>.json verdicts: the helper's
side (handshake, tags, deny list) is tested in tests/test_trust.py with the real assembly.

Not provable here: how GameMaker reads files, the F7 / Shift+F7 hotkey chord, the notification popup.
"""
import json

from event_sim import World
import gml_subset as gml
from test_event_features import Driver, FeatureNode

FP_A = "a" * 32
FP_B = "b" * 32
FP_C = "c" * 32


class TrustNode(FeatureNode):
    extra_files = FeatureNode.extra_files + ("MistriMultiTrust.gml",)

    def builtins(self):
        self.files = {}
        self.notes = []
        out = super().builtins()
        out.update({
            "file_exists": self.file_exists, "try_read_json_file": self.read_json, "save_text_file": self.save,
            "file_rename": self.rename, "read_text_file": self.read_text, "mmapi_mod_data_dir": lambda name: "mod",
            "create_notification": self.notes.append, "ANCHOR": gml.GStruct(wrap_for_local=lambda text: text),
            "mistrimulti_player_path": lambda uid: "players/" + uid,
        })
        return out

    def file_exists(self, path):
        return path in self.files or (path.startswith("players/") and path[len("players/"):] in self.store)

    def read_text(self, path):
        return self.files[path]

    def read_json(self, path):
        try:
            return gml.from_json(json.loads(self.files[path]))
        except (KeyError, ValueError):
            return None

    def save(self, path, text):
        self.files[path] = text

    def rename(self, old, new):
        self.files[new] = self.files.pop(old)

    def setup(self):
        super().setup()
        self.rt.update(bridge="bridge", enabled=True)
        self.interp.call("mistrimulti_trust_initialize")

    def verdict(self, slot, fp, state=1, gen=1, reject=0):
        self.files[f"bridge/auth_{slot}.json"] = json.dumps({"fp": fp, "gen": gen, "state": state, "reject": reject})

    def trust(self):
        return json.loads(self.files["mod/trust.json"])

    def errors(self):
        return self.rt["player_error"]


class NamedDriver(Driver):
    def frame(self):
        return dict(super().frame(), name="Friend" + str(self.node.slot))


def make_world(seed, guests=2, **faults):
    world = World(seed, {i: TrustNode for i in range(guests + 1)}, **faults)
    for game in world.games.values():
        game.feature = NamedDriver(game)
    return world


def request(node, uid):
    node.rt["player_request"] = ""
    return node.call("mistrimulti_event_emit", "profile_request", {"world": "world_1", "uid": uid}, 0)


def connected(world, host, count=2):
    world.run(4000)
    for slot in range(1, count + 1):
        host.verdict(slot, {1: FP_A, 2: FP_B, 3: FP_C}[slot])


def test_first_use_binds():
    world = make_world(41)
    host, guest, other = (world.games[i].node for i in range(3))
    connected(world, host)
    uid = guest.rt["uid"]
    assert request(guest, uid)
    world.run(3000)
    assert guest.calls == [("fresh",)] and guest.errors() == "", guest.errors()
    assert host.trust()["bound"][uid]["fp"] == FP_A
    # the same install, new session (re-entering the world): still admitted, nothing to approve
    guest.interp.call("mistrimulti_player_reset_session")
    guest.calls.clear()
    assert request(guest, uid)
    world.run(3000)
    assert guest.errors() == "" and not host.rt["trust"]["pending"]
    print("PASS: a new identity is bound to the verified install on first use; the same install is admitted again")


def test_claim_by_another_install():
    world = make_world(42)
    host, guest, other = (world.games[i].node for i in range(3))
    connected(world, host)
    uid = guest.rt["uid"]
    profile = {"v": 1, "uid": uid, "world": "world_1", "inventory": ["sword"]}
    assert request(guest, uid)
    world.run(3000)
    host.store[uid] = {"revision": 1, "data": profile}
    # the friend leaves; someone else claims the same id (a Steam id is only a claim)
    guest.interp.call("mistrimulti_events_reset")
    host.rt["player_sessions"][1] = None
    host.verdict(1, FP_A, state=0)
    other.rt["uid"] = uid
    world.run(1500)
    assert request(other, uid)
    world.run(3000)
    assert "approval" in other.errors() and FP_B[:8] in other.errors(), other.errors()
    assert not any(c[0] == "restore" for c in other.calls), "the record must not be handed over"
    assert len(host.rt["trust"]["pending"]) == 1 and host.trust()["bound"][uid]["fp"] == FP_A
    assert any("approve" in n.lower() for n in host.notes), host.notes
    # a second try neither duplicates the request nor leaks anything
    assert request(other, uid)
    world.run(2000)
    assert len(host.rt["trust"]["pending"]) == 1
    # the record is not accepted from the claimant either: an upload for the uid is ignored
    other.rt["player_revision"] = 1
    other.interp.call("mistrimulti_player_send", "profile_update", 0, other.rt["epoch"], 1, other.data(dict(profile, inventory=["stolen"])))
    world.run(4000)
    assert host.store[uid]["data"]["inventory"] == ["sword"]
    # the host approves (F7): the claimant now receives the record
    assert host.call("mistrimulti_trust_approve") is True
    world.run(6000)
    assert ("restore", profile) in other.calls, other.calls
    assert host.trust()["bound"][uid]["fp"] == FP_B
    # the old install now needs approval to come back
    host.verdict(1, FP_A)
    guest.rt["epoch"] += "x"
    guest.interp.call("mistrimulti_player_reset_session")
    assert request(guest, uid)
    world.run(3000)
    assert len(host.rt["trust"]["pending"]) == 1 and host.rt["trust"]["pending"][0]["fp"] == FP_A
    print("PASS: another install claiming a bound id gets nothing until the host approves; approval hands over the record")


def test_refuse_bans():
    world = make_world(43)
    host, guest, other = (world.games[i].node for i in range(3))
    connected(world, host)
    uid = guest.rt["uid"]
    request(guest, uid)
    world.run(3000)
    other.rt["uid"] = uid
    guest.interp.call("mistrimulti_events_reset")
    host.rt["player_sessions"][1] = None
    host.verdict(1, FP_A, state=0)
    world.run(1500)
    host.files["mod/deny.txt"] = "# my own list\n10.1.2.3"
    request(other, uid)
    world.run(3000)
    assert host.call("mistrimulti_trust_refuse") is True
    deny = host.files["mod/deny.txt"]
    assert deny.startswith("# my own list\n10.1.2.3\n") and FP_B in deny and "Friend2" in deny, deny
    assert host.trust()["denied"][0]["fp"] == FP_B and not host.rt["trust"]["pending"]
    assert host.call("mistrimulti_trust_approve") is False
    print("PASS: refusing a claim bans the install in deny.txt (hand-written lines kept) and trust.json")


def test_legacy_record_needs_approval():
    world = make_world(44)
    host, guest, other = (world.games[i].node for i in range(3))
    connected(world, host)
    uid = guest.rt["uid"]
    host.store[uid] = {"revision": 3, "data": {"v": 1, "uid": uid, "world": "world_1", "inventory": ["old"]}}
    request(guest, uid)
    world.run(3000)
    assert "approval" in guest.errors() and len(host.rt["trust"]["pending"]) == 1
    assert uid not in host.rt["trust"]["bound"]
    assert host.call("mistrimulti_trust_approve") is True
    world.run(6000)
    assert any(c[0] == "restore" for c in guest.calls) and host.trust()["bound"][uid]["fp"] == FP_A
    print("PASS: a record that predates bindings is claimed only with the host's approval")


def test_upload_requires_the_verified_install():
    world = make_world(45)
    host, guest, other = (world.games[i].node for i in range(3))
    connected(world, host)
    uid = guest.rt["uid"]
    request(guest, uid)
    world.run(3000)
    profile = {"v": 1, "uid": uid, "world": "world_1", "inventory": ["a"]}
    guest.rt["player_revision"] = 1
    guest.interp.call("mistrimulti_player_send", "profile_update", 0, guest.rt["epoch"], 1, guest.data(profile))
    world.run(5000)
    assert host.store[uid]["data"] == profile
    # the slot changes hands underneath (the helper now reports another install): uploads are ignored
    host.verdict(1, FP_C, gen=2)
    guest.rt["player_revision"] = 2
    guest.interp.call("mistrimulti_player_send", "profile_update", 0, guest.rt["epoch"], 2, guest.data(dict(profile, inventory=["b"])))
    world.run(5000)
    assert host.store[uid]["data"] == profile and host.store[uid]["revision"] == 1
    host.verdict(1, FP_A, state=0, gen=3)
    guest.interp.call("mistrimulti_player_send", "profile_update", 0, guest.rt["epoch"], 2, guest.data(dict(profile, inventory=["c"])))
    world.run(5000)
    assert host.store[uid]["revision"] == 1, "an unauthenticated slot stores nothing"
    print("PASS: an upload is stored only while the slot still belongs to the install the record is bound to")


def test_unverified_and_limits_on_identities():
    world = make_world(46)
    host, guest, other = (world.games[i].node for i in range(3))
    world.run(4000)
    uid = guest.rt["uid"]
    # no verdict from the helper (it has not authenticated this slot): nothing is handed out
    request(guest, uid)
    world.run(3000)
    assert "not verified" in guest.errors() and not host.rt["trust"]["bound"], guest.errors()
    host.verdict(1, FP_A)
    # one install may hold at most four identities, and bindings are bounded
    for n in range(4):
        fake = "local:" + f"{n + 100:032x}"
        verdict = host.interp.call("mistrimulti_trust_admit", 1, fake, "x", None)
        assert verdict["ok"] is True, n
    verdict = host.interp.call("mistrimulti_trust_admit", 1, "local:" + f"{999:032x}", "x", None)
    assert verdict["ok"] is False and "room" in verdict["message"]
    for n in range(300):
        host.verdict(1, f"{n + 1:032x}")
        host.interp.call("mistrimulti_trust_admit", 1, "local:" + f"{n + 5000:032x}", "x", None)
    assert len(host.trust()["bound"]) <= 256
    for n in range(20):
        host.verdict(1, f"{n + 1000:032x}")
        host.interp.call("mistrimulti_trust_admit", 1, "local:" + f"{n + 100:032x}", "x", {"world": "w", "uid": "x"})
    assert len(host.rt["trust"]["pending"]) <= 8
    print("PASS: unverified slots get nothing; identities per install, bindings and open approvals are bounded")


def test_damaged_trust_file():
    world = make_world(47)
    host, guest, other = (world.games[i].node for i in range(3))
    host.files["mod/trust.json"] = "{ not json"
    host.interp.call("mistrimulti_trust_initialize")
    assert "mod/trust.json.bad" in host.files and "mod/trust.json" not in host.files
    host.files["mod/trust.json"] = json.dumps({"v": 1, "bound": {"local:" + "1" * 32: {"fp": FP_A, "name": "a"},
        "bad id": {"fp": FP_A}, "local:" + "2" * 32: {"fp": "xyz"}}, "denied": [{"fp": FP_B}, {"fp": 7}, "x"]})
    host.interp.call("mistrimulti_trust_initialize")
    bound = host.rt["trust"]["bound"]
    assert list(bound.keys()) == ["local:" + "1" * 32] and len(host.rt["trust"]["denied"]) == 1
    print("PASS: a damaged trust.json is kept aside and treated as empty; invalid entries are skipped")


def test_rate_limits():
    world = make_world(48)
    host, guest, other = (world.games[i].node for i in range(3))
    connected(world, host)
    done = {1: 0, 2: 0}

    def handler(slot):
        def run(player, data, ctx):
            done[player] += 1
            return {}
        return run
    handlers = host.handlers(on_request=lambda player, data, ctx: (done.__setitem__(player, done[player] + 1) or {}))
    for node in (host, guest, other):
        node.call("mistrimulti_event_register", "flood", handlers)
    world.run(500)
    # a guest sends 400 requests at once: the host handles them at its own pace, none is lost or applied twice,
    # and the other guest's single request is not held up behind them
    for n in range(400):
        assert guest.call("mistrimulti_event_request", "flood", {"n": n}) is not None or n >= 64
    sent = guest.call("mistrimulti_events_debug")["requests"]
    world.run(1000)
    first = done[1]
    other.call("mistrimulti_event_request", "flood", {"n": "friend"})
    world.run(1000)
    assert done[2] == 1, "the other guest is served while the flood is throttled"
    world.run(15000)
    assert done[1] == sent and done[1] <= 64, (done, sent)
    assert host.rt["trust"]["failures"] >= 0
    # a sustained flood is held to the rate: 200 per second offered, about 40 per second handled once the burst is spent
    done[1] = 0
    limit_hits = host.rt["trust"]["failures"]
    offered = 0
    for second in range(6):
        for n in range(200):
            if guest.call("mistrimulti_event_request", "flood", {"n": n}) is not None:
                offered += 1
        world.run(1000)
    assert done[1] <= 6 * 40 + 80 + 20, done
    assert host.rt["trust"]["failures"] > limit_hits, "the limiter must have refused some events"
    world.run(20000)
    assert done[1] == offered, (done[1], offered)
    # new event streams (a guest that restarts its event layer over and over) are limited too
    peers = []
    host.call("mistrimulti_event_register", "watch", host.handlers(on_peer=lambda slot, joined, stream: peers.append((slot, joined))))
    world.run(1000)
    peers.clear()
    for n in range(40):
        guest.call("mistrimulti_events_reset")
        world.run(300)
    joins = [p for p in peers if p == (1, True)]
    assert 1 <= len(joins) <= 8, f"{len(joins)} stream restarts were honoured"
    print("PASS: per-guest limits: floods are throttled without loss, other guests are not starved, stream restarts are bounded")


def test_blob_rate():
    world = make_world(49)
    host, guest, other = (world.games[i].node for i in range(3))
    connected(world, host)
    got = []
    handlers = host.handlers(on_blob=lambda player, text, meta: got.append((player, len(text))) or True)
    for node in (host, guest, other):
        node.call("mistrimulti_event_register", "bulk", handlers)
    world.run(500)
    for n in range(6):
        assert guest.call("mistrimulti_event_send_blob", "bulk", "x" * 200000, 0, {"n": n})
        world.run(1500)
    world.run(30000)
    assert len(got) == 6 and all(size == 200000 for _, size in got), got
    print("PASS: blob uploads within the byte rate arrive whole")


def test_guest_pins_the_host():
    world = make_world(50)
    host, guest, other = (world.games[i].node for i in range(3))
    connected(world, host)
    guest.rt["world_key"] = "w1"
    guest.verdict(0, FP_A, state=2)
    assert guest.interp.call("mistrimulti_trust_host_ok") is True
    pinned = json.loads(guest.files["mod/known_hosts.json"])
    assert pinned["hosts"]["w1"] == FP_A
    guest.rt["trust"]["host_pin"] = ""
    guest.verdict(0, FP_B, state=2)
    assert guest.interp.call("mistrimulti_trust_host_ok") is False and "changed" in guest.rt["trust"]["warning"]
    text = guest.interp.call("mistrimulti_trust_status_text")
    assert "changed" in text
    # the player data tick refuses to send the request while the host is unverified
    guest.rt["world_key"] = ""
    assert guest.call("mistrimulti_trust_accept_host") is False
    guest.rt["world_key"] = "w1"
    assert guest.call("mistrimulti_trust_approve") is True
    assert guest.interp.call("mistrimulti_trust_host_ok") is True
    assert json.loads(guest.files["mod/known_hosts.json"])["hosts"]["w1"] == FP_B
    # not authenticated yet
    guest.rt["trust"]["host_pin"] = ""
    guest.verdict(0, "", state=1)
    assert guest.interp.call("mistrimulti_trust_host_ok") is False
    # reasons the helper gives are shown to the player
    for reason, word in ((1, "password"), (2, "banned"), (3, "slot"), (6, "needs a password")):
        guest.rt["trust"]["warning"] = ""
        guest.verdict(0, "", state=0, reject=reason)
        assert word in guest.interp.call("mistrimulti_trust_status_text"), reason
    print("PASS: a guest pins each hosted world to the host's verified identity and says why a join was refused")


TESTS = [test_first_use_binds, test_claim_by_another_install, test_refuse_bans, test_legacy_record_needs_approval,
         test_upload_requires_the_verified_install, test_unverified_and_limits_on_identities, test_damaged_trust_file,
         test_rate_limits, test_blob_rate, test_guest_pins_the_host]

if __name__ == "__main__":
    import sys
    for test in TESTS:
        if len(sys.argv) > 1 and test.__name__ not in sys.argv[1:]:
            continue
        test()
    print("OK")
