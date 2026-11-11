"""The physics solver's step count above 60 fps (nx2/oot_patches.py patch_solver_steps, host/nn_vi.c hos_solver_steps).

The game gives the rigid body world trunc(frames per update * 4 + 0.001) solver steps a frame: 4 at 60 fps, 8 at 30, but 3, 2
and 1 above 60 and 0 in a frame under a quarter of a 60 Hz frame, where the solve is skipped and what stands on a moving body is
left behind. The patch hands the sum to hos_solver_steps, which rounds up from the product less a quarter: the game's counts at 60
and 30 fps, never fewer steps a second than at 60, at least 1 down to a 16th of a frame; HOS_PHYSICS_STEPS=0 gives the game's own.
python -I -B tests/test_physics_steps.py [--cc gcc]
"""
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402

CC = "gcc"

LIFTED = "".join(
    '#include "a64.h"\n' if i == 0 else "" for i in range(1)) + "".join(
    head + "    c->x[8]=recomp_load64(c,c->x[0] + 0);\n" + oot_patches.SOLVER_OLD + "    return;\n}\n"
    for head in oot_patches.SOLVER_HEADS)

HARNESS = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
%s
int main(int argc, char **argv) {
    for (int i = 1; i < argc; i++) {
        float f = (float)atof(argv[i]);
        uint32_t b;
        memcpy(&b, &f, 4);
        printf("%%llu\n", (unsigned long long)hos_solver_steps(b));
    }
    return 0;
}
"""


def solver_function():
    source = (ROOT / "host" / "nn_vi.c").read_text(encoding="utf-8")
    start = source.index("uint64_t hos_solver_steps(uint32_t sum_bits) {")
    end = source.index("\n}\n", start) + 3
    return source[start:end]


class SolverSteps(unittest.TestCase):
    def test_patch_replaces_both_counts_once(self):
        out, done = oot_patches.patch_solver_steps(LIFTED)
        self.assertEqual(done, 2)
        self.assertEqual(out.count(oot_patches.SOLVER_MARK), 2)
        self.assertNotIn(oot_patches.SOLVER_OLD, out)
        self.assertEqual(out.count(oot_patches.SOLVER_DECL), 1)
        again, done = oot_patches.patch_solver_steps(out)   # (an earlier run's file)
        self.assertEqual((again, done), (out, 0))
        other = LIFTED.replace("+ 712", "+ 716")   # (another game version: left as it is)
        self.assertEqual(oot_patches.patch_solver_steps(other), (other, 0))

    def test_patch_file_counts_the_supported_build_only(self):
        _, counts, _ = oot_patches.patch_file(LIFTED, "code_044.c", True)
        self.assertEqual(counts["solver sites"], 2)
        _, counts, _ = oot_patches.patch_file(LIFTED, "code_044.c", False)
        self.assertEqual(counts["solver sites"], 0)

    def run_steps(self, sums, env=None):
        with tempfile.TemporaryDirectory(prefix="physics-steps-") as tmp:
            c = Path(tmp) / "h.c"
            exe = Path(tmp) / "h.exe"
            c.write_text(HARNESS % solver_function(), encoding="utf-8")
            subprocess.run([CC, "-std=c11", "-Wall", "-Werror", str(c), "-o", str(exe)], check=True)
            e = dict(os.environ)
            e.pop("HOS_PHYSICS_STEPS", None)
            e.update(env or {})
            out = subprocess.run([str(exe)] + ["%.9g" % s for s in sums], check=True, capture_output=True, text=True, env=e).stdout
            return [int(x) for x in out.split()]

    def test_counts_at_each_rate(self):
        # (frames per update at a rate: 60 / fps; the game's sum: that times 4, plus 0.001)
        def sum_at(fps):
            return struct.unpack("<f", struct.pack("<f", 60.0 / fps * 4 + 0.001))[0]
        rates = [30, 60, 58, 62, 72, 120, 144, 240, 480, 1000]
        steps = self.run_steps([sum_at(r) for r in rates])
        got = dict(zip(rates, steps))
        self.assertEqual(got[30], 8)
        self.assertEqual(got[60], 4)
        self.assertEqual(got[58], 4)        # (a frame a few percent long: still the game's 4)
        self.assertEqual(got[62], 4)        # (a little short: still 4, the game's 3)
        for r in rates:
            if 60 <= r <= 960:
                self.assertGreaterEqual(got[r] * r, 240, r)   # (no fewer steps a second than at 60)
            if r <= 960:   # (at least 1 down to a 16th of a frame: 960 fps)
                self.assertGreaterEqual(got[r], 1, r)
        own = dict(zip(rates, self.run_steps([sum_at(r) for r in rates], {"HOS_PHYSICS_STEPS": "0"})))
        self.assertEqual((own[30], own[60], own[72], own[120], own[240], own[1000]), (8, 4, 3, 2, 1, 0))   # (the game's trunc)
        self.assertEqual(self.run_steps([0.0, -1.0, 0.2]), [0, 0, 0])


if __name__ == "__main__":
    if "--cc" in sys.argv:
        i = sys.argv.index("--cc")
        CC = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    elif not shutil.which(CC) and shutil.which("clang"):
        CC = "clang"
    unittest.main()
