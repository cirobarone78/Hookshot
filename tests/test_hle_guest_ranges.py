"""HLE functions that read or write a span the game names check that it lies in guest memory (host/hos.h hos_guest_range).

GP() turns a guest address into a host pointer without a check, and a size from the game walks a copy past the guest
window into the host's own memory. A save or a mod's data can lead the game to odd pointers or sizes. These functions
now take only spans that lie in the window:

- nn::audio's wave buffers (AppendWaveBuffer) and ADPCM coefficients (AcquireVoiceSlot): the mixer read their data for as
  long as the voice played, so the host's memory went into the sound. Checked here by running wb_in_guest itself;
- nn::os::GenerateRandomBytes, nn::hid's GetNpadStates (at most 16 states) and GetSixAxisSensorStates, the socket Poll
  stand-in, OutputDebugString and nn::diag's log lines (into the log), and the event-name and item-key copies in
  host/hos_main.c and host/oot_menu.c: their text checked to use hos_guest_range on the whole span.
- the NVN proc names the game asks for (nvnDeviceGetProcAddress, nvnBootstrapLoader): read by guest_name only inside
  guest memory and up to 255 characters, run here.

python -I -B tests/test_hle_guest_ranges.py [--cc gcc]
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


def host(name):
    return (ROOT / "host" / name).read_text(encoding="utf-8")


# (file, the function's first line, text it must hold, text it must not)
SOURCES = [
    ("nn_os_sync.c", "HLE(_ZN2nn2os19GenerateRandomBytesEPvm)", "hos_guest_range(ARG(0), ARG(1))", "GP(ARG(0))"),
    ("nn_hid.c", "static void npad_states(Ctx *c)", "hos_guest_range(out, (uint64_t)count * STATE_SIZE)", "int count = (int)ARG(1);"),
    ("nn_hid.c", "HLE(_ZN2nn3hid22GetSixAxisSensorStatesEPNS0_18SixAxisSensorStateEiRKNS0_19SixAxisSensorHandleE)",
     "hos_guest_range(out, (uint64_t)count * 0x60)", None),
    ("nn_applet.c", "static void socket_poll(Ctx *c)", "hos_guest_range(fds, 8 * m)", None),
    ("hos_main.c", "static int oot_event_arg(", "hos_guest_range(name_buf, length + 1)", "A64_PTR(name_buf)"),
    ("oot_menu.c", "static int set_item_key(", "hos_guest_range(buf, n + 1)", "buf + n + 1 > HOS_GUEST_SPACE"),
    ("nn_diag.c", "HLE(_ZN2nn4diag6detail7PutImplERKNS0_11LogMetaDataEPKcm)", "hos_guest_range(ARG(1), n)", "GP(ARG(1))"),
    ("nn_audio.c", "HLE(_ZN2nn5audio16AppendWaveBufferEPNS0_9VoiceTypeEPKNS0_10WaveBufferE)", "wb_in_guest(&checked)", None),
    ("nvn_native.c", "NV(nvnDeviceGetProcAddress)", "guest_name(U64(1), name, sizeof name)", "GP(U64(1))"),
    ("nvn_native.c", "HLE(nvnBootstrapLoader)", "guest_name(ARG(0), name, sizeof name)", "GP(ARG(0))"),
]

NAME_FIXTURE = r'''#include <stdint.h>
#include <stdio.h>
#include <string.h>
static uint8_t window[0x1000];
#define HOS_SPACE_END 0x1000ull
#define GP(a) ((void *)(window + (a)))
static inline void *hos_guest_range(uint64_t a, uint64_t n) { return a < HOS_SPACE_END && n <= HOS_SPACE_END - a ? GP(a) : (void *)0; }
%s
int main(void) {
    char out[256];
    strcpy((char *)window + 0x10, "nvnDeviceInitialize");
    memset(window + 0x800, 'x', 0x800);                     /* (no end before the window's) */
    memset(window + 0x100, 'y', 300), window[0x100 + 300] = 0;   /* (longer than a name) */
    const int ok = !strcmp(guest_name(0x10, out, sizeof out), "nvnDeviceInitialize") && !*guest_name(0x800, out, sizeof out) &&
                   !*guest_name(0x100, out, sizeof out) && !*guest_name(0x5000, out, sizeof out) && !*guest_name(0, out, sizeof out) &&
                   !strcmp(guest_name(0xFF0, out, sizeof out), "") ;
    puts(ok ? "PASS: a proc name is read only inside guest memory and up to its 255 characters" : "FAIL: guest_name");
    return !ok;
}
'''

FIXTURE = r'''#include <stdint.h>
#include <stdio.h>
#include <string.h>
static uint8_t window[0x10000];
#define SPACE 0x10000ull
#define GP(a) ((void *)(window + (a)))
static inline void *hos_guest_range(uint64_t a, uint64_t n) { return a < SPACE && n <= SPACE - a ? GP(a) : (void *)0; }
typedef struct { uint64_t buffer, size; int32_t start, end; int loop; uint64_t context; } WB;
''' + "%s" + r'''
int main(void) {
    const WB inside = {0x1000, 0x800, 0, 0, 0, 0}, with_context = {0x1000, 0x800, 0, 0, 0, 0x2000};
    const WB past = {0xF000, 0x2000, 0, 0, 0, 0}, wraps = {0x1000, ~0ull - 0x800, 0, 0, 0, 0};
    const WB far = {0x100000000ull, 0x10, 0, 0, 0, 0}, bad_context = {0x1000, 0x10, 0, 0, 0, 0xFFFE};
    const int ok = wb_in_guest(&inside) && wb_in_guest(&with_context) && !wb_in_guest(&past) && !wb_in_guest(&wraps) &&
                   !wb_in_guest(&far) && !wb_in_guest(&bad_context);
    puts(ok ? "PASS: a wave buffer is taken only when its data and context lie in guest memory" : "FAIL: wb_in_guest");
    return !ok;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    bad = []
    for name, marker, must, must_not in SOURCES:
        text = host(name)
        if marker not in text:
            bad.append("%s: %s is gone (update this check)" % (name, marker))
            continue
        fn = block(text, marker)
        if must not in fn:
            bad.append("%s %s: no %s" % (name, marker.split("(")[0], must))
        if must_not and must_not in fn:
            bad.append("%s %s: still %s" % (name, marker.split("(")[0], must_not))
    svc = host("hos_svc.c")
    debug = svc[svc.index("case 0x27: { /* OutputDebugString(str, size) */"):]
    debug = debug[:debug.index("return;")]
    if "hos_guest_range(c->x[0], n)" not in debug:
        bad.append("hos_svc.c OutputDebugString: no hos_guest_range(c->x[0], n)")
    audio = host("nn_audio.c")
    acquire = audio[audio.index("v->param = ARG(6);"):]
    if "hos_guest_range(v->param, 32)" not in acquire[:acquire.index("\n", acquire.index("v->coefs"))]:
        bad.append("nn_audio.c AcquireVoiceSlot: the coefficients are copied from an unchecked pointer")
    if bad:
        sys.exit("\n".join(bad))
    print("PASS: %d HLE functions check the spans they read or write" % (len(SOURCES) + 2))
    if "static int wb_in_guest(const WB *w) {" not in audio:
        sys.exit("nn_audio.c: no wb_in_guest")
    with tempfile.TemporaryDirectory(prefix="hle-ranges-") as tmp:
        tmp = Path(tmp)
        (tmp / "f.c").write_text(FIXTURE % block(audio, "static int wb_in_guest(const WB *w) {"), encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Werror", str(tmp / "f.c"), "-o", str(tmp / "f")], check=True)
        subprocess.run([str(tmp / "f")], check=True)
        nvn = host("nvn_native.c")
        (tmp / "n.c").write_text(NAME_FIXTURE % block(nvn, "static const char *guest_name("), encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Werror", str(tmp / "n.c"), "-o", str(tmp / "n")], check=True)
        subprocess.run([str(tmp / "n")], check=True)


if __name__ == "__main__":
    main()
