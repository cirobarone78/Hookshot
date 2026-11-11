"""A dispatched or briefly idle event is not a completed scene chain."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import event_play
from analysis_api import InputPollTimeout

RUN_ALL_SKIP = {'windows': 'Linux runtime API and Unix session isolation'}


class EventPlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name); self.info = dict(profile_kind='analysis')
        (self.run/'scene-bindings.json').write_text(json.dumps(dict(event_state={},
            event_sequences={'first': dict(followup_events=['second'])})))
        self.now = 0.; self.sequence = 0; self.frame = 0; self.polls = 0
        self.mode = 'exclusive'; self.behavior = 'normal'; self.started = []
        for attr, fn in [('monotonic', lambda: self.now), ('time', lambda: self.now),
                         ('sleep', self.sleep)]:
            p = patch.object(event_play.time, attr, fn); p.start(); self.addCleanup(p.stop)
        for attr, fn in [('read_event_state', self.event), ('start_event', self.start),
                         ('read_fields', lambda api, profile: self.scene_state(None))]:
            p = patch.object(event_play, attr, fn); p.start(); self.addCleanup(p.stop)

    def sleep(self, seconds): self.now += seconds
    def scene_state(self, path): return dict(fields=dict(current_scene='map'))
    def request(self, command):
        if command == 'guest info': return dict(sequence=self.sequence)
        if self.behavior != 'stall': self.frame += 6
        return dict(control=self.mode, presents=self.frame, last_present_age_ms=0)
    def start(self, api, name, scene, **kwargs):
        self.sequence += 1; self.polls = 0; self.started.append(name)
        return dict(sequence=self.sequence, entry_event=name)
    def event(self, api, layout):
        self.polls += 1
        active = bool(self.started) and self.polls <= 3 and self.behavior != 'never-started'
        return dict(ready=True, active=active, name=self.started[-1] if active else None)
    def play(self, **kwargs): return event_play.play_event(self, 'first', 'map', **kwargs)

    def test_chain_waits_for_matching_active_then_idle_frames(self):
        result = self.play()
        self.assertEqual(self.started, ['first', 'second'])
        self.assertTrue(result['lifecycle_completed'])
        self.assertFalse(result['gameplay_verified'])
        self.assertGreaterEqual(self.frame, 60)
    def test_ack_without_start_never_completes(self):
        self.behavior = 'never-started'
        with self.assertRaises(TimeoutError): self.play(timeout=3)
        self.assertEqual(self.started, ['first'])
        self.assertEqual(json.loads(next(self.run.glob('event-play-*')).read_text())['status'], 'failed')
    def test_stall_and_handoff_abort(self):
        self.behavior = 'stall'
        with self.assertRaisesRegex(RuntimeError, 'frames'): self.play(timeout=10)
        self.started=[]; self.mode='player'; self.behavior='normal'
        with self.assertRaisesRegex(RuntimeError, 'exclusive'): self.play()
    def test_observe_existing_does_not_dispatch_twice(self):
        self.started = ['first']; self.sequence = 1; self.polls = 0
        result = event_play.play_event(self, 'first', 'map', observe=True)
        self.assertEqual(self.started, ['first', 'second'])
        self.assertEqual(result['steps'][0]['status'], 'observing')

    def test_arrival_requires_boot_event_not_just_destination(self):
        profile = dict(event_state={}, event_sequences={'first': dict(arrival=dict(scene='next', events=['boot']))})
        (self.run/'scene-bindings.json').write_text(json.dumps(profile))
        self.scene_state = lambda path: dict(fields=dict(current_scene='next' if self.started else 'map',
            pending_scene='', pending_entrance='', pending_event=''))
        with self.assertRaises(TimeoutError): self.play(timeout=3)
        self.started=[]; self.polls=0
        def event(api, layout):
            self.polls += 1
            name = ('first' if self.polls < 3 else 'boot') if self.started and self.polls < 5 else None
            return dict(ready=True, active=bool(name), name=name)
        with patch.object(event_play, 'read_event_state', event):
            self.assertTrue(self.play()['lifecycle_completed'])

    def test_dialogue_is_bounded_and_canceled_on_failure(self):
        (self.run/'scene-bindings.json').write_text(json.dumps(dict(event_state={},
            event_sequences={'first': dict(dialogue=dict(press_every=.2, press_ms=80))})))
        self.input = lambda *a, **k: dict(sequence=77)
        self.screenshot = lambda: 'authored.png'
        original = self.request; commands=[]
        def request(command):
            commands.append(command)
            if command.startswith('cancel '):return dict(canceled=True)
            result=original(command)
            if 'cancel 77' in commands:
                result.update(input_sequence=78,applied_sequence=78)
            return result
        self.request = request
        with patch.object(event_play, 'read_event_state', lambda *args: dict(
                ready=True, active=bool(self.started), name='first' if self.started else None)):
            with self.assertRaises(TimeoutError): self.play(timeout=3)
        self.assertIn('cancel 77', commands)
        report=json.loads(next(self.run.glob('event-play-*')).read_text())
        self.assertGreater(len(report['inputs']), 1)
        self.assertTrue(report['input_cleanup']['canceled'])
        self.assertTrue(report['captures'])

    def test_success_waits_for_neutral_input_acknowledgement(self):
        (self.run/'scene-bindings.json').write_text(json.dumps(dict(event_state={},
            event_sequences={'first':dict(dialogue=dict(press_every=1,press_ms=80))})))
        self.input=lambda *a, **k: dict(sequence=77)
        self.screenshot=lambda: 'authored.png'
        original=self.request; cleanup_polls=[]; canceled=[]
        def request(command):
            if command=='cancel 77':canceled.append(True);return dict(canceled=True)
            result=original(command)
            if canceled and command=='status':
                cleanup_polls.append(1)
                result.update(input_sequence=78,applied_sequence=78 if len(cleanup_polls)>2 else 77)
            return result
        self.request=request
        r=self.play()
        self.assertTrue(r['input_cleanup']['canceled'])
        self.assertEqual(len(cleanup_polls),3)
        self.assertEqual(r['status'],'completed')

    def test_idle_during_map_loading_is_not_completion(self):
        (self.run/'scene-bindings.json').write_text(json.dumps(dict(event_state={},
            event_sequences={'first':dict(arrival=dict(scene='next',events=['boot']))})))
        self.scene_state=lambda path: dict(fields=dict(current_scene='next' if self.polls>12 else 'map',
            pending_scene='next' if 3<self.polls<12 else '',pending_entrance='',pending_event=''))
        def state(api, layout):
            self.polls+=1
            name='first' if self.started and self.polls<=3 else 'boot' if 13<=self.polls<=15 else None
            return dict(ready=not 4<=self.polls<=10,active=bool(name),name=name)
        with patch.object(event_play,'read_event_state',state):
            result=self.play()
        self.assertTrue(result['lifecycle_completed'])
        self.assertGreaterEqual(self.polls,18)

    def test_invalid_dialogue_and_arrival_reject_before_dispatch(self):
        invalid = [dict(dialogue={}), dict(dialogue=dict(press_every=.01,press_ms=80)),
                   dict(dialogue=dict(press_every=float('nan'),press_ms=80)),
                   dict(arrival=dict(scene='next',events=[])),
                   dict(arrival=dict(scene='next',events=['boot']),followup_events=['second'])]
        for route in invalid:
            (self.run/'scene-bindings.json').write_text(json.dumps(dict(event_sequences={'first':route})))
            with self.assertRaises(ValueError):self.play()
            self.assertFalse(self.started)

    def test_invalid_followup_rejects_before_dispatch(self):
        (self.run/'scene-bindings.json').write_text(json.dumps(dict(event_sequences={'first':dict(followup_events=[''])})))
        with self.assertRaises(ValueError): self.play()
        self.assertFalse(self.started)

    def dialogue_fixture(self, canceled=True, superseded=False, retry=False):
        (self.run/'scene-bindings.json').write_text(json.dumps(dict(event_state={},
            event_sequences={'first': dict(dialogue=dict(press_every=.9, press_ms=80))})))
        self.input_seq = 0
        self.input_calls = 0
        original_request = self.request

        def request(command):
            if command.startswith('cancel '):
                match = int(command.split()[1]) == self.input_seq
                if match: self.input_seq += 1
                return dict(canceled=match)
            result = original_request(command)
            if command == 'status':
                result.update(input_sequence=self.input_seq, applied_sequence=self.input_seq)
            return result

        def input(buttons, **kwargs):
            self.input_calls += 1
            self.input_seq += 1
            sequence = self.input_seq
            if self.input_calls == 1:
                self.now += 1
                if canceled: self.input_seq += 1
                if superseded: self.input_seq += 1
                raise InputPollTimeout(sequence, canceled)
            return dict(sequence=sequence, applied=True)

        self.request = request
        self.input = input
        self.screenshot = lambda: self.run/'authored-shot.png'
        if retry:
            def event(api, layout):
                self.polls += 1
                active = bool(self.started) and self.polls <= 16
                return dict(ready=True, active=active, name='first' if active else None)
            self.event = event
            patcher = patch.object(event_play, 'read_event_state', event)
            patcher.start(); self.addCleanup(patcher.stop)

    def test_canceled_unpolled_dialogue_keeps_observing_without_recancel(self):
        self.dialogue_fixture()
        result = self.play()
        self.assertTrue(result['lifecycle_completed'])
        self.assertEqual(result['inputs'][0]['acknowledgement'],
                         dict(sequence=1, applied=False, canceled=True, neutral_sequence=2))
        self.assertNotIn('input_cleanup', result)  # Already neutral, even without another input poll.

    def test_later_dialogue_pulse_after_cancellation_is_cleaned_up(self):
        self.dialogue_fixture(retry=True)
        result = self.play()
        self.assertGreater(self.input_calls, 1)
        self.assertTrue(result['input_cleanup']['canceled'])

    def test_failed_cancel_or_superseded_neutral_still_aborts(self):
        self.dialogue_fixture(canceled=False)
        with self.assertRaises(InputPollTimeout): self.play()
        self.started = []; self.polls = 0
        self.dialogue_fixture(superseded=True)
        with self.assertRaisesRegex(RuntimeError, 'ownership'): self.play()

    def test_unclassified_input_timeout_still_aborts(self):
        self.dialogue_fixture()
        def failed_input(*args, **kwargs):
            raise TimeoutError('transport timeout')
        self.input = failed_input
        with self.assertRaisesRegex(TimeoutError, 'transport'): self.play()


if __name__ == '__main__': unittest.main()
