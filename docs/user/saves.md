# Saves

- [Where your saves are](#where-your-saves-are)
- [Backing up](#backing-up)
- [Bringing a save from an emulator, or taking yours there](#bringing-a-save-from-an-emulator-or-taking-yours-there)

## Where your saves are

| | Windows | Linux |
|---|---|---|
| Saves | `user\save\<user id>\` in the game folder | `~/.local/share/hookshot/save/<user id>/` |

`<user id>` is a folder with a 32-character name. On Linux, `$XDG_DATA_HOME` replaces `~/.local/share` when it's set.
To keep saves somewhere else, start the game with `--user <folder>`: saves then go in `<folder>/save/<user id>/`.

Each save folder holds:

```
account.sav
option.sav            the game's own settings (camera, text speed, ...)
slot_00/ ... slot_NN/ one folder per save slot
  progress.sav
  caption.sav
```

## Backing up

Close the game, then copy the whole save folder somewhere safe. To restore, close the game and copy it back. Updates
keep your saves, but a backup before updating costs nothing.

## Bringing a save from an emulator, or taking yours there

Hookshot and the emulators that run this game keep saves in **the same files**. Moving a save is a plain copy: nothing
is converted, and you carry on at the same spot.

### Where each program keeps them

| Program | Windows | Linux |
|---|---|---|
| Hookshot | `<game folder>\user\save\<user id>\` | `~/.local/share/hookshot/save/<user id>/` |
| [Lichii](https://github.com/zortos293/Lichii) | `%APPDATA%\lichii\` + the Eden path below | `~/.local/share/lichii/` + the Eden path below |
| [Eglantine](https://github.com/Djihads80/Eglantine) | `%APPDATA%\eglantine\` + the Eden path | `~/.local/share/eglantine/` + the Eden path |
| [Orchid](https://github.com/MythosOfs/Orchid), [PokeDinner](https://git.eden-emu.dev/Franseven/PokeDinner-a-Eglantine-Fork), [Frizti](https://github.com/Frizti/Lichii) | `%APPDATA%\eden\` + the Eden path | `~/.local/share/eden/` + the Eden path (Frizti is Windows only) |
| [NX2navi](https://github.com/tangerineturtle1/NX2navi) | `<game folder>\profile\save\<account>\` | `<game folder>/profile/save/<account>/` |

The Eden path is `nand/user/save/0000000000000000/<profile id>/0400486024DEC000/`, where `<profile id>` is the
emulator's user profile you play with.

Orchid, PokeDinner and Frizti share one folder, so a save there is the same save in all three. Older Lichii builds
used the `eden` folder too; the script below checks both. If you run an emulator in portable mode (a `user` folder
beside the program), point the script at that folder with `--from` or `--to`.

### Copy with the script

[`oot_saves.py`](https://github.com/NotRexed/Hookshot/blob/main/scripts/oot_saves.py) finds the folders, backs up
the side it overwrites, and copies the save one way. Download it (it's a single file) and run it with Python 3; it
needs nothing else.

On Linux:

```sh
python3 -I oot_saves.py list                   # every save it finds, its slots, and when each was saved
python3 -I oot_saves.py import lichii          # Lichii -> Hookshot
python3 -I oot_saves.py export lichii          # Hookshot -> Lichii
python3 -I oot_saves.py import --from ~/Downloads/my-save   # any folder holding a save -> Hookshot
```

On Windows, also tell it where your game folder is:

```powershell
python -I oot_saves.py import lichii --hookshot "C:\Users\you\Games\Hookshot"
python -I oot_saves.py export nx2navi --hookshot "C:\Users\you\Games\Hookshot"
```

Program names: `lichii`, `eglantine`, `orchid`, `pokedinner`, `frizti`, `eden`, `nx2navi`.

| Option | What it does |
|---|---|
| `--dry-run` | Shows what it would copy, and changes nothing |
| `--keep-settings` | Leaves the target's `option.sav` alone, so each program keeps its own game settings |
| `--profile <id>` | Which emulator profile to use, when more than one has saves |
| `--from <folder>`, `--to <folder>` | The emulator's save folder, or a folder above it to search |
| `--hookshot <folder>` | Hookshot's game folder (Windows) or data folder |
| `--backup-dir <folder>` | Where to put the backup |
| `--force` | Copies even if a game seems to be running |

The script won't run while it sees Hookshot or one of these emulators running. Before copying, it saves the side
being overwritten in `oot-save-backups/` (in `~/.local/share` on Linux, `%LOCALAPPDATA%\Hookshot` on Windows). To
undo a copy, put that backup back.

### Copy by hand

1. Close both programs.
2. Back up the folder you're copying into.
3. Delete its `slot_*` folders, so no old slot gets mixed in with the new save.
4. Copy the **contents** of the save folder you're leaving into the folder you're going to.

### Good to know

- Close both programs before copying. A running game can write its save again when it exits and undo your copy.
- Don't run two programs on the same save folder at the same time.
- `option.sav` holds the game's own settings and is copied with the save. Use `--keep-settings` to keep them separate.
- Start each program once and save before your first copy, so its save folder exists.
- NX2navi finishes writing a save the next time it starts. If the script says a save is waiting, start NX2navi once,
  quit it, then copy. NX2navi's launcher also has its own **Import Saves**.
- Copying between Hookshot and Lichii has been tested on Linux. The other programs' folders come from their source
  code and haven't been tried.
