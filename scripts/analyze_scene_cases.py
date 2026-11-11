#!/usr/bin/env python3
"""Report per-operation native frame times without certifying visual/gameplay quality.

Read a scene-cases report beside its own session and native-presents.csv. Loading,
setup and event calls remain separate; event calls include their internal loads,
validation and cleanup. A wait call covers only the observed suffix of an event.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path

spec = importlib.util.spec_from_file_location('hookshot_present_trace', Path(__file__).with_name('analyze_present_trace.py'))
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
analyze = module.analyze


def summarize(path, target_fps=60):
    path = Path(path).resolve()
    if type(target_fps) not in (int, float) or not math.isfinite(target_fps) or target_fps <= 0:
        raise ValueError('target_fps must be finite and positive')
    source = json.loads(path.read_text())
    session_path, trace = path.parent/'session.json', path.parent/'native-presents.csv'
    if (source.get('measurement_schema') != 1 or Path(source.get('session', '')).resolve() != session_path or
            Path(source.get('trace', '')).resolve() != trace):
        raise ValueError('Expected frame boundaries and trace from this report session')
    session = json.loads(session_path.read_text())
    if (session.get('profile_kind') != 'analysis' or not source.get('pid') or not source.get('process_start_ticks') or
            any(source[k] != session.get(k) for k in ('pid', 'process_start_ticks'))):
        raise ValueError('Scene report does not match its analysis process')
    result = dict(source=str(path), source_status=source['status'], target_fps=target_fps,
                  performance_certified=False, operations=[], complete_trace_coverage=True,
                  proof='native present-call intervals; not GPU/display timestamps or visual acceptance')
    event_passes = []
    for case in source['cases']:
        for index, entry in enumerate(case['steps']):
            op = entry['step']['op']
            row = dict(case=case['id'], step_index=index, op=op, status=entry.get('status'),
                       category='load' if op == 'load' else 'event' if op in ('event','wait') else 'setup',
                       observed_suffix_only=op == 'wait')
            result['operations'].append(row)
            try:
                before, after = entry.get('frame_before'), entry.get('frame_after')
                if entry.get('measurement_error'):
                    raise ValueError(entry['measurement_error'])
                if type(before) is not int or type(after) is not int or before < 1 or after <= before:
                    raise ValueError('No complete positive native frame interval')
                row['timing'] = analyze(trace, before+1, after, target_fps)
                row['available'] = True
            except (OSError, ValueError) as exc:
                row.update(available=False, error=str(exc))
                result['complete_trace_coverage'] = False
            if row['category'] == 'event':
                event_passes.append(row.get('timing', {}).get('every_frame_within_budget')
                                    if row['available'] and row['status'] == 'completed' else None)
    completed = source['status'] == 'completed' and all(
        c['status'] == 'completed' and all(e.get('status') == 'completed' for e in c['steps'])
        for c in source['cases'])
    result['all_event_call_intervals_within_budget'] = (
        all(event_passes) if completed and event_passes and None not in event_passes else None)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--target-fps', type=float, default=60)
    args = parser.parse_args()
    print(json.dumps(summarize(args.report, args.target_fps), indent=2))
