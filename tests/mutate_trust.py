"""Mutation check for the trust code: each mutation breaks one rule and at least one test must notice.

    python3 tests/mutate_trust.py            # all (about 25 minutes: every assembly mutation is rebuilt and tested)
    python3 tests/mutate_trust.py cookie     # only mutations whose name contains "cookie"

Breaks one rule at a time in helper/include/{auth,core}.inc, linux/launcher.asm and the GML (a bad tag accepted, the cookie
or password ignored, a ban or a limit skipped, an identity claimed by another install...), builds a throw-away helper, runs
the tests that should notice, and restores the file. Exit status 1 if a mutation goes unnoticed. Linux only.
"""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
AUTH, CORE = "helper/include/auth.inc", "helper/include/core.inc"
LAUNCHER = "linux/launcher.asm"
TRUST, PLAYERSYNC, EVENTS = ("mod/mistrimulti/gml/MistriMultiTrust.gml", "mod/mistrimulti/gml/MistriMultiPlayerSync.gml",
                             "mod/mistrimulti/gml/MistriMultiEvents.gml")

# (name, file, old text (must occur exactly once), new text, kind, tests that must fail)
MUTATIONS = [
    ("tag never checked", AUTH, "    mov r8d, TAG\n    call ct_equal\nEND_FN", "    mov r8d, TAG\n    call ct_equal\n    mov eax, 1\nEND_FN",
     "helper", ["test_no_handshake", "test_replay_and_tamper", "test_guest_join"]),
    ("cookie not checked", AUTH, "    lea rdx, [packet_in+36]\n    mov r8d, 16\n    call ct_equal\n    test eax, eax\n    jz .bad\n",
     "    lea rdx, [packet_in+36]\n    mov r8d, 16\n    call ct_equal\n    test eax, eax\n    nop\n", "helper", ["test_replay_and_tamper", "test_cookie_expiry"]),
    ("cookie never expires", AUTH, "    cmp ecx, eax\n    jne .bad\n.window_ok:", "    cmp ecx, eax\n    nop\n.window_ok:", "helper", ["test_cookie_expiry"]),
    ("replayed PROOF accepted", AUTH, "    call ct_equal\n    test eax, eax\n    jnz .done\n    inc ebx\n    cmp ebx, 8",
     "    call ct_equal\n    test eax, eax\n    nop\n    inc ebx\n    cmp ebx, 8", "helper", ["test_replay_and_tamper"]),
    ("password ignored by the host", AUTH, "    cmp dword [pass_len], 0\n    je .nopw\n    lea rcx, [my_fp]", "    cmp dword [pass_len], 0\n    jmp .nopw\n    lea rcx, [my_fp]",
     "helper", ["test_password"]),
    ("fingerprint need not name the key", AUTH, "    test eax, eax\n    jz .authfail\n    mov dword [is_new], 1", "    test eax, eax\n    nop\n    mov dword [is_new], 1",
     "helper", ["test_hijack"]),
    ("stored key ignored for a known fingerprint", AUTH, "    test r13, r13\n    jz .register\n", "    jmp .register\n", "helper", ["test_identity_keys"]),
    ("deny list ignores fingerprints", AUTH, "    test r12, r12\n    jz .ips\n.fps:", "    jmp .ips\n.fps:", "helper", ["test_deny"]),
    ("deny list ignores addresses", AUTH, "    cmp [r14+rbx*4], r13d\n    je .yes", "    cmp [r14+rbx*4], r13d\n    jne .yes", "helper", ["test_deny"]),
    ("live slot can be taken", AUTH, "    test eax, eax\n    jz .busy\n.slot_free:", "    test eax, eax\n    nop\n.slot_free:", "helper", ["test_hijack"]),
    ("snapshot limit off", CORE, "%define FRM_BUCKET_ADD 3\n%define FRM_BUCKET_CAP 60", "%define FRM_BUCKET_ADD 3000\n%define FRM_BUCKET_CAP 60000", "helper", ["test_limits"]),
    ("packet limit off", CORE, "%define PKT_BUCKET_ADD 40\n%define PKT_BUCKET_CAP 800", "%define PKT_BUCKET_ADD 40000\n%define PKT_BUCKET_CAP 800000", "helper", ["test_limits"]),
    ("stranger handshake limit off", AUTH, "    mov eax, [r10]\n    test eax, eax\n    jz .no\n    dec eax", "    mov eax, [r10]\n    test eax, eax\n    nop\n    dec eax", "helper", ["test_limits"]),
    ("guest believes any WELCOME", AUTH, "    mov r8d, 16\n    call ct_equal\n    test eax, eax\n    jz .done\n    mov dword [g_state], 2",
     "    mov r8d, 16\n    call ct_equal\n    test eax, eax\n    nop\n    mov dword [g_state], 2", "helper", ["test_guest_rejections"]),
    ("guest takes data from any address", CORE, "    cmp rax, [host_address]\n    jne .bad\n    lea rdx, [g_sk]", "    cmp rax, [host_address]\n    nop\n    nop\n    lea rdx, [g_sk]",
     "helper", ["test_guest_join"]),
    ("bad password opens the room", AUTH, "    cmp dword [pass_len], -1\n    je .badpass", "    cmp dword [pass_len], -1\n    nop\n    nop", "helper", ["test_config"]),
    ("unchecked argument", CORE, "    call pl_arg\n    test rax, rax                  ; an argument that cannot be converted is invalid, never a null pointer\n    jz .bad\n    cmp dword [rax], 'host'",
     "    call pl_arg\n    cmp dword [rax], 'host'", "helper-windows", ["test_config"]),
    ("launcher forgets the password", LAUNCHER, "    cmp byte [a_pass], 0\n    je .nopass\n    lea rcx, [t_auth_pass]", "    cmp byte [a_pass], 0\n    jmp .nopass\n    lea rcx, [t_auth_pass]",
     "launcher", ["test_password"]),
    ("another install takes the identity", TRUST, "        if (bound.fp == fp) return { ok: true };", "        if (true) return { ok: true };", "gml", ["test_claim_by_another_install"]),
    ("a record without binding is open to all", TRUST, "    if (file_exists(path) || file_exists(path + \".bak\")) return __mistrimulti_trust_pending(player, uid, name, request, fp, \"unbound\");",
     "    if (false) return __mistrimulti_trust_pending(player, uid, name, request, fp, \"unbound\");", "gml", ["test_legacy_record_needs_approval"]),
    ("upload from a slot that changed hands", TRUST, "    return auth != undefined && auth.state == 1 && is_struct(bound) && bound.fp == auth.fp;", "    return true;",
     "gml", ["test_upload_requires_the_verified_install"]),
    ("bindings not saved", TRUST, "    r.trust.bound[$ uid] = { fp: fp, name: is_string(name) ? string_copy(name, 1, 64) : \"\" };\n    mistrimulti_trust_save();",
     "    r.trust.bound[$ uid] = { fp: fp, name: is_string(name) ? string_copy(name, 1, 64) : \"\" };", "gml", ["test_first_use_binds"]),
    ("no cap on identities per install", TRUST, "|| __mistrimulti_trust_installs_of(fp) >= MISTRIMULTI_TRUST_PER_INSTALL", "|| false", "gml", ["test_unverified_and_limits_on_identities"]),
    ("approvals unbounded", TRUST, "    if (array_length(list) >= MISTRIMULTI_TRUST_PENDING_MAX) {", "    if (false) {", "gml", ["test_unverified_and_limits_on_identities"]),
    ("request limit off", TRUST, "(kind == \"~q\" && s.requests.tokens < 1)", "false", "gml", ["test_rate_limits"]),
    ("event stream restarts unlimited", TRUST, "        if (s.streams.tokens < 1) { r.trust.failures++; return false; }", "", "gml", ["test_rate_limits"]),
    ("event layer ignores the gate", EVENTS, "        if (gate != undefined && !gate(slot, item)) {\n            ev.stalls++;\n            break;\n        }\n", "", "gml", ["test_rate_limits"]),
    ("record request not checked", PLAYERSYNC, "    var admit = r[$ \"trust_admit\"];", "    var admit = undefined;", "gml", ["test_claim_by_another_install", "test_first_use_binds"]),
    ("refusal does not ban", TRUST, "    mistrimulti_trust_deny(item.fp, item.name);\n", "", "gml", ["test_refuse_bans"]),
    ("hostile event data crashes the layer", EVENTS, "    var e = is_struct(frame) ? frame[$ \"ev\"] : undefined;\n    if (slot == r.id || !__mistrimulti_ev_valid(e)) return;",
     "    var e = frame[$ \"ev\"];\n    if (slot == r.id) return;", "gml", ["test_hostile_frames"]),
]


def run(command, env=None, timeout=1800):
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)


def build_helper(windows):
    if windows:
        run(["sh", "scripts/build-helper.sh"])
        return BUILD / "mistrimulti-helper.exe"
    BUILD.mkdir(exist_ok=True)
    obj, exe = BUILD / "mutant-helper.o", BUILD / "mutant-helper-linux"
    done = run(["nasm", "-f", "elf64", "-I", "helper/include/", "-I", "linux/", "helper/linux.asm", "-o", str(obj)])
    if done.returncode != 0:
        raise SystemExit("mutant does not assemble:\n" + done.stderr)
    run(["ld", str(obj), "-o", str(exe)])
    return exe


def main():
    pick = sys.argv[1:]
    survived = []
    for name, rel, old, new, kind, tests in MUTATIONS:
        if pick and not any(p in name for p in pick):
            continue
        path = ROOT / rel
        original = path.read_text()
        assert original.count(old) == 1, f"{name}: the text to mutate occurs {original.count(old)} times"
        path.write_text(original.replace(old, new))
        try:
            if kind == "helper":
                exe = build_helper(False)
                result = run([sys.executable, "tests/test_trust.py", str(exe)] + tests)
            elif kind == "helper-windows":
                exe = build_helper(True)
                env = dict(os.environ, WINEPREFIX=os.environ.get("WINEPREFIX", "/tmp/wp_main"), WINEDEBUG="-all")
                result = run([sys.executable, "tests/test_trust.py", str(exe)] + tests, env=env)
            elif kind == "launcher":
                run(["sh", "scripts/build-linux.sh"])
                env = dict(os.environ, ONLY=",".join(tests))
                result = run([sys.executable, "tests/test_launcher_linux.py", "build/mistrimulti-launcher", "build/mistrimulti-helper-linux",
                              "build/fakegame-linux", "build/mistrimulti-manager"], env=env)
            else:
                result = run([sys.executable, "tests/test_trust_gml.py"] + tests)
        finally:
            path.write_text(original)
        caught = result.returncode != 0
        print(("caught   " if caught else "SURVIVED ") + name, flush=True)
        if not caught:
            survived.append(name)
    # leave the build directory with the real programs again
    run(["sh", "scripts/build-linux.sh"])
    run(["sh", "scripts/build-helper.sh"])
    if survived:
        print("\n%d mutation(s) survived: %s" % (len(survived), ", ".join(survived)))
        sys.exit(1)
    print("\nall mutations caught")


if __name__ == "__main__":
    main()
