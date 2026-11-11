"""Authored event stack: idle, startup, nested entries and unstable reads."""
import struct
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from event_state import read_event_state


class EventStateTests(unittest.TestCase):
    def setUp(self):
        self.data = bytearray(4096)
        self.layout = dict(manager_pointer=8, active_offset=16, count_offset=0,
                           items_offset=8, index_offset=16, name_offset=8)
        self.put(8, 128); self.put(144, 256)
        self.put(256, 2, 'I'); self.put(264, 512); self.put(272, 1, 'I')
        self.put(520, 768); self.put(776, 1024)
        self.data[1024:1030] = b'child\0'

    def put(self, offset, value, fmt='Q'):
        struct.pack_into('<' + fmt, self.data, offset, value)

    def read_memory(self, address, size):
        return dict(data_hex=self.data[address:address+size].hex())

    def test_active_child_and_idle(self):
        self.assertEqual(read_event_state(self, self.layout)['name'], 'child')
        self.put(144, 0)
        self.assertFalse(read_event_state(self, self.layout)['active'])
        self.put(8, 0)
        self.assertFalse(read_event_state(self, self.layout)['ready'])

    def test_startup_is_busy_without_name(self):
        self.put(272, 2, 'I')
        state = read_event_state(self, self.layout)
        self.assertTrue(state['active']); self.assertIsNone(state['name'])

    def test_bounds_and_terminator(self):
        self.put(256, 257, 'I')
        with self.assertRaises(RuntimeError): read_event_state(self, self.layout)
        self.put(256, 2, 'I'); self.data[1024:1088] = b'x'*64
        with self.assertRaises(RuntimeError): read_event_state(self, self.layout)
        with self.assertRaises(ValueError): read_event_state(self, dict(self.layout, active_offset=-1))

    def test_root_changes_are_rejected(self):
        original = self.read_memory; calls = [0]
        def read(address, size):
            if address == 144:
                calls[0] += 1
                if calls[0] == 2: self.put(144, 0)
            return original(address, size)
        self.read_memory = read
        with self.assertRaisesRegex(RuntimeError, 'changed during read'):
            read_event_state(self, self.layout)


if __name__ == '__main__': unittest.main()
