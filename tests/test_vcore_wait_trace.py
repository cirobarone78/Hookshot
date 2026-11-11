"""Exercise the production slow-wait snapshot with authored threads; no game needed."""
import os
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--cc", default="cc")
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]
source = (root / 'host/hos_thread.c').read_text()
start = source.index('typedef struct {\n    int64_t at_ns, waited_ns;')
fragment = source[start:source.index('static void vc_acquire(', start)]
prefix = r'''
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <stdarg.h>
typedef unsigned long DWORD;
typedef struct { DWORD host_tid; int priority, vc_kick; char name[48]; } HosThread;
static HosThread *vc_owner[8];
static int vc_cores(void) { return 6; }
static unsigned vc_allowed(HosThread *t) { (void)t; return 0x25; }
static int writes;
static void hos_log(const char *fmt, ...) { (void)fmt; ++writes; }
'''
fixture = r'''
int main(void) {
 HosThread waiter = {.host_tid=42,.name="presentation"}, owner = {.host_tid=71,.priority=16,.vc_kick=2,.name="worker"};
 vc_owner[0]=&owner; vc_owner[1]=&owner; vc_owner[5]=&owner;
 VcWaitTrace r={0};
 vc_trace_capture(&r,&waiter,100000000,19000000);
 assert(!r.at_ns); vc_trace_emit(&r,20000000,0); assert(!writes);
 vc_trace_capture(&r,&waiter,101000000,20000000);
 if (!getenv("HOS_VCORE_TRACE_MS") || (getenv("HOS_VCORE_TRACE_THREAD") && strcmp(getenv("HOS_VCORE_TRACE_THREAD"),"presentation"))) { assert(!r.at_ns); return 0; }
 assert(r.at_ns==101000000 && r.waited_ns==20000000 && r.waiter==42 && r.mask==0x25);
 assert(r.owner[0].tid==71 && r.owner[0].priority==16 && r.owner[0].kick==2);
 assert(!r.owner[1].tid && !r.owner[2].tid && r.owner[5].tid==71);
 owner.host_tid=99; strcpy(owner.name,"changed");
 vc_trace_capture(&r,&waiter,200000000,40000000);
 assert(r.at_ns==101000000 && r.owner[0].tid==71 && !strcmp(r.owner[0].name,"worker"));
 vc_trace_emit(&r,250000000,0); assert(writes==4);
 for (int i=1;i<256;++i) { VcWaitTrace next={0}; vc_trace_capture(&next,&waiter,300000000,30000000); assert(next.at_ns); }
 VcWaitTrace capped={0}; vc_trace_capture(&capped,&waiter,400000000,30000000); assert(!capped.at_ns);
}
'''
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    (folder / 'test.c').write_text(prefix + fragment + fixture)
    subprocess.run([args.cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', str(folder/'test.c'), '-o', str(folder/'test.exe')], check=True)
    env = dict(os.environ)
    env.pop('HOS_VCORE_TRACE_MS', None)
    env.pop('HOS_VCORE_TRACE_THREAD', None)
    subprocess.run([str(folder/'test.exe')], env=env, check=True)
    subprocess.run([str(folder/'test.exe')], env={**env, 'HOS_VCORE_TRACE_MS':'20'}, check=True)
    subprocess.run([str(folder/'test.exe')], env={**env, 'HOS_VCORE_TRACE_MS':'20', 'HOS_VCORE_TRACE_THREAD':'other'}, check=True)
    subprocess.run([str(folder/'test.exe')], env={**env, 'HOS_VCORE_TRACE_MS':'20', 'HOS_VCORE_TRACE_THREAD':'presentation'}, check=True)
print('PASS: disabled, threshold, allowed owners, copied snapshot, deferred emission and process cap')
