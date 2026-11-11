"""The files the game writes by itself are not written through a symbolic link at their name (Linux).

A game folder unpacked from an archive someone shared can hold links (tar and unzip keep them on Linux). The game rewrites
hookshot_options.ini when an option changes, and writes its pipeline caches, state lists, markers, button-prompt textures,
mouse_sens.txt, language.txt and the moved-saves note by itself: through such a link a plain fopen("w") emptied and rewrote
the file it named. host/hos_fopen_write.h opens those with O_NOFOLLOW and only as regular files.

Checked here, without a game:
- hos_fopen_write refuses a link (to a file, or dangling: nothing is made where it points) and a FIFO (without waiting),
  writes and empties a regular file for "w"/"wb" and appends for "a"/"ab";
- on Windows (its branch, with a stand-in windows.h) it refuses a symbolic link or junction at the name, and writes
  OneDrive's files and plain ones;
- in the files that write those, every fopen for writing goes through it, except the debugging writes that a switch
  turns on (ALLOWED: their counts).

python -I -B tests/test_game_writes_no_links.py [--cc gcc]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_SKIP = {"windows": "the links checked are Linux's (an archive's links are not made on Windows)"}

# (the small text files the game reads at the start, each through hos_fopen_read: file -> how many)
BINARY_READS = {"gpu/vk/vk_draw.cpp": 15, "host/prompts.c": 2, "gpu/vk/vk_main.cpp": 1, "gpu/vk/vk_game_font.h": 1,
                "host/hos_main.c": 1}   # (the caches, lists and markers; the prompt files)
READS = {"host/hos_main.c": 2, "host/nn_applet.c": 2, "host/nn_hid.c": 2, "host/discord_rpc.c": 1, "host/prompts.c": 2,
         "host/nn_audio.c": 1, "gpu/vk/vk_menu.cpp": 2, "gpu/vk/vk_draw.cpp": 1, "gpu/vk/vk_main.cpp": 2}

# (the sources of the writes listed above, and how many plain fopen writes each keeps: switch-gated debugging only.
# vk_draw.cpp: RX_VK_PROBE's two files and RX_VK_DRAW_STATS' file)
ALLOWED = {"gpu/vk/vk_menu.cpp": 0, "gpu/vk/vk_draw.cpp": 3, "host/nn_applet.c": 0, "host/prompts.c": 0,
           "host/nn_hid.c": 0, "host/hos_main.c": 0}
# (fopen(<path>, "w"), or with the mode chosen by a ?: : the path's own text holds no string)
PLAIN_WRITE = re.compile(r'(?<![\w.])(?:std::)?fopen\s*\([^;"]*,[^;",]*"[wa]b?\+?"')

FIXTURE = r'''
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include "hos_fopen_write.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
static int text_is(const char *path, const char *want) {
    char got[64] = {0};
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    size_t n = fread(got, 1, sizeof got - 1, f);
    fclose(f);
    return n == strlen(want) && !memcmp(got, want, n);
}
int main(int argc, char **argv) {
    const char *dir = argv[1];   /* (a folder: hos_fopen_read refuses it) */
    char target[512], link[512], dangling[512], nowhere[512], plain[512], fifo[512];
    snprintf(target, sizeof target, "%s/target", dir);
    snprintf(link, sizeof link, "%s/hookshot_options.ini", dir);
    snprintf(dangling, sizeof dangling, "%s/language.txt", dir);
    snprintf(nowhere, sizeof nowhere, "%s/made_by_the_link", dir);
    snprintf(plain, sizeof plain, "%s/mouse_sens.txt", dir);
    snprintf(fifo, sizeof fifo, "%s/fifo", dir);
    const char *modes[] = {"w", "wb", "a", "ab"};
    for (int i = 0; i < 4; i++) {
        CHECK(hos_fopen_write(link, modes[i]) == NULL);
        CHECK(text_is(target, "the player's file"));
        CHECK(hos_fopen_write(dangling, modes[i]) == NULL);
        struct stat st;
        CHECK(lstat(nowhere, &st) != 0);
        CHECK(hos_fopen_write(fifo, modes[i]) == NULL);   /* (returns: a FIFO is not waited on) */
    }
    FILE *f = hos_fopen_write(plain, "w");
    CHECK(f && fputs("first", f) >= 0 && fclose(f) == 0 && text_is(plain, "first"));
    f = hos_fopen_write(plain, "ab");
    CHECK(f && fputs("+more", f) >= 0 && fclose(f) == 0 && text_is(plain, "first+more"));
    f = hos_fopen_write(plain, "wb");
    CHECK(f && fputs("new", f) >= 0 && fclose(f) == 0 && text_is(plain, "new"));
    CHECK(hos_fopen_write(plain, "r") == NULL);
    puts("PASS: hos_fopen_write refuses links and FIFOs, writes, empties and appends to regular files");
    /* (hos_fopen_read: a regular file, also through a link, but never a FIFO, which it does not wait on) */
    f = hos_fopen_read(plain);
    char got[64] = {0};
    CHECK(f && fgets(got, sizeof got, f) && !strcmp(got, "new") && fclose(f) == 0);
    f = hos_fopen_read(link);
    CHECK(f && fgets(got, sizeof got, f) && !strcmp(got, "the player's file") && fclose(f) == 0);
    CHECK(hos_fopen_read(fifo) == NULL && hos_fopen_read(dir) == NULL && hos_fopen_read_binary(fifo) == NULL);
    puts("PASS: hos_fopen_read reads regular files and refuses FIFOs and folders without waiting");
    return 0;
}
'''


# (the Windows branch, built here with a stand-in windows.h: a symbolic link or junction at the name is not written, a
# OneDrive file (another reparse point) and a plain file are)
WINDOWS_H = r'''#pragma once
typedef unsigned long DWORD;
typedef void *HANDLE;
#define INVALID_FILE_ATTRIBUTES ((DWORD)-1)
#define INVALID_HANDLE_VALUE ((HANDLE)(long)-1)
#define FILE_ATTRIBUTE_REPARSE_POINT 0x400
typedef struct { DWORD dwFileAttributes, dwReserved0; } WIN32_FIND_DATAA;
extern DWORD fake_attributes, fake_tag;
static DWORD GetFileAttributesA(const char *p) { (void)p; return fake_attributes; }
static HANDLE FindFirstFileA(const char *p, WIN32_FIND_DATAA *fd) { (void)p; fd->dwReserved0 = fake_tag; return (HANDLE)1; }
static int FindClose(HANDLE h) { (void)h; return 1; }
'''
WINDOWS_FIXTURE = r'''#include <stdio.h>
#include "hos_fopen_write.h"
DWORD fake_attributes, fake_tag;
static int writes(DWORD attributes, DWORD tag, const char *path) {
    fake_attributes = attributes, fake_tag = tag;
    FILE *f = hos_fopen_write(path, "w");
    if (f) fclose(f);
    return f != NULL;
}
int main(int argc, char **argv) {
    (void)argc;
    const int ok = writes(INVALID_FILE_ATTRIBUTES, 0, argv[1]) && writes(0x20, 0, argv[1]) &&
                   writes(0x420, 0x9000001AUL, argv[1]) &&   /* (OneDrive: IO_REPARSE_TAG_CLOUD_6) */
                   !writes(0x420, 0xA000000CUL, argv[1]) && !writes(0x420, 0xA0000003UL, argv[1]) &&
                   !writes(0x420, 0xA000001DUL, argv[1]) && !hos_fopen_write(argv[1], "r");
    puts(ok ? "PASS: on Windows, hos_fopen_write refuses symbolic links and junctions, writes OneDrive's and plain files"
            : "FAIL: the Windows branch");
    return !ok;
}
'''


def check_windows(cc, tmp):
    fake = tmp / "fake"
    fake.mkdir()
    (fake / "windows.h").write_text(WINDOWS_H, encoding="utf-8")
    (tmp / "win.c").write_text(WINDOWS_FIXTURE, encoding="utf-8")
    exe = tmp / "win"
    subprocess.run([cc, "-std=c11", "-D_WIN32", "-Wall", "-Werror", "-Wno-unused-function", "-I", str(fake), "-I",
                    str(ROOT / "host"), str(tmp / "win.c"), "-o", str(exe)], check=True)
    subprocess.run([str(exe), str(tmp / "plain_win.txt")], check=True, timeout=30)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    bad = []
    for rel, keep in ALLOWED.items():
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        plain = PLAIN_WRITE.findall(text)
        if len(plain) != keep:
            bad.append("%s: %d plain fopen writes, %d expected (switch-gated debugging only): %s" % (
                rel, len(plain), keep, "; ".join(plain)))
        if "hos_fopen_write(" not in text:
            bad.append("%s: does not use hos_fopen_write" % rel)
    for rel, want in READS.items():
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        got = text.count("hos_fopen_read(")
        if got != want:
            bad.append("%s: %d reads through hos_fopen_read, %d expected" % (rel, got, want))
        for name in ("hookshot_options.ini", "hookshot_env.txt", "language.txt", "mouse_sens.txt"):
            for m in re.finditer(r'"%s"\);\s*\n\s*(?:#endif\s*\n\s*)?(?:FILE \*)?\w+ = fopen\(path, "r"\)' % re.escape(name), text):
                bad.append("%s: %s still read with fopen" % (rel, name))
    for rel, want in BINARY_READS.items():
        got = (ROOT / rel).read_text(encoding="utf-8", errors="replace").count("hos_fopen_read_binary(")
        if got != want:
            bad.append("%s: %d reads through hos_fopen_read_binary, %d expected" % (rel, got, want))
    if bad:
        sys.exit("\n".join(bad))
    print("PASS: the game's own writes in %d files go through hos_fopen_write, its start-up reads through hos_fopen_read"
          % len(ALLOWED))
    # (the back end's objects are keyed by the headers they see: the host's it includes must be among them, or a change
    # to hos_fopen_write.h left vk_draw.cpp's object with the old code)
    included = set()
    for f in (ROOT / "gpu" / "vk").glob("*.[ch]*"):
        included.update(re.findall(r'#include "\.\./\.\./host/([\w.]+)"', f.read_text(encoding="utf-8", errors="replace")))
    for h in list(included):   # (and the host headers those include)
        if (ROOT / "host" / h).exists():
            included.update(re.findall(r'#include "([\w.]+)"', (ROOT / "host" / h).read_text(encoding="utf-8")))
    build = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
    keyed = re.search(r'vdeps \+= b"".join\(open\(os\.path\.join\(HOST, h\), "rb"\)\.read\(\) for h in \(([^)]*)\)\)', build)
    keyed = set(re.findall(r'"([\w.]+)"', keyed.group(1))) if keyed else set()
    if not included or not included <= keyed:
        sys.exit("nx2/build.py: the back end's object keys leave out the host headers it includes: %s"
                 % ", ".join(sorted(included - keyed)))
    print("PASS: the back end's object keys hold the %d host headers it includes" % len(included))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "fopen_write.c"
        src.write_text(FIXTURE, encoding="utf-8")
        exe = tmp / "fopen_write"
        subprocess.run([a.cc, "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Werror", "-I", str(ROOT / "host"),
                        str(src), "-o", str(exe)], check=True)
        files = tmp / "game"
        files.mkdir()
        (files / "target").write_text("the player's file", encoding="utf-8")
        os.symlink(files / "target", files / "hookshot_options.ini")
        os.symlink(files / "made_by_the_link", files / "language.txt")
        os.mkfifo(files / "fifo")
        r = subprocess.run([str(exe), str(files)], capture_output=True, text=True, timeout=30)
        print(r.stdout, end="")
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
        # (a refusal is said in the log, once, naming the file)
        said = [l for l in r.stderr.splitlines() if "the game does not write through it" in l]
        if len(said) != 1 or "hookshot_options.ini" not in said[0]:
            sys.exit("hos_fopen_write: a refusal is not said once in the log: %r" % r.stderr)
        print("PASS: a refused write is said once in the log, with the file's name")
        check_windows(a.cc, tmp)


if __name__ == "__main__":
    main()
