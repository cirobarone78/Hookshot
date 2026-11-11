"""Authored actor pools: select one identity, never an ambiguous or stale actor."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scene_actor import find_actor


class ActorTests(unittest.TestCase):
    def setUp(self):
        self.memory = bytearray(2048)
        self.layout = dict(manager_pointer=8, pool_offset=0, slot_count=2, stride=32,
                          holder_actor_offset=0, holder_id_offset=8, actor_id_offset=0,
                          actor_holder_offset=8, actor_name_pointer_offset=16, actor_position_offset=24)
        self.selector = dict(name='starter', position=[1., 2., 3.])
        struct.pack_into('<Q', self.memory, 8, 128)
        self.put_actor(128, 256, 11, 512)

    def put_actor(self, holder, actor, identity, name):
        struct.pack_into('<QI', self.memory, holder, actor, identity)
        struct.pack_into('<I', self.memory, actor, identity)
        struct.pack_into('<QQ3f', self.memory, actor + 8, holder, name, 1., 2., 3.)
        self.memory[name:name+8] = b'starter\0'

    def read_memory(self, address, length):
        self.assertLessEqual(length, 256)
        return {'data_hex': self.memory[address:address+length].hex()}

    def test_unique_name_and_position(self):
        r = find_actor(self, self.layout, self.selector)
        self.assertEqual((r['actor'], r['actor_id'], r['holder']), (256, 11, 128))

    def test_ambiguous_actor_rejected(self):
        self.put_actor(160, 768, 12, 1024)
        with self.assertRaisesRegex(RuntimeError, 'found 2'):
            find_actor(self, self.layout, self.selector)

    def test_stale_identity_rejected(self):
        struct.pack_into('<I', self.memory, 256, 12)
        with self.assertRaisesRegex(RuntimeError, 'found 0'):
            find_actor(self, self.layout, self.selector)

    def test_wrong_position_rejected(self):
        self.selector['position'][0] = 50
        with self.assertRaisesRegex(RuntimeError, 'found 0'):
            find_actor(self, self.layout, self.selector)

    def test_unterminated_name_rejected(self):
        self.memory[512:576] = b'x' * 64
        with self.assertRaisesRegex(RuntimeError, 'found 0'):
            find_actor(self, self.layout, self.selector)

    def test_bad_bounds_and_nan_rejected(self):
        self.layout['slot_count'] = 9999
        with self.assertRaises(ValueError):
            find_actor(self, self.layout, self.selector)
        self.layout['slot_count'] = 2
        self.selector['position'][0] = float('nan')
        with self.assertRaises(ValueError):
            find_actor(self, self.layout, self.selector)


if __name__ == '__main__':
    unittest.main()
