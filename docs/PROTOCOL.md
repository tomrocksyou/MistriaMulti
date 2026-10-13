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
