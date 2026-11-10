"""Execute the generated HUD projection patch for wide and narrow displays."""
import argparse
import runpy
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    hud = runpy.run_path(str(ROOT / "nx2" / "oot_wide.py"))["HUD"]
    fixture = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct { uint64_t x[32]; unsigned char vreg[32][16]; } Ctx;
volatile float hos_wide_squeeze, hos_wide_vertical_squeeze;
volatile uint32_t hos_wide_keep_mask;
static uint64_t recomp_load64(Ctx *c, uint64_t address) { (void)address; return c->x[1]; }
static void patch(Ctx *c) {
/* WIDE_HUD_PATCH */
}
static void matrix(Ctx *c) {
    const float x[4] = {2.0f / 3840.0f, 0.0f, 0.0f, 1.0f};
    const float y[4] = {2.0f / 2160.0f, 0.0f, 0.0f, 1.0f};
    memcpy(c->vreg[1], x, sizeof x);
    memcpy(c->vreg[4] + 4, y, sizeof y);
}
static int close_to(float a, float b) { return a > b - 0.00001f && a < b + 0.00001f; }
int main(void) {
    Ctx c = {0};
    float x[4], y[4];
    matrix(&c);
    hos_wide_squeeze = 1.0f;
    hos_wide_vertical_squeeze = 0.75f;
    patch(&c);
    memcpy(y, c.vreg[4] + 4, sizeof y);
    if (!close_to(y[0], (2.0f / 2160.0f) * 0.75f) || !close_to(y[3], 0.75f)) return 1;
    matrix(&c);
    hos_wide_squeeze = 0.75f;
    hos_wide_vertical_squeeze = 1.0f;
    patch(&c);
    memcpy(x, c.vreg[1], sizeof x);
    memcpy(y, c.vreg[4] + 4, sizeof y);
    if (!close_to(x[0], (2.0f / 3840.0f) * 0.75f) || !close_to(x[3], 0.75f)) return 2;
    if (!close_to(y[0], 2.0f / 2160.0f) || !close_to(y[3], 1.0f)) return 3;
    puts("PASS: HUD proportions stay 16:9 on narrow and wide screens");
    return 0;
}
'''.replace("/* WIDE_HUD_PATCH */", hud)
    with tempfile.TemporaryDirectory(prefix="widescreen-hud-") as tmp:
        source, exe = Path(tmp) / "fixture.c", Path(tmp) / "fixture"
        source.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
