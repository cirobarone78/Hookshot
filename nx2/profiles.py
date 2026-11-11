"""The launcher's profiles: each one is a user of the game with saves of its own, save/<id> in the game's user folder.

The game plays the profile HOOKSHOT_PROFILE=<id> names (host/nn_applet.c) while it is on the list; without it, or with
one that is not, the default profile, the one user every build had before profiles, so its saves stay where they were.
The list is profiles.txt in the user folder, one "<id> <name>" a line: the game reads it there too. An id is 32 hex
digits, the save folder's name (host/nn_fs.c).

A profile's saves are imported from the emulators by scripts/oot_saves.py (docs/saves.md), with its --hookshot naming
the profile's save folder. Export copies them into a new folder of the player's choosing, never into an emulator.
Removing a profile moves its saves to save-backups/<id>-<time> in the user folder: nothing is deleted.

The Hookshot Builder asks this module (its launcher page) and so does builder/linux/hookshot-launch's profile= line.

    python -I nx2/profiles.py list <game folder>
    python -I nx2/profiles.py add <game folder> <name>
    python -I nx2/profiles.py rename <game folder> <id> <name>
    python -I nx2/profiles.py remove <game folder> <id>
    python -I nx2/profiles.py export <game folder> <id> <parent folder>

Every command prints one JSON object; a failure is {"error": "..."} and a nonzero exit status.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

DEFAULT = "5a3c9e1f0b7d24680000000000000001"   # (the uid host/nn_applet.c always had)
PREFIX = DEFAULT[:16]
LIST = "profiles.txt"
NAME_MAX = 32
_ID = re.compile(r"[0-9a-f]{32}")


def user_dir(folder, environ=os.environ):
    """The folder the game keeps saves in when the launcher starts it, as host/hos_main.c's saves_dir chooses it:
    $XDG_DATA_HOME/hookshot or ~/.local/share/hookshot, unless a user folder is still beside it. The game moves that one's
    entries there at its next start, and plays the one beside it when some could not go: either way the game finds what
    the launcher wrote there (profiles.txt, save/<id>) where the launcher reads it next. The only copy of the rule
    outside the game: hookshot-launch leaves the profile to the game, which checks it against the list in its folder."""
    beside = os.path.join(folder, "user")
    try:
        if os.listdir(beside):
            return beside
    except OSError:
        pass
    xdg, home = environ.get("XDG_DATA_HOME", ""), environ.get("HOME", "")
    if xdg.startswith("/"):
        return os.path.join(xdg, "hookshot")
    if home.startswith("/"):
        return os.path.join(home, ".local", "share", "hookshot")
    return beside


def supported(folder):
    """Whether the game in folder plays the launcher's profile: nx2/make_game.py writes profiles=1 into its
    hookshot_version.txt. A game built before profiles ignores HOOKSHOT_PROFILE and plays the default profile's saves,
    whichever profile is chosen, so the launcher offers none for it."""
    try:
        with open(os.path.join(folder, "hookshot_version.txt"), encoding="utf-8") as f:
            return any(line.strip() == "profiles=1" for line in f)
    except (OSError, UnicodeDecodeError):
        return False


def shown_name(uid, name):
    """the name the profile list shows: the default profile says it is, whatever it is called, so that it is clear why it
    cannot be removed"""
    return "%s (default)" % name if uid == DEFAULT else name


def clean_name(name):
    return " ".join((name or "").split())[:NAME_MAX]


def load(user):
    """[(id, name)], the default profile first"""
    profiles = []
    try:
        # (a name a hand edit wrote in another encoding is shown with a replacement character: its id is ASCII and is kept,
        # so the next store does not drop the profile)
        with open(os.path.join(user, LIST), encoding="utf-8", errors="replace") as f:
            for line in f:
                uid, _, name = line.strip().partition(" ")
                uid = uid.lower()
                if _ID.fullmatch(uid) and uid != "0" * 32 and all(uid != p[0] for p in profiles):
                    profiles.append((uid, clean_name(name) or uid[-4:]))
    except OSError:
        pass
    if all(uid != DEFAULT for uid, _ in profiles):
        profiles.insert(0, (DEFAULT, "Player"))
    else:
        profiles.sort(key=lambda p: p[0] != DEFAULT)
    return profiles


def store(user, profiles):
    os.makedirs(user, exist_ok=True)
    path = os.path.join(user, LIST)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write("# Hookshot's profiles: the save folder (save/<id>) and the name the launcher shows\n")
        f.writelines("%s %s\n" % (uid, name) for uid, name in profiles)
    os.replace(path + ".tmp", path)


def add(user, name):
    """a new profile, with no saves yet: the game starts it at an empty file select. Returns its id."""
    name = clean_name(name)
    if not name:
        raise ValueError("Give the profile a name.")
    profiles = load(user)
    if any(n.casefold() == name.casefold() for _, n in profiles):
        raise ValueError('There is a profile called "%s" already.' % name)
    # (a removed profile's id is not reused: its saves, moved to save-backups/<id>-<time>, and a launcher's profile= that
    # still names it would be taken for the new profile's)
    taken = set(p[0] for p in profiles)
    for folder in ("save", "save-backups"):
        try:
            taken.update(n[:32].lower() for n in os.listdir(os.path.join(user, folder)))
        except OSError:
            pass
    n = 2
    while "%s%016x" % (PREFIX, n) in taken:
        n += 1
    uid = "%s%016x" % (PREFIX, n)
    store(user, profiles + [(uid, name)])
    return uid


def rename(user, uid, name):
    name = clean_name(name)
    if not name:
        raise ValueError("Give the profile a name.")
    profiles = load(user)
    if any(n.casefold() == name.casefold() and u != uid for u, n in profiles):
        raise ValueError('There is a profile called "%s" already.' % name)
    store(user, [(u, name if u == uid else n) for u, n in profiles])


def save_dir(user, uid):
    """the profile's saves: save/<id>, as host/nn_fs.c names it"""
    return os.path.join(user, "save", uid)


def folder_to_show(user, uid):
    """The folder "Open save folder" shows: the profile's saves, or the nearest folder above them that is there. None is
    made: an empty save folder would read to the game as a save that exists."""
    for path in (save_dir(user, uid), os.path.join(user, "save"), user):
        if os.path.isdir(path):
            return path
    return None


def _backup(user, uid):
    """moves save/<id> to save-backups/<id>-<time>; returns where, or None when there were no saves"""
    saves = save_dir(user, uid)
    try:
        if not os.listdir(saves):
            os.rmdir(saves)
            return None
    except OSError:
        return None
    root = os.path.join(user, "save-backups")
    os.makedirs(root, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    dest = os.path.join(root, "%s-%s" % (uid, stamp))
    k = 2
    while os.path.exists(dest):
        dest = os.path.join(root, "%s-%s-%d" % (uid, stamp, k))
        k += 1
    os.replace(saves, dest)
    return dest


def remove(user, uid):
    """takes the profile off the list; its saves go to save-backups. Returns where they went, or None."""
    if uid == DEFAULT:
        raise ValueError("The default profile cannot be removed: the game plays it when it is started without the launcher.")
    moved = _backup(user, uid)
    store(user, [p for p in load(user) if p[0] != uid])
    return moved


def export(user, uid, name, parent):
    """Copies the profile's save (account.sav, option.sav and slot_*, what an import takes) into a new folder in parent,
    "Hookshot save - <name> - <time>". Nothing there is replaced. Returns the new folder."""
    saves = save_dir(user, uid)
    files = [f for f in ("account.sav", "option.sav") if os.path.isfile(os.path.join(saves, f))]
    try:
        slots = sorted(n for n in os.listdir(saves) if n.startswith("slot_") and os.path.isdir(os.path.join(saves, n)))
    except OSError:
        slots = []
    if not slots:
        raise ValueError("%s has no saves yet: nothing to export." % name)
    if not os.path.isdir(parent):
        raise ValueError("There is no folder at %s." % parent)
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .") or uid[-4:]
    base = os.path.join(parent, "Hookshot save - %s - %s" % (safe, time.strftime("%Y-%m-%d %H-%M")))
    dest, k = base, 2
    while os.path.lexists(dest):
        dest, k = "%s (%d)" % (base, k), k + 1
    os.makedirs(dest)
    try:
        for n in slots:
            shutil.copytree(os.path.join(saves, n), os.path.join(dest, n), symlinks=True)
        for f in files:
            shutil.copy2(os.path.join(saves, f), os.path.join(dest, f), follow_symlinks=False)
    except OSError:
        shutil.rmtree(dest, ignore_errors=True)   # (no half a save left behind to be imported later)
        raise
    return dest


def state(folder, selected=None):
    """What a launcher shows: the game's user folder, its profiles and the one the launcher last chose."""
    user = user_dir(folder)
    profiles = load(user)
    ids = {uid for uid, _ in profiles}
    if selected not in ids:
        selected = profiles[0][0]
    return {
        "user": user,
        "supported": supported(folder),
        "profiles": [{"id": uid, "name": name, "default": uid == DEFAULT} for uid, name in profiles],
        "selected": selected,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="The Hookshot launcher's profiles.")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("list", "add", "rename", "remove", "export"):
        p = sub.add_parser(name)
        p.add_argument("folder")
        if name in ("rename", "remove", "export"):
            p.add_argument("id")
        if name in ("add", "rename"):
            p.add_argument("name")
        if name == "export":
            p.add_argument("parent")
    a = ap.parse_args(argv)
    try:
        user = user_dir(a.folder)
        if a.command == "list":
            result = state(a.folder)
        elif a.command == "add":
            uid = add(user, a.name)
            result = state(a.folder, uid)
        elif a.command == "rename":
            rename(user, a.id, a.name)
            result = state(a.folder, a.id)
        elif a.command == "remove":
            result = {"moved": remove(user, a.id)}
            result.update(state(a.folder))
        else:
            profiles = dict(load(user))
            dest = export(user, a.id, profiles.get(a.id, a.id), a.parent)
            result = {"path": dest}
    except (OSError, ValueError) as e:
        print(json.dumps({"error": str(e)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
