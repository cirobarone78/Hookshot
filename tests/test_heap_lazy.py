"""HOS_HEAP_LAZY (host/mkw_glue.c): the heap committed where it is first used, and hos_commit_reserved before host APIs.

hos_commit_reserved runs on a real reserved region (Windows): its reserved pages are committed read-write, a committed page
keeps the protection it had (a watched page's PAGE_READONLY), an unaligned range commits the pages it touches and no more,
and nothing happens with the switch off. The sources: SetMemoryHeapSize commits nothing up front with the switch, the fault
handler commits a heap page without the "nothing handed it out" line, and the file reads and writes commit their range first.
python -I -B tests/test_heap_lazy.py [--cc clang]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
static uint8_t *base;
#define GP(a) ((void *)(base + (a)))
static void *hos_guest_range(uint64_t a, uint64_t n) { return a + n <= (16u << 20) ? GP(a) : NULL; }
static int lazy = 1;
static int hos_heap_lazy(void) { return lazy; }
static int failed;
static void hos_commit(uint64_t a, uint64_t n) { (void)a, (void)n; failed++; }
@FUNC@
static DWORD state(uint64_t a, DWORD *protect) {
    MEMORY_BASIC_INFORMATION mi;
    VirtualQuery(GP(a), &mi, sizeof mi);
    if (protect) *protect = mi.Protect;
    return mi.State;
}
int main(void) {
    base = (uint8_t *)VirtualAlloc(NULL, 16u << 20, MEM_RESERVE, PAGE_NOACCESS);
    CHECK(base);
    CHECK(VirtualAlloc(GP(0x20000), 0x1000, MEM_COMMIT, PAGE_READONLY));   /* (a watched page) */
    lazy = 0;
    hos_commit_reserved(0x10000, 0x40000);
    CHECK(state(0x10000, NULL) == MEM_RESERVE);                             /* (off: nothing) */
    lazy = 1;
    hos_commit_reserved(0x10000, 0x40000);
    DWORD p;
    CHECK(state(0x10000, &p) == MEM_COMMIT && p == PAGE_READWRITE);
    CHECK(state(0x4f000, &p) == MEM_COMMIT && p == PAGE_READWRITE);
    CHECK(state(0x20000, &p) == MEM_COMMIT && p == PAGE_READONLY);          /* (kept as it was) */
    CHECK(state(0x50000, NULL) == MEM_RESERVE);                             /* (past the range) */
    hos_commit_reserved(0x80010, 0x20);                                     /* (unaligned: its one page) */
    CHECK(state(0x80000, NULL) == MEM_COMMIT && state(0x81000, NULL) == MEM_RESERVE && state(0x7f000, NULL) == MEM_RESERVE);
    hos_commit_reserved(0x90ff8, 0x10);                                     /* (across a page boundary: both) */
    CHECK(state(0x90000, NULL) == MEM_COMMIT && state(0x91000, NULL) == MEM_COMMIT && state(0x92000, NULL) == MEM_RESERVE);
    hos_commit_reserved((16u << 20) - 8, 64);                               /* (outside the window: nothing) */
    CHECK(failed == 0);
    printf("PASS: the lazy heap commits reserved pages before host APIs and leaves a page's own protection\n");
    return 0;
}
'''


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
    p.add_argument("--cc", default="clang")
    a = p.parse_args()
    glue = (ROOT / "host" / "mkw_glue.c").read_text(encoding="utf-8")
    mem = (ROOT / "host" / "hos_mem.c").read_text(encoding="utf-8")
    fs = (ROOT / "host" / "nn_fs.c").read_text(encoding="utf-8")
    checks = [
        ("if (size > hos_heap_size && !hos_heap_lazy()) hos_commit(" in mem, "SetMemoryHeapSize commits up front only without the switch"),
        ("const int heap = hos_heap_lazy() && guest >= HOS_HEAP_BASE" in glue, "the fault handler knows a lazy heap page"),
        ("if (!heap && InterlockedIncrement(&touched) <= 16)" in glue, "a heap page is not logged as handed out by nothing"),
        (fs.count("hos_commit_reserved(") == 2, "the file read and write commit their range first"),
    ]
    for ok, what in checks:
        if not ok:
            raise SystemExit("FAIL: " + what)
    if os.name != "nt":
        print("PASS (sources only: the commit test needs Windows)")
        return
    func = block(glue, "void hos_commit_reserved(uint64_t addr, uint64_t size) {").replace("InterlockedAdd64(&lazy_bytes, next - q)", "(void)0")
    with tempfile.TemporaryDirectory(prefix="heap-lazy-") as tmp:
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / "fixture.exe"
        c.write_text(FIXTURE.replace("@FUNC@", func), encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Werror", str(c), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
