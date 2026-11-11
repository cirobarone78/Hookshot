# SPDX-License-Identifier: GPL-3.0-or-later
"""A shader preparation the GPU driver stops answering in goes on or ends, and says why (#2107).

Builds on players' cards of all kinds, AMD and NVIDIA, stopped for good in the predicted pipelines, the Builder's details showing
the last line written ("vertex format NVN 0xe -> vk 17"). The driver had faulted in a pipeline compile (caught: "the driver faulted compiling") and
was left holding a lock of its own. Compiled from the real source, with stand-ins for the driver and the files:

- predict_run (gpu/vk/vk_draw.cpp): builds every predicted pipeline; its first one alone; a pipeline the driver never finishes
  leaves the run going on once nothing has finished for RX_VK_PREDICT_STALL_S; a slow driver that still finishes pipelines does not.
- the --prepare-shaders run's watchdog (gpu/vk/vk_main.cpp prepare_watchdog): a status line in the log after a quiet spell, saying
  what it is waiting on; once nothing has moved for RX_VK_PREPARE_STALL_S, the reason, hookshot_prepare_skipped and exit status 4,
  never during the pipeline cache's save.
- make_game.py says "the GPU driver stopped responding" for exit status 4.

python -I -B tests/test_prepare_stall.py --cxx clang++
"""
import argparse
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def block(text, marker):
    """The function or block that starts at marker, through its closing brace"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PREDICT_HEAD = r'''
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>
#define CHECK(c) do { if (!(c)) { std::fprintf(stderr, "CHECK failed line %d: %s\n", __LINE__, #c); std::_Exit(7); } } while (0)
using VkPipeline = uintptr_t;
using VkPrimitiveTopology = int;
struct NvnState { int unused = 0; };
struct Targets {};
struct PipeNote { uint64_t key, prog, variant; uint32_t topo; NvnState s; };
struct Program { uint64_t key; uint64_t variant; };
struct { uintptr_t device = 1; } dev;
thread_local bool driver_cache_only = false;
static int mode;              // 0 quick, 1 one pipeline never finishes, 2 each pipeline slow
static int programs_n = 40, per_program = 3;
static constexpr uint64_t kStuck = 7;
static std::atomic<int> built{0}, destroyed{0}, inside{0}, most_inside{0};
static std::atomic<bool> first_was_alone{true}, first_seen{false};
static std::string logged;
static std::mutex log_mu;
void logf(const char* f, ...) {
    char b[2048];
    va_list a;
    va_start(a, f);
    std::vsnprintf(b, sizeof b, f, a);
    va_end(a);
    std::lock_guard lk(log_mu);
    logged += b;
    logged += "\n";
}
bool prepare_stopped() { return false; }
void ub_thread_off() {}
void Sleep(unsigned ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
std::vector<std::unique_ptr<PipeNote>> pipe_notes_read() {
    std::vector<std::unique_ptr<PipeNote>> v;
    v.push_back(std::make_unique<PipeNote>(PipeNote{1, 1, 0, 3, {}}));
    return v;
}
std::vector<std::unique_ptr<PipeNote>> predict_pipelines(const std::vector<std::unique_ptr<PipeNote>>&, size_t* programs) {
    std::vector<std::unique_ptr<PipeNote>> v;
    for (int p = 1; p <= programs_n; p++)
        for (int k = 0; k < per_program; k++) v.push_back(std::make_unique<PipeNote>(PipeNote{0, (uint64_t)p, 0, 3, {}}));
    v.push_back(std::make_unique<PipeNote>(PipeNote{0, 2, 99, 3, {}}));   // (a variant no kept program answers)
    *programs = (size_t)programs_n;
    return v;
}
void program_cache_borrow(uint64_t key, const std::function<void(Program&)>& fn) {
    Program p{key, 0};
    fn(p);
}
void ensure_layout(Program&) {}
Targets note_targets(const PipeNote&) { return {}; }
VkPrimitiveTopology pipeline_topology(const Program&, VkPrimitiveTopology t) { return t; }
VkPipeline build_graphics(const Program& p, const NvnState&, const Targets&, VkPrimitiveTopology) {
    CHECK(driver_cache_only);
    const int now = ++inside;
    for (int m = most_inside.load(); now > m && !most_inside.compare_exchange_weak(m, now);) {}
    const bool first = !first_seen.exchange(true);
    if (mode == 1 && p.key == kStuck && !first)   // (the driver never answers; not the first, which the others wait for)
        for (;;) std::this_thread::sleep_for(std::chrono::hours(1));
    std::this_thread::sleep_for(std::chrono::milliseconds(mode == 2 ? 300 : first ? 200 : 1));
    if (first && inside.load() != 1) first_was_alone = false;   // (another began while the first was being built)
    --inside;
    return (VkPipeline)(0x100 + ++built);
}
void vkDestroyPipeline(uintptr_t, VkPipeline, const void*) { ++destroyed; }
static std::atomic<size_t> last_done{0}, last_total{0};
void progress(size_t done, size_t total) {
    CHECK(done <= total);
    last_done = done, last_total = total;
}
'''

PREDICT_MAIN = r'''
int main(int argc, char** argv) {
    CHECK(argc == 2);
    mode = std::atoi(argv[1]);
    if (mode == 2) programs_n = 6, per_program = 5;   // (each program 1.5 s, past the 1 s stall: only per pipeline counts)
    const auto t0 = std::chrono::steady_clock::now();
    predict_run(progress);
    const double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    const int all = programs_n * per_program;
    std::printf("%s", logged.c_str());
    CHECK(last_total == (size_t)all + 1 && last_done == last_total);   // (the bar full, the stuck pipeline's part included)
    CHECK(first_was_alone);
    if (mode == 1) {
        CHECK(logged.find("nothing finished for 1 s") != std::string::npos);
        CHECK(logged.find("gone on without the pipelines the driver did not finish") != std::string::npos);
        CHECK(secs < 20);
        if (std::thread::hardware_concurrency() > 1)   // (only the stuck program's left: its first, when it was the very first)
            CHECK(built >= all - per_program && built <= all - per_program + 1);
        std::fflush(stdout);
        std::_Exit(0);   // (its worker is still in the "driver")
    }
    CHECK(logged.find("nothing finished") == std::string::npos);
    CHECK(built == all && destroyed == all);
    return 0;
}
'''

WATCH_HEAD = r'''
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#else
static void Sleep(unsigned ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
#endif
struct MkwVkHost { void (*log)(const char*); void (*log_flush)(void); };
static void host_log(const char* s) { std::printf("[log] %s\n", s); std::fflush(stdout); }
static void host_flush() { std::fflush(stdout); }
static const MkwVkHost host_v{host_log, host_flush};
const MkwVkHost* host = &host_v;
static int faults;
int driver_faults() { return faults; }
std::string skipped_path() { return std::getenv("FIXTURE_SKIPPED"); }
'''

WATCH_MAIN = r'''
int main(int argc, char** argv) {
    if (argc != 2) return 9;
    const std::string c = argv[1];
    if (c == "fault") faults = 1;
    prepare_watchdog();
    if (c == "stuck" || c == "fault") {
        prepare_moved(1, 5, 10);
        Sleep(20000);   // (the watchdog ends the process before this does)
        return 8;
    }
    if (c == "moving") {
        for (size_t i = 1; i <= 15; i++) prepare_moved(0, i, 100), Sleep(300);
        return 0;
    }
    if (c == "save") {
        prepare_moved(3, 0, 0);
        Sleep(4000);
        return 0;
    }
    return 9;
}
'''


def compile_run(cxx, name, code, tmp):
    src = Path(tmp) / (name + ".cpp")
    exe = Path(tmp) / (name + (".exe" if os.name == "nt" else ""))
    src.write_text(code, encoding="utf-8")
    cmd = [cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", str(src), "-o", str(exe)]
    if os.name != "nt":
        cmd.insert(1, "-pthread")
    subprocess.run(cmd, check=True, timeout=180)
    return exe


def check_predict(cxx, tmp):
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    exe = compile_run(cxx, "predict", PREDICT_HEAD + block(draw, "void predict_run(") + PREDICT_MAIN, tmp)
    for case, what in (("0", "every predicted pipeline built, the first alone"),
                       ("1", "a pipeline the driver never finishes: the run goes on"),
                       ("2", "a slow driver that still finishes pipelines: no stop")):
        env = dict(os.environ, RX_VK_PREDICT_STALL_S="1")
        r = subprocess.run([str(exe), case], env=env, capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise SystemExit("predict_run, %s: exit %d\n%s%s" % (what, r.returncode, r.stdout, r.stderr))
        print("PASS predict_run:", what, flush=True)


def check_watchdog(cxx, tmp):
    main = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    pieces = [block(main, "int64_t steady_ms() {"), "std::atomic<int64_t> last_log_ms{0};\n", block(main, "void logf(const char* fmt, ...) {"),
              main[main.index("std::atomic<int64_t> prepare_moved_ms{0};"):main.index("void prepare_moved(")],
              block(main, "void prepare_moved("), "std::atomic<int> driver_faults_seen{0};\n", block(main, "void prepare_watchdog() {")]
    exe = compile_run(cxx, "watchdog", WATCH_HEAD + "\n".join(pieces) + WATCH_MAIN, tmp)
    for case, code, need, never in (
            ("stuck", 4, ["waiting on the GPU driver or the disk", "the predicted pipelines (5 of 10)", "STOPPED"], ["faulted"]),
            ("fault", 4, ["faulted 1 time so far", "waiting on the GPU driver, which faulted (above)", "after it faulted (above)", "STOPPED"],
             []),
            ("moving", 0, ["still working on the shader programs"], ["STOPPED", "waiting:"]),
            ("save", 0, ["still writing the pipeline cache's save"], ["STOPPED"])):
        skipped = Path(tmp) / ("skipped-" + case)
        env = dict(os.environ, RX_VK_PREPARE_STALL_S="4", RX_VK_PREPARE_STATUS_S="1", FIXTURE_SKIPPED=str(skipped))
        t0 = time.time()
        r = subprocess.run([str(exe), case], env=env, capture_output=True, text=True, timeout=60)
        out = r.stdout
        if r.returncode != code:
            raise SystemExit("watchdog %s: exit %d, expected %d\n%s%s" % (case, r.returncode, code, out, r.stderr))
        for n in need:
            if n not in out:
                raise SystemExit("watchdog %s: the log lacks %r\n%s" % (case, n, out))
        for n in never:
            if n in out:
                raise SystemExit("watchdog %s: the log has %r\n%s" % (case, n, out))
        if (code == 4) != skipped.exists():
            raise SystemExit("watchdog %s: hookshot_prepare_skipped %s" % (case, "missing" if code == 4 else "left by a run that went on"))
        if code == 4 and time.time() - t0 > 15:
            raise SystemExit("watchdog %s: took %.0f s to stop" % (case, time.time() - t0))
        print("PASS watchdog:", case, flush=True)


def check_sources():
    main = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    only = main[main.index("if (prepare_only()) {"):]
    only = only[:only.index("\n        return true;\n    }\n")]
    for need, why in (("prepare_watchdog();", "the --prepare-shaders run has no watchdog"),
                      ("prepare_moved(part, done, total);", "the watchdog does not see the parts' progress"),
                      ("prepare_moved(3, 0, 0);", "the watchdog could stop the pipeline cache's save")):
        if need not in only:
            raise SystemExit(why)
    if only.index("prepare_moved(3, 0, 0);") > only.index("pipeline_cache_save(true);"):
        raise SystemExit("the watchdog could stop the pipeline cache's save")
    watch = block(main, "void prepare_watchdog() {")
    if "TerminateProcess(GetCurrentProcess(), 4);" not in watch or "exit(4)" in watch.replace("_Exit(4)", ""):
        raise SystemExit("the watchdog ends the run through exit(), which unloads the driver it waits on")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    if draw.count("note_driver_fault();") < 4:
        raise SystemExit("a fault guard does not count its faults for the watchdog")


def check_make_game():
    spec = importlib.util.spec_from_file_location("make_game_stall", ROOT / "nx2" / "make_game.py")
    make_game = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_game)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = make_game.prepare_shaders([sys.executable, "-I", "-c", "import sys; sys.exit(4)"])
    lines = [l for l in out.getvalue().splitlines() if l.startswith(make_game.NOT_PREPARED)]
    if code != 4 or len(lines) != 1 or "(the GPU driver stopped responding)" not in lines[0]:
        raise SystemExit("make_game.py does not say why for exit status 4: %r" % out.getvalue())
    print("PASS make_game: exit status 4", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check_sources()
    check_make_game()
    if not shutil.which(args.cxx):
        raise SystemExit("C++ compiler not found: " + args.cxx)
    with tempfile.TemporaryDirectory(prefix="prepare-stall-") as tmp:
        check_predict(args.cxx, tmp)
        check_watchdog(args.cxx, tmp)
    print("PASS: predict_run and the preparation's watchdog")


if __name__ == "__main__":
    main()
