"""The Linux game process's Landlock sandbox (host/posix/sandbox_linux.c): what it lets the game write, and what not.

Builds sandbox_linux.c with a stub log, lays out a game folder, a saves folder and a home folder in a temporary directory,
applies the sandbox in a child process (as the game does at its start) and tries each path:

- the game folder's state files (options, caches, the log, the button prompts) written in place; a new file there (a
  library beside the game, a temporary file), or in its ngx/ folder, refused;
- the saves folder's save/, cache/ and temp/ written, and present.txt; a new file in the saves folder itself, or in its
  builder/ or ngx/ folders (which a later start runs or loads), refused;
- the rest of the home folder refused, the drivers' shader caches allowed.

Skipped where the kernel has no Landlock (the game then runs without its sandbox, said in the log).

python -I -B tests/test_sandbox_linux.py [--cc gcc]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_SKIP = {"windows": "Landlock is Linux's"}

HARNESS = r'''
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static int off;
void hos_log(const char *f, ...) {
    char b[8192];
    va_list a;
    va_start(a, f);
    vsnprintf(b, sizeof b, f, a);
    va_end(a);
    if (strstr(b, "without its sandbox")) off = 1;
    fprintf(stderr, "[log] %s\n", b);
}
void hos_sandbox_apply(const char *game_dir, const char *user_dir);
static int bad;
static void try_open(const char *dir, const char *rel, int flags, int allowed) {
    char p[4096];
    snprintf(p, sizeof p, "%s/%s", dir, rel);
    const int fd = open(p, flags | O_CLOEXEC, 0644);
    const int ok = fd >= 0;
    if (ok) close(fd);
    if (ok != allowed) bad++, fprintf(stderr, "FAIL %s: %s (%s)\n", rel, ok ? "allowed" : strerror(errno), allowed ? "should be allowed" : "should be refused");
}
#define W (O_WRONLY | O_CREAT)
int main(int argc, char **argv) {
    const char *g = argv[1], *u = argv[2], *h = argv[3];
    hos_sandbox_apply(g, u);
    if (off) { printf("SKIP: no Landlock here\n"); return 0; }
    try_open(g, "hookshot_options.ini", O_RDWR | O_TRUNC, 1);
    try_open(g, "hookshot_log.txt", O_WRONLY | O_TRUNC, 1);
    try_open(g, "mkw_vk_pipelines.bin", O_WRONLY | O_TRUNC, 1);
    try_open(g, "hookshot_programs.idx", O_WRONLY | O_TRUNC, 1);
    try_open(g, "hookshot_computes.bin", O_WRONLY | O_APPEND, 1);
    try_open(g, "hookshot_pipeline_states.bin", O_WRONLY | O_APPEND, 1);
    try_open(g, "prompts/Common.key", O_WRONLY | O_TRUNC, 1);
    try_open(g, "image.bin", O_RDONLY, 1);
    try_open(g, "image.bin", O_WRONLY, 0);
    try_open(g, "mkw_vk_pipelines.bin.tmp", W, 0);
    try_open(g, "libplanted.so", W, 0);
    try_open(g, "ngx/nvngx_dlss.so", W, 0);
    try_open(u, "save/0011/progress.sav", W, 1);
    try_open(u, "cache/0/x.bin", W, 1);
    try_open(u, "temp/x", W, 1);
    try_open(u, "present.txt", O_WRONLY | O_TRUNC, 1);
    try_open(u, "planted.txt", W, 0);
    try_open(u, "builder/current", W | O_TRUNC, 0);
    try_open(u, "ngx/nvngx_dlss.so", W, 0);
    try_open(h, ".bashrc", O_RDONLY, 0);
    try_open(h, ".cache/nvidia/x", W, 1);
    if (bad) return 1;
    printf("PASS: state files in place, saves written; nothing new in the game folder, the saves folder's root, builder/ or ngx/\n");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default=None)
    a = p.parse_args()
    if not sys.platform.startswith("linux"):
        print("SKIP: Landlock is Linux's")
        return 0
    cc = a.cc or shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if not cc:
        print("SKIP: no C compiler")
        return 0
    with tempfile.TemporaryDirectory(prefix="sandbox-") as tmp:
        tmp = Path(tmp)
        src = tmp / "harness.c"
        src.write_text(HARNESS, encoding="utf-8")
        exe = tmp / "harness"
        r = subprocess.run([cc, "-O1", str(src), str(ROOT / "host/posix/sandbox_linux.c"), "-o", str(exe)],
                           capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stdout + r.stderr)
            raise SystemExit("test_sandbox_linux: the harness did not build")
        g, u, h = tmp / "game", tmp / "user", tmp / "home"
        for d in (g / "prompts", u / "save" / "0011", u / "cache" / "0", u / "builder", u / "ngx", h / ".cache"):
            d.mkdir(parents=True)
        (g / "image.bin").write_bytes(b"x")
        (h / ".bashrc").write_text("x")
        # (the child's own environment: its temporary folder somewhere that is not, or the sandbox would allow all of tmp)
        env = {"PATH": os.environ.get("PATH", "/usr/bin"), "HOME": str(h), "XDG_CACHE_HOME": str(h / ".cache"),
               "XDG_RUNTIME_DIR": str(tmp / "no-runtime"), "TMPDIR": str(tmp / "no-tmp")}
        r = subprocess.run([str(exe), str(g), str(u), str(h)], capture_output=True, text=True, env=env, timeout=60)
        print(r.stdout, end="")
        if r.returncode:
            sys.stderr.write(r.stderr)
            raise SystemExit("test_sandbox_linux: failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
