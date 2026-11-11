"""Correlate opt-in event waits with native present intervals.

The last signal is correlation evidence, not a proven unique producer. Post-signal
elapsed time includes lock reacquisition and virtual-core/OS scheduling. Missing
rows do not prove absence of waits: threshold, thread filtering and the 4096-row
process cap apply. Native present intervals are not displayed/GPU frame times.
"""
import argparse
import csv
import json
import re
from pathlib import Path

PATTERN = re.compile(r'sync-wait: kind=event key=(\S+) waiter_tid=(\d+) start_ns=(\d+) end_ns=(\d+) signal_ns=(\d+) signal_tid=(\d+) got=([01]) name=(.*)')


def parse_waits(text):
    rows = []
    for line in text.splitlines():
        match = PATTERN.search(line)
        if not match:
            continue
        key, waiter, start, end, signal, producer, got, name = match.groups()
        start, end, signal = int(start), int(end), int(signal)
        if end < start or signal > end:
            raise ValueError('Invalid event wait timestamps')
        rows.append(dict(key=int(key, 0), waiter_tid=int(waiter), start_ns=start,
                         end_ns=end, last_signal_ns=signal, last_signal_tid=int(producer),
                         got=bool(int(got)), name=name, wall_ms=(end-start)/1e6,
                         post_signal_ms=(end-signal)/1e6 if int(got) and start <= signal <= end else None))
    return rows


def analyze(log, presents, first=None, last=None):
    rows = parse_waits(Path(log).read_text(errors='replace'))
    with Path(presents).open() as source:
        frames = [r for r in csv.DictReader(source)
                  if (first is None or int(r['frame']) >= first)
                  and (last is None or int(r['frame']) <= last)]
    if not frames:
        raise ValueError('No present intervals in range')
    lo = int(frames[0]['return_ns'])-int(frames[0]['interval_ns'])
    hi = int(frames[-1]['return_ns'])
    selected = [r for r in rows if r['end_ns'] > lo and r['start_ns'] < hi]
    slow = []
    for frame in sorted(frames, key=lambda f: int(f['interval_ns']), reverse=True)[:10]:
        end, duration = int(frame['return_ns']), int(frame['interval_ns'])
        overlap = [{**r, 'overlap_ms': (min(end,r['end_ns'])-max(end-duration,r['start_ns']))/1e6}
                   for r in selected if r['end_ns'] > end-duration and r['start_ns'] < end]
        slow.append(dict(frame=int(frame['frame']), interval_ms=duration/1e6,
                         waits_not_additive=overlap))
    return dict(proof=__doc__.strip(), total_logged_waits=len(rows), process_cap_reached=len(rows)>=4096,
                selected_waits=selected, slow_frames=slow)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log'); parser.add_argument('presents')
    parser.add_argument('--first', type=int); parser.add_argument('--last', type=int)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(analyze(args.log,args.presents,args.first,args.last),indent=2)+'\n'
    if args.output: args.output.write_text(result)
    else: print(result, end='')


if __name__ == '__main__': main()
