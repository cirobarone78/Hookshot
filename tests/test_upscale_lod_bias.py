"""The upscalers' texture LOD bias at Auto (gpu/vk/upscale_lod_bias.h): the steps for each share of the picture, built as C++
and run, and that vk_draw.cpp's upscale_lod_bias takes them from what the upscalers drew, with the samplers made anew
when they change. No game or GPU required.

python -I -B tests/test_upscale_lod_bias.py [--cxx g++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

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
    # a fixed Render resolution keeps the menu's share; Auto takes what was measured, for the upscalers that scale alone
    bias = function(draw, "float upscale_lod_bias() {")
    scales, auto, fixed = (bias.find(part) for part in (
        "if (!upscaler_rows::scales_by_mode(up)) return 0.0f;",
        "if (share <= 0) return upscale_lod::bias(upscale_lod_auto_steps.load());",
        "std::log2((float)share / 7500.0f)"))
    if not 0 <= scales < auto < fixed:
        raise SystemExit("upscale_lod_bias: Auto's measured bias is gone, or reaches the game's own upscale or a fixed share")
    # another measured step: stored first, then the samplers' generation moved (sampler_for reads the generation first)
    drew = function(draw, "void upscale_lod_drew(uint32_t scene_width, uint32_t picture_width) {")
    stored, moved = drew.find("upscale_lod_auto_steps.exchange(steps) == steps) return;"), drew.find("samplers_changed();")
    if "upscale_lod::steps(scene_width, picture_width, upscale_lod_auto_steps.load())" not in drew or not 0 <= stored < moved:
        raise SystemExit("upscale_lod_drew: a new step does not make the samplers anew after it is stored")
    # the other files call it through vk_draw.h, so it is not in vk_draw.cpp's anonymous namespace (a file-local function
    # of that name leaves theirs unresolved: the renderer does not link)
    inside = 0
    for line in draw[:draw.index("void upscale_lod_drew(uint32_t scene_width, uint32_t picture_width) {")].splitlines():
        if line.startswith("namespace {"):
            inside += 1
        elif inside and re.match(r"\}\s*//\s*namespace\b(?!\s+\w)", line):
            inside -= 1
    if inside:
        raise SystemExit("upscale_lod_drew: defined inside vk_draw.cpp's anonymous namespace (vk_temporal.cpp and vk_fsr3.cpp "
                         "would not find it)")
    header = (ROOT / "gpu" / "vk" / "vk_draw.h").read_text(encoding="utf-8")
    if "void upscale_lod_drew(uint32_t scene_width, uint32_t picture_width);" not in header:
        raise SystemExit("vk_draw.h: upscale_lod_drew is not declared")
    # both upscalers say what they drew
    for name, call in (("vk_temporal.cpp", "upscale_lod_drew(rw, dw);"), ("vk_fsr3.cpp", "upscale_lod_drew(f.width, ow);")):
        if call not in (ROOT / "gpu" / "vk" / name).read_text(encoding="utf-8"):
            raise SystemExit("%s: the size it drew from is not given to upscale_lod_drew" % name)
    with tempfile.TemporaryDirectory(prefix="upscale-lod-") as tmp:
        exe = Path(tmp) / "upscale-lod"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests" / "test_upscale_lod_bias.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
