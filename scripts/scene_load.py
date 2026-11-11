"""Verified map transitions in disposable runs, using local image-bound bindings.

A dispatch acknowledgement is never sufficient: observe the destination, cleared
reservation and fresh native frame progress. Game-derived names stay in work/.
"""
from contextlib import nullcontext
import fcntl
import importlib.util
import json
import math
from pathlib import Path
import time
import uuid

def sibling(name):
    spec = importlib.util.spec_from_file_location('hookshot_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scene_state = sibling('scene_state')
find_actor = sibling('scene_actor').find_actor
read_event_state = sibling('event_state').read_event_state


def event_wait_ms(profile):
    guard = profile.get('dispatch', {}).get('event_guard', {})
    if guard is None:
        guard = {}
    if not isinstance(guard, dict):
        raise ValueError('Invalid event readiness profile')
    value = guard.get('wait_ms', 2000)
    if type(value) is not int or not 2000 <= value <= 10000:
        raise ValueError('Event readiness wait must be 2000..10000 milliseconds')
    return value


def event_command(profile, event, starter=None):
    command = 'guest event ' + event.encode().hex()
    if starter is not None:
        command += f" {starter['actor']:#x} {starter['actor_id']:#x}"
    wait_ms = event_wait_ms(profile)
    if wait_ms != 2000:
        command += f' wait {wait_ms}'
    return command


def load_scene(api, scene_id, entrance, catalog=None, timeout=60):
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 3 <= timeout <= 300:
        raise ValueError('Scene timeout must be 3..300 seconds')
    for value in (scene_id, entrance):
        if not isinstance(value, str) or not value or '\0' in value or len(value.encode('utf-8')) > 63:
            raise ValueError('Scene and entrance must be nonempty strings of at most 63 UTF-8 bytes')
    if api.info.get('profile_kind') != 'analysis':
        raise ValueError('Scene loading requires a disposable analysis profile')
    bindings = api.run / 'scene-bindings.json'
    profile = json.loads(bindings.read_text())
    event_wait_ms(profile)  # Validate the wait before writing any reservation.
    event = profile['dispatch'].get('transition_event')
    if not profile['dispatch'].get('event_helper') or not isinstance(event, str) or not event or '\0' in event or len(event.encode()) > 63:
        raise ValueError('No validated transition event binding in this session')
    scene = api.scenes(catalog, scene_id)['scenes'][0]
    entries = [e for e in scene['entrances'] if e['name'] == entrance]
    if scene['missing_sources'] or len(entries) != 1 or not entries[0]['unique_name']:
        raise ValueError('Scene sources must exist and entrance name must be unambiguous')
    # Independent API clients share this run lock. Raw debug requests remain an
    # expert interface and must not be mixed with an in-flight scene transaction.
    with (api.run / 'scene-load.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another scene load is already running') from None
        return _load(api, profile, scene_id, entrance, event, timeout)


def _load(api, profile, scene_id, entrance, event, timeout):
    scene_state.validate_profile(api, profile)

    def state():
        result = scene_state.read_fields(api, profile)
        if not result['ready']:
            raise RuntimeError('Scene state is not ready')
        fields = result['fields']
        for key in ('current_scene', 'pending_scene', 'pending_entrance', 'pending_event'):
            if key not in fields:
                raise ValueError('Incomplete scene bindings')
        return fields

    def status():
        result = api.request('status')
        if result['control'] != 'exclusive':
            raise RuntimeError('Scene loading requires exclusive API control')
        return result

    before = state()  # Verifies image before any mutation.
    initial = status()
    if profile.get('event_state'):
        active = api.event_state()
        if not active['ready'] or active['active']:
            raise RuntimeError('Finish the active event before loading a scene')
    if not before['current_scene'] or any(before[k] for k in ('pending_scene', 'pending_entrance', 'pending_event')):
        raise RuntimeError('Load a save and finish the existing scene transition first')
    reload = before['current_scene'] == scene_id
    reloads = profile.get('same_map_reload', {})
    if not isinstance(reloads, dict):
        raise ValueError('Invalid same-map reload bindings')
    entries = reloads.get(scene_id, {})
    if not isinstance(entries, dict):
        raise ValueError('Invalid same-map reload entrance bindings')
    witnesses = entries.get(entrance) if reload else None
    if reload and (not isinstance(witnesses, list) or not 1 <= len(witnesses) <= 4 or not profile.get('event_state')):
        raise ValueError('Same-map reload requires validated scene actor witnesses and event bindings')
    if initial['buttons'] or any(initial['sticks']) or initial['input_sequence'] != initial['applied_sequence']:
        raise RuntimeError('Release inputs and wait for their acknowledgement before loading')
    if initial.get('last_present_age_ms') is None or initial['last_present_age_ms'] > 1000:
        raise RuntimeError('Game is not making fresh frame progress')
    if not api.request('guest info')['allowed']:
        raise RuntimeError('Configured guest worker has not polled yet')
    witness_before = [find_actor(api, profile.get('actor_table'), selector) for selector in witnesses] if reload else []
    report = dict(status='running', source=before['current_scene'], destination=scene_id,
                  same_map_reload=reload, witness_before=witness_before,
                  entrance=entrance, started_at=time.time(), dispatches=[], requests=[], samples=[])
    path = api.run / ('scene-load-' + uuid.uuid4().hex + '.json')
    deadline = time.monotonic() + timeout
    sequence = None
    event_submitted = False

    def check_time():
        if time.monotonic() >= deadline:
            raise TimeoutError('Scene load timed out; arrival was not verified')
        status()  # A player handoff aborts the transaction.

    def dispatch(command):
        nonlocal sequence
        check_time()
        request = dict(command=command)
        report['requests'].append(request)
        ack = api.request(command)
        request['acknowledgement'] = ack
        sequence = ack['sequence']
        while True:
            check_time()
            info = api.request('guest info')
            request['last_info'] = info
            if info['sequence'] != sequence:
                raise RuntimeError('Guest request was replaced by another client')
            if info['phase'] == 'dispatched':
                report['dispatches'].append(info)
                sequence = None
                return
            if info['phase'] not in ('pending', 'executing'):
                raise RuntimeError('Guest request ' + info['phase'])
            time.sleep(.02)

    try:
        for field, value in (('pending_event', ''), ('pending_entrance', entrance), ('pending_scene', scene_id)):
            key = profile['fields'][field]
            dispatch(f'guest string {key:#x} {value.encode().hex() or "-"}')
            while True:
                check_time()
                observed = state()
                if observed['current_scene'] != before['current_scene']:
                    raise RuntimeError('Scene changed before transition dispatch')
                if observed[field] == value:
                    break
                time.sleep(.05)
        reserved = state()
        if reserved['pending_scene'] != scene_id or reserved['pending_entrance'] != entrance or reserved['pending_event']:
            raise RuntimeError('Scene reservation changed before transition dispatch')
        event_submitted = True  # An interrupted request may already have reached the game.
        dispatch(event_command(profile, event))
        arrived_frame = None
        while True:
            check_time()
            observed = state()
            telemetry = status()
            report['samples'].append(dict(time=time.time(), fields=observed, presents=telemetry['presents'],
                                          last_present_age_ms=telemetry['last_present_age_ms']))
            ready = observed['current_scene'] == scene_id and not any(observed[k] for k in
                    ('pending_scene', 'pending_entrance', 'pending_event'))
            if ready:
                if arrived_frame is None:
                    arrived_frame = telemetry['presents']
                if telemetry['presents'] >= arrived_frame + 30 and telemetry['last_present_age_ms'] is not None and telemetry['last_present_age_ms'] < 1000:
                    if reload:
                        current_event = read_event_state(api, profile['event_state'])
                        if not current_event['ready'] or current_event['active']:
                            arrived_frame = None
                            time.sleep(.1)
                            continue
                        try:
                            witness_after = [find_actor(api, profile.get('actor_table'), selector) for selector in witnesses]
                        except RuntimeError as exc:
                            report['witness_error'] = str(exc)
                            arrived_frame = None
                            time.sleep(.1)
                            continue
                        report['witness_after'] = witness_after
                        if any(old['actor_id'] == new['actor_id'] for old, new in zip(witness_before, witness_after)):
                            arrived_frame = None
                            time.sleep(.1)
                            continue
                        check_time()
                        confirmed = state()
                        telemetry = status()
                        if (confirmed != observed or telemetry.get('last_present_age_ms') is None or
                                telemetry['last_present_age_ms'] >= 1000):
                            arrived_frame = None
                            continue
                    report.update(status='completed', arrived_frame=arrived_frame,
                                  final_frame=telemetry['presents'], elapsed_seconds=time.time() - report['started_at'])
                    return dict(report, evidence=str(path))
            else:
                arrived_frame = None
            time.sleep(.1)
    except BaseException as exc:
        report.update(status='failed', error=str(exc), event_submitted=event_submitted,
                      recovery='Inspect the reservation or restart this disposable run before retrying')
        if sequence is not None:
            try:
                report['cancel'] = api.request(f'guest cancel {sequence}')
            except Exception as cancel_error:
                report['cancel_error'] = str(cancel_error)
        raise
    finally:
        path.write_text(json.dumps(report, indent=2) + '\n')


def start_event(api, event_id, scene_id, timeout=None, *, _lock_held=False):
    """Request an event on an explicitly selected map; does not certify playback."""
    if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 30):
        raise ValueError('Event dispatch timeout must be 1..30 seconds')
    for value in (event_id, scene_id):
        if not isinstance(value, str) or not value or '\0' in value or len(value.encode()) > 63:
            raise ValueError('Event and scene identifiers must be 1..63 UTF-8 bytes')
    if api.info.get('profile_kind') != 'analysis':
        raise ValueError('Event dispatch requires a disposable analysis profile')
    bindings = api.run / 'scene-bindings.json'
    profile = json.loads(bindings.read_text())
    wait_ms = event_wait_ms(profile)
    if timeout is None:
        timeout = wait_ms / 1000 + 1
    if not profile.get('dispatch', {}).get('event_helper'):
        raise ValueError('No event helper configured for this session')
    # Some cinematic clips are child events: their parent performs setup,
    # subsequent dialogue and camera/control restoration. Routes are identified
    # locally, never inferred from a matching name or embedded game identifiers.
    entry_event = event_id
    sequences = profile.get('event_sequences', {})
    if not isinstance(sequences, dict):
        raise ValueError('Invalid event sequence bindings')
    route = sequences.get(event_id)
    if route is not None:
        if not isinstance(route, dict) or route.get('scene_id') != scene_id:
            raise ValueError('Event sequence requires another scene or has invalid bindings')
        entry_event = route.get('entry_event')
        if not isinstance(entry_event, str) or not entry_event or '\0' in entry_event or len(entry_event.encode()) > 63:
            raise ValueError('Invalid event sequence entry')
    with (nullcontext(None) if _lock_held else (api.run / 'scene-load.lock').open('a')) as lock:
        try:
            if lock is not None:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another scene or event request is already running') from None
        state = api.scene_state(bindings)  # Image validation precedes dispatch.
        fields = state['fields']
        if not state['ready'] or fields.get('current_scene') != scene_id:
            raise RuntimeError('Required scene is not loaded')
        if any(fields.get(key, None) != '' for key in ('pending_scene', 'pending_entrance', 'pending_event')):
            raise RuntimeError('Finish the pending scene transition first')
        if profile.get('event_state'):
            spec = importlib.util.spec_from_file_location('hookshot_event_state', Path(__file__).with_name('event_state.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            read_event_state = module.read_event_state
            current = read_event_state(api, profile['event_state'])
            if not current['ready'] or current['active']:
                raise RuntimeError('Finish the active event before requesting another')
        starter = None
        if route and 'starter' in route:
            if not profile['dispatch'].get('event_context'):
                raise ValueError('Event sequence requires native actor-context bindings')
            spec = importlib.util.spec_from_file_location('hookshot_scene_actor', Path(__file__).with_name('scene_actor.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            starter = module.find_actor(api, profile.get('actor_table'), route['starter'])
        def check_control():
            status = api.request('status')
            if status['control'] != 'exclusive':
                raise RuntimeError('Event dispatch requires exclusive API control')
            return status
        status = check_control()
        if status['buttons'] or any(status['sticks']) or status['input_sequence'] != status['applied_sequence']:
            raise RuntimeError('Release inputs before requesting an event')
        if status.get('last_present_age_ms') is None or status['last_present_age_ms'] > 1000:
            raise RuntimeError('No fresh frame progress')
        report = dict(event=event_id, entry_event=entry_event, uses_sequence=route is not None,
                      starter=starter, scene=scene_id, status='requesting', playback_verified=False,
                      completion_verified=False, started_at=time.time())
        path = api.run / ('event-request-' + uuid.uuid4().hex + '.json')
        sequence = None
        try:
            deadline = time.monotonic() + timeout
            command = event_command(profile, entry_event, starter)
            report['command'] = command
            ack = api.request(command)
            report['acknowledgement'] = ack
            sequence = ack['sequence']
            report['sequence'] = sequence
            while True:
                check_control()
                info = api.request('guest info')
                report['last_info'] = info
                if info['sequence'] != sequence:
                    raise RuntimeError('Event request replaced by another client')
                if info['phase'] == 'dispatched':
                    report.update(status='dispatched', dispatch=info)
                    return dict(report, evidence=str(path))
                if info['phase'] not in ('pending', 'executing'):
                    raise RuntimeError('Event request ' + info['phase'])
                if time.monotonic() >= deadline:
                    raise TimeoutError('Event dispatch timed out; playback is unknown')
                time.sleep(.02)
        except BaseException as exc:
            report.update(status='failed', error=str(exc))
            if sequence is not None:
                try:
                    report['cancel'] = api.request(f'guest cancel {sequence}')
                except Exception as cancel_error:
                    report['cancel_error'] = str(cancel_error)
            raise
        finally:
            path.write_text(json.dumps(report, indent=2) + '\n')
