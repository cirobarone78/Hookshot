"""The Insert menu's Keyboard row: Auto, On or Off.

Steam Input's Desktop layout sends a pad's stick and buttons to a focused window as key presses (left stick to the
arrow keys, A to Enter, View to Tab, Menu to Escape). With the keyboard's controls read as the game's, walking moved
the camera and View and Menu both pressed Plus on a Steam Deck in Desktop Mode. Auto (the default) counts the
keyboard's bindings only while no controller is connected; On and Off force them.

key() and keyboard_counts() are extracted unmodified from host/nn_hid.c; the option, keyboard and pad-count APIs are
fakes. No device, desktop or game is accessed.

python -I -B tests/test_keyboard_option.py [--cc gcc]
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]
ENV_ON_H = str(ROOT / "gpu" / "vk" / "compat" / "hookshot_env.h")

# (name, menu open, the row's value, a controller is connected, the key is down, a mouse button, expected)
CASES = (
    ("auto-no-pad-key-down", 0, 0, 0, 1, 0, 1),
    ("auto-pad-key-down", 0, 0, 1, 1, 0, 0),
    ("auto-pad-mouse-button", 0, 0, 1, 0, 1, 1),
    ("on-no-pad", 0, 1, 0, 1, 0, 1),
    ("on-pad", 0, 1, 1, 1, 0, 1),
    ("off-no-pad", 0, 2, 0, 1, 0, 0),
    ("off-pad", 0, 2, 1, 1, 0, 0),
    ("off-menu-open", 1, 2, 0, 1, 0, 0),
    ("auto-menu-open", 1, 0, 0, 1, 0, 0),
    ("auto-key-up", 0, 0, 0, 0, 0, 0),
)


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
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")

    # The row, its options-file key and the host's view of it
    if '"Keyboard", &opts.keyboard' not in menu:
        raise SystemExit("the Insert menu has no Keyboard row")
    if "int keyboard" not in (ROOT / "gpu" / "vk" / "vk_menu.h").read_text(encoding="utf-8"):
        raise SystemExit("opts.keyboard is not declared")
    if "HOS_OPT_KEYBOARD" not in api:
        raise SystemExit("HOS_OPT_KEYBOARD is not declared")
    option = replay[replay.index("t.option = "):]
    option = option[:option.index("};") + 2]
    if "id == HOS_OPT_KEYBOARD) return opts.keyboard" not in option:
        raise SystemExit("the host cannot see the Keyboard row")
    if "ini_key" in menu and re.search(r'if \(r\.value == &opts\.keyboard\) return', menu):
        raise SystemExit("the Keyboard row's key should be its name's: keyboard")

    key = block(hid, "static int key(")
    counts = block(hid, "static int keyboard_counts(")
    if "pad_count_now" not in counts:
        raise SystemExit("Auto does not look at whether a controller is connected")
    if "HOS_OPT_KEYBOARD" not in counts:
        raise SystemExit("the keyboard's controls do not consult the Keyboard row")
    if "VK_LBUTTON" not in counts and "0x01" not in counts:
        raise SystemExit("a mouse button is treated as the keyboard's")

    constants = """\
#include <stdint.h>
typedef int LONG;
typedef short SHORT;
enum { HOS_OPT_KEYBOARD = %s };
static volatile LONG pad_count_now;
static int menu_open, keyboard_mode, key_down, mouse_button;
int rx_option(int id, int otherwise) {
    if (id == 1) return menu_open;
    if (id == HOS_OPT_KEYBOARD) return keyboard_mode;
    return otherwise;
}
SHORT GetAsyncKeyState(int vk) {
    const int button = vk >= 0x01 && vk <= 0x06 && vk != 0x03;
    return (button ? mouse_button : key_down) ? (SHORT)0x8000 : 0;
}
""" % re.search(r"HOS_OPT_KEYBOARD\s*=\s*(\d+)", api).group(1)

    body = constants + counts + "\n" + key + """
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    if (argc != 6) return 2;
    keyboard_mode = atoi(argv[1]);
    menu_open = atoi(argv[2]);
    pad_count_now = atoi(argv[3]);
    key_down = atoi(argv[4]);
    mouse_button = atoi(argv[5]);
    printf("%d\\n", key(mouse_button ? 0x01 : 0x26));   /* (VK_LBUTTON, or VK_UP: a camera key) */
    return 0;
}
"""
    with tempfile.TemporaryDirectory(prefix="keyboard-option-") as tmp:
        folder = Path(tmp).resolve()
        src = folder / "fixture.c"
        src.write_text(body, encoding="utf-8")
        exe = folder / "fixture.exe"
        build = subprocess.run([a.cc, "-std=c11", "-include", ENV_ON_H, "-Wall", "-Wextra", "-Werror",
                                str(src), "-o", str(exe)], capture_output=True, text=True)
        sys.stdout.write(build.stdout)
        sys.stderr.write(build.stderr)
        build.check_returncode()
        for name, menu_open_, mode, pads, down, mouse, want in CASES:
            got = subprocess.run([str(exe), str(mode), str(menu_open_), str(pads), str(down), str(mouse)],
                                 capture_output=True, text=True)
            got.check_returncode()
            value = int(got.stdout.strip())
            if value != want:
                raise SystemExit("FAIL %s: key() = %d, want %d" % (name, value, want))
    print("keyboard option: %d cases pass" % len(CASES))


if __name__ == "__main__":
    main()
