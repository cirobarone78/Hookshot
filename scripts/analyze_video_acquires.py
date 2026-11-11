"""Summarize opt-in video delivery diagnostics; these are not display FPS."""
import argparse
import json
import re
import statistics
from pathlib import Path


def analyze(text, start_ns=None, end_ns=None):
    if start_ns is not None and end_ns is not None and end_ns < start_ns:
        raise ValueError('End precedes start')
    rows = []
    for line in text.splitlines():
        if 'video-acquire: ' not in line:
            continue
        row = {k: int(v) for k, v in re.findall(r'(\w+)=(-?\d+)', line.split('video-acquire: ', 1)[1])}
        required = {'start_ns', 'end_ns', 'lock_ns', 'ready_ns', 'select_ns',
                    'pts_ns', 'slot', 'skipped', 'repeated', 'decode_ns', 'decoder', 'waits'}
        if not required <= row.keys():
            raise ValueError('Incomplete video acquire trace row')
        if not row['start_ns'] <= row['lock_ns'] <= row['ready_ns'] <= row['select_ns'] <= row['end_ns']:
            raise ValueError('Nonmonotonic video acquire trace row')
        if start_ns is not None and row['end_ns'] < start_ns:
            continue
        if end_ns is not None and row['end_ns'] > end_ns:
            continue
        row['total_ms'] = (row['end_ns'] - row['start_ns']) / 1e6
        row['lock_ms'] = (row['lock_ns'] - row['start_ns']) / 1e6
        row['decode_ms'] = row['decode_ns'] / 1e6
        row['prepare_ms'] = (row['ready_ns'] - row['lock_ns']) / 1e6
        row['catchup_ms'] = (row['select_ns'] - row['ready_ns']) / 1e6
        row['copy_ms'] = (row['end_ns'] - row['select_ns']) / 1e6
        rows.append(row)
    decoders = {}
    for row in rows:
        decoders.setdefault(row['decoder'], []).append(row)
    streams = []
    for decoder, records in decoders.items():
        # Log emission happens after unlocking: concurrent callers may emit out of order.
        records.sort(key=lambda r: r['end_ns'])
        delivered = [r for r in records if r['slot'] >= 0 and not r['repeated']]
        if not delivered:
            continue
        origin = delivered[0]['end_ns']
        buckets = {}
        for row in records:
            second = (row['end_ns'] - origin) // 1_000_000_000
            if second < 0:
                continue
            bucket = buckets.setdefault(second, {'second': second, 'deliveries': 0,
                                                 'skipped': 0, 'repeated': 0})
            bucket['deliveries'] += int(row['slot'] >= 0 and not row['repeated'])
            bucket['skipped'] += row['skipped']
            bucket['repeated'] += row['repeated']
        gaps = [(b['end_ns'] - a['end_ns']) / 1e6 for a, b in zip(delivered, delivered[1:])]
        pts = [(b['pts_ns'] - a['pts_ns']) / 1e6 for a, b in zip(delivered, delivered[1:])]
        streams.append({'decoder': decoder, 'first_delivery_ns': origin, 'deliveries': len(delivered),
                        'max_delivery_gap_ms': max(gaps, default=None),
                        'median_delivery_gap_ms': statistics.median(gaps) if gaps else None,
                        'max_pts_step_ms': max(pts, default=None),
                        'same_pts_deliveries': sum(p == 0 for p in pts),
                        'backward_pts_steps': sum(p < 0 for p in pts),
                        'seconds_since_first_delivery': [buckets[s] for s in sorted(buckets)]})
    return {'rows': len(rows), 'repeated_buffers': sum(r['repeated'] for r in rows),
            'skipped_pictures': sum(r['skipped'] for r in rows),
            'no_free_slot': sum(r['slot'] < 0 for r in rows),
            'poll_waits': sum(r['waits'] for r in rows),
            'delivery_streams': streams,
            'slowest': sorted(rows, key=lambda r: r['total_ms'], reverse=True)[:30],
            'proof': 'Decoder delivery wall times only. Decode time overlaps prepare/catchup; do not add them. '
                     'PTS identifies decoded pictures, not the time they became visible. Buckets are delivery counts, '
                     'not displayed FPS; first/last buckets can be partial. Decoder addresses may be reused after destruction. '
                     'Trace is capped at 12000 calls per decoder.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--start-ns', type=int, help='Include calls ending at or after this monotonic timestamp')
    parser.add_argument('--end-ns', type=int, help='Include calls ending at or before this monotonic timestamp')
    args = parser.parse_args()
    print(json.dumps(analyze(args.log.read_text(errors='replace'), args.start_ns, args.end_ns), indent=2))
