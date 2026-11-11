"""Linux: moving a game folder's old user/ folder to the saves folder leaves links where they are.

On Linux the saves live in $XDG_DATA_HOME/hookshot, and a user/ folder beside the game from before is moved there entry by
entry at the start (host/hos_main.c saves_dir). A game folder from elsewhere can hold links there (an archive keeps them).
Builds saves_dir and its copy over host/posix/win32_posix.c's file functions, from the sources as they are, and checks:

- an entry of user/ that is a link (to a folder or a file) is moved as the link it is, never copied through, and what
  it points to is untouched; the other entries are moved as before;
- a link by a relative path is not moved (it would name something else there), and the saves stay;
- a folder that has to be copied (another file system) and holds a link is not copied: it stays, and delete_tree takes
  a link away without going through it.

python -I -B tests/test_saves_move_links.py [--cc gcc]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_SKIP = {"windows": "saves_dir is Linux's (the posix layer's file functions)"}


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    if os.name == "nt" or sys.platform == "darwin":
        print("SKIP: the posix layer's checks run on Linux")
        return
    posix = (ROOT / "host/posix/win32_posix.c").read_text(encoding="utf-8")
    main_c = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    pieces = [
        block(posix, "static DWORD error_of(int e) {"),
        "static BOOL fail_errno(void) { last_error = error_of(errno); return FALSE; }",
        "enum { H_THREAD = 0x48540001, H_EVENT, H_SEMA, H_TIMER, H_FILE, H_FIND };",
        "typedef struct { int type; } HObj;",
        "static int is(HANDLE h, int type) { return h && h != INVALID_HANDLE_VALUE && (uintptr_t)h > 0x10000 && ((HObj *)h)->type == type; }",
        block(posix, "static void slashes(char *dst, size_t cap, const char *src) {"),
        block(posix, "DWORD GetFileAttributesA(LPCSTR name) {"),
        block(posix, "BOOL CreateDirectoryA(LPCSTR name, void *attr) {"),
        block(posix, "BOOL RemoveDirectoryA(LPCSTR name) {"),
        block(posix, "BOOL DeleteFileA(LPCSTR name) {"),
        block(posix, "BOOL MoveFileExA(LPCSTR from, LPCSTR to, DWORD flags) {"),
        "typedef struct { HObj h; DIR *d; char dir[PATH_MAX], pat[256]; } HFind;",
        block(posix, "static BOOL find_next(HFind *f, WIN32_FIND_DATAA *fd) {"),
        block(posix, "HANDLE FindFirstFileA(LPCSTR pattern, WIN32_FIND_DATAA *fd) {"),
        block(posix, "BOOL FindNextFileA(HANDLE h, WIN32_FIND_DATAA *fd) {"),
        block(posix, "BOOL FindClose(HANDLE h) {"),
        block(main_c, "static int is_dir(const char *p) {"),
        block(main_c, "static int copy_tree(const char *from, const char *to) {"),
        block(main_c, "static void delete_tree(const char *p) {"),
        block(main_c, "static const char *saves_dir(const char *beside) {"),
    ]
    fixture = r'''#define _GNU_SOURCE
#include <windows.h>
#include <dirent.h>
#include <errno.h>
#include <fnmatch.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "hos_fopen_write.h"
static DWORD last_error;
#define SEP '/'
#define SEP_S "/"
static void hos_log(const char *f, ...) { (void)f; }
''' + "\n".join(pieces) + r'''
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
static int there(const char *dir, const char *name) {
    char p[PATH_MAX];
    struct stat st;
    snprintf(p, sizeof p, "%s/%s", dir, name);
    return lstat(p, &st) == 0;
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    const char *w = argv[1];
    char beside[PATH_MAX], data[PATH_MAX], saves[PATH_MAX], cmd[6 * PATH_MAX];
    snprintf(beside, sizeof beside, "%s/game/user", w);
    snprintf(data, sizeof data, "%s/data", w);
    snprintf(saves, sizeof saves, "%s/data/hookshot", w);
    /* user/: a slot (moved), a link to a folder elsewhere and one to a file elsewhere (left) */
    snprintf(cmd, sizeof cmd, "mkdir -p '%s/save/slot_00' '%s/elsewhere' '%s' && echo s > '%s/save/slot_00/a.sav' && "
             "echo private > '%s/elsewhere/key' && ln -s '%s/elsewhere' '%s/config' && ln -s '%s/elsewhere/key' '%s/mouse_sens.txt'",
             beside, w, data, beside, w, w, beside, w, beside);
    CHECK(system(cmd) == 0);
    setenv("XDG_DATA_HOME", data, 1);
    const char *dir = saves_dir(beside);
    CHECK(!strcmp(dir, saves));
    CHECK(there(saves, "save/slot_00/a.sav"));
    /* (the links moved as links: a player's save folder kept elsewhere still works, and nothing was copied through them) */
    struct stat st;
    char p[PATH_MAX];
    snprintf(p, sizeof p, "%s/config", saves);
    CHECK(lstat(p, &st) == 0 && S_ISLNK(st.st_mode));
    snprintf(p, sizeof p, "%s/mouse_sens.txt", saves);
    CHECK(lstat(p, &st) == 0 && S_ISLNK(st.st_mode));
    CHECK(!there(beside, "config") && !there(beside, "mouse_sens.txt"));
    char key[PATH_MAX];
    snprintf(key, sizeof key, "%s/elsewhere", w);
    CHECK(there(key, "key"));
    /* a copy (as across file systems) stops at a link inside a folder: the copy fails and the entry stays */
    char from[PATH_MAX], to[PATH_MAX];
    snprintf(from, sizeof from, "%s/copyme", w);
    snprintf(to, sizeof to, "%s/copied", w);
    snprintf(cmd, sizeof cmd, "mkdir -p '%s/in' && echo f > '%s/in/f.sav' && ln -s '%s/elsewhere' '%s/in/away'",
             from, from, w, from);
    CHECK(system(cmd) == 0);
    CHECK(!copy_tree(from, to));
    /* (and a FIFO in a copied folder fails the copy at once, not waited on) */
    char fifo_from[PATH_MAX], fifo_to[PATH_MAX];
    snprintf(fifo_from, sizeof fifo_from, "%s/fifo", w);
    snprintf(fifo_to, sizeof fifo_to, "%s/fifo-copied", w);
    snprintf(cmd, sizeof cmd, "mkdir -p '%s' && mkfifo '%s/pipe'", fifo_from, fifo_from);
    CHECK(system(cmd) == 0);
    CHECK(!copy_tree(fifo_from, fifo_to));
    /* delete_tree takes a link away, never what it names */
    delete_tree(from);
    CHECK(!there(w, "copyme") && there(key, "key"));
    /* a relative link would name something else from the saves folder: it is not moved, and the saves stay */
    char rel[PATH_MAX];
    snprintf(rel, sizeof rel, "%s/game2/user", w);
    snprintf(cmd, sizeof cmd, "mkdir -p '%s' && ln -s ../../elsewhere '%s/other'", rel, rel);
    CHECK(system(cmd) == 0);
    CHECK(!strcmp(saves_dir(rel), rel) && there(rel, "other") && there(key, "key"));
    printf("PASS: saves_dir moves user/'s links by a full path as links, keeps relative ones; a copy or delete never goes through a link\n");
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="saves-links-") as tmp:
        tmp = Path(tmp)
        src = tmp / "fixture.c"
        src.write_text(fixture, encoding="utf-8")
        exe = tmp / "fixture"
        subprocess.run([a.cc, "-std=gnu11", "-I", str(ROOT / "host/posix"), "-I", str(ROOT / "host"),
                        "-Wno-unused-function", str(src), "-o", str(exe)], check=True)
        work = tmp / "work"
        work.mkdir()
        r = subprocess.run([str(exe), str(work)], capture_output=True, text=True, timeout=60)
        print(r.stdout, end="")
        if r.returncode:
            print(r.stderr, end="")
            raise SystemExit("test_saves_move_links: failed (exit %d)" % r.returncode)


if __name__ == "__main__":
    main()
