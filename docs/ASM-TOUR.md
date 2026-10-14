# Assembly tour

## Where to start

1. `helper/include/abi.inc` defines the routine prologue and epilogue. The shared
   internal convention uses RCX, RDX, R8 and R9 for arguments on both operating systems.
   Nonvolatile registers are saved, and callers have shadow space and stack argument space.
   The epilogue uses LEA rather than ADD so parsers can return failure in the carry flag.
   Windows routines also carry unwind records in `.pdata` / `.xdata`.
2. `mistria_main` in `core.inc` parses options, binds UDP, waits at most 50 ms,
   reads one local frame, drains a bounded number of incoming packets, and sends updates.
3. `read_local_frame` compares bytes with the cached state. Unchanged game data
   produces a heartbeat once a second, or a retry every 100 ms while an event awaits ACKs.
4. `send_record` splits a snapshot into 1152-byte payload fragments.
5. `receive_fragment` validates bounds and session/source identity, rejects older
   sequence numbers, assembles fragments into a fixed buffer, checks the complete
   checksum and only then publishes a game-readable JSON file.
6. `windows.asm` translates the shared calls into Windows API calls. Read how
   the fifth/sixth arguments to Winsock functions are placed on the stack, and why
   32-bit SOCKET_ERROR return values are sign-extended before 64-bit comparisons.
7. `linux.asm` translates those calls into Linux syscalls. R10 carries the fourth
   syscall argument, and SYSCALL clobbers RCX and R11. This is different from the
   normal System V userspace function-call convention.

## The Linux launcher and manager

`linux/launcher.asm` and `linux/manager.asm` are the Linux twins of `launcher/launcher.asm` and the manager window; they use the
same routine convention (`abi.inc`) over raw syscalls. The pieces:

- `linux/sys.inc`: syscall wrappers (`sys_*` return -errno), the bounded string builder (`pb_start` / `pb_str` / `pb_int` /
  `pb_end`), files and directories, UTC time stamps, `spawn` (fork + `PR_SET_PDEATHSIG` + dup2 + execve / PATH search).
- `common/textutil.inc`: validators and parsers shared with the Windows build (`v_ipv4`, `v_room`, `a2i`, `wf_valid_name`...).
- `linux/config.inc`: where the game keeps its files, and `launcher.cfg` reading (strict validation) and writing.
- `linux/sha256.inc`: SHA-256 (the Windows build asks bcrypt). Follow `sha_block`: the big sigmas are written as nested rotates
  to fit in three temporary registers.
- `linux/net.inc`: the world download client, interface and Tailscale scan, discovery query.

## Memory and performance

`helper/steam_windows.asm` and `helper/steam_linux.asm` load the installed game's
Steam library. Their shared `include/steam_identity.inc` reads the Steam ID and
formats it as an exact decimal string. Windows uses the system DLL loader;
Linux uses glibc/libdl for this separate probe. The networking helper still
has no C runtime dependency.

There is no heap allocation in the helper's transport logic. Fixed records hold
the last completed state and in-progress reassembly for each slot. Windows argument
decoding is the one OS-owned allocation; it is released on shutdown. Kernel socket
buffers, DLL mappings, stacks and process bookkeeping still consume memory.

File size, working set, private memory, CPU time, bandwidth and game frame time are
different measurements. A small executable does not guarantee a particular working set.
The bridge currently uses cached regular files because they are supported by the game.
It is not shared memory or a named-pipe bridge.

## First learning exercises

- Watch `parse_decimal` reject an invalid port and return CF=1.
- Follow a tool update from `tx.frame` into `file_bytes`, then the cached peer record.
- Inspect the header before `pl_send` and compare it with `docs/PROTOCOL.md`.
- Run `tests/test_packet_faults.py` while stopped at `receive_fragment` to observe
  missing/duplicate fragments and the bitmap that prevents partial publication.
- Add a counter to status output, then run both OS test suites before changing gameplay.
