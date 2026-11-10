"""The Insert menu's controller prompts use the game's own button icons, the Switch's code points in
Font2/Scalable/External (gpu/vk/vk_ui.h prompt_icons). They must be the same code points the prompt font is built
around (nx2/prompt_assets.py SWITCH, SWITCH_ICON), or the menu would show another button than the game does.

The namespace is cut from the source and compiled with a fixture; no ImGui, Vulkan or game.

    python -I -B tests/test_menu_prompt_icons.py [--cxx g++]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))

import prompt_assets  # noqa: E402 (the Switch code points and each pad input's icon)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    src = (ROOT / "gpu/vk/vk_ui.h").read_text(encoding="utf-8")
    fixture = r'''#include <cstdio>
#include <cstdlib>
enum { HOS_PAD_SOUTH, HOS_PAD_EAST, HOS_PAD_WEST, HOS_PAD_NORTH, HOS_PAD_BACK, HOS_PAD_GUIDE, HOS_PAD_START,
       HOS_PAD_LSTICK, HOS_PAD_RSTICK, HOS_PAD_LSHOULDER, HOS_PAD_RSHOULDER, HOS_PAD_UP, HOS_PAD_DOWN, HOS_PAD_LEFT,
       HOS_PAD_RIGHT, HOS_PAD_LTRIGGER, HOS_PAD_RTRIGGER, HOS_PAD_N };
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
''' + block(src, "namespace prompt_icons {") + r'''
int main() {
    // (the Switch's buttons, in the order nx2/prompt_assets.py SWITCH lists them)
    CHECK(prompt_icons::kA == 0xE040 && prompt_icons::kB == 0xE041);
    CHECK(prompt_icons::kX == 0xE042 && prompt_icons::kY == 0xE043);
    CHECK(prompt_icons::kLS == 0xE056 && prompt_icons::kRS == 0xE057);
    CHECK(prompt_icons::kL == 0xE044 && prompt_icons::kR == 0xE045);
    CHECK(prompt_icons::kZL == 0xE046 && prompt_icons::kZR == 0xE047);
    CHECK(prompt_icons::kPlus == 0xE04B && prompt_icons::kMinus == 0xE04C);
    CHECK(prompt_icons::kLeft == 0xE062 && prompt_icons::kUp == 0xE060);
    CHECK(prompt_icons::kRight == 0xE063 && prompt_icons::kDown == 0xE061);
    CHECK(prompt_icons::kUpDown == 0xE064 && prompt_icons::kLeftRight == 0xE065);
    // (the dot of a face button is its pad input: 0 the top, 1 the right, 2 the left, 3 the bottom)
    CHECK(prompt_icons::dot_pad(0) == HOS_PAD_NORTH && prompt_icons::dot_pad(1) == HOS_PAD_EAST);
    CHECK(prompt_icons::dot_pad(2) == HOS_PAD_WEST && prompt_icons::dot_pad(3) == HOS_PAD_SOUTH);
    std::printf("PASS: the menu's prompt icons are the game's code points\n");
}
'''
    with tempfile.TemporaryDirectory() as d:
        cpp = Path(d) / "prompt_icons.cpp"
        exe = Path(d) / "prompt_icons"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++17", "-O0", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

    # (every pad input's icon, as the build's SWITCH_ICON says)
    pads = prompt_assets.PADS
    switch_icon = prompt_assets.SWITCH_ICON
    fixture = r'''#include <cstdio>
#include <cstdlib>
enum { HOS_PAD_SOUTH, HOS_PAD_EAST, HOS_PAD_WEST, HOS_PAD_NORTH, HOS_PAD_BACK, HOS_PAD_GUIDE, HOS_PAD_START,
       HOS_PAD_LSTICK, HOS_PAD_RSTICK, HOS_PAD_LSHOULDER, HOS_PAD_RSHOULDER, HOS_PAD_UP, HOS_PAD_DOWN, HOS_PAD_LEFT,
       HOS_PAD_RIGHT, HOS_PAD_LTRIGGER, HOS_PAD_RTRIGGER, HOS_PAD_N };
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
''' + block(src, "namespace prompt_icons {") + r'''
int main() {
    const unsigned want[] = {''' + ", ".join("0x%04X" % switch_icon[p] for p in pads) + r'''};
    for (int i = 0; i < HOS_PAD_N; i++) CHECK(prompt_icons::pad(i) == want[i]);
    CHECK(prompt_icons::pad(-1) == 0 && prompt_icons::pad(HOS_PAD_N) == 0);
    std::printf("PASS: each pad input's icon is the game's\n");
}
'''
    with tempfile.TemporaryDirectory() as d:
        cpp = Path(d) / "prompt_pads.cpp"
        exe = Path(d) / "prompt_pads"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++17", "-O0", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

    # (the face fonts nx2/prompt_assets.py writes: one icon per pad input at its PAD_BASE, which the menu reads too)
    assert prompt_assets.PAD_BASE == 0xF700 and len(prompt_assets.PADS) == 17
    ui = (ROOT / "gpu/vk/vk_ui.h").read_text(encoding="utf-8")
    imgui = (ROOT / "gpu/vk/vk_imgui.cpp").read_text(encoding="utf-8")
    if "0xF700 + pad" not in ui or "0xF700, 0xF700 + HOS_PAD_N - 1" not in imgui:
        raise SystemExit("FAIL: the menu and the prompt build disagree on the face font's pad icons")
    print("PASS: the face font's pad icons are at the prompt build's PAD_BASE")


if __name__ == "__main__":
    main()
