# Security: who may join, who may be whom, and how much one player can ask

MistriMulti is played with friends, but the host's UDP port may also be reachable by strangers (a port forward, a
public IP, a shared Tailscale network). This page says what the mod protects, what it does not, how to switch the
protection on, and how it was tested. Wire formats are in `docs/PROTOCOL.md`; the record handshake is in
`docs/PLAYER-DATA.md`.

## In one minute

- **Room code**: eight hex digits that name a session. Anyone who sees one packet knows it, and it has only 32 bits.
  It is **not a password**.
- **Host password** (optional, off by default): set it in `launcher.cfg` (`password=...`) or with
  `mistrimulti-manager host --password ...` / the password field of the Windows Join window. With a password set, nobody
  can take a player slot, read the guest key during registration or talk to the host without knowing it.
- **Install key**: every install makes a random 32-byte secret on first start (`install.key`, never sent). A guest's
  identity on a host is a key derived from it. The host remembers the guest's fingerprint; **the same Steam ID or local
  id sent by another install gets nothing** until the host approves it (F7).
- **Every game datagram carries a 16-byte HMAC tag** under a per-session key. Without the handshake a packet is dropped.
- **Limits**: a guest cannot make the host do unbounded work. Packets, snapshots, events, requests, blob bytes, new event
  streams, handshakes and replies are all rate-limited; sizes are bounded; hostile input is rejected, never fatal.
- **Not protected**: confidentiality (packets are signed, not encrypted), a malicious host, the world download on TCP 7775,
  and anything a modified game client can legitimately ask for. See [What is not protected](#what-is-not-protected).

## Threat model

| Who | Can do | Defended by |
| --- | --- | --- |
| Stranger who reaches the host's UDP port and knows the room code | Take a free player slot, forge a friend's snapshots, feed the host any JSON as "a player", flood | Handshake before any slot exists, per-packet tags, per-peer buckets |
| Stranger without the password | The same, when a password is set | Password in the handshake key (never sent), registration key masked with it |
| Passive observer of the network | Read everything, learn who plays | Nothing (no encryption). Cannot forge anything, cannot learn the password, cannot reuse a captured join |
| Active attacker on the path | Drop, delay, replay, spoof the source address | Tags and a nonce cookie bound to the source address; replays are dead; spoofing only denies service |
| Guest who knows a friend's Steam ID | Claim the friend's record (inventory, progress) | Identity binding: uid is bound to the install fingerprint verified by the helper |
| Guest who is a bad citizen | Flood requests, restart event streams, send giant or malformed events | Per-guest limits in the helper and the event layer, size caps, fail-soft handlers |
| Another guest | Same as a stranger, plus uses the same host | Slots belong to fingerprints; a live slot cannot be taken; one install cannot hold two slots |
| Malicious host | Everything: it owns the world and every record | Out of scope (guests only protect their own local save: the host cannot write to it except through the record handshake). A guest pins the host's identity per world and refuses a changed one until it presses F7 |
| Other users of the same computer | Read `launcher.cfg`, `auth.cfg`, `install.key` | Files holding secrets are created 0600 on Linux; Windows uses the user profile's permissions |

## Design

### Why the helper (assembly), not the game's GML

The native helper is the only code that sees every datagram before anything is allocated, written or forwarded, so
admission and tags must live there. The game's GML has no hash function and no reliable randomness, and it only sees
JSON after the helper has already published it. The helper uses the SHA-256 the launchers already ship
(`linux/sha256.inc`, plain assembly, included by both helpers, so there is one implementation and one set of tests on
both systems) and `getrandom` / `BCryptGenRandom` for randomness. HMAC-SHA256 and the password stretching are built on
it in `helper/include/auth.inc`. The GML layer adds what only the game knows: which *player record* an identity may
use (`MistriMultiTrust.gml`), and limits on what a guest may ask the event layer to do.

There is no asymmetric cryptography and no encryption: the repository's toolchain is bare assembly, and HMAC-SHA256 is
the one primitive small enough to implement and test completely. That decides what is promised (authenticity and
integrity, not secrecy).

### Join handshake (UDP, `MSAU` packets)

```text
guest                                              host
  HELLO (128 B: room code, slot, client nonce) ->
                  <- CHALLENGE (64 B: flags, window, cookie, host fingerprint)
  PROOF (128 B: cookie, guest fingerprint, masked key, tag) ->
                  <- WELCOME (48 B: tag)            or REJECT (16 B: reason)
  game datagrams ('MSMP' v2) now carry a 16-byte tag in both directions
```

- The cookie is `HMAC(host secret, window | source address | slot | client nonce)`: the host keeps **no state** for a
  stranger who only sent HELLO, and a PROOF is only looked at when the cookie matches the sender's address.
- `PWK` is the room password stretched with 30 000 rounds of SHA-256 salted with the host fingerprint (32 zero bytes
  with no password). `IK` is the install key. `K = HMAC(IK, "MMBIND1" | host fingerprint)` is the guest's key *for this
  host* (a host that learns it cannot impersonate the guest to another host). The guest fingerprint is
  `SHA256("MMFP2" | K)[0..16]`: it names `K`, so nobody can claim a fingerprint without its key.
- The first time a host sees a fingerprint, the PROOF carries `K` masked with `HMAC(PWK, ...)` and the host stores
  `(fingerprint, K)` in `trust_keys.txt`. Later joins are authenticated against the stored key; the field is ignored.
  With a password, only a password holder can unmask `K`. Without one, `K` crosses the network once in the clear (see
  below).
- `AK = HMAC(PWK, K)` signs the PROOF and the WELCOME (so a guest knows the host holds the same keys: a fake host without
  the password, or without the stored key of a returning guest, cannot complete the join), and
  `SK = HMAC(AK, "MMSK1" | nonces)` is the session key for the data tags. Tags cover the direction byte, the header and
  the payload; the header carries the sender slot, sequence and epoch.
- A slot is created only by a valid PROOF, never by a data packet. A live slot is released only after ten silent seconds
  or by the owner's own fingerprint (the same install rejoining replaces its own session).

Reasons in REJECT: 1 wrong or missing password, 2 banned, 3 slot (or install) already in use, 4 key store full,
6 password needed but this install has none (set locally by the guest helper, never sent).

### Identity binding (the game layer)

The helper writes `<bridge>/auth_<slot>.json` (`{"fp","gen","state","reject"}`) with the verified fingerprint of each
slot. When a guest sends `profile_request` with a uid, `MistriMultiTrust.gml` decides:

1. No verified fingerprint for the slot: refused.
2. uid already **bound** to this fingerprint: admitted.
3. uid unbound and **no record** exists: bound to this fingerprint (first use wins).
4. uid bound to **another** fingerprint, or unbound but a **record exists** (made before bindings): the guest gets
   "needs the host's approval (code XXXXXXXX)" and nothing else; the host sees a notification.

The host presses **F7** to approve the oldest open request (the binding moves to the new fingerprint and the guest
receives its record at once) or **Shift+F7** to refuse and ban that install. Uploads of a record are stored only while the
slot still reports the fingerprint the uid is bound to. Bindings live in `mod_data/mistrimulti/trust.json`
(`{"v":1,"bound":{uid:{fp,name}},"denied":[...]}`). Limits: 4 identities per install, 256 bindings, 8 open approvals.

A guest also remembers the host's fingerprint per hosted world (`known_hosts.json`). If a different host answers for the
same world, the guest sends no record request and shows "the host's identity changed" until it presses F7.

#### Recovery paths

- **A friend reinstalls** (new `install.key`, same Steam ID): the first join shows the code to the host; the host presses
  F7 after confirming the code out of band (for example over voice chat). Nothing else changes.
- **Better**: keep `install.key` (`mod_data/mistrimulti/`). Restoring it restores the identity and no approval is needed.
- **A friend with a local id** (no Steam): the id lives in `local_identity.json`; restore it with `install.key`. A new local
  id is a new character; the host can move the old record file (`players/<old id>.json`, see `docs/PLAYER-DATA.md`) by hand.
- **A binding was wrong or must go**: close the game, delete the entry from `trust.json` (or the whole file: records then
  need approval again). Bindings are never deleted automatically.

### Deny list and kicking

`mod_data/mistrimulti/deny.txt` is read by the host helper once a second. One entry per line: a **32-digit fingerprint**
or a **dotted IPv4 address**; `#` starts a comment; anything else is ignored. A listed player is removed within about a
second (the slot is freed, its snapshot becomes inactive) and gets `REJECT 2` on every later attempt. Delete the line to
lift the ban. F8 on the host lists each connected guest with the first eight characters of its fingerprint; the full
fingerprint is in `<bridge>/auth_<slot>.json`. Refusing a request with Shift+F7 adds the fingerprint to `deny.txt`
(your own lines are kept). To kick without banning, add the line, wait for the removal, and delete it again.

## Abuse limits

| Layer | Limit | Over the limit |
| --- | --- | --- |
| Datagram | 8 to 1208 bytes ('MSMP' 41..1208 with the tag), payload 2..16 384 B in at most 15 fragments | dropped, counted in `dropped` |
| Handshake, per kind (HELLO, PROOF) | 30 per second, burst 30, for all strangers together | silently dropped, counted in `limited` |
| Replies to strangers | never larger than the request (CHALLENGE 64 B for 128 B, RESYNC 16 B at most twice a second) | |
| Cookie | valid for the current and the previous 20 s window, bound to the source address | |
| Replayed PROOF | the last eight accepted nonces are refused | dropped |
| Game packets, per peer | 400 per second, burst 800 | dropped, counted in `limited` |
| Completed snapshots, per peer | 30 per second, burst 60 (each costs a file write and up to six forwards) | not published; the sender retransmits |
| Stored keys, deny list | 256 guests; 64 fingerprints and 64 addresses; `auth.cfg` 4096 B, password 64 B | extra entries ignored |
| Events, per guest (host side) | 300 per second, burst 600 | the event waits, unacknowledged; the guest keeps its queue |
| Requests, per guest | 40 per second, burst 80 | the same: ordered, nothing lost or applied twice |
| Blob bytes, per guest | 512 KiB per second, burst 1 MiB (blobs are at most 256 KiB, 8 at a time) | the same |
| New event streams, per guest | burst 6, then one per ten seconds (each runs every feature's snapshot) | frames of the new stream are ignored |
| Event size | 8 KiB per event, 12 KiB of events per frame, 512 events or 512 KiB queued | refused at the sender |

All numbers are constants at the top of `helper/include/core.inc` / `auth.inc` and `MistriMultiTrust.gml`. The limits protect the
host from a single guest. They do not defend against a flood that fills the network link or the socket buffer; nothing
in user space can.

### What the audit of the receive paths found

| Finding | Where | Fix | Test |
| --- | --- | --- | --- |
| Anyone who knew the room code could claim any free slot, publish arbitrary JSON as that player (including a forged Steam ID) and keep the slot alive. Reproduced on the original helper: one datagram published `rx_1.json`. | `receive_fragment` created the slot from the first packet | Slots exist only after the handshake; tags; address pinning | `test_no_handshake`, `test_hijack` |
| One guest could force unlimited file writes and six-fold forwarding by sending many tiny snapshots | `receive_fragment` / forward loop | Packet and completed-snapshot buckets per peer | `test_limits` |
| A Windows argument that cannot be converted (more than 4096 bytes) became a null pointer: the helper died with a page fault instead of printing the usage. Local only (the launcher builds the command line), but it is the one real memory-safety bug found. Reproduced on the original build. | `parse_arguments` used `pl_arg` unchecked | Every argument is checked | `test_config` (lengths 2001 to 20 000) |
| The receive buffer had no room for the tag; the status buffer was 256 bytes against about 170 used | `packet_in`, `status_buffer` | Sized for the new maximum | covered by every test (a truncated datagram fails its tag) |
| Reassembly arithmetic (fragment count, index, offset, bitmap, `bts`) | `receive_fragment` | Reviewed line by line: every index is checked against the declared length before a byte is copied; the 15-fragment bitmap fits a dword. No out-of-bounds access found. | `test_fuzz`: 3 700 random and correctly tagged malformed datagrams (every length 0..140 and 1150..1260, every handshake type at every length, impossible counts, indexes, lengths, slots, sequences and epochs) |
| The TCP world server and the discovery responder read fixed-size requests only | `linux/launcher.asm`, `launcher/launcher.asm` | Existing tests (`fuzz`, `world server`, `discovery`) cover malformed requests. **Not changed:** the world server serves one connection at a time, so a client that connects and stalls can delay discovery and downloads (never game traffic) | existing launcher tests |

## Setting the password

Pick 1 to 64 letters, digits and punctuation, **without spaces or accents**. Tell friends over a private channel.

| Where | How |
| --- | --- |
| **In the game** (normal way) | Multiplayer -> **Host a game** -> **Set a password (optional)**. Friends type it when they pick the host (the list shows `[password]`). The launcher keeps it only in the helper's `auth.cfg`; the command file that carries it is deleted as soon as it is read (`docs/SYNC-MENU.md`). The password is checked by the join handshake **before** the world is downloaded. |
| `launcher.cfg` (any system) | add a line `password=your-secret-here` (the file is in `mod_data/mistrimulti/`). Remove the line to switch it off. |
| Linux / Steam Deck manager | `mistrimulti-manager host --password SECRET`. Friends: `mistrimulti-manager join IP --password SECRET`, or just `join` and type it when the list shows `[needs a password]`. Running `host` or `join` rewrites `launcher.cfg`: give the password again. |
| Windows manager | Join window: **Room password** field (masked). Hosts: add the `password=` line by hand once; **Host a game** keeps it. |
| `mistrimulti-launcher --configure` / `MistriMultiLauncher.exe --configure` | keep an existing `password=` line; they do not ask for one. |

A password that is too long, has a space, a control character or a non-ASCII character stops multiplayer from starting
(the game itself starts normally, the reason is in `launcher.log`; a bad `launcher.cfg` now leaves the launcher in standby, where
nothing is hosted or open, and the in-game menu is still available; the in-game menu refuses such a password before sending it). The launcher also refuses to start the helper if it
cannot write the password to `auth.cfg`. The helper stops with exit code 4 if it is handed a bad password. It never
falls back to an open room.

A password the host forgets to give a friend shows as "The host needs a password" in F8. A wrong password shows as
"wrong or missing password". The guest retries every three seconds, so fixing `launcher.cfg` and restarting the game is
enough.

What a password is worth: the stretching makes an offline guess cost 30 000 SHA-256 rounds, but a recorded handshake can
be attacked offline. Use a long random one if the host is on the open internet. Switching the password off or changing
it does not delete the stored guest keys.

## Files

| File (in `mod_data/mistrimulti/`) | Written by | Holds | Secret |
| --- | --- | --- | --- |
| `launcher.cfg` | manager, launcher, you | mode, port, room, `password=` | password |
| `bridge_N/auth.cfg` | launcher, at every start | paths of the files below, `pass=` | password (0600) |
| `install.key` | helper | 32 random bytes | yes (0600). Back it up to keep an identity |
| `trust_keys.txt` | host helper | `<fingerprint> <key>` of every guest | yes |
| `trust.json` | host game | uid to fingerprint bindings, bans | no |
| `deny.txt` | you, host game | bans | no |
| `known_hosts.json` | guest game | world to host fingerprint | no |
| `bridge_N/auth_<slot>.json` | helper | verified fingerprint, session counter, state | no |

## What is not protected

- **Secrecy.** Packets are authenticated, not encrypted. Anyone on the path sees positions, names, inventories in transit
  and events. Use Tailscale or a VPN if that matters.
- **The first join without a password.** The guest key crosses the network once unmasked. An attacker who recorded that
  exact join can impersonate that install afterwards. With a password this does not happen. Later joins reveal nothing new.
- **Joining without a password** lets any stranger take a free slot (bound to a fresh install key, so it cannot take over
  a friend's record). Set a password if strangers can reach the port.
- **The host.** It owns the world, every guest's record and the rules. A guest only trusts it with its character after the
  host's identity matched the pin. A malicious host can still send harmful events within the event layer's validation.
- **A modified client** can ask the host for anything the protocol allows (the host validates every request, see the
  `SYNC-*` pages); this page adds identity and rate limits, not game rules.
- **The world download** (TCP 7775) is not authenticated: anyone who can connect gets the host's newest save. A password
  does not cover it yet.
- **Denial of service** by saturating the link, or of *new joins* by flooding handshake packets (30 per second per kind
  are accepted from strangers; established sessions are not affected). Spoofed-source floods cannot be told apart from
  real ones by an unconnected UDP service.
- **Steam IDs** are claims. Binding stops a second install from using one; it does not prove the player owns the account.
- **Clock and replay of old data inside a session.** Within one session, sequence numbers decide: an old snapshot is
  dropped, an identical one is idempotent.

## Manual checklist

Run this when you change the helper, the launcher or `MistriMultiTrust.gml`, or before a release:

1. Host with no password: a friend joins, plays, and a second friend joins; both appear. Restart the host's game; the
   friends rejoin within a few seconds without touching anything.
2. Set `password=...` on the host. A friend without it sees "The host needs a password" (F8); with the wrong one, "wrong
   or missing password"; with the right one, joins. The host's F8 shows the friend with an eight-character code.
3. From another machine on the same network run `nc -u HOST PORT` and type junk; nothing appears in the game and F8 is
   unchanged. (Optional: a UDP fuzzer; the helper must keep running and the friends must stay connected.)
4. A friend's second computer (different install) joins with the same Steam ID: it is told to wait for the host's
   approval and receives nothing; the host sees the notification, **F7** approves (check the code first); Shift+F7 refuses
   and bans.
5. Reinstall check: delete `install.key` on a friend's machine, rejoin: the host is asked to approve; restore the file:
   no approval is needed.
6. Add a friend's fingerprint to `deny.txt` while they play: they disappear within seconds and cannot rejoin. Remove
   the line: they can.
7. Join the same room twice from one computer with the same `install.key`: the second is told the slot is in use.
8. Start a guest against a host whose game is not running: no crash, hello retries about once a second.
9. Confirm `install.key`, `trust_keys.txt` and `auth.cfg` are not group or world readable (Linux: `ls -l`).
10. `tests/test_trust.py` (both helpers), `tests/test_trust_gml.py`, `tests/test_event_bridge.py`, then the launcher suites.

## Tests

```sh
python3 tests/test_trust.py build/mistrimulti-helper-linux        # re-runs itself in `unshare -n`
python3 tests/test_trust.py build/mistrimulti-helper.exe          # under Wine on Linux, directly on Windows
python3 tests/test_trust_gml.py                                   # identity binding, limits, hostile frames (no ports)
```

`tests/mmauth.py` is the reference implementation of the handshake; `test_trust.py` uses it as the guest against the
real host helper and as the host in front of the real guest helper. See `docs/TESTING.md` for what each test proves and
what they cannot (the game's real file reading, the hotkey chord, real networks).
