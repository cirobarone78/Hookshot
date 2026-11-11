"""The button prompts' files are read into memory only when they are what the builder makes (host/prompts.c read_all).

prompts/<face>/textures.bin, ring.bin, hint.bin and External.bfotf are a few MB, made by the builder in the game folder.
A game folder from elsewhere can hold any file under those names: a large or sparse one was read whole into memory at the
start. Cuts read_all out of the source as it is, with malloc counted, and checks:

- a file with the right magic comes back whole; one with another magic, or too short, does not, and nothing is allocated
  for it;
- a sparse 3 GB file with the right magic is not allocated (no request past PROMPT_FILE_MAX).

python -I -B tests/test_prompt_file_read.py [--cc gcc]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_SKIP = {"windows": "a sparse 3 GB file and ftell past 2 GB (long is 32 bits there)"}


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
    if os.name == "nt":
        print("SKIP: Linux")
        return
    src = (ROOT / "host/prompts.c").read_text(encoding="utf-8")
    limit = "\n".join(l for l in src.splitlines() if l.startswith("#define PROMPT_FILE_MAX"))
    fixture = r'''#include <stdint.h>
#include <stdio.h>
#include "HOS_FOPEN_HEADER"
#include <stdlib.h>
#include <string.h>
static size_t largest;
static void *counted(size_t n) { if (n > largest) largest = n; return n <= (64u << 20) ? malloc(n) : NULL; }
#define malloc(n) counted(n)
''' + limit + "\n" + block(src, "static uint8_t *read_all(const char *path, const char *magic, long *n) {") + r'''
#undef malloc
#ifndef PROMPT_FILE_MAX
#define PROMPT_FILE_MAX (256L << 20)   /* (a source without the limit: what it should be) */
#endif
int main(int argc, char **argv) {
    (void)argc;
    long n = 0;
    uint8_t *t = read_all(argv[1], "HPTX", &n);
    int ok = t && n == 4096 && !memcmp(t, "HPTX", 4);
    free(t);
    largest = 0;
    t = read_all(argv[2], "HPTX", &n);   /* (another magic) */
    ok &= !t && largest == 0;
    t = read_all(argv[3], "HPTX", &n);   /* (a sparse 3 GB file, the right magic) */
    ok &= !t && largest <= (size_t)PROMPT_FILE_MAX;
    t = read_all(argv[4], NULL, &n);     /* (too short to be one) */
    ok &= !t;
    printf("%s largest request %zu\n", ok ? "PASS" : "FAIL", largest);
    return ok ? 0 : 1;
}
'''
    with tempfile.TemporaryDirectory(prefix="prompt-read-") as tmp:
        tmp = Path(tmp)
        (tmp / "fixture.c").write_text(fixture.replace("HOS_FOPEN_HEADER", (ROOT / "host" / "hos_fopen_read.h").as_posix()), encoding="utf-8")
        exe = tmp / "fixture"
        subprocess.run([a.cc, "-std=c11", "-D_FILE_OFFSET_BITS=64", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Werror", "-Wno-unused-function",
                        str(tmp / "fixture.c"), "-o", str(exe)], check=True)
        (tmp / "good.bin").write_bytes(b"HPTX" + bytes(4092))
        (tmp / "other.bin").write_bytes(b"XXXX" + bytes(4092))
        with open(tmp / "sparse.bin", "wb") as f:
            f.write(b"HPTX")
            f.truncate(3 << 30)
        (tmp / "short.bin").write_bytes(b"HPTX")
        r = subprocess.run([str(exe), *(str(tmp / n) for n in ("good.bin", "other.bin", "sparse.bin", "short.bin"))],
                           capture_output=True, text=True, timeout=60)
        print(r.stdout, end="")
        if r.returncode:
            sys.exit("prompts read_all: %s%s" % (r.stdout, r.stderr))


if __name__ == "__main__":
    main()
