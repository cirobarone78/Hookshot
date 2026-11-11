"""Run explicit local cutscene chains; engine lifecycle is not visual acceptance."""
import fcntl
import json
import math
from pathlib import Path
import time
import uuid

import importlib.util


def sibling(name):
    spec = importlib.util.spec_from_file_location('hookshot_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


read_event_state = sibling('event_state').read_event_state
start_event = sibling('scene_load').start_event
read_fields = sibling('scene_state').read_fields


def play_event(api, event_id, scene_id, timeout=180, *, observe=False):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 3 <= timeout <= 600:
        raise ValueError('Event playback timeout must be 3..600 seconds')
    if api.info.get('profile_kind') != 'analysis':
        raise ValueError('Event playback requires a disposable analysis profile')
    profile = json.loads((api.run / 'scene-bindings.json').read_text())
    initial_scene = api.scene_state(api.run / 'scene-bindings.json')  # Image validation.
    if initial_scene.get('fields', {}).get('current_scene') != scene_id:
        raise RuntimeError('Required scene is not loaded')
    layout = profile.get('event_state')
    route = profile.get('event_sequences', {}).get(event_id, {})
    active_names = route.get('active_names', [route.get('entry_event', event_id)])
    if not isinstance(active_names, list) or not 1 <= len(active_names) <= 32 or any(not isinstance(n, str) or not n or len(n.encode()) > 63 for n in active_names):
        raise ValueError('Invalid active event names')
    followups = route.get('followup_events', [])
    if not isinstance(followups, list) or len(followups) > 15 or any(
            not isinstance(v, str) or not v or '\0' in v or len(v.encode()) > 63 for v in followups):
        raise ValueError('Invalid event follow-up list')
    # Dialogue pulses and a map handoff are opt-in parts of an image-bound recipe.
    dialogue = route.get('dialogue')
    arrival = route.get('arrival')
    if dialogue is not None:
        if not isinstance(dialogue, dict) or set(dialogue) != {'press_every', 'press_ms'}:
            raise ValueError('Dialogue requires press_every and press_ms')
        interval, pulse = dialogue['press_every'], dialogue['press_ms']
        if (type(interval) not in (int, float) or not math.isfinite(interval) or
                type(pulse) is not int or not 1 <= pulse <= 1000 or
                not pulse / 1000 + .05 <= interval <= 60):
            raise ValueError('Invalid bounded dialogue pulse policy')
    if arrival is not None:
        if (not isinstance(arrival, dict) or set(arrival) != {'scene', 'events'} or
                not isinstance(arrival.get('events'), list) or not 1 <= len(arrival['events']) <= 32 or
                any(not isinstance(v, str) or not v or '\0' in v or len(v.encode()) > 63
                    for v in [arrival.get('scene'), *arrival['events']]) or followups):
            raise ValueError('Arrival requires a scene and boot event, without follow-ups')
    report = dict(event=event_id, scene=scene_id, status='running', steps=[], samples=[],
                  lifecycle_completed=False, gameplay_verified=False, started_at=time.time(), inputs=[], captures=[])
    path = api.run / ('event-play-' + uuid.uuid4().hex + '.json')
    deadline = time.monotonic() + timeout
    next_press = next_capture = time.monotonic()
    last_input = None
    last_input_canceled = False
    with (api.run / 'scene-load.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another scene or event operation is running') from None
        try:
            for index, name in enumerate([event_id, *followups]):
                before = read_event_state(api, layout)
                observing = observe and index == 0
                if observing:
                    if not before['ready'] or not before['active'] or before['name'] not in active_names:
                        raise RuntimeError('Expected event is not active')
                    step = dict(event=name, entry_event=route.get('entry_event', name), status='observing',
                                sequence=api.request('guest info')['sequence'])
                else:
                    if not before['ready'] or before['active']:
                        raise RuntimeError('Finish the active event before playback')
                    step = start_event(api, name, scene_id, _lock_held=True)
                report['steps'].append(step)
                seen_active = observing
                seen_arrival = False
                idle_frame = None
                last_frame, progressed_at = None, time.monotonic()
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Event lifecycle did not finish before timeout')
                    status = api.request('status')
                    if last_input is not None and status.get('input_sequence', last_input) != last_input:
                        raise RuntimeError('Dialogue input was superseded by another client')
                    if status['control'] != 'exclusive':
                        raise RuntimeError('Event playback lost exclusive API control')
                    if status['presents'] != last_frame:
                        last_frame, progressed_at = status['presents'], time.monotonic()
                    if time.monotonic() - progressed_at > 5 or status.get('last_present_age_ms', 6000) > 5000:
                        raise RuntimeError('Event playback stopped producing frames')
                    if api.request('guest info')['sequence'] != step['sequence']:
                        raise RuntimeError('Another client dispatched a guest operation')
                    try:
                        state = read_event_state(api, layout)
                    except RuntimeError as exc:
                        if 'changed during read' not in str(exc):
                            raise
                        time.sleep(.05)
                        continue
                    report['samples'].append(dict(time=time.time(), frame=last_frame, **state))
                    fields = read_fields(api, profile)['fields'] if arrival else None
                    if arrival:
                        report['samples'][-1]['scene'] = fields
                        seen_arrival = seen_arrival or (fields.get('current_scene') == arrival['scene'] and
                            state['active'] and state['name'] in arrival['events'])
                    if not state['ready'] and not arrival:
                        raise RuntimeError('Event manager disappeared')
                    if dialogue and state['active'] and time.monotonic() >= next_press:
                        try:
                            acknowledgement = api.input(1, milliseconds=dialogue['press_ms'], timeout=min(1, max(.01, deadline-time.monotonic())))
                            last_input = acknowledgement['sequence']
                            last_input_canceled = False
                        except TimeoutError as exc:
                            # A loading transition may keep rendering without polling input.
                            # Only continue after our own command was canceled into neutral;
                            # network timeouts, handoffs and superseding clients still abort.
                            sequence = getattr(exc, 'input_sequence', None)
                            if type(sequence) is not int or getattr(exc, 'input_canceled', None) is not True:
                                raise
                            neutral = api.request('status')
                            if neutral['control'] != 'exclusive' or neutral['input_sequence'] != sequence + 1:
                                raise RuntimeError('Canceled dialogue input lost exclusive ownership') from exc
                            last_input = sequence + 1
                            last_input_canceled = True
                            acknowledgement = dict(sequence=sequence, applied=False, canceled=True,
                                                   neutral_sequence=last_input)
                        report['inputs'].append(dict(time=time.time(), frame=last_frame, acknowledgement=acknowledgement))
                        next_press = time.monotonic() + dialogue['press_every']
                    if dialogue and time.monotonic() >= next_capture:
                        report['captures'].append(dict(time=time.time(), frame=last_frame, path=str(api.screenshot())))
                        next_capture = time.monotonic() + 5
                        path.write_text(json.dumps(report, indent=2) + '\n')
                    arrived = not arrival or (seen_arrival and fields.get('current_scene') == arrival['scene'] and
                        not any(fields.get(k) for k in ('pending_scene', 'pending_entrance', 'pending_event')))
                    if state['active']:
                        seen_active = seen_active or state['name'] == step['entry_event']
                        idle_frame = None
                    elif state['ready'] and seen_active and arrived:
                        if idle_frame is None:
                            idle_frame = last_frame
                        if last_frame - idle_frame >= 12:
                            step['lifecycle_completed'] = True
                            break
                    else:
                        idle_frame = None
                    time.sleep(.1)
            report.update(status='completed', lifecycle_completed=True)
        except BaseException as exc:
            report.update(status='failed', error=str(exc))
            raise
        finally:
            if last_input is not None and not last_input_canceled:
                try:
                    report['input_cleanup'] = api.request('cancel ' + str(last_input))
                    if report['input_cleanup'].get('canceled'):
                        cleanup_deadline = time.monotonic() + 1
                        while True:
                            neutral = api.request('status')
                            if neutral['input_sequence'] != last_input + 1:
                                raise RuntimeError('Input changed during dialogue cleanup')
                            if neutral['applied_sequence'] == neutral['input_sequence']:
                                break
                            if time.monotonic() >= cleanup_deadline:
                                raise TimeoutError('Neutral dialogue input was not acknowledged')
                            time.sleep(.02)
                except (OSError, RuntimeError) as exc:
                    report['input_cleanup_error'] = str(exc)
                    report['status'] = 'failed'
            report['finished_at'] = time.time()
            path.write_text(json.dumps(report, indent=2) + '\n')
    if report.get('input_cleanup_error'):
        raise RuntimeError(report['input_cleanup_error'])
    return dict(report, evidence=str(path))
