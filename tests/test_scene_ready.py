"""Readiness must observe progress and never submit guest operations."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import scene_ready


class ReadyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        (self.run / 'scene-bindings.json').write_text('{}')
        self.now = 0; self.frozen = False; self.busy = False; self.active = False
        self.control = 'exclusive'; self.pending = ''; self.scene = 'map'
        self.calls = []
        patches = [patch.object(scene_ready.time, 'monotonic', lambda: self.now),
                   patch.object(scene_ready.time, 'sleep', self.sleep),
                   patch.object(scene_ready.scene_state, 'validate_profile'),
                   patch.object(scene_ready.scene_state, 'read_fields', self.fields),
                   patch.object(scene_ready, 'read_event_state', self.event)]
        for p in patches: p.start(); self.addCleanup(p.stop)
    def sleep(self, seconds): self.now += seconds
    def fields(self, *args):
        return dict(ready=True, fields=dict(current_scene=self.scene, pending_scene=self.pending,
                                           pending_entrance='', pending_event=''))
    def event(self, *args): return dict(ready=True, active=self.active)
    def request(self, command):
        self.calls.append(command)
        if command == 'guest info': return dict(allowed=True, phase='pending' if self.busy else 'idle')
        self.assertEqual(command, 'status')
        return dict(control=self.control, presents=0 if self.frozen else int(self.now*60),
                    buttons=0, sticks=[0]*4, input_sequence=1, applied_sequence=1, last_present_age_ms=0)
    def test_progress_completes_without_writes(self):
        r = scene_ready.wait_ready(self, 'map', 1)
        self.assertEqual(r['status'], 'completed')
        self.assertGreaterEqual(r['last_ready_frame'] - r['first_ready_frame'], 12)
        self.assertFalse(r['gameplay_verified'])
        self.assertEqual(set(self.calls), {'status', 'guest info'})
    def test_busy_event_transition_wrong_scene_and_frozen_time_out(self):
        for attr, value in [('busy', True), ('active', True), ('pending', 'next'),
                            ('scene', 'other'), ('frozen', True)]:
            with self.subTest(attr=attr):
                old = getattr(self, attr); setattr(self, attr, value)
                with self.assertRaises(TimeoutError): scene_ready.wait_ready(self, 'map', 1)
                setattr(self, attr, old)
        self.assertTrue(all(json.loads(p.read_text())['status']=='failed'
                            for p in self.run.glob('scene-ready-*')))
    def test_stale_or_unacknowledged_input_cannot_be_ready(self):
        original = self.request
        for override in [dict(last_present_age_ms=1001), dict(buttons=1),
                         dict(sticks=[1,0,0,0]), dict(applied_sequence=0)]:
            with self.subTest(override=override):
                def request(command):
                    r = original(command)
                    if command == 'status': r.update(override)
                    return r
                with patch.object(self, 'request', request):
                    with self.assertRaises(TimeoutError): scene_ready.wait_ready(self, 'map', 1)
    def test_worker_must_have_polled(self):
        original = self.request
        def request(command):
            return dict(allowed=False, phase='idle') if command == 'guest info' else original(command)
        with patch.object(self, 'request', request):
            with self.assertRaises(TimeoutError): scene_ready.wait_ready(self, 'map', 1)

    def test_control_loss_stops(self):
        self.control = 'player'
        with self.assertRaisesRegex(RuntimeError, 'exclusive'): scene_ready.wait_ready(self, 'map')
    def test_invalid_timeout_has_no_requests(self):
        for timeout in [True, float('nan'), 0, 601]:
            with self.assertRaises(ValueError): scene_ready.wait_ready(self, 'map', timeout)
        self.assertFalse(self.calls)
    def test_transient_read_failure_resets_stability(self):
        original = self.fields
        def fields(*args):
            if .09 < self.now < .11: raise RuntimeError('Manager changed')
            return original(*args)
        with patch.object(scene_ready.scene_state, 'read_fields', fields):
            r = scene_ready.wait_ready(self, 'map', 1)
        self.assertGreaterEqual(r['first_ready_frame'], 12)
        self.assertTrue(any('read_error' in s for s in r['samples']))


if __name__ == '__main__': unittest.main()
