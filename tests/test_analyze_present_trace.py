"""Averages must not hide stalls, gaps, or an incomplete segment."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
spec = importlib.util.spec_from_file_location('trace', Path(__file__).resolve().parents[1] / 'scripts/analyze_present_trace.py')
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)

class TraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'trace.csv'

    def write(self, intervals):
        stamp = 1000000000
        lines = ['frame,return_ns,interval_ns', f'1,{stamp},0']
        for frame, interval in enumerate(intervals, 2):
            stamp += interval
            lines.append(f'{frame},{stamp},{interval}')
        self.path.write_text('\n'.join(lines)+'\n')

    def test_fast_average_does_not_hide_stall(self):
        self.write([10000000]*150 + [100000000] + [10000000]*150)
        result = trace.analyze(self.path, 2, 302)
        self.assertGreater(result['mean_fps'], 60)
        self.assertFalse(result['every_frame_within_budget'])
        self.assertEqual(result['over_budget_frames'], 1)
        self.assertEqual(result['max_ms'], 100)
        self.assertLess(result['slowest_one_second_window']['fps'], 100)

    def test_segment_excludes_loading_but_requires_all_selected_frames(self):
        self.write([500000000] + [10000000]*120)
        result = trace.analyze(self.path, 3, 122)
        self.assertTrue(result['every_frame_within_budget'])
        self.assertEqual(result['mean_fps'], 100)
        with self.assertRaises(ValueError):
            trace.analyze(self.path, 3, 123)
        self.path.write_text(self.path.read_text().replace('5,', '6,', 1))
        with self.assertRaises(ValueError):
            trace.analyze(self.path, 3, 122)

    def test_timestamp_mismatch_is_rejected(self):
        self.write([10000000]*3)
        self.path.write_text(self.path.read_text().replace('1020000000', '1020000001'))
        with self.assertRaises(ValueError):
            trace.analyze(self.path, 2, 4)

    def test_phase_columns_preserve_all_interval_checks(self):
        self.write([10000000]*120 + [100000000])
        expected = trace.analyze(self.path, 2, 122)
        lines = self.path.read_text().splitlines()
        lines[0] += ',present_begin_ns,renderer_begin_ns,renderer_end_ns,vcore_back_ns'
        for i in range(1, len(lines)):
            stamp = int(lines[i].split(',')[1])
            lines[i] += f',{stamp-4},{stamp-3},{stamp-2},{stamp-1}'
        self.path.write_text('\n'.join(lines)+'\n')
        self.assertEqual(trace.analyze(self.path, 2, 122), expected)
        self.path.write_text(self.path.read_text().replace('1020000000', '1020000001', 1))
        with self.assertRaises(ValueError):
            trace.analyze(self.path, 2, 122)

if __name__ == '__main__':
    unittest.main()
