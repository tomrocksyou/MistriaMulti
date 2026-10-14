# Transport probes

Three throwaway mods that answer: can we replace the file bridge?

| Probe | Question | Output |
| --- | --- | --- |
| `mmprobe_net` | Do GameMaker `network_*` sockets work from a mod? Can replies be received? | `mod_data/mmprobe_net/results.json` |
| `mmprobe_native` | Can a mod call native code (`external_define`)? | `mod_data/mmprobe_native/results.json` |
| `mmprobe_file` | Round-trip time of the current file bridge (baseline) | `mod_data/mmprobe_file/results.json` |

Each is its own mod so a compile error in one (itself a result) cannot hide the others.

1. Close the game. Copy each folder in `probes/` into the game's `mods/` folder.
2. Open MOMI, install the three `mmprobe_*` mods (note any compile errors).
3. Run `python tools/probe_listener.py`, start the game, load any save, wait ~30 seconds.
4. Send back the three `results.json` files (and any MOMI compile errors).

Remove the probe mods afterwards.
