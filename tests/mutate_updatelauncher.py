"""Mutation check for the launcher side of the Update button (common/updatecore.inc and the Linux platform code in linux/menu.inc).

    python3 tests/mutate_updatelauncher.py            # needs nasm + ld and the built helper / fake game in build/

Breaks one rule at a time in the assembly (a version comparison turned round, a message that is not cleaned, a run while hosting,
a cancel in the middle of an installation, no time limit, a check every start, a check that ignores the opt-out, ...), assembles
the launcher into a temporary file, runs the Linux launcher tests that should notice (in a private network namespace) and
restores the sources. Exit status 1 if a mutation goes unnoticed.
"""
import fcntl
import os
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
if os.environ.get("MM_NETNS") != "1":
    os.environ["MM_NETNS"] = "1"
    os.execvp("unshare", ["unshare", "-n", sys.executable, os.path.abspath(__file__)] + sys.argv[1:])
_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
fcntl.ioctl(_s, 0x8914, struct.pack("16sH14s", b"lo", 0x41, b"\0" * 14))      # lo up

C, L = "common/updatecore.inc", "linux/menu.inc"
RUN = "test_update_run_ok,test_update_needs_momi_and_failures"
CANCEL = "test_update_one_at_a_time_busy_and_cancel"
TIME = "test_update_timeout_and_missing_program"
CHECK = "test_release_check"
CHECKS = "test_release_check_never_delays_or_breaks_the_game"
OPT = "test_release_check_needs_manifest_and_honours_opt_out"
RETRY = "test_release_check_retry_rules"

MUTATIONS = [
    ("newer version compared the wrong way", C, "    ja .yes\n    jb .no\n    inc ecx", "    jb .yes\n    ja .no\n    inc ecx", CHECK),
    ("result messages keep their quotes", C, "    mov al, 39\n.a: cmp al, 92", "    nop\n.a: cmp al, 92", RUN),
    ("a failure exit code gets the wrong code", C, "    mov dword [up_err], UP_ER_FAILED\n    mov byte [up_msg], 0\n    jmp .fin\n.failed_err:",
     "    mov dword [up_err], UP_ER_NORESULT\n    mov byte [up_msg], 0\n    jmp .fin\n.failed_err:", RUN),
    ("an update while hosting or joining", C, "    cmp dword [sv_session], 0\n    je .go\n    mov dword [up_state], UP_ST_FAILED",
     "    cmp dword [sv_session], 0\n    jmp .go\n    mov dword [up_state], UP_ST_FAILED", CANCEL),
    ("cancel in the middle of an installation", C, "    cmp dword [up_state], UP_ST_INSTALLING\n    je .publish\n    call plat_up_kill",
     "    call plat_up_kill", CANCEL),
    ("a second run while one runs", C, "    cmp dword [up_active], 0\n    jne .publish\n    cmp dword [up_state], UP_ST_DONE",
     "    cmp dword [up_active], 0\n    cmp dword [up_state], UP_ST_DONE", CANCEL),
    ("no time limit for the update program", C, "    cmp rax, rcx\n    ja .timeout\n    call plat_up_poll", "    cmp rax, rcx\n    call plat_up_poll", TIME),
    ("the check runs at every start", C, "CK_OK_SECONDS equ 86400", "CK_OK_SECONDS equ 1", CHECK),
    ("a failed check is retried at once", C, "CK_RETRY_SECONDS equ 10800", "CK_RETRY_SECONDS equ 1", RETRY),
    ("the opt-out is ignored", C, "    jnz .publish                            ; the player turned the check off: update stays \"none\"",
     "    jnz .cache", OPT),
    ("an invalid version is published", C, "    mov byte [r12], 0\n    test eax, eax\n    jz .d\n    mov rsi, r13", "    mov byte [r12], 0\n    mov rsi, r13", RUN),
    ("the download size is not limited", L, "s_cu_mf2 db '65536',0", "s_cu_mf2 db '6553600',0", CHECKS),
]

work = pathlib.Path(tempfile.mkdtemp(prefix="mutlauncher-"))
originals = {}
bad = 0
try:
    for name, which, old, new, tests in MUTATIONS:
        if sys.argv[1:] and not any(a in name for a in sys.argv[1:]):
            continue                                   # python3 tests/mutate_updatelauncher.py "opt-out" runs the matching ones
        path = ROOT / which
        originals.setdefault(path, path.read_text())
        text = originals[path]
        if old not in text:
            print("MISSING PATTERN:", name)
            bad += 1
            continue
        path.write_text(text.replace(old, new, 1))
        obj, exe = work / "launcher.o", work / "mistrimulti-launcher"
        built = subprocess.run(["nasm", "-f", "elf64", "-I", str(ROOT / "helper/include") + "/", "-I", str(ROOT / "common") + "/",
                                "-I", str(ROOT / "linux") + "/", str(ROOT / "linux/launcher.asm"), "-o", str(obj)], capture_output=True, text=True)
        path.write_text(text)
        if built.returncode == 0:
            built = subprocess.run(["ld", str(obj), "-o", str(exe)], capture_output=True, text=True)
        if built.returncode != 0:
            print("DOES NOT BUILD:", name, built.stderr[-300:])
            bad += 1
            continue
        env = dict(os.environ, ONLY=tests)
        out = subprocess.run([sys.executable, "-I", "tests/test_launcher_linux.py", str(exe), str(ROOT / "build/mistrimulti-helper-linux"),
                              str(ROOT / "build/fakegame-linux"), str(ROOT / "build/mistrimulti-manager")],
                             cwd=ROOT, env=env, capture_output=True, text=True, timeout=1800)
        caught = out.returncode != 0
        print(("caught " if caught else "NOT CAUGHT ") + name, flush=True)
        bad += 0 if caught else 1
finally:
    for path, text in originals.items():
        path.write_text(text)
sys.exit(1 if bad else 0)
