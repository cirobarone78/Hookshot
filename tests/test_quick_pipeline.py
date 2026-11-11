"""A draw that has to wait for its pipeline gets one at once: from a cache if the driver has it, else built without the
driver's optimizer, standing in until the queued full build takes its place (gpu/vk/vk_draw.cpp quick_pipeline; no
game/GPU).

quick_pipeline is compiled as it is in vk_draw.cpp, beside a stand-in driver that has the pipeline compiled, has to compile
it, or cannot make it, and a worker whose full build lands while the stand-in is built: the full build is never run in the
draw, a stand-in never replaces a full build, and one that lost the race is destroyed. The source checks cover the rest of
the change: the stand-in's build flags and caches, the Shader compile row (Wait where needed by default), the translation
jobs ahead of the pipeline builds, and the workers' count.
python -I -B tests/test_quick_pipeline.py
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
using VkPipeline = uint64_t;
using VkPrimitiveTopology = int;
#define VK_NULL_HANDLE 0
#define PROF_EXACT()
struct Program { uint64_t key; };
struct NvnState {};
struct Targets {};
struct PipeEntry {
    std::atomic<bool> ready{false};
    std::atomic<VkPipeline> pipeline{VK_NULL_HANDLE};
};
struct { int device; struct { bool pipelineCreationCacheControl; } vk13; } dev;
int64_t st_waits;
double st_wait_ms;
std::atomic<int64_t> st_quick, st_quick_us;
thread_local bool quick_build = false;
inline void logf(const char*, ...) {}
enum Driver { HAS, COLD, BROKEN } driver;   // (the pipeline: compiled already, to be compiled, never made)
PipeEntry* racing = nullptr;                 // (a worker's full build lands in it while the stand-in is built)
int asks, quick_builds, full_builds, asked_quick, destroyed;
VkPipeline build_graphics(const Program& p, const NvnState&, const Targets&, VkPrimitiveTopology, int part = -1,
                          bool* cold = nullptr) {
    if (part != -1) return VK_NULL_HANDLE;
    if (cold) {   // (asked without compiling)
        asks++, asked_quick += quick_build;
        if (driver == COLD) *cold = true;
        return driver == HAS ? 100 + p.key : VK_NULL_HANDLE;
    }
    if (!quick_build) return full_builds++, 300 + p.key;   // (the worker's full build: never the draw's)
    quick_builds++;
    if (racing) racing->pipeline = 900, racing->ready = true;
    return driver == BROKEN ? VK_NULL_HANDLE : 200 + p.key;
}
inline void vkDestroyPipeline(int, VkPipeline, void*) { destroyed++; }
@CODE@
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
int main(int argc, char** argv) {
    NvnState s;
    Targets at;
    if (argc > 1 && !std::strcmp(argv[1], "off")) {   // (RX_VK_QUICK_WAIT=0: the full build waited for, as before)
        PipeEntry e;
        CHECK(!quick_pipeline(e, Program{1}, s, at, 0) && !e.ready && !asks && !quick_builds && !st_waits);
        return 0;
    }
    dev.vk13.pipelineCreationCacheControl = true;
    // (the driver has it: the optimized one at once, no stand-in built)
    driver = HAS;
    PipeEntry cached;
    CHECK(quick_pipeline(cached, Program{1}, s, at, 0) && cached.ready && cached.pipeline == 101);
    CHECK(asks == 1 && !asked_quick && !quick_builds && !st_quick && st_waits == 1);
    // (cold: built without the optimizer, the flag set for that build only)
    driver = COLD;
    PipeEntry fresh;
    CHECK(quick_pipeline(fresh, Program{2}, s, at, 0) && fresh.ready && fresh.pipeline == 202);
    CHECK(asks == 2 && quick_builds == 1 && st_quick == 1 && !quick_build && st_waits == 2);
    // (the worker's full build landed meanwhile: it stays, and the stand-in, never recorded, is destroyed)
    PipeEntry raced;
    racing = &raced;
    CHECK(quick_pipeline(raced, Program{3}, s, at, 0) && raced.ready && raced.pipeline == 900 && destroyed == 1);
    racing = nullptr;
    // (nothing made: not ready, the caller waits for the full build and counts that wait)
    driver = BROKEN;
    PipeEntry broken;
    CHECK(!quick_pipeline(broken, Program{4}, s, at, 0) && !broken.ready && !broken.pipeline && st_waits == 3 && !quick_build);
    // (a device without pipelineCreationCacheControl: not asked, built without the optimizer at once)
    dev.vk13.pipelineCreationCacheControl = false;
    driver = HAS;
    const int asked = asks;
    PipeEntry plain;
    CHECK(quick_pipeline(plain, Program{5}, s, at, 0) && plain.pipeline == 205 && asks == asked);
    CHECK(!full_builds && !asked_quick && destroyed == 1);
    return 0;
}
"""


PERSIST_FIXTURE = r"""
#include <cstdint>
#include <cstdio>
#include <cstdlib>
struct Texture { uint64_t first_render_frame = 0, cleared_frame = 0; };
struct Targets { int n = 0; Texture* color[8] = {}; Texture* depth = nullptr; };
static uint64_t now_frame = 10;
uint64_t texture_frame_no() { return now_frame; }
@CODE@
#define CHECK(c) do { if (!(c)) { std::printf("FAIL line %d: %s\n", __LINE__, #c); std::exit(1); } } while (0)
int main() {
    Texture c, d;
    Targets at; at.n = 1; at.color[0] = &c; at.depth = &d;
    c.first_render_frame = 5, d.first_render_frame = 5;
    CHECK(targets_persistent(at));                            // (rendered before, not cleared: the last frame's picture fills in)
    c.cleared_frame = 10, d.cleared_frame = 10;
    CHECK(!targets_persistent(at));                           // (both cleared whole this frame: nothing earlier is left)
    d.cleared_frame = 9;
    CHECK(targets_persistent(at));                            // (the depth cleared last frame only: it kept this frame's draws' picture)
    c.cleared_frame = 0, c.first_render_frame = 10, d.cleared_frame = 10;
    CHECK(!targets_persistent(at));                           // (colour made this frame, depth cleared this frame)
    Targets bare; CHECK(!targets_persistent(bare));           // (no targets)
    return 0;
}
"""


def between(text, start, end="\n}\n"):
    a = text.index(start)
    return text[a:text.index(end, a)]


def check_source(draw, shader, jobs, menu, menu_h):
    """What the fixture does not run: the stand-in's flags and caches, the Shader compile row, the jobs' order and count"""
    build = between(draw, "VkPipeline build_graphics(const Program& p, const NvnState& s, const Targets& at, "
                          "VkPrimitiveTopology topo, int part, bool* cold) {")
    if "if (noopt || quick_build) ci.flags |= VK_PIPELINE_CREATE_DISABLE_OPTIMIZATION_BIT;" not in build:
        raise SystemExit("build_graphics: a quick build is not made without the driver's optimizer")
    if "(part < 0 && !driver_cache_only && !quick_build) ? pcache : VK_NULL_HANDLE" not in build or \
            "pcache_built_since_save += !driver_cache_only && !quick_build;" not in build:
        raise SystemExit("build_graphics: a quick build goes into the pipeline cache (the start's or a play file would keep it)")
    body = between(draw, "void draw(VkCommandBuffer cmd, NvnState& s, const DrawArgs& d) {")
    if "const bool may_skip = !always_wait && (opts.async_pipelines != 0 || targets_persistent(at));" not in body:
        raise SystemExit("draw: the Shader compile row does not decide whether a draw may be left out")
    if "if (!quick_pipeline(*pe, p, s, at, topo)) wait_for(pe->ready);" not in body:
        raise SystemExit("draw: a draw that has to wait for its pipeline does not get a quick one first")
    # (a target cleared whole this frame kept no earlier picture: both clears say so, targets_persistent reads it)
    if "at.color[index]->cleared_frame = texture_frame_no();" not in between(draw, "void clear_color_target("):
        raise SystemExit("clear_color_target: a whole clear does not mark the target cleared this frame")
    if "at.depth->cleared_frame = texture_frame_no();" not in between(draw, "void clear_depth_stencil("):
        raise SystemExit("clear_depth_stencil: a whole depth clear does not mark the target cleared this frame")
    if '#include "vk_menu.h"' not in draw:
        raise SystemExit("vk_draw.cpp reads opts without vk_menu.h")
    if "job->e->pipeline = full;" not in between(draw, "PipeEntry* graphics_pipeline("):
        raise SystemExit("graphics_pipeline: the worker's full build no longer takes the stand-in's place")
    if len(re.findall(r"\},\s*true,\s*&raw->ready[,)]", shader)) != 2:   # (then main's failure callback, #1874)
        raise SystemExit("a graphics or mesh translation job is not pushed ahead of the pipeline builds, with its flag")
    start = between(jobs, "void start() {")
    if 'getenv("RX_VK_WORKERS")' not in start or "hw >= 16 ? 6u : std::clamp(hw / 3, 2u, 4u)" not in start:
        raise SystemExit("vk_jobs.cpp start: not 6 workers with 16 hardware threads, or no RX_VK_WORKERS")
    if '{TAB_GRAPHICS, "Shader compile", &opts.async_pipelines, 0, 1, 1, tx_shader_compile,' not in menu:
        raise SystemExit("vk_menu.cpp: no Shader compile row")
    if 'return v ? "Asynchronous" : "Wait where needed";' not in menu:
        raise SystemExit("vk_menu.cpp: the Shader compile row's values are not Wait where needed and Asynchronous")
    # (out of the box a draw waits where it must, as before the row: Asynchronous can leave a pass drawn once wrong)
    if "int async_pipelines = 0;" not in menu_h:
        raise SystemExit("vk_menu.h: Shader compile is not Wait where needed by default")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    vk = ROOT / "gpu" / "vk"
    draw = (vk / "vk_draw.cpp").read_text(encoding="utf-8")
    check_source(draw, (vk / "vk_shader.cpp").read_text(encoding="utf-8"), (vk / "vk_jobs.cpp").read_text(encoding="utf-8"),
                 (vk / "vk_menu.cpp").read_text(encoding="utf-8"), (vk / "vk_menu.h").read_text(encoding="utf-8"))
    code = between(draw, "bool quick_pipeline(PipeEntry& e, const Program& p, const NvnState& s, const Targets& at, "
                         "VkPrimitiveTopology topo) {") + "\n}\n"
    with tempfile.TemporaryDirectory(prefix="quick-pipeline-") as tmp:
        src = Path(tmp) / "quick_pipeline.cpp"
        exe = Path(tmp) / "quick_pipeline"
        src.write_text(FIXTURE.replace("@CODE@", code), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(exe)], check=True)
        env = {k: v for k, v in os.environ.items() if k != "RX_VK_QUICK_WAIT"}
        subprocess.run([str(exe)], check=True, timeout=60, env=env)
        subprocess.run([str(exe), "off"], check=True, timeout=60, env=dict(env, RX_VK_QUICK_WAIT="0"))
        persist = between(draw, "bool targets_persistent(const Targets& at) {") + "\n}\n"
        src2 = Path(tmp) / "targets_persistent.cpp"
        exe2 = Path(tmp) / "targets_persistent"
        src2.write_text(PERSIST_FIXTURE.replace("@CODE@", persist), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(src2), "-o", str(exe2)], check=True)
        subprocess.run([str(exe2)], check=True, timeout=60)
    print("PASS: a waiting draw's pipeline comes from a cache or a quick build, and the full build takes its place; "
          "a target cleared this frame is not left to the last frame's picture")


if __name__ == "__main__":
    main()
