"""Check disabled tracing and distinguish repeats/skips from decoder delivery time."""
import importlib.util
import os
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--cc", default="cc")
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('video_trace', root/'scripts/analyze_video_acquires.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.analyze('ordinary log')['rows'] == 0
row = ('video-acquire: start_ns=1000000 end_ns=11000000 lock_ns=2000000 '
       'ready_ns=7000000 select_ns=9000000 acquire=4 pts_ns=60000000 slot=2 '
       'queued=1 skipped=3 repeated=0 eos=0 decoder=42 decode_ns=4000000 waits=1')
result = module.analyze(row + '\n' + row.replace('repeated=0', 'repeated=1').replace('skipped=3', 'skipped=0'))
assert result['rows'] == 2 and result['repeated_buffers'] == 1 and result['skipped_pictures'] == 3
r = result['slowest'][0]
assert (r['total_ms'], r['lock_ms'], r['decode_ms'], r['prepare_ms'], r['catchup_ms'], r['copy_ms']) == (10, 1, 4, 5, 2, 2)
def at(base, pts, repeated=0):
    return (f'video-acquire: start_ns={base} end_ns={base+10} lock_ns={base+1} '
            f'ready_ns={base+2} select_ns={base+3} acquire=1 pts_ns={pts} slot=0 '
            f'queued=1 skipped=0 repeated={repeated} eos=0 decoder=7 decode_ns=1 waits=0')

# Emission order is deliberately shuffled; repeated buffers do not count as deliveries.
cadence_log = '\n'.join([at(1_100_000_000, 17), at(1_000_000_000, 0),
                         at(1_200_000_000, 17, 1), at(2_000_000_000, 34)])
stream = module.analyze(cadence_log)['delivery_streams'][0]
assert stream['deliveries'] == 3 and stream['max_delivery_gap_ms'] == 900
assert stream['seconds_since_first_delivery'] == [
    {'second': 0, 'deliveries': 2, 'skipped': 0, 'repeated': 1},
    {'second': 1, 'deliveries': 1, 'skipped': 0, 'repeated': 0}]
window = module.analyze(cadence_log, 1_100_000_010, 1_200_000_010)
assert window['rows'] == 2 and window['delivery_streams'][0]['deliveries'] == 1
assert module.analyze(cadence_log, 3_000_000_000)['rows'] == 0
for bad in ('video-acquire: start_ns=1', row.replace('lock_ns=2000000', 'lock_ns=12000000')):
    try:
        module.analyze(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid timing accepted')
compiler = args.cc
if not compiler:
    raise SystemExit('SKIP: C compiler unavailable')
fixture = r'''
#include <stdint.h>
#include <assert.h>
#include <stdarg.h>
static int clocks, logs;
static int64_t hos_now_ns(void) { ++clocks; return 123; }
static void hos_log(const char *fmt, ...) { (void)fmt; ++logs; }
#include "video_acquire_trace.h"
int main(void) {
 VideoAcquireTrace t = video_acquire_trace_begin(0);
 video_acquire_trace_end(&t);
 assert(clocks == 0 && logs == 0);
 t = video_acquire_trace_begin(1);
 assert(clocks == 1 && t.start == 123 && t.slot == -1);
 t.end = 456;
 video_acquire_trace_end(&t);
 assert(clocks == 1 && logs == 1);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp)/'test.c'
    binary = Path(tmp)/('test.exe' if os.name == 'nt' else 'test')
    source.write_text(fixture)
    subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(root/'host'), str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('PASS: disabled trace clocks/logs, timing decomposition, repeats, skips and malformed records')
