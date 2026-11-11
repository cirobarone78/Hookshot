# Hookshot-local achievements

Hookshot can store achievement progress on this PC, separately from game saves. Progress is written beside
`hookshot_options.ini` as `hookshot_options.ini.achievements`. The menu page is Insert → Gameplay → Achievements.
Existing local IDs 0–97 are retained so progress files keep their indexes.

New unlocks appear as four-second notifications. If several arrive together, Hookshot shows them one at a time in the
order received, and writes each unlock to `hookshot_log.txt`.

The entries currently use numbered placeholder names and descriptions. Automatic unlock triggers are disabled until
their game events are identified and verified in play; loading an existing save therefore cannot unlock entries or
queue a burst of notifications. The icon is drawn from Hookshot's own UI primitives: locked entries are grayscale, and
unlocked entries use color. No downloaded badge artwork or third-party achievement text is included.

## Trigger work

Implement each unlock only after confirming its signal in a running game:

1. Identify reliable signals for item acquisition, boss and minigame results, damage, current hearts, healing, equipment
   use, falls, scores, and game completion. Use the existing GameData and bank-name readers in `host/hos_main.c` and
   validate each signal against play.
2. Track temporary boss or minigame state per player and update it from `oot_update_player_cheats` each game frame. Start
   only on a confirmed entry event and evaluate only on a confirmed result event.
3. Track session-only conditions in session state. Keep full-run state separate per game save slot and clear it only
   when that save is replaced or a new run begins.
4. Call `rx_option_set(HOS_OPT_ACHIEVEMENT_BASE + id, 1)` only when the exact condition passes. Keep progress local and
   route unlocks through the existing save and notification path.
5. Check positive and negative cases for every trigger, including that a save load does not award an achievement and
   that another save slot does not inherit run progress.

Any future achievement names, descriptions, or artwork must be original or have a compatible license and a
`PROVENANCE.md` record. The removed community-authored catalog should be used only if the maintainers confirm that its
text can be included.
