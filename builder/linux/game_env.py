"""hookshot_env.txt beside the game (host/hos_main.c, load_hookshot_env): NAME=VALUE lines the game sets at every start,
however it is started. The launcher's "Lower memory use" switch (Settings) is one such line, RX_VK_PCACHE_LOAD=0 (#2206):
the game neither loads nor saves its pipeline cache file, mkw_vk_pipelines.bin, which can reach 2.5 GB and is held by the
driver for the whole session. builder/HookshotBuilder/GameEnv.cs, the same rules. The rest of the file is the player's and
stays as it is, and the cache file is never deleted: switched off again, the game takes it up where it was
(tests/test_linux_launcher_lists.py)."""
import os

FILE_NAME = "hookshot_env.txt"
CACHE_FILE = "mkw_vk_pipelines.bin"
NAME = "RX_VK_PCACHE_LOAD"


def _value(line):
    """the value of a line that sets NAME, as the game reads it (Notepad's BOM and spaces around it; # notes and lines with
    no = left out; the name exact), or None"""
    s = line.lstrip("﻿").strip(" \t\r")
    if not s or s.startswith("#") or "=" not in s:
        return None
    name, _eq, value = s.partition("=")
    return value if name == NAME else None


def _zero(value):
    """as the game's atoi takes a value: its leading digits, after an optional sign; none is 0"""
    v = value.lstrip(" \t")
    if v[:1] in ("-", "+"):
        v = v[1:]
    digits = ""
    for ch in v:
        if not ("0" <= ch <= "9"):
            break
        digits += ch
    return not digits or set(digits) == {"0"}


def skips_cache(text):
    """the cache file is skipped by this file's text: the last line that sets the switch is the one the game keeps"""
    last = None
    for line in text.split("\n"):
        v = _value(line)
        if v is not None:
            last = v
    return last is not None and _zero(last)


def with_skip(text, skip):
    """the file's text with the switch on (its line, once, at the end) or off (every line that sets it gone); every other
    line, and the file's line ends, as they were"""
    nl = "\r\n" if "\r\n" in text else "\n"
    kept = [line.rstrip("\r") for line in text.split("\n") if _value(line) is None]
    while kept and not kept[-1].strip():
        kept.pop()
    if skip:
        kept.append(NAME + "=0")
    return nl.join(kept) + nl if kept else ""


def folder_skips_cache(folder):
    """the game folder's file says the cache is skipped (no file, or one that cannot be read: it is not)"""
    try:
        with open(os.path.join(folder, FILE_NAME), encoding="utf-8", errors="replace", newline="") as f:
            return skips_cache(f.read())
    except OSError:
        return False


def set_skip(folder, skip):
    """the switch written to the game folder's file: replaced whole (a .new beside it, then moved over), deleted when nothing
    is left in it. Raises OSError (a folder that cannot be written)"""
    path = os.path.join(folder, FILE_NAME)
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    now = with_skip(text, skip)
    if now == text:
        return
    if not now:
        os.remove(path)
        return
    with open(path + ".new", "w", encoding="utf-8", newline="") as f:
        f.write(now)
    os.replace(path + ".new", path)


def cache_bytes(folder):
    """the cache file's size in bytes (-1: there is none yet: the game makes it as it plays)"""
    try:
        return os.path.getsize(os.path.join(folder, CACHE_FILE))
    except OSError:
        return -1


def size_text(size):
    """as the Windows launcher writes a size (Storage.Gb): 2.4 GB, 437 MB"""
    return "%.1f GB" % (size / float(1 << 30)) if size >= 1 << 30 else "%d MB" % (size >> 20)
