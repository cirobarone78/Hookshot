"""Guest accesses masked into the 512 GB window (nx2/rtgen.py A64_PTR) and the base + offset form (nx2/addr_split.py).

- addr_split.split rewrites the forms the translator writes, per function (the (_b+_o) forms only where every _o of that
  function is a constant), leaves offsets of 64 KB or more whole, and a second run changes nothing;
- chunks.edit_c runs it last, after nx2/oot_patches.py and the page-mark groups, whose exact-text matches it would break;
- the header rtgen.py writes has a _k form of every memory helper; built and run (Linux, clang or gcc), each _k access
  reads and writes what the whole address does, and an address past the window wraps into it instead of reaching the
  host memory after it.

python -I -B tests/test_addr_split.py
"""
import inspect
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "third_party", "a64-kit", d) for d in ("lift", "tools")] + [os.path.join(ROOT, "nx2")]
import addr_split  # noqa: E402
import chunks  # noqa: E402

HEAD = "void f_80000000(Ctx *__restrict A64_NOESC c) {\n"


class SplitTests(unittest.TestCase):
    def test_forms(self):
        cases = [
            ("recomp_load64(c,c->x[9] + 2440)", "recomp_load64_k(c,c->x[9],2440)"),
            ("recomp_store32(c,c->x[19] + 3668,c->x[8])", "recomp_store32_k(c,c->x[19],3668,c->x[8])"),
            ("recomp_store64_sp(c,c->x[21] + 8,c->x[1])", "recomp_store64_sp_k(c,c->x[21],8,c->x[1])"),
            ("recomp_load64(c,(c->x[31]+80ULL))", "recomp_load64_k(c,c->x[31],80)"),
            ("recomp_load64(c,c->x[9] + 65536)", "recomp_load64(c,c->x[9] + 65536)"),   # (past the guard below: whole)
            ("recomp_load64(c,c->x[9])", "recomp_load64(c,c->x[9])"),
            ("recomp_load32(c, c->x[20] + 8)", "recomp_load32(c, c->x[20] + 8)"),   # (host-written C: not the lift's form)
        ]
        for old, new in cases:
            self.assertEqual(addr_split.split(HEAD + "    x=" + old + ";\n}\n"), HEAD + "    x=" + new + ";\n}\n", old)

    def test_base_and_offset_per_function(self):
        const = ("void f_80000000(Ctx *__restrict A64_NOESC c) {\n"
                 "    { uint64_t _b=c->x[0]; int64_t _o=16; { uint64_t _p0,_p1; recomp_ldp64(c,(_b+_o),&_p0,&_p1); } }\n"
                 "    { uint64_t _b=c->x[1]; int64_t _o=-8; recomp_stp64(c,(_b+_o)+16,c->x[2],c->x[3]); }\n"
                 "}\n")
        reg = ("void f_80000100(Ctx *__restrict A64_NOESC c) {\n"
               "    { uint64_t _b=c->x[0]; int64_t _o=(int64_t)c->x[5]; recomp_store64(c,(_b+_o),c->x[8]); }\n"
               "    { uint64_t _b=c->x[0]; int64_t _o=8; recomp_store64(c,(_b+_o),c->x[8]); }\n"
               "}\n")
        out = addr_split.split('#include "a64.h"\n' + const + reg)
        self.assertIn("recomp_ldp64_k(c,_b,_o,&_p0,&_p1)", out)
        self.assertIn("recomp_stp64_k(c,_b,_o+16,c->x[2],c->x[3])", out)
        self.assertTrue(out.endswith(reg), "a function with a register offset keeps its whole addresses")
        self.assertEqual(addr_split.split(out), out)

    def test_off(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "code_000.c")
            with open(path, "w", newline="") as f:
                f.write(HEAD + "    recomp_load64(c,c->x[9] + 8);\n}\n")
            os.environ["A64_NO_ADDR_SPLIT"] = "1"
            try:
                self.assertEqual(addr_split.split_files([path]), 0)
            finally:
                del os.environ["A64_NO_ADDR_SPLIT"]
            self.assertEqual(addr_split.split_files([path]), 1)
            with open(path) as f:
                self.assertIn("recomp_load64_k(c,c->x[9],8)", f.read())

    def test_last_in_the_lift(self):
        src = inspect.getsource(chunks.edit_c)
        self.assertLess(src.index("oot_patches.apply("), src.index("group_marks("))
        self.assertLess(src.index("group_marks("), src.index("addr_split.split_files("))
        with open(os.path.join(ROOT, "nx2", "lift.py"), encoding="utf-8") as f:
            self.assertNotIn("addr_split", f.read())   # (not in emit_function: the patches would not find their text)


HARNESS = r'''
#define _GNU_SOURCE
#include "a64.h"
#include <stdio.h>
#include <sys/mman.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
int main(void) {
    GuestContext ctx = {0}, *c = &ctx;
    /* two pages of the window: its first and the one at 1 MB */
    if (mmap(A64_MEM, 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0) != A64_MEM ||
        mmap(A64_MEM + 0x100000, 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0) !=
            A64_MEM + 0x100000) {
        printf("SKIP: the window's pages could not be mapped\n");
        return 0;
    }
    const uint64_t b = 0x100000;
    recomp_store64_k(c, b, 16, 0x1122334455667788ULL);
    CHECK(recomp_load64(c, b + 16) == 0x1122334455667788ULL);
    CHECK(recomp_load32_k(c, b + 32, -16) == 0x55667788u && recomp_load16_k(c, b, 22) == 0x1122 && recomp_load8_k(c, b, 23) == 0x11);
    recomp_stp32_k(c, b, 64, 1, 2);
    uint64_t lo, hi;
    recomp_ldp32_k(c, b + 64, 0, &lo, &hi);
    CHECK(lo == 1 && hi == 2);
    recomp_stp64_sp_k(c, b, 128, 3, 4);
    recomp_ldp64_k(c, b, 120, &lo, &hi);
    CHECK(lo == 0 && hi == 3 && recomp_load64(c, b + 136) == 4);
    recomp_store8_sp_k(c, b, 200, 9), recomp_store16_k(c, b, 202, 0x1234), recomp_store32_sp_k(c, b, 204, 7);
    CHECK(recomp_load8(c, b + 200) == 9 && recomp_load16(c, b + 202) == 0x1234 && recomp_load32(c, b + 204) == 7);
    /* past the window: wrapped into it (whole and base + offset), never the host memory after it */
    const uint64_t past = (1ULL << 39) + b;
    recomp_store64(c, past + 8, 42);
    CHECK(recomp_load64(c, b + 8) == 42);
    recomp_store64_k(c, past | (1ULL << 63), 24, 43);
    CHECK(recomp_load64(c, b + 24) == 43 && recomp_load64_k(c, past, 24) == 43);
    CHECK((uint8_t *)A64_PTR(~0ULL) < A64_MEM + (1ULL << 39) && (uint8_t *)A64_PTR(past) == A64_MEM + b);
    printf("PASS: the _k accesses match the whole ones; addresses past the window wrap into it\n");
    return 0;
}
'''


class HeaderTests(unittest.TestCase):
    def test_every_helper_has_a_k_form_and_it_runs(self):
        import a64_rtgen
        import rtgen
        with tempfile.TemporaryDirectory() as tmp:
            a64_rtgen.write(tmp)
            with open(os.path.join(tmp, "a64_fpx.h"), "w") as f:
                f.write("")
            rt = rtgen.write(os.path.join(tmp, "rt64"))
            with open(os.path.join(rt, "a64.h"), encoding="utf-8") as f:
                header = f.read()
            plain = set(re.findall(r"^A64_INLINE \w+ (recomp_(?:load|store|ldp|stp)\w*)\(GuestContext \*c, uint64_t a", header, re.M))
            split = set(re.findall(r"^A64_INLINE \w+ (recomp_\w+)_k\(GuestContext \*c, uint64_t b, int64_t k", header, re.M))
            self.assertGreaterEqual(len(plain), 16)
            self.assertEqual(plain, split)
            self.assertIn("#define A64_PTR(a) (A64_MEM + ((uint64_t)(a) & A64_WINDOW_MASK))", header)
            if os.name == "nt" or sys.platform == "darwin":
                self.skipTest("the run maps the window's pages: Linux")
            cc = shutil.which("clang") or shutil.which("gcc")
            if not cc:
                self.skipTest("no C compiler")
            src = os.path.join(tmp, "harness.c")
            with open(src, "w") as f:
                f.write(HARNESS)
            exe = os.path.join(tmp, "harness")
            r = subprocess.run([cc, "-O1", "-w", "-I" + rt, "-I" + tmp, src, "-o", exe], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            print(r.stdout, end="")


if __name__ == "__main__":
    unittest.main()
