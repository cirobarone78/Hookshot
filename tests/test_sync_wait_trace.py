"""Exercise production event wait tracing without changing signal/auto-clear semantics."""
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
source = (root / 'host/nn_os_sync.c').read_text()
helpers = source[source.index('static int sync_wait_trace_ms('):source.index('static void event_clear(')]
wait = source[source.index('static int event_wait('):source.index('/* SignalEvent from host code')]
fixture = r'''
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <stdarg.h>
typedef unsigned long DWORD;
typedef long LONG;
typedef struct { uint64_t key; int signaled, autoclear, lk, cv; int64_t sig_ns, trace_signal_ns; DWORD trace_signal_tid; } Obj;
static int64_t now=1000000000;
static int clocks, logs, held;
static DWORD tid=7;
static Obj *waiting;
static int64_t logged_start, logged_end, logged_signal;
static unsigned long logged_tid;
static int logged_got;
static const char *hos_thread_name(void *self) { (void)self; return "main"; }
static void *hos_self(void) { return NULL; }
static int64_t hos_now_ns(void) { ++clocks; return now; }
static DWORD GetCurrentThreadId(void) { return tid; }
static LONG InterlockedIncrement(volatile LONG *p) { return ++*p; }
static void hos_log(const char *fmt, ...) {
 assert(!held); ++logs;
 va_list ap; va_start(ap,fmt);
 assert(va_arg(ap,unsigned long long)==42); assert(va_arg(ap,unsigned long)==7);
 logged_start=va_arg(ap,long long); logged_end=va_arg(ap,long long);
 logged_signal=va_arg(ap,long long); logged_tid=va_arg(ap,unsigned long);
 logged_got=va_arg(ap,int); va_end(ap);
}
static void AcquireSRWLockExclusive(int *p) { (void)p; assert(!held); held=1; }
static void ReleaseSRWLockExclusive(int *p) { (void)p; assert(held); held=0; }
static void WakeAllConditionVariable(int *p) { (void)p; }
static void poke_multiwait(Obj *o) { assert(o == waiting); }
static int wake_lat_on(void) { return 0; }
static void wake_lat_note(int a,int64_t b) { (void)a;(void)b; }
static void spin_until_set(Obj *o,int *p) { (void)o;(void)p; }
static int wait_until(Obj *o,int64_t deadline) { (void)o; now=deadline; return 0; }
#define INFINITE -1
static void hos_cv_sleep(int *,int *,int);
'''
fixture += helpers
fixture += r'''
static void hos_cv_sleep(int *cv,int *lk,int timeout) {
 (void)cv;(void)timeout; ReleaseSRWLockExclusive(lk);
 now+=25000000; tid=99; event_signal(waiting); tid=7;
 now+=3000000; AcquireSRWLockExclusive(lk);
}
'''
fixture += wait
fixture += r'''
int main(void) {
 Obj e={.key=42,.autoclear=1}; waiting=&e;
 e.signaled=1; assert(event_peek(&e) && !e.signaled); e.signaled=0;
 int enabled=getenv("HOS_SYNC_WAIT_TRACE_MS")!=NULL;
 int filtered=getenv("HOS_SYNC_WAIT_TRACE_THREAD")!=NULL;
 assert(event_wait(&e,0,0)==1 && !e.signaled);
 if (enabled && !filtered) {
  assert(logs==1 && logged_start==1000000000 && logged_end==1028000000);
  assert(logged_signal==1025000000 && logged_tid==99 && logged_got==1);
 } else assert(!logs);
 if (!enabled) assert(!clocks);
 int before=logs; assert(!event_wait(&e,0,1)); assert(logs==before);
 assert(!event_wait(&e,20000000,0));
 if (enabled && !filtered) assert(logs==before+1 && !logged_got);
 e.autoclear=0; e.signaled=1; assert(event_wait(&e,0,0) && e.signaled);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    folder = Path(tmp)
    (folder/'test.c').write_text(fixture)
    subprocess.run([args.cc,'-std=c11','-O2','-Wall','-Wextra','-Werror',str(folder/'test.c'),'-o',str(folder/'test.exe')],check=True)
    env = {k:v for k,v in os.environ.items() if not k.startswith('HOS_SYNC_WAIT_TRACE')}
    for extra in ({}, {'HOS_SYNC_WAIT_TRACE_MS':'20'}, {'HOS_SYNC_WAIT_TRACE_MS':'20','HOS_SYNC_WAIT_TRACE_THREAD':'other'}):
        subprocess.run([str(folder/'test.exe')],env={**env,**extra},check=True)
print('PASS: disabled clock path, filtering, signal correlation, timeout, auto/manual clear and unlocked logging')
