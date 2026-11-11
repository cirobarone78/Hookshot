#!/usr/bin/env python3
"""Game-free lifecycle checks for the opt-in external DLSS helper adapter."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

RUN_ALL_SKIP = {'windows': 'Linux Vulkan-layer adapter and private Proton lifecycle'}

if sys.platform != 'linux':
    print('SKIP: Linux-only adapter')
    raise SystemExit(0)

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('dlss5_api', ROOT / 'scripts/dlss5_api.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class AdapterTests(unittest.TestCase):
    def test_live_transport_survives_helper_death_and_metadata_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            cfg = self.fixture(base)
            shm = base / 'shm.bin'
            shm.touch(); shm.with_suffix('.ready').touch()
            path = base / 'session.json'
            info = dict(base=str(base), prefix=str(base / 'prefix'), shm=str(shm),
                        shmctl=cfg['artifacts']['shmctl']['path'],
                        helper_launcher_pid=os.getpid(), helper_launcher_start_ticks='stale')
            path.write_text(json.dumps(info))
            session = api.DLSS5Session(path)
            status = session.status()
            self.assertFalse(status['launcher_alive'])
            self.assertNotIn('archived', status)
            self.assertEqual(status['helper_state'], 4)
            info['helper_launcher_start_ticks'] = api.process_stamp(os.getpid())
            path.write_text(json.dumps(info))
            self.assertTrue(session.status()['launcher_alive'])
            info['shm'] = str(base / 'different-session')
            path.write_text(json.dumps(info))
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                session.status()

    def test_replacement_wait_is_bounded_and_never_waits_on_reused_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            info = dict(helper_launcher_pid=os.getpid(), helper_launcher_start_ticks=api.process_stamp(os.getpid()))
            path.write_text(json.dumps(info))
            session = api.DLSS5Session(path)
            start = time.monotonic()
            self.assertFalse(api.wait_replacement_helper(session, -1, 'original', timeout=.04))
            self.assertLess(time.monotonic() - start, 1)
            info['helper_launcher_start_ticks'] = 'stale'
            path.write_text(json.dumps(info))
            with patch.object(api.time, 'sleep') as sleep:
                self.assertTrue(api.wait_replacement_helper(session, -1, 'original'))
                sleep.assert_not_called()
            self.assertTrue(api.wait_replacement_helper(session, os.getpid(), 'stale'))

    def test_replacement_finishes_before_server_and_transport_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='hookshot dlss replacement ') as directory:
            base = Path(directory)
            self.fixture(base)
            target = base / 'replace-helper.py'
            target.write_text('''import importlib.util,json,os,signal,subprocess,sys,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('adapter',sys.argv[1]);api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
base=Path(sys.argv[2]);path=Path(os.environ['HOS_DLSS5_SESSION']);info=json.loads(path.read_text())
os.kill(info['helper_launcher_pid'],signal.SIGTERM)
deadline=time.monotonic()+5
while api.process_stamp(info['helper_launcher_pid'])==info['helper_launcher_start_ticks']:
 if time.monotonic()>deadline:raise RuntimeError('fixture original helper did not exit')
 time.sleep(.01)
code="""import sys,time
from pathlib import Path
shm=Path(sys.argv[1]);base=Path(sys.argv[2]);(base/'replacement-ready').touch()
while not shm.with_suffix('.quit').exists():time.sleep(.01)
time.sleep(.2) # Model and exported descriptor teardown after quit.
if not shm.is_file() or (base/'prefix/pfx/server-stopped').exists():
 (base/'replacement-premature-cleanup').touch()
(base/'replacement-finished').touch()
"""
helper=subprocess.Popen([sys.executable,'-I','-c',code,info['shm'],str(base)],start_new_session=True)
while not (base/'replacement-ready').exists():
 if helper.poll() is not None or time.monotonic()>deadline:raise RuntimeError('fixture replacement did not start')
 time.sleep(.01)
info.update(helper_launcher_pid=helper.pid,helper_launcher_start_ticks=api.process_stamp(helper.pid))
tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(info));tmp.replace(path)
''')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(api.run(base, [sys.executable, '-I', str(target),
                                               str(ROOT / 'scripts/dlss5_api.py'), str(base)]), 0)
            self.assertTrue((base / 'replacement-finished').is_file())
            self.assertFalse((base / 'replacement-premature-cleanup').exists())
            self.assertTrue((base / 'prefix/pfx/server-stopped').is_file())
            session = api.DLSS5Session(next((base / 'runs').glob('*/session.json')))
            self.assertFalse(Path(session.info['shm']).exists())
            self.assertTrue(session.status()['archived'])

    def test_server_cleanup_accepts_absence_only_after_wait(self):
        for code in (0, 1):
            with self.subTest(code=code), patch.object(api.subprocess, 'run') as run:
                run.return_value = api.subprocess.CompletedProcess(['server', '-k'], code, '', '')
                env = {'WINEPREFIX': '/private/prefix'}
                api.stop_private_server(Path('/private/wineserver'), env)
                self.assertEqual([call.args[0][-1] for call in run.call_args_list], ['-k', '-w'])
                self.assertTrue(all(call.kwargs['env'] is env for call in run.call_args_list))
                self.assertEqual(run.call_args_list[1].kwargs['timeout'], 10)
                self.assertTrue(run.call_args_list[1].kwargs['check'])

    def test_server_cleanup_preserves_errors(self):
        for code, diagnostic in ((1, 'permission denied'), (2, ''), (-9, '')):
            with self.subTest(code=code), patch.object(api.subprocess, 'run') as run:
                run.return_value = api.subprocess.CompletedProcess(['server', '-k'], code, '', diagnostic)
                with self.assertRaises(api.subprocess.CalledProcessError):
                    api.stop_private_server(Path('/private/wineserver'), {})
                self.assertEqual(run.call_count, 1)

    def test_server_cleanup_rejects_unfinished_shutdown(self):
        for error in (api.subprocess.TimeoutExpired(['server', '-w'], 10),
                      api.subprocess.CalledProcessError(1, ['server', '-w'])):
            with self.subTest(error=type(error)), patch.object(api.subprocess, 'run') as run:
                run.side_effect = [api.subprocess.CompletedProcess(['server', '-k'], 1, '', ''), error]
                with self.assertRaises(type(error)):
                    api.stop_private_server(Path('/private/wineserver'), {})

    def fixture(self, base):
        runner = base / 'runner/proton'
        runner.parent.mkdir()
        runner.write_text(f'#!{sys.executable}\n' + f'fixture_dir = {str(base)!r}\n' + '''import os,time,json
from pathlib import Path
shm=Path(os.environ['DLSSNR_SHM'])
(Path(fixture_dir)/'helper-env.json').write_text(json.dumps(dict(os.environ)))
if os.environ.get('FAKE_START_FAILURE'): raise SystemExit(2)
shm.with_suffix('.ready').touch()
while not shm.with_suffix('.quit').exists(): time.sleep(.01)
assert shm.is_file(), 'transport removed while helper still needs it'
(Path(fixture_dir)/'helper-finished').touch()
''')
        runner.chmod(0o700)
        server = runner.parent / 'files/bin/wineserver'
        server.parent.mkdir(parents=True)
        server.write_text(f'#!{sys.executable}\n' + '''import os
from pathlib import Path
prefix=Path(os.environ['WINEPREFIX'])
prefix.mkdir(parents=True,exist_ok=True)
(prefix/'server-stopped').write_text(str(prefix))
''')
        server.chmod(0o700)
        ctl = base / 'shmctl'
        ctl.write_text(f'#!{sys.executable}\n' + f'fixture_dir = {str(base)!r}\n' + '''import sys
from pathlib import Path
shm=Path(sys.argv[1]);cmd=sys.argv[2]
if cmd=='status': print('helper_state='+('4' if shm.with_suffix('.ready').exists() else '5'))
elif cmd=='quit': shm.with_suffix('.quit').touch()
elif cmd=='resume': shm.touch()
elif cmd=='set':
 with (Path(fixture_dir)/'recorded-settings').open('a') as f: f.write(' '.join(sys.argv[3:])+'\\n')
''')
        ctl.chmod(0o700)
        model = base / 'fake model.dll'
        model.write_bytes(b'authored fixture, not a DLL')
        cfg = dict(version='fixture', proton=str(runner), steam_root=str(base / 'steam'),
                   artifacts={key: dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                              for key, path in [('helper', model), ('model', model), ('layer', model), ('shmctl', ctl)]})
        (base / 'integration.json').write_text(json.dumps(cfg))
        return cfg

    def test_failed_target_cleans_up_only_private_helper(self):
        with tempfile.TemporaryDirectory(prefix='hookshot dlss ') as directory:
            base = Path(directory)
            self.fixture(base)
            original = dict(os.environ)
            child_env = base / 'child-env.json'
            command = [sys.executable, '-I', '-c',
                       'import json,os,sys;open(sys.argv[1],"w").write(json.dumps(dict(os.environ)));sys.exit(7)',
                       str(child_env)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(api.run(base, command), 7)
            run = next((base / 'runs').iterdir())
            self.assertTrue((base / 'helper-finished').is_file())
            self.assertTrue((base / 'prefix/pfx/server-stopped').is_file())
            self.assertEqual(dict(os.environ), original)
            env = json.loads(child_env.read_text())
            self.assertEqual(env['HOS_DLSS5_CONTROL'], str(run / 'control'))
            self.assertNotIn('HOS_DLSS5_MENU', env)
            self.assertIn('available=0', (run / 'control/state').read_text())
            self.assertEqual(env['HOME'], original['HOME'])
            shared = Path(env['DLSSNR_SHM'])
            self.assertEqual(shared.parent.parent, Path('/dev/shm'))
            self.assertFalse(shared.parent.exists())
            self.assertFalse((run / 'shm.bin').exists())
            helper_env = json.loads((base / 'helper-env.json').read_text())
            self.assertEqual(helper_env['DLSSNR_SHM'], str(shared))
            self.assertIn(api.LAYER, env['VK_INSTANCE_LAYERS'].split(':'))
            self.assertEqual(json.loads((run / 'result.json').read_text())['exit_code'], 7)
            settings = (base / 'recorded-settings').read_text().splitlines()
            self.assertIn('bypass 0', settings)
            self.assertIn('transfer 2', settings)
            self.assertIn('workingscale 0.5', settings)
            session = api.DLSS5Session(run / 'session.json')
            self.assertEqual(session.info['shm'], str(shared))
            with patch.object(api.subprocess, 'run') as control:
                self.assertFalse(session.status()['launcher_alive'])
                self.assertTrue(session.status()['archived'])
                with self.assertRaises(RuntimeError):
                    session.set('enabled', 1)
                control.assert_not_called()

    def test_initialization_failure_never_launches_target(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self.fixture(base)
            target_marker = base / 'target-started'
            with patch.dict(os.environ, FAKE_START_FAILURE='1'), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    api.run(base, [sys.executable, '-c',
                                   'from pathlib import Path;import sys;Path(sys.argv[1]).touch()', str(target_marker)])
            self.assertFalse(target_marker.exists())
            self.assertTrue((base / 'prefix/pfx/server-stopped').is_file())
            session = json.loads(next((base / 'runs').glob('*/session.json')).read_text())
            self.assertFalse(Path(session['shm']).parent.exists())

    def test_changed_model_is_rejected_before_start(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            cfg = self.fixture(base)
            Path(cfg['artifacts']['model']['path']).write_bytes(b'changed')
            with self.assertRaises(ValueError):
                api.run(base, ['not-executed'])
            self.assertFalse((base / 'runs').exists())

    def test_helper_does_not_inherit_layer_or_game_switches(self):
        parent = dict(HOME='/original', HOS_AUDIO='1', RX_BACKEND='vulkan',
                      VK_INSTANCE_LAYERS=api.LAYER, VKLayer_DLSS5='1', DLSSNR_SHM='/wrong',
                      DLSSNR_TIME='1', DLSSNR_TIME_EVERY='30')
        cfg = dict(steam_root='/steam', artifacts={'model': {'path': '/private/model.dll'}})
        env = api.helper_environment(parent, Path('/private'), Path('/private/run'), cfg, Path('/dev/shm/private/shm.bin'))
        self.assertEqual(env['DLSSNR_TIME'], '1')
        self.assertEqual(env['DLSSNR_TIME_EVERY'], '30')
        self.assertEqual(env['HOME'], '/original')
        self.assertEqual(env['WINEPREFIX'], '/private/prefix/pfx')
        self.assertEqual(env['DLSSNR_DISABLE'], '1')
        for key in ('HOS_AUDIO', 'RX_BACKEND', 'VK_INSTANCE_LAYERS', 'VKLayer_DLSS5'):
            self.assertNotIn(key, env)
        self.assertEqual(parent['DLSSNR_SHM'], '/wrong')

    def test_transport_is_private_tmpfs_and_lives_through_the_session(self):
        with api.shared_transport() as first, api.shared_transport() as second:
            self.assertNotEqual(first.parent, second.parent)
            self.assertEqual(stat.S_IMODE(first.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
            with first.open('r+b') as f:
                self.assertEqual(api.filesystem_type(f.fileno()), 0x01021994)
                f.write(b'authored shared memory payload')
            self.assertEqual(first.read_bytes(), b'authored shared memory payload')
        self.assertFalse(first.parent.exists())
        self.assertFalse(second.parent.exists())

    def test_disk_filesystem_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self.fixture(base)
            with patch.object(api, 'filesystem_type', return_value=0x9123683E), \
                    patch.object(api.subprocess, 'Popen') as process:
                with self.assertRaisesRegex(RuntimeError, 'tmpfs'):
                    api.run(base, ['not-executed'])
                process.assert_not_called()
            self.assertFalse((base / 'runs').exists())

    def test_invalid_live_values_do_not_reach_shared_memory(self):
        session = object.__new__(api.DLSS5Session)
        with patch.object(session, 'control') as control:
            for key, value in [('enabled', '0.5'), ('detail', 'nan'), ('colour', 'inf'), ('sharpness', '-1')]:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    session.set(key, value)
            control.assert_not_called()

    def test_flow_enums_reach_only_the_selected_session(self):
        session = object.__new__(api.DLSS5Session)
        with patch.object(session, 'control') as control, patch.object(session, 'status', return_value={'fixture': True}):
            for key, values in [('mvecquality', range(3)), ('mvecpixels', range(4))]:
                for value in values:
                    with self.subTest(key=key, value=value):
                        self.assertEqual(session.set(key, str(value)), {'fixture': True})
                        control.assert_called_with('set', key, str(value))

    def test_invalid_flow_enums_never_reach_ipc(self):
        session = object.__new__(api.DLSS5Session)
        with patch.object(session, 'control') as control:
            for key, upper in [('mvecquality', 2), ('mvecpixels', 3)]:
                for value in [-1, upper + 1, 0.5, 'nan', 'inf', '-inf']:
                    with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                        session.set(key, value)
            control.assert_not_called()

    def test_explicit_flow_preferences_reach_helper_before_target(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self.fixture(base)
            preferences = base / 'flow-preferences.json'
            preferences.write_text(json.dumps({'mvecquality': 1, 'mvecpixels': 2}))
            original = preferences.read_bytes()
            # Authored fake runner/control only; the child checks the observed commands.
            command = [sys.executable, '-I', '-c',
                       'import pathlib,sys; s=pathlib.Path(sys.argv[1]).read_text(); '
                       'assert "mvecquality 1" in s and "mvecpixels 2" in s',
                       str(base / 'recorded-settings')]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(api.run(base, command, preferences), 0)
            self.assertEqual(preferences.read_bytes(), original)

    def test_preferences_preserve_model_style_and_native_details(self):
        with tempfile.TemporaryDirectory() as directory:
            session = object.__new__(api.DLSS5Session)
            session.info = {'base': directory}
            settings = {key: low for key, (low, high, kind) in api.SETTINGS.items()}
            settings.update(style=2, preset=3, intensity=1.66, localstructure=1.48,
                            bypass=0, transfer=2, workingscale=.5, mvecquality=1, mvecpixels=2)
            with patch.object(session, 'control', return_value=settings):
                session.save_preferences()
            saved = json.loads((Path(directory) / 'preferences.json').read_text())
            self.assertEqual(saved, settings)
            settings['workingscale'] = 0
            with patch.object(session, 'control', return_value=settings), self.assertRaises(ValueError):
                session.save_preferences()
            self.assertEqual(json.loads((Path(directory) / 'preferences.json').read_text()), saved)


if __name__ == '__main__':
    unittest.main()
