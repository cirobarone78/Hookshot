"""The virtual amiibo: nn::nfp's tag data and the figures a scan can present.

host/nfp_amiibo.h holds the layouts the game reads (TagInfo 0x58, RegisterInfo 0x100, CommonInfo 0x40,
ModelInfo 0x40) and the profile table; host/nn_nfp.c answers nn::nfp's free functions from it. The header is
compiled alone and checked against those offsets, the ids and the effects, and the host file is checked for the
functions the game imports.

python -I -B tests/test_amiibo.py [--cc clang]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''
#include "nfp_amiibo.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    uint8_t id[8], model[NFP_MODEL_INFO_SIZE], tag[NFP_TAG_INFO_SIZE], common[NFP_COMMON_INFO_SIZE],
        reg[NFP_REGISTER_INFO_SIZE], uid[10];
    int len;

    /* Link - Ocarina of Time: character 010000, numbering 034b, series 09 */
    assert(nfp_parse_id("0x01000000034b0902", id));
    assert(id[0] == 0x01 && id[1] == 0x00 && id[2] == 0x00 && id[3] == 0x00);
    assert(id[4] == 0x03 && id[5] == 0x4b && id[6] == 0x09 && id[7] == 0x02);
    assert(nfp_parse_id("01000000034b0902", id));
    assert(!nfp_parse_id("01000000034b090", id));
    assert(!nfp_parse_id("01000000034b090z", id));
    assert(nfp_profile_by_key("link-oot") != NULL);
    assert(nfp_profile_by_key("LINK-OOT") == nfp_profile_by_key("link-oot"));
    assert(nfp_profile_by_index(nfp_amiibo_count) == NULL);
    assert(nfp_profile_by_key("no-such-figure") == NULL);

    nfp_model_info_from_id(id, model);
    assert(model[0] == 0x01 && model[1] == 0x00 && model[2] == 0x00);
    assert(model[3] == 0x09);                        /* seriesId */
    assert(model[4] == 0x4b && model[5] == 0x03);    /* numberingId 0x034b, little-endian uint16_t */
    assert(model[6] == 0x00);                        /* nfpType */
    assert(model[7] == 0 && model[63] == 0);

    nfp_tag_info_from_uid((const uint8_t *)"ABCDEFG", 7, tag);
    assert(tag[0] == 'A' && tag[6] == 'G' && tag[10] == 7);
    assert(tag[32] == 1 && tag[36] == 2);            /* NFC-A / TYPE2 */
    assert(tag[31] == 0 && tag[87] == 0);

    nfp_common_info(common, 2026, 11, 9);
    assert(common[0] == 0xEA && common[1] == 0x07);
    assert(common[2] == 11 && common[3] == 9);
    assert(common[6] == 1);
    assert(common[8] == 0xD8 && common[9] == 0 && common[10] == 0 && common[11] == 0);

    nfp_register_info(reg, "Young Link", 2026, 11, 9);
    assert(reg[0x58] == 0xEA && reg[0x59] == 0x07);
    assert(reg[0x5A] == 11 && reg[0x5B] == 9);
    assert(reg[0x5C] == 'Y' && reg[0x65] == 'k' && reg[0x66] == 0);
    assert(reg[0x85] == 0);

    nfp_uid_from_id(id, uid, &len);
    assert(len == 7);

    assert(nfp_effect_from_id(id)[0] == 'a');
    assert(nfp_profile_by_key("mario")->zelda == 0);
    assert(nfp_profile_by_key("oot-young-link")->effect[0] == 'M');
    assert(nfp_profile_by_key("oot-young-zelda")->effect[0] == 'M');
    puts("nfp_amiibo.h ok");
    return 0;
}
'''


def find_cc(explicit):
    if explicit:
        return explicit
    for name in ("cc", "gcc", "clang", "cc.exe", "gcc.exe", "clang.exe"):
        found = shutil.which(name)
        if found:
            return found
    mingw = os.environ.get("HOOKSHOT_MINGW")
    if mingw:
        for name in ("clang.exe", "gcc.exe", "clang", "gcc"):
            path = Path(mingw) / "bin" / name
            if path.exists():
                return str(path)
    return None


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default=None)
    a = p.parse_args()

    header = (ROOT / "host" / "nfp_amiibo.h").read_text(encoding="utf-8")
    host = (ROOT / "host" / "nn_nfp.c").read_text(encoding="utf-8")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    menu_h = (ROOT / "gpu" / "vk" / "vk_menu.h").read_text(encoding="utf-8")
    readme = (ROOT / "readme.md").read_text(encoding="utf-8")

    for symbol in (
        "_ZN2nn3nfp10InitializeEv",
        "_ZN2nn3nfp14StartDetectionERKNS0_12DeviceHandleE",
        "_ZN2nn3nfp5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE",
        "_ZN2nn3nfp10GetTagInfoEPNS0_7TagInfoERKNS0_12DeviceHandleE",
        "_ZN2nn3nfp9GetNpadIdEPjRKNS0_12DeviceHandleE",
        "_ZN2nn3nfp15GetRegisterInfoEPNS0_12RegisterInfoERKNS0_12DeviceHandleE",
        "_ZN2nn3nfp13GetCommonInfoEPNS0_10CommonInfoERKNS0_12DeviceHandleE",
        "_ZN2nn3nfp12GetModelInfoEPNS0_9ModelInfoERKNS0_12DeviceHandleE",
        # the SDK spellings the game imports: unsigned long, not unsigned long long
        "_ZN2nn3nfp18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm",
        "_ZN2nn3nfp18SetApplicationAreaERKNS0_12DeviceHandleEPKvm",
    ):
        check("HLE(" + symbol + ")" in host, "nn_nfp.c has no " + symbol)
    detect = host[host.index("_ZN2nn3nfp14StartDetection"):]
    check("nfp_device_state = NFP_DEV_SEARCH;" in detect and "nfp_scan_pending = 1;" in detect,
          "StartDetection does not start a scan")
    check("nfp_poll_scan();" in detect, "the tag never appears after StartDetection")
    check("HOS_AMIIBO" in host and "HOS_AMIIBO_RANDOM_UID" in host, "nn_nfp.c has no amiibo switches")
    check("amiibo" in host and "nfp_ini_text" in host, "nn_nfp.c does not read amiibo= from the ini")
    check("int amiibo = 0;" in menu_h, "vk_menu.h has no amiibo option")
    check('"Amiibo"' in menu and "&opts.amiibo" in menu, "vk_menu.cpp has no Amiibo row")
    check("HOS_AMIIBO" in readme, "readme.md does not describe the Amiibo row")

    for key in ("link-oot", "zelda-botw", "young-link", "young-zelda", "oot-young-link", "oot-young-zelda", "mario"):
        check('"' + key + '"' in header, "nfp_amiibo.h has no " + key + " profile")
    check("Mask 101" in header and "Mask 102" in header, "the two Ocarina of Time mask effects are missing")
    check("0x03, 0x4b, 0x09, 0x02" in header, "Link - Ocarina of Time's id is missing")

    cc = find_cc(a.cc)
    if not cc:
        print("SKIP: no C compiler (gcc, clang or HOOKSHOT_MINGW)")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "nfp_amiibo.c"
        src.write_text(FIXTURE, encoding="utf-8")
        exe = Path(tmp) / "nfp_amiibo.exe"
        subprocess.run([cc, "-std=c11", "-Wall", "-Werror", "-I", str(ROOT / "host"), "-o", str(exe), str(src)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        check(r.returncode == 0, "nfp_amiibo.h fixture: " + r.stderr.strip())
    print("PASS: virtual amiibo layouts, ids and effects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
