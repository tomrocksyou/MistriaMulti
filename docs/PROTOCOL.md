# MistriMulti protocol v2 (authenticated)

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
`denied` and `unknown` counters. The launcher writes `auth.cfg` (`key=`, `keys=`, `deny=`, `pass=` lines) into the bridge
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

## Host discovery (UDP 7776)

While a host plays, the launcher (`MistriMultiLauncher.exe` on Windows, `mistrimulti-launcher` on Linux; identical wire behaviour) answers discovery queries on UDP port 7776 (the game traffic itself uses the separate
port from `launcher.cfg`, 7777 by default). A query is exactly 64 bytes: `MSDQ`, version byte `1`, 59 zero bytes. The reply
is exactly 64 bytes: `MSDR`, version `1`, flags (bit 0 = the host uses a custom room code, bit 1 = it needs a room password), game port (u16 little-endian),
computer name (32 bytes, NUL padded), 24 zero bytes. Anything else is ignored, and the reply is never larger than the
query, so the responder cannot amplify traffic. Players scan with a broadcast query on every local network plus a unicast
query to each Tailscale peer (Windows: `tailscale.exe status --json` from Program Files; Linux: the `tailscale` command found on `PATH`,
or `$MISTRIMULTI_TAILSCALE`). Discovery gives no authentication: it only tells a friend where to connect. Flag bit 1 says the host needs a room password. On Linux the computer name
is the kernel's node name (`uname`), and a scan never lists the computer's own non-loopback addresses.

## World transfer (TCP 7775)

While a host plays, the launcher also listens on TCP port 7775 and gives a joining player the host's newest multiplayer save
(`%LOCALAPPDATA%\FieldsOfMistria\multiplayer\saves\game-<digits>-(autosave|<digits>).sav` on Windows,
`<game folder>/multiplayer/saves/` on Linux, see `README.md` for how the folder is found; other names, such as `.old.sav`,
are never sent; "newest" is the latest modification time). The client sends 16 bytes: `MSWQ`, version `1`, 11 zero bytes. The host replies with a 112-byte header and
then the file: `MSWR`, version `1`, status (0 = ok, 1 = no world yet, 2 = cannot send), file length (u32 little-endian,
at most 200 MB) at offset 8, SHA-256 of the file at offset 12, and the file name at offset 48 (64 bytes, NUL padded).
The client rejects any name that does not match the pattern above, checks the length and the SHA-256, writes
`<name>.part` and only then renames it over the old copy. The client never names a file; the host never reads a path
from the client. Every wait is bounded (3 s request, 5 s header, 15 s data) and one connection is served at a time. The Linux host sends with
`MSG_NOSIGNAL`, so a client that hangs up cannot kill the launcher. The Linux client computes the SHA-256 with its own assembly
implementation (`linux/sha256.inc`); Windows uses bcrypt.
Anyone who can reach the host's port can download the world, so use a private network (Tailscale, LAN): the room password does not cover this port.
