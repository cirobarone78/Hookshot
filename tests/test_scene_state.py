"""Authored memory layout: scene reads must fail closed on stale/incomplete data."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scene_state import read_state


class FakeAPI:
    def __init__(self, game):
        self.info = {'game': str(game)}
        self.memory = bytearray(1024)
        self.reads = 0
        struct.pack_into('<Q', self.memory, 8, 64)
        struct.pack_into('<QIQI', self.memory, 64, 128, 4, 256, 2)
        # Collision, then wrap from slot 3 to slot 0.
        struct.pack_into('<II', self.memory, 128 + 3 * 8, 7, 0)
        struct.pack_into('<II', self.memory, 128, 11, 1)
        struct.pack_into('<Q', self.memory, 256 + 32 + 8, 512)
        self.memory[512:517] = b'map\0\0'

    def read_memory(self, address, length):
        self.reads += 1
        if not 1 <= length <= 256:
            raise ValueError('Unbounded read')
        return {'data_hex': self.memory[address:address + length].hex()}


class SceneStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / 'image.bin').write_bytes(b'fixture')
        self.api = FakeAPI(root)
        self.path = root / 'bindings.json'
        self.profile = dict(schema=1, image_sha256=hashlib.sha256(b'fixture').hexdigest(),
                            manager_pointer=8, fields={'current_scene': 11}, string_table=dict(
                                slots_pointer_offset=0, slot_count_offset=8, values_pointer_offset=12,
                                value_count_offset=20, value_stride=32, string_pointer_offset=8,
                                string_capacity=16))

    def run_read(self):
        self.path.write_text(json.dumps(self.profile))
        return read_state(self.api, self.path)

    def test_collision_wrap(self):
        self.assertEqual(self.run_read(), dict(ready=True, consistent_snapshot=False, fields={'current_scene': 'map'}))

    def test_uninitialized(self):
        struct.pack_into('<Q', self.api.memory, 8, 0)
        self.assertFalse(self.run_read()['ready'])

    def test_wrong_image_before_memory_access(self):
        self.profile['image_sha256'] = 'stale'
        with self.assertRaises(ValueError):
            self.run_read()
        self.assertEqual(self.api.reads, 0)

    def test_missing_field(self):
        self.profile['fields']['current_scene'] = 15
        with self.assertRaisesRegex(RuntimeError, 'not found'):
            self.run_read()

    def test_bad_record(self):
        struct.pack_into('<I', self.api.memory, 132, 2)
        with self.assertRaisesRegex(RuntimeError, 'outside value array'):
            self.run_read()

    def test_unterminated(self):
        self.api.memory[512:528] = b'x' * 16
        with self.assertRaisesRegex(RuntimeError, 'terminator'):
            self.run_read()

    def test_bad_layout_before_memory_access(self):
        self.profile['string_table']['string_capacity'] = 1024
        with self.assertRaises(ValueError):
            self.run_read()
        self.assertEqual(self.api.reads, 0)

    def test_short_read(self):
        self.api.memory = self.api.memory[:516]
        with self.assertRaisesRegex(RuntimeError, 'Incomplete'):
            self.run_read()


if __name__ == '__main__':
    unittest.main()
