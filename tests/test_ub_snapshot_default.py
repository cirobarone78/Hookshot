"""The uniform-buffer snapshot default, game-free: the actual selection code from gpu/vk/vk_draw.cpp, compiled.

Without buffer mirrors (integrated GPUs such as the Steam Deck) a uniform buffer bound in place is the game's own memory,
which it rewrites right after the submit; the copy as submitted is the default there. With mirrors it stays in place.
RX_VK_UB_SNAPSHOT=1 / present-but-empty forces the copy, RX_VK_UB_SNAPSHOT=0 forces the pool.

    python -I -B tests/test_ub_snapshot_default.py [--cxx g++]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
RUN_ALL_SKIP = {"windows": "the fixture sets the switch with POSIX setenv: checked on Linux"}

ROOT = Path(__file__).resolve().parents[1]
MARKER = "static const bool snapshot = [] {"


def selection(source):
    start = source.index(MARKER) + len("static const bool snapshot = ")
    end = source.index("}();", start) + 3
    return source[start:end]


FIXTURE = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
static bool mirrors;
static char logged[256];
[[maybe_unused]] static bool memory_mirrors_on() { return mirrors; }
static void logf(const char* f, ...) { std::snprintf(logged, sizeof logged, "%s", f); }
static bool pick() { return SELECTION; }
int main(int argc, char** argv) {
    if (argc != 3) return 2;
    mirrors = argv[1][0] == '1';
    if (std::strcmp(argv[2], "unset")) setenv("RX_VK_UB_SNAPSHOT", argv[2], 1); else unsetenv("RX_VK_UB_SNAPSHOT");
    const bool on = pick();
    if (!std::strstr(logged, "uniform buffers")) return 3;
    std::puts(on ? "copy" : "pool");
    return 0;
}
'''

CASES = [("0", "unset", "copy"), ("1", "unset", "pool"), ("1", "1", "copy"), ("1", "", "copy"),
         ("0", "0", "pool"), ("1", "0", "pool")]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    p.add_argument("--source", type=Path, default=ROOT / "gpu/vk/vk_draw.cpp")
    a = p.parse_args()
    code = FIXTURE.replace("SELECTION", selection(a.source.read_text(encoding="utf-8")))
    with tempfile.TemporaryDirectory(prefix="ub-snapshot-") as tmp:
        cpp, exe = Path(tmp) / "t.cpp", Path(tmp) / "t"
        cpp.write_text(code, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Werror", "-Wno-format-security", str(cpp), "-o", str(exe)],
                       check=True)
        for mirrors, value, want in CASES:
            got = subprocess.run([str(exe), mirrors, value], capture_output=True, text=True, check=True).stdout.strip()
            if got != want:
                raise SystemExit("mirrors=%s RX_VK_UB_SNAPSHOT=%r: %s, expected %s" % (mirrors, value, got, want))
    print("PASS: uniform buffers copied without mirrors by default; the switch forces either way")


if __name__ == "__main__":
    main()
