"""Menu transactions must never repeat inputs after failure or control loss."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ui_navigation as nav


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.info = dict(profile_kind='analysis', debug_socket='test')
        self.profile = dict(screens={'menu': {}}, navigation=dict(expected_scene='fixture', steps=[
            dict(button='A', expect={'menu': [dict(state=1, input_state=1)]}),
            dict(button='B', expect={'menu': [dict(state=2, input_state=1)]})]))
        self.path = self.run / 'binding.json'
        self.clock = 0
        self.frame = 0
        self.sequence = 0
        self.inputs = []
        self.cancels = []
        self.fault = None
        self.stage = 1
        self.destination = False
        self.addCleanup(patch.stopall)
        patch.object(nav.time, 'monotonic', lambda: self.clock).start()
        patch.object(nav.time, 'sleep', self.sleep).start()
        patch.object(nav.ui, 'read_state', return_value={}).start()
        patch.object(nav.ui, 'read_fields', self.observe).start()

    def sleep(self, seconds):
        self.clock += seconds

    def observe(self, api, profile):
        return dict(available=True, screens={'menu': dict(state=self.stage, input_state=1)})

    def request(self, command):
        if command == 'status':
            if self.fault != 'stall':
                self.frame += 6
            s = dict(control='exclusive', input_sequence=self.sequence, applied_sequence=self.sequence,
                     presents=self.frame, buttons=0, sticks=[0, 0, 0, 0], last_present_age_ms=0)
            if self.inputs and self.fault == 'handoff':
                s['control'] = 'player'
            if self.inputs and self.fault == 'superseded':
                s['input_sequence'] += 1
            if self.fault == 'no_frame_age':
                s['last_present_age_ms'] = None
            return s
        if command.startswith('input '):
            self.inputs.append(command)
            self.sequence += 1
            self.stage += 1
            return dict(sequence=self.sequence)
        if command.startswith('cancel '):
            self.cancels.append(command)
            return dict(canceled=self.fault != 'superseded')
        raise AssertionError(command)

    def scene_ready(self, expected, timeout):
        self.assertEqual(expected, 'fixture')
        self.destination = True
        if self.fault == 'destination':
            raise TimeoutError('wrong destination')
        return dict(status='completed')

    def execute(self, timeout=2):
        self.path.write_text(json.dumps(self.profile))
        return nav.navigate(self, self.path, timeout)

    def report(self):
        return json.loads(next(self.run.glob('ui-navigation-*.json')).read_text())

    def test_sequence_and_destination(self):
        self.assertEqual(self.execute()['status'], 'completed')
        self.assertEqual(self.inputs, ['input 1 0 0 0 0 100', 'input 2 0 0 0 0 100'])
        self.assertTrue(self.destination)
        self.assertEqual(self.cancels, ['cancel 2'])

    def test_changing_preflight_restarts_stable_frames_without_duplicate_input(self):
        calls = 0
        frames = []
        original_request = self.request
        def request(command):
            if command.startswith('input '):
                frames.append(self.frame)
            return original_request(command)
        self.request = request
        def changing(api, profile):
            nonlocal calls
            calls += 1
            if calls == 4:  # The immediate pre-input recheck.
                raise nav.ui.UIStateChanging('UI state changed during read')
            return self.observe(api, profile)
        with patch.object(nav.ui, 'read_fields', changing):
            self.assertEqual(self.execute()['status'], 'completed')
        self.assertEqual(frames[0], 42)
        self.assertEqual(len(self.inputs), 2)
        self.assertEqual(self.report()['steps'][0]['changing_reads'], 1)

    def test_continuously_changing_state_times_out_without_input(self):
        with patch.object(nav.ui, 'read_fields', side_effect=nav.ui.UIStateChanging('changing')):
            with self.assertRaises(TimeoutError):
                self.execute()
        self.assertEqual(self.inputs, [])
        self.assertEqual(self.report()['status'], 'failed')

    def test_object_or_read_errors_still_abort_without_input(self):
        with patch.object(nav.ui, 'read_fields', side_effect=RuntimeError('UI object type or owner changed')):
            with self.assertRaisesRegex(RuntimeError, 'owner changed'):
                self.execute()
        self.assertEqual(self.inputs, [])
        self.assertNotIn('changing_reads', self.report()['steps'][0])

    def test_control_loss(self):
        self.fault = 'handoff'
        with self.assertRaisesRegex(RuntimeError, 'exclusive'):
            self.execute()
        self.assertEqual(len(self.inputs), 1)
        self.assertEqual(self.report()['status'], 'failed')

    def test_superseded_input(self):
        self.fault = 'superseded'
        with self.assertRaisesRegex(RuntimeError, 'superseded'):
            self.execute()
        self.assertEqual(len(self.inputs), 1)
        self.assertEqual(self.cancels, ['cancel 1'])

    def test_wrong_state_times_out_without_input(self):
        self.stage = 9
        with self.assertRaises(TimeoutError):
            self.execute()
        self.assertEqual(self.inputs, [])

    def test_missing_frame_age_is_not_ready(self):
        self.fault = 'no_frame_age'
        with self.assertRaises(TimeoutError):
            self.execute()
        self.assertEqual(self.inputs, [])

    def test_stall_does_not_count_polling_as_frames(self):
        self.fault = 'stall'
        self.frame = 6
        with self.assertRaisesRegex(TimeoutError, 'frame progress'):
            self.execute(timeout=20)
        self.assertEqual(self.inputs, [])

    def test_slow_preparation_before_first_frame(self):
        request = self.request
        def preparing(command):
            if command == 'status' and self.clock < 12:
                return dict(control='exclusive', input_sequence=0, applied_sequence=0,
                            presents=0, buttons=0, sticks=[0, 0, 0, 0], last_present_age_ms=None)
            return request(command)
        self.request = preparing
        self.assertEqual(self.execute(timeout=20)['status'], 'completed')
        self.assertGreaterEqual(self.clock, 12)

    def test_no_first_frame_still_has_overall_deadline(self):
        self.fault = 'stall'
        with self.assertRaisesRegex(TimeoutError, 'deadline'):
            self.execute(timeout=12)
        self.assertEqual(self.inputs, [])
        self.assertLess(self.clock, 13)

    def test_destination_failure_does_not_retry(self):
        self.fault = 'destination'
        with self.assertRaisesRegex(TimeoutError, 'destination'):
            self.execute()
        self.assertEqual(len(self.inputs), 2)
        self.assertEqual(self.report()['status'], 'failed')

    def test_full_recipe_checked_before_input(self):
        self.profile['navigation']['steps'][1]['button'] = 'INVALID'
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.inputs, [])

    def test_checkpoint_precedes_input(self):
        request = self.request
        def checked(command):
            if command.startswith('input '):
                report = self.report()
                self.assertEqual(report['status'], 'running')
                self.assertTrue(report['steps'][-1]['input_attempted'])
                self.assertNotIn('input', report['steps'][-1])
            return request(command)
        self.request = checked
        self.execute()

    def test_changed_preinput_state_prevents_pulse(self):
        calls = 0
        def changing(api, profile):
            nonlocal calls
            calls += 1
            if calls >= 4:
                self.stage = 9
            return self.observe(api, profile)
        with patch.object(nav.ui, 'read_fields', changing):
            with self.assertRaises(TimeoutError):
                self.execute()
        self.assertEqual(self.inputs, [])

    def test_player_profile_rejected(self):
        self.info['profile_kind'] = 'player'
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.inputs, [])

    def test_keyboard_interrupt_records_failure(self):
        def fail(api, profile):
            raise KeyboardInterrupt()
        with patch.object(nav.ui, 'read_fields', fail):
            with self.assertRaises(KeyboardInterrupt):
                self.execute()
        self.assertEqual(self.report()['status'], 'failed')
        self.assertEqual(self.inputs, [])


if __name__ == '__main__':
    unittest.main()
