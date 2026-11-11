#!/usr/bin/env python3
"""Optional, game-free regression against the pinned local DLSS5VKLayer source.

DLSS5_LAYER_SOURCE may name layer.cpp from either the original or patched tree.
Only the actual shared-mapping functions are compiled; no Vulkan calls are made.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('DLSS5_LAYER_SOURCE',
                           ROOT / 'work/dlss5/source/layer_linux/src/layer.cpp'))


class MappingTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux' and shutil.which('g++') and SOURCE.is_file(),
                         'needs Linux, g++ and a local DLSS5VKLayer checkout')
    def test_imported_addresses_survive_model_growth(self):
        source = SOURCE.read_text()
        mapping = source[source.index('struct ShmMap {'):source.index('static bool ShmOpen(')]
        # Compile the same protocol constants as the layer; no copied layout.
        protocol = ROOT / 'work/dlss5/source/common/shm_protocol.h'
        harness = (ROOT / 'tests/dlss5_mapping_test.cpp').read_text()
        harness = harness.replace('/* PROTOCOL */', f'#include "{protocol}"')
        harness = harness.replace('/* MAPPING */', mapping)
        if 'static void ShmClose(' in mapping:
            harness = '#define HAS_SHM_CLOSE 1\n' + harness
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'test.cpp'
            executable = Path(directory) / 'test'
            unit.write_text(harness)
            subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra',
                            '-Wno-unused-function', str(unit), '-o', str(executable)],
                           check=True, timeout=30)
            subprocess.run([str(executable)], check=True, timeout=15)


if __name__ == '__main__':
    unittest.main()
