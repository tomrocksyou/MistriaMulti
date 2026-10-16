# Helper performance (load test)

These numbers come from `tests/loadtest_helper.py`. **This is a loopback simulation on one machine, not a real
network and not the real game.** A host helper and up to seven guest helpers (the real assembly programs) talk over
127.0.0.1 inside a private network namespace; the game side of each player is the Python reference model
(`tests/event_model.py`) driven by the harness of `tests/test_event_bridge.py`. Real networks add latency, jitter,
loss and a bandwidth limit that loopback does not have, and the real game's frames may be smaller or larger than the
3 KB used here.

## What the test does

For the whole run every player's game side:

- writes `tx.frame` every 50 ms (20 Hz) with a new frame of about 3 KB each time (position fields plus 3000
  changing characters standing in for player state), reads `status.json` once a second and every peer's
  `rx_<slot>.json` at 20 Hz;
- sends about 10 small events per second and 3 requests per second (the test feature of `tests/test_event_layer.py`);
- the host sends a 100 KB blob to all guests every 5 s, every guest sends a 10 KB record to the host every 6 s.

It measures the helper processes only: CPU is the process's own `utime+stime` (`/proc/<pid>/stat`; `GetProcessTimes`
on Windows), memory is `VmRSS`/`VmHWM`. Other jobs on the machine therefore do not change the CPU figures. Packet counts
come from the helper's own `status.json` (`rx` counts complete snapshots accepted, `tx` counts datagrams sent), bytes from
`/proc/net/dev` of the namespace (the helper does not count bytes). A world download (TCP 7775) is not included: the
helper does not serve it, the launcher/manager does (see `tests/test_world.py`). After each run the traffic stops and
every blob must have been delivered (all were).

## Machine

4 cores (`nproc`), Intel(R) Xeon(R) Processor @ 2.10GHz (a virtual machine), Linux 6.18.44-fc-v139, mod 0.4.7, other test
jobs running at the same time. The harness held 19.9 game ticks per second per player in every run.

## Results (Linux helper, 60 s per run after 5 s warm-up)

CPU is percent of ONE core. "max" is the highest 1-second window. "Guest" is guest 1. RSS start is 5 s after the players
are admitted, end is after 60 s.

| Run | Role | CPU avg % | CPU max % | RSS start KB | RSS end KB | Peak KB | snapshots/s in | datagrams/s out | datagrams/s in | KB/s in | KB/s out |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 guest | host | 0.70 | 1.99 | 116 | 152 | 152 | 20 | 100 | 65 | 74 | 114 |
| 1 guest | guest | 0.68 | 2.00 | 116 | 148 | 148 | 20 | 65 | ~100 | 114 | 74 |
| 3 guests | host | 2.22 | 3.50 | 152 | 220 | 220 | 58 | 712 | 200 | 222 | 792 |
| 3 guests | guest | 1.28 | 2.86 | 140 | 204 | 204 | 58 | 67 | ~237 | 264 | 75 |
| 7 guests | host | 6.98 | 8.94 | 240 | 340 | 340 | 131 | 3955 | 529 | 536 | 4012 |
| 7 guests | guest | 2.27 | 2.99 | 232 | 332 | 332 | 130 | 75 | ~565 | 573 | 77 |
| 3 guests, guest 2 behind 10% loss / 10% duplication | host | 3.10 | 5.00 | 148 | 216 | 216 | 48 | 1227 | 318 | 354 | 1368 |
| same | guest 1 (clean path) | 1.45 | 2.99 | 144 | 208 | 208 | 50 | 104 | ~409 | 456 | 116 |
| same | guest 2 (lossy path) | 2.05 | 3.00 | 148 | 212 | 212 | 25 | 117 | ~409 | 456 | 131 |

Notes on the columns: datagrams/s in for the host is the sum of the guests' `tx` (exact on a clean path); for a guest it is
the host's `tx` divided by the number of guests (an estimate, marked ~). KB/s is datagrams/s times the mean datagram size
seen on loopback (about 1.0-1.2 KB including 28 bytes of IP and UDP headers). A 3 KB frame is 3 datagrams. The whole
namespace carried 165 / 910 / 4452 / 2106 datagrams/s (1 / 3 / 7 / 3-lossy guests), i.e. 188 KB/s, 1.0 MB/s, 4.5 MB/s and 2.3 MB/s.
Under loss the lossy guest receives fewer snapshots (25/s instead of 50/s): the proxy drops any frame that loses a fragment
and the game just takes the next one.

Longer run: 7 guests for 240 s, host 7.7% average (10.9% max), guest 2.5% (4.0% max), RSS flat at 340 KB (host) and 332 KB
(guest) from the first 10-second sample to the last (23 samples); 602 of 602 blob deliveries arrived.

Windows helper under Wine (`build/mistrimulti-helper.exe`, 30 s runs; the figures are the Wine process, wineserver not
included, so they include Wine's own overhead):

| Run | Role | CPU avg % | CPU max % | RSS start KB | RSS end KB | snapshots/s in | datagrams/s out |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 guests | host | 5.03 | 7.60 | 16928 | 16980 | 60 | 701 |
| 3 guests | guest | 3.23 | 4.75 | 16728 | 16760 | 55 | 68 |
| 7 guests | host | 23.08 | 28.95 | 17028 | 17132 | 99 | 5124 |
| 7 guests | guest | 6.49 | 7.76 | 16952 | 17068 | 101 | 160 |

## What looks alarming, and why

- **Host CPU at 7 guests is 7-8% of one core (above the 5% line), 11% in the worst second.** This is the fan-out of the
  star topology, not a defect found in the code: the host forwards every accepted frame of every player to every other
  player, so the host sends about N x N frames per 50 ms (7 guests: 8 players x 7 receivers x 3 fragments x 20 Hz, plus
  retransmits and blobs, is about 4000 datagrams/s) while a guest sends 75/s. CPU grows with the square of the player count
  (0.7 -> 2.2 -> 7.0% for 1 -> 3 -> 7 guests). Per datagram it is about 15 microseconds, about half of it in the
  kernel (the user-mode share of the host's CPU was 36-48%; the rest is send/receive system calls). I did not profile the user
  part; the per-datagram authentication tag (HMAC-SHA256, `docs/PROTOCOL.md`) is the obvious candidate but that is an
  assumption. Under Wine the same load costs 23% of a core on the host, and it dropped to 99 snapshots/s in where 140 are
  possible, so a 7-guest host on the Windows helper under Wine on a busy 4-core machine is near its limit (a native Windows
  host was not measured).
- **Bandwidth, not CPU, is the real limit of a big room.** At 7 guests the host sends about 4 MB/s (32 Mbit/s) and each guest
  receives about 0.57 MB/s (4.6 Mbit/s) with 3 KB frames at 20 Hz, because every guest gets the other six frames from the host.
  A home upload link will not carry that; 3 guests need about 0.8 MB/s (6 Mbit/s) from the host. A smaller real frame or a lower
  frame rate scales this down linearly. Loopback hides all of this, so test over a real link before promising 8 players.
- **Memory growth during the run (+32 to +124 KB) is warm-up, not a leak.** The helper's RSS rises during the first ten seconds
  (receive and reassembly buffers are touched the first time a peer sends) and is then constant: the 240-second run shows 340 KB
  from the first 10-second sample to the last, and the Wine runs change by about 100 KB. The "start" figure is taken 5 s after
  admission, so it is inside that rise. Memory scales with the number of peers (116 KB with 1 guest, 340 KB with 7).
- Delivery: no blob was lost or refused, in any run including the lossy one; the lossy guest's frames arrive at half the rate
  (above) but events and blobs are reliable.

## How to rerun

```
sh scripts/build-linux.sh                                   # builds build/mistrimulti-helper-linux
python3 tests/loadtest_helper.py build/mistrimulti-helper-linux --matrix --seconds 60   # this table (about 8 minutes)
python3 tests/loadtest_helper.py build/mistrimulti-helper-linux --guests 7 --seconds 240 # one run, any 1-7 guests
python3 tests/loadtest_helper.py build/mistrimulti-helper-linux --guests 3 --lossy       # guest 2 through the loss proxy
sh scripts/build-helper.sh && python3 tests/loadtest_helper.py build/mistrimulti-helper.exe --guests 3 --seconds 30  # Windows helper (Wine)
```

The script re-runs itself in `unshare -n` (needs root or a user namespace) with `lo` up, so it cannot collide with other tests'
ports. Options: `--blob-kb` (host blob size, default 100), `--seconds`, `--guests`, `--lossy`, `--matrix`. Run nothing else heavy
at the same time if you want the delivery figures to be comparable; the CPU figures are per process and are less sensitive.
