"""The Insert menu's tab strip fits the window (gpu/vk/vk_menu.cpp tab_strip_fit, draw_options).

The menu is scaled by the window's height alone, so the strip of tab titles is as wide in points on every screen: six tabs
at Large were wider than a 16:10 screen (the Steam Deck's 1280x800 put the Q and E keys past its edges) and a 4:3 one.
tab_strip_fit keeps the titles and their gaps inside the room between the safe margins and the tab keys: the gaps narrow
first, down to a least gap, then the titles shrink in proportion; where they fit, nothing changes. Compile the function
from the source and run it over the screens and menu sizes players use, with the six titles' widths as the menu's font
draws them (in points at 23); check that draw_options draws with what it returns. No game or GPU is needed.

    python -I -B tests/test_tab_strip_fit.py [--cxx g++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    depth = 0
    for at in range(text.index("{", start), len(text)):
        depth += text[at] == "{"
        depth -= text[at] == "}"
        if depth == 0:
            return text[start:at + 1]
    raise SystemExit("unterminated block: " + marker)


FIXTURE = r"""
#include <algorithm>
#include <cmath>
#include <cstdio>
/* FIT */
// (the six titles' widths in points at 23, as the heading font draws Game, Graphics, Display, Audio, Controls, Debug; Game
// as Gameplay's 104, the widest the first tab has been)
static const float kTitlePt[6] = {104, 92, 80, 62, 98, 70};
// (vk_ui.h unit: pixels per point h / 720 times 0.85, 1 or 1.3; the safe margin 2.5% of h, 5% at Large)
static int check(const char* what, float w, float h, int size, int tabs, bool want_same) {
    const float k = size == 1 ? 0.85f : size == 3 ? 1.3f : 1.0f, s = h / 720.0f * k, safe = h * (size == 3 ? 0.05f : 0.025f);
    float tw[6], px = 23 * s, gap = 56 * s, titles = 0;
    for (int i = 0; i < tabs; i++) tw[i] = kTitlePt[i] * s, titles += tw[i];
    const float room = w - 2 * (safe + 48 * s);
    tab_strip_fit(tw, tabs, room, 16 * s, &px, &gap);
    const float used = titles * (px / (23 * s)) + gap * tabs;
    const bool same = px == 23 * s && gap == 56 * s;
    std::printf("%-28s room %7.1f  used %7.1f  title %.2f pt  gap %.1f pt%s\n", what, room, used, px / s, gap / s,
                same ? "  (unchanged)" : "");
    if (used > room + 0.01f) { std::fprintf(stderr, "FAIL %s: the strip is wider than its room\n", what); return 1; }
    if (gap < 16 * s - 0.001f) { std::fprintf(stderr, "FAIL %s: a gap below the least\n", what); return 1; }
    if (want_same && !same) { std::fprintf(stderr, "FAIL %s: a strip that fitted was changed\n", what); return 1; }
    if (!(px > 0)) { std::fprintf(stderr, "FAIL %s: no title size\n", what); return 1; }
    return 0;
}
int main() {
    int bad = 0;
    bad += check("1920x1080 Small", 1920, 1080, 1, 6, true);
    bad += check("1920x1080 Medium", 1920, 1080, 2, 6, true);
    bad += check("1920x1080 Large", 1920, 1080, 3, 6, false);
    bad += check("5120x2160 Large", 5120, 2160, 3, 6, true);
    bad += check("1280x800 Medium (Deck)", 1280, 800, 2, 6, true);
    bad += check("1280x800 Large (Deck)", 1280, 800, 3, 6, false);
    bad += check("1920x1200 Large (16:10)", 1920, 1200, 3, 6, false);
    bad += check("1440x1080 Large (4:3)", 1440, 1080, 3, 6, false);
    bad += check("800x800 Large (a narrow window)", 800, 800, 3, 6, false);
    bad += check("1920x1080 Medium, five tabs", 1920, 1080, 2, 5, true);
    return bad ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    fit = block(menu, "void tab_strip_fit(const float* w, int n, float room, float min_gap, float* px, float* gap) {")
    draw = block(menu, "void draw_options(ui::Ctx& c) {")
    for need, why in (("tab_strip_fit(title_w, TAB_COUNT, c.w - 2 * (c.safe + 48 * s), 16 * s, &title_px, &gap);",
                       "draw_options does not fit the strip between the safe margins and the tab keys"),
                      ("ui::text_mid(c, c.f.heading, title_px, x + gap * 0.5f, ty,",
                       "draw_options does not draw the titles at the fitted size and gap")):
        if need not in draw:
            raise SystemExit("FAIL: " + why)
    with tempfile.TemporaryDirectory(prefix="tab-strip-fit-") as tmp:
        src = Path(tmp) / "fit.cpp"
        exe = Path(tmp) / ("fit" + (".exe" if os.name == "nt" else ""))
        src.write_text(FIXTURE.replace("/* FIT */", fit), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++17", "-O1", "-o", str(exe), str(src)], check=True)
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        print(run.stdout, end="")
        if run.returncode:
            raise SystemExit(run.stderr.strip() or "FAIL")
    print("PASS: the tab strip fits the window at every size, unchanged where it fitted")


if __name__ == "__main__":
    main()
