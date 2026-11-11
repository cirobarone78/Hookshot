"""A game compute program is pinned to 32 lanes only where it can see its lanes (gpu/vk/vk_draw.cpp compute_pin_needed, Intel).

Mesa's compiler for Intel GPUs takes minutes over a big compute program at 32 lanes, and Intel's one compute build thread waits
behind it: OoT's abccf81b45c5eb50 at the Deku Tree never finished on an Iris Xe, and the mesh fallback's builds queued after it
never ran (surfaces left flat white, a haze of bloom over them). A program whose SPIR-V has no subgroup capability is built
without the pin on Intel. This compiles spirv_uses_subgroups and compute_pin_needed and checks: the capabilities that see
lanes (GroupNonUniform*, KHR ballot and vote, Groups, matrices) keep the pin and others do not; unreadable SPIR-V keeps it; a
program with shared memory and at most 32 invocations keeps it; other vendors keep it; RX_VK_PIN_ALL overrides. And that every
game compute pipeline is made through pin_compute, and the compute stages' modules have their flag set from their SPIR-V.

python -I -B tests/test_compute_pin.py [--cxx g++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]


def block(text, marker, start=0):
    start = text.index(marker, start)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


STUBS = r"""
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
struct { struct { uint32_t vendorID = 0x8086; } props; } dev;
struct Stage { bool subgroups = true; };
struct Program { std::vector<Stage> stages; std::array<uint32_t, 3> workgroup{1, 1, 1}; uint32_t shared_memory = 0; };
static int fails = 0;
#define CHECK(c, what) do { if (!(c)) { std::printf("FAIL: %s\n", what); fails++; } } while (0)
"""

MAIN = r"""
static std::vector<uint32_t> module(std::vector<uint32_t> caps, bool ext = false) {
    std::vector<uint32_t> w{0x07230203u, 0x00010600u, 0, 100, 0};
    for (uint32_t c : caps) w.push_back(2u << 16 | 17), w.push_back(c);
    if (ext) w.push_back(3u << 16 | 10), w.push_back(0x5f565053), w.push_back(0);   // (an OpExtension after the capabilities)
    w.push_back(3u << 16 | 14), w.push_back(0), w.push_back(1);                      // (OpMemoryModel: the end of the scan)
    w.push_back(2u << 16 | 17), w.push_back(61);                                     // (a capability past it is not read)
    return w;
}
static Program prog(bool subgroups, uint32_t x, uint32_t shared) {
    Program p;
    p.stages.push_back(Stage{subgroups});
    p.workgroup = {x, 1, 1}, p.shared_memory = shared;
    return p;
}
int main(int argc, char** argv) {
    const char* mode = argc > 1 ? argv[1] : "intel";
    if (std::string_view(mode) == "intel") {
        CHECK(!spirv_uses_subgroups(module({1, 4, 48})), "Shader, Addresses, ...: no lanes seen");
        CHECK(!spirv_uses_subgroups(module({1}, true)), "an extension does not count");
        for (uint32_t c : {18u, 61u, 62u, 63u, 64u, 65u, 66u, 67u, 68u, 4423u, 4431u, 5297u, 5357u, 6022u})
            CHECK(spirv_uses_subgroups(module({1, c}, true)), "a capability that sees the lanes");
        CHECK(spirv_uses_subgroups({}), "empty: as if it did");
        CHECK(spirv_uses_subgroups({0xdeadbeef, 0, 0, 0, 0}), "not SPIR-V: as if it did");
        std::vector<uint32_t> cut = module({1});
        cut[5] = 9u << 16 | 17;   // (a word count past the end)
        CHECK(spirv_uses_subgroups(cut), "a broken module: as if it did");
        CHECK(!compute_pin_needed(prog(false, 64, 0)), "Intel, no subgroups: not pinned");
        CHECK(!compute_pin_needed(prog(false, 64, 4096)), "Intel, shared memory over 32 invocations: not pinned");
        CHECK(compute_pin_needed(prog(false, 32, 4096)), "shared memory and one warp of invocations: pinned");
        CHECK(!compute_pin_needed(prog(false, 32, 0)), "one warp without shared memory: not pinned");
        CHECK(compute_pin_needed(prog(true, 256, 0)), "subgroups: pinned");
        CHECK(compute_pin_needed(Program{}), "no stage: pinned");
    } else if (std::string_view(mode) == "amd") {
        dev.props.vendorID = 0x1002;
        CHECK(compute_pin_needed(prog(false, 64, 0)), "other vendors: pinned as before");
    } else if (std::string_view(mode) == "all") {
        CHECK(compute_pin_needed(prog(false, 64, 0)), "RX_VK_PIN_ALL=1 on Intel: pinned");
    } else if (std::string_view(mode) == "none") {
        dev.props.vendorID = 0x10de;
        CHECK(!compute_pin_needed(prog(false, 64, 0)), "RX_VK_PIN_ALL=0 on NVIDIA: not pinned");
        CHECK(compute_pin_needed(prog(true, 64, 0)), "RX_VK_PIN_ALL=0 keeps the subgroup programs pinned");
    }
    (void)argv;
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    shader = (ROOT / "gpu/vk/vk_shader.cpp").read_text(encoding="utf-8")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    scan = block(shader, "bool spirv_uses_subgroups(const std::vector<uint32_t>& spirv) {")
    needed = block(draw, "bool compute_pin_needed(const Program& p) {")
    pin = block(draw, "void pin_compute(VkPipelineShaderStageCreateInfo& st, const Program& p) {")
    if "pin_subgroup(st, p.workgroup[0]);" not in pin or "compute_pin_needed(p)" not in pin:
        raise SystemExit("pin_compute no longer pins through pin_subgroup when compute_pin_needed says so")

    # every game compute pipeline: its stage through pin_compute (graphics and the mesh fallback keep pin_subgroup)
    if "pin_subgroup(ci.stage" in draw:
        raise SystemExit("a compute pipeline is pinned with pin_subgroup directly: use pin_compute")
    if draw.count("pin_compute(ci.stage, ") < 4:
        raise SystemExit("fewer compute pipelines made through pin_compute than the four (warm, prepare, worker, in the dispatch)")
    # the compute stages' flag: set from the SPIR-V where their modules are made (a translated program, one from the cache)
    # (translated in vk_shader.cpp, read back from the program cache in vk_progcache.cpp)
    cache = (ROOT / "gpu/vk/vk_progcache.cpp").read_text(encoding="utf-8")
    flag = "st.subgroups = spirv_uses_subgroups(spirv);"
    for source, made in ((shader, "st.module = make_module(spirv);\n            " + flag + "\n            kept.push_back(spirv);\n"
                                  "            st.vk_stage = VK_SHADER_STAGE_COMPUTE_BIT;"),
                         (cache, "st.module = make_module(spirv);\n            " + flag + "\n            ok = ok && st.module;")):
        if made not in source:
            raise SystemExit("a compute stage's module is made without its subgroup flag (translated, or from the program cache)")

    with tempfile.TemporaryDirectory(prefix="compute-pin-") as folder:
        folder = Path(folder)
        (folder / "t.cpp").write_text(STUBS + "#include <string_view>\n" + scan + "\n" + needed + "\n" + MAIN, encoding="utf-8")
        exe = folder / "t.exe"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", str(folder / "t.cpp"), "-o", str(exe)], check=True)
        env = {k: v for k, v in os.environ.items() if k != "RX_VK_PIN_ALL"}
        for mode, switch in (("intel", None), ("amd", None), ("all", "1"), ("none", "0")):
            run_env = dict(env, RX_VK_PIN_ALL=switch) if switch else env
            run = subprocess.run([str(exe), mode], capture_output=True, text=True, timeout=10, env=run_env)
            if run.returncode:
                raise SystemExit(run.stdout.strip() or f"the compute pin check failed ({mode})")
    print("PASS: compute pin: only programs that see their lanes pinned on Intel; shared one-warp programs and other vendors "
          "kept pinned; RX_VK_PIN_ALL; every compute pipeline through pin_compute")


if __name__ == "__main__":
    main()
