#!/usr/bin/env python3
"""Run explicit local scene cases in order; stop on failure and retain evidence.

Recipes contain owner-derived identifiers and remain in ignored work/. A completed
case verifies its API steps and assertions, not visual fidelity or a performance target.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import time
import uuid


def validate(document):
    if not isinstance(document, dict) or document.get('schema') != 1:
        raise ValueError('Unsupported scene-case schema')
    cases = document.get('cases')
    if not isinstance(cases, list) or not 1 <= len(cases) <= 32:
        raise ValueError('Expected 1..32 scene cases')
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get('id'), str) or not case['id'] or case['id'] in seen:
            raise ValueError('Scene cases need unique nonempty IDs')
        seen.add(case['id'])
        steps = case.get('steps')
        if not isinstance(steps, list) or not 1 <= len(steps) <= 32:
            raise ValueError('Expected 1..32 steps per case')
        for step in steps:
            if not isinstance(step, dict): raise ValueError('Invalid case step')
            kind = step.get('op')
            required = {'load': ('scene', 'entrance'), 'event': ('scene', 'event'), 'wait': ('scene', 'event'),
                        'write': ('name',), 'expect': ('name',)}.get(kind)
            if required is None or any(not isinstance(step.get(k), str) or not step[k] or
                                       '\0' in step[k] or len(step[k].encode()) > 63 for k in required):
                raise ValueError('Invalid scene-case operation or identifier')
            if 'timeout' in step and (kind not in ('event', 'wait') or
                    type(step['timeout']) not in (int, float) or not math.isfinite(step['timeout']) or
                    not 3 <= step['timeout'] <= 600):
                raise ValueError('Event timeout must be 3..600 seconds')
            if kind in ('write', 'expect') and (type(step.get('value')) not in (bool, int) or
                    type(step['value']) is int and not -(1 << 31) <= step['value'] < (1 << 31)):
                raise ValueError('Case scalar values must be bool or signed 32-bit integer')
    return cases


def native_frame(api):
    frame = api.request('status').get('presents')
    if type(frame) is not int or frame < 0:
        raise RuntimeError('Native frame counter is unavailable')
    return frame


def run_cases(api, document, selected=None):
    cases = validate(document)  # Validate the entire plan before any mutations.
    if api.info.get('profile_kind') != 'analysis':
        raise ValueError('Scene cases require a disposable analysis profile')
    bindings = json.loads((api.run / 'scene-bindings.json').read_text())
    api.scene_state(api.run / 'scene-bindings.json')
    if document.get('image_sha256') != bindings.get('image_sha256') or not document.get('image_sha256'):
        raise ValueError('Scene cases belong to another image')
    if selected is not None:
        cases = [c for c in cases if c['id'] in selected]
        if {c['id'] for c in cases} != set(selected):
            raise ValueError('Unknown selected scene case')
    path = api.run / ('scene-cases-' + uuid.uuid4().hex + '.json')
    report = dict(measurement_schema=1, session=str(api.session),
                  process_start_ticks=api.info.get('process_start_ticks'), pid=api.info.get('pid'),
                  trace=str(api.run / 'native-presents.csv'), status='running', started_at=time.time(), cases=[], gameplay_verified=False,
                  performance_certified=False)

    def checkpoint():
        # Readers must see either the previous complete report or the new one,
        # including while an event call is still running.
        pending = path.with_suffix('.json.tmp')
        pending.write_text(json.dumps(report, indent=2) + '\n')
        pending.replace(path)

    checkpoint()
    try:
        for case in cases:
            current = dict(id=case['id'], status='running', steps=[], started_at=time.time())
            report['cases'].append(current)
            for step in case['steps']:
                kind = step['op']
                options = {'timeout': step['timeout']} if 'timeout' in step else {}
                entry = dict(step=step, status='running', started_at=time.time())
                current['steps'].append(entry)
                checkpoint()
                try:
                    entry['frame_before'] = native_frame(api)
                    checkpoint()
                    if kind == 'load': result = api.scene_load(step['scene'], step['entrance'])
                    elif kind == 'wait': result = api.event_wait(step['event'], step['scene'], **options)
                    elif kind == 'event': result = api.event_play(step['event'], step['scene'], **options)
                    elif kind == 'write': result = api.value_write(step['name'], step['value'])
                    else:
                        result = api.value_read(step['name'])
                        if type(result['value']) is not type(step['value']) or result['value'] != step['value']:
                            raise RuntimeError('Scene-case value assertion failed: ' + step['name'])
                    # Samples and captures remain in the per-operation evidence file.
                    entry.update(status='completed', result={k:v for k,v in result.items()
                                 if k not in ('samples', 'captures', 'inputs')})
                except BaseException as exc:
                    entry.update(status='failed', error=str(exc))
                    raise
                finally:
                    try:
                        entry['frame_after'] = native_frame(api)
                        if entry['frame_after'] < entry.get('frame_before', 0):
                            raise RuntimeError('Native frame counter moved backwards')
                    except (OSError, RuntimeError, ValueError) as exc:
                        entry['measurement_error'] = str(exc)
                    entry['finished_at'] = time.time()
                    checkpoint()
                if 'measurement_error' in entry:
                    entry['status'] = 'failed'
                    raise RuntimeError(entry['measurement_error'])
            current.update(status='completed', finished_at=time.time(), screenshot=api.screenshot(),
                           final_scene=api.scene_state()['fields']['current_scene'])
            checkpoint()
        report['status'] = 'completed'
    except BaseException as exc:
        report.update(status='failed', error=str(exc))
        if report['cases'] and report['cases'][-1]['status'] == 'running':
            report['cases'][-1].update(status='failed', finished_at=time.time())
        raise
    finally:
        report['finished_at'] = time.time()
        checkpoint()
    return dict(report, evidence=str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--case', action='append', dest='selected')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('hookshot_analysis', Path(__file__).with_name('analysis_api.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    result = run_cases(module.HookshotAPI(args.session), json.loads(args.cases.read_text()), args.selected)
    print(json.dumps(dict(status=result['status'], evidence=result['evidence'],
                          cases=[dict(id=c['id'], status=c['status']) for c in result['cases']]), indent=2))


if __name__ == '__main__': main()
