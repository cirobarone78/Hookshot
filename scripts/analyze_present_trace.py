#!/usr/bin/env python3
"""Analyze every native present interval in an explicitly bounded scene segment.

These are host present-call timestamps, not GPU completion/display timestamps.
The scene boundaries and correct rendering must be verified separately.
"""
import argparse
import csv
import json
import math
from pathlib import Path


def analyze(path, first_frame, last_frame, target_fps=60):
    if (type(first_frame) is not int or type(last_frame) is not int or
            first_frame < 2 or last_frame < first_frame):
        raise ValueError('Use an inclusive frame range starting at frame 2 or later')
    if not math.isfinite(target_fps) or target_fps <= 0:
        raise ValueError('target_fps must be finite and positive')
    rows = []
    with Path(path).open(newline='') as stream:
        reader = csv.DictReader(stream)
        basic = ['frame', 'return_ns', 'interval_ns']
        phased = basic + ['present_begin_ns', 'renderer_begin_ns', 'renderer_end_ns', 'vcore_back_ns']
        if reader.fieldnames not in (basic, phased):
            raise ValueError('Unrecognized native present trace header')
        for row in reader:
            frame = int(row['frame'])
            if first_frame <= frame <= last_frame:
                rows.append((frame, int(row['return_ns']), int(row['interval_ns'])))
    if len(rows) != last_frame - first_frame + 1:
        raise ValueError('Scene range is missing frames (possibly an unflushed trace tail)')
    previous = rows[0][1] - rows[0][2]
    stamps = [previous]
    for expected, (frame, stamp, interval) in enumerate(rows, first_frame):
        if frame != expected or interval <= 0 or stamp - previous != interval:
            raise ValueError('Noncontiguous frames or inconsistent monotonic timestamps')
        stamps.append(stamp)
        previous = stamp
    intervals = sorted(row[2] for row in rows)
    total = sum(intervals)
    percentile = lambda p: intervals[max(0, math.ceil(len(intervals)*p)-1)] / 1e6
    # Sliding windows end on a frame and span at least one second, including the
    # full interval of a long stall rather than dropping it from the denominator.
    slowest = None
    right = 1
    for left in range(len(stamps)-1):
        right = max(right, left+1)
        while right < len(stamps) and stamps[right]-stamps[left] < 1_000_000_000:
            right += 1
        if right == len(stamps):
            break
        fps = (right-left)*1e9/(stamps[right]-stamps[left])
        if slowest is None or fps < slowest['fps']:
            slowest = dict(fps=fps, first_frame=first_frame+left, last_frame=first_frame+right-1,
                           seconds=(stamps[right]-stamps[left])/1e9)
    over = sum(value > 1e9/target_fps for value in intervals)
    return dict(first_frame=first_frame, last_frame=last_frame, frames=len(rows), seconds=total/1e9,
                mean_fps=len(rows)*1e9/total, p50_ms=percentile(.5), p95_ms=percentile(.95),
                p99_ms=percentile(.99), max_ms=intervals[-1]/1e6,
                target_fps=target_fps, over_budget_frames=over, over_20ms=sum(x>20e6 for x in intervals),
                over_33_333ms=sum(x>1e9/30 for x in intervals), over_50ms=sum(x>50e6 for x in intervals),
                slowest_one_second_window=slowest, every_frame_within_budget=over == 0,
                proof='native present-call intervals only; scene coverage and visual correctness require separate verification')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--first-frame', type=int, required=True)
    parser.add_argument('--last-frame', type=int, required=True)
    parser.add_argument('--target-fps', type=float, default=60)
    args = parser.parse_args()
    print(json.dumps(analyze(args.trace, args.first_frame, args.last_frame, args.target_fps), indent=2))
