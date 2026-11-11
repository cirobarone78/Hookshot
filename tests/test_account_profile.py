"""The game's user is the launcher's profile: HOOKSHOT_PROFILE=<32 hex digits> is the save folder's name (save/<digits>)
while the profile is on the launcher's list (profiles.txt in the user folder), and anything else plays the default
profile, the user every build had before profiles.

This builds host/nn_applet.c's user_uid and hos_account_init as they are in the source, with nn_fs.c's folder naming,
and checks which save folder each value leads to.

python -I -B tests/test_account_profile.py [--cc gcc]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = "5a3c9e1f0b7d24680000000000000001"   # (nx2/profiles.py's DEFAULT)

HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#define MAX_PATH 260
#define _strnicmp strncasecmp
static void hos_log(const char *f, ...) { (void)f; }
const char *hos_user_dir;
void hos_account_init(void);
%s
int main(int argc, char **argv) {
    hos_user_dir = argc > 1 ? argv[1] : NULL;
    hos_account_init();
    /* (host/nn_fs.c's MountSaveData: the uid's second word, then its first) */
    printf("%%016llx%%016llx\n", (unsigned long long)user_uid[1], (unsigned long long)user_uid[0]);
    return 0;
}
'''


def source():
    text = (ROOT / "host" / "nn_applet.c").read_text(encoding="utf-8")
    start = text.index("extern const char *hos_user_dir;")
    end = text.index("HLE(_ZN2nn7account10InitializeEv)", start)
    return text[start:end]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="cc")
    args = ap.parse_args()
    failures = 0
    with tempfile.TemporaryDirectory(prefix="hookshot-account-") as tmp:
        c, exe = Path(tmp) / "t.c", Path(tmp) / "t"
        c.write_text(HARNESS % source(), encoding="utf-8")
        user = Path(tmp) / "user"
        user.mkdir()
        # (as profiles.py writes it, with a hand edit or two: the case of an id, a line with no name, a long name)
        (user / "profiles.txt").write_text(
            "# Hookshot's profiles\n5a3c9e1f0b7d24680000000000000002 Link\n45eb517681bceaf4b834e0fa511e3212\n"
            "5a3c9e1f0b7d24680000000000000005 %s\n# 5a3c9e1f0b7d24680000000000000004 Gone\n"
            "5A3C9E1F0B7D24680000000000000006 Zelda" % ("x" * 300), encoding="utf-8")
        subprocess.run([args.cc, "-D_DEFAULT_SOURCE", "-std=c11", "-Wall", "-Wextra", "-Werror", "-o", str(exe), str(c)], check=True)
        cases = {
            None: DEFAULT,
            "": DEFAULT,
            "5a3c9e1f0b7d24680000000000000002": "5a3c9e1f0b7d24680000000000000002",
            "45EB517681BCEAF4B834E0FA511E3212": "45eb517681bceaf4b834e0fa511e3212",
            "0" * 32: DEFAULT,
            "5a3c9e1f0b7d2468000000000000002": DEFAULT,   # (31 digits)
            "5a3c9e1f0b7d24680000000000000002x": DEFAULT,
            "../../../../../../etc/passwd/xx": DEFAULT,
            DEFAULT.upper(): DEFAULT,
            "5a3c9e1f0b7d24680000000000000003": DEFAULT,   # (not on the list: removed, or another user folder's)
            "5a3c9e1f0b7d24680000000000000004": DEFAULT,   # (a comment is no line of the list)
            "5a3c9e1f0b7d24680000000000000005": "5a3c9e1f0b7d24680000000000000005",
            "5a3c9e1f0b7d24680000000000000006": "5a3c9e1f0b7d24680000000000000006",
        }
        for value, want in cases.items():
            env = {k: v for k, v in os.environ.items() if k != "HOOKSHOT_PROFILE"}
            if value is not None:
                env["HOOKSHOT_PROFILE"] = value
            got = subprocess.run([str(exe), str(user)], env=env, capture_output=True, text=True, check=True).stdout.strip()
            ok = got == want
            failures += not ok
            print("%s HOOKSHOT_PROFILE=%r: save/%s%s" % ("PASS" if ok else "FAIL", value, got, "" if ok else " (want %s)" % want))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
