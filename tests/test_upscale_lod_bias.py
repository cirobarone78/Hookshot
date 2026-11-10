"""The scene's texture LOD bias while NVIDIA DLSS or AMD FSR 3.1 scales it up (gpu/vk/upscale_lod_bias.h): the bias for each
scale, built as C++ and run, and that vk_draw.cpp gives it only to the scene's own mipmapped textures, as samplers of their
own, without a draw keeping the descriptors of a draw with another bias. No game or GPU required.

python -I -B tests/test_upscale_lod_bias.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def function(source, start):
    """A function's body from its first line to its closing brace at the start of a line"""
    at = source.find(start)
    if at < 0:
        raise SystemExit("%s is missing" % start.rstrip(" {("))
    body = source[at:]
    return body[:body.index("\n}\n")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    draw = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
    # which draws: the scene the upscaler last took, by the jitter's sizes (0 with no jitter: no bias without it)
    steps = function(draw, "int scene_lod_steps(const Targets& at) {")
    for part in ('getenv("RX_VK_UPSCALE_LOD_BIAS")', "dlss_jitter_size(axis)", "fsr3_inputs::jitter_size(axis)",
                 "upscale_lod::steps(size(0), size(3), strength)", "at.width == seen.w && at.height == seen.h", "at.depth",
                 "at.color_format[0] == VK_FORMAT_B10G11R11_UFLOAT_PACK32"):
        if part not in steps:
            raise SystemExit("scene_lod_steps: %s is gone (the bias is for the jittered scene alone)" % part)
    # which textures: the fragment stage's own mipmapped ones, never what the GPU drew
    build = function(draw, "void build_descriptors(const NvnState& s, const Program& p) {")
    for part in ("st.vk_stage == VK_SHADER_STAGE_FRAGMENT_BIT && tex && view", "!tex->gpu_written && tex->levels > 1",
                 "sampler_for((int)(handle >> 20), d.is_depth, lod_steps)"):
        if part not in build:
            raise SystemExit("build_descriptors: %s is gone (the scene's LOD bias reaches other textures, or none)" % part)
    # which samplers: those with a mip filter that do not compare, each bias a sampler of its own
    make = function(draw, "VkSampler sampler_make(int id, bool compare, int lod_steps) {")
    if "if (compare || !mip_filter) lod_steps = 0;" not in make:
        raise SystemExit("sampler_make: a comparing sampler or one without a mip filter takes the scene's LOD bias")
    if make.index("lod_steps = 0;") > make.index("uint64_t key = ") or "if (lod_steps) key = mix(key," not in make:
        raise SystemExit("sampler_make: the bias is not part of the sampler's key (a biased sampler for every draw, or none)")
    if "p.lod_bias + upscale_lod::bias(lod_steps)" not in make:
        raise SystemExit("sampler_make: the scene's LOD bias is not added to the game's own")
    table = function(draw, "VkSampler sampler_for(int id, bool compare, int lod_steps")
    if "e.gen == gen && e.steps == lod_steps" not in table:
        raise SystemExit("sampler_for: its biased table does not check the bias it was filled for")
    # a draw with another bias builds its descriptors again
    body = function(draw, "void draw(")
    at = body.index("const bool same_desc = ")
    same = body[at:body.index(";", at)]
    if "last_desc_lod_steps == draw_lod_steps" not in same or body.index("draw_lod_steps = scene_lod_steps(at);") > at:
        raise SystemExit("draw: descriptors are reused across draws with another LOD bias (the scene's samplers elsewhere)")
    if "last_desc_lod_steps = draw_lod_steps" not in body[at:]:
        raise SystemExit("draw: the bias of the descriptors bound is not kept")
    # the upscalers say what they scale to
    for name, start in (("vk_dlss.cpp", "uint32_t dlss_jitter_size(int axis) {"), ("vk_fsr3_inputs.cpp", "uint32_t jitter_size(int axis) {")):
        source = (ROOT / "gpu" / "vk" / name).read_text(encoding="utf-8")
        if "if (axis == 3) return s.jitter_to_w" not in function(source, start) or "s.jitter_to_w = dw;" not in source:
            raise SystemExit("%s: the width the scene is scaled to is not given (axis 3)" % name)
    with tempfile.TemporaryDirectory(prefix="upscale-lod-") as tmp:
        exe = Path(tmp) / "upscale-lod"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests" / "test_upscale_lod_bias.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
