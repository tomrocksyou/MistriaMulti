# MistriMulti protocol v1

UDP is used on a reachable IPv4 host/port. Each client speaks to the host; the host
forwards fully accepted snapshots to the other clients. All integers in the protocol
header use little-endian order (both supported CPU targets are x86-64). Sockaddr IP
addresses and UDP ports use the operating system's normal network-byte-order layout.

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 4 | ASCII `MSMP` |
| 4 | 2 | Version = 1 |
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

One snapshot occupies at most fifteen fragments. Reassembly is per original player
and accepts out-of-order and duplicate fragments. A newer sequence supersedes an
unfinished older one. No frame reaches the game until all fragments are present,
the checksum matches, and atomic file publication succeeds.

The session code and checksum are not cryptographic authentication. Use trusted
networks. The host pins an admitted slot to its source address/port until it expires;
clients accept traffic only from their configured host address/port. Ten seconds
without valid traffic expires a peer. Unknown fields are not executed as commands.

## File bridge

The game publishes `tx.frame` using a temporary file and rename. Its first two
bytes are `0\n` (ordinary snapshot) or `1\n` (an event is waiting for acknowledgements).
The rest is compact JSON. That prefix stays local; only JSON crosses the network.
The helper publishes `rx_<slot>.json` and a one-second `status.json` in the bridge.
It atomically replaces output files and leaves the last good output on a failed write.
`status.json.heartbeat` contains the helper's monotonic millisecond clock. The
game expires the local helper's peer list when this value stops advancing for
three seconds, so an abruptly terminated helper cannot leave stale characters.

Game snapshots include `v`, `id`, `epoch`, `active`, a fixed eight-slot ACK array `a`,
movement/animation fields, and optional `q={s,k,d}`. Only one queued event is sent
at a time. Each active peer acknowledges its application, and the sender then moves
to the next event. The queue is bounded to 256 entries. There is no disk journal or
resume-after-game-crash guarantee. Existing event types are idempotent appearance
and terrain updates; item transactions need a stronger persistence design before
they can be added safely.

Updates are retried every 100 ms while reliable; otherwise an identical snapshot is
sent once per second. This also heals loss of the final movement update when a player stops.

## Host discovery (UDP 7776)

While a host plays, the launcher answers discovery queries on UDP port 7776 (the game traffic itself uses the separate
port from `launcher.cfg`, 7777 by default). A query is exactly 64 bytes: `MSDQ`, version byte `1`, 59 zero bytes. The reply
is exactly 64 bytes: `MSDR`, version `1`, flags (bit 0 = the host uses a custom room code), game port (u16 little-endian),
computer name (32 bytes, NUL padded), 24 zero bytes. Anything else is ignored, and the reply is never larger than the
query, so the responder cannot amplify traffic. Players scan with a broadcast query on every local network plus a unicast
query to each Tailscale peer. Discovery gives no authentication: it only tells a friend where to connect.

## World transfer (TCP 7775)

While a host plays, the launcher also listens on TCP port 7775 and gives a joining player the host's newest multiplayer save
(`%LOCALAPPDATA%\FieldsOfMistria\multiplayer\saves\game-<digits>-(autosave|<digits>).sav`; other names, such as `.old.sav`,
are never sent). The client sends 16 bytes: `MSWQ`, version `1`, 11 zero bytes. The host replies with a 112-byte header and
then the file: `MSWR`, version `1`, status (0 = ok, 1 = no world yet, 2 = cannot send), file length (u32 little-endian,
at most 200 MB) at offset 8, SHA-256 of the file at offset 12, and the file name at offset 48 (64 bytes, NUL padded).
The client rejects any name that does not match the pattern above, checks the length and the SHA-256, writes
`<name>.part` and only then renames it over the old copy. The client never names a file; the host never reads a path
from the client. Every wait is bounded (3 s request, 5 s header, 15 s data) and one connection is served at a time.
Anyone who can reach the host's port can download the world, so use a private network (Tailscale, LAN).
