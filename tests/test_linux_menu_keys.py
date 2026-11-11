"""On Linux the Insert menu takes its keys from the same queue as on Windows: host/posix/display_sdl.c's keys_update notes
each key on the look it goes down (host/rx_backend.c hos_vk_note_key_press, as host/display.c's WM_KEYDOWN does), once
while it is held, again after it is let go; none while the window is not in front. So the pause menu's Recomp Options
button (host/oot_pause_menu.c), which asks for F1 through that queue, opens the menu on Linux too.

keys_update is cut from the source and compiled with stand-ins for SDL's key state, the window's focus and the queue.

python -I -B tests/test_linux_menu_keys.py [--cc gcc]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cc", "gcc"]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define VK_LBUTTON 1
#define VK_RBUTTON 2
#define VK_MBUTTON 4
#define VK_BACK 8
#define VK_TAB 9
#define VK_RETURN 13
#define VK_SHIFT 16
#define VK_CONTROL 17
#define VK_MENU 18
#define VK_PAUSE 19
#define VK_CAPITAL 20
#define VK_ESCAPE 27
#define VK_SPACE 32
#define VK_PRIOR 33
#define VK_NEXT 34
#define VK_END 35
#define VK_HOME 36
#define VK_LEFT 37
#define VK_UP 38
#define VK_RIGHT 39
#define VK_DOWN 40
#define VK_INSERT 45
#define VK_DELETE 46
#define VK_NUMPAD0 96
#define VK_MULTIPLY 106
#define VK_ADD 107
#define VK_SUBTRACT 109
#define VK_DECIMAL 110
#define VK_DIVIDE 111
#define VK_F1 112
#define VK_LSHIFT 160
#define VK_RSHIFT 161
#define VK_LCONTROL 162
#define VK_RCONTROL 163
#define VK_LMENU 164
#define VK_RMENU 165
#define VK_OEM_1 186
#define VK_OEM_PLUS 187
#define VK_OEM_COMMA 188
#define VK_OEM_MINUS 189
#define VK_OEM_PERIOD 190
#define VK_OEM_2 191
#define VK_OEM_3 192
#define VK_OEM_4 219
#define VK_OEM_5 220
#define VK_OEM_6 221
#define VK_OEM_7 222
volatile uint8_t hos_posix_keys[256];
volatile int hos_posix_window[4];
static uint8_t sdl[512];
static const uint8_t *hos_sdl_keys(int *n) { *n = (int)sizeof sdl; return sdl; }
static uint32_t hos_sdl_mouse_buttons(void) { return 0; }
static int noted[256];
void hos_vk_note_key_press(unsigned key) { if (key < 256) noted[key]++; }
%s
static int fails;
#define CHECK(c, what) do { if (!(c)) { printf("FAIL: %%s\n", what); fails++; } } while (0)
int main(void) {
    const int f1 = 58;   /* (SDL's scancode for F1) */
    hos_posix_window[0] = 1;
    sdl[f1] = 1;
    keys_update();
    CHECK(noted[VK_F1] == 1, "F1 going down is not noted once");
    CHECK(hos_posix_keys[VK_F1] == 1, "F1 held is not in the key state");
    keys_update();
    keys_update();
    CHECK(noted[VK_F1] == 1, "F1 held is noted again");
    sdl[f1] = 0;
    keys_update();
    sdl[f1] = 1;
    keys_update();
    CHECK(noted[VK_F1] == 2, "F1 pressed again is not noted");
    sdl[f1] = 0;
    keys_update();
    hos_posix_window[0] = 0;
    sdl[f1] = 1;
    keys_update();
    CHECK(noted[VK_F1] == 2, "a key is noted while the window is not in front");
    CHECK(hos_posix_keys[VK_F1] == 0, "a key is in the state while the window is not in front");
    if (!fails) printf("PASS: Linux keys reach the Insert menu's queue on their way down, once\n");
    return fails != 0;
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    sdl = (ROOT / "host" / "posix" / "display_sdl.c").read_text(encoding="utf-8")
    rx = (ROOT / "host" / "rx_backend.c").read_text(encoding="utf-8")
    if "void hos_vk_note_key_press(unsigned key) {" not in rx or "#define host_take_key_press NULL" in rx:
        raise SystemExit("FAIL: the Insert menu's key queue is not on every platform (host/rx_backend.c)")
    with tempfile.TemporaryDirectory() as d:
        src, exe = Path(d) / "fixture.c", Path(d) / "fixture.exe"
        src.write_text(FIXTURE % block(sdl, "static void keys_update(void) {"), encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Werror", "-Wno-unused-function", str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout, end="")
        if r.returncode:
            sys.exit(1)


if __name__ == "__main__":
    main()
