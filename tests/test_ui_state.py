"""Authored UI tables exercise lifetime checks without any game data."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ui_state import read_state, UIStateChanging


class UIStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'image.bin').write_bytes(b'authored')
        self.info = {'game': str(self.root)}
        self.memory = bytearray(1024)
        self.put(8, 64)
        self.put(64, 900)
        struct.pack_into('<I', self.memory, 72, 2)
        self.put(80, 128)
        self.put(128, 256)
        self.put(256, 901)
        self.put(272, 64)
        self.memory[280:282] = b'\x02\x01'
        self.hook = None
        self.calls = {}
        self.profile = dict(schema=1, image_sha256=hashlib.sha256(b'authored').hexdigest(),
                            manager_pointer=8, manager_vtable=900, count_offset=8,
                            table_offset=16, owner_offset=16, state_offset=24,
                            input_state_offset=25, screens={
                                'menu': dict(index=0, vtable=901),
                                'dialog': dict(index=1, vtable=902)})

    def put(self, address, value):
        struct.pack_into('<Q', self.memory, address, value)

    def read_memory(self, address, size):
        self.assertLessEqual(size, 256)
        self.calls[address] = self.calls.get(address, 0) + 1
        if self.hook:
            self.hook(address, self.calls[address])
        return {'data_hex': self.memory[address:address + size].hex()}

    def observe(self):
        path = self.root / 'bindings.json'
        path.write_text(json.dumps(self.profile))
        return read_state(self, path)

    def test_present_and_absent(self):
        self.assertEqual(self.observe(), dict(available=True, consistent_snapshot=False,
                         screens={'menu': dict(state=2, input_state=1), 'dialog': None}))

    def test_uninitialized(self):
        self.put(8, 0)
        self.assertFalse(self.observe()['available'])

    def test_image_checked_before_memory(self):
        self.profile['image_sha256'] = 'wrong'
        with self.assertRaises(ValueError):
            self.observe()
        self.assertEqual(self.calls, {})

    def test_invalid_layout_before_memory(self):
        self.profile['screens']['menu']['index'] = True
        with self.assertRaises(ValueError):
            self.observe()
        self.assertEqual(self.calls, {})

    def test_wrong_type_or_owner(self):
        for address in (256, 272):
            with self.subTest(address=address):
                original = bytes(self.memory)
                self.put(address, 999)
                with self.assertRaisesRegex(RuntimeError, 'type or owner'):
                    self.observe()
                self.memory[:] = original

    def test_replaced_slot(self):
        self.hook = lambda a, n: self.put(128, 512) if a == 128 and n == 2 else None
        with self.assertRaisesRegex(RuntimeError, 'table changed'):
            self.observe()

    def test_absent_slot_appears(self):
        self.hook = lambda a, n: self.put(136, 512) if a == 136 and n == 2 else None
        with self.assertRaisesRegex(RuntimeError, 'table changed'):
            self.observe()

    def test_state_changes(self):
        def change(a, n):
            if a == 280 and n == 2:
                self.memory[a] = 3
        self.hook = change
        with self.assertRaisesRegex(UIStateChanging, 'state changed'):
            self.observe()

    def test_root_changes(self):
        self.hook = lambda a, n: self.put(8, 512) if a == 8 and n == 2 else None
        with self.assertRaisesRegex(RuntimeError, 'manager changed'):
            self.observe()

    def test_reallocated_table(self):
        self.hook = lambda a, n: self.put(80, 512) if a == 80 and n == 2 else None
        with self.assertRaisesRegex(RuntimeError, 'manager changed'):
            self.observe()

    def test_short_read(self):
        self.memory = self.memory[:280]
        with self.assertRaisesRegex(RuntimeError, 'Incomplete'):
            self.observe()

    def test_bounded_count(self):
        struct.pack_into('<I', self.memory, 72, 513)
        with self.assertRaisesRegex(RuntimeError, 'incompatible'):
            self.observe()


if __name__ == '__main__':
    unittest.main()
