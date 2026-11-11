#!/usr/bin/env python3
"""Bounded A-button pulses and periodic captures from a disposable analysis session.

Screenshots are complete, fresh renderer PNGs, selected at the requested cadence.
Their frame numbers and age are recorded; capture cadence cannot exceed the
renderer recording cadence. Input delivery and rendering progress are separate
from successful dialogue progression. Inspect the resulting images.
"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import time

PNG_END = b'\x00\x00\x00\x00IEND\xaeB`\x82'


def record(api, output, *, seconds=60, press_every=.75, capture_every=2,
           press_ms=80, stall_seconds=5):
    for name, value in [('seconds', seconds), ('press_every', press_every),
                        ('capture_every', capture_every), ('stall_seconds', stall_seconds)]:
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be finite and positive')
    if not 0 < seconds <= 3600 or type(press_ms) is not int or not 1 <= press_ms <= 1000:
        raise ValueError('Use at most 3600 seconds and a 1..1000 ms pulse')
    if press_every < press_ms / 1000 + .05:
        raise ValueError('Leave at least 50 ms between A pulses')
    if api.info.get('profile_kind') != 'analysis':
        raise RuntimeError('Dialogue automation requires a disposable analysis profile')
    initial = api.request('status')
    if initial.get('control') != 'exclusive':
        raise RuntimeError('Dialogue automation requires exclusive API control')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + seconds
    next_press, next_capture = started, started
    last_progress, last_frame = started, initial.get('presents')
    last_sequence = None
    captures, missed, presses = [], [], []
    seen = set()
    result = dict(session=str(api.session), started_at=time.time(), seconds=seconds,
                  press_every=press_every, press_ms=press_ms, capture_every=capture_every,
                  stall_seconds=stall_seconds, status='running', captures=captures,
                  missed_captures=missed, inputs=presses)
    manifest = output / 'manifest.json'
    error = None
    with (output / 'events.jsonl').open('w') as events:
        def event(kind, **fields):
            row = dict(event=kind, elapsed=time.monotonic()-started, **fields)
            events.write(json.dumps(row) + '\n')
            events.flush()
            return row
        try:
            while time.monotonic() < deadline:
                if not api.alive():
                    raise RuntimeError('Game process exited')
                state = api.request('status')
                if state.get('control') != 'exclusive':
                    raise RuntimeError('API control was handed away')
                now = time.monotonic()
                frame = state.get('presents')
                if frame != last_frame:
                    last_progress, last_frame = now, frame
                age = state.get('last_present_age_ms')
                if now-last_progress >= stall_seconds or (age is not None and age >= stall_seconds*1000):
                    raise TimeoutError('Native rendering stopped progressing')
                if now >= next_press and now < deadline:
                    ack = api.input(1, milliseconds=press_ms, timeout=min(1, deadline-now))
                    last_sequence = ack['sequence']
                    presses.append(event('input', button='A', milliseconds=press_ms,
                                         frame=frame, acknowledgement=ack))
                    next_press = time.monotonic() + press_every
                if now >= next_capture and time.monotonic() < deadline:
                    status = api.status()
                    source = status.get('latest_screenshot')
                    reason = 'no fresh complete renderer PNG'
                    if source and source not in seen:
                        path = Path(source).resolve()
                        if path.parent != (api.run / 'shots').resolve():
                            raise RuntimeError('Screenshot path is outside this analysis session')
                        try:
                            before = path.stat()
                            data = path.read_bytes()
                            after = path.stat()
                            identity = lambda st: (st.st_ino, st.st_size, st.st_mtime_ns)
                            age = time.time() - after.st_mtime
                            complete = (data.startswith(b'\x89PNG\r\n\x1a\n') and
                                        data.endswith(PNG_END))
                            fresh = (after.st_mtime >= result['started_at'] and
                                     0 <= age < stall_seconds)
                            if complete and fresh and identity(before) == identity(after):
                                target = output / f'{len(captures):05d}-{path.name}'
                                target.write_bytes(data)
                                seen.add(source)
                                captures.append(event('capture', file=target.name, source=str(path),
                                                      source_age_seconds=age,
                                                      status=status))
                                reason = None
                        except (FileNotFoundError, OSError):
                            # A PNG being written or rotated is not a new complete capture.
                            pass
                    if reason:
                        missed.append(event('capture_missed', reason=reason, status=status))
                    next_capture = time.monotonic() + capture_every
                time.sleep(max(0, min(.1, deadline-time.monotonic(),
                                      next_press-time.monotonic(), next_capture-time.monotonic())))
            result['status'] = 'completed'
        except BaseException as exc:
            error = exc
            result.update(status='aborted', error=f'{type(exc).__name__}: {exc}')
            event('aborted', error=result['error'])
        finally:
            # Cancel only our last sequence; never replace another client's newer input.
            if last_sequence is not None and api.alive():
                try:
                    result['input_cleanup'] = api.request(f'cancel {last_sequence}')
                except (OSError, RuntimeError) as exc:
                    result['input_cleanup_error'] = str(exc)
            result.update(elapsed=time.monotonic()-started, finished_at=time.time(),
                          manifest=str(manifest),
                          proof='input acknowledgements and fresh frames; inspect images for dialogue progression')
            manifest.write_text(json.dumps(result, indent=2) + '\n')
    if error is not None:
        raise error
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--press-every', type=float, default=.75)
    parser.add_argument('--capture-every', type=float, default=2)
    parser.add_argument('--press-ms', type=int, default=80)
    parser.add_argument('--stall-seconds', type=float, default=5)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from analysis_api import HookshotAPI
    api = HookshotAPI(args.session)
    output = args.output or api.run / datetime.now().strftime('dialogue-%Y%m%d-%H%M%S-%f')
    result = record(api, output, seconds=args.seconds, press_every=args.press_every,
                    capture_every=args.capture_every, press_ms=args.press_ms,
                    stall_seconds=args.stall_seconds)
    print(json.dumps({k: v for k, v in result.items() if k not in ('captures', 'inputs', 'missed_captures')}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        sys.exit(str(exc))
