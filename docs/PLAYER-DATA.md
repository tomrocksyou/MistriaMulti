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

The identity bindings (`trust.json`), the guest key store (`trust_keys.txt`) and the ban list (`deny.txt`) live one level up,
in `mod_data/mistrimulti/`, and apply to every world the host plays.

These files accompany the game save; they are not embedded in its `.sav` archive.
Back up or copy the matching world directory when moving the farm to another
computer. They contain account identifiers and character data and do not belong
in the source repository.

## Included data

- Name, pronouns, birthday and appearance.
- Inventory slots and equipment, including serialized item attributes.
- Gold, essence, renown, health, stamina, mana and free baths. (Gold and renown are mirrors of the shared pool and the shared town
  rank, `docs/SYNC-WALLET.md` and `docs/SYNC-RENOWN.md`: the host's value wins when a player joins.)
- Skill XP, learned spells and perks.
- NPC friendship points, relationship status, known gift preferences and daily
  gift/conversation flags. Daily flags reset when the stored calendar day differs.

The progress record carries the rest of the personal data (personal quests, recipe and
cosmetic unlocks, romance scene history, dating and marriage dates, children, mail, tutorials
and other seen flags, counters, daily flags); see `docs/SYNC-PROGRESS.md` for the full list and
what is still copied from the host's save. The two records together are a character
checkpoint, not a complete standalone game save. Chests and shared item transfers still need
host-controlled transactions. Client-reported progress is validated for shape and
bounds; gameplay actions are not yet recomputed on the host. A uid (Steam ID or local id) is only a claim:
the host binds it to the install fingerprint its helper verified (`docs/SECURITY.md`), so another install cannot use it.

## A character per world

A character belongs to one identity **in one world**: the record in `worlds/<world-key>/players/` (above) is the only place that
decides which character a guest plays. A friend who joins a world that is new to him therefore makes a new character, and the
character he made in another world is not offered, not applied and not changed. How the guest reaches the world decides what
happens (`MistriMultiSaveSpace.gml` records it in `s.entry` when the player starts playing; `MistriMultiBoot.gml` copies it to the
runtime for the session; the guest sends it as `intent` in `profile_request`, `"new"` or `"load"`):

| Entry | The host has no record of this identity in this world | The host has a record |
| --- | --- | --- |
| **Load Game > Multiplayer** (the downloaded worlds) | the character editor, as a new player | the record is restored, **no editor** |
| **New Game > Multiplayer > Join a game** | the character editor | the game asks: **Keep mine** (restore, no editor) or **New character** (the editor) |

The editor of a new character starts from the game's defaults (the default look, the name "Guest", the default pronouns and
birthday), never from the host's character that the guest's game loaded and never from an earlier character of this install.
There is no "start from my last look" button: the owner prefers a fresh start, and a button would need UI nodes that cannot
be checked here. The per-install file `mod_data/mistrimulti/characters/<identity>.json` (and its `.bak`) is still written after the
editor, as a convenience copy of the last character this install made; **nothing reads it any more**. Old files of that kind and the
legacy `character.json` stay on disk untouched; they cannot override a world. (They used to be applied to every world.)

Answering **New character** does not delete anything. The host's old records stay in place while the guest is in the editor (a crash
there loses nothing and the next join finds the old character); on the answer the host copies them to
`players/<identity>.replaced.json` and `players/<identity>.progress.replaced.json`, hands the guest a fresh start (core and
progress, nothing of the old progress is merged in) and the new character's first upload replaces the primary files, after
which the old ones are also the `.bak`. A second replacement overwrites the `.replaced.json` copies. Wire protocol: after
`profile_request` with `intent: "new"` and an existing record, the host answers `profile_exists` instead of the record, the
guest asks, then sends `profile_choice {world, uid, keep}` (1 or 0) and the host answers with the record or `profile_start`.
The host acts only on a choice for a question it asked this session (same slot, epoch and identity); anything else is ignored.

Other per-player host state (the shared wallet and renown mirror, the one-partner-per-villager claims) is not rebuilt at the moment
of the answer; it follows the new records as they upload. A replaced player's old romance claims therefore stay registered
until the new progress record's first upload.

### The character editor, observable

The guest cannot be active (no presence, no checkpoint, no synced action: `character_pending`) until the editor is finished. While
a guest has not finished, the other players' characters are not created in its game either. Every step is logged at warn level
with the prefix `Character editor:`: waiting (with the reason, every 20 s), opening (attempt number and entry), opened or failed
(with the reason; a failed open is retried after 5 s), shown (with the editor's alpha, pause status and load-sequence state), still
not visible after 3 seconds (the state; the mod then calls `request_show(0)` once), still open (every minute), closed without
Continue (it opens again with the same look), Continue tapped (ticks since opening, whether it was ever shown), complete or
completing failed (with the reason; the editor opens again). The question for an existing character is logged too. If a guest
reports "I never saw the editor", these lines say whether it was opened, whether it was visible, whether Continue was tapped
without being shown, or whether the guest was never asked.

The first real-game log of a guest who never saw the editor also showed the host's ghost being created, hidden and destroyed on
every read for as long as the guest was loading. The cause was `mistrimulti_read_peers` creating ghosts while the main tick
(correctly) removed them again for a guest that was not active yet; ghosts are now created only when the guest is playing
(`mistrimulti_local_active`).

## Joining and saving

A guest requests its record before publishing an active character or sending
progress, and then requests its progress record; it becomes active only when both are
applied. A returning player loads the host's records and does not create a character
again (when it entered through Load Game, or answered "Keep mine"; see "A character per world"). A new player receives starter items, the starter kit (the items, baths, spell and tutorial of the host's first-day scenes, which the
guest's copy of the world would otherwise skip: the first hoe and seeds; once, see `docs/SYNC-STORY.md` "Starter kit") and a new
character's progress and opens the
character creator; inventory and money from another local save are not imported.
A world whose players only have core records (made before the progress record existed) keeps
working: the core record is restored as before and the progress starts fresh and is then stored. The same identity cannot occupy two guest slots simultaneously,
and a guest cannot claim the host's identity. An identity is bound to one install on first use (`trust.json` next to the
world folders): a different install claiming it, or a record that has no binding yet, waits for the host's approval (F7),
and an upload is stored only while the slot still reports the bound install.

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
world (`docs/SYNC-GUESTSAVE.md`: what a save attempt, a quit and a lost host do). The host's own native save remains its main character save; its checkpoint
record is also mirrored alongside the guest records.

## In-game checklist (the character per world)

Unverified in the real game: everything below. Use a Windows guest and a host, and read the guest's log (`Character editor:` lines).

1. Host a new world. Guest: New Game > Multiplayer > Join. The editor opens from the default look and name "Guest", whatever the guest
   made before; the log shows opening, opened, shown, Continue tapped, complete. The guest cannot be seen by the host before Continue.
2. Same guest leaves and uses Load Game > Multiplayer, same world: no editor, no question, the character as it was.
3. Same guest uses New Game > Multiplayer > Join again for the same world: the question appears with "Keep mine" and "New character".
   "Keep mine": no editor, old character. Join again, "New character": the editor opens from the defaults; the host's
   `players/<id>.json` is unchanged until Continue; afterwards `.replaced.json` and `.bak` hold the old character.
4. Another world (another host): the editor again from the defaults; the first world's character is untouched.
5. Close the question without choosing (back/escape): it is asked again after a second. Kill the game inside the editor: the next
   join finds the old character (Load Game) or asks again (New Game).
6. If the editor is invisible: the log says `still not visible after 3 seconds (alpha=...)` and the editor appears; send that line.
7. No flicker of the host's character while loading (the log no longer repeats `trace ghost: create ... hide ... cleanup`).

## Source

`MistriMultiPlayerData.gml` captures, validates, restores and writes engine data.
`MistriMultiProgress.gml` does the same for the progress record, commits and restores records with the host's save
and keeps the claim registry of the one-partner rule.
`MistriMultiPlayerSync.gml` handles the world handshake, record transfer and save
confirmation. `MistriMultiEvents.gml` orders, acknowledges and reassembles the
transfers; the assembly networking helper handles transport, fragmentation,
checksums and retries. No additional player runtime is required.
