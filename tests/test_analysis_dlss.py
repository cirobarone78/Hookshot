"""Launch an authored socket fixture through the real analysis/DLSS adapters.

No game, GPU, Wine or external binaries are used. The helper/runner are the
authored lifecycle fixtures from test_dlss5_api.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

RUN_ALL_SKIP = {'windows': 'Linux runtime API and Unix session isolation'}

if sys.platform != 'linux':
    print('SKIP: Linux-only analysis adapter')
    raise SystemExit(0)

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


analysis = module('analysis', ROOT / 'scripts/analysis_api.py')
dlss_fixture = (module('dlss_fixture', ROOT / 'tests/test_dlss5_api.py')
                if (ROOT / 'scripts/dlss5_api.py').is_file() and (ROOT / 'tests/test_dlss5_api.py').is_file() else None)


@unittest.skipUnless(dlss_fixture is not None, 'optional DLSS adapter and authored fixture are not installed')
class AnalysisDLSSTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='hookshot-analysis-dlss-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / 'work/dlss5'
        self.base.mkdir(parents=True)
        dlss_fixture.AdapterTests().fixture(self.base)
        (self.root / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/dlss5_api.py', self.root / 'scripts/dlss5_api.py')
        control = ROOT / 'scripts/dlss5_control.py'
        if control.is_file():
            shutil.copy2(control, self.root / 'scripts/dlss5_control.py')
        self.prefs = self.base / 'preferences.json'
        self.prefs.write_text('{"workingscale": 0.7, "style": 2, "intensity": 1.2}\n')
        self.game = self.root / 'game'
        (self.game / 'bin').mkdir(parents=True)
        (self.game / 'image.bin').write_bytes(b'authored fixture, not a game image')
        (self.game / 'romfs').mkdir()
        (self.game / 'hookshot_options.ini').write_text('frame_generation=3\n')
        exe = self.game / 'bin/hookshot'
        exe.write_text(f'#!{sys.executable}\n' + '''import json,os,socket,sys
from pathlib import Path
Path(__file__).with_name('observed.json').write_text(json.dumps({'argv':sys.argv,'env':dict(os.environ)}))
server=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET)
server.bind('\\0'+os.environ['HOS_DEBUG_SOCKET'])
server.listen()
while True:
 connection,_=server.accept()
 with connection:
  command=connection.recv(512)
  connection.sendall(b'{"ok":true,"presents":1,"last_present_age_ms":0}')
''')
        exe.chmod(0o700)
        self.save = self.root / 'source-save'
        self.save.mkdir()
        (self.save / 'account.sav').write_bytes(b'authored account fixture')
        self.root_patch = patch.object(analysis, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def launch(self, **options):
        api = analysis.HookshotAPI.launch(self.game, self.save, **options)
        self.addCleanup(self.stop, api)
        return api

    def stop(self, api):
        api.stop()
        deadline = time.monotonic() + 10
        while analysis.process_stamp(api.info['launcher_pid']) == api.info['launcher_start_ticks']:
            if time.monotonic() >= deadline:
                self.fail('analysis wrapper did not finish cleanup')
            time.sleep(.02)

    def test_dlss_uses_copied_settings_and_save_with_native_pid(self):
        original = self.prefs.read_bytes()
        api = self.launch(dlss5=True, frame_generation=0, profile=True)
        observed = json.loads((self.game / 'bin/observed.json').read_text())
        env = observed['env']
        self.assertEqual(env['DLSSNR_TIME'], '1')
        self.assertEqual(env['DLSSNR_TIME_EVERY'], '30')
        for key, value in {'HOS_START_MINIMIZED': '1', 'HOS_AUDIO': '0', 'HOS_ASPECT': '0', 'HOS_REQUIRE_WINDOW': '1',
                           'HOS_FULLSCREEN': '0', 'RX_VK_FRAMEGEN': '0'}.items():
            self.assertEqual(env[key], value)
        self.assertEqual(api.request('status')['presents'], 1)  # includes SO_PEERCRED PID validation
        self.assertEqual(api.info['profile_kind'], 'analysis')
        self.assertNotEqual(api.info['pid'], api.info['launcher_pid'])
        session = dlss_fixture.api.DLSS5Session(api.info['dlss5_session'])
        prefs = Path(session.info['preferences_path'])
        self.assertEqual(prefs, api.run / 'dlss5-preferences.json')
        self.assertEqual(json.loads(prefs.read_text()), json.loads(original))
        controls = self.base / 'recorded-settings'
        self.assertIn('workingscale 0.7', controls.read_text().splitlines())
        settings = {key: low for key, (low, high, kind) in dlss_fixture.api.SETTINGS.items()}
        with patch.object(session, 'control', return_value=settings):
            session.save_preferences()
        self.assertEqual(json.loads(prefs.read_text()), settings)
        self.assertEqual(self.prefs.read_bytes(), original)
        profile = Path(observed['argv'][observed['argv'].index('--user') + 1])
        copied = profile / 'save' / analysis.HOOKSHOT_UID / 'account.sav'
        self.assertEqual(copied.read_bytes(), (self.save / 'account.sav').read_bytes())
        self.assertNotEqual(copied.parent, self.save)
        copied.write_bytes(b'analysis-only save change')
        self.assertEqual((self.save / 'account.sav').read_bytes(), b'authored account fixture')
        self.stop(api)
        self.assertTrue((self.base / 'prefix/pfx/server-stopped').is_file())
        self.assertEqual((self.game / 'hookshot_options.ini').read_text(), 'frame_generation=3\n')

    def test_candidate_integration_is_separate_from_default(self):
        candidate = self.root / 'candidate'
        candidate.mkdir()
        dlss_fixture.AdapterTests().fixture(candidate)
        (candidate / 'preferences.json').write_text('{"workingscale": 0.6}')
        original = self.prefs.read_bytes()
        api = self.launch(dlss5=True, dlss_base=candidate)
        session = dlss_fixture.api.DLSS5Session(api.info['dlss5_session'])
        self.assertEqual(Path(session.info['base']), candidate)
        self.assertEqual(self.prefs.read_bytes(), original)
        self.assertIn('workingscale 0.6', (candidate/'recorded-settings').read_text())
        self.assertFalse((self.base/'runs').exists())

    def test_dlss_timing_rejects_missing_bridge_and_nonboolean(self):
        with self.assertRaisesRegex(ValueError, 'requires dlss5'):
            self.launch(dlss_timing=True)
        with self.assertRaisesRegex(ValueError, 'must be boolean'):
            self.launch(dlss5=True, dlss_timing=1)

    def test_dlss_timing_without_cpu_profiler(self):
        api = self.launch(dlss5=True, dlss_timing=True)
        env = json.loads((self.game / 'bin/observed.json').read_text())['env']
        self.assertEqual(env['DLSSNR_TIME'], '1')
        self.assertEqual(env['DLSSNR_TIME_EVERY'], '30')
        self.assertNotIn('HOS_PROFILE', env)
        self.assertNotIn('HOS_SAMPLE_ALL', env)
        self.stop(api)

    def test_plain_analysis_clears_inherited_dlss_and_selects_multiplier(self):
        with patch.dict(os.environ, VK_INSTANCE_LAYERS='unwanted', VK_ADD_LAYER_PATH='/unwanted',
                        VKLayer_DLSS5='1', DLSSNR_SHM='/unwanted', HOS_AUDIO='1', RX_VK_PRESENT_STAGES='1', RX_VK_WB_DIFF='1'):
            api = self.launch(frame_generation=3)
        env = json.loads((self.game / 'bin/observed.json').read_text())['env']
        for key in ('VK_INSTANCE_LAYERS', 'VK_ADD_LAYER_PATH', 'VKLayer_DLSS5', 'DLSSNR_SHM'):
            self.assertNotIn(key, env)
        self.assertEqual(env['RX_VK_FRAMEGEN_MULT'], '3')
        self.assertEqual(env['RX_VK_FRAMEGEN'], '1')
        for key in ('RX_VK_WB_DIFF', 'RX_VK_PRESENT_STAGES', 'HOS_PRESENT_TRACE', 'HOS_FPS_TARGET', 'RX_VK_STAGE_CACHE', 'HOS_PROFILE', 'HOS_SAMPLE_ALL'):
            self.assertNotIn(key, env)
        self.assertFalse(api.info['dlss5_enabled'])
        self.assertFalse((self.base / 'runs').exists())

    def test_writeback_diff_explicit_on_and_off(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                api = self.launch(writeback_diff=enabled)
                env = json.loads((self.game / 'bin/observed.json').read_text())['env']
                self.assertEqual(env['RX_VK_WB_DIFF'], '1' if enabled else '0')
                self.assertEqual(api.info['environment']['RX_VK_WB_DIFF'], env['RX_VK_WB_DIFF'])
                api.stop()

    def test_writeback_diff_rejects_non_booleans(self):
        for value in (0, 1, 'on', [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.launch(writeback_diff=value)

    def test_cpu_snapshot_policy_is_explicit(self):
        for enabled in (None, False, True):
            with self.subTest(enabled=enabled):
                api = self.launch(cpu_uncached=enabled)
                env = json.loads((self.game / 'bin/observed.json').read_text())['env']
                if enabled is None:
                    self.assertNotIn('RX_VK_CAPTURE_CPU_UNCACHED', env)
                else:
                    self.assertEqual(env['RX_VK_CAPTURE_CPU_UNCACHED'], '1' if enabled else '0')
                api.stop()
        for value in (0, 1, 'on', [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.launch(cpu_uncached=value)

    def test_trace_and_fps_target_are_private_explicit_overrides(self):
        api = self.launch(present_trace=True, present_stages=True, stage_trace=True, fps_target=120, stage_cache=False, profile=True)
        env = json.loads((self.game / 'bin/observed.json').read_text())['env']
        self.assertEqual(env['HOS_PRESENT_TRACE'], str(api.run / 'native-presents.csv'))
        self.assertEqual(env['RX_VK_PRESENT_STAGES'], '1')
        self.assertEqual(env['RX_VK_STAGE_TRACE'], str(api.run / 'renderer-stages.csv'))
        self.assertEqual(api.info['environment']['RX_VK_PRESENT_STAGES'], '1')
        self.assertEqual(env['HOS_FPS_TARGET'], '120')
        self.assertEqual(env['RX_VK_STAGE_CACHE'], '0')
        self.assertEqual(env['RX_VK_SLOW_LOG'], '20')
        self.assertEqual(env['HOS_SAMPLE_ALL'], str(api.run / 'stacks.txt'))
        self.assertEqual(api.info['environment']['HOS_PRESENT_TRACE'], env['HOS_PRESENT_TRACE'])

    def test_stage_trace_also_enables_native_intervals(self):
        api = self.launch(stage_trace=True)
        env = json.loads((self.game / 'bin/observed.json').read_text())['env']
        self.assertEqual(env['RX_VK_STAGE_TRACE'], str(api.run / 'renderer-stages.csv'))
        self.assertEqual(env['HOS_PRESENT_TRACE'], str(api.run / 'native-presents.csv'))

    def test_scene_bindings_are_image_checked_and_copied(self):
        binding = dict(schema=1, image_sha256=hashlib.sha256((self.game / 'image.bin').read_bytes()).hexdigest(),
                       manager_pointer=512, dispatch=dict(build_id='1' * 40, thread='worker',
                                                         string_setter=256, event_helper=260))
        binding['dispatch']['scalar_calls'] = dict(bool_set=264, bool_get=268, int_set=272, int_get=276)
        binding['dispatch']['event_context'] = {key: i + 1 for i, key in enumerate(analysis.EVENT_CONTEXT_FIELDS)}
        guard = dict.fromkeys(analysis.EVENT_GUARD_FIELDS, 0)
        guard.update(root_slot=512, flag0_mask=8, flag1_mask=4)
        guard['state'] = dict(container_offset=32, state_offset=16, value_offset=4, alias_value=99, alias_offset=8, blocked_values=[7, 8])
        binding['dispatch']['event_guard'] = guard
        path = self.root / 'bindings.json'
        path.write_text(json.dumps(binding))
        api = self.launch(scene_bindings=path)
        env = json.loads((self.game / 'bin/observed.json').read_text())['env']
        self.assertEqual(env['HOS_DEBUG_SCENE_CALL'], '1' * 40 + ':100:200:worker')
        self.assertEqual(env['HOS_DEBUG_SCENE_EVENT'], '104')
        self.assertEqual(env['HOS_DEBUG_SCALAR_CALLS'], '108:10c:110:114')
        self.assertEqual(env['HOS_DEBUG_EVENT_CONTEXT'], ':'.join(format(i + 1, 'x') for i in range(len(analysis.EVENT_CONTEXT_FIELDS))))
        self.assertEqual(env['HOS_DEBUG_EVENT_GUARD'], '200:0:0:0:0:0:0:0:0:0:8:0:4')
        self.assertEqual(env['HOS_DEBUG_EVENT_STATE_GUARD'], '20:10:4:63:8:7:8')
        self.assertEqual(json.loads((api.run / 'scene-bindings.json').read_text()), binding)
        self.stop(api)
        binding['image_sha256'] = 'stale'
        path.write_text(json.dumps(binding))
        with self.assertRaisesRegex(ValueError, 'another game image'):
            self.launch(scene_bindings=path)

    def test_scene_dispatch_does_not_leak_from_environment(self):
        with patch.dict(os.environ, {'HOS_DEBUG_EVENT_STATE_GUARD': 'inherited', 'HOS_DEBUG_EVENT_GUARD': 'inherited', 'HOS_DEBUG_SCENE_CALL': 'inherited', 'HOS_DEBUG_SCENE_EVENT': '123', 'HOS_DEBUG_EVENT_CONTEXT': 'inherited', 'HOS_DEBUG_SCALAR_CALLS': 'inherited'}):
            api = self.launch()
        env = json.loads((self.game / 'bin/observed.json').read_text())['env']
        self.assertNotIn('HOS_DEBUG_EVENT_GUARD', env)
        self.assertNotIn('HOS_DEBUG_EVENT_STATE_GUARD', env)
        self.assertNotIn('HOS_DEBUG_SCENE_CALL', env)
        self.assertNotIn('HOS_DEBUG_SCENE_EVENT', env)
        self.assertNotIn('HOS_DEBUG_EVENT_CONTEXT', env)
        self.assertNotIn('HOS_DEBUG_SCALAR_CALLS', env)
        self.assertFalse((api.run / 'scene-bindings.json').exists())

    def test_invalid_event_guard_profile(self):
        valid = dict.fromkeys(analysis.EVENT_GUARD_FIELDS, 0)
        valid.update(root_slot=512, flag0_mask=8, flag1_mask=4)
        for key, value in (('root_slot', True), ('root_slot', 513), ('root_slot', 0),
                           ('root_slot', 1 << 39), ('owner_offset', -1),
                           ('component_offset', 4097), ('flag0_mask', 0),
                           ('flag1_mask', 256), ('actor_id_offset', '24'), ('wait_ms', True), ('wait_ms', 1999), ('wait_ms', 10001)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                analysis.encode_event_guard(dict(valid, **{key: value}))
        del valid['actor_holder_offset']
        with self.assertRaises(ValueError):
            analysis.encode_event_guard(valid)

    def test_invalid_event_state_guard_profile(self):
        valid = dict(container_offset=32, state_offset=16, value_offset=4,
                     alias_value=99, alias_offset=8, blocked_values=[7, 8])
        for key, value in (('container_offset', True), ('state_offset', -1),
                           ('value_offset', 4097), ('alias_value', 1 << 32),
                           ('alias_offset', '8'), ('blocked_values', []),
                           ('blocked_values', [0] * 17), ('blocked_values', [True]),
                           ('blocked_values', [-1]), ('blocked_values', [1 << 32]),
                           ('blocked_values', '7')):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                analysis.encode_event_state_guard(dict(valid, **{key: value}))
        for bad in (None, {}, [], 1):
            with self.assertRaises(ValueError):
                analysis.encode_event_state_guard(bad)

    def test_saved_aspect_uses_game_options_without_parent_override(self):
        options = self.game / 'hookshot_options.ini'
        options.write_text('frame_generation=3\nultrawide=1\nresolution=1\n')
        original = options.read_bytes()
        with patch.dict(os.environ, {'HOS_ASPECT': '1.25'}):
            api = self.launch(saved_aspect=True)
        observed = json.loads((self.game / 'bin/observed.json').read_text())
        self.assertNotIn('HOS_ASPECT', observed['env'])
        self.assertEqual(observed['env']['HOS_FULLSCREEN'], '0')
        self.assertEqual(options.read_bytes(), original)
        self.assertEqual(api.info['profile_kind'], 'analysis')

    def test_invalid_benchmark_options_do_not_launch(self):
        for value in (None, 0, 1, 'yes'):
            with self.subTest(saved_aspect=value), self.assertRaises(ValueError):
                self.launch(saved_aspect=value)
        for value in (0, 59, 241, True, 60.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.launch(fps_target=value)
        with self.assertRaises(ValueError):
            self.launch(present_trace='yes')
        for value in (0, 1, 'yes', None):
            with self.subTest(present_stages=value), self.assertRaises(ValueError):
                self.launch(present_stages=value)
        self.assertFalse((self.game / 'bin/observed.json').exists())

    def test_game_lock_prevents_even_helper_start(self):
        with (self.root / 'work/local-game.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(RuntimeError):
                self.launch(dlss5=True)
        self.assertFalse((self.base / 'runs').exists())
        self.assertFalse((self.game / 'bin/observed.json').exists())

    def test_invalid_multiplier_never_starts_any_process(self):
        for value in (-1, 1, 9, True, 2.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.launch(dlss5=True, frame_generation=value)
        self.assertFalse((self.base / 'runs').exists())
        self.assertFalse((self.game / 'bin/observed.json').exists())


if __name__ == '__main__':
    unittest.main()
