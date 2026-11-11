"""Bounded recorder checks with an authored clock and API, no game content."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('recorder', Path(__file__).resolve().parents[1] / 'scripts/record_dialogue.py')
recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recorder)


class RecorderTests(unittest.TestCase):
    def run_recording(self, mode='fresh'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'shots').mkdir()
            shot = root / 'shots/vk_000001.png'
            payload = b'\x89PNG\r\n\x1a\n' + b'authored fixture' + recorder.PNG_END
            shot.write_bytes(payload if mode != 'partial' else payload[:-4])
            os.utime(shot, (999, 999) if mode == 'old' else (1000.01, 1000.01))
            clock = [0.0]
            commands = []

            class API:
                info = {'profile_kind': 'analysis'}
                run = root
                session = root / 'session.json'

                def alive(self):
                    return mode != 'exit' or clock[0] < .2

                def request(self, command):
                    commands.append(command)
                    return dict(control='exclusive', presents=1 if mode == 'stall' else int(clock[0]*60),
                                last_present_age_ms=clock[0]*1000 if mode == 'stall' else 0)

                def input(self, *args, **kwargs):
                    return {'sequence': 7}

                def status(self):
                    return dict(latest_screenshot=str(shot), presents=int(clock[0]*60))

            def sleep(seconds):
                clock[0] += max(seconds, .001)

            with patch.object(recorder.time, 'monotonic', side_effect=lambda: clock[0]), \
                 patch.object(recorder.time, 'time', side_effect=lambda: 1000+clock[0]), \
                 patch.object(recorder.time, 'sleep', side_effect=sleep):
                try:
                    recorder.record(API(), root / 'out', seconds=.6, capture_every=.1,
                                    press_every=.2, press_ms=50, stall_seconds=.3)
                except (RuntimeError, TimeoutError):
                    pass
            result = json.loads((root / 'out/manifest.json').read_text())
            if mode == 'exit':
                self.assertNotIn('cancel 7', commands)
            else:
                self.assertIn('cancel 7', commands)
            if result['captures']:
                self.assertEqual((root / 'out' / result['captures'][0]['file']).read_bytes(), payload)
            return result

    def test_fresh_capture_only_once(self):
        result = self.run_recording()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['captures']), 1)
        self.assertGreater(len(result['inputs']), 1)

    def test_old_or_partial_capture_is_not_new(self):
        for mode in ('old', 'partial'):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_recording(mode)['captures'], [])

    def test_stall_and_exit_abort_and_release(self):
        for mode in ('stall', 'exit'):
            with self.subTest(mode=mode):
                result = self.run_recording(mode)
                self.assertEqual(result['status'], 'aborted')
                self.assertLess(result['elapsed'], .6)


if __name__ == '__main__':
    unittest.main()
