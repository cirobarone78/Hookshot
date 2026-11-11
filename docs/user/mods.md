# Mods

Hookshot loads mods that replace or add the game's files (textures, models, text, ...), in the same layout
emulators use.

## Installing a mod

1. Make a `mods` folder in the game folder, next to `hookshot.exe` (Windows) or `hookshot` (Linux).
2. Put each mod in a folder of its own inside it, so the game's files are at `mods/<mod name>/romfs/...`.
   Layouts made for emulators, such as `mods/contents/<title id>/<mod name>/romfs/...`, work too.
3. Start the game. `hookshot_log.txt` lists each mod it loaded and the files it read from it.

To keep mods somewhere else, start the game with the environment variable `HOS_MODS` set to that folder. (It can't
go in `hookshot_env.txt`, which doesn't accept folder paths.)

## Turning mods off and choosing the order

- **Off:** rename the mod's folder to start with `-` or `_` (for example `_HD-Textures`).
- **Order:** when two mods change the same file, the one whose folder name sorts last wins. Number them (`01-...`,
  `02-...`) to control it.

## What doesn't work

Only file mods (`romfs`) load. Code patches (`exefs`, `.pchtxt`, `.ips`) are ignored: Hookshot turns the game's code
into a PC program when it builds the game, so there's no code left to patch at run time.

## Mods that make files bigger

The game sets aside a fixed amount of memory for each file, listed in its resource size table
(`System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs`). A modded file bigger than that doesn't
load: the game carries on without it, or a loading screen never ends.

Mods that enlarge files (HD texture packs, for example) ship their own copy of that table with bigger entries. Only
one table is used, the one in the mod that sorts last. So if you combine two mods that each enlarge files, you need a
table that covers both, in the mod that sorts last.

Hookshot adds its own button-prompt entries to whichever table is used, so your controller's button icons still show
in the game's text.
