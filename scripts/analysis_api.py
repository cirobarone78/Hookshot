#!/usr/bin/env python3
"""Local Linux test API: silent minimized runs, scripted input, renderer telemetry and screenshots.

New runs use the native Unix-socket API; older sessions retain the file/log adapter.
FPS covers up to 120 native frame intervals, including minimized rendering, not displayed FPS.
Input acknowledgement means a game input poll consumed a command, not that a menu accepted it.
Stopping sends SIGTERM; use only disposable copies of saves.
Launch forces 16:9 unless saved_aspect=True (--saved-aspect). That option reads
the test game folder's Ultrawide preference; it does not copy player settings or
change the window size. Verify actual render dimensions in game.log.
"""
import argparse
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import struct
import subprocess
import time
import uuid
import importlib.util

ROOT = Path(__file__).resolve().parent.parent


class InputPollTimeout(TimeoutError):
    """An input missed its polling deadline; retain the cancellation evidence."""
    def __init__(self, sequence, canceled):
        super().__init__(f'No game input poll consumed the command; canceled={canceled}')
        self.input_sequence = sequence
        self.input_canceled = canceled


EVENT_CONTEXT_FIELDS = ('ctor', 'submit', 'assign', 'destroy', 'manager_pointer', 'request_size',
                        'name_pointer_offset', 'name_capacity_offset', 'link0_offset', 'link1_offset',
                        'actor_id_offset', 'actor_holder_offset', 'holder_actor_offset', 'holder_id_offset')
EVENT_GUARD_FIELDS = ('root_slot', 'actor_offset', 'component_offset', 'owner_offset',
                      'owner_actor_offset', 'actor_id_offset', 'actor_holder_offset',
                      'holder_actor_offset', 'holder_id_offset', 'flag0_offset',
                      'flag0_mask', 'flag1_offset', 'flag1_mask')


def encode_event_guard(profile):
    if not isinstance(profile, dict) or any(type(profile.get(k)) is not int for k in EVENT_GUARD_FIELDS):
        raise ValueError('Invalid event readiness profile')
    wait_ms = profile.get('wait_ms', 2000)
    if type(wait_ms) is not int or not 2000 <= wait_ms <= 10000:
        raise ValueError('Event readiness wait must be 2000..10000 milliseconds')
    root = profile['root_slot']
    if not 0 < root < (1 << 39) or root & 7:
        raise ValueError('Invalid event readiness root')
    if any(not 0 <= profile[k] <= 4096 for k in EVENT_GUARD_FIELDS[1:]):
        raise ValueError('Invalid event readiness offset')
    if any(not 1 <= profile[k] <= 255 for k in ('flag0_mask', 'flag1_mask')):
        raise ValueError('Invalid event readiness mask')
    return ':'.join(f'{profile[k]:x}' for k in EVENT_GUARD_FIELDS)

EVENT_STATE_GUARD_FIELDS = ('container_offset', 'state_offset', 'value_offset', 'alias_value', 'alias_offset')


def encode_event_state_guard(profile):
    if not isinstance(profile, dict) or any(type(profile.get(k)) is not int or
            not 0 <= profile[k] <= (0xffffffff if k == 'alias_value' else 4096)
            for k in EVENT_STATE_GUARD_FIELDS):
        raise ValueError('Invalid event state readiness profile')
    values = profile.get('blocked_values')
    if not isinstance(values, list) or not 1 <= len(values) <= 16 or any(
            type(v) is not int or not 0 <= v <= 0xffffffff for v in values):
        raise ValueError('Invalid event state readiness values')
    return ':'.join(f'{v:x}' for v in [*(profile[k] for k in EVENT_STATE_GUARD_FIELDS), *values])


BUTTONS = set('A B X Y LS RS L R ZL ZR PLUS MINUS LEFT UP RIGHT DOWN LUP LDOWN LLEFT LRIGHT RUP RDOWN RLEFT RRIGHT'.split())
BUTTON_BITS = {name: 1 << i for i, name in enumerate('A B X Y LS RS L R ZL ZR PLUS MINUS LEFT UP RIGHT DOWN'.split())}
STICK_DIRECTIONS = {name: (axis, sign) for axis, names in enumerate(
    (('LLEFT', 'LRIGHT'), ('LDOWN', 'LUP'), ('RLEFT', 'RRIGHT'), ('RDOWN', 'RUP')))
    for name, sign in zip(names, (-1, 1))}
HOOKSHOT_UID = '5a3c9e1f0b7d24680000000000000001'
STATS = re.compile(r'vk: (\d+) presents, ([\d.]+) fps; a frame: ([\d.]+) draws \(([\d.]+) skipped\), ([\d.]+) dispatches, ([\d.]+) passes,.*?GPU-bound wait ([\d.]+) ms; (\d+) pipelines \(([\d.]+) ms\), (\d+) programs \((\d+) failed\)')


def process_stamp(pid):
    try:
        # The command name can contain spaces and parentheses.
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[19] if fields[0] != 'Z' else None
    except (FileNotFoundError, ProcessLookupError):
        return None


def tail(path, limit=2 * 1024 * 1024):
    with path.open('rb') as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - limit))
        return f.read().decode('utf-8', errors='replace')


def local_module(name):
    spec = importlib.util.spec_from_file_location('hookshot_' + name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HookshotAPI:
    def __init__(self, session):
        self.session = Path(session).resolve()
        self.info = json.loads(self.session.read_text())
        self.run = self.session.parent

    def scenes(self, catalog=None, scene_id=None):
        """Local asset catalogue, image-checked; not a claim of runtime loadability."""
        spec = importlib.util.spec_from_file_location('hookshot_scene_catalog', ROOT / 'scripts/scene_catalog.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.read_catalog(catalog or ROOT / 'work/scene-api/catalog.json',
                                     Path(self.info['game']) / 'image.bin')
        if scene_id is not None:
            matches = [scene for scene in result['scenes'] if scene['id'] == scene_id]
            if not matches:
                raise ValueError('Unknown scene identifier')
            result = dict(result, scenes=matches)
        return result

    def scene_state(self, bindings=None):
        """Read current/pending scene fields using locally verified layout data."""
        spec = importlib.util.spec_from_file_location('hookshot_scene_state', ROOT / 'scripts/scene_state.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        default = self.run / 'scene-bindings.json'
        return module.read_state(self, bindings or (default if default.is_file() else ROOT / 'work/scene-api/bindings.json'))

    def ui_state(self, bindings):
        """Observe local UI objects; no input-readiness or atomicity guarantee."""
        return local_module('ui_state').read_state(self, bindings)

    def navigate_ui(self, bindings, *, timeout=120):
        """Run an explicit image-bound menu recipe on a disposable session."""
        return local_module('ui_navigation').navigate(self, bindings, timeout)

    def scene_ready(self, expected_scene, *, timeout=60):
        """Observe idle scene/worker state across fresh frames; does not load a save."""
        return local_module('scene_ready').wait_ready(self, expected_scene, timeout)

    def scene_load(self, scene_id, entrance, *, catalog=None, timeout=60):
        """Load a map; same-map reloads require locally validated actor witnesses."""
        spec = importlib.util.spec_from_file_location('hookshot_scene_load', ROOT / 'scripts/scene_load.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.load_scene(self, scene_id, entrance, catalog, timeout)

    def event_start(self, event_id, scene_id, *, timeout=None):
        """Dispatch a cutscene/event request; inspect playback separately."""
        spec = importlib.util.spec_from_file_location('hookshot_scene_load', ROOT / 'scripts/scene_load.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.start_event(self, event_id, scene_id, timeout)

    def event_state(self):
        self.scene_state(self.run / 'scene-bindings.json')
        read_event_state = local_module('event_state').read_event_state
        profile = json.loads((self.run / 'scene-bindings.json').read_text())
        return read_event_state(self, profile.get('event_state'))

    def event_play(self, event_id, scene_id, *, timeout=180):
        play_event = local_module('event_play').play_event
        return play_event(self, event_id, scene_id, timeout)

    def event_wait(self, event_id, scene_id, *, timeout=180):
        return local_module('event_play').play_event(self, event_id, scene_id, timeout, observe=True)

    def value_read(self, name):
        self.scene_state(self.run / 'scene-bindings.json')
        profile = json.loads((self.run / 'scene-bindings.json').read_text())
        return dict(name=name, value=local_module('game_values').read_value(self, profile, name), consistent_snapshot=False)

    def value_write(self, name, value, *, timeout=5):
        return local_module('game_values').write_value(self, name, value, timeout)

    @classmethod
    def launch(cls, game, source_save, shot_every=120, *, dlss5=False, dlss_timing=False, frame_generation=None, dlss_preferences=None, dlss_base=None, present_trace=False, present_stages=False, stage_trace=False, fps_target=None, stage_cache=None, writeback_diff=None, cpu_uncached=None, profile=False, single_page_cache=False, scene_bindings=None, start_minimized=True, audio_enabled=False, saved_aspect=False):
        if dlss5 and not (ROOT / 'scripts/dlss5_api.py').is_file():
            raise ValueError('The optional DLSS adapter is not installed; omit --dlss5 or supply the adapter')
        game, source_save = Path(game).resolve(), Path(source_save).resolve()
        executable = game / 'bin/hookshot'
        if not executable.is_file() or not (game / 'image.bin').is_file():
            raise ValueError('The native game build is not ready')
        if not (source_save / 'account.sav').is_file():
            raise ValueError('--save must name one account save folder containing account.sav')
        scene_call = None
        event_context = None
        event_guard = None
        event_state_guard = None
        scalar_calls = None
        if scene_bindings is not None:
            binding = json.loads(Path(scene_bindings).read_text())
            if binding.get('image_sha256') != hashlib.sha256((game / 'image.bin').read_bytes()).hexdigest():
                raise ValueError('Scene bindings belong to another game image')
            dispatch = binding['dispatch']
            if not re.fullmatch('[0-9a-f]{40}', dispatch['build_id']) or not re.fullmatch('[A-Za-z0-9_:.-]{1,47}', dispatch['thread']):
                raise ValueError('Invalid scene dispatch build or thread')
            for number in (dispatch['string_setter'], binding['manager_pointer']):
                if type(number) is not int or not 0 < number < (1 << 39):
                    raise ValueError('Invalid scene dispatch address')
            event_helper = dispatch.get('event_helper')
            if event_helper is not None and (type(event_helper) is not int or not 0 < event_helper < (1 << 39)):
                raise ValueError('Invalid scene event helper')
            scalar_profile = dispatch.get('scalar_calls')
            if scalar_profile is not None:
                keys = ('bool_set', 'bool_get', 'int_set', 'int_get')
                if not isinstance(scalar_profile, dict) or any(type(scalar_profile.get(k)) is not int or
                        not 0 < scalar_profile[k] < (1 << 39) for k in keys):
                    raise ValueError('Invalid scalar call profile')
                scalar_calls = ':'.join(f'{scalar_profile[k]:x}' for k in keys)
            context_profile = dispatch.get('event_context')
            if context_profile is not None:
                if not isinstance(context_profile, dict) or any(type(context_profile.get(k)) is not int or
                        not 0 <= context_profile[k] < (1 << 39) for k in EVENT_CONTEXT_FIELDS):
                    raise ValueError('Invalid event context ABI profile')
                event_context = ':'.join(f'{context_profile[k]:x}' for k in EVENT_CONTEXT_FIELDS)
            if dispatch.get('event_guard') is not None:
                event_guard = encode_event_guard(dispatch['event_guard'])
                if 'state' in dispatch['event_guard']:
                    event_state_guard = encode_event_state_guard(dispatch['event_guard']['state'])
            scene_call = f"{dispatch['build_id']}:{dispatch['string_setter']:x}:{binding['manager_pointer']:x}:{dispatch['thread']}"
        if type(saved_aspect) is not bool:
            raise ValueError('saved_aspect must be boolean')
        if not 1 <= shot_every <= 3600:
            raise ValueError('shot_every must be 1..3600')
        if frame_generation is not None and (type(frame_generation) is not int or frame_generation not in (0, *range(2, 9))):
            raise ValueError('frame_generation must be 0 (off) or 2..8')
        if type(dlss_timing) is not bool:
            raise ValueError('dlss_timing must be boolean')
        if dlss_timing and not dlss5:
            raise ValueError('dlss_timing requires dlss5=True')
        if dlss_base is not None and not dlss5:
            raise ValueError('dlss_base requires dlss5=True')
        dlss_base = Path(dlss_base).resolve() if dlss_base is not None else ROOT / 'work/dlss5'
        if dlss_preferences is not None and not dlss5:
            raise ValueError('dlss_preferences requires dlss5=True')
        if writeback_diff is not None and type(writeback_diff) is not bool:
            raise ValueError('writeback_diff must be boolean or None')
        if stage_cache is not None and type(stage_cache) is not bool:
            raise ValueError('stage_cache must be boolean or None')
        if type(single_page_cache) is not bool:
            raise ValueError('single_page_cache must be boolean')
        if type(profile) is not bool:
            raise ValueError('profile must be boolean')
        if cpu_uncached is not None and type(cpu_uncached) is not bool:
            raise ValueError('cpu_uncached must be boolean or None')
        if type(stage_trace) is not bool:
            raise ValueError('stage_trace must be boolean')
        if type(present_stages) is not bool:
            raise ValueError('present_stages must be boolean')
        if type(present_trace) is not bool:
            raise ValueError('present_trace must be boolean')
        if fps_target is not None and (type(fps_target) is not int or not 60 <= fps_target <= 240):
            raise ValueError('fps_target must be 60..240')
        preferences = None
        if dlss5:
            preferences_path = Path(dlss_preferences) if dlss_preferences is not None else dlss_base / 'preferences.json'
            preferences = json.loads(preferences_path.read_text()) if preferences_path.is_file() else {}
            if dlss_preferences is not None and not preferences_path.is_file():
                raise ValueError('The requested DLSS preferences file does not exist')
            if not isinstance(preferences, dict):
                raise ValueError('DLSS preferences must be a JSON object')
        run = ROOT / 'work/runs' / datetime.now().strftime('analysis-%Y%m%d-%H%M%S-%f')
        run.mkdir(parents=True, mode=0o700)
        (run / 'shots').mkdir()
        target = run / 'user/save' / HOOKSHOT_UID
        shutil.copytree(source_save, target)
        hashes = {str(p.relative_to(source_save)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in source_save.rglob('*') if p.is_file()}
        (run / 'source-save-sha256.json').write_text(json.dumps(hashes, indent=2))
        (run / 'input.txt').touch(mode=0o600)
        (run / 'environment.txt').write_text('# This run uses its own environment, not hookshot_env.txt.\n')
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('HOS_', 'RX_', 'HOOKSHOT_', 'DLSSNR_')) and
               k not in ('VK_INSTANCE_LAYERS', 'VK_ADD_LAYER_PATH', 'VKLayer_DLSS5', 'VKLAYER_DLSS5')}
        debug_socket = 'hookshot-' + uuid.uuid4().hex
        env.update(HOS_ENV_FILE=str(run / 'environment.txt'), HOS_START_MINIMIZED='1' if start_minimized else '0', HOS_AUDIO='1' if audio_enabled else '0',
                   HOS_FULLSCREEN='0', HOS_ASPECT='0', HOS_REQUIRE_WINDOW='1',
                   HOS_LANGUAGE='de', HOS_INPUT_LIVE=str(run / 'input.txt'),
                   HOS_INPUT_BACKGROUND='0', HOS_DEBUG_SOCKET=debug_socket, HOS_DEBUG_CONTROL='exclusive',
                   RX_BACKEND='vulkan',
                   RX_VK_DUMP_FILE=str(run / 'frame-dump.request'), RX_VK_DUMP_DIR=str(run / 'dumps'),
                   RX_VK_SHOTS=str(run / 'shots'), RX_VK_SHOT_EVERY=str(shot_every))
        if saved_aspect:
            # Absence lets the runtime read ultrawide from this game folder's options.
            # Parent HOS_ASPECT was stripped above; never inherit a stale override.
            env.pop('HOS_ASPECT', None)
        if scene_call is not None:
            env['HOS_DEBUG_SCENE_CALL'] = scene_call
            if scalar_calls is not None:
                env['HOS_DEBUG_SCALAR_CALLS'] = scalar_calls
            if event_context is not None:
                env['HOS_DEBUG_EVENT_CONTEXT'] = event_context
            if event_guard is not None:
                env['HOS_DEBUG_EVENT_GUARD'] = event_guard
            if event_state_guard is not None:
                env['HOS_DEBUG_EVENT_STATE_GUARD'] = event_state_guard
            if event_helper is not None:
                env['HOS_DEBUG_SCENE_EVENT'] = f'{event_helper:x}'
            (run / 'scene-bindings.json').write_text(json.dumps(binding, indent=2))
        if cpu_uncached is not None:
            env['RX_VK_CAPTURE_CPU_UNCACHED'] = '1' if cpu_uncached else '0'
        if writeback_diff is not None:
            env['RX_VK_WB_DIFF'] = '1' if writeback_diff else '0'
        if stage_cache is not None:
            env['RX_VK_STAGE_CACHE'] = '1' if stage_cache else '0'
        if single_page_cache:
            env['RX_VK_SUBMITTED_PAGES'] = '1'
        if profile:
            env.update(HOS_PROFILE='2', HOS_SAMPLE_ALL=str(run / 'stacks.txt'), RX_VK_SLOW_LOG='20')
        if (profile or dlss_timing) and dlss5:
            env.update(DLSSNR_TIME='1', DLSSNR_TIME_EVERY='30')
        if present_stages:
            env['RX_VK_PRESENT_STAGES'] = '1'
        if stage_trace:
            env['RX_VK_STAGE_TRACE'] = str(run / 'renderer-stages.csv')
        if present_trace or stage_trace:
            env['HOS_PRESENT_TRACE'] = str(run / 'native-presents.csv')
        if fps_target is not None:
            env['HOS_FPS_TARGET'] = str(fps_target)
        if frame_generation is not None:
            env['RX_VK_FRAMEGEN'] = '0' if frame_generation == 0 else '1'
            if frame_generation:
                env['RX_VK_FRAMEGEN_MULT'] = str(frame_generation)
        session = run / 'session.json'
        env['HOS_GAME_SESSION'] = str(session)
        runtime = [str(executable), str(game / 'image.bin'), '--romfs', str(game / 'romfs'), '--user', str(run / 'user')]
        if dlss5:
            private_preferences = run / 'dlss5-preferences.json'
            private_preferences.write_text(json.dumps(preferences, indent=2) + '\n')
            runtime = ['/usr/bin/python3', '-I', str(ROOT / 'scripts/dlss5_api.py'), '--base', str(dlss_base), 'run',
                       '--preferences', str(private_preferences), '--', *runtime]
        (run / 'dumps').mkdir()
        # All analysis sessions in this checkout share one lock.
        lock = ROOT / 'work/local-game.lock'
        # Keep the lock in flock's parent, out of runtime/driver helper processes.
        command = ['flock', '--nonblock', '--close', str(lock), *runtime]
        with (run / 'game.log').open('w') as log:
            proc = subprocess.Popen(command, cwd=game, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True, umask=0o077)
        time.sleep(0.3)
        if proc.poll() is not None:
            raise RuntimeError(f'Game exited at launch ({proc.returncode}); see {run / "game.log"}')
        children = Path(f'/proc/{proc.pid}/task/{proc.pid}/children').read_text().split()
        if len(children) != 1:
            raise RuntimeError(f'Cannot identify the native game child of launcher {proc.pid}')
        child_pid = int(children[0])
        child_stamp = process_stamp(child_pid)
        game_pid = child_pid
        dlss_session = None
        if dlss5:
            try:
                deadline = time.monotonic() + 95
                while True:
                    if proc.poll() is not None:
                        raise RuntimeError(f'DLSS analysis launcher exited; see {run / "game.log"}')
                    if dlss_session is None:
                        for line in tail(run / 'game.log').splitlines():
                            if line.startswith('{"dlss5_session":'):
                                dlss_session = Path(json.loads(line)['dlss5_session'])
                                break
                    if dlss_session is not None:
                        details = json.loads(dlss_session.read_text())
                        if details.get('target_pid'):
                            game_pid = details['target_pid']
                            if process_stamp(game_pid) != details['target_start_ticks']:
                                raise RuntimeError('DLSS target already exited')
                            break
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'DLSS target did not start; see {run / "game.log"}')
                    time.sleep(.1)
            except BaseException:
                # Signal the wrapper, not flock: it owns and cleans up the private helper.
                if process_stamp(child_pid) == child_stamp:
                    fd = os.pidfd_open(child_pid)
                    try:
                        if process_stamp(child_pid) == child_stamp:
                            signal.pidfd_send_signal(fd, signal.SIGTERM)
                    finally:
                        os.close(fd)
                raise
        info = dict(pid=game_pid, process_start_ticks=process_stamp(game_pid), launcher_pid=proc.pid,
                    launcher_start_ticks=process_stamp(proc.pid), executable=str(executable),
                    game=str(game), source_save=str(source_save), launched_at=time.time(),
                    headless=False, start_minimized=bool(start_minimized), audio_enabled=bool(audio_enabled), input_clock='wall from first poll',
                    shot_every=shot_every, debug_socket=debug_socket,
                    environment={k: v for k, v in env.items() if k.startswith(('HOS_', 'RX_'))})
        info.update(profile_kind='analysis', dlss5_enabled=bool(dlss5), frame_generation_override=frame_generation, saved_aspect=saved_aspect)
        if dlss_session is not None:
            info['dlss5_session'] = str(dlss_session)
        session.write_text(json.dumps(info, indent=2))
        api = cls(session)
        try:
            # The API starts before the game/renderer threads, independent of scene loading.
            deadline = time.monotonic() + 5
            while True:
                try:
                    api.request('status')
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
        except (OSError, RuntimeError, ValueError):
            api.stop()
            raise RuntimeError(f'Native API unavailable; rebuild the local host. Session: {session}')
        return api

    def alive(self):
        stamp = process_stamp(self.info['pid'])
        return stamp is not None and stamp == self.info['process_start_ticks']

    def request(self, command):
        if not self.info.get('debug_socket'):
            raise RuntimeError('This older session has no native API; the next analysis start will have it')
        if not self.alive():
            raise RuntimeError('The game is not running')
        data = command.encode('ascii')
        if not data or len(data) > 511 or b'\0' in data:
            raise ValueError('Invalid native API command')
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as connection:
            connection.settimeout(2)
            connection.connect('\0' + self.info['debug_socket'])
            pid, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if pid != self.info['pid'] or uid != os.geteuid():
                raise RuntimeError('Native API peer does not match this session')
            connection.sendall(data)
            result = json.loads(connection.recv(4096))
        if result.get('ok') is not True:
            raise RuntimeError(result.get('error', 'Invalid native API response'))
        return result

    def control(self, mode):
        if mode not in ('player', 'exclusive', 'shared'):
            raise ValueError('Control must be player, exclusive or shared')
        return self.request('control ' + mode)

    def memory_info(self):
        """Guest offsets and bounds, available once the host has loaded the image."""
        return self.request('memory info')

    def read_memory(self, address, length):
        """Read 1..256 live guest bytes as hex. This does not pause the game or provide an atomic snapshot."""
        if type(address) is not int or not 0 <= address < 1 << 64 or type(length) is not int or not 1 <= length <= 256:
            raise ValueError('Use a 64-bit unsigned guest address and 1..256 bytes')
        result = self.request(f'memory read {address:#x} {length}')
        data = bytes.fromhex(result['data_hex'])
        if result.get('address') != f'{address:#x}' or result.get('length') != length or len(data) != length:
            raise RuntimeError('Memory response does not match the requested range')
        return result

    def input(self, buttons=0, sticks=(0, 0, 0, 0), milliseconds=200, timeout=15):
        if (type(buttons) is not int or not 0 <= buttons <= 65535 or len(sticks) != 4 or
                any(type(v) is not int or not -32767 <= v <= 32767 for v in sticks) or
                type(milliseconds) is not int or not 1 <= milliseconds <= 60000):
            raise ValueError('Use a 16-bit button mask, four integer axes -32767..32767 and 1..60000 ms')
        result = self.request('input ' + ' '.join(map(str, (buttons, *sticks, milliseconds))))
        sequence = result['sequence']
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.request('status')
            if status['input_sequence'] != sequence:
                raise RuntimeError('Input was superseded by another command or control handoff')
            if status['applied_sequence'] == sequence:
                return dict(result, applied=True, input_clock='wall from first poll')
            time.sleep(0.02)
        canceled = self.request(f'cancel {sequence}')['canceled']
        raise InputPollTimeout(sequence, canceled)

    def presentation_startup(self):
        """Observed startup configuration, not current visibility or displayed FPS."""
        with (self.run / 'game.log').open('rb') as log:
            startup = log.read(2 * 1024 * 1024).decode('utf-8', errors='replace')
        modes = re.findall(r'vk: replay ready \((window|offscreen);', startup)
        swap = re.search(r'vk: swapchain (\d+)x(\d+), (\d+) images, (fifo|mailbox|immediate)\b', startup)
        initial = None if not swap else dict(width=int(swap[1]), height=int(swap[2]),
                                             images=int(swap[3]), present_mode=swap[4])
        return dict(mode=modes[-1] if modes else 'unknown', initial_swapchain=initial)

    def presentation_mode(self):
        """Startup evidence only: a window does not prove visibility or displayed FPS."""
        return self.presentation_startup()['mode']

    def status(self):
        log = self.run / 'game.log'
        content = tail(log)
        matches = list(STATS.finditer(content))
        result = dict(session=str(self.session), alive=self.alive(), headless=self.info['headless'],
                      start_minimized=self.info.get('start_minimized', False),
                      audio_enabled=self.info['audio_enabled'], telemetry_source='renderer log',
                      log_age_seconds=round(time.time() - log.stat().st_mtime, 3),
                      sample_frames=120, fps=None)
        startup = self.presentation_startup()
        result['presentation_mode'] = startup['mode']
        result['initial_swapchain'] = startup['initial_swapchain']
        result['headless_requested'] = self.info['headless']
        result['headless'] = {'window': False, 'offscreen': True}.get(result['presentation_mode'])
        if matches:
            names = ['presents', 'fps', 'draws', 'draws_skipped', 'dispatches', 'passes', 'gpu_wait_ms',
                     'pipelines', 'pipeline_compile_ms_total', 'programs', 'shader_failures']
            result.update({k: float(v) for k, v in zip(names, matches[-1].groups())})
        gpu = re.findall(r'vk: GPU time ([\d.]+) ms a frame', content)
        if gpu:
            result['gpu_frame_ms'] = float(gpu[-1])
        acks = re.findall(r'hid: live input at [^\n]+', content)
        result['last_input_ack'] = acks[-1] if acks else None
        shots = sorted((self.run / 'shots').glob('vk_*.png'))
        result['latest_screenshot'] = str(shots[-1]) if shots else None
        result['fatal_errors'] = [line for line in content.splitlines() if 'FATAL:' in line or 'device lost' in line.lower()][-8:]
        if self.info.get('debug_socket'):
            result['renderer_sample'] = {k: result[k] for k in ('presents', 'fps', 'sample_frames') if k in result}
            result.update(fps=None, presents=None, sample_frames=None, telemetry_source='native present hook',
                          runtime_api_available=False)
            if result['alive']:
                try:
                    result.update(self.request('status'), runtime_api_available=True)
                except (OSError, RuntimeError, ValueError) as error:
                    result['runtime_api_error'] = str(error)
        return result

    def press(self, buttons, milliseconds=200, timeout=15):
        tokens = buttons.upper().split('+')
        if any(t not in BUTTONS for t in tokens) or not 1 <= milliseconds <= 60000:
            raise ValueError('Use known buttons/stick directions, joined by +, and 1..60000 ms')
        if self.info.get('debug_socket'):
            bits, sticks = 0, [0] * 4
            for token in tokens:
                if token in BUTTON_BITS:
                    bits |= BUTTON_BITS[token]
                else:
                    axis, sign = STICK_DIRECTIONS[token]
                    sticks[axis] = sign * 32767
            return self.input(bits, sticks, milliseconds, timeout)
        if not self.alive():
            raise RuntimeError('The game is not running')
        # A distinctive trailing space is accepted by parse_presses and makes each log acknowledgement unique.
        command = f'0:{"+".join(tokens)}/{milliseconds}'
        marker = f'{command} ' + str(time.monotonic_ns())
        path = self.run / 'input.txt'
        with path.open('ab', buffering=0) as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write((marker + '\n').encode())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if f'1 presses ({marker})' in tail(self.run / 'game.log'):
                return {'parsed': True, 'command': command, 'duration_ms': milliseconds, 'input_clock': 'wall'}
            if not self.alive():
                raise RuntimeError('Game exited before acknowledging input')
            time.sleep(0.05)
        raise TimeoutError('No input acknowledgement; the game may still be loading')

    def screenshot(self, timeout=30):
        previous = self.status()['latest_screenshot']
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = self.status()['latest_screenshot']
            if current and current != previous:
                # Wait for the asynchronous PNG writer to close the file (IEND trailer).
                with Path(current).open('rb') as f:
                    f.seek(max(0, Path(current).stat().st_size - 12))
                    if f.read() == b'\x00\x00\x00\x00IEND\xaeB`\x82':
                        return current
            if not self.alive():
                raise RuntimeError('Game exited before producing a screenshot')
            time.sleep(0.1)
        raise TimeoutError('No new periodic screenshot within the timeout')

    def dump(self, timeout=15):
        """Request a Vulkan pass-by-pass frame dump. Consumption is not GPU/file completion."""
        if not self.alive():
            raise RuntimeError('The game is not running')
        configured = self.info.get('environment', {}).get('RX_VK_DUMP_FILE')
        if not configured:
            raise RuntimeError('This older session was not started with the Vulkan dump trigger')
        trigger = Path(configured)
        trigger.touch(exist_ok=False)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not trigger.exists():
                return dict(request_consumed=True, directory=str(self.run / 'dumps'),
                            complete=False, note='The next frame is armed; dump files may still be writing')
            if not self.alive():
                raise RuntimeError('Game exited before consuming the frame dump request')
            time.sleep(0.05)
        trigger.unlink(missing_ok=True)
        raise TimeoutError('Frame dump not acknowledged in time; pending trigger removed')

    def stop(self):
        if self.info.get('profile_kind') == 'player':
            raise RuntimeError('This is a real player session. Close it normally after saving; analysis stop is disabled')
        if not self.alive():
            return {'stopped': True, 'already_exited': True}
        fd = os.pidfd_open(self.info['pid'])
        try:
            if not self.alive():
                return {'stopped': True, 'already_exited': True}
            signal.pidfd_send_signal(fd, signal.SIGTERM)
        finally:
            os.close(fd)
        deadline = time.monotonic() + 5
        while self.alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        launcher = self.info.get('launcher_pid')
        while launcher and time.monotonic() < deadline:
            stamp = process_stamp(launcher)
            if stamp is None or stamp != self.info.get('launcher_start_ticks'):
                break
            time.sleep(0.05)
        return {'stop_requested': True, 'stopped': not self.alive(), 'signal': 'SIGTERM',
                'profile': 'disposable copy'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('start')
    start.add_argument('--game', type=Path, default=ROOT / 'work/native-game')
    start.add_argument('--save', type=Path, required=True)
    start.add_argument('--shot-every', type=int, default=120)
    start.add_argument('--dlss5', action='store_true')
    start.add_argument('--saved-aspect', action='store_true', help='Use the test game folder saved Ultrawide preference instead of forcing 16:9')
    start.add_argument('--scene-bindings', type=Path, help='Opt in to local image-bound guest dispatch')
    start.add_argument('--single-page-cache', action='store_true', help='A/B test the legacy one-page submitted-memory cache')
    start.add_argument('--cpu-uncached', choices=('on', 'off'), help='A/B test bounded CPU snapshots for uncached Vulkan buffers')
    start.add_argument('--writeback-diff', choices=('on', 'off'), help='Explicit A/B override of GPU write-back diff; default follows the renderer')
    start.add_argument('--stage-cache', choices=('on', 'off'), help='A/B test CPU stage lowering cache')
    start.add_argument('--profile', action='store_true', help='Enable slow-frame diagnostics and stacks.txt.go-triggered sampling')
    start.add_argument('--dlss-timing', action='store_true', help='Measure DLSS bridge stages without CPU sampling (requires --dlss5)')
    start.add_argument('--stage-trace', action='store_true', help='Record renderer wall/thread-CPU stages and native intervals (diagnostic overhead)')
    start.add_argument('--present-stages', action='store_true', help='Log renderer present CPU stages in the private game log')
    start.add_argument('--present-trace', action='store_true', help='Record every native present interval in the run directory')
    start.add_argument('--fps-target', type=int, help='Diagnostic minimum engine FPS target, 60..240; not a performance guarantee')
    start.add_argument('--frame-generation', type=int, choices=(0, *range(2, 9)))
    start.add_argument('--dlss-preferences', type=Path)
    start.add_argument('--dlss-base', type=Path, help='Private DLSS integration directory for candidate testing')
    for name in ('status', 'press', 'input', 'control', 'shot', 'dump', 'stop', 'memory-info', 'read-memory', 'scenes', 'scene-state', 'scene-load', 'event-start', 'event-state', 'event-play', 'event-wait', 'value-read', 'value-write'):
        cmd = commands.add_parser(name)
        cmd.add_argument('session', type=Path)
        if name in ('value-read', 'value-write'):
            cmd.add_argument('name')
            if name == 'value-write':
                cmd.add_argument('value', type=json.loads, help='JSON true/false or signed integer')
        elif name in ('event-start', 'event-play', 'event-wait'):
            cmd.add_argument('event_id')
            cmd.add_argument('--scene-id', required=True)
            cmd.add_argument('--timeout', type=float, default=None if name == 'event-start' else 180)
        elif name == 'scene-load':
            cmd.add_argument('scene_id')
            cmd.add_argument('entrance')
            cmd.add_argument('--catalog', type=Path)
            cmd.add_argument('--timeout', type=float, default=60)
        elif name == 'scene-state':
            cmd.add_argument('--bindings', type=Path)
        elif name == 'scenes':
            cmd.add_argument('--catalog', type=Path)
            cmd.add_argument('--scene-id')
        elif name == 'press':
            cmd.add_argument('buttons')
            cmd.add_argument('--ms', type=int, default=200)
        elif name == 'input':
            cmd.add_argument('--buttons', type=lambda v: int(v, 0), default=0)
            cmd.add_argument('--sticks', type=int, nargs=4, default=[0, 0, 0, 0], metavar=('LX', 'LY', 'RX', 'RY'))
            cmd.add_argument('--ms', type=int, default=200)
        elif name == 'control':
            cmd.add_argument('mode', choices=('player', 'exclusive', 'shared'))
        elif name == 'read-memory':
            cmd.add_argument('address', type=lambda v: int(v, 0))
            cmd.add_argument('length', type=int)
    args = parser.parse_args()
    if args.command == 'start':
        result = HookshotAPI.launch(args.game, args.save, args.shot_every, dlss5=args.dlss5, dlss_timing=args.dlss_timing,
                                   frame_generation=args.frame_generation, dlss_preferences=args.dlss_preferences, dlss_base=args.dlss_base,
                                   present_trace=args.present_trace, present_stages=args.present_stages, stage_trace=args.stage_trace, fps_target=args.fps_target,
                                   stage_cache=None if args.stage_cache is None else args.stage_cache == 'on',
                                   writeback_diff=None if args.writeback_diff is None else args.writeback_diff == 'on',
                                   cpu_uncached=None if args.cpu_uncached is None else args.cpu_uncached == 'on',
                                   profile=args.profile, single_page_cache=args.single_page_cache,
                                   scene_bindings=args.scene_bindings, saved_aspect=args.saved_aspect).status()
    else:
        api = HookshotAPI(args.session)
        if args.command == 'value-read':
            result = api.value_read(args.name)
        elif args.command == 'value-write':
            result = api.value_write(args.name, args.value)
        elif args.command == 'event-state':
            result = api.event_state()
        elif args.command == 'event-wait':
            result = api.event_wait(args.event_id, args.scene_id, timeout=args.timeout)
        elif args.command == 'event-play':
            result = api.event_play(args.event_id, args.scene_id, timeout=args.timeout)
        elif args.command == 'event-start':
            result = api.event_start(args.event_id, args.scene_id, timeout=args.timeout)
        elif args.command == 'scene-load':
            result = api.scene_load(args.scene_id, args.entrance, catalog=args.catalog, timeout=args.timeout)
        elif args.command == 'scene-state':
            result = api.scene_state(args.bindings)
        elif args.command == 'scenes':
            result = api.scenes(args.catalog, args.scene_id)
        elif args.command == 'press':
            result = api.press(args.buttons, args.ms)
        elif args.command == 'input':
            result = api.input(args.buttons, args.sticks, args.ms)
        elif args.command == 'control':
            result = api.control(args.mode)
        elif args.command == 'shot':
            result = {'screenshot': api.screenshot()}
        elif args.command == 'memory-info':
            result = api.memory_info()
        elif args.command == 'read-memory':
            result = api.read_memory(args.address, args.length)
        else:
            result = getattr(api, args.command)()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
