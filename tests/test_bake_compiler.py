"""Check the compiler choice used by the offline shader-bake helper."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import bake_mimo


class BakeCompilerSelectionTests(unittest.TestCase):
    def test_bake_cxx_overrides_cxx(self):
        with patch.dict(os.environ, {"BAKE_CXX": "custom-bake-cxx", "CXX": "g++"}):
            self.assertEqual(bake_mimo.cxx(), "custom-bake-cxx")

    def test_falls_back_when_first_compiler_lacks_cxx23(self):
        found = {"clang++": "/usr/bin/clang++", "g++": "/usr/bin/g++"}
        with patch.dict(os.environ, {"BAKE_CXX": "", "CXX": ""}), \
             patch.object(bake_mimo.shutil, "which", side_effect=found.get), \
             patch.object(bake_mimo, "cxx_std", side_effect=[SystemExit("no C++23"), "-std=c++23"]):
            self.assertEqual(bake_mimo.cxx(), "/usr/bin/g++")


if __name__ == "__main__":
    unittest.main(verbosity=2)
