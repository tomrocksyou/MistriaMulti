# Ideas box

Things that are wanted or might be nice, in no particular order. Nothing here is promised.

- **Shared or separate money.** Gold is one shared pool for everyone in a hosted world. When separate houses exist, make shared vs
  separate money a host option. Until then it stays shared.
- **Town rank (renown).** Done: one farm-wide rank, owned by the host like the gold pool (`docs/SYNC-RENOWN.md`; still to be checked in the game).
- **Separate houses.** Shelved for now: the door placed the player wrongly.
- **Tree hit animations.** Show the tree shaking when the other player hits it (today it simply disappears).
- **Map.** Update the other players' markers live while the map is open.
- **Mines.** Same floor, shared monster health; shared movement, boss rooms and seal floors are not done.
- **Villagers.** They agree on room and activity, but exact positions are a few seconds apart.
- **Furniture and ground items inside player buildings, museum donations.**
- **Badge.** Draw it above the other UI and make it show the true state.
- **Sell screen total.** At the end-of-day sell screen a guest can show a different amount than the host (seen: 50 vs 100) while the
  shared gold is correct afterwards. Make the guest's summary show the host's total.
- **Cutscenes.** Every player now watches the world-story scenes themselves (docs/SYNC-STORY.md, "Cutscenes that every player
  watches"); they are not shown at the same time. Seeing one together, in step, is still open (needs a safe way to avoid soft-locks).

## Decided against
- **Bringing an existing singleplayer character into a hosted world.** A guest always makes a new character per world, so nothing in
  anyone's singleplayer saves is ever read or changed by multiplayer (solo saves stay in their own folder and are backed up at launch).
