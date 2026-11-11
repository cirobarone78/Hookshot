#!/usr/bin/env python3
"""Opt-in, workspace-local DLSS5VKLayer launcher and structured telemetry.

The external layer/helper and the user's model stay in ignored work/. Nothing is
registered in the desktop session. Each run gets its own IPC file and logs; only
the dedicated Proton prefix is reused. A helper being ready is not model success.
"""
import argparse
import contextlib
import ctypes
from datetime import datetime
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = ROOT / 'work/dlss5'
LAYER = 'VK_LAYER_NV_dlssnr'
# Restrict settings to documented bounds. Style/preset/tone changes rebuild the
# model; composition and comparison controls can change without that rebuild.
SETTINGS = {'enabled': (0, 1, int), 'applymodel': (0, 1, int),
            'compare': (0, 2, int), 'comparesplit': (0, 1, float),
            'detail': (0, 4, float), 'colour': (0, 4, float),
            'sharpness': (0, 1, float), 'intensity': (0, 4, float),
            'localtone': (0, 4, float), 'localstructure': (0, 4, float),
            'skinstructure': (-1, 4, float), 'automask': (0, 1, int),
            'style': (0, 2, int), 'preset': (0, 15, int),
            'workingscale': (.25, 1, float), 'bypass': (0, 1, int),
            'transfer': (0, 2, int),
            # Helper enums: quality 0=fast, 1=balanced, 2=quality; grid 0..3=1/2/4/8 px.
            # Requests may fall back to a supported grid; status alone is not proof of the effective grid.
            'mvecquality': (0, 2, int), 'mvecpixels': (0, 3, int)}


# External ShmInitDefaults, with this adapter's native-detail composition
# defaults (50% model resolution, bypass off, native + edit transfer).
# Keep gpu/vk/dlss5_controls.h synchronized; test_dlss5_menu.py compares them.
DEFAULT_SETTINGS = {'enabled': 1, 'applymodel': 1, 'compare': 0, 'comparesplit': .5,
                    'detail': 1., 'colour': 1., 'sharpness': 0., 'intensity': 1.,
                    'localtone': 1., 'localstructure': 1., 'skinstructure': -1.,
                    'automask': 1, 'style': 0, 'preset': 0, 'workingscale': .5,
                    'bypass': 0, 'transfer': 2, 'mvecquality': 1, 'mvecpixels': 2}


def filesystem_type(fd):
    # Linux statfs begins with a native long. Leave ample room for the complete
    # structure without depending on the host architecture's remaining fields.
    libc = ctypes.CDLL(None, use_errno=True)
    function = libc.fstatfs
    function.argtypes = (ctypes.c_int, ctypes.c_void_p)
    function.restype = ctypes.c_int
    result = ctypes.create_string_buffer(512)
    if function(fd, result):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return ctypes.c_long.from_buffer(result).value


@contextlib.contextmanager
def shared_transport():
    # The layer imports these pages with VK_EXT_external_memory_host. NVIDIA
    # refuses disk-backed shared mappings; that refusal can also break later
    # allocations in the game's VkInstance. A fallback after import is too late.
    # Keep logs in work/, but use verified tmpfs for the pixel exchange.
    with tempfile.TemporaryDirectory(prefix='hookshot-dlss5-', dir='/dev/shm') as directory:
        path = Path(directory) / 'shm.bin'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            if filesystem_type(fd) != 0x01021994:  # TMPFS_MAGIC
                raise RuntimeError('DLSS shared memory requires tmpfs at /dev/shm; refusing a disk-backed GPU import')
        finally:
            os.close(fd)
        yield path


def setting_value(key, value):
    low, high, kind = SETTINGS[key]
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f'{key} must be in {low}..{high}')
    if kind is int and number != int(number):
        raise ValueError(f'{key} must be an integer')
    return kind(number)


def config(base, verify=False):
    data = json.loads((base / 'integration.json').read_text())
    if verify:
        for name, artifact in data['artifacts'].items():
            path = Path(artifact['path'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
                raise ValueError(f'{name} differs from the staged artifact: {path}')
        if not os.access(data['proton'], os.X_OK):
            raise ValueError('The configured Proton runner is not executable')
    return data


def process_stamp(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[19] if fields[0] != 'Z' else None
    except (FileNotFoundError, ProcessLookupError):
        return None


def parse_status(output):
    data = {}
    for line in output.splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        try:
            value = int(value, 0)
        except ValueError:
            try:
                number = float(value)
                value = number if math.isfinite(number) else value
            except ValueError:
                pass
        data[key] = value
    return data


class DLSS5Session:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.info = json.loads(self.path.read_text())
        self.run = self.path.parent

    def refresh_helper(self):
        """Pick up a session-local replacement without redirecting the IPC or prefix."""
        current = json.loads(self.path.read_text())
        for key in ('base', 'prefix', 'shm', 'shmctl'):
            if current.get(key) != self.info.get(key):
                raise ValueError(f'DLSS session identity changed: {key}')
        for key in ('helper_launcher_pid', 'helper_launcher_start_ticks'):
            self.info[key] = current[key]
        return self.info['helper_launcher_pid'], self.info['helper_launcher_start_ticks']

    def control(self, *args):
        if not Path(self.info['shm']).is_file():
            raise RuntimeError('This DLSS session has ended; its shared memory was released')
        result = subprocess.run([self.info['shmctl'], self.info['shm'], *args],
                                capture_output=True, text=True, timeout=5, check=True)
        return parse_status(result.stdout)

    def status(self):
        pid, stamp = self.refresh_helper()
        alive = stamp is not None and process_stamp(pid) == stamp
        # A dead helper can leave a live game passing through original frames.
        # Its IPC remains observable until the adapter actually releases it.
        if not Path(self.info['shm']).is_file():
            result = self.run / 'result.json'
            data = json.loads(result.read_text()).get('status', {}) if result.is_file() else {}
            data.update(session=str(self.path), launcher_alive=alive, archived=True, observed_at=time.time(),
                        proof='saved session status, not a live model evaluation')
            return data
        data = self.control('status')
        data.update(session=str(self.path),
                    launcher_alive=alive,
                    observed_at=time.time(),
                    proof='model_up plus advancing helper_frames proves evaluation, not visual quality')
        return data

    def set(self, key, value):
        self.control('set', key, str(setting_value(key, value)))
        return self.status()

    def save_preferences(self):
        current = self.control('settings')
        settings = {key: setting_value(key, current[key]) for key in SETTINGS}
        path = Path(self.info.get('preferences_path', Path(self.info['base']) / 'preferences.json'))
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(settings, indent=2) + '\n')
        temporary.replace(path)


def helper_environment(parent, base, run, cfg, shm):
    env = {k: v for k, v in parent.items()
           if not k.startswith(('DLSSNR_', 'HOS_', 'RX_')) and
           k not in ('VK_INSTANCE_LAYERS', 'VK_LAYER_PATH', 'VK_ADD_LAYER_PATH',
                     'VK_IMPLICIT_LAYER_PATH', 'VK_ADD_IMPLICIT_LAYER_PATH',
                     'VKLayer_DLSS5', 'VKLAYER_DLSS5')}
    env.update(STEAM_COMPAT_DATA_PATH=str(base / 'prefix'),
               STEAM_COMPAT_CLIENT_INSTALL_PATH=cfg['steam_root'],
               WINEPREFIX=str(base / 'prefix/pfx'),
               SteamAppId='0', SteamGameId='0', PROTON_ENABLE_NVAPI='1',
               WINEDEBUG='-all', DLSSNR_SKIP_NVAPI='1', DLSSNR_DISABLE='1',
               DLSSNR_SHM=str(shm), DLSSNR_LOG=str(run / 'helper.log'),
               DLSSNR_BIN_DIR='Z:' + str(Path(cfg['artifacts']['model']['path']).parent))
    # Forward only explicit timing diagnostics, never transport/model overrides.
    if parent.get('DLSSNR_TIME') == '1':
        env['DLSSNR_TIME'] = '1'
        interval = parent.get('DLSSNR_TIME_EVERY', '30')
        if interval.isdecimal() and 1 <= int(interval) <= 3600:
            env['DLSSNR_TIME_EVERY'] = interval
    return env


def layer_environment(parent, base, run, shm):
    env = dict(parent)
    env.pop('DLSSNR_DISABLE', None)
    layers = [name for name in env.get('VK_INSTANCE_LAYERS', '').split(':') if name and name != LAYER]
    paths = [str(base / 'layers')]
    if env.get('VK_ADD_LAYER_PATH'):
        paths.append(env['VK_ADD_LAYER_PATH'])
    env.update(VK_INSTANCE_LAYERS=':'.join([*layers, LAYER]),
               VK_ADD_LAYER_PATH=':'.join(paths),
               VKLayer_DLSS5='1', VKLAYER_DLSS5='1',
               DLSSNR_SHM=str(shm), DLSSNR_LOG=str(run / 'layer.log'),
               XDG_STATE_HOME=str(run / 'state'),
               HOS_DLSS5_SESSION=str(run / 'session.json'),
               HOS_DLSS5_CONTROL=str(run / 'control'))
    env.pop('HOS_DLSS5_MENU', None)
    return env


def run(base, command, preferences_path=None):
    cfg = config(base, verify=True)
    with (base / 'helper.lock').open('a') as lock:
        # The prefix is dedicated to this adapter. Refuse concurrent reuse.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with shared_transport() as shm:
            run_dir = base / 'runs' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            run_dir.mkdir(parents=True, mode=0o700)
            (base / 'prefix').mkdir(exist_ok=True, mode=0o700)
            ctl = cfg['artifacts']['shmctl']['path']
            subprocess.run([ctl, str(shm), 'resume'], check=True)
            # Keep native detail when the model works below presentation resolution.
            # Upstream's raw-answer default otherwise replaces the frame with an
            # enlarged low-resolution image, even where the model changed nothing.
            preferences = dict(DEFAULT_SETTINGS)
            path = Path(preferences_path).resolve() if preferences_path is not None else base / 'preferences.json'
            if preferences_path is not None and not path.is_file():
                raise ValueError(f'The requested preferences file does not exist: {path}')
            if path.is_file():
                saved = json.loads(path.read_text())
                if not isinstance(saved, dict):
                    raise ValueError('Saved DLSS 5 settings must be a JSON object')
                preferences.update(saved)
            for key, value in preferences.items():
                if key not in SETTINGS:
                    raise ValueError(f'Unknown saved DLSS 5 setting: {key}')
                subprocess.run([ctl, str(shm), 'set', key,
                                str(setting_value(key, value))], check=True)
            env = helper_environment(os.environ, base, run_dir, cfg, shm)
            helper = None
            session = None
            target = None
            bridge = None
            try:
                with (run_dir / 'launcher.log').open('w') as log:
                    helper = subprocess.Popen([cfg['proton'], 'run', cfg['artifacts']['helper']['path']],
                                              env=env, stdout=log, stderr=subprocess.STDOUT,
                                              start_new_session=True, umask=0o077)
                info = dict(helper_launcher_pid=helper.pid, helper_launcher_start_ticks=process_stamp(helper.pid),
                            shmctl=ctl, shm=str(shm), base=str(base), command=command,
                            prefix=str(base / 'prefix'), version=cfg['version'], preferences_path=str(path))
                session_path = run_dir / 'session.json'
                session_path.write_text(json.dumps(info, indent=2) + '\n')
                session = DLSS5Session(session_path)
                print(json.dumps({'dlss5_session': str(session_path)}), flush=True)
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    status = session.status()
                    if status.get('helper_state') == 4:
                        break
                    # A freshly initialized mapping is Stopped until the helper
                    # attaches. Proton's first prefix setup can take several seconds.
                    if helper.poll() is not None or status.get('helper_state') in (1, 2, 3):
                        raise RuntimeError(f'Helper initialization failed: {status}; see {run_dir}')
                    time.sleep(0.2)
                else:
                    raise TimeoutError(f'Helper did not initialize; see {run_dir}')
                (run_dir / 'ready.json').write_text(json.dumps(status, indent=2) + '\n')
                spec = importlib.util.spec_from_file_location('hookshot_dlss5_control', Path(__file__).with_name('dlss5_control.py'))
                controls = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(controls)
                bridge = controls.ControlBridge(session, SETTINGS, setting_value, run_dir / 'control',
                                                defaults=DEFAULT_SETTINGS).start()
                target = subprocess.Popen(command, env=layer_environment(os.environ, base, run_dir, shm))
                info.update(target_pid=target.pid, target_start_ticks=process_stamp(target.pid))
                temporary = session_path.with_suffix('.tmp')
                temporary.write_text(json.dumps(info, indent=2) + '\n')
                temporary.replace(session_path)
                result = target.wait()
                (run_dir / 'result.json').write_text(json.dumps(
                    {'exit_code': result, 'status': session.status()}, indent=2) + '\n')
                return result
            finally:
                if target is not None and target.poll() is None:
                    target.terminate()
                    try:
                        target.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        target.kill()
                        target.wait()
                try:
                    if bridge is not None:
                        bridge.close()
                    if session is not None:
                        session.control('quit')
                        if not wait_replacement_helper(session, info['helper_launcher_pid'],
                                                       info['helper_launcher_start_ticks']):
                            print('DLSS replacement helper did not exit after quit; stopping its private wineserver',
                                  file=sys.stderr, flush=True)
                    if helper is not None:
                        try:
                            helper.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            # The live Popen child still owns its private process group.
                            os.killpg(helper.pid, signal.SIGTERM)
                            try:
                                helper.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                os.killpg(helper.pid, signal.SIGKILL)
                                helper.wait()
                finally:
                    # Wine children can detach from Proton's process group during
                    # prefix initialization. Stop only this adapter's private server.
                    server = Path(cfg['proton']).parent / 'files/bin/wineserver'
                    if server.is_file():
                        stop_private_server(server, env)


def wait_replacement_helper(session, original_pid, original_stamp, timeout=10):
    """Allow a replacement's resource teardown before killing the private server.

    The original child still uses Popen.wait below. A replacement is not our
    child: observe only its exact start stamp, never signal a PID from metadata.
    A single deadline also bounds repeated replacements during shutdown.
    """
    deadline = time.monotonic() + timeout
    while True:
        pid, stamp = session.refresh_helper()
        if (pid, stamp) == (original_pid, original_stamp):
            return True
        if stamp is None or process_stamp(pid) != stamp:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(.02, remaining))


def stop_private_server(server, env):
    """Stop the dedicated prefix and wait for its server lock to be released."""
    stopped = subprocess.run([str(server), '-k'], env=env, timeout=10,
                             capture_output=True, text=True)
    # Wine also returns 1 when the prefix has no running server. Fatal setup
    # errors print a diagnostic; never suppress those or unexpected exit codes.
    if stopped.returncode != 1 or stopped.stderr.strip():
        stopped.check_returncode()
    # A kill request alone does not establish exit. In particular, a silent
    # failed kill against a still-running server must time out here.
    subprocess.run([str(server), '-w'], env=env, timeout=10, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=DEFAULT_BASE)
    sub = parser.add_subparsers(dest='action', required=True)
    launch = sub.add_parser('run', help='Run a command with the local layer/helper')
    launch.add_argument('--preferences', type=Path, help='Use and save this session-specific preferences file')
    launch.add_argument('command', nargs=argparse.REMAINDER)
    for name in ('status', 'set'):
        child = sub.add_parser(name)
        child.add_argument('session', type=Path)
        if name == 'set':
            child.add_argument('key', choices=SETTINGS)
            child.add_argument('value')
    args = parser.parse_args()
    if args.action == 'run':
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        if not command:
            parser.error('run needs a command after --')
        return run(args.base.resolve(), command, args.preferences)
    session = DLSS5Session(args.session)
    print(json.dumps(session.status() if args.action == 'status' else
                     session.set(args.key, args.value), indent=2))
    return 0


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
