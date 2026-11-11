"""Run the real NR fallback/off policy with a fake clock; no SDK, GPU or game."""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    source = (ROOT / "gpu/vk/vk_dlss.cpp").read_text(encoding="utf-8")
    start = source.index("bool neural_render(")
    end = source.index("    const int64_t ms_now", start)
    policy = source[start:end].replace("std::chrono::steady_clock::now()", "fake_now()") + "    return true;\n}\n"
    fixture = r"""
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdio>
#include "gpu/vk/dlss_nr_support.h"
using namespace mkwvk;
using Clock = std::chrono::steady_clock;
Clock::time_point now{std::chrono::seconds(100)};
auto fake_now() { return now; }
using VkCommandBuffer = int;
enum { NR_WAITING, NR_ACTIVE };
int g_nr_status = NR_ACTIVE;
std::atomic<int> g_nr_compare{-1};
struct State {
    struct { bool requested = true, native_hdr = false; } nr_controls;
    bool nr_requested = true, nr_running = true, nr_failed = false, nr_rejected = false;
    int nr_feature = 1;
    unsigned long long nr_frames = 60;
    Clock::time_point nr_off_since{}, nr_last_check{};
} state;
State& st() { return state; }
bool comparing = false;
bool menu_comparing() { return comparing; }
void logf(const char*, ...) {}
int drops = 0, checks = 0;
dlss_nr::Issue issue = dlss_nr::Issue::none, supported = dlss_nr::Issue::none;
auto dlss_nr_issue() { return issue; }
void nr_issue_set(dlss_nr::Issue value) { issue = value; }
auto nr_check_locked(bool) { ++checks; return supported; }
void drop_nr() { ++drops; state.nr_feature = 0; state.nr_running = false; }
""" + policy + r"""
bool step(int millis = 17) {
    now += std::chrono::milliseconds(millis);
    bool reset = false;
    neural_render(0, 1280, 720, reset);
    return reset;
}
void fresh() {
    state = {}; drops = checks = 0;
    supported = issue = dlss_nr::Issue::none;
    comparing = false; g_nr_compare = -1;
}
int main() {
    fresh(); state.nr_controls.native_hdr = true;
    assert(step());
    for (int frame = 0; frame < 600; ++frame) assert(!step());
    fresh(); supported = dlss_nr::Issue::missing_runtime;
    assert(step()); assert(drops == 1);
    for (int frame = 0; frame < 600; ++frame) assert(!step());
    assert(checks > 5 && drops == 1); // Rechecking availability never destroys SR's history.
    fresh(); state.nr_running = false; state.nr_feature = 0;
    supported = dlss_nr::Issue::missing_runtime;
    for (int frame = 0; frame < 600; ++frame) assert(!step());
    assert(drops <= 1);
    fresh(); issue = dlss_nr::Issue::missing_runtime; state.nr_last_check = now;
    assert(step()); assert(drops == 1); // UI notices a missing DLL between renderer probes.
    fresh(); state.nr_controls.requested = false;
    assert(step()); assert(drops == 0);
    assert(!step(1900) && drops == 0);
    assert(!step(101) && drops == 1);
    fresh(); comparing = true; g_nr_compare = 0;
    assert(step());
    assert(!step(10000) && drops == 0);
    comparing = false; state.nr_controls.requested = false; g_nr_compare = -1;
    assert(!step(1999) && drops == 0);
    assert(!step(2) && drops == 1);
    fresh(); state.nr_controls.requested = false; step(); step(1900);
    state.nr_controls.requested = true; step(); // A new On resets the ordinary-Off grace timer.
    state.nr_controls.requested = false; step();
    assert(!step(1900) && drops == 0);
    assert(!step(101) && drops == 1);
    std::puts("NR fallback transitions, repeated unavailable/HDR frames and Compare/Off grace: PASS");
}
"""
    with tempfile.TemporaryDirectory(prefix="nr-lifecycle-") as tmp:
        src = Path(tmp) / "policy.cpp"
        exe = Path(tmp) / "policy.exe"
        src.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                        "-I" + str(ROOT), str(src), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

if __name__ == "__main__":
    main()
