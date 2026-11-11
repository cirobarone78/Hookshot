"""Export CPU renderer stages and native-present intervals as a Chrome/Perfetto trace.

This is a CPU timeline, not GPU execution or displayed FPS. Thread CPU is only
known for the whole stage; it is never prorated into a clipped frame. Coverage is
the union of instrumented wall intervals per thread, including waits. Coverage
across threads must not be added. Missing coverage does not prove idle time.
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def read_rows(path):
    with Path(path).open() as source:
        yield from csv.DictReader(source)


def merge_intervals(intervals):
    merged = []
    for start, stop in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(stop, merged[-1][1]))
        else:
            merged.append((start, stop))
    return merged


def union_ns(intervals):
    return sum(b-a for a,b in merge_intervals(intervals))


def export(stages, presents, first=None, last=None):
    frames = [r for r in read_rows(presents)
              if (first is None or int(r['frame']) >= first)
              and (last is None or int(r['frame']) <= last)]
    if not frames:
        raise ValueError('No native present intervals in requested range')
    windows = [(int(r['return_ns'])-int(r['interval_ns']), int(r['return_ns'])) for r in frames]
    if any(a >= b for a,b in windows) or any(windows[i][1] > windows[i+1][0] for i in range(len(windows)-1)):
        raise ValueError('Invalid or overlapping present intervals')
    lo, hi = windows[0][0], windows[-1][1]
    events = []
    ids = {}
    intervals = defaultdict(list)
    rows_read = 0
    row_limit = 1000000
    for row in read_rows(stages):
        rows_read += 1
        row_limit = int(row.get("trace_row_limit", 1000000))
        start, end, wall, cpu = (int(row[k]) for k in ('start_ns','end_ns','wall_ns','cpu_ns'))
        if end < start or wall != end-start or cpu < -1:
            raise ValueError('Malformed stage interval')
        if end <= lo or start >= hi:
            continue
        thread = row['thread']
        if thread not in ids:
            ids[thread] = len(ids)+1
            events.append({'ph':'M','pid':1,'tid':ids[thread], 'name':'thread_name',
                           'args':{'name':'Renderer thread '+thread}})
        a,b = max(lo,start),min(hi,end)
        intervals[thread].append((a,b))
        events.append({'ph':'X','pid':1,'tid':ids[thread], 'cat':row['operation'],
            'name':row['operation']+'/'+row['stage'], 'ts':(a-lo)/1000,'dur':(b-a)/1000,
            'args':{'submission_or_queue':row['submission'], 'whole_wall_ns':wall,
                    'whole_thread_cpu_ns':cpu if cpu>=0 else None,
                    'clipped':a!=start or b!=end}})
    events.append({'ph':'M','pid':1,'tid':0,'name':'thread_name','args':{'name':'Native present intervals (CPU)'}})
    intervals = {thread:merge_intervals(spans) for thread,spans in intervals.items()}
    report=[]
    for row,(a,b) in zip(frames,windows):
        events.append({'ph':'X','pid':1,'tid':0,'cat':'native_present',
            'name':'Frame '+row['frame'],'ts':(a-lo)/1000,'dur':(b-a)/1000})
        coverage={thread:union_ns((max(a,s),min(b,e)) for s,e in spans if e>a and s<b)
                  for thread,spans in intervals.items()}
        report.append({'frame':int(row['frame']),'interval_ns':b-a,
                       'instrumented_wall_ns_per_thread_not_additive':coverage})
    return {'traceEvents':events,'displayTimeUnit':'ms',
            'metadata':{'proof':__doc__.strip(),'origin_monotonic_ns':lo,
                        'trace_rows_read':rows_read,'trace_row_limit':row_limit,
                        'trace_row_limit_reached':rows_read>=row_limit,
                        'frames':report}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stages');parser.add_argument('presents')
    parser.add_argument('--first',type=int);parser.add_argument('--last',type=int)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    args.output.write_text(json.dumps(export(args.stages,args.presents,args.first,args.last))+'\n')


if __name__=='__main__':main()
