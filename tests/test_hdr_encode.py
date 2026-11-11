"""The HDR10 pass (gpu/vk/shaders/hdr_encode.comp): hdr_encode_comp_spv.h names the sha256 of the shader it was compiled from, and
with glslangValidator (--glslang) the header's code is the shader compiled now. And the PQ curve and the highlight expansion it
uses, checked in Python: paper white lands where ST 2084 puts it, the picture's white reaches the peak, black stays black.
The HDR contrast row's grading, the shader's own grade() and shoulder() run in Python: nothing at 100%, and at any contrast
from 50% to 200% the light rises with the picture's, black stays black and its top lands on the peak, eased into it rather
than cut flat. Native is graded under the peak the game is told, moves on smoothly from 100%, and the game's light above that
peak is not cut flat (no peak limit for it). And its push constants are the ones framegen_hdr pushes.
Also what the HDR paths around it need, from the sources: Native HDR is told by the format the game presents alone, its
picture never blitted from its image, and at 100% contrast (exposure 1) the pass writes the game's PQ codes as they are.

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


def pq_decode(e):
    m1, m2, c1, c2, c3 = 0.1593017578125, 78.84375, 0.8359375, 18.8515625, 18.6875
    p = min(max(e, 0.0), 1.0) ** (1 / m2)
    return 10000.0 * (max(p - c1, 0.0) / (c2 - c3 * p)) ** (1 / m1)


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


def glsl_functions(text, names, consts):
    """The shader's scalar functions (names) as Python: their statements are const float declarations, if (...) return ...
    and return ...; consts: what pc.<field> reads"""
    out = {}
    scope = dict(consts, min=min, max=max, abs=abs, pow=pow)
    for name in names:
        m = re.search(r"\nfloat %s\(([^)]*)\) \{(.*?)\n?\}\n" % name, text, re.S)
        if not m:
            sys.exit("FAIL: hdr_encode.comp has no float %s(...)" % name)
        params = [a.split()[-1] for a in m.group(1).split(",")]
        lines = ["def %s(%s):" % (name, ", ".join(params))]
        for stmt in re.sub(r"//[^\n]*", "", m.group(2)).split(";"):
            stmt = " ".join(stmt.split()).replace("||", "or").replace("&&", "and").replace("pc.", "pc_")
            if not stmt:
                continue
            cond = re.fullmatch(r"if \((.*)\) return (.*)", stmt)
            decl = re.fullmatch(r"const float (\w+) = (.*)", stmt)
            if cond:
                lines.append("    if %s: return %s" % cond.groups())
            elif decl:
                lines.append("    %s = %s" % decl.groups())
            elif stmt.startswith("return "):
                lines.append("    " + stmt)
            else:
                sys.exit("FAIL: %s(): a statement this check cannot read: %s" % (name, stmt))
        exec("\n".join(lines), scope)
        out[name] = scope[name]
    return out


def check_grading():
    # (the row: 50 to 200%, 100% (none) out of the box, kept in the options file as hdr_contrast, its name's key)
    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    if not re.search(r'\{TAB_GRAPHICS, "HDR contrast", &opts\.hdr_contrast, 50, 200, 5, tx_percent,', menu) or \
            "int hdr_contrast = 100;" not in (VK / "vk_menu.h").read_text(encoding="utf-8"):
        sys.exit("FAIL: the HDR contrast row is not 50 to 200% in steps of 5, 100% by default")
    text = (SHADERS / "hdr_encode.comp").read_text(encoding="utf-8")
    # (the push constants: the shader's, and framegen_hdr's struct in the same order, 48 bytes)
    block = re.sub(r"//[^\n]*", "", text[text.index("uniform P {") + 11:text.index("} pc;")])
    shader = [n.strip() for decl in block.split(";") if decl.strip() for n in decl.split(None, 1)[1].split(",")]
    hdr = function((VK / "vk_framegen.cpp").read_text(encoding="utf-8"), "VkImage framegen_hdr(")
    pushed = re.search(r"const struct \{ float uv\[4\]; float ([^;]*); \} pc", hdr)
    if shader != ["uv", "white", "peak", "knee", "mode", "contrast", "exposure", "pad0", "pad1"] or not pushed or \
            [n.strip() for n in pushed.group(1).split(",")] != shader[1:] or "{S, I}, 48)" not in hdr:
        sys.exit("FAIL: hdr_encode.comp's push constants %s are not the 48 bytes framegen_hdr pushes" % shader)
    main = text[text.index("void main()"):]
    # (Native at 100% contrast and exposure 1: the game's PQ codes written as they are, before any decode or encode)
    through = main.index("if (pc.mode >= 0.5 && pc.contrast == 1.0 && pc.exposure == 1.0) {")
    if "imageStore(dst, at, vec4(c, 1.0));\n        return;" not in main[through:through + 200] or \
            through > main.index("pq_decode(c)"):
        sys.exit("FAIL: hdr_encode.comp does not pass Native's PQ codes through as they are at 100% contrast")
    for line in ("if (y > 1e-6 && (pc.contrast != 1.0 || pc.exposure != 1.0)) {",
                 "const float top = pc.peak / pc.white;",
                 "nits *= shoulder(grade(y), grade(top), top) / y;", "if (pc.mode < 0.5 && yn > pc.peak) nits *= pc.peak / yn;"):
        if line not in main:
            sys.exit("FAIL: hdr_encode.comp's main does not grade as this check expects: %s" % line)
    for white, peak in ((200, 1000), (230, 800), (80, 400), (400, 400), (80, 4000), (400, 4000)):
        top = peak / white
        for percent in range(50, 205, 5):
            f = glsl_functions(text, ("grade", "shoulder"), {"pc_exposure": 1.0, "pc_contrast": percent / 100})
            # (Expanded: the SDR picture's luminance 0..1 as the pass expands it, relative to the paper white)
            ys = [nits(i / 2000, white, peak) / white for i in range(2001)]
            out = [f["shoulder"](f["grade"](y), f["grade"](top), top) for y in ys]
            where = "at %d%%, paper white %d, peak %d" % (percent, white, peak)
            if percent == 100 and any(abs(o - y) > 1e-9 * max(1.0, y) for o, y in zip(out, ys)):
                sys.exit("FAIL: 100% changes the picture " + where)
            if any(b < a - 1e-12 for a, b in zip(out, out[1:])) or out[0] != 0.0:
                sys.exit("FAIL: the graded light does not rise with the picture's from black " + where)
            if abs(out[-1] - top) > 1e-9 * top or max(out) > top * (1 + 1e-12):
                sys.exit("FAIL: the picture's top does not land on the peak " + where)
            # (eased into the peak, not cut flat: a plain limit put a fifth of the picture at the peak at 150%)
            if sum(o >= 0.999 * top for o in out) > 0.03 * len(out):
                sys.exit("FAIL: the highlights are cut flat at the peak " + where)
            # (light past the picture's top goes on rising: Native's above the peak row, not cut flat; Expanded's has none)
            m = f["grade"](top)
            if not f["shoulder"](m * 1.5, m, top) > f["shoulder"](m, m, top) >= top * (1 - 1e-9):
                sys.exit("FAIL: light past the picture's top does not keep rising " + where)
        # (Native: the game's own PQ picture, codes 0..1. Graded under the peak the game is told (the HDR peak row, which it stays
        # under), its top and the shoulder's target; light the game puts above that peak keeps rising, with no limit after it)
        for percent in range(50, 205, 5):
            f = glsl_functions(text, ("grade", "shoulder"), {"pc_exposure": 1.0, "pc_contrast": percent / 100})
            ys = [pq_decode(i / 2000) / white for i in range(2001)]
            out = [f["shoulder"](f["grade"](y), f["grade"](top), top) for y in ys]
            where = "with Native at %d%%, paper white %d, peak %d" % (percent, white, peak)
            if percent == 100 and any(abs(o - y) > 1e-9 * max(1.0, y) for o, y in zip(out, ys)):
                sys.exit("FAIL: 100% changes the game's picture " + where)
            if out[0] != 0.0 or any(b <= a for a, b in zip(out, out[1:])):
                sys.exit("FAIL: the game's light does not rise with each PQ code from black (above the peak too) " + where)
            if abs(f["shoulder"](f["grade"](top), f["grade"](top), top) - top) > 1e-9 * top:
                sys.exit("FAIL: the peak the game is told, graded, does not land on itself " + where)
            if any(o > top * (1 + 1e-12) for o, y in zip(out, ys) if y <= top):
                sys.exit("FAIL: the game's light under the peak row is graded past it " + where)
        # (continuous with 100%, where the picture is passed through as it is: at 95% and 105% the paper white and 0.9 of the
        # peak move by less than a fifth)
        graded = {}
        for percent in (95, 100, 105):
            f = glsl_functions(text, ("grade", "shoulder"), {"pc_exposure": 1.0, "pc_contrast": percent / 100})
            graded[percent] = [f["shoulder"](f["grade"](y), f["grade"](top), top) * white for y in (1.0, 0.9 * top)]
        for percent in (95, 105):
            if any(abs(g / n - 1) >= 0.2 for g, n in zip(graded[percent], graded[100])):
                sys.exit("FAIL: Native's grade jumps away from the picture at 100%%: %d%% gives %s nits for %s, paper white %d, "
                         "peak %d" % (percent, ["%.0f" % g for g in graded[percent]], ["%.0f" % n for n in graded[100]],
                                      white, peak))


def check_paths():
    # (Native told by the format the game presents, the view's, alone: the cached image's format is not the picture's when the
    # two share an image by format class, either way round)
    replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    present = function(replay, "void do_present(")
    native = present[present.index("present_native_pq.store("):]
    native = native[:native.index(";")]
    if "const VkFormat shown_format = t ? vk_format(t->d.format).format" not in present or \
            "shown_format == VK_FORMAT_A2B10G10R10_UNORM_PACK32" not in native or "tex->format" in native:
        sys.exit("FAIL: do_present does not tell Native HDR by the format the game presents alone")
    # (Native: never the game's image blitted in its image's format; the shot's scale pass told it is PQ as well)
    image = function(replay, "void present_image(")
    if "} else if (src && !native_pq) {" not in image or \
            "framegen_scale(f.cmd, view, src, sw, sh, crop, rect.w, rect.h, native_pq)" not in image:
        sys.exit("FAIL: present_image can blit Native HDR's picture from its image, or scales it as SDR")
    shot = present[present.index("const VkImage fx_img ="):]
    if "kShotW, kShotH,\n" not in shot[:shot.index(";")] or "present_native_pq.load(" not in shot[:shot.index(";")]:
        sys.exit("FAIL: the RX_VK_SHOT_FX shot scales Native HDR's picture as SDR")


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
check_grading()
if args.glslang:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d, "h.h")
        subprocess.run([args.glslang, "-V", "--target-env", "vulkan1.2", "--vn", "HDR_ENCODE_COMP_SPV", "-o", str(out),
                        str(SHADERS / "hdr_encode.comp")], check=True, capture_output=True)
        if out.read_text() != "\n".join(header.splitlines(True)[1:]) and out.read_text() != "".join(header.splitlines(True)[1:]):
            sys.exit("FAIL: hdr_encode_comp_spv.h differs from the shader compiled now")
print("PASS: the HDR10 pass's header is its shader, PQ, the highlight expansion and the contrast grading as intended, "
      "and the HDR paths around it")
