# Player records

The host owns a separate record for each player in each hosted world. A world key
combines the host's stable identity with the game's saved world identifier. Player
slots are temporary network addresses; changing slots does not change the record.

A player has two records: the **core record** (this page: appearance, inventory, money,
skills, friendship) and the **progress record** (recipes, almanac, mail, personal quests,
romance and family, cosmetics, counters, daily flags). `docs/SYNC-PROGRESS.md` audits every
field the game saves, says which part is personal and which belongs to the world, and
describes the progress record, the host save commit and the one-partner-per-villager rule.

Files live in the game's configuration directory:

```text
mod_data/mistrimulti/worlds/<world-key>/
    world.json
    roster.json
    members.json                              identities that have records
    players/<player-identity>.json            core record (+ .bak)
    players/<player-identity>.progress.json   progress record (+ .bak)
    commits/<save name>.json                  records committed with a host save (+ .bak)
    commits/discarded.json                    records replaced by the last rollback
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

The progress record carries the rest of the personal data (personal quests, recipe and
cosmetic unlocks, romance scene history, dating and marriage dates, children, mail, tutorials
and other seen flags, counters, daily flags); see `docs/SYNC-PROGRESS.md` for the full list and
what is still copied from the host's save. The two records together are a character
checkpoint, not a complete standalone game save. Chests and shared item transfers still need
host-controlled transactions. Client-reported progress is validated for shape and
bounds; gameplay actions are not yet recomputed on the host, and the UDP transport
does not authenticate a claimed remote Steam ID.

## Joining and saving

A guest requests its record before publishing an active character or sending
progress, and then requests its progress record; it becomes active only when both are
applied. A returning player loads the host's records and does not create a character
again. A new player receives starter items and a new character's progress and opens the
character creator; inventory and money from another local save are not imported.
A world whose players only have core records (made before the progress record existed) keeps
working: the core record is restored as before and the progress starts fresh and is then stored. The same identity cannot occupy two guest slots simultaneously,
and a guest cannot claim the host's identity.

Checkpoints run about every five seconds while the character is ready. The first
checkpoint also runs after character creation. Only changed records are sent, and of the
progress record only the changed sections.
A core record holds at most 128 KiB of encoded data and travels as one event-layer blob
(`docs/EVENT-LAYER.md`): it is delivered whole, with a length and hash check, or not at
all, so partial uploads never replace the last saved record.

The host validates a complete upload, preserves the last valid backup, writes a
temporary file and renames it into place. It then confirms the saved revision to
the guest. A damaged primary record can fall back to its backup; if neither is
valid, the host reports a recovery error instead of creating a replacement player.

Each host save also commits copies of the players' records next to the save
(`commits/`), and loading that save restores them, so reloading the host's world never
leaves a player with records from a later moment than the world (`docs/SYNC-PROGRESS.md`,
"Host save commit").

Disconnects or crashes can lose progress after the last confirmed checkpoint.
Transfers may take longer than the checkpoint interval when peers or the network
are waiting. The F8 status message shows pending saves and record-loading errors.
Guest native saves are blocked throughout multiplayer to protect their local
world. The host's own native save remains its main character save; its checkpoint
record is also mirrored alongside the guest records.

## Source

`MistriMultiPlayerData.gml` captures, validates, restores and writes engine data.
`MistriMultiProgress.gml` does the same for the progress record, commits and restores records with the host's save
and keeps the claim registry of the one-partner rule.
`MistriMultiPlayerSync.gml` handles the world handshake, record transfer and save
confirmation. `MistriMultiEvents.gml` orders, acknowledges and reassembles the
transfers; the assembly networking helper handles transport, fragmentation,
checksums and retries. No additional player runtime is required.
