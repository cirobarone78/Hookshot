"""The HDR10 pass (gpu/vk/shaders/hdr_encode.comp): hdr_encode_comp_spv.h names the sha256 of the shader it was compiled from, and
with glslangValidator (--glslang) the header's code is the shader compiled now. And the PQ curve and the highlight expansion it
uses, checked in Python: paper white lands where ST 2084 puts it, the picture's white reaches the peak, black stays black.
Also what the HDR paths around it need, from the sources: the scaled picture the pass samples (Sharpness, the Window scaling
filter, ultrawide's menu sides) is made with SAMPLED usage, and with the game's native HDR NVIDIA DLSS is made for HDR colour
and given the scene's colour unclamped (dlss_prep.comp's colour ceiling, a specialization constant).

    python -I -B tests/test_hdr_encode.py [--glslang glslangValidator]
"""
import argparse, hashlib, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
SHADERS = VK / "shaders"


def pq(nits):
    m1, m2, c1, c2, c3 = 0.1593017578125, 78.84375, 0.8359375, 18.8515625, 18.6875
    l = (min(max(nits / 10000.0, 0.0), 1.0)) ** m1
    return ((c1 + c2 * l) / (1 + c3 * l)) ** m2


def nits(y, white, peak, knee=0.6):
    over = min(max((y - knee) / (1 - knee), 0.0), 1.0)
    return y * white * (1 + (peak / white - 1) * over * over)


def function(source, start):
    """A function's text from its first line to its closing brace at the start of a line"""
    at = source.find(start)
    if at < 0:
        sys.exit("FAIL: %s is missing" % start.rstrip(" {("))
    body = source[at:]
    return body[:body.index("\n}\n")]


def check_paths():
    # (the HDR pass samples framegen_scale's picture: made without SAMPLED usage, the picture was black with HDR and Sharpness)
    scale = function((VK / "vk_framegen.cpp").read_text(encoding="utf-8"), "VkImage framegen_scale(")
    made = scale[scale.index("make_img(scale.scaled,"):]
    if "VK_IMAGE_USAGE_SAMPLED_BIT" not in made[:made.index("{")]:
        sys.exit("FAIL: framegen_scale's picture is not made with SAMPLED usage, and the HDR pass samples it")
    if "framegen_hdr(f.cmd, framegen_scaled_view()" not in function((VK / "vk_replay.cpp").read_text(encoding="utf-8"),
                                                                     "void present_image("):
        sys.exit("FAIL: present_image's HDR pass no longer reads the scaled picture (this check needs another look)")
    # (the game's native HDR goes past 1 in the scene: DLSS made for HDR colour, and its input not clamped to 1)
    prep = (SHADERS / "dlss_prep.comp").read_text(encoding="utf-8")
    if not re.search(r"layout\(constant_id = 0\) const float kColorMax = 1\.0;", prep) or \
            "clamp(c, 0.0, kColorMax)" not in prep:
        sys.exit("FAIL: dlss_prep.comp's colour is not clamped to its kColorMax (constant 0, 1 by default)")
    chain = (VK / "vk_temporal.cpp").read_text(encoding="utf-8")
    pipes = function(chain, "bool make_pipelines() {")
    if "s.prep_hdr" not in pipes or "&hdr_spec" not in pipes or "VkSpecializationMapEntry hdr_entry{0," not in pipes:
        sys.exit("FAIL: vk_temporal.cpp makes no second dlss_prep pipeline with kColorMax raised for HDR colour")
    upscale = function(chain, "bool temporal_upscale(")
    if "engine.e->hdr && engine.e->hdr()" not in upscale or "hdr ? s.prep_hdr : s.prep" not in upscale:
        sys.exit("FAIL: temporal_upscale does not give an engine made for HDR colour the unclamped pass")
    dlss = (VK / "vk_dlss.cpp").read_text(encoding="utf-8")
    prepare = function(dlss, "int prepare(")
    if "dev.hdr && opts.hdr == 2" not in prepare or "s.feature_hdr == hdr" not in prepare or \
            "NVSDK_NGX_DLSS_Feature_Flags_IsHDR" not in prepare:
        sys.exit("FAIL: DLSS's feature is not made for HDR colour (and again when the game's native HDR turns on or off)")
    if "start, prepare, evaluate, release, memory, hdr}" not in dlss:
        sys.exit("FAIL: vk_dlss.cpp's engine does not tell the chain it takes HDR colour")


a = argparse.ArgumentParser()
a.add_argument("--glslang")
args = a.parse_args()
src = (SHADERS / "hdr_encode.comp").read_bytes()
header = (SHADERS / "hdr_encode_comp_spv.h").read_text()
first = header.splitlines()[0]
if hashlib.sha256(src).hexdigest() not in first:
    sys.exit("FAIL: hdr_encode_comp_spv.h was not made from hdr_encode.comp as it is (recompile it)")
assert abs(pq(100) - 0.5081) < 0.001 and abs(pq(1000) - 0.7518) < 0.001 and pq(0) < 1e-6, "PQ curve"
assert abs(nits(1.0, 200, 1000) - 1000) < 1e-6 and abs(nits(0.5, 200, 1000) - 100) < 1e-6 and nits(0, 200, 1000) == 0
assert all(nits(a / 100, 200, 1000) <= nits((a + 1) / 100, 200, 1000) for a in range(100)), "monotonic"
check_paths()
if args.glslang:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d, "h.h")
        subprocess.run([args.glslang, "-V", "--target-env", "vulkan1.2", "--vn", "HDR_ENCODE_COMP_SPV", "-o", str(out),
                        str(SHADERS / "hdr_encode.comp")], check=True, capture_output=True)
        if out.read_text() != "\n".join(header.splitlines(True)[1:]) and out.read_text() != "".join(header.splitlines(True)[1:]):
            sys.exit("FAIL: hdr_encode_comp_spv.h differs from the shader compiled now")
print("PASS: the HDR10 pass's header is its shader, PQ and the highlight expansion as intended, and the HDR paths around it")
