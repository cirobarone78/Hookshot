"""The Insert menu's Volume row scales what the game plays (host/nn_audio.c au_volume_gain, au_volume_apply).

The menu's row (Gameplay, 0 to 100 in steps of 5, a slider that stops at its ends, applied at once, left alone by the
Quality preset), the renderer's answer for HOS_OPT_VOLUME and the mixer's call are checked in the sources; the real
au_volume_gain and au_volume_apply from host/nn_audio.c are compiled on their own and run: 100% leaves the samples as
they are, 0% silences them, 50% is -12 dB, and a change ramps over one frame instead of jumping (a click).

python -I -B tests/test_audio_volume.py [--cc gcc]
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <assert.h>
#include <math.h>
#include <stdio.h>
#define FRAME 240
SECTION
static float out[2][FRAME];
static void fill(float v) { for (int i = 0; i < FRAME; i++) out[0][i] = out[1][i] = v; }
static int near(float a, float b) { return fabsf(a - b) < 1e-5f; }
int main(void) {
    assert(au_volume_gain(100) == 1.0f && au_volume_gain(150) == 1.0f);
    assert(au_volume_gain(0) == 0.0f && au_volume_gain(-5) == 0.0f);
    assert(near(au_volume_gain(50), 0.25f) && near(au_volume_gain(25), 0.0625f));
    for (int p = 0; p < 100; p += 5) assert(au_volume_gain(p) < au_volume_gain(p + 5));   /* (each step louder) */
    /* the first frame at its gain at once: no fade in at the start */
    fill(1.0f);
    au_volume_apply(out, 2, 50);
    assert(near(out[0][0], 0.25f) && near(out[1][FRAME - 1], 0.25f));
    /* unchanged: the same gain all through */
    fill(1.0f);
    au_volume_apply(out, 2, 50);
    for (int i = 0; i < FRAME; i++) assert(near(out[0][i], 0.25f) && near(out[1][i], 0.25f));
    /* up to 100: a ramp from the last gain, reaching the new one at the frame's end, never past it */
    fill(1.0f);
    au_volume_apply(out, 2, 100);
    assert(out[0][0] > 0.25f && out[0][0] < 0.26f && near(out[0][FRAME - 1], 1.0f));
    for (int i = 1; i < FRAME; i++) assert(out[0][i] >= out[0][i - 1] && out[0][i] <= 1.0f && out[1][i] == out[0][i]);
    /* at 100 the samples are left as they are */
    for (int i = 0; i < FRAME; i++) out[0][i] = out[1][i] = (float)i / FRAME - 0.5f;
    au_volume_apply(out, 2, 100);
    for (int i = 0; i < FRAME; i++) assert(out[0][i] == (float)i / FRAME - 0.5f);
    /* down to muted: ramps to silence */
    fill(1.0f);
    au_volume_apply(out, 2, 0);
    assert(out[0][0] > 0.99f && out[0][FRAME - 1] == 0.0f);
    for (int i = 1; i < FRAME; i++) assert(out[0][i] <= out[0][i - 1]);
    fill(1.0f);
    au_volume_apply(out, 2, 0);
    for (int i = 0; i < FRAME; i++) assert(out[0][i] == 0.0f && out[1][i] == 0.0f);
    puts("ok");
    return 0;
}
"""


def between(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()

    audio = (ROOT / "host/nn_audio.c").read_text(encoding="utf-8")
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    header = (ROOT / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")

    # (tab, name, value, lo, hi, step, text, help, then hint, restart, preset_exempt)
    row = re.search(r'\{TAB_(\w+), "Volume", &opts\.volume, (-?\d+), (-?\d+), (\d+), (\w+),\s*"[^{}]*?", '
                    r'(\w+), (true|false), (true|false)\},', menu)
    assert row, "the Insert menu has no Volume row"
    assert row.groups() == ("GAMEPLAY", "0", "100", "5", "tx_volume", "nullptr", "false", "true"), row.groups()
    assert re.search(r"int volume = 100;", header), "opts.volume is not 100 (the game's own) by default"
    assert re.search(r"bool is_slider\(const Row& r\) \{[^}]*&opts\.volume", menu), "the Volume row is not a slider"
    assert re.search(r"bool stops_at_ends\(const Row& r\) \{[^}]*&opts\.volume", menu), \
        "the Volume row wraps from 100 to Muted"
    assert re.search(r"HOS_OPT_DISCORD, HOS_OPT_VOLUME \}", api), "no HOS_OPT_VOLUME after HOS_OPT_DISCORD"
    # (an id the renderer does not answer is 0: the game would be silent)
    assert "if (id == HOS_OPT_VOLUME) return std::clamp(opts.volume, 0, 100);" in replay, \
        "the renderer does not answer HOS_OPT_VOLUME"
    render = between(audio, "static void render_frame(", "\n}\n")
    call = render.find("au_volume_apply(out, nch, rx_option(HOS_OPT_VOLUME, 100));")
    assert call >= 0, "render_frame does not apply the Volume"
    assert render.find("lim_env") < call < render.find("* 32767.0f"), \
        "the Volume is not applied after the limiter and before the samples are made"

    section = between(audio, "static float au_volume_gain(int percent) {", "static void render_frame(")
    with tempfile.TemporaryDirectory(prefix="audio-volume-") as tmp:
        work = Path(tmp)
        source, exe = work / "fixture.c", work / "fixture.exe"
        source.write_text(FIXTURE.replace("SECTION", section), encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(exe), "-lm"],
                       check=True)
        subprocess.run([str(exe)], check=True, capture_output=True)
    print("PASS: Volume: a Gameplay slider, 0 to 100; 100% leaves the sound as it is, 0% silences it, changes ramp over "
          "a frame")


if __name__ == "__main__":
    main()
