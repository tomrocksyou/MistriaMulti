# Transport and save-discovery probes

Throwaway mods, each separate so one unavailable function cannot hide the others.
Results are written to the MMAPI logs: `%LOCALAPPDATA%\FieldsOfMistria\mod_data\mmapi\logs\<mod>.log`.

| Probe | Question |
| --- | --- |
| `mmprobe_net` | Do GameMaker sockets work from a mod? |
| `mmprobe_native` | Can a mod call native code (`external_define`)? |
| `mmprobe_file` | Round-trip time of the current file bridge |
| `mmprobe_scripts` | Which save/load/menu/sleep scripts and objects exist? |
| `mmprobe_files` | Where does the game keep its saves? |
| `mmprobe_globals` | What global state does the game expose? |

1. Close the game. Uninstall the old probes in MOMI (an error log means a probe failed to load).
2. Copy every `probes/mmprobe_*` folder into the game's `mods/` folder; install them in MOMI
   with MistriMulti unchecked.
3. `python tools/probe_listener.py --data-dir %LOCALAPPDATA%\FieldsOfMistria\mod_data`
4. Start the game, load a save, wait about 2 minutes.
5. Send every `mmprobe_*.log` from `mod_data\mmapi\logs`.
