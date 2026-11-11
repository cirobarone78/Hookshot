"""A block-compressed texture over storage render targets used is uploaded from memory (gpu/vk/vk_texture.cpp texture_touch).

texture_touch skips the upload of a new texture whose storage the GPU rendered into since the CPU last wrote it: the image
already holds what the GPU drew there. The GPU cannot render into a compressed format, so for ASTC, BC and ETC textures
that storage only means render targets used it before; skipped, a boss or a new enemy whose textures were loaded there was
drawn with an empty texture, all blue, for its first cutscene (from Shakoquo/Mako ff479e988d). Cuts texture_touch's decision
out of the source as it is and checks it for each kind of format, with and without RX_VK_SKIP_COMPRESSED_OVER_RT=1.

python -I -B tests/test_compressed_over_rt.py [--cxx g++]
"""
import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
ENV_ON_H = ROOT / "gpu" / "vk" / "compat" / "hookshot_env.h"

FIXTURE = r'''#include <atomic>
#include <initializer_list>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
enum VkFormat { VK_FORMAT_R8G8B8A8_UNORM = 37, VK_FORMAT_BC1_RGB_UNORM_BLOCK = 131, VK_FORMAT_BC7_SRGB_BLOCK = 146,
                VK_FORMAT_ETC2_R8G8B8_UNORM_BLOCK = 147, VK_FORMAT_ASTC_4x4_UNORM_BLOCK = 157,
                VK_FORMAT_ASTC_12x12_SRGB_BLOCK = 184, VK_FORMAT_D32_SFLOAT = 126 };
struct Texture { bool uploaded = false, astc = false, bc = false; VkFormat format = VK_FORMAT_R8G8B8A8_UNORM;
                 uint64_t gpu = 0x1000, guest_size = 0x4000; uint32_t id = 1, width = 64, height = 64, layers = 1; int nvn_format = 0; };
static int logs;
static void logf(const char *, ...) { logs++; }
static uint32_t gpu_owned_since(uint64_t, uint64_t) { return 7; }   /* (render targets took this storage) */
static uint32_t decide(Texture *tex) {
    static const bool upload_all = false;
DECISION
    return owned;
}
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
int main(int argc, char **) {
    const bool old_rule = argc > 1;   /* (RX_VK_SKIP_COMPRESSED_OVER_RT=1) */
    Texture rgba, bc, bc_kept, astc_decoded, astc_raw, etc2, depth;
    bc.format = VK_FORMAT_BC1_RGB_UNORM_BLOCK;
    bc_kept.bc = true;              /* (ASTC decoded and kept as BC3) */
    astc_decoded.astc = true;       /* (ASTC decoded into RGBA8: its image format says nothing) */
    astc_raw.format = VK_FORMAT_ASTC_12x12_SRGB_BLOCK;
    etc2.format = VK_FORMAT_ETC2_R8G8B8_UNORM_BLOCK;
    depth.format = VK_FORMAT_D32_SFLOAT;
    CHECK(decide(&rgba) == 7 && decide(&depth) == 7);   /* (formats the GPU renders: skipped as before) */
    for (Texture *t : {&bc, &bc_kept, &astc_decoded, &astc_raw, &etc2}) CHECK(decide(t) == (old_rule ? 7u : 0u));
    Texture done = bc;
    done.uploaded = true;
    CHECK(decide(&done) == 0);
    CHECK(old_rule ? logs == 0 : logs > 0);
    std::printf("PASS: %s\n", old_rule ? "RX_VK_SKIP_COMPRESSED_OVER_RT=1: compressed textures skipped as before"
                                       : "compressed textures over render targets' storage uploaded, others skipped as before");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    src = (ROOT / "gpu" / "vk" / "vk_texture.cpp").read_text(encoding="utf-8")
    body = src[src.index("Texture* texture_touch(Texture* tex, bool for_sampling) {"):]
    start = body.index("    static const bool skip_compressed")
    end = body.index("\n", body.index("    uint32_t owned = ", start))
    decision = body[start:end]
    assert "gpu_owned_since(tex->gpu, tex->guest_size)" in decision, decision
    # (the log after it is in the block: up to its closing brace)
    tail = body.index("\n    }\n", end) + len("\n    }\n")
    decision = body[start:tail]
    cxx = shutil.which(a.cxx) or shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        print("SKIP: no C++ compiler")
        return
    with tempfile.TemporaryDirectory(prefix="compressed-rt-") as tmp:
        tmp = Path(tmp)
        (tmp / "f.cpp").write_text(FIXTURE.replace("DECISION", decision), encoding="utf-8")
        exe = tmp / ("f.exe" if os.name == "nt" else "f")
        # (env_on from the renderer's own header; _CRT_SECURE_NO_WARNINGS: Windows' C runtime marks getenv deprecated, and
        # -Werror made that an error with clang on Windows)
        subprocess.run([cxx, "-std=c++17", "-D_CRT_SECURE_NO_WARNINGS", "-include", str(ENV_ON_H), "-Wall",
                        "-Wno-unused-function", "-Werror", str(tmp / "f.cpp"), "-o", str(exe)],
                       check=True)
        for extra in ({}, {"RX_VK_SKIP_COMPRESSED_OVER_RT": "1"}):
            env = {k: v for k, v in os.environ.items() if k != "RX_VK_SKIP_COMPRESSED_OVER_RT"}
            env.update(extra)
            args = [str(exe)] + (["old"] if extra else [])
            r = subprocess.run(args, env=env, capture_output=True, text=True)
            print(r.stdout.strip())
            if r.returncode:
                raise SystemExit("FAIL:\n" + r.stdout + r.stderr)


if __name__ == "__main__":
    main()
