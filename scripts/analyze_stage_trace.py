"""Summarize opt-in renderer stage traces alongside native present intervals.

Wall-minus-thread-CPU includes scheduling/preemption as well as blocking. Rows
from different operations may nest or execute concurrently: never sum them into
a frame cost. CPU work is not GPU execution time. Diagnostic overhead is included.
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def rows_from(path):
    with Path(path).open() as source:
        yield from csv.DictReader(source)


def analyze(trace, presents, first=None, last=None):
    frames = [r for r in rows_from(presents)
              if (first is None or int(r['frame']) >= first)
              and (last is None or int(r['frame']) <= last)]
    if not frames:
        raise ValueError('No native present intervals in requested range')
    lo = int(frames[0]['return_ns']) - int(frames[0]['interval_ns'])
    hi = int(frames[-1]['return_ns'])
    slow = sorted(frames, key=lambda r: int(r['interval_ns']), reverse=True)[:10]
    overlaps = [[] for _ in slow]
    totals = defaultdict(lambda: {'calls': 0, 'wall_ns': 0, 'cpu_ns': 0,
                                  'cpu_known_calls': 0, 'max_wall_ns': 0,
                                  'wall_minus_cpu_ns': 0})
    selected = crossing = rows_read = 0
    row_limit = 1000000
    for r in rows_from(trace):
        rows_read += 1
        row_limit = int(r.get("trace_row_limit", 1000000))
        start, end, wall, cpu = (int(r[k]) for k in ('start_ns','end_ns','wall_ns','cpu_ns'))
        if end < start or wall != end-start or cpu < -1:
            raise ValueError('Malformed stage interval')
        if end <= lo or start >= hi:
            continue
        for i, f in enumerate(slow):
            fend, duration = int(f['return_ns']), int(f['interval_ns'])
            overlap = max(0, min(end,fend)-max(start,fend-duration))
            if overlap:
                overlaps[i].append({'operation': r['operation'], 'submission': int(r['submission']),
                    'thread': r['thread'], 'stage': r['stage'], 'overlap_ms': overlap/1e6,
                    'whole_stage_wall_ms': wall/1e6, 'whole_stage_cpu_ms': cpu/1e6 if cpu>=0 else None})
        if start < lo or end > hi:
            crossing += 1
            continue
        selected += 1
        memory_flags = int(r['source_memory_flags']) if 'source_memory_flags' in r else None
        t = totals[(r['operation'], r['stage'], memory_flags)]
        t['calls'] += 1; t['wall_ns'] += wall
        t['max_wall_ns'] = max(t['max_wall_ns'], wall)
        if cpu >= 0:
            t['cpu_known_calls'] += 1; t['cpu_ns'] += cpu
            t['wall_minus_cpu_ns'] += max(0,wall-cpu)
    return {'proof': __doc__.strip(), 'trace_rows_read': rows_read,
        'trace_row_limit': row_limit, 'trace_row_limit_reached': rows_read >= row_limit,
        'first_frame': int(frames[0]['frame']), 'last_frame': int(frames[-1]['frame']),
        'complete_stage_rows': selected, 'boundary_crossing_rows_excluded_from_totals': crossing,
        'stages': [{'operation': op, 'stage': stage, 'source_memory_flags': flags, **values}
                   for (op,stage,flags),values in sorted(totals.items())],
        'slow_intervals': [{'frame': int(f['frame']), 'interval_ms': int(f['interval_ns'])/1e6,
            'overlapping_stages_not_additive': sorted(rows,key=lambda r:r['overlap_ms'],reverse=True)[:20]}
            for f,rows in zip(slow,overlaps)]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace'); parser.add_argument('presents')
    parser.add_argument('--first',type=int); parser.add_argument('--last',type=int)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    text=json.dumps(analyze(args.trace,args.presents,args.first,args.last),indent=2)
    if args.output: args.output.write_text(text+'\n')
    else: print(text)


if __name__=='__main__': main()
