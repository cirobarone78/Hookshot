"""The event-wait ordering default, game-free: the actual selection code from gpu/vk/vk_replay.cpp, compiled.

Without buffer mirrors (integrated GPUs such as the Steam Deck) submissions replay in submit order by default; with mirrors
they are ordered by their events. RX_VK_EVENT_WAITS=1 / 0 forces either.

    python -I -B tests/test_event_waits_default.py [--cxx g++]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
RUN_ALL_SKIP = {"windows": "the fixture sets the switch with POSIX setenv: checked on Linux"}

ROOT = Path(__file__).resolve().parents[1]
MARKER = "bool event_waits_on() {"


def selection(source):
    body = source[source.index(MARKER):]
    start = body.index("static const bool v = ") + len("static const bool v = ")
    end = body.index("}();", start) + 3
    return body[start:end]


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
    if (std::strcmp(argv[2], "unset")) setenv("RX_VK_EVENT_WAITS", argv[2], 1); else unsetenv("RX_VK_EVENT_WAITS");
    const bool on = pick();
    if (!std::strstr(logged, "RX_VK_EVENT_WAITS")) return 3;
    std::puts(on ? "events" : "order");
    return 0;
}
'''

CASES = [("0", "unset", "order"), ("1", "unset", "events"), ("0", "1", "events"), ("1", "0", "order")]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    p.add_argument("--source", type=Path, default=ROOT / "gpu/vk/vk_replay.cpp")
    a = p.parse_args()
    code = FIXTURE.replace("SELECTION", selection(a.source.read_text(encoding="utf-8")))
    with tempfile.TemporaryDirectory(prefix="event-waits-") as tmp:
        cpp, exe = Path(tmp) / "t.cpp", Path(tmp) / "t"
        cpp.write_text(code, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Werror", "-Wno-format-security", str(cpp), "-o", str(exe)],
                       check=True)
        for mirrors, value, want in CASES:
            got = subprocess.run([str(exe), mirrors, value], capture_output=True, text=True, check=True).stdout.strip()
            if got != want:
                raise SystemExit("mirrors=%s RX_VK_EVENT_WAITS=%r: %s, expected %s" % (mirrors, value, got, want))
    print("PASS: submit order by default without mirrors; event order with them; the switch forces either way")


if __name__ == "__main__":
    main()
