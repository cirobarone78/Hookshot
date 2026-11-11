"""Scene transactions: acknowledgement is not arrival, and failure stays failure."""
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import scene_load

RUN_ALL_SKIP = {'windows': 'Linux runtime API and Unix session isolation'}


class Clock:
    now = 100.0

    def time(self):
        return self.now

    monotonic = time

    def sleep(self, seconds):
        self.now += seconds


class FakeAPI:
    def __init__(self, root):
        self.run = root
        self.info = {'profile_kind': 'analysis', 'game': str(root)}
        (root / 'image.bin').write_bytes(b'authored image')
        self.fields = dict(current_scene='source', pending_scene='', pending_entrance='', pending_event='')
        self.keys = {name: i + 1 for i, name in enumerate(self.fields)}
        (root / 'scene-bindings.json').write_text(json.dumps(dict(
            schema=1, image_sha256=hashlib.sha256(b'authored image').hexdigest(), fields=self.keys,
            dispatch=dict(event_helper=16, transition_event='wait'))))
        self.mode, self.phase = 'exclusive', 'dispatched'
        self.sequence, self.frames, self.event_reads = 0, 100, 0
        self.calls = []
        self.started = False
        self.arrive = True
        self.progress = True
        self.unique = True
        self.bad_image = False
        self.handoff = False
        self.replaced = False

    def scenes(self, catalog, scene_id):
        return dict(scenes=[dict(id=scene_id, missing_sources=[], entrances=[dict(name='door', unique_name=self.unique)])])

    def scene_state(self, bindings):
        if self.bad_image:
            raise ValueError('Wrong image')
        if self.started:
            self.event_reads += 1
            if self.arrive and self.event_reads >= 3:
                self.fields.update(current_scene='target', pending_scene='', pending_entrance='', pending_event='')
        return dict(ready=True, fields=dict(self.fields))

    def request(self, command):
        self.calls.append(command)
        if command == 'status':
            if self.progress:
                self.frames += 5
            return dict(control='player' if self.started and self.handoff else self.mode,
                        buttons=0, sticks=[0]*4, input_sequence=0, applied_sequence=0,
                        presents=self.frames, last_present_age_ms=0)
        if command == 'guest info':
            return dict(allowed=True, sequence=self.sequence + int(self.replaced), phase=self.phase)
        if command.startswith('guest cancel '):
            return dict(canceled=self.phase == 'pending')
        self.sequence += 1
        if command.startswith('guest string '):
            _, _, key, value = command.split()
            field = next(k for k, v in self.keys.items() if v == int(key, 16))
            self.fields[field] = bytes.fromhex(value).decode() if value != '-' else ''
        elif command.startswith('guest event '):
            self.started = True
        else:
            raise AssertionError(command)
        return dict(sequence=self.sequence, phase='pending')


class SceneLoadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api = FakeAPI(Path(self.temp.name))
        self.clock = Clock()
        p = patch.object(scene_load, 'time', self.clock)
        p.start()
        self.addCleanup(p.stop)

    def load(self, **kwargs):
        with patch.object(scene_load.scene_state, 'read_fields',
                          side_effect=lambda api, profile: api.scene_state(None)):
            return scene_load.load_scene(self.api, 'target', 'door', timeout=3, **kwargs)

    def test_transition_uses_bounded_event_wait(self):
        path = self.api.run / 'scene-bindings.json'
        profile = json.loads(path.read_text())
        profile['dispatch']['event_guard'] = dict(wait_ms=4000)
        path.write_text(json.dumps(profile))
        self.load()
        self.assertIn('guest event 77616974 wait 4000', self.api.calls)

    def test_invalid_event_wait_precedes_reservation(self):
        path = self.api.run / 'scene-bindings.json'
        profile = json.loads(path.read_text())
        for value in (True, 1999, 10001, '4000'):
            profile['dispatch']['event_guard'] = dict(wait_ms=value)
            path.write_text(json.dumps(profile))
            with self.assertRaises(ValueError):
                self.load()
            self.assertEqual(self.api.calls, [])

    def test_image_is_validated_once_per_transaction(self):
        original = scene_load.scene_state.validate_profile
        with patch.object(scene_load.scene_state, 'validate_profile', wraps=original) as validate:
            self.load()
        self.assertEqual(validate.call_count, 1)
        self.assertGreater(self.api.event_reads, 3)
        # Validation is not cached across separate requests.
        self.api.fields['current_scene'] = 'source'
        self.api.started = False
        (self.api.run / 'image.bin').write_bytes(b'changed image')
        before = list(self.api.calls)
        with self.assertRaises(ValueError):
            self.load()
        self.assertEqual(self.api.calls, before)

    def test_polling_keeps_the_validated_binding_snapshot(self):
        profiles = []
        def read(api, profile):
            profiles.append(profile)
            # A separate client replacing the file cannot alter an in-flight load.
            (api.run / 'scene-bindings.json').write_text('{}')
            return api.scene_state(None)
        with patch.object(scene_load.scene_state, 'read_fields', side_effect=read):
            result = scene_load.load_scene(self.api, 'target', 'door', timeout=3)
        self.assertEqual(result['status'], 'completed')
        self.assertGreater(len(profiles), 3)
        self.assertTrue(all(profile is profiles[0] for profile in profiles))
        self.assertEqual(profiles[0]['fields'], self.api.keys)

    def reload_fixture(self, *, replaced=True, busy=False):
        self.api.fields['current_scene'] = 'target'
        path = self.api.run / 'scene-bindings.json'
        profile = json.loads(path.read_text())
        profile.update(event_state={'fixture': True}, same_map_reload={'target': {'door': [{'name': 'landmark'}]}})
        path.write_text(json.dumps(profile))
        idle = dict(ready=True, active=False)
        self.api.event_state = lambda: idle
        actor = patch.object(scene_load, 'find_actor', side_effect=lambda *args:
                             dict(actor=100, holder=200, actor_id=2 if self.api.started and replaced else 1))
        event = patch.object(scene_load, 'read_event_state', return_value=dict(ready=True, active=busy))
        actor.start(); event.start()
        self.addCleanup(actor.stop); self.addCleanup(event.stop)

    def test_reload_requires_new_actor_generation_even_at_reused_address(self):
        self.reload_fixture()
        result = self.load()
        self.assertTrue(result['same_map_reload'])
        self.assertEqual(result['witness_before'][0]['actor'], result['witness_after'][0]['actor'])
        self.assertNotEqual(result['witness_before'][0]['actor_id'], result['witness_after'][0]['actor_id'])

    def test_reload_unchanged_actor_cannot_pass_on_frames_and_name(self):
        self.reload_fixture(replaced=False)
        with self.assertRaises(TimeoutError):
            self.load()
        report = json.loads(next(self.api.run.glob('scene-load-*.json')).read_text())
        self.assertEqual(report['status'], 'failed')

    def test_reload_unverified_entrance_never_mutates(self):
        self.reload_fixture()
        path = self.api.run / 'scene-bindings.json'
        profile = json.loads(path.read_text())
        profile['same_map_reload']['target']['other'] = profile['same_map_reload']['target'].pop('door')
        path.write_text(json.dumps(profile))
        with self.assertRaises(ValueError):
            self.load()
        self.assertFalse(any(c.startswith('guest string ') for c in self.api.calls))

    def test_reload_requires_every_witness_to_change(self):
        self.reload_fixture()
        path = self.api.run / 'scene-bindings.json'
        profile = json.loads(path.read_text())
        profile['same_map_reload']['target']['door'].append({'name': 'persistent'})
        path.write_text(json.dumps(profile))
        def actor(api, layout, selector):
            return dict(actor=100, holder=200, actor_id=2 if api.started and selector['name']=='landmark' else 1)
        with patch.object(scene_load, 'find_actor', side_effect=actor):
            with self.assertRaises(TimeoutError):
                self.load()

    def test_reload_waits_for_event_completion(self):
        self.reload_fixture(busy=True)
        with self.assertRaises(TimeoutError):
            self.load()

    def test_missing_reload_witness_never_mutates(self):
        self.reload_fixture()
        with patch.object(scene_load, 'find_actor', side_effect=RuntimeError('missing witness')):
            with self.assertRaisesRegex(RuntimeError, 'missing witness'):
                self.load()
        self.assertFalse(any(c.startswith('guest string ') for c in self.api.calls))

    def test_arrival_needs_state_and_frames(self):
        result = self.load()
        self.assertEqual(result['status'], 'completed')
        self.assertGreaterEqual(result['final_frame'] - result['arrived_frame'], 30)
        self.assertGreaterEqual(self.api.event_reads, 3)
        self.assertEqual(json.loads(Path(result['evidence']).read_text())['status'], 'completed')

    def test_ack_without_arrival_times_out(self):
        self.api.arrive = False
        with self.assertRaises(TimeoutError):
            self.load()
        report = json.loads(next(self.api.run.glob('scene-load-*.json')).read_text())
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(report['event_submitted'])

    def test_arrival_without_frames_times_out(self):
        self.api.progress = False
        with self.assertRaises(TimeoutError):
            self.load()

    def test_player_profile_and_ambiguous_entrance_never_mutate(self):
        self.api.info['profile_kind'] = 'player'
        with self.assertRaises(ValueError):
            self.load()
        self.api.info['profile_kind'] = 'analysis'
        self.api.unique = False
        with self.assertRaises(ValueError):
            self.load()
        self.assertEqual(self.api.calls, [])

    def test_wrong_image_never_dispatches(self):
        (self.api.run / 'image.bin').write_bytes(b'wrong image')
        with self.assertRaises(ValueError):
            self.load()
        self.assertEqual(self.api.calls, [])

    def test_pending_transition_and_same_map_rejected(self):
        self.api.fields['pending_scene'] = 'other'
        with self.assertRaises(RuntimeError):
            self.load()
        self.api.fields.update(pending_scene='', current_scene='target')
        with self.assertRaises(ValueError):
            self.load()
        self.assertFalse(any(c.startswith('guest string ') for c in self.api.calls))

    def test_handoff_cancels_without_claiming_arrival(self):
        self.api.handoff = True
        with self.assertRaisesRegex(RuntimeError, 'exclusive'):
            self.load()
        self.assertTrue(any(c.startswith('guest cancel ') for c in self.api.calls))

    def test_replaced_and_rejected_requests(self):
        self.api.replaced = True
        with self.assertRaisesRegex(RuntimeError, 'replaced'):
            self.load()
        report = json.loads(next(self.api.run.glob('scene-load-*.json')).read_text())
        request = report['requests'][-1]
        self.assertTrue(request['command'].startswith('guest string '))
        self.assertEqual(request['acknowledgement']['sequence'], 1)
        self.assertEqual(request['last_info'], dict(allowed=True, sequence=2, phase='dispatched'))
        self.assertEqual(report['dispatches'], [])
        self.api.replaced = False
        self.api.phase = 'rejected'
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            self.load()
        reports = [json.loads(p.read_text()) for p in self.api.run.glob('scene-load-*.json')]
        rejected = next(r for r in reports if r['error'] == 'Guest request rejected')
        self.assertEqual(rejected['requests'][-1]['last_info'],
                         dict(allowed=True, sequence=2, phase='rejected'))
        self.assertEqual(rejected['dispatches'], [])
        self.assertFalse(self.api.started)

    def test_queue_timeout_cancels(self):
        self.api.phase = 'pending'
        with self.assertRaises(TimeoutError):
            self.load()
        self.assertTrue(any(c.startswith('guest cancel ') for c in self.api.calls))
        self.assertFalse(self.api.started)

    def test_concurrent_scene_client_rejected(self):
        with (self.api.run / 'scene-load.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'already running'):
                self.load()
        self.assertEqual(self.api.calls, [])


class EventRequestTests(unittest.TestCase):
    setUp = SceneLoadTests.setUp
    def event(self):
        return scene_load.start_event(self.api, 'fixture-event', 'source', timeout=1)

    def test_default_timeout_tracks_event_wait_and_explicit_timeout_wins(self):
        path = self.api.run / 'scene-bindings.json'
        profile = json.loads(path.read_text())
        profile['dispatch']['event_guard'] = dict(wait_ms=4000)
        path.write_text(json.dumps(profile))
        request = self.api.request
        begin = self.clock.now
        def delayed(command):
            if command == 'guest info' and self.api.started:
                self.api.phase = 'dispatched' if self.clock.now - begin >= 3.5 else 'pending'
            return request(command)
        self.api.request = delayed
        result = scene_load.start_event(self.api, 'fixture-event', 'source')
        self.assertEqual(result['status'], 'dispatched')
        self.assertTrue(result['command'].endswith(' wait 4000'))
        begin = self.clock.now
        with self.assertRaises(TimeoutError):
            self.event()  # Explicit one-second client limit is preserved.
        self.assertLess(self.clock.now - begin, 1.1)
        self.assertTrue(any(c.startswith('guest cancel ') for c in self.api.calls))

    def test_event_dispatch_is_not_playback(self):
        result = self.event()
        self.assertEqual(result['status'], 'dispatched')
        self.assertFalse(result['playback_verified'])
        self.assertFalse(result['completion_verified'])
        self.assertEqual(json.loads(Path(result['evidence']).read_text())['status'], 'dispatched')

    def test_child_event_uses_configured_parent_sequence(self):
        path = self.api.run / 'scene-bindings.json'
        profile = json.loads(path.read_text())
        profile['event_sequences'] = {'fixture-event': dict(scene_id='source', entry_event='parent-sequence')}
        path.write_text(json.dumps(profile))
        result = self.event()
        self.assertEqual(result['event'], 'fixture-event')
        self.assertEqual(result['entry_event'], 'parent-sequence')
        self.assertTrue(result['uses_sequence'])
        self.assertIn('guest event ' + 'parent-sequence'.encode().hex(), self.api.calls)
        self.assertFalse(result['completion_verified'])
        profile['event_sequences']['fixture-event']['scene_id'] = 'wrong'
        path.write_text(json.dumps(profile))
        count = len(self.api.calls)
        with self.assertRaises(ValueError):
            self.event()
        self.assertEqual(len(self.api.calls), count)

    def test_event_wrong_map_and_image_never_dispatch(self):
        self.api.fields['current_scene'] = 'wrong'
        with self.assertRaisesRegex(RuntimeError, 'Required scene'):
            self.event()
        self.api.bad_image = True
        with self.assertRaises(ValueError):
            self.event()
        self.assertFalse(self.api.started)

    def test_event_rejection_timeout_and_handoff(self):
        self.api.phase = 'rejected'
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            self.event()
        report = json.loads(next(self.api.run.glob('event-request-*.json')).read_text())
        self.assertEqual(report['command'], 'guest event ' + 'fixture-event'.encode().hex())
        self.assertEqual(report['acknowledgement'], dict(sequence=1, phase='pending'))
        self.assertEqual(report['last_info'], dict(allowed=True, sequence=1, phase='rejected'))
        self.api.phase = 'pending'
        with self.assertRaises(TimeoutError):
            self.event()
        self.api.handoff = True
        with self.assertRaisesRegex(RuntimeError, 'exclusive'):
            self.event()
        self.assertTrue(any(c.startswith('guest cancel ') for c in self.api.calls))

    def test_event_uses_scene_transaction_lock(self):
        with (self.api.run / 'scene-load.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'already running'):
                self.event()
        self.assertFalse(self.api.started)


if __name__ == '__main__':
    unittest.main()
