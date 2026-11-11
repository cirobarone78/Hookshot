"""On GCN the precompile leaves the notes' graphics pipelines to play, and makes the compute and mesh fallback ones
(gpu/vk/vk_draw.cpp precompile_run). An RX 580 drew wrongly from the graphics pipelines made there; the switch is
RX_VK_PRECOMPILE_GRAPHICS. Reads the source, game-free.

python -I -B tests/test_gcn_precompile_graphics.py
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def precompile_run():
    text = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
    start = text.index("void precompile_run(")
    end = text.index("\n}\n", start)
    return text[start:end]


class GcnPrecompileGraphics(unittest.TestCase):
    def setUp(self):
        self.body = precompile_run()

    def test_gate_is_gcn_and_switchable(self):
        gate = self.body[self.body.index("graphics_here"):]
        gate = gate[:gate.index("}();")]
        self.assertIn('getenv("RX_VK_PRECOMPILE_GRAPHICS")', gate)
        # (the same GCN test as the mirror and batch defaults: no stage pinned to 32 lanes, waves wider than 32)
        self.assertRegex(gate, r"dev\.sg32_stages\s*==\s*0\s*&&\s*dev\.subgroup_size\s*>\s*32")

    def test_notes_dropped_before_the_work_is_counted(self):
        clear = self.body.index("notes.clear()")
        self.assertLess(self.body.index("graphics_here"), clear)
        # (the total and the workers' lists come after: nothing graphics is built here when the gate is off)
        self.assertLess(clear, self.body.index("const size_t total = notes.size()"))
        self.assertLess(clear, self.body.index("pre->notes = std::move(notes)"))

    def test_programs_still_read_and_other_pipelines_kept(self):
        # (the notes' programs stay in the wanted set, read before play; the fallback and compute lists are untouched)
        self.assertLess(self.body.index("wanted.insert(n->prog)"), self.body.index("notes.clear()"))
        self.assertIn("fallbacks.push_back(&p)", self.body)
        self.assertIn("computes.push_back(&p)", self.body)
        self.assertIsNone(re.search(r"fallbacks\.clear\(\)|computes\.clear\(\)", self.body))


if __name__ == "__main__":
    unittest.main()
