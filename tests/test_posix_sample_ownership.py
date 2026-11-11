"""Compile the real sampler handoff with deterministic signal completion schedules."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

RUN_ALL_ARGS = ["--cc", "gcc"]
RUN_ALL_SKIP = {"windows": "Linux sampler signals and nonlocal-jump assembly"}

ROOT = Path(__file__).resolve().parents[1]


parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--cc", default="cc")
args, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0], *remaining]

@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which(args.cc), 'Linux C compiler required')
class SampleOwnershipTests(unittest.TestCase):
    def test_delayed_handler_cannot_complete_a_new_request(self):
        source = (ROOT / 'host/posix/prof.c').read_text()
        globals = source[source.index('enum { DEPTH ='):source.index('typedef struct { uintptr_t *pcs;')]
        start = source.index('static int sample_one(')
        function = source[start:source.index('\n}\n', start)+3]
        prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <limits.h>
#include <pthread.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <stdarg.h>
static long fake_syscall(long number, ...);
static int fake_yield(void);
static int64_t hos_now_ns(void);
#define syscall fake_syscall
#define sched_yield fake_yield
#define SAMPLE_SIG 1
'''
        harness = r'''
static int mode, requests, current_tid;
static int64_t now;
static int64_t hos_now_ns(void) {
    now += 10000000;
    if (mode == 4 && now >= 70000000) {
        sample_pcs[0] = (uintptr_t)current_tid; sample_n = 1;
        sample_finish(current_tid);
        mode = 5;
    }
    return now;
}
static long fake_syscall(long number, ...) {
    (void)number;
    va_list ap; va_start(ap, number); (void)va_arg(ap, int);
    current_tid = va_arg(ap, int); va_end(ap);
    requests++;
    assert(pthread_mutex_trylock(&sample_mu) != 0);
    if (mode == 3) return -1;
    if (mode != 2) assert(sample_claim(current_tid));
    if (mode == 0) {
        sample_pcs[0] = (uintptr_t)current_tid; sample_n = 1;
        sample_finish(current_tid);
    }
    return 0;
}
static int fake_yield(void) { return 0; }
int main(void) {
    uintptr_t pcs[1] = {0};
    mode = 1; /* Handler claimed the buffer, then stalled past timeout. */
    assert(sample_one(101, pcs, 1) == 0);
    assert(sample_state == SAMPLE_ABANDONED);
    assert(sample_one(202, pcs, 1) == 0);
    assert(requests == 1); /* No second signal while old handler owns storage. */
    sample_pcs[0] = 0xaaa; sample_n = 1; sample_finish(101);
    assert(sample_state == 0);
    mode = 0;
    assert(sample_one(202, pcs, 1) == 1 && pcs[0] == 202);
    mode = 2; /* Timeout before the handler claims; its later signal is ignored. */
    assert(sample_one(303, pcs, 1) == 0);
    assert(!sample_claim(303));
    __atomic_store_n(&sample_state, 404, __ATOMIC_RELEASE);
    assert(!sample_claim(303)); /* Old thread cannot claim a new thread's request. */
    assert(sample_claim(404)); sample_finish(404);
    assert(sample_state == SAMPLE_DONE);
    __atomic_store_n(&sample_state, 0, __ATOMIC_RELEASE);
    mode = 3;
    assert(sample_one(505, pcs, 1) == -1 && sample_state == 0);
    mode = 0;
    assert(sample_one(606, pcs, 1) == 1 && pcs[0] == 606);
    mode = 4; now = 0;
    assert(sample_one(707, pcs, 1) == 1 && pcs[0] == 707);
    assert(sample_state == 0);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            c = Path(directory) / 'sample.c'; exe = c.with_suffix('')
            c.write_text(prefix + globals + function + harness)
            subprocess.run([args.cc, '-std=c11', '-O2', '-pthread', str(c), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=10)


if __name__ == '__main__': unittest.main()
