# MistriaMulti protocol v2 (authenticated)

UDP is used on a reachable IPv4 host/port. Each client speaks to the host; the host
forwards fully accepted snapshots to the other clients. All integers in the protocol
header use little-endian order (both supported CPU targets are x86-64). Sockaddr IP
addresses and UDP ports use the operating system's normal network-byte-order layout.

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 4 | ASCII `MSMP` |
| 4 | 2 | Version = 2 (version 1 had no authentication and is refused) |
| 6 | 2 | Reserved = 0 |
| 8 | 4 | Original player slot, 0–7 |
| 12 | 4 | Snapshot sequence, compared with signed modular subtraction |
| 16 | 4 | Shared session code |
| 20 | 4 | FNV-1a checksum of the complete payload |
| 24 | 4 | Complete payload length, 2–16384 bytes |
| 28 | 2 | Zero-based fragment index |
| 30 | 2 | Fragment count = ceil(length / 1152) |
| 32 | 4 | Helper epoch; a restart resets sequence history |
| 36 | 4 | Reserved = 0 |
| 40 | up to 1152 | UTF-8 JSON payload fragment |
| 40 + payload | 16 | Tag: first 16 bytes of `HMAC-SHA256(session key, direction byte \| header \| payload)`. Direction is 0 guest to host, 1 host to guest |

One snapshot occupies at most fifteen fragments. Reassembly is per original player
and accepts out-of-order and duplicate fragments. A newer sequence supersedes an
unfinished older one. No frame reaches the game until all fragments are present,
the checksum matches, and atomic file publication succeeds.

The checksum only detects damage; the tag authenticates. A datagram is accepted only after the join handshake below gave
both sides a session key, and (on the host) only from the address that completed it. A slot exists only after a valid
handshake. Ten seconds without valid traffic expires a peer. Unknown fields are not executed as commands. The room
(session) code in the header is a name, not a secret. Replies to unknown senders are never larger than the request.

## Join handshake (`MSAU`)

Packets that start `MSAU`, a type byte and version byte `1`. Integers are little endian. Every packet has an exact length;
other lengths are dropped. `docs/SECURITY.md` explains the keys; `tests/mmauth.py` is a complete reference implementation.

| Type | From | Length | Fields (byte offset) |
| --- | --- | --- | --- |
| 1 HELLO | guest | 128 | 8 room code u32, 12 slot u32 (1-7), 16 client nonce (16), rest zero |
| 2 CHALLENGE | host | 64 | 8 flags u32 (bit 0 password), 12 window u32, 16 cookie (16), 32 host fingerprint (16), 48 client nonce echo (16) |
| 3 PROOF | guest | 128 | 8 room code, 12 slot, 16 client nonce, 32 window, 36 cookie, 52 guest fingerprint (16), 68 masked key (32), 100 tag (16), rest zero |
| 4 WELCOME | host | 48 | 8 room code, 12 slot, 16 tag (16), 32 flags u32 (bit 0: first registration) |
| 5 REJECT | host | 16 | 8 reason u32 (1 password/auth, 2 banned, 3 busy, 4 full), 12 room code |
| 6 RESYNC | host | 16 | all zero: "I do not know this sender, send HELLO" (unauthenticated hint, at most twice a second) |

- `window` = host milliseconds / 20 000; `cookie` = `HMAC(host secret, "MMCK1" | window | port and address (6 bytes) | slot | client nonce)[0..16]`.
  The host accepts the current and the previous window and no other.
- Host fingerprint `HFP = SHA256("MMFP1" | install key)[0..16]`. `PWK` = 32 zero bytes, or `x = 0; 30000 times x = SHA256(x | HFP | password)`.
  `K = HMAC(IK, "MMBIND1" | HFP)`; guest fingerprint `GFP = SHA256("MMFP2" | K)[0..16]`.
  Masked key = `K xor HMAC(PWK, "MMREG1" | cookie | client nonce)`. `AK = HMAC(PWK, K)`.
- PROOF tag = `HMAC(AK, "MMPROOF1" | bytes 8..99 of the PROOF | HFP)[0..16]`; WELCOME tag =
  `HMAC(AK, "MMWELCOME1" | client nonce | cookie | slot u32)[0..16]`; session key = `HMAC(AK, "MMSK1" | client nonce | cookie)`.
- A host that already holds `K` for `GFP` ignores the masked key. A host that does not unmasks it, checks that
  `SHA256("MMFP2" | K)[0..16] == GFP`, verifies the tag and stores `(GFP, K)`.
- Guests send HELLO once a second (every three seconds after a REJECT), wait 1.5 s for a WELCOME, and start again when
  the host is silent for five seconds or answers RESYNC.

The helper publishes `auth_<slot>.json` next to `rx_<slot>.json` (see the file bridge below).

## File bridge

The game publishes `tx.frame` using a temporary file and rename. Its first two
bytes are `0\n` (ordinary snapshot) or `1\n` (events are waiting for acknowledgements, or this
game's own acknowledgements changed in the last 1.5 s). The rest is compact JSON. That prefix
stays local; only JSON crosses the network.
The helper publishes `rx_<slot>.json` and a one-second `status.json` in the bridge, plus `auth_<slot>.json`
(`{"fp":"<32 hex>","gen":N,"state":S,"reject":R}`) whenever a slot's authentication changes: on a host the verified install
fingerprint of a guest (`state` 1) or `""` when it left; on a guest, slot 0 is the host (`state` 2 once the host proved itself,
`fp` its fingerprint) and `reject` says why a join was refused. `status.json` adds `auth`, `reject`, `limited`, `authfail`,
`denied` and `unknown` counters. Next to them the helper writes `world_<slot>.key` (the world download's key, see below). The launcher writes `auth.cfg` (`key=`, `keys=`, `deny=`, `pass=` lines) into the bridge
folder before it starts the helper; without it the helper keeps its keys in memory and uses no password.
It atomically replaces output files and leaves the last good output on a failed write.
`status.json.heartbeat` contains the helper's monotonic millisecond clock. The
game expires the local helper's peer list when this value stops advancing for
three seconds, so an abruptly terminated helper cannot leave stale characters.

Game snapshots (`v: 2`) include `id`, `epoch`, `uid`, `world`, `active`, movement and
animation fields, and `ev`, the event layer's window. `ev` carries the sender's stream id, the
oldest unacknowledged sequence number, as many queued events as fit (at most 12 KB), and a
cumulative ACK plus the acknowledged stream id for each of the eight slots. Events are ordered
and delivered exactly once per sender session. Large payloads travel as blobs (up to 256 KB),
and host-authoritative requests are applied once per request id. `docs/EVENT-LAYER.md`
describes the format, the delivery rules, behaviour across reconnects and restarts, and why
there is no disk journal (including what item transfers still need). Version-1 and version-2
games ignore each other's frames.

Updates are retried every 100 ms while reliable; otherwise an identical snapshot is
sent once per second. This also heals loss of the final movement update when a player stops.
The event layer does not change the helper's UDP protocol.

## Menu bridge (`menu/cmd.txt`, `menu/status.json`)

The in-game Host / Join menu talks to the launcher through two files in the same data folder as the bridge, so no network port is
involved: the mod writes `menu/cmd.txt` (`key=value` lines: `seq`, `cmd` = host | join | scan | stop, `host`, `port`, `password`,
`room`; the launcher deletes it after reading) and the launcher publishes `menu/status.json` (heartbeat, last `seq`, state, error
code, addresses, scan results, and after a join the host's current world). `docs/SYNC-MENU.md` has the complete format, the state machine and
the error codes. A host's mod also writes `menu/world.txt` (`id=<game id>`, the world it plays now); see "World info" below.

## Host discovery (UDP 7776)

While a host plays (never in standby: a computer that has not chosen to host does not answer), the launcher (`MistriMultiLauncher.exe` on Windows, `mistrimulti-launcher` on Linux; identical wire behaviour) answers discovery queries on UDP port 7776 (the game traffic itself uses the separate
port from `launcher.cfg`, 7777 by default). A query is exactly 64 bytes: `MSDQ`, version byte `1`, 59 zero bytes. The reply
is exactly 64 bytes: `MSDR`, version `1`, flags (bit 0 = the host uses a custom room code, bit 1 = it needs a room password), game port (u16 little-endian),
computer name (32 bytes, NUL padded), 24 zero bytes. **World info (added after 0.4.5, backward compatible, versions stay 1):** flags bit 2 = the host
named the world it plays now, bit 3 = a save of that world exists (so a friend can download it); both are 0 from a host that predates this
or whose game has not loaded a world yet. Anything else is ignored, and the reply is never larger than the
query, so the responder cannot amplify traffic. Players scan with a broadcast query on every local network plus a unicast
query to each Tailscale peer (Windows: `tailscale.exe status --json` from Program Files; Linux: the `tailscale` command found on `PATH`,
or `$MISTRIMULTI_TAILSCALE`). Discovery gives no authentication: it only tells a friend where to connect. Flag bit 1 says the host needs a room password. On Linux the computer name
is the kernel's node name (`uname`), and a scan never lists the computer's own non-loopback addresses.

## World transfer (TCP 7775)

While a host plays, the launcher also listens on TCP port 7775 and gives a joining player the host's newest multiplayer save
(`%LOCALAPPDATA%\FieldsOfMistria\multiplayer\saves\game-<digits>-(autosave|<digits>).sav` on Windows,
`<game folder>/multiplayer/saves/` on Linux, see `README.md` for how the folder is found; other names, such as `.old.sav`,
are never sent; "newest" is the latest modification time).

**The world is released only to a player whose join the host's helper has authenticated** (version 2 of this protocol; the
unauthenticated version 1 is refused). The proof is a challenge and response under a key derived from the join session, so it
needs the room password (when there is one) and the guest's install key, exactly like the UDP join; nothing about the world
(not even whether one exists) is sent before it is checked.

**The key.** When the helper finishes a join handshake it has the session key `SK` (see the join handshake above). It also
writes `WK = HMAC(SK, "MMWORLD1")` (32 raw bytes) to `<bridge>/world_<slot>.key`: on the host one file per authenticated
guest slot (1-7), on a guest the one for its own slot. The file is written before the new state is published in
`auth_<slot>.json`, created `0600` on Linux, replaced by a new `WK` when the same slot joins again, and overwritten with
32 zero bytes when the session ends (kick, expiry, silent host). The launcher of the same computer reads it; an absent,
short, long or all-zero file means "no session". The launcher deletes all `world_*.key` files when it prepares a bridge.

**The exchange** (all lengths are exact; `nonce` = 16 random bytes; integers are little endian):

| Step | From | Bytes | Layout |
| --- | --- | --- | --- |
| 1 REQUEST | guest | 64 | `MSWQ`, version `2`, slot (1-7) at offset 5, zero to 16, guest nonce `cn` @16, 32 zero bytes |
| 2 CHALLENGE | host | 32 | `MSWC`, version `2`, status `0`, zero to 16, host nonce `hn` @16 (fresh for every connection) |
| 3 PROOF | guest | 48 | `MSWP`, version `2`, zero to 16, tag @16 = `HMAC(WK, "MMWORLDQ1" \| slot byte \| cn \| hn)` (32 bytes, not truncated) |
| 4 HEADER | host | 144 | `MSWR`, version `2`, status (0 ok, 1 no world yet, 2 cannot send, 3 refused, **4 the host's current world is not saved**) at offset 5, **world info flags @6**, file length (u32, at most 200 MB) @8, SHA-256 of the file @12, **host world id (u32) @44**, file name @48 (64 bytes, NUL padded), tag @112 = `HMAC(WK, "MMWORLDR1" \| slot byte \| cn \| hn \| header bytes 0..111)` |
| 5 DATA | host | length | the file, only after status 0 |

- The host answers a REQUEST with a CHALLENGE for any slot number, even one without a session, and decides only after the PROOF
  (so the answer does not tell a stranger which slots are in use). It then checks slot 1-7, loads that slot's `WK`, recomputes
  the tag and compares it without early exit. Any failure gets exactly one 144-byte header with status 3 and no tag; the file
  is not read from disk before the proof is accepted.
- **Replay.** `hn` is fresh for every connection and covered by both tags, so a recorded request and proof, or a recorded
  reply, is worthless on another connection. A key from an earlier session fails as soon as the helper rotates the file.
- **The client believes the host only if the reply tag is valid**, so a fake host without `WK` cannot hand over a world (the
  client then reports code 7). The client then applies the same checks as before: length, name pattern, SHA-256, `<name>.part`
  written first and renamed over the old copy. The client never names a file; the host never reads a path from the client.
- **Old clients.** A version-1 request (16 bytes: `MSWQ`, version `1`, 11 zero bytes) is answered at once with a 112-byte
  version-1 header, status 3, the text "Update MistriaMulti: the world download now needs a login" in the name field, and no
  data: the old client reports "invalid reply" (menu code 43) instead of hanging. A new client that talks to an old host
  gets its connection closed after the REQUEST and reports code 7. Both sides need the same release.
- Every wait is bounded (3 s per request or proof read, 5 s for the client's challenge and header waits, 15 s for data) and one
  connection is served at a time. The Linux host sends with `MSG_NOSIGNAL`, so a client that hangs up cannot kill the launcher.
  The HMAC is built on each program's own SHA-256 (`common/hmac.inc`: bcrypt on Windows, `linux/sha256.inc` on Linux).
- Client result codes: 0 ok, 1 cannot connect, 2 the host has no world yet, 3 invalid reply, 4 checksum mismatch, 5 cannot
  write, 6 out of memory, 7 refused (no joined session, wrong proof, unsigned or edited reply, or a host that does not speak
  this protocol; the menu shows code 47), 8 the host plays a world it has not saved (status 4; the menu shows code 48).

### World info (which world does the host play?)

A guest used to get "the newest save in the host's multiplayer folder", which is the wrong world when the host started a NEW world
and has not saved it yet. The extension is backward compatible: it lives in bytes that were zero (and are covered by the header tag),
and the version numbers stay as they are.

- **The host's mod** (`MistriMultiMenu.gml`) writes `<mod data>/menu/world.txt` = `id=<Game.unique_identifier>` once its world is loaded
  (a game id: 1..2147483647; it is also the number in every save name `game-<id>-...sav` and the suffix of the mod's world key).
  The launcher reads it for each world request and discovery query, and deletes it at launcher start and whenever a session
  starts or stops. No file (or one that does not parse) = the old behaviour: the newest save, no world info.
- **Header with a note:** only saves whose name carries that id count (the newest of them, automatic or manual). Byte 6: bit 0 = the host named a
  world, bit 1 = that world has a save; bytes 44..47 = the id. No save of that world: status **4**, no file, flags `1`, the id.
  Without a note bytes 6 and 44..47 stay zero.
- **Guest:** the signed header is checked first (an unsigned or edited header is refused as before), then the launcher reports
  `hw` (host world id, 0 = not told), `hf` (flags) and `dw` (the id in the name of the file that was downloaded) in
  `menu/status.json`. The mod enters only when `hw == 0`, `dw == 0` or `hw == dw`. Status 4 is menu error 48.
- **Discovery:** flags bit 2 / bit 3 as above (the launcher looks at the disk at most once a second). The scan result's `flags` passes them on
  unchanged, so the host list can show "[new world, not saved]" before anyone joins.
- **When the clients ask.** The in-game menu downloads right after the helper reports the host's WELCOME. A launcher started
  with a `launcher.cfg` join waits up to 5 s for the helper's key file and then refreshes the world as the game starts. The
  managers' *join* only saves `launcher.cfg` (they have no helper session to prove), and say so. The test hook
  `--fetch <ip> <folder> <result file> [<bridge folder> <slot>]` of both managers proves the key in that bridge folder.

Anyone who can reach the host's port still learns that a Mistria host is there and can make it spend up to a few seconds per
connection; they get no world. The world itself is not encrypted on the wire (only authenticated), like all other traffic: use a
private network if that matters.
