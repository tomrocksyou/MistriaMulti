# Player records

The host owns a separate record for each player in each hosted world. A world key
combines the host's stable identity with the game's saved world identifier. Player
slots are temporary network addresses; changing slots does not change the record.

Files live in the game's configuration directory:

```text
mod_data/mistrimulti/worlds/<world-key>/
    world.json
    roster.json
    players/<player-identity>.json
    players/<player-identity>.json.bak
```

These files accompany the game save; they are not embedded in its `.sav` archive.
Back up or copy the matching world directory when moving the farm to another
computer. They contain account identifiers and character data and do not belong
in the source repository.

## Included data

- Name, pronouns, birthday and appearance.
- Inventory slots and equipment, including serialized item attributes.
- Gold, essence, renown, health, stamina, mana and free baths.
- Skill XP, learned spells and perks.
- NPC friendship points, relationship status, known gift preferences and daily
  gift/conversation flags. Daily flags reset when the stored calendar day differs.

Quests, recipe and cosmetic unlocks, romance scene history, marriage dates and
children require further integration. This record is a core character checkpoint,
not a complete standalone game save. Chests and shared item transfers still need
host-controlled transactions. Client-reported progress is validated for shape and
bounds; gameplay actions are not yet recomputed on the host, and the UDP transport
does not authenticate a claimed remote Steam ID.

## Joining and saving

A guest requests its record before publishing an active character or sending
progress. A returning player loads the host's record. A new player receives starter
items and opens the character creator; inventory and money from another local save
are not imported. The same identity cannot occupy two guest slots simultaneously,
and a guest cannot claim the host's identity.

Checkpoints run about every five seconds while the character is ready. The first
checkpoint also runs after character creation. Only changed records are sent.
A record holds at most 128 KiB of encoded data and travels as one event-layer blob
(`docs/EVENT-LAYER.md`): it is delivered whole, with a length and hash check, or not at
all, so partial uploads never replace the last saved record.

The host validates a complete upload, preserves the last valid backup, writes a
temporary file and renames it into place. It then confirms the saved revision to
the guest. A damaged primary record can fall back to its backup; if neither is
valid, the host reports a recovery error instead of creating a replacement player.

Disconnects or crashes can lose progress after the last confirmed checkpoint.
Transfers may take longer than the checkpoint interval when peers or the network
are waiting. The F8 status message shows pending saves and record-loading errors.
Guest native saves are blocked throughout multiplayer to protect their local
world. The host's own native save remains its main character save; its checkpoint
record is also mirrored alongside the guest records.

## Source

`MistriMultiPlayerData.gml` captures, validates, restores and writes engine data.
`MistriMultiPlayerSync.gml` handles the world handshake, record transfer and save
confirmation. `MistriMultiEvents.gml` orders, acknowledges and reassembles the
transfers; the assembly networking helper handles transport, fragmentation,
checksums and retries. No additional player runtime is required.
