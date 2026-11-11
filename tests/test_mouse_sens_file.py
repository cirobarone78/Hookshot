"""The mouse sensitivity read from <user>/mouse_sens.txt or HOS_MOUSE_SENS is a finite number kept to the menu's range.

host/nn_hid.c mouse_setup takes the sensitivity kept in mouse_sens.txt (saves can come from elsewhere) and moves it into
the menu's option with lround(). "inf", "nan" or "1e999" went on as an undefined number. Cuts mouse_setup out of the
source as it is and checks that such values leave the default, and that a value past the menu's 0.1-5 is kept to it.

python -I -B tests/test_mouse_sens_file.py [--cc gcc]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r'''#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "HOS_FOPEN_READ_H"
#include "HOOKSHOT_ENV_H"   /* (env_on) */
static double hos_mouse_sens;
static const char *hos_user_dir;
static int invert = -1, sens_from_file;
%s
int main(int argc, char **argv) {
    hos_user_dir = argv[1];
#ifdef _WIN32
    if (argc > 2) _putenv_s("HOS_MOUSE_SENS", argv[2]);
#else
    if (argc > 2) setenv("HOS_MOUSE_SENS", argv[2], 1);
#endif
    mouse_setup();
    (void)sens_from_file;
    printf("%%.3f\n", hos_mouse_sens);
    return !(isfinite(hos_mouse_sens) && hos_mouse_sens >= 0.1 && hos_mouse_sens <= 5);
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
    fn = block(src, "static void mouse_setup(void) {")
    bad = []
    with tempfile.TemporaryDirectory(prefix="mouse-sens-") as tmp:
        tmp = Path(tmp)
        c = tmp / "f.c"
        c.write_text((FIXTURE % fn).replace("HOS_FOPEN_READ_H", (ROOT / "host" / "hos_fopen_read.h").as_posix())
                     .replace("HOOKSHOT_ENV_H", (ROOT / "gpu" / "vk" / "compat" / "hookshot_env.h").as_posix()),
                     encoding="utf-8")
        exe = tmp / ("f.exe" if sys.platform == "win32" else "f")
        subprocess.run([a.cc, "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Wno-unused-function", str(c), "-o",
                        str(exe), "-lm"], check=True)
        for text, env, want in (("1.5", None, 1.5), ("inf", None, 1.0), ("nan", None, 1.0), ("1e999", None, 1.0),
                                ("40", None, 5.0), ("0.01", None, 0.1), ("1.5", "inf", 1.5), ("1.5", "2", 2.0)):
            (tmp / "mouse_sens.txt").write_text(text + "\n", encoding="ascii")
            r = subprocess.run([str(exe), str(tmp)] + ([env] if env else []), capture_output=True, text=True, timeout=30)
            got = r.stdout.strip()
            if r.returncode or abs(float(got) - want) > 1e-6:
                bad.append("mouse_sens.txt %r, HOS_MOUSE_SENS %r: %s (want %.3f)" % (text, env, got, want))
    if bad:
        sys.exit("FAIL: " + "; ".join(bad))
    print("PASS: the mouse sensitivity from mouse_sens.txt or HOS_MOUSE_SENS is finite and within the menu's 0.1-5")


if __name__ == "__main__":
    main()
