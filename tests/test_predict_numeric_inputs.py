"""Predict vertex layouts only between matching numeric input classes.

Compile the real predictor with synthetic SPIR-V declarations. No game data is used.
python -I -B tests/test_predict_numeric_inputs.py --cxx g++
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check_numeric_inputs(cxx):
    source = (ROOT / "gpu/vk/vk_predict.cpp").read_text(encoding="utf-8")
    source = source.replace('#include "vk_draw.h"', '').replace('#include "vk_shader.h"', '')
    fixture = r"""#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <vector>
#include <utility>
#include <initializer_list>
#define CHECK(x)                                                                                   \
    do {                                                                                           \
        if (!(x)) {                                                                                \
            std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x);                                    \
            std::exit(1);                                                                          \
        }                                                                                          \
    } while (0)
namespace mkwvk {
constexpr uint32_t VK_SHADER_STAGE_VERTEX_BIT = 1, VK_SHADER_STAGE_FRAGMENT_BIT = 16,
                   VK_SHADER_STAGE_TASK_BIT_EXT = 64, VK_SHADER_STAGE_MESH_BIT_EXT = 128;
struct Stream {
    uint32_t stride = 0, divisor = 0;
};
struct State {
    uint32_t vattr[16]{};
    int nvattr = 16;
    Stream vstream[16]{};
};
struct PipeNote {
    State s;
    uint32_t topo = 3, samples = 1, n = 1, color_format[8]{}, has_depth = 0, depth_format = 0;
    uint64_t prog = 0, variant = 0, key = 0;
};
struct KeptProgram {
    uint64_t key, variant = 0;
    std::vector<std::pair<uint32_t, std::vector<uint32_t>>> stages;
};
std::vector<KeptProgram> kept;
template <class F> void program_cache_each(F fn) {
    for (const auto &k : kept)
        fn(k);
}
} // namespace mkwvk
""" + source + r"""
using namespace mkwvk;
// Synthetic declaration words only: exercise predictor inspection, not a Vulkan shader or game
// input.
std::vector<uint32_t> input(unsigned kind, unsigned base, bool grouped = false) {
    std::vector<uint32_t> w{0x07230203, 0x10000, 0, base + 10, 0};
    auto op = [&](uint32_t code, std::initializer_list<uint32_t> a) {
        w.push_back(((uint32_t)a.size() + 1) << 16 | code);
        w.insert(w.end(), a);
    };
    op(71, {base + 4, 30, 6});
    if (grouped) {
        op(73, {base + 9});
        op(71, {base + 9, 31, 2});
        op(74, {base + 9, base + 4});
    }
    if (kind == 0)
        op(22, {base, 32});
    else if (kind == 3)
        op(22, {base, 64});
    else
        op(21, {base, 32, kind == 1 ? 1u : 0u});
    op(23, {base + 1, base, 4});
    op(32, {base + 2, 1, base + 1});
    op(59, {base + 2, base + 4, 1});
    return w;
}
void trial(unsigned donor, unsigned target, bool expected, bool exact = false,
           bool grouped = false) {
    auto d = input(donor, 10, exact && grouped), t = exact ? d : input(target, 40, grouped);
    kept = {{1, 0, {{VK_SHADER_STAGE_VERTEX_BIT, d}}}, {2, 0, {{VK_SHADER_STAGE_VERTEX_BIT, t}}}};
    std::vector<std::unique_ptr<PipeNote>> notes;
    auto n = std::make_unique<PipeNote>();
    n->prog = 1;
    n->s.vattr[6] = 77;
    n->s.vstream[0].stride = 16;
    notes.push_back(std::move(n));
    size_t programs = 0;
    auto predicted = predict_pipelines(notes, &programs);
    CHECK(predicted.size() == (expected ? 1u : 0u));
    CHECK(programs == (expected ? 1u : 0u));
    if (expected) {
        CHECK(predicted[0]->prog == 2);
        CHECK(predicted[0]->s.vattr[6] == 77);
        CHECK(predicted[0]->s.vstream[0].stride == 16);
    }
}
int main() {
    trial(2, 0, false); // same locations, UINT donor must not feed FLOAT target
    trial(0, 0, true);  // different SPIR-V IDs, same numeric class shares fallback
    trial(2, 2, true);
    trial(1, 1, true);
    trial(1, 2, false);
    trial(0, 1, false);              // S32, U32 and F32 are distinct
    trial(3, 3, false);              // unsupported64-bit inputs must not share fallback
    trial(3, 3, true, true);         // exact module still works for unknown representations
    trial(0, 0, false, false, true); // grouped Component decoration is not a plain location input
    trial(0, 0, true, true, true);   // the identical grouped module keeps exact matching
    std::puts("PASS: numeric32 predictor fallback, canonical IDs, unsupported exact-only");
}
"""
    with tempfile.TemporaryDirectory(prefix="predict-inputs-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / "fixture.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run(
            [cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)],
            check=True, timeout=120,
        )
        subprocess.run([str(exe)], check=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_numeric_inputs(args.cxx)


if __name__ == "__main__":
    main()
