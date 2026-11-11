"""Run an explicit local menu recipe on a disposable analysis session."""
import importlib.util
import json
import math
from pathlib import Path
import time
import uuid

spec = importlib.util.spec_from_file_location('hookshot_ui_state', Path(__file__).with_name('ui_state.py'))
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


def validate(profile):
    route = profile.get('navigation', {})
    steps = route.get('steps')
    scene = route.get('expected_scene')
    if not isinstance(scene, str) or not scene or '\0' in scene:
        raise ValueError('Expected destination scene is required')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 16:
        raise ValueError('Expected 1..16 UI steps')
    screens = profile.get('screens', {})
    for step in steps:
        if not isinstance(step, dict) or step.get('button') not in ('A', 'B'):
            raise ValueError('UI steps support only A/B pulses')
        expected = step.get('expect')
        if not isinstance(expected, dict) or not expected or set(expected) != set(screens):
            raise ValueError('Each step must constrain every bound screen')
        for options in expected.values():
            if not isinstance(options, list) or not 1 <= len(options) <= 4:
                raise ValueError('Invalid UI state alternatives')
            for option in options:
                if option is not None and (not isinstance(option, dict) or set(option) != {'state', 'input_state'} or
                        any(type(v) is not int or not 0 <= v <= 255 for v in option.values())):
                    raise ValueError('Expected raw UI byte states or null')
    return route


def navigate(api, bindings, timeout=120):
    if api.info.get('profile_kind') != 'analysis' or not api.info.get('debug_socket'):
        raise ValueError('UI navigation requires a disposable native API session')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 600:
        raise ValueError('UI navigation timeout must be 1..600 seconds')
    profile = json.loads(Path(bindings).read_text())
    route = validate(profile)
    # Validate the complete binding and image before sending any input.
    ui.read_state(api, bindings)
    path = api.run / ('ui-navigation-' + uuid.uuid4().hex + '.json')
    report = dict(status='running', steps=[], gameplay_verified=False, consistent_snapshot=False)
    deadline = time.monotonic() + timeout
    previous = None
    progress = time.monotonic()
    sequence = None
    owned = None

    def checkpoint():
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report, indent=2) + '\n')
        temporary.replace(path)

    def status():
        nonlocal previous, progress, sequence
        s = api.request('status')
        if s.get('control') != 'exclusive':
            raise RuntimeError('UI navigation lost exclusive control')
        current = s.get('input_sequence')
        if type(current) is not int or sequence is not None and current != sequence:
            raise RuntimeError('UI navigation input was superseded')
        sequence = current
        frame = s.get('presents')
        if type(frame) is not int or frame < 0 or previous is not None and frame < previous:
            raise RuntimeError('Invalid or regressing frame counter')
        now = time.monotonic()
        if previous is None or frame > previous:
            progress = now
        previous = frame
        # Shader preparation can legitimately precede the first present. The
        # overall transaction deadline still bounds that startup phase.
        if frame > 0 and now - progress > 10:
            raise TimeoutError('UI navigation stopped making frame progress')
        age = s.get('last_present_age_ms')
        neutral = (s.get('buttons') == 0 and s.get('sticks') == [0, 0, 0, 0] and
                   s.get('applied_sequence') == sequence and type(age) in (int, float) and 0 <= age <= 1000)
        return s, neutral

    def matches(observed, expected):
        return observed.get('available') and all(observed['screens'].get(k) in v for k, v in expected.items())

    def observe(record):
        try:
            return ui.read_fields(api, profile)
        except ui.UIStateChanging:
            # Discard this observation and restart the stable-frame window.
            # No input is retried; object identity/read errors still propagate.
            record['changing_reads'] = record.get('changing_reads', 0) + 1
            time.sleep(.05)
            return dict(available=False, consistent_snapshot=False, screens={})

    try:
        checkpoint()
        for step in route['steps']:
            record = dict(button=step['button'], samples=[])
            report['steps'].append(record)
            checkpoint()
            first = None
            while time.monotonic() < deadline:
                s, neutral = status()
                observed = observe(record)
                record['samples'].append(dict(frame=s['presents'], ui=observed, neutral=neutral))
                ready = neutral and matches(observed, step['expect'])
                first = (s['presents'] if first is None else first) if ready else None
                if first is not None and s['presents'] >= first + 12:
                    # Recheck immediately before the pulse. The host still cannot
                    # make this observation plus an input atomic with game state.
                    if not matches(observe(record), step['expect']) or not status()[1]:
                        first = None
                        continue
                    if time.monotonic() >= deadline:
                        raise TimeoutError('UI navigation deadline reached before input')
                    record['input_attempted'] = True
                    checkpoint()
                    bits = 1 if step['button'] == 'A' else 2
                    result = api.request(f'input {bits} 0 0 0 0 100')
                    sequence = owned = result['sequence']
                    record['input'] = result
                    checkpoint()
                    break
                time.sleep(.05)
            else:
                raise TimeoutError('Expected UI state not reached before deadline')
        remaining = deadline - time.monotonic()
        if remaining < 1:
            raise TimeoutError('No time left for destination readiness')
        status()
        report['destination'] = api.scene_ready(route['expected_scene'], timeout=remaining)
        status()
        report['status'] = 'completed'
        return dict(report, evidence=str(path))
    except BaseException as exc:
        report.update(status='failed', error=str(exc))
        raise
    finally:
        if owned is not None:
            try:
                report['input_cleanup'] = api.request(f'cancel {owned}')
            except Exception as exc:
                report['cleanup_error'] = str(exc)
        checkpoint()
