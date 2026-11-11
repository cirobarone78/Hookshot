"""Exercise the native page's complete requests, isolation, and idle lifecycle."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

RUN_ALL_SKIP = {'windows': 'The optional external-layer adapter manages Linux/Wine processes.'}
ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api, control = load('dlss5_api'), load('dlss5_control')


class Session:
    def __init__(self, root):
        self.info = {'base': str(root), 'preferences_path': str(root / 'preferences.json')}
        self.values = {key: kind(low) for key, (low, high, kind) in api.SETTINGS.items()}
        self.values.update(enabled=1, applymodel=1, workingscale=.45, detail=.8, colour=1.4)
        self.calls = []
        self.helper_state, self.model_up = 4, 1
        self.fail = None

    def control(self, *args):
        self.calls.append(args)
        if args[0] == 'set':
            if args[1] == self.fail:
                raise subprocess.CalledProcessError(1, ['authored-shmctl'])
            self.values[args[1]] = api.setting_value(args[1], args[2])
            return {}
        if args[0] == 'settings':
            return dict(self.values)
        if args[0] == 'status':
            return dict(helper_state=self.helper_state, model_up=self.model_up)
        raise AssertionError(args)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.session = Session(self.root)
        self.bridge = control.ControlBridge(self.session, api.SETTINGS, api.setting_value, self.root / 'control',
                                            defaults=api.DEFAULT_SETTINGS)
        self.bridge._refresh(); self.bridge._publish()
        self.addCleanup(self.temp.cleanup)

    def request(self, sequence=1, **changes):
        data = dict(protocol=1, sequence=sequence, **self.bridge.values)
        data.update(changes)
        control.atomic_text(self.bridge.directory / 'request', ''.join(f'{key}={value}\n' for key, value in data.items()))

    def state(self):
        return control.fields(control.read_small(self.bridge.directory / 'state'))

    def test_complete_changes_persist_without_losing_other_rows(self):
        self.request(detail=125, workingscale=50, skinstructure=-100, mvecpixels=3)
        self.bridge.process_once()
        saved = json.loads((self.root / 'preferences.json').read_text())
        self.assertEqual(saved['detail'], 1.25)
        self.assertEqual(saved['workingscale'], .5)
        self.assertEqual(saved['skinstructure'], -1)
        self.assertEqual(saved['mvecpixels'], 3)
        self.assertEqual(saved['colour'], 1.4)
        self.assertEqual(self.state()['ack'], 1)
        self.assertEqual(self.state()['error'], 0)
        self.assertEqual(len(self.state()), len(api.SETTINGS) + 6)
        self.assertEqual(sum(call[0] == 'set' for call in self.session.calls), 3)

    def test_factory_reset_applies_all_settings_and_persists_one_request(self):
        # Every setting starts away from its default, including model rebuild
        # controls. The real bridge receives the complete native reset snapshot.
        for key, (low, high, kind) in api.SETTINGS.items():
            self.session.values[key] = kind(high if api.DEFAULT_SETTINGS[key] != high else low)
        self.bridge._refresh()
        defaults = {key: round(value * (100 if api.SETTINGS[key][2] is float else 1))
                    for key, value in api.DEFAULT_SETTINGS.items()}
        self.request(1, reset=1, **defaults)
        self.bridge.process_once()
        self.assertEqual(self.state()['ack'], 1)
        self.assertEqual(self.state()['error'], 0)
        self.assertEqual(self.session.values, api.DEFAULT_SETTINGS)
        self.assertEqual(json.loads((self.root / 'preferences.json').read_text()), api.DEFAULT_SETTINGS)
        self.assertEqual(sum(call[0] == 'set' for call in self.session.calls), len(api.SETTINGS))
        # The saved reset is also a valid complete startup preference snapshot.
        for key, value in json.loads((self.root / 'preferences.json').read_text()).items():
            self.assertEqual(api.setting_value(key, value), api.DEFAULT_SETTINGS[key])

    def test_factory_reset_discards_subcent_precision_and_rejects_other_snapshots(self):
        self.session.values.update(api.DEFAULT_SETTINGS)
        self.session.values['detail'] = 1.004  # displays the default 100%, but is not exactly 1.0
        self.bridge._refresh()
        defaults = {key: round(value * (100 if api.SETTINGS[key][2] is float else 1))
                    for key, value in api.DEFAULT_SETTINGS.items()}
        self.request(1, reset=1, **defaults); self.bridge.process_once()
        self.assertEqual(self.session.values['detail'], 1.0)
        self.assertEqual(json.loads((self.root / 'preferences.json').read_text()), api.DEFAULT_SETTINGS)
        calls = list(self.session.calls)
        for sequence, bad in enumerate((dict(defaults, detail=105, reset=1), dict(defaults, reset=0)), 2):
            self.request(sequence, **bad); self.bridge.process_once()
            self.assertEqual(self.state()['ack'], sequence)
            self.assertEqual(self.state()['error'], 1)
        self.assertEqual([call for call in self.session.calls if call[0] == 'set'],
                         [call for call in calls if call[0] == 'set'])
        self.assertEqual(json.loads((self.root / 'preferences.json').read_text()), api.DEFAULT_SETTINGS)

    def test_full_overwrite_preserves_rapid_changes_to_different_rows(self):
        self.request(1, detail=120)
        self.request(2, detail=120, colour=175)
        self.bridge.process_once()
        self.assertEqual(self.session.values['detail'], 1.2)
        self.assertEqual(self.session.values['colour'], 1.75)
        self.assertEqual(self.state()['ack'], 2)

    def test_untouched_preferences_keep_subcent_precision(self):
        self.session.values['colour'] = 1.437
        self.bridge._refresh()
        self.request(detail=120); self.bridge.process_once()
        saved = json.loads((self.root / 'preferences.json').read_text())
        self.assertEqual(saved['colour'], 1.437)
        self.assertFalse(any(call[:2] == ('set', 'colour') for call in self.session.calls))

    def test_stale_and_repeated_sequences_have_no_ipc_work(self):
        self.request(2, detail=120); self.bridge.process_once()
        calls = list(self.session.calls)
        self.request(1, detail=90); self.bridge.process_once()
        self.request(2, detail=90); self.bridge.process_once()
        self.assertEqual(self.session.calls, calls)
        self.assertEqual(self.state()['detail'], 120)

    def test_invalid_fields_reject_whole_request_and_acknowledge_error(self):
        for changed in ({'detail': 401}, {'workingscale': 24}, {'mvecpixels': 4}, {'protocol': 2}, {'unknown': 1}):
            with self.subTest(changed=changed):
                sequence = self.bridge.ack + 1
                self.request(sequence, **changed); self.bridge.process_once()
                self.assertEqual(self.state()['ack'], sequence)
                self.assertEqual(self.state()['error'], 1)
        self.assertFalse(any(call[0] == 'set' for call in self.session.calls))
        self.assertFalse((self.root / 'preferences.json').exists())

    def test_missing_duplicate_and_noninteger_fields_fail_closed(self):
        for transform in (lambda text: text.replace('detail=80\n', ''),
                          lambda text: text + 'detail=90\n',
                          lambda text: text.replace('detail=80', 'detail=0.8')):
            sequence = self.bridge.ack + 1
            self.request(sequence)
            path = self.bridge.directory / 'request'
            control.atomic_text(path, transform(path.read_text()))
            self.bridge.process_once()
            self.assertEqual(self.state()['ack'], sequence)
            self.assertEqual(self.state()['error'], 1)
        self.assertFalse(any(call[0] == 'set' for call in self.session.calls))

    def test_poll_refreshes_each_new_nonce_and_ignores_duplicates(self):
        path = self.bridge.directory / 'poll'
        self.session.values['detail'] = 1.6
        control.atomic_text(path, '1\n'); self.bridge.process_once()
        self.assertEqual(self.state()['detail'], 160)
        first = (self.bridge.directory / 'state').stat().st_mtime_ns
        calls = len(self.session.calls)
        control.atomic_text(path, '1\n'); self.bridge.process_once()
        self.assertEqual(len(self.session.calls), calls)
        control.atomic_text(path, '2\n'); self.bridge.process_once()
        self.assertGreater((self.bridge.directory / 'state').stat().st_mtime_ns, first)

    def test_helper_unavailable_prevents_changes(self):
        self.session.helper_state = 2
        self.request(detail=120); self.bridge.process_once()
        self.assertEqual(self.state()['available'], 0)
        self.assertEqual(self.state()['error'], 1)
        self.assertFalse(any(call[0] == 'set' for call in self.session.calls))

    def test_partial_external_failure_never_persists_full_request(self):
        self.session.fail = 'colour'
        self.request(detail=120, colour=175); self.bridge.process_once()
        self.assertEqual(self.state()['error'], 1)
        self.assertFalse((self.root / 'preferences.json').exists())
        self.assertEqual(self.session.values['detail'], 1.2)
        self.assertEqual(self.session.values['colour'], 1.4)
        self.assertEqual(self.state()['detail'], 120)
        self.session.fail = None
        self.request(2, detail=120, colour=175); self.bridge.process_once()
        self.assertEqual(self.state()['error'], 0)

    def test_oversized_symlink_and_fifo_are_bounded(self):
        path = self.bridge.directory / 'request'
        path.write_text('x' * 4097)
        with self.assertRaises(ValueError): control.read_small(path)
        path.unlink(); path.symlink_to(self.root / 'outside')
        with self.assertRaises(OSError): control.read_small(path)
        path.unlink(); os.mkfifo(path)
        start = time.monotonic()
        with self.assertRaises(ValueError): control.read_small(path)
        self.assertLess(time.monotonic() - start, .5)

    def test_idle_bridge_does_no_periodic_shmctl_work(self):
        self.bridge.start()
        calls = list(self.session.calls)
        time.sleep(.25)
        self.assertEqual(self.session.calls, calls)
        self.bridge.close()
        self.assertFalse(self.bridge.thread.is_alive())
        self.assertEqual(self.state()['available'], 0)
        self.assertEqual(self.session.calls, calls)


if __name__ == '__main__':
    unittest.main()
