"""Signal metadata is correlated only within the measured wait, with frame clipping."""
import importlib.util
from pathlib import Path
import tempfile

spec = importlib.util.spec_from_file_location('waits', Path(__file__).resolve().parents[1]/'scripts/analyze_sync_waits.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
lines = '\n'.join([
 'prefix sync-wait: kind=event key=0x2a waiter_tid=7 start_ns=100 end_ns=200 signal_ns=170 signal_tid=9 got=1 name=Main Thread',
 'sync-wait: kind=event key=0x2a waiter_tid=7 start_ns=200 end_ns=300 signal_ns=170 signal_tid=9 got=0 name=Main Thread',
 'sync-wait: kind=event key=0x2a waiter_tid=7 start_ns=300 end_ns=400 signal_ns=170 signal_tid=9 got=1 name=Main Thread'])
rows = m.parse_waits(lines)
assert len(rows)==3 and rows[0]['post_signal_ms']==30/1e6
assert rows[1]['post_signal_ms'] is None and rows[2]['post_signal_ms'] is None
assert rows[0]['key']==42 and rows[0]['name']=='Main Thread'
with tempfile.TemporaryDirectory() as folder:
    p=Path(folder); (p/'log').write_text(lines)
    (p/'frames').write_text('frame,return_ns,interval_ns\n1,250,100\n2,400,150\n')
    r=m.analyze(p/'log',p/'frames',first=1,last=1)
    assert len(r['selected_waits'])==2 and not r['process_cap_reached']
    assert [x['overlap_ms'] for x in r['slow_frames'][0]['waits_not_additive']]==[50/1e6,50/1e6]
try:
    m.parse_waits(lines.replace('end_ns=200','end_ns=99'))
    raise AssertionError('Bad interval accepted')
except ValueError: pass
print('PASS: signal correlation, timeout/stale signal, frame clipping and invalid intervals')
