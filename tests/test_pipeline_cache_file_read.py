"""A pipeline cache file is read only when its header is this device's, and never past kPcacheMax (gpu/vk/vk_draw.cpp).

mkw_vk_pipelines.bin and the play caches beside it were read whole into memory before their header was looked at: a large
or sparse file (another PC's, or any file under that name) ran the game out of memory at the start. Cuts pcache_file_read
out of the source as it is and runs it with its memory held to 1 GB (setrlimit), on files made sparse so they take no disk:

- this device's cache comes back as it is, byte for byte;
- another device's 3 GB file and a 5 GB file with this device's header come back empty, without the memory for them;
- short files and a header whose size runs past the file come back empty.

python -I -B tests/test_pipeline_cache_file_read.py [--cxx c++]
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]
RUN_ALL_SKIP = {"windows": "the memory limit is setrlimit's (Linux)"}

UUID = bytes(range(16))


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def header(vendor=0x10DE, device=0x2204, uuid=UUID, size=32):
    return struct.pack("<IIII", size, 1, vendor, device) + uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="c++")
    a = p.parse_args()
    if os.name == "nt":
        print("SKIP: setrlimit")
        return
    import resource
    text = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    fn = block(text, "std::vector<uint8_t> pcache_file_read(")
    limit = ""
    for line in text.splitlines():
        if line.startswith("constexpr int64_t kPcacheMax"):
            limit = line
    fixture = r'''#include <cstdint>
#include <cstdio>
#include "HOS_FOPEN_HEADER"
#include <cstring>
#include <string>
#include <vector>
#define _fseeki64 fseeko
#define _ftelli64 ftello
constexpr uint32_t VK_PIPELINE_CACHE_HEADER_VERSION_ONE = 1, VK_UUID_SIZE = 16;
struct { struct { uint32_t vendorID = 0x10DE, deviceID = 0x2204; uint8_t pipelineCacheUUID[16] = {0, 1, 2, 3, 4, 5, 6, 7, 8,
    9, 10, 11, 12, 13, 14, 15}; } props; } dev;
[[maybe_unused]] static void logf(const char*, ...) {}
''' + limit + "\n" + fn + r'''
int main(int argc, char** argv) {
    for (int i = 1; i + 1 < argc; i += 2) {
        const std::vector<uint8_t> got = pcache_file_read(argv[i]);
        std::printf("%s %zu\n", argv[i + 1], got.size());
    }
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="pcache-read-") as tmp:
        tmp = Path(tmp)
        src = tmp / "fixture.cpp"
        src.write_text(fixture.replace("HOS_FOPEN_HEADER", (ROOT / "host" / "hos_fopen_read.h").as_posix()), encoding="utf-8")
        exe = tmp / "fixture"
        subprocess.run([a.cxx, "-std=c++17", "-O1", "-Wall", "-Werror", "-D_FILE_OFFSET_BITS=64", str(src), "-o", str(exe)],
                       check=True)
        good = header() + bytes(range(256)) * 64

        def sparse(name, head, size):
            path = tmp / name
            with open(path, "wb") as f:
                f.write(head)
                f.truncate(size)
            return path
        files = [(tmp / "good.bin", "good")]
        (tmp / "good.bin").write_bytes(good)
        files.append((sparse("other_device.bin", header(vendor=0x1002), 3 << 30), "other_device"))
        files.append((sparse("too_large.bin", header(), 5 << 30), "too_large"))
        (tmp / "short.bin").write_bytes(header()[:31])
        files.append((tmp / "short.bin", "short"))
        (tmp / "head_past_end.bin").write_bytes(header(size=4096) + b"x" * 100)
        files.append((tmp / "head_past_end.bin", "head_past_end"))
        want = {"good": len(good), "other_device": 0, "too_large": 0, "short": 0, "head_past_end": 0}

        def held():
            resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
        r = subprocess.run([str(exe)] + [x for path, name in files for x in (str(path), name)], capture_output=True,
                           text=True, timeout=120, preexec_fn=held)
        got = dict(line.split() for line in r.stdout.splitlines())
        bad = [n for n in want if got.get(n) != str(want[n])]
        if r.returncode or bad:
            sys.exit("pcache_file_read: exit %d, wrong for %s\n%s%s" % (r.returncode, bad, r.stdout, r.stderr))
        print("PASS: pipeline cache files read only for this device's header and up to kPcacheMax, within 1 GB of memory")


if __name__ == "__main__":
    main()
