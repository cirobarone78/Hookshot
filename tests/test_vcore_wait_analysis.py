"""Authored interleaved scheduler records and native interval boundaries."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
spec = importlib.util.spec_from_file_location('trace', Path(__file__).resolve().parents[1]/'scripts/analyze_vcore_waits.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TraceTests(unittest.TestCase):
    def test_interleaved_and_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            (p/'log').write_text('''vcore-owner: at_ns=200 waiter_tid=1 core=0 owner_tid=9 priority=16 kick=2 name=worker
vcore-wait: at_ns=300 waiter_tid=2 waited_ns=20 total_ns=50 held=0 mask=3
vcore-wait: at_ns=200 waiter_tid=1 waited_ns=20 total_ns=100 held=1 mask=1
vcore-owner: at_ns=300 waiter_tid=2 core=0 owner_tid=0 priority=0 kick=0 name=-
vcore-wait: at_ns=99 waiter_tid=3 waited_ns=20 total_ns=50 held=0 mask=1
''')
            (p/'csv').write_text('frame,return_ns,interval_ns\n1,100,0\n2,200,100\n3,300,100\n')
            rows=module.analyze(p/'log',p/'csv')['waits']
            self.assertIsNone(rows[0]['present_interval'])
            self.assertEqual(rows[1]['present_interval']['frame'],2)
            self.assertEqual(rows[1]['owners_at_snapshot'][0]['tid'],9)
            self.assertTrue(rows[1]['owners_complete'])
            self.assertEqual(rows[2]['present_interval']['frame'],3)
            self.assertFalse(rows[2]['owners_complete'])
            self.assertEqual(rows[2]['owners_at_snapshot'][0]['tid'],0)


if __name__ == '__main__':
    unittest.main()
