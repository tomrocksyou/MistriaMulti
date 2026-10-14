# Event layer

Every synchronised feature (farm terrain and player records today; clock and sleep, crops, chests, animals, NPCs and quests
later) sends its changes through one layer: `mod/mistrimulti/gml/MistriMultiEvents.gml`. It provides:

- **Ordered, reliable, batched events per sender.** Many events per frame, sequence numbers, cumulative ACKs, duplicate
  rejection, retransmission, bounded queues and back-pressure, for one host and up to seven guests.
- **Blobs**: strings up to 256 KB, cut into events and delivered whole or not at all, with an integrity check.
- **Host-authoritative requests**: a guest asks, the host validates and applies **exactly once** per request id (across
  retransmissions and reconnects), then broadcasts the result. Every guest applies the result, and the requester also gets
  a reply.
- **A small registry**: each feature registers handlers for its event kinds and never touches the bridge files.

`tests/event_model.py` is the executable specification. The GML mirrors it function by function: `__mistrimulti_ev_x`
corresponds to `_ev_x`, and public functions have the same name in both. Change both together. The tests also run the
GML file itself (see [Testing](#testing)).

## Where it sits

```text
feature (GML) --emit/request/send_blob--> event layer --frame.ev--> tx.frame (<= 16 KB JSON)
                                                                      |  native helper: UDP, 1152-byte fragments,
                                                                      |  checksum, replay rejection, host relay
feature (GML) <--handlers-- event layer <--frame.ev-- rx_<slot>.json <-+
```

The helper still moves one *latest-wins* JSON snapshot per player (see `docs/PROTOCOL.md`). A snapshot can be lost,
skipped by a newer one, or read twice by the game. The event layer is built for that: **every frame carries the sender's
whole unacknowledged window**, from its oldest unacknowledged event up to as many events as fit. Skipping or losing a
frame therefore loses nothing; the next frame carries the same events again. Receivers deliver strictly in sequence
order and acknowledge cumulatively; the sender drops events once they are acknowledged.

### Why the helper did not change

The existing helper already provides what the layer needs:

- A 16 KB frame holds a 12 KB window, i.e. up to hundreds of small events, or six blob chunks per frame.
- Retransmission: while the game marks its frame reliable (`1\n` prefix), the helper resends it every 100 ms.
- Integrity: fragments are checksummed and a frame is published only when complete.
- Relay: the host forwards every accepted guest frame to the other guests.

Measured throughput is adequate for the features planned so far (see [Performance](#performance)). A larger frame or a
second channel would mean a new wire format and new risk in the assembly for a gain no current feature needs. The wire
protocol between helpers is unchanged, and all helper tests pass as before.

## Wire format

The game frame version is now `v: 2`. A version-1 game ignores version-2 frames and the reverse, so mixed mod versions
do not misinterpret each other (they simply do not see each other's events). Movement fields are unchanged. The event
layer adds one field:

```json
"ev": { "s": "1-a1b2c3d4-8812345", "b": 41, "q": [ {"s":41,"k":"look","d":{}}, {"s":42,"k":"~q","d":{},"t":0,"ts":"0-..."} ],
        "a": [57, 0, 12, 0, 0, 0, 0, 0], "c": ["0-9f8e7d6c-1234", "", "2-77aa00bb-9921", "", "", "", "", ""] }
```

| Field | Meaning |
| --- | --- |
| `s` | The sender's **stream id**: slot, first 8 characters of the launcher epoch, and `get_timer()` at the stream's start. A new stream begins whenever the game enters a world (`mistrimulti_events_reset`). |
| `b` | Base: the oldest sequence number the sender still holds. Everything below was acknowledged by every participant. |
| `q` | Events `b, b+1, ...` in order, as many as fit in 12 KB and in the frame's 16 KB. |
| `a[i]` | Cumulative ACK: the highest sequence from slot `i` that this game has delivered in order. |
| `c[i]` | The stream id that `a[i]` refers to. An ACK counts only for that stream, so an ACK left over from a peer's earlier session can never retire a new session's events. |

An event is `{ s: seq, k: kind, d: data, t?: target slot, ts?: target stream }`. When `t` is set, only that slot
delivers it. When `ts` is also set, it is delivered only if that slot is still the same session. Everyone else skips the
event but still acknowledges it, so cumulative ACKs never stall. Three kinds are internal:

| Kind | `d` |
| --- | --- |
| `~q` request | `{ k: kind, n: request number, i: "<stream>:<n>", d: data }`, targeted at the host |
| `~r` result | `{ k: kind, i: request id, f: requester slot, d: result }`, broadcast; or targeted at the requester when the host re-answers a re-sent request; `x: true` instead of `d` when that answer has expired |
| `~b` blob chunk | `{ k: kind, i: blob id, n: chunk index, x: text, l: total bytes (first chunk), m: meta (first chunk), e: true and h: FNV-1a hash (last chunk) }` |

## Delivery rules

- **Order and duplicates.** Per sender stream, a receiver delivers sequence `x` only after `x-1`; anything below `x` is a
  duplicate and is ignored. There is no ordering *between* different senders. Host-authoritative state therefore flows
  as results and events in the host's single stream, which defines the order.
- **Participants.** A peer is a participant when the helper reports it present (the `mask` in `status.json`, refreshed
  once a second) and its latest frame carries a valid `ev`. Boot includes `ev` only while a world is loaded (`ARI` is
  set), because a game on the title or loading screen does not process events and would hold every sender's queue.
  A sender retires event `s` once every participant has
  acknowledged `s` for this stream. On a guest, **the host is always required**, even while it is unreachable, so a
  guest never discards a request because the host was briefly away.
- **Late joiners.** A game that sees a stream for the first time starts at that stream's base. Events retired before it
  became a participant are not delivered to it. Features that need the current state must send it from `on_peer` (see
  the guide). A host with no participants retires its events immediately.
- **Gaps.** If a known sender's base has moved past what this game delivered, the game was away (expired) while the
  sender moved on. The receiver jumps to the new base and calls every `on_gap` handler. If the sender is the host, the
  receiver also re-sends its outstanding requests (below).
- **Targeting.** `mistrimulti_event_emit(kind, data, slot)` delivers only to `slot`, and only while it is still the
  session that was in that slot when the event was emitted. A player who later takes over the slot never gets data
  meant for the previous one.
- **Relay.** Guests talk only to the host's helper. The host's helper forwards every guest frame to the other guests,
  so guest-to-guest events (for example appearance) work and are acknowledged the same way. Requests are targeted at
  the host; the other guests skip them.
- **Retransmission.** The frame is marked reliable while events are unacknowledged, and for 1.5 s after this game's own
  ACKs change, so a lost ACK frame is repeated within 100 ms instead of waiting for the 1 s heartbeat.
- **Back-pressure.** `mistrimulti_event_emit` returns `false` when the queue is full (512 events or 512 KB). A handler
  that returns `false` ("not now") holds its sender's stream at that event and is retried every bridge tick. Such a hold
  fills the sender's queue, so it should be short.
- **Handler failures.** An exception in a handler is logged, counted in `errors` and treated as handled, so one bad event
  cannot stall a stream forever. (The player-record handlers catch their own exceptions and retry, as they always did.)

## Blobs

`mistrimulti_event_send_blob(kind, text, target, meta)` queues a string of up to 256 KB of UTF-8, with at most 8 blobs
waiting per game. The layer cuts it into chunks of up to 2048 characters (fewer when the JSON-escaped chunk would exceed
6 KB) and emits them only while less than 24 KB is unacknowledged, so ordinary events are never stuck behind a large
transfer. Because events are ordered, reassembly is a simple append. Memory is bounded at one blob per sender, and the
announced length is checked as each chunk arrives. The last chunk carries an FNV-1a hash of the whole text, computed
incrementally on both sides; a length or hash mismatch discards the blob and counts an error. The handler receives the
complete text exactly once; if it returns `false`, the same complete blob is offered again later. A targeted blob is
dropped by the sender if its target leaves (expires) or restarts.

## Requests

```gml
var id = mistrimulti_event_request("chest_take", { chest: key, slot: 3, count: 5 });   // undefined = try later
```

On a guest, the request is queued as a `~q` event to the host and remembered as outstanding. On the host, it goes
through the same code path locally. The host:

1. Checks that the id belongs to the sending stream (`<stream>:<n>`), so a guest cannot forge another player's id.
2. If `n` is at or below that stream's **watermark**, the request was already applied. The host does not apply it again,
   but re-sends the cached result to the requester only (or `expired` if the result is no longer cached).
3. Makes sure a result can be queued, then calls `on_request(slot, data, ctx)`. A result struct is broadcast as `~r` and
   recorded. Returning `false` means "not now": the request is retried later, and the requester's stream waits.
4. Calls `on_reply` locally when the host itself was the requester.

Every guest calls `on_result(0, result, ctx)` when the result arrives; the requester then also calls
`on_reply(0, result, ctx)` and forgets the request. Requests from one stream are applied in order. The host keeps, per
requester stream, the watermark plus that stream's newest 64 results (up to 64 KB), for the 16 most recently active
streams. Since a guest can have at most 64 outstanding requests and refuses new ones while a resend is waiting, a resend
after a reconnect always finds its result unless the results were very large. Other players' traffic cannot evict
anyone's results.

| Situation | What happens |
| --- | --- |
| Lost or duplicated packets, frames, ACKs | Retransmitted and de-duplicated; applied once, answered once |
| Guest away > 10 s (expired), then back with the same game session | Its outstanding requests reach the host in order; anything already applied is re-answered from the cache, never applied twice; `on_gap` fires |
| Guest re-enters the world / restarts its game | New stream: its outstanding requests are dropped with it (the requesting session is gone) |
| Host restarts (new host stream) | Every outstanding request gets `on_reply(0, undefined, { lost: true })`. The new host cannot know whether the old one applied it, so the layer never re-sends it: requests are **at most once across a host restart** and exactly once otherwise. The feature decides whether to ask again. |
| Result evicted from the cache | `on_reply(0, undefined, { expired: true })`: it was applied, the details are gone |

## Lifecycle

| Event | Effect |
| --- | --- |
| Entering a world | `mistrimulti_player_reset_session` → `mistrimulti_events_reset`: new stream; queues, blobs, outstanding requests and receive state of the old session are discarded; registered handlers stay. Peers see a new stream (`on_peer(slot, true, stream)`). |
| Peer expires (10 s silent) | It stops being a participant (`on_peer(slot, false, ...)`); senders retire events without it. Its receive state is kept, so if the same session returns it continues (or gets `on_gap`). |
| Helper restart, same game | The helper epoch handles transport sequence numbers; the game's streams continue unaffected. |
| Game crash | Everything in memory is lost; the next session is a new stream (late joiner). |
| Slot reused by another player | A different stream; targeted events carry the old session's stream id and are not delivered to the new player. |

## Decision: no disk journal

The layer keeps its queues in memory only. Reasons:

- **The durability boundary is the game save, not the event.** The host's world is persisted only when the game saves
  (sleep), and guests do not save the world at all. A journal replayed after a host crash would re-apply events to a
  world reloaded from an *older* save, mixing two timelines. Without a journal, a crash rolls everything back to the
  last save consistently, and in-flight requests are reported `lost`, not silently re-applied.
- **Cost on the game thread.** Writing a file per event (20 Hz, synchronously, from GML) would add disk latency to every
  frame for a guarantee the world save cannot honour anyway.
- **Exactly-once already holds while the host runs**, which is when it matters: retransmissions, duplicates and guest
  reconnects are all covered in memory.

What a journal would *not* fix is the real hazard for **item transfers**. The world (chests, drops) is saved with the
host's `.sav`, but player inventories are checkpointed to the host's player records every ~5 s. A transfer between the
two can be duplicated or lost by a host crash between those two save points. The recommended design for chests and
trades:

1. Make each transfer a host request that applies *both* sides on the host, i.e. the container and the guest's host-side
   record (or a pending-delta list kept with it).
2. Commit both at the same moment, from `game.save_guard` (the host save).

This is a feature-level design, built on this layer, still to be done.

## Limits

| Macro (`MISTRIMULTI_EV_*`) | Value | Meaning |
| --- | --- | --- |
| `FRAME_LIMIT` / `FRAME_MARGIN` | 16384 / 256 | Helper frame limit; head room |
| `WINDOW_BYTES` | 12288 | Event bytes per frame |
| `EVENT_BYTES` | 8192 | Largest single event (use a blob above this) |
| `QUEUE_EVENTS` / `QUEUE_BYTES` | 512 / 512 KB | Unacknowledged events per game |
| `BLOB_BYTES` / `BLOB_JOBS` / `BLOB_META_BYTES` | 256 KB / 8 / 2 KB | Blob size, queued blobs, meta size |
| `CHUNK_CHARS` / `CHUNK_BYTES` | 2048 / 6144 | Chunk size tried / largest escaped chunk |
| `PENDING_LIMIT` | 64 | Outstanding requests (guest), queued local requests (host) |
| `DONE_LIMIT` / `DONE_BYTES` / `REQ_STREAMS` | 64 / 64 KB / 16 | Host result cache per requester stream; streams kept |
| `ACK_HOT_TICKS` | 90 | Frames (1.5 s) a changed ACK keeps the 100 ms resend |

Worst-case memory per game: about 0.5 MB outgoing queue, 2 MB queued blobs, 1.8 MB of incoming blobs (7 senders), and
1 MB host result cache. Typical use is a few kilobytes.

## Performance

These figures are measured with the real helpers on loopback and the reference model as the game, at 20 Hz
(`tests/test_event_bridge.py`), with one guest behind a proxy dropping and duplicating about 9% of datagrams each, and
random traffic running at the same time:

- 4 players: a 100 KB blob reached 4 receivers in 5–6 s.
- 8 players: 6–10 s.

Without competing traffic and loss, a 100 KB blob between two games takes 1.0–1.2 s (about 100 KB/s; three runs each
way). One round trip through the file bridge takes 100–250 ms, and each frame carries at most 12 KB of events. While
events are unacknowledged, each game resends a frame of up to ~12.5 KB every 100 ms per receiver (the host sends to
every guest), up to about 0.9 MB/s from a host with 7 guests, and only until acknowledged. Idle games fall back to one
small frame per second.

## API

All functions are in `MistriMultiEvents.gml`. Kinds are strings of 1–32 characters that do not start with `~`; slots are
0–7, and `-1` means everyone.

| Function | Returns |
| --- | --- |
| `mistrimulti_event_register(kind, handlers)` | `true` if registered (replaces an earlier registration of the kind) |
| `mistrimulti_event_emit(kind, data, target = -1)` | `false` when the queue is full, the event is over 8 KB, or the kind or target is invalid (not this game's own slot) |
| `mistrimulti_event_request(kind, data)` | the request id, or `undefined` (queue full, 64 outstanding, or a resend is waiting) |
| `mistrimulti_event_send_blob(kind, text, target = -1, meta = undefined)` | `false` when over 256 KB, 8 blobs are queued, or `meta` is over 2 KB |
| `mistrimulti_event_can_emit(count)` | whether `count` events of the maximum size would fit now |
| `mistrimulti_event_backlog()` | unacknowledged events |
| `mistrimulti_event_blobs_pending()` | blobs not yet fully queued |
| `mistrimulti_event_requests_pending()` | outstanding requests |
| `mistrimulti_events_debug()` | stream, queue sizes, `errors`, `stalls`, `gaps`, ACKs (also the debug function `mistrimulti.events`) |

Boot calls `mistrimulti_events_initialize`, `_reset` (via the player session reset), `_receive`, `_tick`, `_encode` and
`_reliable`; features do not.

Handlers are named top-level functions taking **three** parameters (declare all three, even when unused). Return `false`
from any of them to mean "not now, retry later"; any other return value means handled.

| Handler | Runs on | Arguments |
| --- | --- | --- |
| `on_event(from, data, ctx)` | every game the event is for (not the sender) | `ctx = { kind, seq, to }` |
| `on_request(from, data, ctx)` | the host, once per request id | return the result struct, or `false`; `ctx = { kind, id, from, mine }` |
| `on_result(0, result, ctx)` | every guest | `ctx = { kind, id, from, mine, lost, expired }` (`from` = requester) |
| `on_reply(0, result, ctx)` | the requester only (host or guest), once | `result` is `undefined` when `ctx.lost` or `ctx.expired` |
| `on_blob(from, text, meta)` | every game the blob is for | the complete text |
| `on_peer(slot, joined, stream)` | every game, for all kinds' handlers | a participant appeared (new session) or left |
| `on_gap(slot, base, expected)` | every game, for all kinds' handlers | events from `slot` between `expected` and `base` were missed |

## How to add a synced feature

Follow this order; the existing `MistriMultiTerrain.gml` is a complete small example.

1. **Decide who owns the state.** World state (crops, chests, animals, the clock, NPCs, quests) is owned by the host.
   Guests never change it directly; they *request*. Purely presentational, per-player data (appearance) may be emitted
   by its owner.
2. **Name your kinds** with a feature prefix (`chest_take`, `chest_state`) and register them in
   `mistrimulti_register_events()` (MistriMultiBoot.gml), by calling one registration function from your file:

   ```gml
   function mistrimulti_chest_register_events() {
       mistrimulti_event_register("chest_take", { on_request: mistrimulti_chest_take, on_result: mistrimulti_chest_apply,
           on_reply: mistrimulti_chest_reply });
       mistrimulti_event_register("chest_state", { on_event: mistrimulti_chest_apply_state, on_peer: mistrimulti_chest_peer });
   }
   ```
3. **Guest action → request.** Validate locally only for responsiveness, then
   `mistrimulti_event_request("chest_take", {...})`. If it returns `undefined`, keep the action pending and try again on
   a later tick (as `mistrimulti_watch_changes` does), or refuse it in the UI.
4. **Host validates and applies in `on_request`**, using the host's own state and the requester's latest frame
   (`__mistrimulti_runtime().peers[from]`: position, room, `uid`). Return a *small* result struct describing the
   authoritative outcome (`{ ok: false }` for a refusal, or the new state of what changed). Never trust counts, items or
   positions from `data` without checking them. It runs once per id; do not keep your own duplicate checks.
5. **Guests apply the result in `on_result`.** Make the result self-describing (the new state, not "+5"), so applying
   it is idempotent and corrects any local prediction. In `on_reply`, finish the requester's UI and handle
   `ctx.lost` / `ctx.expired` (for example by re-reading state).
6. **The host's own actions** are either requests too (simplest: same validation path), or a plain broadcast after
   applying (`mistrimulti_event_emit("chest_state", {...})`), as terrain commits do.
7. **Joining and rejoining.** In `on_peer(slot, joined, stream)` on the host, queue a snapshot of the current state for
   that player (`mistrimulti_event_emit(kind, data, slot)` for small state, `mistrimulti_event_send_blob` for large
   state, or stream it in slices across ticks as `mistrimulti_stream_terrain` does). A guest that gets `on_gap(0, ...)`
   missed host events: its state is re-sent because the host also sees it rejoin, but a guest-side feature may also ask
   explicitly.
8. **Respect back-pressure.** Check `mistrimulti_event_can_emit(n)` before producing bulk output, and keep
   `mistrimulti_event_backlog()` modest when streaming. Never loop until a send succeeds.
9. **Keep events small** (well under 8 KB); use a blob for anything larger, and bound every array you accept.
10. **Validate every field** of incoming `data` (`is_struct`, `is_real`, ranges, array lengths). Data from the network
    is untrusted; an exception is caught, but it still means the event was dropped.
11. **Test it.** Add your handlers to a scenario in `tests/test_event_features.py`: load your file in `FeatureNode`,
    stub only the engine calls it makes, and check the outcome on every game under loss, rejoin and restart. If you
    change the layer itself, change `tests/event_model.py` and `MistriMultiEvents.gml` together; the lockstep test
    fails on any difference.

Things to avoid: storing game instances or methods in event data (JSON only); relying on events emitted before a peer
joined; ordering assumptions between different players' events; sending the same state every tick (emit on change,
and snapshot on join).

## Testing

| Test | What it proves |
| --- | --- |
| `tests/test_event_layer.py` | The model and the GML (run by `tests/gml_subset.py`), separately and mixed, under simulated loss, duplication, reordering, 10 s expiry, reconnects, host restart, world re-entry, slot reuse, back-pressure, stalled handlers and 256 KB blobs, with 1 host and 7 guests. Checks: in-order exactly-once delivery, nothing missing except across reported gaps, requests applied once and answered once, blobs exact, queues drained, frames ≤ 16 KB. A lockstep test requires the model and the GML to publish byte-identical frames on every tick. |
| `tests/test_event_features.py` | The real terrain and player-sync GML on the layer, with the engine stubbed. |
| `tests/test_event_bridge.py` | The real native helpers (Linux, or Windows under Wine) and the real file bridge, with the model as the game: 4 or 8 players, one behind a lossy proxy, 100 KB blobs, a guest helper killed for 13 s, a host restart. |

None of these run the actual game. See `docs/TESTING.md` for what remains to be checked in the game.
