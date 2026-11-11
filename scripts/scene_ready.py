"""Observe stable scene readiness without inputs, mutations or implicit retries."""
import importlib.util
from pathlib import Path
import json
import math
import time
import uuid

spec = importlib.util.spec_from_file_location('hookshot_scene_load', Path(__file__).with_name('scene_load.py'))
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)
scene_state, read_event_state = loader.scene_state, loader.read_event_state


def wait_ready(api, expected_scene, timeout=60):
    if not isinstance(expected_scene, str) or not expected_scene or '\0' in expected_scene:
        raise ValueError('Expected scene must be a nonempty identifier')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 600:
        raise ValueError('Readiness timeout must be 1..600 seconds')
    profile = json.loads((api.run / 'scene-bindings.json').read_text())
    scene_state.validate_profile(api, profile)
    path = api.run / ('scene-ready-' + uuid.uuid4().hex + '.json')
    report = dict(status='running', expected_scene=expected_scene, samples=[],
                  consistent_snapshot=False, gameplay_verified=False)
    deadline = time.monotonic() + timeout
    first = None
    previous = None
    try:
        while time.monotonic() < deadline:
            sample = dict(elapsed=timeout - (deadline - time.monotonic()))
            report['samples'].append(sample)
            status = sample['status'] = api.request('status')
            if status.get('control') != 'exclusive':
                raise RuntimeError('Readiness requires exclusive control')
            frame = status.get('presents')
            if type(frame) is not int or frame < 0 or previous is not None and frame < previous:
                raise RuntimeError('Invalid or regressing native frame counter')
            previous = frame
            guest = sample['guest'] = api.request('guest info')
            try:
                scene = sample['scene'] = scene_state.read_fields(api, profile)
                event = sample['event'] = read_event_state(api, profile.get('event_state'))
            except RuntimeError as exc:
                sample['read_error'] = str(exc)
                first = None
                time.sleep(.1)
                continue
            fields = scene.get('fields', {})
            ready = (scene.get('ready') and fields.get('current_scene') == expected_scene and
                     all(fields.get(k) == '' for k in ('pending_scene', 'pending_entrance', 'pending_event')) and
                     event.get('ready') and event.get('active') is False and guest.get('allowed') and
                     guest.get('phase') in ('idle', 'dispatched', 'canceled', 'rejected') and
                     status.get('buttons') == 0 and status.get('sticks') == [0, 0, 0, 0] and
                     status.get('input_sequence') is not None and
                     status.get('input_sequence') == status.get('applied_sequence') and
                     type(status.get('last_present_age_ms')) in (int, float) and
                     0 <= status['last_present_age_ms'] <= 1000)
            sample['ready'] = bool(ready)
            first = (frame if first is None else first) if ready else None
            if first is not None and frame >= first + 12:
                report.update(status='completed', first_ready_frame=first, last_ready_frame=frame)
                return dict(report, evidence=str(path))
            time.sleep(.1)
        raise TimeoutError('Scene readiness was not observed before the deadline')
    except BaseException as exc:
        report.update(status='failed', error=str(exc))
        raise
    finally:
        path.write_text(json.dumps(report, indent=2) + '\n')
