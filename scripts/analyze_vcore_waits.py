#!/usr/bin/env python3
"""Join opt-in vcore ownership snapshots with native present intervals."""
import argparse
import bisect
import csv
import json
from pathlib import Path
import re

WAIT = re.compile(r'vcore-wait: at_ns=(\d+) waiter_tid=(\d+) waited_ns=(\d+) total_ns=(\d+) held=(\d+) mask=([0-9a-f]+)')
OWNER = re.compile(r'vcore-owner: at_ns=(\d+) waiter_tid=(\d+) core=(\d+) owner_tid=(\d+) priority=(-?\d+) kick=(\d+) name=(.*)$')


def analyze(log, trace):
    waits, owners = {}, {}
    with Path(log).open() as stream:
        for line in stream:
            m = WAIT.search(line)
            if m:
                at, tid, elapsed, total, held = map(int, m.groups()[:5])
                waits[at, tid] = dict(at_ns=at, waiter_tid=tid, waited_ns=elapsed,
                                      total_ns=total, held_after_wait=held, mask=int(m[6], 16))
            m = OWNER.search(line)
            if m:
                at, tid, core, owner, priority, kick = map(int, m.groups()[:6])
                owners.setdefault((at, tid), []).append(dict(core=core, tid=owner, priority=priority,
                                                             kick=kick, name=m[7]))
    with Path(trace).open() as stream:
        rows = [{k: int(v) for k, v in r.items()} for r in csv.DictReader(stream)]
    returns = [r['return_ns'] for r in rows]
    if any(b <= a for a, b in zip(returns, returns[1:])):
        raise ValueError('Present timestamps must be strictly increasing')
    result = []
    for key, wait in sorted(waits.items()):
        wait['owners_at_snapshot'] = sorted(owners.get(key, []), key=lambda r: r['core'])
        wait['owners_complete'] = {r['core'] for r in wait['owners_at_snapshot']} == {k for k in range(8) if wait['mask'] >> k & 1}
        # An interval is (return - interval, return]; exact endpoints belong to the ending interval.
        index = bisect.bisect_left(returns, wait['at_ns'])
        interval = rows[index] if index < len(rows) else None
        wait['present_interval'] = interval if interval and interval['interval_ns'] > 0 and interval['return_ns'] - interval['interval_ns'] < wait['at_ns'] else None
        result.append(wait)
    return dict(waits=result, proof='Ownership is a single scheduler-lock snapshot, not ownership throughout the wait. '
                'Native present intervals are not GPU/display time. Output is deferred until the wait ends. '
                'Trace is capped at 256 snapshots; absence of a row does not prove absence of waits.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('trace', type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.log, args.trace), indent=2))
